import os
import json
import time
import base64
import re
import subprocess
from pathlib import Path
import requests
from utils.logger import logger
from utils.config_manager import get_gemini_api_key
from utils.file_utils import get_temp_path

class GeminiAudioService:
    """
    Enterprise-Grade Gemini Multimodal Audio AI Service.
    Supports arbitrarily long videos (1 minute to 3+ hours) via intelligent 5-minute chunking.
    Directly ingests vocal tracks and outputs precise timestamps, speaker diarization,
    original transcript, and fluent spoken Khmer translations.
    """
    def __init__(self, api_key: str = None):
        self.api_key = api_key or get_gemini_api_key()
        # Active Google Gemini models in 2026 (gemini-3.6-flash is recommended by Google)
        self.models = [
            "gemini-3.6-flash",
            "gemini-3.1-pro-preview",
            "gemini-3.6-pro"
        ]

    def _get_audio_duration(self, audio_path: str) -> float:
        """Get duration in seconds of audio using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get audio duration with ffprobe: {e}")
        return 0.0

    def _compress_to_lightweight_mp3(self, audio_path: str) -> str:
        """
        Compress audio to 16kHz mono 32k MP3.
        Keeps file size tiny (1 hour = ~12 MB) while preserving 100% speech fidelity.
        """
        mp3_path = get_temp_path("gemini_vocal_compressed.mp3")
        try:
            cmd = [
                "ffmpeg", "-y", "-i", audio_path,
                "-vn", "-ar", "16000", "-ac", "1",
                "-b:a", "32k",
                mp3_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                logger.info(f"Compressed audio for Gemini: {os.path.getsize(mp3_path) / 1024:.1f} KB")
                return mp3_path
        except Exception as e:
            logger.warning(f"Audio compression error: {e}, falling back to original audio.")
        return audio_path

    def process_audio(self, audio_path: str, source_lang: str = "auto", target_lang: str = "km", progress_callback=None) -> list:
        """
        Transcribe and translate audio directly into Khmer subtitle segments using Gemini AI.
        Automatically chunks long audio files (>6 mins) to guarantee fast, reliable processing.
        """
        if not audio_path or not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        api_key = self.api_key or get_gemini_api_key()
        if not api_key:
            raise ValueError(
                "Gemini API Key is not configured! Please click '🔑 Gemini API Key' and enter a valid key from https://aistudio.google.com/app/apikey"
            )

        if progress_callback:
            progress_callback(10, "Optimizing and compressing audio for Gemini AI...")

        compressed_mp3 = self._compress_to_lightweight_mp3(audio_path)
        total_duration = self._get_audio_duration(compressed_mp3)
        logger.info(f"Total audio duration: {total_duration:.1f}s ({total_duration/60:.1f} mins)")

        # Chunking strategy: 300 seconds (5 minutes) per chunk for maximum speed and zero timeout
        chunk_duration = 300.0
        if total_duration > 360.0:
            num_chunks = int(total_duration // chunk_duration) + (1 if total_duration % chunk_duration > 0 else 0)
        else:
            num_chunks = 1

        all_segments = []

        for idx in range(num_chunks):
            start_sec = idx * chunk_duration
            dur_sec = min(chunk_duration, total_duration - start_sec) if total_duration > 0 else chunk_duration

            if num_chunks > 1:
                chunk_file = get_temp_path(f"gemini_chunk_{idx:03d}.mp3")
                cmd = [
                    "ffmpeg", "-y", "-ss", str(start_sec), "-t", str(dur_sec),
                    "-i", compressed_mp3, "-c", "copy", chunk_file
                ]
                subprocess.run(cmd, capture_output=True, check=False)
                active_audio_path = chunk_file if os.path.exists(chunk_file) else compressed_mp3
                progress_pct = int(15 + (idx / float(num_chunks)) * 80)
                status_msg = f"Gemini Cloud AI: Processing Part {idx + 1}/{num_chunks} ({int(start_sec//60)}m - {int((start_sec+dur_sec)//60)}m)..."
            else:
                active_audio_path = compressed_mp3
                progress_pct = 35
                status_msg = "Gemini Cloud AI: Transcribing and translating speech to Khmer..."

            if progress_callback:
                progress_callback(progress_pct, status_msg)

            # Process single chunk with Gemini
            chunk_segs = self._process_single_audio_file(active_audio_path, api_key=api_key)

            # Adjust timestamps relative to total video timeline
            for seg in chunk_segs:
                seg["start"] = round(seg["start"] + start_sec, 2)
                seg["end"] = round(seg["end"] + start_sec, 2)
                all_segments.append(seg)

        if progress_callback:
            progress_callback(100, f"Gemini Audio Complete! {len(all_segments)} segments generated.")

        return all_segments

    def _process_single_audio_file(self, audio_file: str, api_key: str) -> list:
        """Call Gemini generateContent with inline audio data and return structured segments."""
        with open(audio_file, "rb") as f:
            audio_bytes = f.read()
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        prompt = (
            "You are an expert audio transcriptionist and professional video dubbing translator specializing in natural spoken Khmer.\n"
            "Listen to this audio track carefully and perform 3 tasks:\n"
            "1. Accurately transcribe every spoken sentence with exact start and end timestamps in seconds (e.g. 1.25).\n"
            "2. Identify speakers (Character: 'Speaker 1', 'Speaker 2', 'Narrator', 'Man', 'Woman', etc.).\n"
            "3. Translate every dialogue directly into fluent, conversational, natural spoken Khmer (ភាសានិយាយបែបធម្មជាតិ ពិរោះ រលូន សមស្របនឹងការបញ្ចូលសម្លេង Dubbing).\n\n"
            "CRITICAL DUBBING CONSTRAINT: The Khmer translation must fit comfortably within the exact speaking duration (end - start seconds) of the original line. Keep phrasing concise, impactful, and natural so that when synthesized via TTS it perfectly synchronizes with the speaker's on-screen pacing without requiring excessive speedup.\n\n"
            "Respond ONLY with a valid JSON array of objects with these exact keys:\n"
            "[\n"
            "  {\n"
            "    \"start\": 0.00,\n"
            "    \"end\": 2.50,\n"
            "    \"character\": \"Speaker 1\",\n"
            "    \"original_text\": \"Hello everyone, welcome back.\",\n"
            "    \"khmer_text\": \"សួស្តីអ្នកទាំងអស់គ្នា សូមស្វាគមន៍ការវិលត្រឡប់មកវិញ។\"\n"
            "  }\n"
            "]\n"
            "Do not output markdown code blocks or explanations, return ONLY the raw JSON array."
        )

        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/mp3",
                            "data": audio_b64
                        }
                    },
                    {
                        "text": prompt
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json"
            }
        }

        last_error = ""
        for model in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    retry_label = f" (Attempt {attempt+1}/{max_retries})" if attempt > 0 else ""
                    logger.info(f"🌐 Calling Gemini Audio AI ({model}){retry_label}...")
                    resp = requests.post(url, headers=headers, json=payload, timeout=90)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            text_res = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            segments = self._parse_json_segments(text_res)
                            if segments:
                                logger.info(f"✅ Gemini Audio ({model}) processed {len(segments)} segments successfully!")
                                return segments
                    elif resp.status_code in [503, 429]:
                        err_msg = resp.text[:200]
                        logger.warning(f"⚠️ Gemini {model} returned HTTP {resp.status_code} (High Demand).")
                        if attempt < max_retries - 1:
                            wait_s = 3.0 * (attempt + 1)
                            logger.info(f"⏳ Waiting {wait_s:.1f}s before retrying {model}...")
                            time.sleep(wait_s)
                            continue
                        else:
                            last_error = f"Gemini {model} high demand: {err_msg}"
                            break
                    else:
                        err_msg = resp.text[:250]
                        last_error = f"Gemini {model} returned HTTP {resp.status_code}: {err_msg}"
                        logger.warning(last_error)
                        break  # For 404 or other non-transient errors, immediately try next model
                except Exception as e:
                    last_error = f"Gemini {model} exception: {e}"
                    logger.warning(last_error)
                    if attempt < max_retries - 1:
                        time.sleep(2.5)
                        continue
                    break

        raise RuntimeError(f"Gemini Audio failed: {last_error}")

    def _parse_json_segments(self, raw_text: str) -> list:
        """Parse and sanitize JSON array returned by Gemini."""
        clean = raw_text.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*", "", clean)
            clean = re.sub(r"\s*```$", "", clean)
        
        try:
            data = json.loads(clean)
        except Exception:
            m = re.search(r"\[\s*\{.*\}\s*\]", clean, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
            else:
                raise ValueError("Could not parse JSON array from Gemini response.")

        if not isinstance(data, list):
            raise ValueError("Expected JSON array from Gemini response.")

        parsed_segments = []
        for i, item in enumerate(data):
            st = float(item.get("start", i * 3.0))
            et = float(item.get("end", st + 2.5))
            if et <= st:
                et = st + 2.0
            
            orig = str(item.get("original_text", "")).strip()
            khmer = str(item.get("khmer_text", "")).strip()
            char = str(item.get("character", f"Speaker {1 + (i % 2)}")).strip()

            parsed_segments.append({
                "start": round(st, 2),
                "end": round(et, 2),
                "character": char,
                "original_text": orig,
                "khmer_text": khmer,
                "text": orig
            })

        return parsed_segments
