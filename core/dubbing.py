import os
import time
from qt_compat import QThread, Signal
from core.video_processor import VideoProcessor
from core.transcriber import Transcriber
from core.translator import Translator
from core.tts import TextToSpeech
from core.audio_processor import AudioProcessor
from utils.file_utils import get_output_path, get_temp_path, clean_temp_directory
from utils.logger import setup_logger

class PipelineStep:
    EXTRACT_AUDIO = "Extracting Audio"
    STT = "Speech to Text (Whisper)"
    TRANSLATION = "Translating to Khmer"
    TTS = "Generating Khmer Voice (VoxCPM2)"
    AUDIO_SYNC = "Syncing & Stitching Audio"
    MERGE_VIDEO = "Combining Video & Audio"
    APPLY_EFFECTS = "Applying Video Effects"
    COMPLETED = "Done"

class DubbingWorker(QThread):
    progress_changed = Signal(int, str)
    segments_ready = Signal(list)
    log_emitted = Signal(str)
    pipeline_finished = Signal(str)
    pipeline_error = Signal(str)

    def __init__(
        self,
        video_path: str,
        output_path: str = None,
        source_lang: str = "auto",
        target_lang: str = "km",
        whisper_model: str = "small",
        voice_name: str = "VoxCPM2-Khmer",
        api_key: str = None,
        background_volume: float = 0.30,
        pre_translated_segments: list = None,
        skip_transcription: bool = True,
        effects_config: dict = None
    ):
        super().__init__()
        self.setStackSize(8 * 1024 * 1024)
        self.video_path = video_path
        self.output_path = output_path or get_output_path(f"khmer_{os.path.basename(video_path)}")
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.whisper_model = whisper_model
        self.voice_name = voice_name
        self.api_key = api_key
        self.background_volume = background_volume
        self.pre_translated_segments = pre_translated_segments
        self.skip_transcription = skip_transcription
        self.effects_config = effects_config
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def log(self, message: str):
        self.log_emitted.emit(message)

    def run(self):
        try:
            self.log("🚀 Starting Khmer Video Dubbing Pipeline...")
            self.progress_changed.emit(5, PipelineStep.EXTRACT_AUDIO)

            if self._is_cancelled: return
            video_proc = VideoProcessor(self.video_path)
            total_duration = video_proc.info.get("duration", 10.0)
            self.log(f"📹 Video file loaded. Duration: {total_duration:.2f} seconds.")

            # Professional Voice & Music Separation
            # Professional Voice & Music Separation
            self.log("🎵 Separating audio: Clean Dialogue (for STT) + Background Music (to preserve)...")
            from services.audio_separator import AudioSeparationService
            sep_service = AudioSeparationService()
            sep_result = sep_service.extract_and_separate(self.video_path)
            vocal_wav = sep_result.get("dialogue_audio") or sep_result.get("vocal_audio")
            self.orig_audio = sep_result.get("original_audio")
            self.music_wav = sep_result.get("background_audio") or sep_result.get("music_audio")

            if self.pre_translated_segments:
                self.log("📝 Using provided translated segments for dubbing...")
                segments = self.pre_translated_segments
            else:
                self.progress_changed.emit(20, PipelineStep.STT)

                if self._is_cancelled: return
                self.log("🌐 Running Dedicated Gemini STT (VAD + gemini-3.5-transcribe)...")
                from services.stt_service import STTService
                stt_service = STTService(api_key=self.api_key)
                
                def _stt_cb(pct, msg):
                    self.progress_changed.emit(20 + int(pct * 0.20), f"STT: {msg}")
                    self.log(f"⚡ {msg}")

                stt_segments = stt_service.transcribe(vocal_wav, source_lang=self.source_lang, progress_callback=_stt_cb)
                
                if self._is_cancelled: return
                self.progress_changed.emit(45, PipelineStep.TRANSLATION)
                self.log("🌐 Running Contextual Gemini Translation (gemini-3.8-flash) with duration constraints...")
                from services.translation_service import TranslationService
                trans_service = TranslationService(api_key=self.api_key)
                segments = trans_service.translate_segments(stt_segments, source_lang=self.source_lang, target_lang=self.target_lang)

                # Automatic Speaker Diarization / Gender Voice Assignment
                try:
                    self.log("👥 Identifying speakers & assigning appropriate voices...")
                    for seg in segments:
                        if not seg.get("voice"):
                            g = (seg.get("gender") or "").lower()
                            spk = str(seg.get("character") or seg.get("speaker_id") or seg.get("speaker", "")).lower()
                            if g == "female" or "ស្រី" in spk or "female" in spk:
                                seg["voice"] = "Khmer Female - Sreymom"
                            elif g == "child" or "ក្មេង" in spk or "child" in spk:
                                seg["voice"] = "Khmer Child - Boy (Vannak)"
                            else:
                                seg["voice"] = "Khmer Male - Piseth"
                except Exception as spk_err:
                    self.log(f"Speaker voice assignment notice: {spk_err}")

            # Ensure every segment (including pre-translated) has voice assigned
            for seg in segments:
                if not seg.get("voice"):
                    g = (seg.get("gender") or "").lower()
                    spk = str(seg.get("character") or seg.get("speaker_id") or seg.get("speaker", "")).lower()
                    if g == "female" or "ស្រី" in spk or "female" in spk:
                        seg["voice"] = "Khmer Female - Sreymom"
                    elif g == "child" or "ក្មេង" in spk or "child" in spk:
                        seg["voice"] = "Khmer Child - Boy (Vannak)"
                    else:
                        seg["voice"] = "Khmer Male - Piseth"

            self.segments_ready.emit(segments)
            self.progress_changed.emit(55, PipelineStep.TTS)

            if self._is_cancelled: return
            self.log(f"🔊 Synthesizing Khmer voices in parallel (Workers=3)...")
            tts_engine = TextToSpeech(voice_name=self.voice_name)
            
            num_segments = len(segments)
            def _tts_progress(completed, total, info):
                pct = 55 + int(25 * (completed / float(max(1, total))))
                self.progress_changed.emit(pct, f"{PipelineStep.TTS} ({completed}/{total})")

            raw_audio_paths = tts_engine.generate_all_segments(
                segments,
                progress_callback=_tts_progress,
                max_workers=3,
                is_cancelled_fn=lambda: self._is_cancelled
            )

            self.progress_changed.emit(82, PipelineStep.AUDIO_SYNC)

            if self._is_cancelled: return
            self.log("⏱ Synchronizing dialogue timeline with DialogueSyncEngine...")
            from core.dialogue_sync import DialogueSyncEngine
            sync_engine = DialogueSyncEngine()
            master_khmer_wav = sync_engine.sync_dialogue_timeline(
                segments=segments,
                seg_audio_paths=raw_audio_paths,
                total_duration_sec=total_duration,
                output_master_path=get_temp_path("master_khmer_voice.wav")
            )
            
            effects_output = None
            if self.effects_config:
                blur_enabled = bool(self.effects_config.get("blur", {}).get("enabled", False) and self.effects_config.get("blur", {}).get("rect"))
                text_config = self.effects_config.get("text_overlay", {})
                text_enabled = bool(text_config.get("text", "").strip()) and bool(text_config.get("enabled", False))
                
                logo_config = self.effects_config.get("logo", {})
                logo_path = logo_config.get("path")
                logo_enabled = bool(logo_path and os.path.exists(str(logo_path))) and bool(logo_config.get("enabled", False))
                
                burn_sub_config = self.effects_config.get("burn_subtitle", {})
                has_segments = bool(self.effects_config.get("segments"))
                burn_sub_enabled = has_segments and bool(burn_sub_config.get("enabled", False))
                
                apply_needed = blur_enabled or text_enabled or logo_enabled or burn_sub_enabled
                
                self.log(f"🔍 Video Effects export configuration check: Blur={blur_enabled}, Text={text_enabled}, Logo={logo_enabled}, BurnSubtitle={burn_sub_enabled}")
                
                if apply_needed:
                    self.progress_changed.emit(90, PipelineStep.APPLY_EFFECTS)
                    self.log("🎨 Rendering video effects (Blur, Text, Logo, Burn Subtitle) into exported video frames...")
                    effects_output = get_temp_path("effects_video.mp4")
                    ok = video_proc.apply_effects_to_video(self.effects_config, effects_output)
                    if not ok or not os.path.exists(effects_output):
                        self.log("⚠️ Video effects rendering failed, fallback to original video")
                        effects_output = self.video_path
                    else:
                        self.log("✅ All video effects (Blur, Text, Logo, Burn Subtitle) rendered successfully into exported video!")
            
            self.progress_changed.emit(92, PipelineStep.MERGE_VIDEO)

            if self._is_cancelled: return
            self.log("🎬 Multiplexing final video stream with Khmer dubbed audio...")
            
            video_for_merge = effects_output if effects_output and os.path.exists(effects_output) else self.video_path
            temp_video_proc = VideoProcessor(video_for_merge)
            
            music_track = getattr(self, "music_wav", None)
            if self.background_volume > 0.0 and segments:
                base_orig = getattr(self, "orig_audio", None)
                if base_orig and os.path.exists(base_orig):
                    try:
                        self.log("🎶 Cleansing background track: Silencing original foreign speech on all dialogue intervals...")
                        from services.audio_separator import create_clean_background_track
                        from utils.file_utils import get_temp_path
                        export_bg_cleaned = get_temp_path("export_bg_cleaned.wav")
                        create_clean_background_track(
                            orig_audio_path=base_orig,
                            segments=segments,
                            output_bgm_path=export_bg_cleaned,
                            bgm_volume=self.background_volume,
                            duck_speech_db=-45.0
                        )
                        music_track = export_bg_cleaned
                        self.log("✅ Original speech silenced; background music & sound effects preserved!")
                    except Exception as e_bg:
                        self.log(f"Notice cleaning background: {e_bg}")

            success = temp_video_proc.merge_dubbed_audio(
                dubbed_audio_path=master_khmer_wav,
                output_video_path=self.output_path,
                music_audio_path=music_track,
                background_volume=self.background_volume
            )

            if success and os.path.exists(self.output_path):
                self.progress_changed.emit(100, PipelineStep.COMPLETED)
                self.log(f"🎉 SUCCESS! Final Khmer video created: {self.output_path}")
                self.pipeline_finished.emit(self.output_path)
            else:
                self.pipeline_error.emit("Failed to create final video output with FFmpeg.")

        except Exception as e:
            self.log(f"❌ Error in dubbing worker pipeline: {e}")
            self.pipeline_error.emit(str(e))
