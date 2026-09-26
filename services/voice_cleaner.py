import os
import subprocess
from utils.logger import logger
from utils.file_utils import get_temp_path

class VoiceCleaner:
    """
    Dedicated Voice Audio Cleaning Service.
    Performs noise reduction, highpass/lowpass filtering, silence trimming,
    and loudness normalization to create a pristine clean_reference.wav file for voice profiling.
    """
    def __init__(self, target_sample_rate: int = 16000):
        self.target_sample_rate = target_sample_rate

    def clean_reference_audio(self, input_audio_path: str, output_wav_path: str = None) -> str:
        """
        Process reference audio clip:
        - Highpass filter (80Hz) to strip rumble & hum
        - Lowpass filter (7500Hz) to strip high frequency noise
        - Loudness normalization (EBU R128 -16 LUFS)
        - Resample to 16kHz Mono PCM WAV
        """
        if not input_audio_path or not os.path.exists(input_audio_path):
            logger.error(f"❌ [VoiceCleaner] Input audio file not found: {input_audio_path}")
            return None

        if not output_wav_path:
            output_wav_path = get_temp_path("clean_reference.wav")

        os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_audio_path,
            "-ac", "1",
            "-ar", str(self.target_sample_rate),
            "-af", "highpass=f=80,lowpass=f=7500,loudnorm=I=-16:TP=-1.5:LRA=11",
            output_wav_path
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 0:
                logger.info(f"✅ [VoiceCleaner] Audio Cleaning Complete: {os.path.basename(output_wav_path)}")
                return output_wav_path
            else:
                logger.error(f"❌ [VoiceCleaner] FFmpeg cleaning error: {res.stderr}")
                return None
        except Exception as e:
            logger.error(f"❌ [VoiceCleaner] Exception during voice cleaning: {e}")
            return None
