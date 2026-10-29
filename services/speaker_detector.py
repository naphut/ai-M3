import os
import re
import wave
import subprocess
import tempfile
import numpy as np
from typing import List, Dict, Optional
from utils.logger import logger

class SpeakerDetector:
    """
    Advanced Acoustic-First Speaker Diarization & Profiling Engine for AI Video Dubbing.
    Categorizes speech accurately across 5 core voice categories:
    1. Child [ក្មេង] (Vannak / Sreyka) - Acoustic F0 >= 225 Hz
    2. Female [ស្រី] (Sreymom) - Acoustic F0 168 Hz - 225 Hz
    3. Male [ប្រុស] (Piseth) - Acoustic F0 70 Hz - 168 Hz
    4. Elderly Male [ចាស់ប្រុស] (Grandfather) - Deep Male F0 < 112 Hz + Elder context
    5. Elderly Female [ចាស់ស្រី] (Grandmother) - Female F0 + Elder context
    """
    def __init__(self, audio_wav_path: Optional[str] = None):
        self.audio_wav_path = audio_wav_path
        self._temp_extracted_wav = None
        self._prepare_audio_source()

    def _prepare_audio_source(self):
        """Ensure audio source is accessible as a 16kHz PCM WAV for reliable pitch estimation."""
        if not self.audio_wav_path or not os.path.exists(self.audio_wav_path):
            return

        is_valid_wav = False
        try:
            with wave.open(self.audio_wav_path, 'rb') as wf:
                if wf.getnframes() > 0:
                    is_valid_wav = True
        except Exception:
            is_valid_wav = False

        if not is_valid_wav:
            try:
                temp_file = tempfile.NamedTemporaryFile(suffix="_spk_16k.wav", delete=False)
                temp_path = temp_file.name
                temp_file.close()

                cmd = [
                    "ffmpeg", "-y", "-i", self.audio_wav_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    "-threads", "2", temp_path
                ]
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if res.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
                    self._temp_extracted_wav = temp_path
                    self.audio_wav_path = temp_path
                    logger.info(f"🎤 [SpeakerDetector] Converted source to 16kHz PCM audio: {temp_path}")
            except Exception as e:
                logger.debug(f"[SpeakerDetector] Audio extraction failed: {e}")

    def __del__(self):
        if self._temp_extracted_wav and os.path.exists(self._temp_extracted_wav):
            try:
                os.remove(self._temp_extracted_wav)
            except Exception:
                pass

    def analyze_audio_segment_pitch(self, start_sec: float, end_sec: float) -> float:
        """Estimate fundamental vocal pitch frequency (F0) using autocorrelation pitch analysis."""
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
                if end_frame <= start_frame:
                    return 0.0
                num_frames = end_frame - start_frame

                wf.setpos(start_frame)
                raw_bytes = wf.readframes(num_frames)

                if not raw_bytes or len(raw_bytes) < 256:
                    return 0.0

                dtype = np.int16 if sampwidth == 2 else np.int8
                samples = np.frombuffer(raw_bytes, dtype=dtype)

                if nchannels > 1:
                    samples = samples[::nchannels]

                if len(samples) < 512:
                    return 0.0

                samples = samples.astype(np.float32)

                # Sliding window frame analysis (80ms windows, 40ms hop)
                win_len = int(framerate * 0.080)
                hop_len = int(framerate * 0.040)
                min_lag = max(1, int(framerate / 420.0)) # Max 420Hz
                max_lag = int(framerate / 65.0)          # Min 65Hz

                if len(samples) <= win_len:
                    win_len = len(samples)
                    hop_len = win_len

                pitches = []
                for i in range(0, len(samples) - win_len + 1, hop_len):
                    w = samples[i : i + win_len]
                    if np.std(w) < 100.0:  # Skip silent / noise floor frames
                        continue

                    w_centered = w - np.mean(w)
                    corr = np.correlate(w_centered, w_centered, mode='full')
                    corr = corr[len(corr)//2:]

                    m_lag = min(max_lag, len(corr) - 1)
                    if min_lag >= m_lag:
                        continue

                    peak_idx = np.argmax(corr[min_lag:m_lag]) + min_lag
                    # Require strong periodicity peak > 35% of zero-lag energy
                    if peak_idx > 0 and corr[0] > 0 and (corr[peak_idx] / corr[0]) > 0.35:
                        f0 = framerate / float(peak_idx)
                        if 65.0 <= f0 <= 420.0:
                            pitches.append(f0)

                if not pitches:
                    return 0.0

                median_f0 = float(np.median(pitches))
                return median_f0

        except Exception as e:
            logger.debug(f"Audio pitch extraction exception: {e}")
            return 0.0

    @staticmethod
    def classify_text_speaker(khmer_text: str, original_text: str) -> dict:
        """
        Analyze universal grammatical markers, politeness particles, and kinship forms
        across any video or genre (without drama-specific names or plot keywords).
        """
        orig_lower = (original_text or "").lower()
        khm_lower = (khmer_text or "").lower()
        combined = f"{orig_lower} {khm_lower}"

        # 1. Explicit tags
        has_child_tag = any(t in combined for t in ['[ក្មេង]', '[ក្មេងប្រុស]', '[ក្មេងស្រី]'])
        has_elder_f_tag = '[ចាស់ស្រី]' in combined
        has_elder_m_tag = any(t in combined for t in ['[ចាស់ប្រុស]', '[ចាស់]'])
        has_female_tag = '[ស្រី]' in combined
        has_male_tag = '[ប្រុស]' in combined

        # 2. Universal Child Indicators (grammar/kinship: kid calling parents, crying/fear, childlike pronouns)
        child_grammar = [
            'កូនឃ្លាន', 'កូនខ្លាច', 'កូនចង់', 'កូនអត់', 'ប៉ាៗ', 'ម៉ាក់ៗ', 'តុក្កតា', 'ស្ករគ្រាប់', 'ក្មេងតូច',
            '小朋友', '小孩', '宝宝', '幼童', '小孩子'
        ]
        is_child = has_child_tag or any(p in combined for p in child_grammar)

        # 3. Universal Elder Female Indicators (grandmother/senior female address forms)
        elder_f_grammar = [
            'លោកយាយ', 'យាយខ្ញុំ', 'យាយប្រាប់', 'យាយដឹង',
            '老太太', '老奶奶', '老太婆', '外婆', '老妪'
        ]
        is_elder_f = has_elder_f_tag or any(p in combined for p in elder_f_grammar)

        # 4. Universal Elder Male Indicators (grandfather/senior male address forms)
        elder_m_grammar = [
            'លោកតា', 'តាខ្ញុំ', 'តាប្រាប់', 'តាដឹង', 'តាឯង',
            '老爷爷', '老伯', '大爷', '老夫', '老朽'
        ]
        is_elder_m = has_elder_m_tag or any(p in combined for p in elder_m_grammar)

        # 5. Universal Female Indicators (Khmer female self-pronouns & particles, standard Chinese female honorifics)
        # In Khmer, only females say 'ចាស' / 'ចាស៎', and 'នាងខ្ញុំ' is exclusively female self-pronoun.
        female_grammar = [
            'ចាស', 'ចាស៎', 'ច៎ាស', 'នាងខ្ញុំ', 'ខ្ញុំម្ចាស់',
            '女士', '太太', '小姐', '姑娘', '夫人', '阿姨', '大妈'
        ]
        is_female = has_female_tag or any(p in combined for p in female_grammar)

        # 6. Universal Male Indicators (Khmer male self-pronouns & particles, standard Chinese male honorifics)
        # In Khmer, 'បាទ' and 'ខ្ញុំបាទ' are exclusively male polite particles/pronouns.
        male_grammar = [
            'ខ្ញុំបាទ', 'បាទ',
            '先生', '大叔', '老兄'
        ]
        is_male = has_male_tag or any(p in combined for p in male_grammar)

        return {
            "has_child_tag": has_child_tag,
            "has_elder_f_tag": has_elder_f_tag,
            "has_elder_m_tag": has_elder_m_tag,
            "has_female_tag": has_female_tag,
            "has_male_tag": has_male_tag,
            "is_child": is_child,
            "is_elder_f": is_elder_f,
            "is_elder_m": is_elder_m,
            "is_female": is_female,
            "is_male": is_male,
            "child_self": is_child,
            "elder_m_self": is_elder_m,
            "elder_f_self": is_elder_f,
            "female_name": is_female,
            "male_name": is_male
        }

    def diarize_and_profile_segments(self, segments: List[Dict]) -> List[Dict]:
        """
        Perform Acoustic-First Universal Speaker Diarization with Conversational Continuity.
        Prioritizes the actual human acoustic audio frequency (F0 pitch) and universal context.
        Works across all genres and videos without movie-specific hardcoding.
        """
        processed_segments = []
        last_role = None
        last_voice = None
        last_tag = None
        last_persona = None
        last_end_sec = 0.0
        last_pitch = 0.0
        last_clean_khmer = ""

        default_child_voice = "Khmer Child - Boy (Vannak)"
        default_child_persona = "Boy / Child"

        for i, seg in enumerate(segments):
            st = float(seg.get("start", i * 3.0))
            et = float(seg.get("end", (i + 1) * 3.0))
            orig_text = str(seg.get("original_text", seg.get("text", "")))
            khmer_text = str(seg.get("khmer_text", seg.get("translated_text", "")))

            # Strip existing bracket tags if present in text
            clean_khmer = khmer_text.strip()
            explicit_tag = None
            tag_m = re.match(r"^\[(ប្រុស|ស្រី|ក្មេង|ក្មេងប្រុស|ក្មេងស្រី|ចាស់|ចាស់ប្រុស|ចាស់ស្រី)\]\s*", clean_khmer)
            if tag_m:
                explicit_tag = f"[{tag_m.group(1)}]"
                clean_khmer = clean_khmer[len(tag_m.group(0)):].strip()

            # Measure acoustic vocal pitch F0 directly from vocal audio waveform
            pitch_f0 = self.analyze_audio_segment_pitch(st, et)
            cues = self.classify_text_speaker(clean_khmer, orig_text)

            # Conversational dialogue turn & clause continuation check
            prev_ended_clause = False
            if last_clean_khmer:
                prev_ended_clause = last_clean_khmer.strip().endswith(('.', '!', '?', '。', '！', '？', '?!', '~', 'ហ្អី?', 'ទេ?', 'ស្អី?', '។', '៕'))

            time_gap = max(0.0, st - last_end_sec)
            can_continue = False
            if i > 0 and time_gap < 1.4:
                # Same pitch cluster
                if pitch_f0 > 0.0 and last_pitch > 0.0 and abs(pitch_f0 - last_pitch) < 30.0:
                    can_continue = True
                # Run-on clause from previous speaker (did not end with punctuation, and this segment has no contradicting cues)
                elif not prev_ended_clause and not (cues["is_female"] or cues["is_child"] or cues["is_elder_f"] or cues["is_elder_m"]):
                    can_continue = True

            existing_tag = seg.get("speaker_tag") or explicit_tag
            existing_voice = seg.get("voice_id") or seg.get("voice")
            existing_role = (seg.get("speaker_role") or seg.get("role") or seg.get("gender") or "").lower()
            existing_persona = seg.get("persona") or seg.get("character")

            # --- UNIVERSAL DECISION LOGIC: ACOUSTIC PITCH (PHYSICS) + GEMINI STORY CONTEXT ---
            role = None
            voice = None
            tag = None
            persona = None

            # 1. ACOUSTIC PITCH AVAILABLE (F0 > 0.0) -> Acoustic physical vocal truth
            if pitch_f0 > 0.0:
                # Child vocal range: F0 >= 265 Hz
                if pitch_f0 >= 265.0:
                    role = "child"
                    tag = "[ក្មេង]"
                    is_girl = cues["is_female"] or existing_role == "female" or "[ក្មេងស្រី]" in str(existing_tag)
                    voice = "Khmer Child - Girl (Sreyka)" if is_girl else "Khmer Child - Boy (Vannak)"
                    persona = "Girl / Child" if is_girl else "Boy / Child"

                # Adult Female vocal range: 165 Hz <= F0 < 265 Hz
                elif pitch_f0 >= 165.0:
                    if cues["is_elder_f"] or existing_role == "elder_female" or existing_tag == "[ចាស់ស្រី]":
                        role = "elder_female"
                        tag = "[ចាស់ស្រី]"
                        voice = "Khmer Elder - Female (Grandmother)"
                        persona = "Elderly Female"
                    else:
                        role = "female"
                        tag = "[ស្រី]"
                        voice = "Khmer Female - Sreymom"
                        persona = "Female Adult"

                # Adult Male vocal range: 65 Hz <= F0 < 165 Hz
                else:
                    if (pitch_f0 < 110.0 and (cues["is_elder_m"] or existing_role == "elder_male" or existing_tag in ("[ចាស់ប្រុស]", "[ចាស់]"))):
                        role = "elder_male"
                        tag = "[ចាស់ប្រុស]"
                        voice = "Khmer Elder - Male (Grandfather)"
                        persona = "Elderly Male"
                    else:
                        role = "male"
                        tag = "[ប្រុស]"
                        voice = "Khmer Male - Piseth"
                        persona = "Male Adult"

            # 2. ACOUSTIC PITCH NOT AVAILABLE (F0 == 0.0) -> Use Gemini Story Context & Universal Grammar
            else:
                # Priority 2A: Explicit specific character role from Gemini Story Analysis
                if existing_role in ("female", "child", "elder_female", "elder_male") or existing_tag in ("[ស្រី]", "[ក្មេង]", "[ចាស់ស្រី]", "[ចាស់ប្រុស]"):
                    if existing_role == "female" or existing_tag == "[ស្រី]":
                        role = "female"
                        tag = "[ស្រី]"
                        voice = "Khmer Female - Sreymom"
                        persona = "Female Adult"
                    elif existing_role == "child" or existing_tag == "[ក្មេង]":
                        role = "child"
                        tag = "[ក្មេង]"
                        is_girl = cues["is_female"] or existing_role == "female" or "[ក្មេងស្រី]" in str(existing_tag)
                        voice = "Khmer Child - Girl (Sreyka)" if is_girl else default_child_voice
                        persona = "Girl / Child" if is_girl else default_child_persona
                    elif existing_role == "elder_female" or existing_tag == "[ចាស់ស្រី]":
                        role = "elder_female"
                        tag = "[ចាស់ស្រី]"
                        voice = "Khmer Elder - Female (Grandmother)"
                        persona = "Elderly Female"
                    elif existing_role == "elder_male" or existing_tag in ("[ចាស់ប្រុស]", "[ចាស់]"):
                        role = "elder_male"
                        tag = "[ចាស់ប្រុស]"
                        voice = "Khmer Elder - Male (Grandfather)"
                        persona = "Elderly Male"

                # Priority 2B: Universal Grammatical & Politeness Markers
                elif cues["is_female"]:
                    role = "female"
                    tag = "[ស្រី]"
                    voice = "Khmer Female - Sreymom"
                    persona = "Female Adult"
                elif cues["is_child"]:
                    role = "child"
                    tag = "[ក្មេង]"
                    voice = default_child_voice
                    persona = default_child_persona
                elif cues["is_elder_f"]:
                    role = "elder_female"
                    tag = "[ចាស់ស្រី]"
                    voice = "Khmer Elder - Female (Grandmother)"
                    persona = "Elderly Female"
                elif cues["is_elder_m"]:
                    role = "elder_male"
                    tag = "[ចាស់ប្រុស]"
                    voice = "Khmer Elder - Male (Grandfather)"
                    persona = "Elderly Male"

                # Priority 2C: Conversational sentence continuation
                elif can_continue and last_role:
                    role = last_role
                    voice = last_voice
                    tag = last_tag
                    persona = last_persona

                # Priority 2D: Male default
                else:
                    role = "male"
                    tag = "[ប្រុស]"
                    voice = "Khmer Male - Piseth"
                    persona = "Male Adult"

            # Update speaker memory
            last_role = role
            last_voice = voice
            last_tag = tag
            last_persona = persona
            last_end_sec = et
            last_pitch = pitch_f0
            last_clean_khmer = clean_khmer

            # Store updated segment fields
            updated = dict(seg)
            spk_id = seg.get("speaker") or seg.get("character") or f"Speaker 1"
            updated["speaker"] = spk_id
            updated["character"] = spk_id
            updated["khmer_text"] = clean_khmer
            updated["voice"] = voice
            updated["role"] = role
            updated["speaker_tag"] = tag
            updated["persona"] = persona
            updated["pitch_f0"] = pitch_f0

            processed_segments.append(updated)

        return processed_segments

    def detect_speaker_for_segment(self, khmer_text: str, original_text: str, start_sec: float, end_sec: float) -> dict:
        """Single segment speaker profile guidance across all 5 voice categories."""
        dummy_seg = {
            "start": start_sec,
            "end": end_sec,
            "khmer_text": khmer_text,
            "original_text": original_text
        }
        res = self.diarize_and_profile_segments([dummy_seg])
        if res:
            r = res[0]
            v = r.get("voice", "Khmer Male - Piseth")
            role = r.get("role", "male")
            tag = r.get("speaker_tag", "[ប្រុស]")
            persona = r.get("persona", "Male Adult")

            # Map to standard category name
            if role == "child":
                spk_type = "Child"
            elif role == "elder_female":
                spk_type = "Elderly Female"
            elif role == "elder_male":
                spk_type = "Elderly Male"
            elif role == "female":
                spk_type = "Female"
            else:
                spk_type = "Male"

            return {
                "speaker_name": r.get("speaker", "Speaker 1"),
                "clean_khmer_text": r.get("khmer_text", khmer_text),
                "voice": v,
                "speaker_type": spk_type,
                "role": role,
                "tag": tag,
                "persona": persona,
                "pitch_f0": r.get("pitch_f0", 0.0)
            }

        return {
            "speaker_name": "Speaker 1",
            "clean_khmer_text": khmer_text,
            "voice": "Khmer Male - Piseth",
            "speaker_type": "Male",
            "role": "male",
            "tag": "[ប្រុស]",
            "persona": "Male Adult",
            "pitch_f0": 0.0
        }
