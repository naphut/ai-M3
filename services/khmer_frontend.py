# services/khmer_frontend.py
"""
Khmer TTS Frontend & Text Normalizer
Fine-tuned Khmer TTS text preprocessing:
1. Unicode NFC normalization & confusable characters
2. Comprehensive number-to-Khmer words expansion (0-9, ០-៩, decimals, %, ៛, $)
3. Accurate HarfBuzz/Khmer Unicode syllable segmentation
4. Sentence and conjunction-aware text chunking for natural speech flow
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import List, Tuple, Optional
from utils.logger import logger

ZWNJ = "‌"
ZWJ = "‍"

_CONFUSABLES = str.maketrans({"็": "៏", "ํ": "ំ"})
_UNSPOKEN = str.maketrans({c: " " for c in "–—‑()[]{}«»<>|/*_~#@^&+="})

_UNITS = ["សូន្យ", "មួយ", "ពីរ", "បី", "បួន", "ប្រាំ",
          "ប្រាំមួយ", "ប្រាំពីរ", "ប្រាំបី", "ប្រាំបួន"]
_TENS = ["", "ដប់", "ម្ភៃ", "សាមសិប", "សែសិប", "ហាសិប",
         "ហុកសិប", "ចិតសិប", "ប៉ែតសិប", "កៅសិប"]
_KH_DIGITS = str.maketrans("០១២៣៤៥៦៧៨៩", "0123456789")

_SENT_END = "។៕!?…\n"
_NEVER_BEFORE = ("ខែ", "ឆ្នាំ", "នាទី", "ម៉ោង", "រៀល", "ដុល្លារ", "នាក់", "ភាគរយ", "ក្បាល", "កន្លែង", "ដើម")
_GOOD_BEFORE = ("នៅ", "កាលពី", "ដោយ", "ដែល", "និង", "ព្រោះ", "ដើម្បី",
                "បន្ទាប់", "ក្នុង", "ចំពោះ", "តាម", "រួម", "ប៉ុន្តែ", "ហើយ")
_DEPENDENT = set("ាិីឹឺុូួើឿៀេែៃោៅំះៈ៉៊់៌៍៎៏័៑្")


def normalize(text: str) -> str:
    """Normalize Khmer text: NFC Unicode, translate confusables, strip unspoken chars."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_CONFUSABLES).translate(_UNSPOKEN)
    text = text.replace(ZWNJ, "").replace(ZWJ, "")
    return " ".join(text.split())


def int_to_khmer(n: int) -> str:
    """Convert an integer into spoken Khmer words."""
    if n < 0:
        return "ដក" + int_to_khmer(-n)
    if n < 10:
        return _UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return _TENS[tens] + (_UNITS[unit] if unit else "")
    for value, word in ((1_000_000_000, "ពាន់លាន"),
                        (1_000_000, "លាន"),
                        (100_000, "សែន"),
                        (10_000, "ម៉ឺន"),
                        (1_000, "ពាន់"),
                        (100, "រយ")):
        if n >= value:
            head, rest = divmod(n, value)
            return int_to_khmer(head) + word + (int_to_khmer(rest) if rest else "")
    return _UNITS[0]


def _read_number(token: str) -> str:
    """Read numeric tokens including currency, percentages, and decimals."""
    token = token.translate(_KH_DIGITS).replace(",", "")
    suffix = ""
    prefix = ""
    
    if token.startswith("$"):
        token = token[1:]
        suffix = "ដុល្លារ"
    elif token.endswith("$"):
        token = token[:-1]
        suffix = "ដុល្លារ"
    elif token.endswith("៛"):
        token = token[:-1]
        suffix = "រៀល"
    elif token.endswith("%"):
        token = token[:-1]
        suffix = "ភាគរយ"
        
    if "." in token:
        parts = token.split(".", 1)
        whole = parts[0]
        frac = parts[1] if len(parts) > 1 else ""
        words = int_to_khmer(int(whole or 0)) + "ក្បៀស" +             "".join(_UNITS[int(d)] for d in frac if d.isdigit())
    else:
        try:
            words = int_to_khmer(int(token)) if token else ""
        except ValueError:
            words = token
            
    return prefix + words + suffix


_NUM_RE = re.compile(r"[\$]?[0-9០-៩][0-9០-៩,]*(?:\.[0-9០-៩]+)?(?:%|៛|\$)?")


def normalize_numbers(text: str) -> str:
    """Replace all numbers, currency, and percentages with Khmer spoken words."""
    if not text:
        return ""
    text = _NUM_RE.sub(lambda m: _read_number(m.group(0)), text)
    text = text.replace("៛", "រៀល").replace("$", "ដុល្លារ")
    return text


def _split_syllables(chunk: str) -> List[str]:
    """Split Khmer text into syllables respecting subscript consonants (្) and vowels."""
    out, cur, i, n = [], "", 0, len(chunk)
    while i < n:
        ch = chunk[i]
        if ch == "្":
            cur += ch
            if i + 1 < n:
                cur += chunk[i + 1]
                i += 2
                continue
            i += 1
            continue
        if ch in _DEPENDENT:
            cur += ch
            i += 1
            continue
        if cur:
            out.append(cur)
        cur = ch
        i += 1
    if cur:
        out.append(cur)
    return out


def _safe_cut(text: str, limit: int) -> int:
    """Find the best natural split point for Khmer text within limit characters."""
    spaces = [i for i, c in enumerate(text[: limit + 1]) if c == " "]
    if spaces:
        def nxt(i):
            return text[i + 1: i + 12].lstrip()
        allowed = [i for i in spaces if not nxt(i).startswith(_NEVER_BEFORE)]
        if allowed:
            good = [i for i in allowed if i >= limit * 0.4 and nxt(i).startswith(_GOOD_BEFORE)]
            return max(good) if good else max(allowed)
        return max(spaces)
    n = 0
    for syl in _split_syllables(text):
        if n + len(syl) > limit and n:
            return n
        n += len(syl)
    return len(text)


def chunk_khmer_text(text: str, max_chars: int = 110) -> List[str]:
    """
    Intelligently chunk Khmer text at punctuation and natural conjunction boundaries.
    """
    text = normalize_numbers(normalize(text))
    sentences, cur = [], ""
    for ch in text:
        cur += ch
        if ch in _SENT_END:
            if cur.strip():
                sentences.append(cur.strip())
            cur = ""
    if cur.strip():
        sentences.append(cur.strip())

    sentence_max = 220
    chunks, buf = [], ""
    for s in sentences:
        if len(s) > sentence_max:
            if buf:
                chunks.append(buf)
                buf = ""
            while len(s) > sentence_max:
                cut = _safe_cut(s, sentence_max)
                chunks.append(s[:cut].strip())
                s = s[cut:].strip()
            if s.strip():
                chunks.append(s.strip())
            continue
            
        if buf and len(buf) + len(s) + 1 > max_chars:
            chunks.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip() if buf else s
            
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c] or [text]


def preprocess_khmer_tts_text(text: str) -> str:
    """
    Unified entry point for preparing raw Khmer text for high-fidelity TTS generation.
    Expands all numbers, currencies, percentages, and normalizes Unicode.
    """
    if not text:
        return ""
    norm = normalize(text)
    expanded = normalize_numbers(norm)
    return expanded
