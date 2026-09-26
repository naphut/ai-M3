import re
import os
import hashlib
import concurrent.futures
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Callable
from services.voxcpm_service import VoxCPMService, VOICE_PRESETS, EMOTION_PRESETS, STYLE_PRESETS
from core.models import Segment
from utils.file_utils import get_temp_path
from utils.logger import logger


class BaseTTSEngine(ABC):
    """Abstract Base Class for Text-to-Speech Engines."""
    @abstractmethod
    def synthesize(self, text: str, output_path: str, voice_name: str, target_duration: Optional[float] = None, emotion: str = "😐 Neutral", style: str = "Normal") -> bool:
        """Synthesize text into WAV at output_path."""
        pass


class VoxCPMEngine(BaseTTSEngine):
    """Engine using VoxCPM2 Zero-Shot Neural Voice Cloning & Stock Presets with Emotion/Style."""
    def synthesize(self, text: str, output_path: str, voice_name: str, target_duration: Optional[float] = None, emotion: str = "😐 Neutral", style: str = "Normal") -> bool:
        service = VoxCPMService(voice_name=voice_name)
        return service.synthesize(text, output_path, target_duration=target_duration, emotion=emotion, style=style)


class EdgeTTSEngine(BaseTTSEngine):
    """Engine using Microsoft Neural Edge-TTS directly with Emotion/Style."""
    def synthesize(self, text: str, output_path: str, voice_name: str, target_duration: Optional[float] = None, emotion: str = "😐 Neutral", style: str = "Normal") -> bool:
        service = VoxCPMService(voice_name=voice_name)
        return service.synthesize(text, output_path, target_duration=target_duration, emotion=emotion, style=style)


class TextToSpeech:
    """
    High-level Production TTS Orchestrator supporting:
    - Smart incremental caching via Content-Hash (only regenerates modified lines)
    - Multi-speaker voice assignments & Emotion/Style DSP modulation
    - 1-Click single line preview synthesis
    - Parallel batch synthesis via ThreadPoolExecutor worker pool (max_workers=3)
    """
    def __init__(self, voice_name: str = "Khmer Male - Piseth", engine_type: str = "voxcpm"):
        self.default_voice = voice_name
        self.engine_type = engine_type
        if engine_type == "edge":
            self.engine: BaseTTSEngine = EdgeTTSEngine()
        else:
            self.engine = VoxCPMEngine()

    def generate_segment_audio(self, segment: dict, index: int, force_regenerate: bool = False) -> Optional[str]:
        """
        Synthesize audio for a single translated Khmer segment with Emotion and Style modulation.
        Checks smart content-hash cache first to avoid re-generating untouched segments.
        """
        raw_text = segment.get("khmer_text") or segment.get("original_text") or segment.get("text", "")
        # Clean any leading speaker tags like [ក្មេង], [ប្រុស], [ស្រី], (ក្មេង), etc. so TTS never speaks brackets/tags
        text = re.sub(r'^\s*(?:\[|\()?\s*(ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)\s*(?:\]|\))?\s*[:：\-–—]?\s*', '', raw_text, flags=re.IGNORECASE).strip()
        if text.startswith('[') and ']' in text[:15]:
            text = re.sub(r'^\s*\[[^\]]+\]\s*', '', text).strip()
        if not text:
            text = raw_text

        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start + 2.5))
        target_duration = max(0.5, round(end - start, 2))
        
        # Use voice from segment if available, otherwise infer from persona or gender
        voice_name = segment.get("voice_id") or segment.get("voice")
        persona = segment.get("persona", "")
        gender = (segment.get("gender") or "").lower()

        from core.models import PERSONA_DEFAULT_VOICE
        if not voice_name or voice_name not in VOICE_PRESETS or (voice_name == self.default_voice and (persona or gender)):
            if persona in PERSONA_DEFAULT_VOICE:
                voice_name = PERSONA_DEFAULT_VOICE[persona]
            elif gender == "female":
                voice_name = "Khmer Female - Sreymom"
            elif gender == "child":
                voice_name = "Khmer Child - Boy (Vannak)"
            elif voice_name not in VOICE_PRESETS:
                voice_name = self.default_voice

        emotion = segment.get("emotion") or "😐 Neutral"
        style = segment.get("speaking_style") or segment.get("style") or "Normal"

        # Content hash for smart incremental caching
        hash_seed = f"{text}|{voice_name}|{emotion}|{style}|{target_duration}"
        cache_hash = hashlib.md5(hash_seed.encode("utf-8")).hexdigest()[:16]
        cached_wav = get_temp_path(f"tts_cache_{cache_hash}.wav")

        # ⚡ Cache Hit: reuse existing audio without calling network!
        if not force_regenerate and os.path.exists(cached_wav) and os.path.getsize(cached_wav) > 1000:
            logger.debug(f"⚡ [TTS Cache Hit] Seg {index+1}: Using cached voice ({cache_hash})")
            segment["tts_audio"] = cached_wav
            segment["audio_hash"] = cache_hash
            return cached_wav

        logger.info(f"🎙️ [TTS Gen] Seg {index+1} [{start:.2f}s -> {end:.2f}s] ({voice_name} | {emotion} | {style}): '{text[:30]}...'")
        
        success = self.engine.synthesize(
            text=text,
            output_path=cached_wav,
            voice_name=voice_name,
            target_duration=target_duration,
            emotion=emotion,
            style=style
        )
        if success and os.path.exists(cached_wav) and os.path.getsize(cached_wav) > 0:
            segment["tts_audio"] = cached_wav
            segment["audio_hash"] = cache_hash
            return cached_wav
        return None

    def synthesize_single_line(self, segment: dict, index: int = 0) -> Optional[str]:
        """Synthesize a single line immediately with force_regenerate for 1️⃣ Line Preview."""
        return self.generate_segment_audio(segment, index, force_regenerate=True)

    def generate_all_segments(
        self,
        segments: List[dict],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        max_workers: int = 3,
        is_cancelled_fn: Optional[Callable[[], bool]] = None
    ) -> List[Optional[str]]:
        """
        Synthesize audio for all segments in parallel using a worker pool.
        Takes advantage of smart caching so only dirty/modified segments are synthesized.
        """
        total = len(segments)
        if total == 0:
            return []

        results: List[Optional[str]] = [None] * total
        completed_count = 0

        logger.info(f"🚀 Starting parallel TTS synthesis for {total} segments (workers={max_workers})...")

        def _worker_task(idx: int, seg: dict):
            if is_cancelled_fn and is_cancelled_fn():
                return idx, None
            wav_path = self.generate_segment_audio(seg, idx, force_regenerate=False)
            return idx, wav_path

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_worker_task, i, seg): i
                for i, seg in enumerate(segments)
            }

            for future in concurrent.futures.as_completed(future_to_idx):
                if is_cancelled_fn and is_cancelled_fn():
                    logger.warning("TTS parallel synthesis cancelled by user.")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    idx, wav_path = future.result()
                    results[idx] = wav_path
                except Exception as e:
                    logger.error(f"Error synthesizing segment: {e}")

                completed_count += 1
                if progress_callback:
                    progress_callback(completed_count, total, f"Segment {completed_count}/{total}")

        return results
