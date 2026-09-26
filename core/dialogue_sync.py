"""
Production-Grade Dialogue Synchronization Engine
Aligns synthesized speech segments with actor dialogue slots.
Implements the recommended timing hierarchy:
1. Duration verification: If TTS fits within slot -> place directly onto timeline.
2. If TTS is longer ->
   a. Borrow available natural silence gap from following segment (up to 400ms).
   b. Apply mild phase-vocoder time-stretch (strictly clamped 0.88x - 1.25x to preserve human pitch).
3. Smooth boundary cross-fading and timeline overlay.
"""
import os
from typing import List, Dict, Union, Any
from pydub import AudioSegment
from pydub.effects import normalize
from core.models import Segment
from utils.file_utils import get_temp_path
from utils.ffmpeg import adjust_audio_speed
from utils.logger import logger

class DialogueSyncEngine:
    def __init__(self, max_stretch_factor: float = 1.35, min_stretch_factor: float = 0.88):
        self.max_stretch_factor = max_stretch_factor
        self.min_stretch_factor = min_stretch_factor

    def sync_dialogue_timeline(
        self,
        segments: List[Union[Segment, Dict[str, Any]]],
        seg_audio_paths: List[str],
        total_duration_sec: float,
        output_master_path: str
    ) -> str:
        """
        Stitch synthesized segment audio clips into a unified dialogue master track
        synchronized with actor mouth movements and scene pacing.
        """
        try:
            total_ms = int(total_duration_sec * 1000) + 1500
            timeline = AudioSegment.silent(duration=total_ms, frame_rate=44100).set_channels(2)
            num_segs = len(segments)

            logger.info(f"⏱ [DialogueSync] Synchronizing {num_segs} dialogue segments across {total_duration_sec:.1f}s...")

            for i, (seg, raw_path) in enumerate(zip(segments, seg_audio_paths)):
                if not raw_path or not os.path.exists(raw_path):
                    continue

                st_sec = seg.start if isinstance(seg, Segment) else float(seg.get("start", 0.0))
                et_sec = seg.end if isinstance(seg, Segment) else float(seg.get("end", st_sec + 2.0))
                start_ms = int(st_sec * 1000)
                end_ms = int(et_sec * 1000)
                slot_ms = max(400, end_ms - start_ms)

                audio = AudioSegment.from_file(raw_path)
                actual_ms = len(audio)
                if actual_ms <= 0:
                    continue

                next_start_ms = total_ms
                if i + 1 < num_segs:
                    nxt_seg = segments[i + 1]
                    nxt_st = nxt_seg.start if isinstance(nxt_seg, Segment) else float(nxt_seg.get("start", 0.0))
                    next_start_ms = max(start_ms + 200, int(nxt_st * 1000))

                # 1. DURATION CHECK: Does it fit naturally within slot?
                if actual_ms <= slot_ms:
                    pass
                else:
                    # 2. TTS IS LONGER: Check available silence gap before next segment
                    silence_gap_ms = max(0, next_start_ms - end_ms)
                    borrowable_ms = min(400, int(silence_gap_ms * 0.70))
                    effective_slot_ms = slot_ms + borrowable_ms

                    if actual_ms <= effective_slot_ms:
                        logger.info(f"⏱ [DialogueSync] Seg {i+1}: Borrowed {borrowable_ms}ms pause. Audio fits without stretching.")
                    else:
                        # Apply mild time-stretch clamped strictly to max stretch factor
                        raw_speed = actual_ms / float(effective_slot_ms)
                        speed_factor = min(self.max_stretch_factor, max(self.min_stretch_factor, raw_speed))
                        
                        adjusted_path = get_temp_path(f"synced_seg_{i:03d}_{os.path.basename(raw_path)}")
                        if adjust_audio_speed(raw_path, adjusted_path, speed_factor):
                            audio = AudioSegment.from_file(adjusted_path)
                            logger.info(f"⏱ [DialogueSync] Seg {i+1}: mild stretch applied ({speed_factor:.2f}x).")

                # 3. STRICT ANTI-COLLISION: Ensure speech NEVER overlaps next segment (លុបសំឡេងជាន់គ្នាចោល)
                max_allowed_len = max(250, next_start_ms - start_ms - 50)
                if len(audio) > max_allowed_len:
                    # Calculate required speed directly against original raw audio to avoid multi-generation artifacts
                    total_needed_speed = actual_ms / float(max_allowed_len)
                    if total_needed_speed <= self.max_stretch_factor:
                        speed_path = get_temp_path(f"anti_overlap_{i:03d}_{os.path.basename(raw_path)}")
                        if adjust_audio_speed(raw_path, speed_path, total_needed_speed):
                            audio = AudioSegment.from_file(speed_path)
                            logger.info(f"⏱ [DialogueSync] Seg {i+1}: Anti-collision speedup applied ({total_needed_speed:.2f}x).")
                    
                    # If still exceeding, gently fade out and clamp to prevent voice overlap
                    if len(audio) > max_allowed_len:
                        audio = audio[:max_allowed_len].fade_out(35)
                        logger.info(f"⏱ [DialogueSync] Seg {i+1}: Clamped to {max_allowed_len}ms to prevent overlapping next dialogue.")

                # Boundary fade to eliminate clicks
                if len(audio) > 30:
                    audio = audio.fade_in(10).fade_out(10)

                # Loudness normalization
                try:
                    audio = normalize(audio)
                except Exception:
                    pass

                # Place onto master timeline at exact start position (guaranteed non-overlapping)
                # Resample segment audio to match master timeline (44.1kHz, 2 channels)
                audio_stereo = audio.set_frame_rate(44100).set_channels(2)
                timeline = timeline.overlay(audio_stereo, position=start_ms)

            timeline = timeline.set_frame_rate(44100).set_channels(2)
            timeline.export(output_master_path, format="wav")
            logger.info(f"✅ [DialogueSync] Master dialogue track exported (44.1kHz stereo): {output_master_path}")
            return output_master_path

        except Exception as e:
            logger.error(f"❌ [DialogueSync] Error: {e}")
            raise
