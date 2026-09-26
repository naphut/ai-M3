import subprocess
import json
import os
import shutil
from pathlib import Path
from utils.logger import logger

def is_ffmpeg_available() -> bool:
    """Check if ffmpeg command is available in system path."""
    try:
        res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0
    except Exception:
        return False

def get_video_info(video_path: str) -> dict:
    """Get metadata about video file (duration, resolution, audio presence)."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        
        duration = float(data.get("format", {}).get("duration", 0.0))
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
        
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        width = video_stream.get("width", 0)
        height = video_stream.get("height", 0)
        
        return {
            "duration": duration,
            "has_audio": has_audio,
            "width": width,
            "height": height,
            "format": data.get("format", {}).get("format_name", "")
        }
    except Exception as e:
        logger.error(f"Failed to probe video info for {video_path}: {e}")
        return {"duration": 0.0, "has_audio": True, "width": 0, "height": 0}

def extract_audio(video_path: str, output_audio_path: str, sample_rate: int = 16000) -> bool:
    """Extract audio from video file to 16kHz mono WAV or MP3 format."""
    codec = "libmp3lame" if output_audio_path.lower().endswith(".mp3") else "pcm_s16le"
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", codec,
        "-ar", str(sample_rate),
        "-ac", "1",
        output_audio_path
    ]
    try:
        logger.info(f"Extracting audio from {os.path.basename(video_path)} -> {os.path.basename(output_audio_path)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg audio extraction error: {res.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error running FFmpeg audio extraction: {e}")
        return False

def extract_video_thumbnail(video_path: str, output_image_path: str) -> bool:
    """Extract a single video frame thumbnail using FFmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:00.500",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        output_image_path
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and os.path.exists(output_image_path)
    except Exception as e:
        logger.error(f"Error extracting video thumbnail: {e}")
        return False

def combine_video_audio(
    video_path: str, 
    audio_path: str, 
    output_path: str, 
    background_volume: float = 0.0
) -> bool:
    """
    Merge video track with new audio track.
    If background_volume > 0.0, mixes original video audio at lowered volume.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if background_volume <= 0.0:
        # Simple replace audio stream
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path
        ]
    else:
        # Mix background audio with synthesized audio
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", (
                f"[0:a]volume={background_volume}[bg];"
                f"[bg][1:a]sidechaincompress=threshold=0.03:ratio=5:attack=50:release=350[ducked_bg];"
                f"[1:a][ducked_bg]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            ),
            "-map", "0:v:0",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]

    try:
        logger.info(f"Combining video & dubbed audio -> {output_path}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"FFmpeg combine video error: {res.stderr}")
            return False
        return True
    except Exception as e:
        logger.error(f"Error merging video and audio: {e}")
        return False

def adjust_audio_speed(input_audio: str, output_audio: str, speed_factor: float) -> bool:
    """Adjust audio playback speed using FFmpeg atempo filter (0.5 to 2.0 per filter stage)."""
    if speed_factor == 1.0:
        shutil.copy(input_audio, output_audio)
        return True

    # FFmpeg atempo limits: 0.5 <= atempo <= 2.0
    filters = []
    current_speed = speed_factor

    while current_speed > 2.0:
        filters.append("atempo=2.0")
        current_speed /= 2.0
    while current_speed < 0.5:
        filters.append("atempo=0.5")
        current_speed /= 0.5
    
    filters.append(f"atempo={current_speed:.4f}")
    filter_chain = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_audio,
        "-filter:a", filter_chain,
        output_audio
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0
    except Exception as e:
        logger.error(f"Error adjusting audio speed: {e}")
        return False
