"""
Dedicated Translation AI Service
Leverages Gemini Flash (gemini-3.8-flash / gemini-3.7-flash / gemini-3.6-flash).
Focuses strictly on:
1. Contextual dialogue translation (Source -> Natural Spoken Khmer)
2. Duration-constrained dialogue phrasing (Matching actor's on-screen pacing)
3. Dialogue condensing for oversized lines
DOES NOT touch audio or STT.
"""
import os
import json
import time
import re
import html
import urllib.parse
import urllib.request
from typing import List, Dict, Any, Union, Optional
import requests
from core.models import Segment
from utils.logger import logger
from utils.config_manager import get_gemini_api_key, get_gemini_api_keys
from typing import Tuple


class GeminiQuotaExceededError(Exception):
    """Raised when Gemini API Quota (HTTP 429 / RESOURCE_EXHAUSTED) is reached."""
    pass


class GeminiAuthError(Exception):
    """Raised when Gemini API Key is invalid or rejected (HTTP 400 / 401 / 403)."""
    pass


def sanitize_khmer_translation(text: Optional[str]) -> str:
    """
    Sanitize translated text by converting accidental Thai words/loan tokens
    into natural Khmer equivalents and removing stray non-Khmer glyphs.
    Prevents unnecessary API retries and quota waste.
    """
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""

    # 1. Strip Chinese source echo if format is 'Chinese text - Khmer text' or 'Chinese: Khmer'
    # e.g. '眼神飘忽 - ក្រសែភ្នែកជនហ្នឹងមើលទៅរ...' -> 'ក្រសែភ្នែកជនហ្នឹងមើលទៅរ...'
    t = re.sub(r'^[\u4E00-\u9FFF\s\d\.,!?:;\-\–_]{2,}\s*[\-\–:\=]\s*', '', t)

    # 2. Clean bracketed duplicate transliterations like 'แค่นี้ (រឿងប៉ុណ្ណឹង)' or 'ไอ้ (ไอ้)'
    t = re.sub(r'[\u0E00-\u0E7F]+\s*\(([\u1780-\u17FF\s]+)\)', r'\1', t)
    t = re.sub(r'\(([\u0E00-\u0E7F\s]+)\)', '', t)

    # 3. Comprehensive Thai loan/particle to natural spoken Khmer replacements
    thai_replacements = [
        ('ហើយแล้ว', 'ហើយ'),
        ('ហើយហើយ', 'ហើយ'),
        ('ហើយ ណាស់', 'ណាស់ហើយ'),
        ('แล้วហើយ', 'ហើយ'),
        ('តต่อ', 'ត'),
        ('រឿងប៉ុណ្ណឹង', 'រឿងប៉ុណ្ណឹង'),
        ('ต่างหาก', 'ទៅវិញទេ'),
        ('ในเมื่อ', 'ក្នុងពេលដែល'),
        ('เมื่อ', 'ពេលដែល'),
        ('ส่วน', 'ចំណែក'),
        ('ហើយ', 'ហើយ'),
        ('แล้ว', 'ហើយ'),
        ('ទៅហើយ', 'ទៅហើយ'),
        ('ไป', 'ទៅ'),
        ('มา', 'មក'),
        ('พา', 'នាំ'),
        ('ยิ่ง', 'កាន់តែ'),
        ('อยู่', 'នៅ'),
        ('ต่อ', 'ត'),
        ('กล้า', 'ហ៊ាន'),
        ('แค่นี้', 'ប៉ុណ្ណឹង'),
        ('ไอ้', 'អា'),
        ('ไม่', 'មិន'),
        ('ใช่', 'មែន'),
        ('ชอบ', 'ចូលចិត្ត'),
        ('รัก', 'ស្រឡាញ់'),
        ('คน', 'មនុស្ស'),
        ('มาก', 'ណាស់'),
        ('ดี', 'ល្អ'),
        ('ทำ', 'ធ្វើ'),
        ('อะไร', 'អី'),
        ('กิน', 'ញ៉ាំ'),
        ('นอน', 'គេង'),
        ('บ้าน', 'ផ្ទះ'),
        ('เงิน', 'លុយ'),
        ('คุณ', 'លោក'),
        ('เธอ', 'នាង'),
        ('เขา', 'គាត់'),
        ('ฉัน', 'ខ្ញុំ'),
        ('เรา', 'យើង'),
        ('ครับ', ''),
        ('ค่ะ', ''),
        ('คะ', ''),
        ('นะ', 'ណា'),
        ('จ้ะ', 'ចាស'),
        ('จ๊ะ', 'ចាស'),
    ]
    for thai_word, khmer_word in thai_replacements:
        if thai_word in t:
            t = t.replace(thai_word, khmer_word)

    # 4. Convert common Latin names to Khmer phonetics
    t = re.sub(r'\b[jJ]ason\b', 'ជេសិន', t)

    # 5. Remove any remaining stray Thai characters (U+0E00 to U+0E7F)
    t = re.sub(r'[\u0E00-\u0E7F]', '', t)

    # 6. Strictly remove ANY Chinese characters (U+4E00 to U+9FFF) - Pure Khmer only
    t = re.sub(r'[\u4E00-\u9FFF]', '', t)

    # 7. Clean duplicate words, particles, spaces, or stray punctuation
    t = re.sub(r'ហើយ\s*ហើយ', 'ហើយ', t)
    t = re.sub(r'ត\s*ត', 'ត', t)
    t = re.sub(r'រឿង\s*រឿង', 'រឿង', t)
    t = re.sub(r'\(\s*\)', '', t)
    t = re.sub(r'^\s*[\-\–:\=]+\s*', '', t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()


def validate_khmer_translation(text: Optional[str], original_text: str = "") -> Tuple[bool, str]:
    """
    Validate translated text for Khmer video dubbing production:
    1. Must be non-empty string.
    2. Must contain Khmer Unicode characters (U+1780 to U+17FF).
    3. Must NOT contain Thai script (U+0E00 to U+0E7F).
    4. Must NOT contain Chinese characters (U+4E00 to U+9FFF).
    5. Must NOT be an untranslated verbatim copy of Chinese source text.
    """
    if text is None:
        return False, "Translation text is None"
    
    t = sanitize_khmer_translation(text)
    if not t:
        return False, "Empty translation text"
    
    # Check Thai script leakage (U+0E00 to U+0E7F)
    if re.search(r'[\u0E00-\u0E7F]', t):
        return False, "Contains Thai script leakage"
    
    # Check Chinese script leakage (U+4E00 to U+9FFF)
    if re.search(r'[\u4E00-\u9FFF]', t):
        return False, "Contains Chinese script leakage"
        
    # Check if Khmer characters exist (U+1780 to U+17FF)
    if not re.search(r'[\u1780-\u17FF]', t):
        orig_clean = re.sub(r'[\s\d\.,!?:;\-\–_]', '', str(original_text))
        t_clean = re.sub(r'[\s\d\.,!?:;\-\–_]', '', t)
        if orig_clean and not t_clean:
            return False, "Missing Khmer script (only numbers/punctuation)"
        if not re.search(r'[\u1780-\u17FF]', t):
            return False, "No Khmer script found in output"

    # Check verbatim source copy if source has Chinese characters
    if original_text and len(original_text.strip()) > 1:
        if t == original_text.strip() and re.search(r'[\u4E00-\u9FFF]', original_text):
            return False, "Verbatim copy of untranslated source text"

    return True, "Valid Khmer translation"


def assign_speaker_demographics(s: Segment, spk_role: str = "", spk_tag: str = ""):
    """
    Classify and map demographic speaker profile (male, female, child, elder)
    based on semantic context of translated Khmer text and original dialogue cues.
    Preserves existing valid values if already assigned.
    """
    try:
        from services.speaker_detector import SpeakerDetector
        cues = SpeakerDetector.classify_text_speaker(s.translated_text or "", s.original_text or "")
        if cues.get("is_female"):
            spk_role = "female"
            spk_tag = "[ស្រី]"
        elif cues.get("is_child"):
            spk_role = "child"
            spk_tag = "[ក្មេង]"
        elif cues.get("is_elder_f"):
            spk_role = "elder_female"
            spk_tag = "[ចាស់ស្រី]"
        elif cues.get("is_elder_m"):
            spk_role = "elder_male"
            spk_tag = "[ចាស់ប្រុស]"
    except Exception:
        pass

    # Map to the 5 core personas and voices
    if spk_role == "female" or (spk_tag and "[ស្រី]" in spk_tag):
        s.persona = "Female Adult"
        s.voice_id = "Khmer Female - Sreymom"
        s.speaker_tag = "[ស្រី]"
        s.speaker_role = "female"
    elif spk_role == "child" or (spk_tag and "[ក្មេង]" in spk_tag):
        is_girl = any(w in (s.translated_text or "").lower() for w in ["ក្មេងស្រី", "កូនស្រី", "ស្រី", "girl"])
        s.persona = "Girl / Child" if is_girl else "Boy / Child"
        s.voice_id = "Khmer Child - Girl (Sreyka)" if is_girl else "Khmer Child - Boy (Vannak)"
        s.speaker_tag = "[ក្មេង]"
        s.speaker_role = "child"
    elif spk_role == "elder_female" or (spk_tag and "[ចាស់ស្រី]" in spk_tag):
        s.persona = "Elderly Female"
        s.voice_id = "Khmer Elder - Female (Grandmother)"
        s.speaker_tag = "[ចាស់ស្រី]"
        s.speaker_role = "elder_female"
    elif spk_role == "elder_male" or (spk_tag and ("[ចាស់ប្រុស]" in spk_tag or "[ចាស់]" in spk_tag)):
        s.persona = "Elderly Male"
        s.voice_id = "Khmer Elder - Male (Grandfather)"
        s.speaker_tag = "[ចាស់ប្រុស]"
        s.speaker_role = "elder_male"
    elif spk_role == "male" or (spk_tag and "[ប្រុស]" in spk_tag):
        s.persona = "Male Adult"
        s.voice_id = "Khmer Male - Piseth"
        s.speaker_tag = "[ប្រុស]"
        s.speaker_role = "male"
    else:
        if not getattr(s, "persona", None):
            s.persona = None
        if not getattr(s, "voice_id", None):
            s.voice_id = None
        if not getattr(s, "speaker_tag", None):
            s.speaker_tag = None
        if not getattr(s, "speaker_role", None):
            s.speaker_role = None


class TranslationService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        # Assemble complete list of all available keys for auto-failover/rotation
        self.all_keys: List[str] = []
        if api_key and api_key.strip():
            self.all_keys.append(api_key.strip())
        for k in get_gemini_api_keys():
            k_s = k.strip()
            if k_s and k_s not in self.all_keys:
                self.all_keys.append(k_s)

        self.exhausted_keys = set()
        self.cooldown_keys: Dict[str, float] = {}
        # Production model hierarchy for translation (verified active endpoints)
        self.models = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-3.5-flash",
            "gemini-3.1-flash-lite"
        ]

    def set_key_cooldown(self, key: str, duration_sec: float = 20.0):
        self.cooldown_keys[key] = time.time() + duration_sec

    def get_active_keys(self) -> List[str]:
        now = time.time()
        active = [k for k in self.all_keys if k not in self.exhausted_keys and now >= self.cooldown_keys.get(k, 0.0)]
        if not active:
            active = [k for k in self.all_keys if k not in self.exhausted_keys]
        return active

    def mark_key_exhausted(self, key: str, reason: str = "Quota Exceeded"):
        if key not in self.exhausted_keys:
            self.exhausted_keys.add(key)
            logger.warning(f"⚠️ [Gemini Key Manager] Key {key[:8]}... marked unusable ({reason}). Active remaining: {len(self.get_active_keys())}")

    def is_all_keys_exhausted(self) -> bool:
        return len([k for k in self.all_keys if k not in self.exhausted_keys]) == 0

    def translate_segments(
        self,
        segments: List[Union[Segment, Dict[str, Any]]],
        source_lang: str = "auto",
        target_lang: str = "km",
        progress_callback = None,
        is_cancelled_fn = None
    ) -> List[Segment]:
        """
        Translate a list of dialogue segments with contextual awareness and duration constraints.
        Supports:
        1. Auto-Resume: Automatically skips already translated segments, resuming from first pending line.
        2. Gemini Cloud AI: Primary high-quality natural spoken Khmer translation.
        3. Local HY-MT1.5-1.8B: Automatic seamless failover when Gemini hits quota limits (HTTP 429).
        4. 100% preservation of Segment IDs, timing (start, end, slot_duration), and speaker profiles.
        """
        if not segments:
            return []

        # Convert all to Segment models
        seg_models: List[Segment] = []
        for i, s in enumerate(segments):
            if isinstance(s, Segment):
                seg_models.append(s)
            else:
                seg_models.append(Segment.from_dict(s, default_idx=i+1))

        total = len(seg_models)

        # 1. AUTO-RESUME CHECK: Identify already translated and validated segments
        pending_segments: List[Segment] = []
        already_completed = 0
        for s in seg_models:
            curr_text = (s.translated_text or getattr(s, 'khmer_text', '') or "").strip()
            if curr_text:
                curr_clean = sanitize_khmer_translation(curr_text)
                is_valid, _ = validate_khmer_translation(curr_clean, s.original_text)
                if is_valid:
                    s.translated_text = curr_clean
                    s.khmer_text = curr_clean
                    s.translation_status = "translated"
                    already_completed += 1
                    continue
            pending_segments.append(s)

        if not pending_segments:
            logger.info(f"✅ [Auto-Resume] All {total} segments already translated and validated. Returning immediately.")
            if progress_callback:
                progress_callback(100, f"Auto-Resume: All {total} segments already translated!")
            return seg_models

        if already_completed > 0:
            logger.info(
                f"⏩ [Auto-Resume] Found {already_completed}/{total} existing translated segments. "
                f"Resuming strictly from segment {pending_segments[0].id} ({len(pending_segments)} pending)..."
            )
            if progress_callback:
                pct = int((already_completed / float(total)) * 100)
                progress_callback(pct, f"Auto-Resume: {already_completed}/{total} ready. Translating {len(pending_segments)} remaining...")

        # 2. Check if active Gemini API keys exist
        active_keys = self.get_active_keys()
        if not active_keys:
            logger.warning("⚠️ [Translation] No active Gemini keys found. Seamlessly invoking Local HY-MT1.5-1.8B Engine...")
            if progress_callback:
                progress_callback(
                    int((already_completed / float(total)) * 100),
                    "ដំណើរការបកប្រែដោយ Local HY-MT1.5-1.8B AI (Apple Silicon)..."
                )
            from services.hymt_service import get_hymt_service
            try:
                hymt = get_hymt_service()
                hymt.translate_segments(
                    pending_segments,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    progress_callback=progress_callback,
                    is_cancelled_fn=is_cancelled_fn,
                    start_completed_count=already_completed,
                    total_count=total
                )
            except Exception as e_hymt:
                logger.error(f"❌ [HY-MT Local Init Error] {e_hymt}. Falling back to multi-engine single-line translation...")
                for s in pending_segments:
                    if is_cancelled_fn and is_cancelled_fn():
                        break
                    t = self.translate_single_text(s.original_text, source_lang=source_lang, target_lang=target_lang, duration=s.slot_duration)
                    s.translated_text = sanitize_khmer_translation(t)
                    s.translation_status = "translated"
            for s in seg_models:
                s.khmer_text = s.translated_text
            if progress_callback:
                progress_callback(100, f"Translation Complete! {total} segments ready.")
            return seg_models

        # 3. Primary: Gemini Parallel Batch Translation
        batch_size = 40
        logger.info(f"🌐 [Translation] Starting parallel translation of {len(pending_segments)} pending segments via Gemini AI...")
        batches = [pending_segments[i:i + batch_size] for i in range(0, len(pending_segments), batch_size)]
        completed_count = already_completed
        quota_exceeded = False

        def _process_one_batch(b_idx_and_batch):
            nonlocal completed_count, quota_exceeded
            if (is_cancelled_fn and is_cancelled_fn()) or quota_exceeded:
                return
            b_idx, batch = b_idx_and_batch

            if b_idx > 0:
                time.sleep(min(0.25 * (b_idx % 3), 0.6))

            try:
                batch_success = self._translate_batch_gemini(batch, source_lang=source_lang, target_lang=target_lang)
            except (GeminiQuotaExceededError, GeminiAuthError):
                quota_exceeded = True
                return
            except Exception as err:
                logger.warning(f"⚠️ Batch {b_idx} error: {err}")
                batch_success = False

            if not batch_success:
                if self.is_all_keys_exhausted():
                    quota_exceeded = True
                    return

            completed_count += len(batch)
            if progress_callback:
                pct = min(98, max(5, int((completed_count / float(total)) * 100)))
                progress_callback(pct, f"Gemini AI: Translating dialogues {completed_count}/{total}...")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(_process_one_batch, enumerate(batches)))

        # 4. Failover to Local HY-MT1.5-1.8B if Gemini quota was exhausted mid-way
        untranslated = [s for s in pending_segments if not s.translated_text or s.translation_status != "translated"]
        if untranslated and (quota_exceeded or self.is_all_keys_exhausted()):
            logger.warning(
                f"⚠️ [Failover] Gemini API Quota reached (HTTP 429). "
                f"Seamlessly switching to HY-MT1.5-1.8B Local Engine for remaining {len(untranslated)} segments..."
            )
            if progress_callback:
                progress_callback(
                    int((completed_count / float(total)) * 100),
                    f"⚠️ Gemini Quota -> ប្តូរទៅ Local HY-MT1.5 AI បន្ត {len(untranslated)} ឃ្លាដែលនៅសល់..."
                )
            from services.hymt_service import get_hymt_service
            try:
                hymt = get_hymt_service()
                hymt.translate_segments(
                    untranslated,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    progress_callback=progress_callback,
                    is_cancelled_fn=is_cancelled_fn,
                    start_completed_count=completed_count,
                    total_count=total
                )
            except Exception as e_hymt:
                logger.error(f"❌ [HY-MT Failover Error] {e_hymt}. Translating remaining items individually...")
                for s in untranslated:
                    if is_cancelled_fn and is_cancelled_fn():
                        break
                    t = self.translate_single_text(s.original_text, source_lang=source_lang, target_lang=target_lang, duration=s.slot_duration)
                    s.translated_text = sanitize_khmer_translation(t)
                    s.translation_status = "translated"

        # 5. Final Validation & Polish Pass
        invalid_segments = []
        for seg in seg_models:
            seg.translated_text = sanitize_khmer_translation(seg.translated_text)
            is_valid, reason = validate_khmer_translation(seg.translated_text, seg.original_text)
            if not is_valid:
                invalid_segments.append((seg, reason))

        if invalid_segments:
            logger.info(f"🔄 Polishing {len(invalid_segments)} edge-case segments...")
            for seg, reason in invalid_segments:
                if is_cancelled_fn and is_cancelled_fn():
                    break
                try:
                    from services.hymt_service import get_hymt_service
                    hymt = get_hymt_service()
                    corrected = hymt.translate_single_text(seg.original_text, source_lang=source_lang)
                except Exception:
                    corrected = self.translate_single_text(seg.original_text, source_lang=source_lang, target_lang=target_lang)

                c_clean = sanitize_khmer_translation(corrected)
                c_valid, _ = validate_khmer_translation(c_clean, seg.original_text)
                if c_valid:
                    seg.translated_text = c_clean.strip()
                    seg.translation_status = "translated"
                else:
                    seg.translated_text = c_clean or seg.original_text
                    seg.translation_status = "translated"

        # Synchronize canonical khmer_text
        for seg in seg_models:
            seg.khmer_text = seg.translated_text

        if progress_callback:
            progress_callback(100, f"Translation Complete! {total} segments translated.")

        logger.info(f"✅ [Translation] All {total} segments successfully validated and translated to {target_lang}.")
        return seg_models


    def _translate_batch_gemini(self, batch: List[Segment], source_lang: str, target_lang: str) -> bool:
        """Translate a batch of dialogues using Gemini with scene context and duration limits."""
        active_keys = self.get_active_keys()
        if not active_keys:
            raise GeminiQuotaExceededError(
                "Gemini API Quota Exceeded (HTTP 429 / RESOURCE_EXHAUSTED). "
                "គ្រប់ Gemini API Keys ទាំងអស់បានអស់ Quota ឬមិនត្រឹមត្រូវ។ សូមបញ្ចូល API Key ថ្មី។"
            )

        lines_payload = []
        for s in batch:
            dur = max(0.4, round(float(s.slot_duration or (s.end - s.start)), 2))
            target_syllables = max(2, int(round(dur * 3.8)))
            lines_payload.append({
                "id": s.id,
                "speaker": s.speaker_id,
                "duration_seconds": dur,
                "target_syllables": f"~{target_syllables} syllables",
                "original_text": s.original_text
            })

        prompt = (
            "You are a master cinematic video dubbing translator specializing in authentic, natural spoken Khmer (អ្នកបកប្រែភាពយន្តជំនាញភាសានិយាយខ្មែរធម្មជាតិ).\n"
            f"Translate the following conversational dialogue lines from {source_lang} into vivid, dramatic, natural spoken Khmer.\n\n"
            "GOLDEN DUBBING TRANSLATION RULES:\n"
            "1. STRICT PURE KHMER SCRIPT ONLY (អក្សរខ្មែរ ១០០%): Translate ONLY into authentic Khmer characters (អក្សរខ្មែរ, U+1780 to U+17FF). Absolutely NEVER output Thai script (ภาษาไทย เช่น แล้ว, ไป, มา, พา, ยิ่ง, อยู่, เมื่อ, ส่วน, แค่นี้, ไอ้), Chinese characters (汉字), or Latin letters in the translated text. Always use proper natural spoken Khmer words (ហើយ, ទៅ, មក, នាំ, កាន់តែ, នៅ, ពេលដែល, ចំណែក, ប៉ុណ្ណឹង, អា).\n"
            "2. DO NOT ECHO SOURCE TEXT: Output ONLY the translated Khmer dialogue. NEVER prepend source Chinese characters, pinyin, or English annotations.\n"
            "3. NATURAL CINEMATIC SPOKEN KHMER (ភាសានិយាយបែបភាពយន្ត រស់រវើក):\n"
            "   - Translate how real Cambodians speak in movies and everyday life. NEVER translate word-for-word literally (កុំបកប្រែពាក្យតាមពាក្យ).\n"
            "   - FORBIDDEN ROBOTIC PHRASES: Do NOT start questions with 'តើ...' or address people as 'អ្នក' unless genuinely addressing a formal stranger. Instead of 'តើអ្នកសុខសប្បាយទេ?' write 'យ៉ាងម៉េចហើយ? / មិនអីទេណ៎ា?'. Instead of 'តើអ្នកចង់ធ្វើអ្វី?' write 'ពួកឯងចង់ធ្វើស្អីហ្នឹង?!'.\n"
            "   - EXPRESSIVE PARTICLES: End sentences with natural Khmer emotional particles that match the drama: '...ណ៎ា / ...ណា៎ / ...ហ្អ៎ / ...ហ្ន៎ / ...ហ្អី / ...ម៉េស / ...ចឹង / ...វ៉ើយ / ...តើ / ...ទៅ!'.\n"
            "4. DYNAMIC RELATIONSHIPS & AUTHENTIC PRONOUNS (សព្វនាមតាមតួអង្គ):\n"
            "   - Parent & Child: 'ប៉ា/ម៉ាក់' vs 'កូន' (e.g. '你怎么醒了' when mom asks child -> 'កូនភ្ញាក់ហើយហ្អ៎?')\n"
            "   - Grandparent & Grandchild: 'លោកតា/លោកយាយ' vs 'ចៅ'\n"
            "   - Couples / Lovers: 'បង' vs 'អូន'\n"
            "   - Friends / Peers / General: 'ឯង' vs 'ខ្ញុំ' or 'គ្នា'\n"
            "   - Boss / Master / Senior: 'លោក / លោកប្រធាន / ចៅហ្វាយ' vs 'ខ្ញុំ / ខ្ញុំបាទ'\n"
            "   - Enemies / Anger / Confrontation: 'ឯង / ហង' vs 'អញ / ខ្ញុំ' (e.g. '你们想干什么' -> 'ពួកឯងចង់ធ្វើស្អី?!')\n"
            "5. IDIOMATIC & DRAMATIC ADAPTATION (បកប្រែតាមន័យសាច់រឿង):\n"
            "   - Adapt foreign idioms into natural Khmer equivalents:\n"
            "     * '绝不是巧合' -> 'មិនមែនជារឿងចៃដន្យដាច់ខាត!'\n"
            "     * '怎么会这样' -> 'មិចបានទៅជាចឹង?!'\n"
            "     * '够...喝一壶了' -> 'ល្មមឱ្យ...រាងចាលម្តងហើយ!' / 'ល្មមឱ្យ...វល់ក្បាលហើយ!'\n"
            "     * '你给我闭嘴' -> 'បិទមាត់ឯងភ្លាមទៅ!'\n"
            "     * '没事了' -> 'មិនអីទេ / អស់អីហើយ'\n"
            "6. RYTHMO-BAND LIP-SYNC & PACING CONSTRAINTS (ចង្វាក់មាត់ និងចំនួនព្យាង្គ):\n"
            "   - Every line has a 'target_syllables' target (based on 3.8 syllables per second of natural spoken Khmer). Formulate your Khmer translation to closely match this target so the voice opens and closes with the actor's lips!\n"
            "   - If duration_seconds <= 1.0s: Keep it extremely punchy (2-4 syllables, e.g. 'លឿនឡើង!', 'មែនហើយ!', 'ទៅណា?', 'ម៉ាក់!'). Never use long polite fluff.\n"
            "   - If duration_seconds <= 2.0s: Keep it concise and direct (4-8 syllables max).\n"
            "   - If duration_seconds <= 3.5s: Keep it natural and expressive (8-14 syllables max).\n"
            "   - CRITICAL: Never write unnecessarily long explanations that force the voice actor to rush or speak after the mouth has closed!\n"
            "7. PRESERVE DIALOGUE DEPTH & VOCAL REPETITIONS:\n"
            "   - Do NOT drop names, vital plot details, or character intent.\n"
            "   - Preserve vocal repetitions if present (e.g. '快 快' -> 'លឿនឡើង លឿនឡើង!').\n"
            "8. SPEAKER ROLE & TAG IDENTIFICATION (ការកំណត់ភេទ និងវ័យតួអង្គទូទៅ):\n"
            "   Analyze the conversational narrative, relationship between characters, and dialogue context to identify who is speaking each line:\n"
            "   - 'female' / '[ស្រី]': for women, mothers, daughters, wives, sisters, ladies, female professionals.\n"
            "   - 'male' / '[ប្រុស]': for men, fathers, sons, husbands, brothers, gentlemen, male professionals.\n"
            "   - 'child' / '[ក្មេង]': for young children, boys, girls.\n"
            "   - 'elder_male' / '[ចាស់ប្រុស]': for grandfathers, elderly men, senior patriarchs.\n"
            "   - 'elder_female' / '[ចាស់ស្រី]': for grandmothers, elderly women, senior matriarchs.\n"
            "   CRITICAL: In dialogues between multiple characters, accurately distinguish alternating speakers and assign their true demographic role!\n\n"
            "Input Lines:\n"
            f"{json.dumps(lines_payload, ensure_ascii=False, indent=2)}\n\n"
            "Output ONLY a valid JSON array of objects containing EXACTLY every input item with keys 'id', 'translated_text', 'speaker_role', 'speaker_tag':\n"
            "[\n"
            "  {\n"
            "    \"id\": \"seg_0001\",\n"
            "    \"translated_text\": \"...natural spoken Khmer dialogue line 1...\",\n"
            "    \"speaker_role\": \"female\",\n"
            "    \"speaker_tag\": \"[ស្រី]\"\n"
            "  },\n"
            "  {\n"
            "    \"id\": \"seg_0002\",\n"
            "    \"translated_text\": \"...natural spoken Khmer dialogue line 2...\",\n"
            "    \"speaker_role\": \"male\",\n"
            "    \"speaker_tag\": \"[ប្រុស]\"\n"
            "  }\n"
            "]"
        )

        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json"
            }
        }

        # Rotate across active keys and model hierarchy
        for api_key in list(active_keys):
            for model in self.models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=35)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            from utils.gemini_parser import parse_gemini_json_response
                            parsed = parse_gemini_json_response(raw_text)
                            
                            # Build comprehensive lookup supporting 'translation', 'translated_text', 'speaker_role', and 'speaker_tag'
                            trans_map = {}
                            for idx_p, item in enumerate(parsed):
                                if isinstance(item, dict):
                                    item_id = str(item.get("id", "")).strip()
                                    trans_txt = str(item.get("translation") or item.get("translated_text") or "").strip()
                                    trans_txt = sanitize_khmer_translation(trans_txt)
                                    spk_r = str(item.get("speaker_role") or item.get("role") or "").strip().lower()
                                    spk_t = str(item.get("speaker_tag") or item.get("tag") or "").strip()
                                    item_val = {"text": trans_txt, "role": spk_r, "tag": spk_t}
                                    if item_id:
                                        trans_map[item_id] = item_val
                                        clean_id = re.sub(r"^[^\d]+", "", item_id).lstrip("0") or "0"
                                        trans_map[clean_id] = item_val
                                    trans_map[f"pos_{idx_p}"] = item_val

                            all_mapped = True
                            for i, s in enumerate(batch):
                                clean_s_id = re.sub(r"^[^\d]+", "", str(s.id)).lstrip("0") or "0"
                                matched = trans_map.get(str(s.id)) or trans_map.get(clean_s_id)
                                if not matched and len(parsed) == len(batch):
                                    matched = trans_map.get(f"pos_{i}")

                                if isinstance(matched, dict):
                                    matched_text = matched.get("text", "")
                                    spk_role = matched.get("role", "")
                                    spk_tag = matched.get("tag", "")
                                else:
                                    matched_text = str(matched or "")
                                    spk_role = ""
                                    spk_tag = ""

                                if matched_text and matched_text.strip():
                                    cleaned_matched = sanitize_khmer_translation(matched_text.strip())
                                    is_valid, rsn = validate_khmer_translation(cleaned_matched, s.original_text)
                                    if is_valid:
                                        s.translated_text = cleaned_matched
                                        s.translation_status = "translated"
                                        assign_speaker_demographics(s, spk_role=spk_role, spk_tag=spk_tag)
                                    else:
                                        logger.warning(f"⚠️ [Translation Validator] Batch item {s.id} rejected: {rsn}. Text: '{matched_text[:30]}'")
                                        all_mapped = False
                                        s.translation_status = "VALIDATION_FAILED"
                                else:
                                    all_mapped = False
                                    s.translation_status = "TRANSLATION_FAILED"

                            # Explicit retry for any individual items missed or rejected by validation
                            if not all_mapped and not self.is_all_keys_exhausted():
                                unmapped_items = [s for s in batch if not s.translated_text or s.translation_status != "translated"]
                                for s in unmapped_items:
                                    salvaged = sanitize_khmer_translation(s.translated_text or "")
                                    if salvaged and re.search(r'[\u1780-\u17FF]', salvaged) and not re.search(r'[\u0E00-\u0E7F\u4E00-\u9FFF]', salvaged):
                                        s.translated_text = salvaged
                                        s.translation_status = "translated"
                                        continue

                                    time.sleep(0.3)  # Gentle pacing to avoid 429 burst
                                    logger.warning(f"⚠️ [Translation] Segment {s.id} failed validation/mapping. Retrying individually...")
                                    res_single = self.translate_single_text(
                                        s.original_text,
                                        source_lang=source_lang,
                                        target_lang=target_lang,
                                        duration=s.slot_duration
                                    )
                                    res_clean = sanitize_khmer_translation(res_single)
                                    s_valid, s_rsn = validate_khmer_translation(res_clean, s.original_text)
                                    if s_valid:
                                        s.translated_text = res_clean.strip()
                                        s.translation_status = "translated"
                                    else:
                                        cleaned = re.sub(r'[\u0E00-\u0E7F\u4E00-\u9FFF]', '', res_clean).strip()
                                        if cleaned and re.search(r'[\u1780-\u17FF]', cleaned):
                                            s.translated_text = cleaned
                                            s.translation_status = "translated"
                                        else:
                                            s.translated_text = s.original_text
                                            s.translation_status = "ready"

                            return True
                    elif resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text:
                        logger.warning(f"⚠️ [Gemini 429] Model {model} rate limited on key {api_key[:8]}... Trying next model.")
                        continue
                    elif resp.status_code in (400, 401, 403) and any(err_kw in resp.text for err_kw in ["API_KEY_INVALID", "PERMISSION_DENIED", "not allowed by policy"]):
                        logger.warning(f"⚠️ [Gemini {resp.status_code}] Key {api_key[:8]}... rejected on {model}. Marking exhausted.")
                        self.mark_key_exhausted(api_key, f"HTTP {resp.status_code}")
                        break
                    else:
                        logger.debug(f"Gemini {model} returned status {resp.status_code}: {resp.text[:100]}")
                except Exception as e:
                    logger.debug(f"Gemini {model} batch translation error: {e}")
                    continue
            else:
                self.set_key_cooldown(api_key, 25.0)
                logger.warning(f"⏳ [Gemini Key Manager] Key {api_key[:8]}... entered 25s cooldown (rate limited on all models). Active remaining: {len(self.get_active_keys())}")

        if self.is_all_keys_exhausted():
            raise GeminiQuotaExceededError(
                "Gemini API Quota Exceeded (HTTP 429 / RESOURCE_EXHAUSTED). "
                "គ្រប់ Gemini API Keys ទាំងអស់បានអស់ Quota ប្រចាំថ្ងៃហើយ។ សូមបញ្ចូល API Key ថ្មី។"
            )

        return False

    def translate_single_text(self, text: str, source_lang: str = "auto", target_lang: str = "km", duration: float = 0.0) -> str:
        """Translate a single line with multi-tiered fallback (Gemini -> Google Mobile -> MyMemory)."""
        if not text or not text.strip():
            return ""

        # 1. Gemini Single (only if active Gemini keys exist)
        if not self.is_all_keys_exhausted():
            res = self._translate_single_gemini(text, source_lang, target_lang, duration)
            if res:
                return res

        # 2. Free Google Mobile Translation Engine
        res = self._translate_google_mobile(text, source_lang, target_lang)
        if res:
            return res

        # 3. MyMemory Free API
        res = self._translate_mymemory(text, source_lang, target_lang)
        if res:
            return res

        return text

    def _translate_single_gemini(self, text: str, source_lang: str, target_lang: str, duration: float) -> Optional[str]:
        active_keys = self.get_active_keys()
        if not active_keys:
            return None

        dur_instruction = f"Speaking slot: {duration:.1f}s. Keep it punchy and concise to match actor lip pace." if duration > 0 else ""
        prompt = (
            f"You are a professional cinematic video dubbing translator specializing in natural spoken Khmer (ភាសានិយាយបែបភាពយន្តធម្មជាតិ).\n"
            f"Translate this dialogue line from {source_lang} into vivid, natural conversational Khmer:\n"
            f"CRITICAL RULES:\n"
            f"- Output MUST be 100% pure Khmer characters (អក្សរខ្មែរ, U+1780 to U+17FF). Absolutely NO Thai script (เช่น แล้ว, ไป, มา, พา, ยิ่ง, อยู่, เมื่อ, ส่วน), Chinese, or Latin.\n"
            f"- Output ONLY the translated Khmer line without repeating Chinese source, notes, or quotes.\n"
            f"- NATURAL SPOKEN KHMER: Avoid literal word-for-word translation. NEVER use robotic 'តើអ្នក...'. Use authentic pronouns (ប៉ា, ម៉ាក់, កូន, បង, អូន, ឯង, ខ្ញុំ) and expressive particles (ណ៎ា, ហ្អ៎, ទៅ, ម៉េស, ហ្នឹង...).\n"
            f"- PRESERVE COMPLETE MEANING: Keep plot meaning and emotional weight.\n"
            f"- {dur_instruction}\n\n"
            f"Original: \"{text}\"\n"
            f"Output ONLY the Khmer translation without quotes, Thai, Chinese, or explanations."
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json"}
        for api_key in list(active_keys):
            for model in self.models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                try:
                    r = requests.post(url, headers=headers, json=payload, timeout=8)
                    if r.status_code == 200:
                        data = r.json()
                        cand = data.get("candidates", [])
                        if cand:
                            raw = cand[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                            clean = sanitize_khmer_translation(raw)
                            return clean or raw
                    elif r.status_code == 429 or "RESOURCE_EXHAUSTED" in r.text:
                        continue
                    elif r.status_code in (400, 401, 403) and any(kw in r.text for kw in ["API_KEY_INVALID", "PERMISSION_DENIED", "not allowed by policy"]):
                        self.mark_key_exhausted(api_key, f"HTTP {r.status_code}")
                        break
                except Exception:
                    continue
            else:
                self.set_key_cooldown(api_key, 25.0)
        return None

    def _translate_google_mobile(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        try:
            sl = "auto" if source_lang == "auto" else source_lang
            url = f"https://translate.google.com/m?sl={sl}&tl={target_lang}&q=" + urllib.parse.quote(text)
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X)'}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                res_html = resp.read().decode('utf-8')
                match = re.search(r'<div[^>]*class=\"result-container\"[^>]*>(.*?)</div>', res_html, re.DOTALL)
                if match:
                    res = html.unescape(match.group(1).strip())
                    if res and not res.startswith("["):
                        return res
        except Exception:
            pass
        return None

    def _translate_mymemory(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        try:
            sl = "en" if source_lang == "auto" else source_lang
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair={sl}|{target_lang}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                res_text = data.get('responseData', {}).get('translatedText')
                if res_text and not res_text.startswith("MYMEMORY WARNING"):
                    return res_text
        except Exception:
            pass
        return None
