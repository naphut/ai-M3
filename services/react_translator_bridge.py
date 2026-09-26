"""
Bridge between PySide6 Desktop Studio and React/Express AI Audio Translator (ai-M3).
Connects to http://localhost:3000/api/translate-audio to convert MP3/video directly
into natural Khmer SRT subtitles with high precision and speed.
"""
import os
import sys
import json
import time
import subprocess
import requests
from typing import List, Dict, Any, Optional, Tuple
from core.models import Segment
from utils.file_utils import get_output_path, get_temp_path, OUTPUT_DIR
from utils.logger import logger

REACT_SERVER_URL = "http://localhost:3000"
REACT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai-audio-translator")

class ReactTranslatorBridge:
    def __init__(self, base_url: str = REACT_SERVER_URL):
        self.base_url = base_url
        self._server_process = None

    def is_server_running(self) -> bool:
        """Check if React/Express backend is running and healthy."""
        try:
            r = requests.get(f"{self.base_url}/api/health", timeout=2.0)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:
            return False

    def ensure_server_running(self) -> bool:
        """Ensure React server is online, auto-spawning in background if needed."""
        if self.is_server_running():
            return True

        logger.info(f"🌐 [ReactBridge] React Translator Server is not running. Starting background server at {REACT_DIR}...")
        try:
            # Check if node_modules exists
            if not os.path.exists(os.path.join(REACT_DIR, "node_modules")):
                logger.info("🌐 [ReactBridge] Installing node_modules...")
                subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=REACT_DIR, check=False)

            # Start server via npm run dev as background process
            self._server_process = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=REACT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Wait up to 10 seconds for server to report healthy
            for _ in range(20):
                time.sleep(0.5)
                if self.is_server_running():
                    logger.info("✅ [ReactBridge] React Translator Server online at http://localhost:3000!")
                    return True
        except Exception as e:
            logger.error(f"❌ [ReactBridge] Failed to start React server: {e}")

        return self.is_server_running()

    def translate_audio(
        self,
        audio_or_video_path: str,
        source_lang: str = "Auto",
        target_lang: str = "Khmer",
        speed_mode: str = "turbo",
        progress_callback = None,
        is_cancelled_fn = None
    ) -> Tuple[List[Segment], str, str]:
        """
        Send MP3 audio to React/Express /api/translate-audio endpoint.
        Returns:
            - List of Segment objects (and dicts)
            - Path to saved subtitles_khmer.srt
            - Full raw SRT text string
        """
        if not os.path.exists(audio_or_video_path):
            raise FileNotFoundError(f"Audio file not found: {audio_or_video_path}")

        if not self.ensure_server_running():
            raise ConnectionError("Cannot connect to React Translator Server at http://localhost:3000")

        if progress_callback:
            progress_callback(15, "Connecting to React AI Engine (:3000)...")

        file_size_mb = os.path.getsize(audio_or_video_path) / (1024.0 * 1024.0)
        actual_upload_path = audio_or_video_path
        temp_speech_extracted = None

        ext = os.path.splitext(audio_or_video_path)[1].lower()
        if ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.m4v'] or file_size_mb > 25:
            if progress_callback:
                progress_callback(20, "⚡ Fast extracting speech audio for instant transfer...")
            import subprocess
            temp_speech_extracted = os.path.join(OUTPUT_DIR, f"speech_opt_{int(time.time())}.mp3")
            try:
                cmd = [
                    "ffmpeg", "-y", "-threads", "0", "-i", audio_or_video_path,
                    "-vn", "-ar", "16000", "-ac", "1", "-b:a", "24k",
                    temp_speech_extracted
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                actual_upload_path = temp_speech_extracted
                file_size_mb = os.path.getsize(actual_upload_path) / (1024.0 * 1024.0)
                logger.info(f"⚡ [ReactBridge] Pre-compressed speech to {file_size_mb:.1f} MB in < 2s")
            except Exception as e:
                logger.warning(f"Could not pre-compress speech mp3 locally: {e}")
                actual_upload_path = audio_or_video_path

        logger.info(f"🌐 [ReactBridge] Uploading {os.path.basename(actual_upload_path)} ({file_size_mb:.1f} MB) to React Engine...")

        if progress_callback:
            progress_callback(30, f"Sending audio to React Engine ({file_size_mb:.1f} MB)...")

        url = f"{self.base_url}/api/translate-audio"
        try:
            with open(actual_upload_path, "rb") as f:
                files = {"audioFile": (os.path.basename(actual_upload_path), f, "audio/mpeg")}
                data = {
                    "sourceLang": source_lang,
                    "targetLang": target_lang,
                    "speedMode": speed_mode
                }

                if progress_callback:
                    progress_callback(50, "React AI Engine: Speech extraction & Khmer SRT translation...")

                res = requests.post(url, files=files, data=data, timeout=360)
        finally:
            if temp_speech_extracted and os.path.exists(temp_speech_extracted):
                try:
                    os.unlink(temp_speech_extracted)
                except Exception:
                    pass

        if is_cancelled_fn and is_cancelled_fn():
            raise RuntimeError("Translation cancelled by user.")

        if res.status_code != 200:
            err_data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = err_data.get("error") or res.text or f"HTTP {res.status_code}"
            raise RuntimeError(f"React Engine translation error: {err_msg}")

        resp_json = res.json()
        raw_segments = resp_json.get("segments", [])
        srt_text = resp_json.get("srtText", "")

        if progress_callback:
            progress_callback(85, f"Received {len(raw_segments)} Khmer segments. Parsing timestamps...")

        # Convert to standardized Segment objects
        segments: List[Segment] = []
        for idx, s in enumerate(raw_segments):
            st = float(s.get("startSeconds", 0.0))
            et = float(s.get("endSeconds", st + 2.5))
            if et <= st:
                et = st + 2.5
            
            orig_text = (s.get("sourceText") or s.get("text") or "").strip()
            khmer_text = (s.get("translatedText") or s.get("khmer") or orig_text).strip()
            
            raw_gender = (s.get("gender") or "").lower().strip()
            orig_spk = str(s.get("speaker") or "").lower()
            if raw_gender == "female" or any(w in orig_spk for w in ['female', 'woman', 'girl', 'ស្រី']):
                gender = "female"
                spk = "👩 ស្រី"
                voice = "Khmer Female - Sreymom"
            elif raw_gender == "child" or any(w in orig_spk for w in ['child', 'kid', 'boy', 'baby', 'ក្មេង']):
                gender = "child"
                spk = "🧒 ក្មេង"
                voice = "Khmer Child - Boy (Vannak)"
            else:
                gender = "male"
                spk = "👨 ប្រុស"
                voice = "Khmer Male - Piseth"

            seg = Segment(
                id=f"seg_{idx+1:04d}",
                start=round(st, 2),
                end=round(et, 2),
                speaker_id=spk,
                source_language=resp_json.get("detectedLanguage", "en"),
                original_text=orig_text,
                target_language="km",
                translated_text=khmer_text,
                slot_duration=round(et - st, 2),
                translation_status="translated"
            )
            setattr(seg, "khmer_text", khmer_text)
            setattr(seg, "speaker", spk)
            setattr(seg, "character", spk)
            setattr(seg, "gender", gender)
            setattr(seg, "voice", voice)
            segments.append(seg)

        # Anti-collision / overlap resolution
        from services.stt_service import STTService
        stt = STTService()
        segments = stt._normalize_transcript_segments(segments)

        # Save SRT file in output directory
        base_stem = os.path.splitext(os.path.basename(audio_or_video_path))[0]
        out_srt_path = os.path.join(OUTPUT_DIR, f"{base_stem}_khmer.srt")
        with open(out_srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_text)

        logger.info(f"✅ [ReactBridge] Successfully received {len(segments)} Khmer segments! Saved SRT: {out_srt_path}")
        if progress_callback:
            progress_callback(100, f"Translation Complete! {len(segments)} Khmer segments ready.")

        return segments, out_srt_path, srt_text
