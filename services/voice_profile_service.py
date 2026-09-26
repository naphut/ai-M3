import os
import json
import shutil
from pathlib import Path
from utils.logger import logger
from services.voice_cleaner import VoiceCleaner
from services.whisper_service import WhisperService

class VoiceProfileService:
    """
    Dedicated Voice Profile & Storage Service.
    Manages persistent voice profiles in storage/voices/<voice_id>/ with metadata.json and reference.wav.
    """
    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or (Path(__file__).resolve().parent.parent / "storage" / "voices")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cleaner = VoiceCleaner()

    def create_voice_profile(
        self,
        name: str,
        reference_audio_path: str,
        prompt_text: str = "",
        gender: str = "female",
        age: str = "adult"
    ) -> dict:
        """
        Create a new persistent Voice Profile directory storage/voices/<voice_id>/.
        Cleans audio, transcribes prompt text via Whisper if missing, and saves metadata.json.
        """
        if not reference_audio_path or not os.path.exists(reference_audio_path):
            logger.error(f"❌ [VoiceProfileService] Cannot create profile: Reference audio missing!")
            return None

        # Sanitize voice ID
        clean_name = "".join([c if c.isalnum() else "_" for c in name.lower()]).strip("_")
        voice_id = f"voice_{clean_name}" if not clean_name.startswith("voice_") else clean_name
        profile_dir = self.storage_dir / voice_id
        profile_dir.mkdir(parents=True, exist_ok=True)

        ref_target = profile_dir / "reference.wav"
        cleaned_wav = self.cleaner.clean_reference_audio(reference_audio_path, str(ref_target))
        if not cleaned_wav or not os.path.exists(cleaned_wav):
            logger.error(f"❌ [VoiceProfileService] Failed to clean reference audio for voice '{name}'")
            return None

        # Auto Whisper STT for prompt_text if empty
        if not prompt_text.strip():
            try:
                whisper_svc = WhisperService(model_size="base")
                prompt_text = whisper_svc.transcribe_reference(str(ref_target))
                logger.info(f"📝 [VoiceProfileService] Whisper auto-transcribed prompt text: '{prompt_text[:50]}...'")
            except Exception as e:
                logger.debug(f"Prompt text auto-transcription exception: {e}")

        # Save reference.txt
        txt_target = profile_dir / "reference.txt"
        with open(txt_target, "w", encoding="utf-8") as tf:
            tf.write(prompt_text or "")

        metadata = {
            "voice_id": voice_id,
            "name": name,
            "language": "km",
            "reference_audio": "reference.wav",
            "reference_text": "reference.txt",
            "reference_audio_path": str(ref_target),
            "prompt_text": prompt_text,
            "gender": gender,
            "age": age,
            "status": "ready",
            "is_clone": True
        }

        meta_file = profile_dir / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ [VoiceProfileService] Created Voice Profile: '{voice_id}' in '{profile_dir}'")
        return metadata

    def get_voice_profile(self, voice_id: str) -> dict:
        """Load Voice Profile metadata by ID."""
        profile_dir = self.storage_dir / voice_id
        meta_file = profile_dir / "metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ [VoiceProfileService] Error reading metadata for '{voice_id}': {e}")
        return None

    def list_voice_profiles(self) -> list:
        """List all persistent voice profiles stored in storage/voices/."""
        profiles = []
        for pdir in self.storage_dir.iterdir():
            if pdir.is_dir():
                mfile = pdir / "metadata.json"
                if mfile.exists():
                    try:
                        with open(mfile, "r", encoding="utf-8") as f:
                            profiles.append(json.load(f))
                    except Exception: pass
        return profiles
