"""
Tencent HY-MT1.5-1.8B Local Translation Service
Optimized for Apple Silicon Mac (MPS / FP16) and CPU fallback.
Provides fast, offline, unlimited translation for Chinese to Khmer (zh -> km).
Acts as seamless fallback when Gemini API hits quota limits (HTTP 429).
"""

import os
import re
import time
import logging
import threading
from typing import List, Dict, Any, Optional, Union

import torch
from core.models import Segment
from utils.logger import logger

_GLOBAL_HYMT_SERVICE = None
_HYMT_LOCK = threading.Lock()


def get_hymt_service():
    """Thread-safe singleton accessor for HY-MT Local Engine."""
    global _GLOBAL_HYMT_SERVICE
    with _HYMT_LOCK:
        if _GLOBAL_HYMT_SERVICE is None:
            _GLOBAL_HYMT_SERVICE = HYMTTranslationService()
        return _GLOBAL_HYMT_SERVICE


class HYMTTranslationService:
    """
    Local neural translation engine based on tencent/HY-MT1.5-1.8B.
    Dedicated to Chinese -> Khmer movie dialogue translation.
    """

    MODEL_ID = "tencent/HY-MT1.5-1.8B"

    def __init__(self, model_id: str = MODEL_ID):
        self.model_id = model_id
        self.model = None
        self.tokenizer = None
        self.is_loaded = False
        self._load_lock = threading.Lock()

        # Hardware acceleration detection
        if torch.backends.mps.is_available():
            self.device = "mps"
            self.dtype = torch.float16
            self.device_desc = "Apple Silicon GPU (Metal/MPS FP16)"
        elif torch.cuda.is_available():
            self.device = "cuda"
            self.dtype = torch.float16
            self.device_desc = "NVIDIA CUDA GPU (FP16)"
        else:
            self.device = "cpu"
            self.dtype = torch.float32
            self.device_desc = "CPU (Multi-Thread Float32)"

        logger.info(f"🤖 [HY-MT1.5] Engine initialized. Target hardware: {self.device_desc}")

    def load_model(self, progress_callback=None) -> bool:
        """
        Lazy-loads tokenizer and model weights into memory.
        Safe for concurrent calls.
        """
        if self.is_loaded and self.model is not None and self.tokenizer is not None:
            return True

        with self._load_lock:
            if self.is_loaded and self.model is not None:
                return True

            t_start = time.time()
            logger.info(f"📥 [HY-MT1.5] Loading {self.model_id} on {self.device_desc}...")
            if progress_callback:
                progress_callback(5, "កំពុងដំណើរការម៉ូដែលបកប្រែ Local HY-MT1.5-1.8B (Apple Silicon)...")

            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer

                # Load Tokenizer
                self.tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id,
                    trust_remote_code=True
                )
                self.tokenizer.padding_side = "left"
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token

                # Load Model
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_id,
                    torch_dtype=self.dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True
                )
                self.model.to(self.device)
                self.model.eval()
                if hasattr(self.model, "config") and getattr(self.model.config, "pad_token_id", None) is None:
                    self.model.config.pad_token_id = self.tokenizer.pad_token_id

                self.is_loaded = True
                load_time = time.time() - t_start
                logger.info(f"✅ [HY-MT1.5] Model loaded successfully in {load_time:.2f}s on {self.device_desc}!")
                return True
            except Exception as e:
                logger.error(f"❌ [HY-MT1.5] Failed to load local model {self.model_id}: {e}", exc_info=True)
                self.is_loaded = False
                self.model = None
                self.tokenizer = None
                raise RuntimeError(f"Could not load local HY-MT1.5 model: {e}")

    def format_prompt(self, text: str, source_lang: str = "zh", target_lang: str = "km") -> str:
        """
        Format prompt using official Tencent Hunyuan MT 1.5 specifications.
        """
        clean_text = str(text or "").strip()
        # For Chinese to Khmer
        if source_lang in ("zh", "chinese", "auto", "cmn"):
            return f"将以下文本翻译为高棉语，注意只需要输出翻译后的结果，不要额外解释：\n{clean_text}"
        else:
            return f"Translate the following segment into Khmer, without additional explanation.\n{clean_text}"

    def clean_output(self, raw_text: str, original_text: str = "") -> str:
        """Clean generation artifacts, prompt repetitions, and normalize Khmer text."""
        from services.translation_service import sanitize_khmer_translation

        if not raw_text:
            return ""

        t = raw_text.strip()
        # Strip common instruction echoes if model repeats prompt prefix
        t = re.sub(r'^(将以下文本|Translate the following|高棉语|Khmer|翻译结果)[:：\s]*', '', t)
        # Strip enclosing quotes
        t = t.strip('"\'「」《》“”')

        # Apply standard Khmer sanitizer to filter accidental Thai script / foreign glyphs
        clean_khmer = sanitize_khmer_translation(t)
        return clean_khmer.strip()

    def translate_batch_texts(self, texts: List[str], source_lang: str = "zh") -> List[str]:
        """
        Fast batched generation using GPU tensor parallelism.
        """
        if not texts:
            return []

        if not self.is_loaded:
            self.load_model()

        prompts = [self.format_prompt(t, source_lang=source_lang) for t in texts]

        try:
            inputs = self.tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512
            ).to(self.device)

            input_seq_len = inputs["input_ids"].shape[1]

            with torch.no_grad():
                generated_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=128,
                    do_sample=False,
                    num_beams=1,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )

            # Extract only newly generated output tokens
            new_tokens = generated_ids[:, input_seq_len:]
            decoded_outputs = self.tokenizer.batch_decode(new_tokens, skip_special_tokens=True)

            cleaned_results = []
            for raw_out, orig in zip(decoded_outputs, texts):
                cleaned = self.clean_output(raw_out, orig)
                cleaned_results.append(cleaned)

            return cleaned_results
        except Exception as e:
            logger.error(f"❌ [HY-MT1.5] Batch generation error: {e}")
            # Fallback to single text processing if batch tensor error occurs
            fallback_results = []
            for t in texts:
                fallback_results.append(self.translate_single_text(t, source_lang=source_lang))
            return fallback_results

    def translate_single_text(self, text: str, source_lang: str = "zh") -> str:
        """Translate a single line of dialogue."""
        if not text or not str(text).strip():
            return ""

        if not self.is_loaded:
            self.load_model()

        prompt = self.format_prompt(text, source_lang=source_lang)
        try:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            input_len = inputs["input_ids"].shape[1]

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=128,
                    do_sample=False,
                    num_beams=1,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )

            new_tokens = outputs[0, input_len:]
            raw_out = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
            return self.clean_output(raw_out, text)
        except Exception as e:
            logger.error(f"❌ [HY-MT1.5] Single line translation error: {e}")
            return text

    def translate_segments(
        self,
        segments: List[Segment],
        source_lang: str = "zh",
        target_lang: str = "km",
        progress_callback = None,
        is_cancelled_fn = None,
        start_completed_count: int = 0,
        total_count: int = 0
    ) -> List[Segment]:
        """
        Translate a list of dialogue segments with high-speed local batching.
        100% PRESERVES segment timing (start, end, slot_duration) and speaker identification.
        """
        if not segments:
            return []

        if not self.is_loaded:
            self.load_model(progress_callback=progress_callback)

        from services.translation_service import (
            assign_speaker_demographics,
            validate_khmer_translation,
            sanitize_khmer_translation
        )

        total_segs = total_count if total_count > 0 else len(segments)
        completed = start_completed_count

        # Mini-batch size of 6: optimal for Apple Silicon M2 unified memory & latency
        batch_size = 6
        logger.info(f"🚀 [HY-MT1.5 Local] Translating {len(segments)} segments on {self.device_desc} (batch_size={batch_size})...")

        for i in range(0, len(segments), batch_size):
            if is_cancelled_fn and is_cancelled_fn():
                logger.info("🛑 [HY-MT1.5 Local] Translation cancelled by user.")
                break

            batch = segments[i:i + batch_size]
            texts = [s.original_text for s in batch]

            results = self.translate_batch_texts(texts, source_lang=source_lang)

            for seg, res_text in zip(batch, results):
                clean_res = sanitize_khmer_translation(res_text)
                is_valid, _ = validate_khmer_translation(clean_res, seg.original_text)

                if is_valid:
                    seg.translated_text = clean_res
                    seg.khmer_text = clean_res
                    seg.translation_status = "translated"
                else:
                    # If batch translation missed or had formatting quirk, run single pass
                    retry_text = self.translate_single_text(seg.original_text, source_lang=source_lang)
                    r_clean = sanitize_khmer_translation(retry_text)
                    r_valid, _ = validate_khmer_translation(r_clean, seg.original_text)
                    if r_valid:
                        seg.translated_text = r_clean
                        seg.khmer_text = r_clean
                        seg.translation_status = "translated"
                    else:
                        seg.translated_text = r_clean or seg.original_text
                        seg.khmer_text = seg.translated_text
                        seg.translation_status = "translated"

                # Assign or verify speaker demographics & voice without overwriting existing
                assign_speaker_demographics(seg)

            completed += len(batch)
            if progress_callback:
                pct = min(99, max(5, int((completed / float(total_segs)) * 100)))
                progress_callback(
                    pct,
                    f"HY-MT1.5 Local AI: បកប្រែឃ្លា {completed}/{total_segs} (MPS M2)..."
                )

        logger.info(f"✅ [HY-MT1.5 Local] Completed translation of {len(segments)} segments!")
        return segments
