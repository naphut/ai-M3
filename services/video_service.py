import os
import subprocess
from utils.logger import logger
from utils.file_utils import get_output_path

class VideoService:
    """
    Dedicated Video Operations & Multiplexing Service.
    Handles video stream metadata extraction and final FFmpeg dubbing video muxing.
    """
    def __init__(self, video_path: str = None):
        self.video_path = video_path

    def get_video_info(self, video_path: str = None) -> dict:
        """Extract video duration, resolution, fps, and audio stream existence."""
        target = video_path or self.video_path
        if not target or not os.path.exists(target):
            return {"duration": 0.0, "has_audio": False}

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration:stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                target
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            lines = [l.strip() for l in res.stdout.split("\n") if l.strip()]

            duration = 0.0
            has_audio = False
            for line in lines:
                if line == "audio":
                    has_audio = True
                else:
                    try: duration = float(line)
                    except ValueError: pass

            return {
                "duration": duration,
                "has_audio": has_audio,
                "video_path": target
            }
        except Exception as e:
            logger.error(f"❌ [VideoService] Error probing video: {e}")
            return {"duration": 0.0, "has_audio": False}

    def merge_dubbed_audio(
        self,
        video_path: str,
        master_audio_path: str,
        output_video_path: str = None,
        music_audio_path: str = None,
        background_volume: float = 0.30
    ) -> bool:
        """
        Merge dubbed audio track with original video stream using FFmpeg.
        Mixes dubbed Khmer voice (100%) with original background music/sound effects.
        """
        if not os.path.exists(video_path) or not os.path.exists(master_audio_path):
            logger.error(f"❌ [VideoService] Missing input files for video merge: {video_path}, {master_audio_path}")
            return False

        if not output_video_path:
            output_video_path = get_output_path("dubbed_khmer.mp4")

        os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

        # Ensure background audio track is available if background_volume > 0
        if (not music_audio_path or not os.path.exists(music_audio_path)) and background_volume > 0.0:
            from utils.file_utils import get_temp_path
            temp_bg = get_temp_path("background.wav")
            if os.path.exists(temp_bg) and os.path.getsize(temp_bg) > 1000:
                music_audio_path = temp_bg
            else:
                try:
                    from services.audio_separator import AudioSeparationService
                    sep = AudioSeparationService().extract_and_separate(video_path)
                    music_audio_path = sep.get("background_audio") or sep.get("original_audio")
                except Exception as e_sep:
                    logger.warning(f"Could not auto-extract fallback BGM: {e_sep}")

        if music_audio_path and os.path.exists(music_audio_path) and background_volume > 0.0:
            bg_vol_str = f"{max(0.05, min(1.0, background_volume)):.2f}"
            logger.info(f"🎶 [VideoService] Mixing Khmer Voice (100%) with BGM ({int(float(bg_vol_str)*100)}%) + Studio Sidechain Auto-Ducking...")
            # When Khmer voice [1:a] speaks, BGM [2:a] ducks smoothly by ~6-8dB
            # When Khmer voice is silent, BGM smoothly returns to full natural volume!
            # Soft limiter prevents digital clipping
            filter_str = (
                f"[2:a]volume={bg_vol_str}[bgm_scaled];"
                f"[bgm_scaled][1:a]sidechaincompress=threshold=0.035:ratio=3.5:attack=35:release=280[ducked_bgm];"
                f"[1:a]volume=1.45[v_boost];"
                f"[v_boost][ducked_bgm]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.99[aout]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", master_audio_path,
                "-i", music_audio_path,
                "-filter_complex", filter_str,
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-ar", "44100",
                "-shortest",
                output_video_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", master_audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_video_path
            ]

        try:
            logger.info(f"🎬 [VideoService] Merging video with dubbed audio -> {os.path.basename(output_video_path)}")
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_video_path) and os.path.getsize(output_video_path) > 1000:
                logger.info(f"✅ [VideoService] Final Dubbed Video Created: {output_video_path}")
                return True
            else:
                logger.error(f"❌ [VideoService] FFmpeg multiplexing error: {res.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ [VideoService] Merge exception: {e}")
            return False
