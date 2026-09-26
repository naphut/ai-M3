import os
import subprocess
from utils.logger import logger
from utils.file_utils import get_temp_path

class AudioExtractor:
    """
    Dedicated Audio Extractor Service.
    Extracts 16kHz Mono PCM WAV audio from input video files for Speech & Voice Processing.
    """
    def __init__(self, sample_rate: int = 16000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels

    def extract_audio(self, video_path: str, output_audio_path: str = None) -> str:
        """
        Extract audio from video file using FFmpeg.
        Returns path to extracted 16kHz PCM Mono WAV file.
        """
        if not video_path or not os.path.exists(video_path):
            logger.error(f"❌ AudioExtractor error: Video file not found: {video_path}")
            return None

        if not output_audio_path:
            output_audio_path = get_temp_path("original_audio.wav")

        os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            output_audio_path
        ]

        try:
            logger.info(f"🎬 [AudioExtractor] Extracting audio from video: {os.path.basename(video_path)}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0:
                logger.info(f"✅ [AudioExtractor] Audio extracted: {os.path.basename(output_audio_path)}")
                return output_audio_path
            else:
                logger.error(f"❌ [AudioExtractor] FFmpeg error: {res.stderr}")
                return None
        except Exception as e:
            logger.error(f"❌ [AudioExtractor] Exception during extraction: {e}")
            return None
