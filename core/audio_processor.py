import os
import wave
import struct
from utils.file_utils import get_temp_path
from utils.ffmpeg import adjust_audio_speed
from utils.logger import logger

class AudioProcessor:
    """
    Audio Sync & Alignment Engine.
    Stitches synthesized segment WAV files into a unified master audio track,
    ensuring each audio segment aligns precisely with its original video timestamps.
    """
    @staticmethod
    def get_wav_duration(wav_path: str) -> float:
        """Get exact duration of WAV audio file in seconds."""
        if not os.path.exists(wav_path):
            return 0.0
        try:
            with wave.open(wav_path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                return frames / float(rate)
        except Exception as e:
            logger.error(f"Error reading WAV duration for {wav_path}: {e}")
            return 0.0

    def sync_and_stitch_segments(
        self, 
        segments: list, 
        seg_audio_paths: list, 
        total_duration: float
    ) -> str:
        """
        Sync each segment audio to its target timestamp window [start, end],
        pad silence where appropriate, and merge into master_khmer_voice.wav.
        """
        output_master_wav = get_temp_path("master_khmer_voice.wav")
        logger.info(f"Syncing {len(segments)} audio segments across {total_duration:.2f}s timeline...")

        # Try pydub for smooth audio processing if installed
        try:
            from pydub import AudioSegment
            master_audio = AudioSegment.silent(duration=int(total_duration * 1000) + 1000, frame_rate=16000)

            for seg, raw_path in zip(segments, seg_audio_paths):
                if not raw_path or not os.path.exists(raw_path):
                    continue

                start_ms = int(seg["start"] * 1000)
                end_ms = int(seg["end"] * 1000)
                target_duration_ms = max(500, end_ms - start_ms)

                seg_audio = AudioSegment.from_file(raw_path)
                actual_duration_ms = len(seg_audio)

                # Speed alignment factor if speech duration differs significantly
                if actual_duration_ms > 0 and abs(actual_duration_ms - target_duration_ms) > 200:
                    speed_factor = actual_duration_ms / float(target_duration_ms)
                    # Limit speed factor between 0.7x (slowdown) and 1.5x (speedup) to keep voice natural
                    speed_factor = max(0.7, min(1.5, speed_factor))
                    
                    adjusted_path = get_temp_path(f"adj_{os.path.basename(raw_path)}")
                    if adjust_audio_speed(raw_path, adjusted_path, speed_factor):
                        seg_audio = AudioSegment.from_file(adjusted_path)

                # Overlay segment audio at exact start timestamp
                master_audio = master_audio.overlay(seg_audio, position=start_ms)

            # Export master track
            master_audio.export(output_master_wav, format="wav")
            logger.info("Pydub audio sync & master stitching completed!")
            return output_master_wav

        except ImportError:
            logger.warning("Pydub not installed. Using wave module silence alignment fallback.")
            return self._sync_with_wave_fallback(segments, seg_audio_paths, total_duration, output_master_wav)

    def _sync_with_wave_fallback(self, segments, seg_audio_paths, total_duration, output_wav_path):
        """Pure standard library wave module fallback for audio stitching."""
        sample_rate = 16000
        num_channels = 1
        sample_width = 2
        total_samples = int(sample_rate * (total_duration + 1.0))
        buffer = bytearray(total_samples * sample_width)

        for seg, raw_path in zip(segments, seg_audio_paths):
            if not raw_path or not os.path.exists(raw_path):
                continue
            
            start_sample = int(seg["start"] * sample_rate)
            try:
                with wave.open(raw_path, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    start_byte = start_sample * sample_width
                    end_byte = min(len(buffer), start_byte + len(frames))
                    copy_len = end_byte - start_byte
                    buffer[start_byte:end_byte] = frames[:copy_len]
            except Exception as e:
                logger.error(f"Error copying wave frames: {e}")

        with wave.open(output_wav_path, 'wb') as out_wf:
            out_wf.setnchannels(num_channels)
            out_wf.setsampwidth(sample_width)
            out_wf.setframerate(sample_rate)
            out_wf.writeframes(buffer)

        return output_wav_path
