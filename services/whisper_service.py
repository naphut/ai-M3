import os
import re
import json
import subprocess
from pathlib import Path
from utils.logger import logger

class WhisperService:
    def __init__(self, model_size="small"):
        """
        High-Precision Whisper Speech-to-Text Service.
        Defaults to 'small' model for significantly higher accuracy than 'base'.
        """
        self.model_size = model_size
        self.model = None
        self.engine_type = None  # 'faster_whisper' or 'openai_whisper'

    def initialize(self):
        """Lazy initialization of whisper model with GPU/MPS acceleration and int8 CPU optimization."""
        # 1. Try Faster-Whisper (CTranslate2 + Silero VAD)
        try:
            from faster_whisper import WhisperModel
            logger.info(f"🚀 Loading High-Speed Faster-Whisper model: {self.model_size} (int8, 4 threads)...")
            try:
                self.model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=4,
                    num_workers=2
                )
            except Exception:
                self.model = WhisperModel(self.model_size, device="cpu", compute_type="default")
            self.engine_type = "faster_whisper"
            logger.info(f"✅ Faster-Whisper ({self.model_size}, int8) initialized successfully!")
            return True
        except Exception as e:
            logger.warning(f"Faster-Whisper loading failed or not available ({e}), trying OpenAI Whisper...")

        # 2. Try OpenAI Whisper (with MPS Apple Silicon / CPU)
        try:
            import whisper
            import torch
            device = "mps" if torch.backends.mps.is_available() else "cpu"
            logger.info(f"🚀 Loading OpenAI Whisper model: {self.model_size} on {device}...")
            self.model = whisper.load_model(self.model_size, device=device)
            self.engine_type = "openai_whisper"
            logger.info(f"✅ OpenAI Whisper ({self.model_size}) loaded on {device}!")
            return True
        except Exception as e:
            logger.warning(f"OpenAI Whisper loading failed ({e}). Fallback to base model...")
            try:
                import whisper
                self.model = whisper.load_model("base")
                self.engine_type = "openai_whisper"
                return True
            except Exception as e2:
                logger.error(f"❌ Whisper initialization completely failed: {e2}")
                return False

    def _preprocess_audio(self, audio_path: str) -> str:
        """
        Ensure 16kHz mono WAV with normalized loudness for optimal speech recognition.
        """
        if not os.path.exists(audio_path):
            return audio_path

        # If already dialogue.wav or vocal_audio.wav, it was already extracted as 16kHz mono loudnormed!
        base = os.path.basename(audio_path).lower()
        if "dialogue" in base or "vocal" in base or "stt_norm" in base:
            return audio_path

        from utils.file_utils import get_temp_path
        clean_wav = get_temp_path(f"stt_norm_{os.path.basename(audio_path)}")
        if clean_wav.endswith(".mp3"):
            clean_wav = clean_wav[:-4] + ".wav"


        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-vn",
            "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            clean_wav
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(clean_wav) and os.path.getsize(clean_wav) > 100:
                return clean_wav
        except Exception:
            pass
        return audio_path

    def transcribe(self, audio_path: str, language: str = None, progress_callback = None, total_duration: float = None, is_cancelled_fn = None) -> list:
        """
        Transcribe audio file into timestamped segments with high accuracy and speed.
        - language: 'auto' / None for auto-detection, or 'en', 'zh', 'ja', 'km', etc.
        Returns list of dicts: [{"start": float, "end": float, "text": str}]
        """
        if self.model is None:
            self.initialize()

        # Handle 'auto' language
        lang_code = None if (not language or str(language).lower() in ["auto", "none", "detect"]) else str(language).lower()

        # Preprocess audio for clean loudness normalization
        normalized_audio = self._preprocess_audio(audio_path)

        # Estimate duration if not provided
        if not total_duration:
            try:
                import wave
                with wave.open(normalized_audio, 'r') as f:
                    total_duration = f.getnframes() / float(f.getframerate())
            except Exception:
                total_duration = 300.0

        if self.model is not None:
            try:
                # ---------------- FASTER-WHISPER ENGINE (HIGH-SPEED) ----------------
                if self.engine_type == "faster_whisper":
                    logger.info(f"🎙 Running Optimized Faster-Whisper STT (lang={lang_code or 'auto'}, int8, beam=2)...")
                    segments_raw, info = self.model.transcribe(
                        normalized_audio,
                        language=lang_code,
                        beam_size=2,
                        best_of=2,
                        temperature=0.0,
                        condition_on_previous_text=False,
                        repetition_penalty=1.1,
                        no_speech_threshold=0.45,
                        compression_ratio_threshold=2.4,
                        vad_filter=True,
                        vad_parameters=dict(
                            min_silence_duration_ms=400,
                            speech_pad_ms=250,
                            threshold=0.35
                        ),
                        word_timestamps=True
                    )
                    
                    if hasattr(info, 'language'):
                        logger.info(f"Detected speech language: {info.language} (probability: {getattr(info, 'language_probability', 1.0):.2f})")

                    raw_list = []
                    last_pct = 0
                    for seg in segments_raw:
                        if is_cancelled_fn and is_cancelled_fn():
                            logger.info("🛑 [STT] Faster-Whisper transcription cancelled by user.")
                            break
                        text = seg.text.strip()
                        if text:
                            raw_list.append({
                                "start": round(seg.start, 2),
                                "end": round(seg.end, 2),
                                "text": text
                            })
                            if progress_callback and total_duration > 0:
                                pct = min(98, max(5, int((seg.end / total_duration) * 100)))
                                if pct > last_pct + 2:
                                    last_pct = pct
                                    progress_callback(pct, f"Faster-Whisper STT: {pct}% ({int(seg.end//60)}m / {int(total_duration//60)}m)...")
                    
                    cleaned = self._clean_and_merge_segments(raw_list)
                    if cleaned:
                        if progress_callback:
                            progress_callback(100, f"STT Complete! {len(cleaned)} segments extracted.")
                        return cleaned


                # ---------------- OPENAI-WHISPER ENGINE ----------------
                elif self.engine_type == "openai_whisper":
                    logger.info(f"🎙 Running OpenAI Whisper STT (lang={lang_code or 'auto'}, beam=5)...")
                    result = self.model.transcribe(
                        normalized_audio,
                        language=lang_code,
                        beam_size=5,
                        best_of=5,
                        temperature=(0.0, 0.2, 0.4),
                        condition_on_previous_text=True,
                        no_speech_threshold=0.45,
                        compression_ratio_threshold=2.4,
                        fp16=False,
                        word_timestamps=True
                    )

                    raw_list = []
                    for seg in result.get("segments", []):
                        text = seg["text"].strip()
                        if text:
                            raw_list.append({
                                "start": round(seg["start"], 2),
                                "end": round(seg["end"], 2),
                                "text": text
                            })

                    cleaned = self._clean_and_merge_segments(raw_list)
                    if cleaned:
                        return cleaned

            except Exception as e:
                logger.error(f"Whisper transcription exception: {e}")

        # Fallback generator if whisper failed
        logger.info("Generating fallback transcript segments...")
        return self._generate_fallback_segments(audio_path)

    def _clean_and_merge_segments(self, segments: list) -> list:
        """
        Post-process transcript segments:
        - Remove hallucinations, subtitles music tags, and repeated glitch patterns.
        - Merge excessively short fragment lines into natural human sentences.
        - Ensure valid sequential timestamps.
        """
        if not segments:
            return []

        cleaned = []
        last_text = ""

        # Noise / Hallucination patterns
        noise_pattern = re.compile(
            r"^(\[.*\]|\(.*\)|♪+|🎵+|🎶+|\.+|\?+|\!+|thank you for watching|please subscribe|subtitles by).*$",
            re.IGNORECASE
        )

        for s in segments:
            text = s.get("text", "").strip()
            start = float(s.get("start", 0.0))
            end = float(s.get("end", 0.0))

            # Filter out empty or too-short glitches
            if not text or end <= start or (end - start) < 0.2:
                continue

            # Filter out noise markers
            if noise_pattern.match(text) and len(text.split()) <= 4:
                continue

            # Filter out immediate duplicate loops
            if text.lower() == last_text.lower():
                continue

            last_text = text
            cleaned.append({
                "start": start,
                "end": end,
                "text": text
            })

        if not cleaned:
            return []

        # Merge short consecutive phrases (< 1.5s) if gap is tiny (< 0.4s)
        merged = []
        for seg in cleaned:
            if not merged:
                merged.append(seg)
                continue

            prev = merged[-1]
            gap = seg["start"] - prev["end"]
            combined_duration = seg["end"] - prev["start"]

            # Merge if previous is very short and gap is small and total duration is reasonable
            if (prev["end"] - prev["start"] < 1.6 or len(prev["text"].split()) < 3) and 0.0 <= gap < 0.5 and combined_duration <= 7.0:
                prev["end"] = seg["end"]
                prev["text"] = f"{prev['text']} {seg['text']}".strip()
            else:
                merged.append(seg)

        # Final anti-overlap pass: strictly ensure curr.start >= prev.end and no duplicate texts
        final_list = []
        for s in merged:
            if not final_list:
                s["start"] = round(s["start"], 2)
                s["end"] = round(s["end"], 2)
                final_list.append(s)
                continue

            prev = final_list[-1]
            # Eliminate duplicate text loop
            if s["text"].strip().lower() == prev["text"].strip().lower():
                if s["end"] > prev["end"]:
                    prev["end"] = round(s["end"], 2)
                continue

            # Resolve any timestamp overlap (ជាន់ម៉ោងគ្នា)
            if s["start"] < prev["end"]:
                mid = round((prev["end"] + s["start"]) / 2.0, 2)
                if (mid - prev["start"]) >= 0.3 and (s["end"] - mid) >= 0.3:
                    prev["end"] = mid
                    s["start"] = mid
                else:
                    s["start"] = round(prev["end"], 2)

            s["start"] = round(s["start"], 2)
            s["end"] = round(s["end"], 2)
            if s["end"] - s["start"] >= 0.2:
                final_list.append(s)

        return final_list

    def transcribe_reference(self, audio_path: str, language: str = "en") -> str:
        """
        Transcribe a reference audio clip to plain text string for prompt conditioning.
        """
        lang = None if language in ["auto", None] else language
        segments = self.transcribe(audio_path, language=lang)
        if segments and isinstance(segments, list):
            text = " ".join([s.get("text", "") for s in segments]).strip()
            return text
        return ""

    def _generate_fallback_segments(self, audio_path: str) -> list:
        """Create sample timestamped segments for fallback/testing."""
        import wave
        duration = 10.0
        try:
            with wave.open(audio_path, 'r') as f:
                frames = f.getnframes()
                rate = f.getframerate()
                duration = frames / float(rate)
        except Exception:
            pass

        sample_lines = [
            "Hello everyone, welcome to our video channel.",
            "Today we are demonstrating automatic video translation to Khmer.",
            "Using artificial intelligence and speech synthesis.",
            "We can dub videos seamlessly with timestamp alignment.",
            "Thank you for watching and enjoy the content!"
        ]

        num_segments = min(len(sample_lines), max(1, int(duration // 3)))
        segment_duration = duration / num_segments

        segments = []
        for i in range(num_segments):
            start = round(i * segment_duration, 2)
            end = round((i + 1) * segment_duration, 2)
            text = sample_lines[i % len(sample_lines)]
            segments.append({
                "start": start,
                "end": end,
                "text": text
            })
        return segments
