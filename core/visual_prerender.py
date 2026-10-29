import os
import time
import math
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from qt_compat import QThread, Signal
from utils.logger import logger
from utils.file_utils import get_temp_path

def compute_visual_effects_hash(video_path: str, effects_config: dict, target_resolution: str = "Original") -> str:
    """Compute unique content-aware signature for visual effects (blur, logo, watermark, subtitles)."""
    v_stat = ""
    if video_path and os.path.exists(video_path):
        try:
            st = os.stat(video_path)
            v_stat = f"{video_path}_{st.st_size}_{st.st_mtime}"
        except Exception:
            v_stat = str(video_path)

    cfg = effects_config or {}
    b_cfg = cfg.get("blur", {})
    b_sig = f"{b_cfg.get('enabled')}_{b_cfg.get('intensity')}_{b_cfg.get('rect')}_{b_cfg.get('blurs')}"

    l_cfg = cfg.get("logo", {})
    l_sig = f"{l_cfg.get('enabled')}_{l_cfg.get('path')}_{l_cfg.get('x')}_{l_cfg.get('y')}_{l_cfg.get('width')}_{l_cfg.get('height')}"

    t_cfg = cfg.get("text_overlay", {})
    t_sig = f"{t_cfg.get('enabled')}_{t_cfg.get('items')}_{t_cfg.get('text')}"

    s_cfg = cfg.get("burn_subtitle", {})
    s_base = f"{s_cfg.get('enabled')}_{s_cfg.get('font_name')}_{s_cfg.get('font_size')}_{s_cfg.get('color_rgb')}_{s_cfg.get('y_ratio')}"

    seg_items = []
    if s_cfg.get("enabled", False):
        raw_segs = cfg.get("segments", [])
        for s in raw_segs:
            txt = (s.get("khmer_text") or s.get("original_text") or s.get("text") or "").strip()
            st_val = round(float(s.get("start", 0.0)), 2)
            et_val = round(float(s.get("end", 0.0)), 2)
            seg_items.append(f"{st_val}_{et_val}_{txt}")

    combined = f"{v_stat}|{b_sig}|{l_sig}|{t_sig}|{s_base}|{'#'.join(seg_items)}|{target_resolution}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]

def get_prerendered_effects_path(video_path: str, effects_config: dict, target_resolution: str = "Original") -> str:
    """Return cache file path for pre-rendered visual master."""
    cache_key = compute_visual_effects_hash(video_path, effects_config, target_resolution=target_resolution)
    return get_temp_path(f"prerendered_visual_{cache_key}.mp4")

def is_prerendered_effects_ready(video_path: str, effects_config: dict, target_resolution: str = "Original") -> bool:
    """Check if valid pre-rendered visual master already exists."""
    p = get_prerendered_effects_path(video_path, effects_config, target_resolution=target_resolution)
    return bool(p and os.path.exists(p) and os.path.getsize(p) > 50000)


class BackgroundVisualPreRenderWorker(QThread):
    """
    Background worker that pre-renders visual video effects (Blur, Burnt Subtitles, Logo)
    concurrently while Khmer voices are being synthesized.
    Allows final export to finish in 3 to 5 seconds via zero-re-encode Stream Copy.
    """
    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        effects_config: dict,
        target_resolution: str = "Original",
        parent=None
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.effects_config = effects_config
        self.target_resolution = target_resolution
        self._is_cancelled = False
        self.output_path = get_prerendered_effects_path(video_path, effects_config, target_resolution=target_resolution)

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if not self.video_path or not os.path.exists(self.video_path):
            self.error.emit("Video path does not exist.")
            return

        # If already ready, finish immediately
        if os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 50000:
            logger.info(f"⚡ [BackgroundPreRender] Visual effects already pre-baked: {self.output_path}")
            self.finished.emit(self.output_path)
            return

        temp_target = f"{self.output_path}.tmp.mp4"
        if os.path.exists(temp_target):
            try: os.remove(temp_target)
            except Exception: pass

        try:
            logger.info(f"🚀 [BackgroundPreRender] Starting background video effects pre-render: {os.path.basename(self.output_path)}...")
            self.progress.emit(5, "🎨 Pre-baking video effects in background...")

            from core.export_engine import VideoExportPipeline
            pipeline = VideoExportPipeline()

            def _cb(pct, desc=""):
                if self._is_cancelled:
                    return
                self.progress.emit(pct, f"🎨 [Background Pre-Render] Video Effects: {pct}%")

            success = pipeline.export_video(
                video_path=self.video_path,
                output_path=temp_target,
                effects_config=self.effects_config,
                master_audio_path=None,   # Visual-only master
                music_audio_path=None,
                background_volume=0.0,
                export_mode="FAST",
                target_resolution=self.target_resolution,
                progress_callback=_cb,
                is_cancelled_fn=lambda: self._is_cancelled
            )

            if self._is_cancelled:
                if os.path.exists(temp_target):
                    try: os.remove(temp_target)
                    except Exception: pass
                logger.info("🛑 [BackgroundPreRender] Canceled by user.")
                return

            if success and os.path.exists(temp_target) and os.path.getsize(temp_target) > 50000:
                os.replace(temp_target, self.output_path)
                logger.info(f"✅ [BackgroundPreRender] Successfully pre-baked visual master ({os.path.getsize(self.output_path)/1024/1024:.1f} MB)!")
                self.progress.emit(100, "✅ Video effects pre-baked! Export will be instant (3-5s).")
                self.finished.emit(self.output_path)
            else:
                self.error.emit("Background pre-render failed or produced incomplete file.")
        except Exception as e:
            if os.path.exists(temp_target):
                try: os.remove(temp_target)
                except Exception: pass
            logger.warning(f"⚠️ [BackgroundPreRender] Notice during pre-render: {e}")
            self.error.emit(str(e))
