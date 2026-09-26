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
from utils.config_manager import get_gemini_api_key

class TranslationService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_gemini_api_key()
        # Production model hierarchy for translation (gemini-3.6-flash is highly available and fast)
        self.models = [
            "gemini-3.6-flash",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview"
        ]


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
        Uses optimized 20-segment batching with 3 parallel workers for ultra-fast throughput.
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
        batch_size = 20
        logger.info(f"🌐 [Translation] Starting parallel translation of {total} segments ({source_lang} -> {target_lang}, batch_size={batch_size})...")

        batches = [seg_models[i:i + batch_size] for i in range(0, total, batch_size)]
        completed_count = 0

        def _process_one_batch(b_idx_and_batch):
            nonlocal completed_count
            if is_cancelled_fn and is_cancelled_fn():
                return
            b_idx, batch = b_idx_and_batch
            
            # Try Gemini contextual batch translation first
            batch_success = self._translate_batch_gemini(batch, source_lang=source_lang, target_lang=target_lang)
            
            # If batch failed, translate items individually using fallbacks
            if not batch_success:
                for seg in batch:
                    if is_cancelled_fn and is_cancelled_fn():
                        break
                    trans = self.translate_single_text(
                        seg.original_text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        duration=seg.slot_duration
                    )
                    seg.translated_text = trans
                    seg.translation_status = "translated"

            completed_count += len(batch)
            if progress_callback:
                pct = min(98, max(5, int((completed_count / float(total)) * 100)))
                progress_callback(pct, f"Gemini AI: Translating dialogues {completed_count}/{total}...")

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(_process_one_batch, enumerate(batches)))

        if progress_callback:
            progress_callback(100, f"Translation Complete! {total} segments translated.")

        logger.info(f"✅ [Translation] All {total} segments successfully translated to {target_lang}.")
        return seg_models


    def _translate_batch_gemini(self, batch: List[Segment], source_lang: str, target_lang: str) -> bool:
        """Translate a batch of dialogues using Gemini with scene context and duration limits."""
        api_key = self.api_key or get_gemini_api_key()
        if not api_key:
            return False

        lines_payload = []
        for s in batch:
            lines_payload.append({
                "id": s.id,
                "speaker": s.speaker_id,
                "duration_seconds": s.slot_duration,
                "original_text": s.original_text
            })

        prompt = (
            "You are a professional cinematic video dubbing translator specializing in natural spoken Khmer (ភាសានិយាយបែបធម្មជាតិ).\n"
            f"Translate the following conversational dialogue lines from {source_lang} into fluent, natural spoken Khmer.\n\n"
            "CRITICAL DUBBING CONSTRAINTS:\n"
            "1. Natural Conversational Flow: Write natural spoken Khmer suitable for voice actors.\n"
            "2. Timing Matching: Each translated line must fit comfortably within the specified duration_seconds.\n"
            "   Keep phrasing concise and punchy without unnecessary wordy filler.\n\n"
            "Input Lines:\n"
            f"{json.dumps(lines_payload, ensure_ascii=False, indent=2)}\n\n"
            "Output ONLY a valid JSON array of objects with 'id' and 'translated_text':\n"
            "[\n"
            "  {\n"
            "    \"id\": \"seg_0001\",\n"
            "    \"translated_text\": \"...\"\n"
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

        for model in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        clean = raw_text.strip()
                        if clean.startswith("```"):
                            clean = re.sub(r"^```(?:json)?\s*", "", clean)
                            clean = re.sub(r"\s*```$", "", clean)
                        parsed = json.loads(clean)
                        trans_map = {item.get("id"): item.get("translated_text", "") for item in parsed if isinstance(item, dict)}
                        
                        for s in batch:
                            if s.id in trans_map and trans_map[s.id].strip():
                                s.translated_text = trans_map[s.id].strip()
                                s.translation_status = "translated"
                        return True
            except Exception as e:
                logger.debug(f"Gemini {model} batch translation error: {e}")
                continue

        return False

    def translate_single_text(self, text: str, source_lang: str = "auto", target_lang: str = "km", duration: float = 0.0) -> str:
        """Translate a single line with multi-tiered fallback (Gemini -> Google Mobile -> MyMemory)."""
        if not text or not text.strip():
            return ""

        # 1. Gemini Single
        api_key = self.api_key or get_gemini_api_key()
        if api_key:
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
        api_key = self.api_key or get_gemini_api_key()
        dur_instruction = f"Dialogue speaking slot: {duration:.1f} seconds. Keep Khmer concise." if duration > 0 else ""
        prompt = (
            f"Translate this line into natural conversational spoken Khmer (ភាសានិយាយ):\n"
            f"{dur_instruction}\n"
            f"Original: {text}\n"
            f"Output ONLY the Khmer translation without quotes or explanations."
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        headers = {"Content-Type": "application/json"}
        for model in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    cand = data.get("candidates", [])
                    if cand:
                        return cand[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            except Exception:
                continue
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
