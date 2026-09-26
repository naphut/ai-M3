from services.translation_service import TranslationService
from utils.logger import logger

class Translator:
    def __init__(self, api_key: str = None):
        self.service = TranslationService(api_key=api_key)

    def process(self, segments: list, source_lang: str = "en", target_lang: str = "km") -> list:
        """
        Translate transcript segments into target language (Khmer).
        """
        logger.info(f"Translating {len(segments)} segments from {source_lang} -> {target_lang}...")
        translated = self.service.translate_segments(segments, source_lang=source_lang, target_lang=target_lang)
        logger.info("Translation completed successfully!")
        return translated
