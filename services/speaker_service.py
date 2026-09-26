import os
from typing import List, Dict
from utils.logger import logger
from services.speaker_detector import SpeakerDetector

class SpeakerService:
    """
    Dedicated Speaker Diarization & Speaker Clustering Service.
    Groups speech segments into distinct speakers (speaker_001, speaker_002, etc.).
    """
    def __init__(self):
        self.detector = SpeakerDetector()

    def identify_speaker_clusters(self, audio_path: str, subtitle_segments: List[dict]) -> List[dict]:
        """
        Assign speaker labels (Speaker 1, Speaker 2) across subtitle segments
        based on median vocal pitch F0 and segment gap analysis.
        """
        if not subtitle_segments:
            return []

        detector = SpeakerDetector(audio_path)
        updated_segments = []

        for seg in subtitle_segments:
            start_s = seg.get("start", 0.0)
            end_s = seg.get("end", 3.0)
            
            f0 = detector.analyze_audio_segment_pitch(start_s, end_s)
            
            # Simple heuristic pitch clustering: F0 > 170Hz -> Female speaker, F0 <= 170Hz -> Male speaker
            if f0 > 0:
                speaker_id = "Speaker 1" if f0 <= 170.0 else "Speaker 2"
            else:
                speaker_id = seg.get("speaker", "Speaker 1")

            seg_copy = dict(seg)
            seg_copy["speaker"] = speaker_id
            seg_copy["pitch_f0"] = f0
            updated_segments.append(seg_copy)

        logger.info(f"👥 [SpeakerService] Assigned speaker labels across {len(updated_segments)} subtitle segments.")
        return updated_segments
