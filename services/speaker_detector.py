import os
import wave
import numpy as np
from typing import List, Dict
from utils.logger import logger

class SpeakerDetector:
    """
    Advanced Speaker Diarization & Profiling Engine for AI Video Dubbing.
    """
    def __init__(self, audio_wav_path: str = None):
        self.audio_wav_path = audio_wav_path

    def analyze_audio_segment_pitch(self, start_sec: float, end_sec: float) -> float:
        """Estimate fundamental pitch frequency using sliding-window median pitch detection."""
        if not self.audio_wav_path or not os.path.exists(self.audio_wav_path):
            return 0.0

        try:
            with wave.open(self.audio_wav_path, 'rb') as wf:
                framerate = wf.getframerate()
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                nframes = wf.getnframes()
                
                start_frame = max(0, int(start_sec * framerate))
                end_frame = min(nframes, int(end_sec * framerate))
                num_frames = max(512, end_frame - start_frame)
                
                wf.setpos(start_frame)
                raw_bytes = wf.readframes(num_frames)

                if not raw_bytes or len(raw_bytes) < 100:
                    return 0.0

                dtype = np.int16 if sampwidth == 2 else np.int8
                samples = np.frombuffer(raw_bytes, dtype=dtype)

                if nchannels > 1:
                    samples = samples[::nchannels]

                if len(samples) < 512:
                    return 0.0

                samples = samples.astype(np.float32) / 32768.0
                samples = samples - np.mean(samples)

                # Sliding window frame analysis (100ms windows, 50ms hop)
                win_len = int(framerate * 0.100)
                hop_len = int(framerate * 0.050)
                min_lag = int(framerate / 400) # Max 400Hz
                max_lag = int(framerate / 65)  # Min 65Hz

                pitches = []
                for i in range(0, len(samples) - win_len, hop_len):
                    w = samples[i : i + win_len]
                    if np.std(w) < 0.01: # Skip silent frames
                        continue

                    w_clean = w - np.mean(w)
                    corr = np.correlate(w_clean, w_clean, mode='full')
                    corr = corr[len(corr)//2:]

                    if max_lag >= len(corr):
                        m_lag = len(corr) - 1
                    else:
                        m_lag = max_lag

                    if min_lag >= m_lag:
                        continue

                    peak_idx = np.argmax(corr[min_lag:m_lag]) + min_lag
                    if peak_idx > 0:
                        f0 = framerate / float(peak_idx)
                        if 65.0 <= f0 <= 400.0:
                            pitches.append(f0)

                if not pitches:
                    return 0.0

                # Return median pitch across voiced frames
                median_f0 = float(np.median(pitches))
                logger.info(f"🎤 Isolated Vocal Median Pitch F0: {median_f0:.1f}Hz from {len(pitches)} voiced frames")
                return median_f0

        except Exception as e:
            logger.debug(f"Audio pitch extraction exception: {e}")
            return 0.0

    def classify_text_speaker(self, khmer_text: str, original_text: str) -> dict:
        """Analyze text semantics for voice profile guidance."""
        combined = f"{original_text} {khmer_text}".lower()

        child_kw = ['boy', 'girl', 'child', 'kid', 'son', 'daughter', 'baby', 'school', 'vannak', 'sreyka', 'ក្មេង', 'កូន']
        elder_kw = ['grandfather', 'grandmother', 'grandpa', 'grandma', 'old', 'elder', 'ta', 'yeay', 'លោកតា', 'យាយ']
        female_kw = ['woman', 'female', 'lady', 'she', 'her', 'wife', 'mom', 'mother', 'sister', 'mrs', 'sreymom', 'ស្រី']
        male_kw = ['man', 'male', 'guy', 'he', 'his', 'husband', 'dad', 'father', 'brother', 'mr', 'piseth', 'ប្រុស']

        return {
            "child": sum(1 for kw in child_kw if kw in combined),
            "elder": sum(1 for kw in elder_kw if kw in combined),
            "female": sum(1 for kw in female_kw if kw in combined),
            "male": sum(1 for kw in male_kw if kw in combined)
        }

    def diarize_and_profile_segments(self, segments: List[Dict]) -> List[Dict]:
        """Perform Speaker Diarization & Profiling."""
        speaker_profiles = {}
        processed_segments = []
        voice_pool = [
            "Khmer Female - Sreymom",
            "Khmer Male - Piseth",
            "Khmer Child - Boy (Vannak)",
            "Khmer Child - Girl (Sreyka)",
            "Khmer Elder - Male (Grandfather)",
            "Khmer Elder - Female (Grandmother)"
        ]
        next_pool_idx = 0

        for i, seg in enumerate(segments):
            st = seg.get("start", i * 3.0)
            et = seg.get("end", (i + 1) * 3.0)
            orig_text = seg.get("original_text", seg.get("text", ""))
            khmer_text = seg.get("khmer_text", "")

            spk_id = seg.get("speaker", "")
            clean_khmer = khmer_text

            if ':' in khmer_text:
                parts = khmer_text.split(':', 1)
                if len(parts) == 2 and 0 < len(parts[0].strip()) < 20:
                    spk_id = parts[0].strip()
                    clean_khmer = parts[1].strip()
            elif ':' in orig_text:
                parts = orig_text.split(':', 1)
                if len(parts) == 2 and 0 < len(parts[0].strip()) < 20:
                    spk_id = parts[0].strip()

            if not spk_id:
                spk_id = f"Speaker {(i % 2) + 1}"

            if spk_id not in speaker_profiles:
                pitch_f0 = self.analyze_audio_segment_pitch(st, et)
                text_scores = self.classify_text_speaker(clean_khmer, orig_text)

                name_lower = spk_id.lower()
                rec_voice = None

                if any(w in name_lower for w in ['boy', 'son', 'vannak', 'ក្មេងប្រុស', 'កូនប្រុស']):
                    rec_voice = "Khmer Child - Boy (Vannak)"
                elif any(w in name_lower for w in ['girl', 'daughter', 'sreyka', 'ក្មេងស្រី', 'កូនស្រី']):
                    rec_voice = "Khmer Child - Girl (Sreyka)"
                elif any(w in name_lower for w in ['grandfather', 'grandpa', 'ta', 'លោកតា']):
                    rec_voice = "Khmer Elder - Male (Grandfather)"
                elif any(w in name_lower for w in ['grandmother', 'grandma', 'yeay', 'លោកយាយ']):
                    rec_voice = "Khmer Elder - Female (Grandmother)"
                elif any(w in name_lower for w in ['john', 'peter', 'mr', 'dad', 'father', 'piseth', 'ប្រុស']):
                    rec_voice = "Khmer Male - Piseth"
                elif any(w in name_lower for w in ['sarah', 'jane', 'mrs', 'mom', 'mother', 'sreymom', 'ស្រី']):
                    rec_voice = "Khmer Female - Sreymom"

                if not rec_voice:
                    if pitch_f0 > 240.0 or text_scores["child"] > 0:
                        rec_voice = "Khmer Child - Boy (Vannak)" if text_scores["male"] > text_scores["female"] else "Khmer Child - Girl (Sreyka)"
                    elif (0 < pitch_f0 < 115.0) or text_scores["elder"] > 0:
                        rec_voice = "Khmer Elder - Female (Grandmother)" if text_scores["female"] > text_scores["male"] else "Khmer Elder - Male (Grandfather)"
                    elif (115.0 <= pitch_f0 <= 175.0) or text_scores["male"] > text_scores["female"]:
                        rec_voice = "Khmer Male - Piseth"
                    else:
                        rec_voice = voice_pool[next_pool_idx % len(voice_pool)]
                        next_pool_idx += 1

                speaker_profiles[spk_id] = {
                    "voice": rec_voice,
                    "pitch_f0": round(pitch_f0, 1)
                }

            spk_info = speaker_profiles[spk_id]
            updated_seg = dict(seg)
            updated_seg["speaker"] = spk_id
            updated_seg["character"] = spk_id
            updated_seg["khmer_text"] = clean_khmer
            updated_seg["voice"] = seg.get("voice", spk_info["voice"])

            processed_segments.append(updated_seg)

        return processed_segments

    def detect_speaker_for_segment(self, khmer_text: str, original_text: str, start_sec: float, end_sec: float) -> dict:
        """Single segment speaker profile guidance."""
        segs = [{"start": start_sec, "end": end_sec, "khmer_text": khmer_text, "original_text": original_text}]
        res = self.diarize_and_profile_segments(segs)
        if res:
            r = res[0]
            return {
                "speaker_name": r["speaker"],
                "clean_khmer_text": r["khmer_text"],
                "voice": r["voice"],
                "speaker_type": "Guided Recommendation",
                "pitch_f0": r.get("pitch_f0", 0.0)
            }
        return {"speaker_name": "Speaker 1", "clean_khmer_text": khmer_text, "voice": "Khmer Female - Sreymom", "speaker_type": "Default", "pitch_f0": 0.0}
