# services/character_voice_manager.py
import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import asdict
from utils.logger import logger
from services.voice_prompt_processor import VoiceProfile, VoicePromptProcessor

class CharacterVoiceManager:
    """
    Manage Character Voice Profiles for consistent multi-character dubbing.
    Persists profiles in storage/characters/*.json.
    """
    
    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or (Path(__file__).resolve().parent.parent / "storage" / "characters")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._characters_cache: Dict[str, VoiceProfile] = {}
        self._load_cached_characters()
    
    def _load_cached_characters(self):
        """Load all character profiles from storage."""
        for file_path in self.storage_dir.glob("*.json"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    profile = VoiceProfile(**data)
                    self._characters_cache[profile.name] = profile
            except Exception as e:
                logger.warning(f"Failed to load character {file_path}: {e}")
    
    def create_character(
        self,
        name: str,
        voice_prompt: str,
        reference_audio: Optional[str] = None,
        reference_text: Optional[str] = None,
        gender: Optional[str] = None,
        age: Optional[str] = None
    ) -> VoiceProfile:
        """
        Create a new character from voice prompt.
        """
        profile = VoicePromptProcessor.process_prompt(voice_prompt, name)
        
        if gender:
            profile.gender = gender
        if age:
            profile.age = age
        
        if reference_audio and os.path.exists(reference_audio):
            profile.reference_audio = reference_audio
            profile.reference_text = reference_text or ""
            profile.is_clone = True
        
        self._save_character(profile)
        self._characters_cache[profile.name] = profile
        logger.info(f"✅ Created character '{name}' with voice profile")
        return profile
    
    def _save_character(self, profile: VoiceProfile):
        """Save character profile to storage."""
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in profile.name)
        file_path = self.storage_dir / f"{safe_name}.json"
        
        data = asdict(profile)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_character(self, name: str) -> Optional[VoiceProfile]:
        """Get character profile by name."""
        if name in self._characters_cache:
            return self._characters_cache[name]
        
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        file_path = self.storage_dir / f"{safe_name}.json"
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    profile = VoiceProfile(**data)
                    self._characters_cache[name] = profile
                    return profile
            except Exception as e:
                logger.error(f"Failed to load character '{name}': {e}")
        return None
    
    def list_characters(self) -> List[str]:
        """List all character names."""
        return list(self._characters_cache.keys())
    
    def delete_character(self, name: str) -> bool:
        """Delete a character profile."""
        if name not in self._characters_cache:
            return False
        
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        file_path = self.storage_dir / f"{safe_name}.json"
        if file_path.exists():
            file_path.unlink()
        
        del self._characters_cache[name]
        logger.info(f"🗑️ Deleted character '{name}'")
        return True
    
    def get_voxcpm_preset(self, name: str) -> Optional[Dict]:
        """
        Get VoxCPM2 preset dictionary for a character.
        """
        profile = self.get_character(name)
        if not profile:
            return None
        
        return VoicePromptProcessor.profile_to_voxcpm_preset(
            profile,
            reference_audio=profile.reference_audio,
            reference_text=profile.reference_text
        )
