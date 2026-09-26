from services.stt_service import STTService
from utils.logger import logger

class Transcriber:
    def __init__(self, model_size: str = "gemini", api_key: str = None):
        self.service = STTService(api_key=api_key)

    def process(self, audio_path: str, language: str = "auto") -> list:
        """
        Transcribe input audio into timestamped segments with high accuracy using Gemini STT with VAD.
        Returns list of segment dicts: [{'id': int, 'start': float, 'end': float, 'text': str, ...}]
        """
        logger.info(f"Starting VAD + Gemini Dedicated STT on {audio_path} (lang={language})...")
        segments = self.service.transcribe(audio_path, source_lang=language)
        logger.info(f"STT processing completed! Generated {len(segments)} timestamped segments.")
        return segments

