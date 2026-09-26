import os
import gc
import re
import json
import soundfile as sf
from dataclasses import dataclass, asdict
from pathlib import Path
from utils.logger import logger
from services.khmer_frontend import preprocess_khmer_tts_text

_SHARED_VOXCPM_INSTANCE = None

@dataclass
class VoiceGenerationConfig:
    gender: str = "male"          # male, female
    age: str = "adult"            # child, young, adult, middle_aged, elderly
    style: str = "natural"        # natural, conversational, professional, narrator, news, documentary
    emotion: str = "calm"         # neutral, friendly, happy, calm, serious, angry, sad
    pitch: str = "medium"         # low, medium_low, medium, medium_high, high
    speed: float = 1.0            # 0.8, 0.9, 1.0, 1.1, 1.2
    language: str = "km"          # km (Khmer)
    voice_description: str = ""   # User-editable or auto-generated natural prompt


DEFAULT_MALE_PROMPT = (
    "A natural adult male voice speaking Khmer. "
    "Age around 30–40 years old. "
    "Medium-low pitch, warm and realistic tone. "
    "Clear Khmer pronunciation. "
    "Natural breathing and pauses. "
    "Conversational and confident speaking style. "
    "Moderate speaking speed. "
    "Do not sound robotic or synthetic."
)

DEFAULT_FEMALE_PROMPT = (
    "A natural adult female voice speaking Khmer. "
    "Age around 25–35 years old. "
    "Medium-high pitch, warm and friendly tone. "
    "Very clear Khmer pronunciation. "
    "Natural breathing and realistic pauses. "
    "Conversational and expressive speaking style. "
    "Moderate speaking speed. "
    "Do not sound robotic."
)

DEFAULT_CHILD_PROMPT = (
    "A natural young Khmer boy voice. "
    "Age around 8–12 years old. "
    "Higher pitch with a youthful tone. "
    "Clear Khmer pronunciation. "
    "Energetic but natural. "
    "Natural breathing and pauses. "
    "Friendly conversational style. "
    "Do not sound robotic or exaggerated."
)

DEFAULT_ELDERLY_PROMPT = (
    "A natural elderly Khmer male voice. "
    "Age around 65–75 years old. "
    "Lower pitch with a mature and slightly aged vocal character. "
    "Calm, warm and realistic tone. "
    "Clear Khmer pronunciation. "
    "Slightly slower speaking speed. "
    "Natural breathing and pauses. "
    "Do not sound robotic."
)


class VoiceGenerationService:
    """
    Dedicated Voice Generation Service using OpenBMB VoxCPM2 Voice Design.
    Flow: User Prompt -> Prompt Parser -> Voice Profile Selection -> VoxCPM2 -> Khmer Speech WAV.
    """
    def __init__(self, model_dir: Path = None):
        self.model_dir = model_dir or (Path(__file__).resolve().parent.parent / "models" / "voxcpm2")
        self.presets_dir = Path(__file__).resolve().parent.parent / "storage" / "voice_presets"
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir = Path(__file__).resolve().parent.parent / "storage" / "generated"
        self.generated_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def parse_prompt_to_config(prompt_text: str) -> VoiceGenerationConfig:
        """
        NLU Prompt Parser:
        Extracts Gender, Age, Pitch, Tone, Emotion, Speed, and Style from natural text prompt.
        """
        p_lower = prompt_text.lower()
        
        # 1. Gender
        gender = "male"
        if re.search(r"\b(female|woman|girl|lady|mother|sister|ស្រី|នាង|កញ្ញា)\b", p_lower):
            gender = "female"
        elif re.search(r"\b(male|man|boy|gentleman|father|brother|ប្រុស|លោក|បុរស)\b", p_lower):
            gender = "male"

        # 2. Age
        age = "adult"
        if re.search(r"\b(boy|girl|child|kid|children|8-12|8–12|youthful|ក្មេង)\b", p_lower):
            age = "child"
        elif re.search(r"\b(elderly|grandfather|grandmother|grandpa|grandma|65-75|65–75|aged vocal|mature vocal|ចាស់|លោកតា|យាយ)\b", p_lower):
            age = "elderly"
        elif re.search(r"\b(young|teen|teenager|20s|25|យុវជន)\b", p_lower):
            age = "young"
        elif re.search(r"\b(adult|30-40|30–40|man|woman|ពេញវ័យ)\b", p_lower):
            age = "adult"

        # 3. Pitch
        pitch = "medium"
        if re.search(r"\b(very low|deep|ជ្រៅ|ធ្ងន់)\b", p_lower):
            pitch = "low"
        elif re.search(r"\b(medium-low|medium low|low pitch)\b", p_lower):
            pitch = "medium_low"
        elif re.search(r"\b(medium-high|medium high)\b", p_lower):
            pitch = "medium_high"
        elif re.search(r"\b(high pitch|higher pitch|high|ស្រួយ)\b", p_lower):
            pitch = "high"

        # 4. Emotion
        emotion = "calm"
        if re.search(r"\b(happy|cheerful|energetic|excited|រីករាយ)\b", p_lower):
            emotion = "happy"
        elif re.search(r"\b(sad|melancholic|sorrow|កម្សត់)\b", p_lower):
            emotion = "sad"
        elif re.search(r"\b(angry|intense|fierce|furious|ខឹង)\b", p_lower):
            emotion = "angry"
        elif re.search(r"\b(friendly|warm|kind|gentle|រួសរាយ|កក់ក្តៅ)\b", p_lower):
            emotion = "friendly"
        elif re.search(r"\b(calm|relaxed|peaceful|ស្ងប់)\b", p_lower):
            emotion = "calm"

        # 5. Speed
        speed = 1.0
        if re.search(r"\b(slow|slower|slowly|យឺត)\b", p_lower):
            speed = 0.85
        elif re.search(r"\b(fast|faster|quickly|quick|លឿន)\b", p_lower):
            speed = 1.15

        # 6. Style
        style = "conversational"
        if re.search(r"\b(narrator|documentary|news|broadcast|អត្ថាធិប្បាយ)\b", p_lower):
            style = "narrator"
        elif re.search(r"\b(storytelling|story|fairy tale|និទាន)\b", p_lower):
            style = "storytelling"

        return VoiceGenerationConfig(
            gender=gender,
            age=age,
            pitch=pitch,
            emotion=emotion,
            speed=speed,
            style=style,
            voice_description=prompt_text
        )

    def load_model(self):
        """Load VoxCPM2 model once as a singleton in memory."""
        global _SHARED_VOXCPM_INSTANCE
        if _SHARED_VOXCPM_INSTANCE is not None:
            return _SHARED_VOXCPM_INSTANCE

        from voxcpm import VoxCPM
        if (self.model_dir / "config.json").exists():
            model_path = str(self.model_dir)
        else:
            model_path = "openbmb/VoxCPM2"

        logger.info(f"🧠 [VoiceGenerationService] Loading VoxCPM2 model from: {model_path}")
        try:
            _SHARED_VOXCPM_INSTANCE = VoxCPM.from_pretrained(model_path, load_denoiser=False)
        except Exception:
            _SHARED_VOXCPM_INSTANCE = VoxCPM.from_pretrained(model_path, load_denoiser=False, device="cpu")

        logger.info("✅ [VoiceGenerationService] VoxCPM2 model loaded successfully.")
        return _SHARED_VOXCPM_INSTANCE

    def cleanup_memory(self):
        """Clean up PyTorch & System RAM memory."""
        gc.collect()
        try:
            import torch
            if hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
        except Exception:
            pass

    def build_voice_prompt(self, config: VoiceGenerationConfig) -> str:
        """Build comprehensive natural-language voice design prompt."""
        if config.voice_description and config.voice_description.strip():
            return config.voice_description.strip()

        gender_str = "male" if config.gender.lower() == "male" else "female"
        if gender_str == "male" and config.age == "adult":
            return DEFAULT_MALE_PROMPT
        if gender_str == "female" and config.age == "adult":
            return DEFAULT_FEMALE_PROMPT
        if config.age == "child":
            return DEFAULT_CHILD_PROMPT
        if config.age == "elderly":
            return DEFAULT_ELDERLY_PROMPT

        age_str = config.age.replace("_", " ")
        style_str = config.style.replace("_", " ")
        emotion_str = config.emotion.replace("_", " ")
        pitch_str = config.pitch.replace("_", "-")

        prompt = (
            f"A natural {age_str} {gender_str} voice speaking Khmer. "
            f"Clear Khmer pronunciation. "
            f"Warm and realistic vocal tone. "
            f"{pitch_str.capitalize()} pitch. "
            f"{emotion_str.capitalize()} and {style_str} speaking style. "
            f"Natural breathing and natural pauses. "
            f"Natural intonation and rhythm. "
            f"Human-like articulation. "
            f"Do not sound robotic or synthetic."
        )
        return prompt

    def generate(
        self,
        text: str,
        config: VoiceGenerationConfig,
        output_path: str,
        cfg_value: float = 2.0,
        inference_timesteps: int = 10,
        seed: int = 42
    ) -> bool:
        """
        Generate speech using OpenBMB VoxCPM2 Voice Design.
        Format: (voice_description)target_text
        """
        if not text or not text.strip():
            logger.error("❌ [VoiceGenerationService] Target text is empty.")
            return False

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # Preprocess Khmer Unicode & Numbers
        normalized_text = preprocess_khmer_tts_text(text)

        voice_desc = self.build_voice_prompt(config)
        clean_desc = " ".join([line.strip() for line in voice_desc.splitlines() if line.strip()])
        full_prompt = f"({clean_desc}){normalized_text}"

        logger.info("=" * 65)
        logger.info("🎙️ VOICE GENERATION (VOXCPM2 VOICE DESIGN)")
        logger.info("=" * 65)
        logger.info(f"Gender     : {config.gender.capitalize()}")
        logger.info(f"Age        : {config.age.capitalize()}")
        logger.info(f"Style      : {config.style.capitalize()}")
        logger.info(f"Emotion    : {config.emotion.capitalize()}")
        logger.info(f"Pitch      : {config.pitch.capitalize()}")
        logger.info(f"Speed      : {config.speed}x")
        logger.info(f"Prompt     : {clean_desc[:70]}...")
        logger.info(f"Target     : {normalized_text[:50]}...")

        # Try Native OpenBMB VoxCPM2
        try:
            model = self.load_model()
            logger.info("🎤 Generating Khmer speech with OpenBMB VoxCPM2...")
            
            wav = model.generate(
                text=full_prompt,
                cfg_value=cfg_value,
                inference_timesteps=inference_timesteps,
                seed=seed
            )

            sample_rate = getattr(model.tts_model, "sample_rate", 48000)
            sf.write(output_path, wav, sample_rate)
            logger.info(f"✅ Voice generated successfully: {output_path} ({sample_rate}Hz)")
            self.cleanup_memory()
            return True

        except Exception as e:
            logger.warning(f"Native VoxCPM2 inference note: {e}, using Studio Acoustic Engine...")
            self.cleanup_memory()
            
            # Fallback to Studio Acoustic Timbre Engine
            from services.voxcpm_service import VoxCPMService
            base_voice = "Khmer Male - Piseth" if config.gender == "male" else "Khmer Female - Sreymom"
            svc = VoxCPMService(voice_name=base_voice)
            
            # Calculate pitch shift based on age and config pitch
            pitch_shift = 1.0
            if config.age == "child": pitch_shift = 1.35
            elif config.age == "elderly": pitch_shift = 0.8
            elif config.pitch == "low": pitch_shift = 0.75
            elif config.pitch == "high": pitch_shift = 1.2
            
            temp_wav = output_path.replace(".wav", "_temp_gen.wav")
            if svc._synthesize_edge_tts(normalized_text, temp_wav, pitch_shift=pitch_shift, speed_factor=config.speed):
                svc._apply_pitch_shift(temp_wav, pitch_shift=pitch_shift, speed_factor=config.speed, apply_eq=True)
                if os.path.exists(temp_wav):
                    if os.path.exists(output_path): os.remove(output_path)
                    os.rename(temp_wav, output_path)
                    return True
            return False

    def save_preset(self, name: str, config: VoiceGenerationConfig) -> str:
        """Save a voice generation design preset to JSON."""
        clean_name = name.strip().lower().replace(" ", "_")
        file_path = self.presets_dir / f"{clean_name}.json"
        
        data = {
            "name": name.strip(),
            "mode": "voice_generation",
            **asdict(config)
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"💾 Saved Voice Preset: '{name}' -> {file_path}")
        return str(file_path)

    def list_presets(self) -> list:
        """List all available voice design presets."""
        presets = [
            {
                "name": "👨 Khmer Male (Adult 30-40)",
                "gender": "male",
                "age": "adult",
                "style": "conversational",
                "emotion": "calm",
                "pitch": "medium_low",
                "speed": 1.0,
                "voice_description": DEFAULT_MALE_PROMPT
            },
            {
                "name": "👩 Khmer Female (Adult 25-35)",
                "gender": "female",
                "age": "adult",
                "style": "conversational",
                "emotion": "friendly",
                "pitch": "medium_high",
                "speed": 1.0,
                "voice_description": DEFAULT_FEMALE_PROMPT
            },
            {
                "name": "👦 Khmer Boy (Child 8-12)",
                "gender": "male",
                "age": "child",
                "style": "natural",
                "emotion": "happy",
                "pitch": "high",
                "speed": 1.05,
                "voice_description": DEFAULT_CHILD_PROMPT
            },
            {
                "name": "👴 Khmer Elder (Elderly 65-75)",
                "gender": "male",
                "age": "elderly",
                "style": "storytelling",
                "emotion": "calm",
                "pitch": "low",
                "speed": 0.85,
                "voice_description": DEFAULT_ELDERLY_PROMPT
            }
        ]

        if self.presets_dir.exists():
            for f in self.presets_dir.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as pf:
                        d = json.load(pf)
                        if d.get("name"):
                            presets.append(d)
                except Exception:
                    pass
        return presets

