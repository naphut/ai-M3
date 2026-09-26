# services/voice_prompt_processor.py
import re
import json
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from utils.logger import logger

@dataclass
class VoiceProfile:
    """Complete Voice Profile extracted from Natural Language Prompt"""
    name: str
    gender: str           # male, female, neutral
    age: str              # child, young, adult, middle_aged, elderly
    emotion: str          # neutral, happy, sad, angry, calm, friendly, serious
    style: str            # natural, conversational, professional, narrator, news, documentary
    pitch: str            # very_low, low, medium_low, medium, medium_high, high, very_high
    speed: float          # 0.7 - 1.5
    voice_description: str # Full original prompt
    language: str = "km"
    is_clone: bool = False
    reference_audio: Optional[str] = None
    reference_text: Optional[str] = None
    pitch_shift: float = 1.0
    eq_preset: str = "balanced"

class VoicePromptProcessor:
    """
    Natural Language Voice Prompt Processor.
    Extracts structured voice characteristics from descriptive text in Khmer & English.
    """
    
    # Pattern mapping for prompt extraction
    GENDER_PATTERNS = {
        "male": re.compile(r'\b(male|man|guy|boy|masculine|ប្រុស|បុរស|ប្អូនប្រុស|លោក|តា)\b', re.IGNORECASE),
        "female": re.compile(r'\b(female|woman|girl|lady|feminine|ស្រី|ស្ត្រី|ប្អូនស្រី|នាង|យាយ)\b', re.IGNORECASE),
        "neutral": re.compile(r'\b(neutral|androgynous|unisex)\b', re.IGNORECASE),
    }
    
    AGE_PATTERNS = {
        "child": re.compile(r'\b(child|kid|young boy|young girl|little girl|little boy|toddler|ក្មេង|កូនក្មេង)\b', re.IGNORECASE),
        "young": re.compile(r'\b(young|youth|teenager|teen|យុវវ័យ|ក្មេងជំទង់)\b', re.IGNORECASE),
        "middle_aged": re.compile(r'\b(middle-aged|middle age|40s|50s|វ័យកណ្តាល)\b', re.IGNORECASE),
        "elderly": re.compile(r'\b(elderly|senior|grandfather|grandmother|old man|old woman|old person|ចាស់|មនុស្សចាស់|តា|យាយ)\b', re.IGNORECASE),
        "adult": re.compile(r'\b(adult|grown|mature|30s|20s|មនុស្សពេញវ័យ)\b', re.IGNORECASE),
    }
    
    EMOTION_PATTERNS = {
        "happy": re.compile(r'\b(happy|cheerful|joyful|energetic|excited|រីករាយ|សប្បាយ|រំភើប)\b', re.IGNORECASE),
        "sad": re.compile(r'\b(sad|sorrowful|melancholy|depressed|សោកសៅ|ក្រៀមក្រំ|ព្រួយ)\b', re.IGNORECASE),
        "angry": re.compile(r'\b(angry|furious|irritated|annoyed|intense|ខឹង|កំហឹង)\b', re.IGNORECASE),
        "friendly": re.compile(r'\b(friendly|warm|kind|approachable|រួសរាយ|រាក់ទាក់|កក់ក្តៅ)\b', re.IGNORECASE),
        "serious": re.compile(r'\b(serious|stern|grave|formal|ម៉ត់ចត់|ហ្មត់ចត់)\b', re.IGNORECASE),
        "emotional": re.compile(r'\b(emotional|passionate|dramatic|deep|រំជួលចិត្ត)\b', re.IGNORECASE),
        "neutral": re.compile(r'\b(neutral|normal|calm|balanced|ស្ងប់|ធម្មតា|ស្ងប់ស្ងាត់)\b', re.IGNORECASE),
    }
    
    STYLE_PATTERNS = {
        "conversational": re.compile(r'\b(conversational|casual|informal|talking|និយាយលេង|សន្ទនា)\b', re.IGNORECASE),
        "professional": re.compile(r'\b(professional|formal|business|corporate|វិជ្ជាជីវៈ|ផ្លូវការ)\b', re.IGNORECASE),
        "narrator": re.compile(r'\b(narrator|documentary|storytelling|voiceover|អ្នកអត្ថាធិប្បាយ|រឿងនិទាន)\b', re.IGNORECASE),
        "news": re.compile(r'\b(news|broadcast|announcer|reporter|ព័ត៌មាន|ពិធីករ)\b', re.IGNORECASE),
        "whisper": re.compile(r'\b(whisper|soft|quiet|hushed|ខ្សឹប|ស្រាល)\b', re.IGNORECASE),
        "natural": re.compile(r'\b(natural|realistic|human|everyday|ធម្មជាតិ|ដូចមនុស្សពិត)\b', re.IGNORECASE),
    }
    
    PITCH_PATTERNS = {
        "very_low": re.compile(r'\b(very low|extremely low|heavy bass|very deep|សំឡេងធំខ្លាំង|ទាបខ្លាំង)\b', re.IGNORECASE),
        "very_high": re.compile(r'\b(very high|extremely high|squeaky|ខ្ពស់ខ្លាំង)\b', re.IGNORECASE),
        "low": re.compile(r'\b(low|deep|bass|ធំ|ទាប|គ្រលរ)\b', re.IGNORECASE),
        "high": re.compile(r'\b(high|bright|sharp|ខ្ពស់|ស្រួច)\b', re.IGNORECASE),
        "medium_low": re.compile(r'\b(medium-low|moderate low)\b', re.IGNORECASE),
        "medium_high": re.compile(r'\b(medium-high|moderate high)\b', re.IGNORECASE),
        "medium": re.compile(r'\b(medium|normal|moderate|ល្មម|កណ្តាល)\b', re.IGNORECASE),
    }
    
    SPEED_PATTERNS = {
        "very_slow": re.compile(r'\b(very slow|extremely slow|យឺតខ្លាំង)\b', re.IGNORECASE),
        "slow": re.compile(r'\b(slow|slower|leisurely|យឺត)\b', re.IGNORECASE),
        "medium": re.compile(r'\b(medium|normal|moderate|ល្មម|ធម្មតា)\b', re.IGNORECASE),
        "fast": re.compile(r'\b(fast|faster|quick|rapid|លឿន|រហ័ស)\b', re.IGNORECASE),
        "very_fast": re.compile(r'\b(very fast|extremely fast|rapid|លឿនខ្លាំង)\b', re.IGNORECASE),
    }

    PITCH_SHIFT_MAP = {
        "very_low": 0.60,
        "low": 0.75,
        "medium_low": 0.85,
        "medium": 1.0,
        "medium_high": 1.15,
        "high": 1.30,
        "very_high": 1.50,
    }
    
    @classmethod
    def process_prompt(cls, prompt_text: str, name: str = None) -> VoiceProfile:
        """
        Parse natural language prompt into structured VoiceProfile.
        
        Args:
            prompt_text: Natural language description (e.g., 'Cambodian male, deep voice, calm narrator')
            name: Optional character name
            
        Returns:
            VoiceProfile with extracted parameters
        """
        if not prompt_text or not prompt_text.strip():
            return VoiceProfile(
                name=name or "Default Voice",
                gender="female",
                age="adult",
                emotion="neutral",
                style="natural",
                pitch="medium",
                speed=1.0,
                voice_description="Default natural voice",
                pitch_shift=1.0
            )
        
        prompt_lower = prompt_text.lower()
        prompt_original = prompt_text.strip()
        
        gender = cls._extract_gender(prompt_lower)
        age = cls._extract_age(prompt_lower)
        emotion = cls._extract_emotion(prompt_lower)
        style = cls._extract_style(prompt_lower)
        pitch = cls._extract_pitch(prompt_lower)
        speed = cls._extract_speed(prompt_lower)
        pitch_shift = cls.PITCH_SHIFT_MAP.get(pitch, 1.0)
        
        voice_description = cls._build_voice_description(
            gender, age, emotion, style, pitch, speed, prompt_original
        )
        
        return VoiceProfile(
            name=name or f"{gender.capitalize()} {age.capitalize()} Voice",
            gender=gender,
            age=age,
            emotion=emotion,
            style=style,
            pitch=pitch,
            speed=speed,
            voice_description=voice_description,
            language="km",
            pitch_shift=pitch_shift
        )
    
    @classmethod
    def _extract_gender(cls, text: str) -> str:
        for gender, pattern in cls.GENDER_PATTERNS.items():
            if pattern.search(text):
                return gender
        return "female"
    
    @classmethod
    def _extract_age(cls, text: str) -> str:
        for age, pattern in cls.AGE_PATTERNS.items():
            if pattern.search(text):
                return age
        return "adult"
    
    @classmethod
    def _extract_emotion(cls, text: str) -> str:
        for emotion, pattern in cls.EMOTION_PATTERNS.items():
            if pattern.search(text):
                return emotion
        return "neutral"
    
    @classmethod
    def _extract_style(cls, text: str) -> str:
        for style, pattern in cls.STYLE_PATTERNS.items():
            if pattern.search(text):
                return style
        return "natural"
    
    @classmethod
    def _extract_pitch(cls, text: str) -> str:
        for pitch, pattern in cls.PITCH_PATTERNS.items():
            if pattern.search(text):
                return pitch
        return "medium"
    
    @classmethod
    def _extract_speed(cls, text: str) -> float:
        if cls.SPEED_PATTERNS["very_slow"].search(text):
            return 0.7
        elif cls.SPEED_PATTERNS["slow"].search(text):
            return 0.85
        elif cls.SPEED_PATTERNS["fast"].search(text):
            return 1.15
        elif cls.SPEED_PATTERNS["very_fast"].search(text):
            return 1.3
        return 1.0
    
    @classmethod
    def _build_voice_description(cls, gender: str, age: str, emotion: str, style: str, pitch: str, speed: float, original: str) -> str:
        pitch_map = {
            "very_low": "very low",
            "low": "low",
            "medium_low": "medium-low",
            "medium": "medium",
            "medium_high": "medium-high",
            "high": "high",
            "very_high": "very high",
        }
        
        age_map = {
            "child": "young child",
            "young": "young adult",
            "adult": "adult",
            "middle_aged": "middle-aged",
            "elderly": "elderly",
        }
        
        gender_str = "male" if gender == "male" else "female"
        age_str = age_map.get(age, "adult")
        emotion_str = emotion.replace("_", " ")
        style_str = style.replace("_", " ")
        pitch_str = pitch_map.get(pitch, "medium")
        
        if len(original.split()) >= 10:
            return original
        
        desc_lines = [
            f"A natural {age_str} {gender_str} voice speaking Khmer.",
            "Clear Khmer pronunciation.",
            "Warm and realistic vocal tone.",
            f"{pitch_str.capitalize()} pitch.",
            f"{emotion_str.capitalize()} and {style_str} speaking style.",
            "Natural breathing and natural pauses.",
            "Natural intonation and rhythm.",
            "Human-like articulation.",
            "Do not sound robotic.",
            "Do not sound synthetic."
        ]
        
        if speed < 0.9:
            desc_lines.append("Slower speaking pace.")
        elif speed > 1.1:
            desc_lines.append("Faster speaking pace.")
        
        return "\n".join(desc_lines)
    
    @classmethod
    def build_natural_prompt(
        cls,
        gender: str = "Male",
        age: int = 30,
        voice_type: str = "Deep",
        tone: str = "Warm",
        emotion: str = "Calm",
        style: str = "Natural Conversation",
        speed: str = "Medium",
        additional: str = ""
    ) -> str:
        """
        Synthesize natural-language voice description from structured form attributes.
        """
        gender_str = gender.lower()
        pronoun = "his" if gender_str == "male" else "her"
        age_str = f"in {pronoun} {age}s" if age >= 20 else f"around {age} years old"
        
        parts = [
            f"A natural Cambodian Khmer {gender_str} voice {age_str}.",
            f"{voice_type.capitalize()} and {tone.lower()} timbre.",
            f"{emotion.capitalize()} and confident, with a {style.lower()} delivery.",
            "Clear Khmer pronunciation and realistic intonation.",
            f"{speed.capitalize()} speaking pace with natural pauses and subtle breathing.",
        ]
        if additional.strip():
            parts.append(f"{additional.strip()}.")
        parts.append("Authentic and human delivery. Avoid robotic or monotone speech.")
        return " ".join(parts)

    @classmethod
    def profile_to_voxcpm_preset(cls, profile: VoiceProfile, reference_audio: str = None, reference_text: str = None) -> Dict[str, Any]:
        return {
            "name": profile.name,
            "edge_voice": "km-KH-SreymomNeural" if profile.gender == "female" else "km-KH-PisethNeural",
            "description": profile.voice_description,
            "gender": profile.gender,
            "age": profile.age,
            "style": profile.style,
            "pitch_shift": profile.pitch_shift,
            "speed_factor": profile.speed,
            "prompt_audio_path": reference_audio or profile.reference_audio,
            "prompt_text": reference_text or profile.reference_text,
            "is_clone": bool(reference_audio or profile.is_clone),
        }
