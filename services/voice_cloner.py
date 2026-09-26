import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from utils.logger import logger
from utils.file_utils import get_temp_path
from services.audio_extractor import AudioExtractor
from services.vad_service import VADService
from services.voice_cleaner import VoiceCleaner
from services.whisper_service import WhisperService
from services.voxcpm_service import VoxCPM2Runner

class VoiceClonerPipeline:
    """
    Unified Zero-Shot Voice Cloning Pipeline:
    🎬 INPUT VIDEO 
         ↓
    🎵 FFmpeg Extract Audio 
         ↓
    📻 WAV 16kHz / Mono / PCM16
         ↓
    🧹 Clean + VAD
         ↓
    🎙️ Best Reference Speech (10–20s)
         ↓
    📝 Whisper STT (Reference Text) + 🧠 VoxCPM2 (Voice Conditioning)
         ↓
    📝 Khmer Text
         ↓
    🧠 VoxCPM2 Generator
         ↓
    🔊 Cloned Khmer WAV / MP3
    """
    def __init__(self):
        self.extractor = AudioExtractor()
        self.vad = VADService()
        self.cleaner = VoiceCleaner()
        self.whisper = WhisperService()
        self.generator = VoxCPM2Runner()

    def process_reference_audio(self, input_file_path: str, name: str = "RefVoice", language: str = "auto") -> Tuple[Optional[str], str]:
        """
        Step 1 to Step 6:
        1. Extract Audio from Video (FFmpeg)
        2. Format to WAV 16kHz Mono PCM16
        3. Clean Audio & Run VAD
        4. Extract Best Speech Segment (5-20 seconds)
        5. Transcribe Reference Text via Whisper (Auto Language Detect)
        Returns (clean_reference_wav_path, reference_text)
        """
        if not input_file_path or not os.path.exists(input_file_path):
            logger.error(f"❌ Input file not found: {input_file_path}")
            return None, ""

        logger.info(f"🎬 [VoiceCloner] Step 1: Processing input reference '{os.path.basename(input_file_path)}'...")
        
        # 1 & 2. Extract / Convert to 16kHz PCM WAV
        ext = os.path.splitext(input_file_path)[1].lower()
        if ext in ['.mp4', '.mov', '.mkv', '.avi', '.webm']:
            extracted_wav = get_temp_path(f"clone_extract_{name}.wav")
            audio_wav = self.extractor.extract_audio(input_file_path, extracted_wav)
        else:
            extracted_wav = get_temp_path(f"clone_extract_{name}.wav")
            cmd = ["ffmpeg", "-y", "-i", input_file_path, "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", extracted_wav]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            audio_wav = extracted_wav if os.path.exists(extracted_wav) else input_file_path

        # 3 & 4. Clean + VAD (Best 5-20s Speech Segment)
        logger.info("🧹 [VoiceCloner] Step 2: VAD Speech Isolation & Voice Cleaning...")
        best_seg = self.vad.extract_best_speech_segment(audio_wav, min_duration=3.0, max_duration=20.0)
        
        cleaned_wav = get_temp_path(f"clone_clean_{name}.wav")
        if best_seg:
            start_s, end_s = best_seg
            seg_wav = get_temp_path(f"clone_seg_{name}.wav")
            cmd_cut = ["ffmpeg", "-y", "-ss", str(start_s), "-to", str(end_s), "-i", audio_wav, "-c", "copy", seg_wav]
            subprocess.run(cmd_cut, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ref_source = seg_wav if os.path.exists(seg_wav) else audio_wav
        else:
            ref_source = audio_wav

        self.cleaner.clean_reference_audio(ref_source, cleaned_wav)
        final_ref_wav = cleaned_wav if os.path.exists(cleaned_wav) else ref_source

        # 5. Whisper STT Reference Text Transcription with Auto Language Detect
        logger.info("📝 [VoiceCloner] Step 3: Whisper STT Reference Text Extraction...")
        ref_text = self.whisper.transcribe_reference(final_ref_wav, language=language)
        logger.info(f"✅ [VoiceCloner] Reference Ready: '{os.path.basename(final_ref_wav)}' | Text: '{ref_text[:50]}...'")

        return final_ref_wav, ref_text

    def clone_from_segment(self, video_path: str, start_sec: float, end_sec: float, character_name: str) -> Optional[Dict[str, Any]]:
        """
        1-Click Clone from a specific video subtitle segment:
        Clips the audio slice, runs cleaning, detects pitch F0 & gender, transcribes text, and saves character profile.
        """
        if not video_path or not os.path.exists(video_path):
            return None
        
        name = character_name.strip() or f"Speaker_{int(start_sec)}s"
        slice_wav = get_temp_path(f"seg_slice_{abs(hash(name))}.wav")
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_sec:.3f}",
            "-to", f"{end_sec:.3f}",
            "-i", video_path,
            "-vn", "-ar", "16000", "-ac", "1",
            slice_wav
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if not os.path.exists(slice_wav):
            return None
        
        clean_ref, ref_text = self.process_reference_audio(slice_wav, name=name, language="auto")
        if not clean_ref:
            return None
        
        # Analyze pitch
        from services.speaker_detector import SpeakerDetector
        detector = SpeakerDetector(clean_ref)
        f0 = detector.analyze_audio_segment_pitch(0.0, end_sec - start_sec)
        gender = "male" if 0 < f0 <= 160 else "female"
        
        # Create character profile
        from services.character_voice_manager import CharacterVoiceManager
        manager = CharacterVoiceManager()
        prompt_desc = f"A {gender} voice speaking with natural inflection and clear articulation."
        profile = manager.create_character(
            name=name,
            voice_prompt=prompt_desc,
            reference_audio=clean_ref,
            reference_text=ref_text,
            gender=gender
        )
        
        return {
            "name": name,
            "gender": gender,
            "f0": f0,
            "reference_audio": clean_ref,
            "reference_text": ref_text,
            "profile": profile
        }

    def clone_voice(self, khmer_text: str, reference_wav_path: str, reference_text: str, output_wav_path: str, convert_to_mp3: bool = True) -> Optional[str]:
        """
        Step 7 & 8:
        Execute VoxCPM2 Neural Generator conditioned on reference audio + reference text -> Cloned Khmer WAV & MP3.
        """
        if not reference_wav_path or not os.path.exists(reference_wav_path):
            logger.error(f"❌ Reference audio missing: {reference_wav_path}")
            return None

        logger.info(f"🧠 [VoiceCloner] Step 4: VoxCPM2 Neural Voice Synthesis (Mode C: Neural + F0 + EQ) for text: '{khmer_text[:30]}...'")
        success = self.generator.generate(
            text=khmer_text,
            prompt_audio=reference_wav_path,
            prompt_text=reference_text,
            output_path=output_wav_path,
            mode="full_c"
        )

        if not success or not os.path.exists(output_wav_path):
            logger.error("❌ VoxCPM2 synthesis failed!")
            return None

        logger.info(f"🔊 [VoiceCloner] Generated Cloned Khmer WAV: {output_wav_path}")

        # Optional MP3 Export
        if convert_to_mp3:
            mp3_path = output_wav_path.replace(".wav", ".mp3")
            cmd_mp3 = ["ffmpeg", "-y", "-i", output_wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", mp3_path]
            subprocess.run(cmd_mp3, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if os.path.exists(mp3_path):
                logger.info(f"🎵 [VoiceCloner] Exported MP3: {mp3_path}")

        return output_wav_path
