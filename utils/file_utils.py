import os
import shutil
import json
import tempfile
from datetime import datetime
from pathlib import Path
from utils.logger import logger

BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"

def ensure_directories():
    """Ensure temp and output directories exist."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "videos").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "audio").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "subtitles").mkdir(parents=True, exist_ok=True)

def get_temp_path(filename: str) -> str:
    """Return an absolute path inside the project temp directory."""
    ensure_directories()
    return str(TEMP_DIR / filename)

def get_output_path(filename: str) -> str:
    """Return an absolute path inside the project output directory."""
    ensure_directories()
    return str(OUTPUT_DIR / filename)

def generate_unique_filename(base_path: str, prefix: str = "khmer", subfolder: str = None, extension: str = None, custom_dir: str = None) -> str:
    """
    Generate developer-grade unique timestamped filename inside target output directory.
    If custom_dir is provided, saves directly inside custom_dir.
    """
    ensure_directories()
    if custom_dir and os.path.exists(custom_dir):
        target_dir = Path(custom_dir)
    elif subfolder:
        target_dir = OUTPUT_DIR / subfolder
    else:
        target_dir = OUTPUT_DIR
        
    target_dir.mkdir(parents=True, exist_ok=True)

    path_obj = Path(base_path)
    stem = path_obj.stem if path_obj.stem else "video"
    ext = extension if extension else (path_obj.suffix if path_obj.suffix else ".mp4")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{stem}_{timestamp}{ext}"
    output_path = target_dir / filename
    
    counter = 1
    while output_path.exists():
        filename = f"{prefix}_{stem}_{timestamp}_{counter:02d}{ext}"
        output_path = target_dir / filename
        counter += 1
        
    return str(output_path)

def clean_temp_directory():
    """Clean all temporary files generated during process."""
    if TEMP_DIR.exists():
        for item in TEMP_DIR.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"Error cleaning {item}: {e}")

def save_json(data, filepath: str):
    """Save dictionary or list data to JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_json(filepath: str):
    """Load data from JSON file."""
    if not os.path.exists(filepath):
        return None
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def ensure_accessible_video_file(file_path: str) -> str:
    """
    Ensure the video file is directly accessible to external child processes like FFmpeg and Qt.
    If outside the workspace (e.g. ~/Downloads, ~/Desktop), copy to workspace temp directory.
    """
    if not file_path or not os.path.exists(file_path):
        return file_path

    workspace_dir = str(Path(__file__).resolve().parent.parent)
    resolved = str(Path(file_path).resolve())

    # If already inside workspace, it is safe
    if resolved.startswith(workspace_dir):
        return resolved

    ensure_directories()
    safe_name = f"safe_input_{Path(file_path).name}"
    safe_path = get_temp_path(safe_name)

    # 1. If safe_path already exists and matches size or is valid, use it
    if os.path.exists(safe_path) and os.path.getsize(safe_path) > 1000:
        try:
            if os.path.getsize(safe_path) == os.path.getsize(file_path):
                logger.info(f"✅ Using cached safe video: {safe_path}")
                return safe_path
        except Exception:
            return safe_path

    # 2. Try copying via multiple methods
    copied = False
    try:
        shutil.copyfile(file_path, safe_path)
        copied = True
    except Exception as e1:
        # Fallback A: Binary chunk copy
        try:
            with open(file_path, 'rb') as src_f, open(safe_path, 'wb') as dst_f:
                while True:
                    chunk = src_f.read(1024 * 1024)
                    if not chunk:
                        break
                    dst_f.write(chunk)
            copied = True
        except Exception as e2:
            # Fallback B: subprocess cp
            try:
                import subprocess
                res = subprocess.run(["cp", "-f", file_path, safe_path], capture_output=True)
                if res.returncode == 0 and os.path.exists(safe_path) and os.path.getsize(safe_path) > 1000:
                    copied = True
            except Exception:
                pass

    if copied and os.path.exists(safe_path) and os.path.getsize(safe_path) > 1000:
        logger.info(f"✅ Successfully prepared safe accessible video copy: {safe_path}")
        return safe_path

    # If copy failed but we already have an existing cached safe file, return it
    if os.path.exists(safe_path) and os.path.getsize(safe_path) > 1000:
        logger.info(f"Using existing cached safe video: {safe_path}")
        return safe_path

    logger.warning(f"Could not copy external video to safe path: {file_path}")
    return file_path
