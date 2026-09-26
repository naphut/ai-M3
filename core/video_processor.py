import os
import sys
import re
import shutil
import subprocess
import cv2
import numpy as np
from qt_compat import QApplication, QtGui, QtCore, Qt
from utils.ffmpeg import extract_audio, combine_video_audio, get_video_info
from utils.file_utils import get_temp_path
from utils.logger import logger

_loaded_qt_fonts = set()
def ensure_qt_fonts():
    font_dir = os.path.abspath('fonts')
    if os.path.exists(font_dir):
        for f in os.listdir(font_dir):
            if f.endswith('.ttf') or f.endswith('.otf'):
                p = os.path.join(font_dir, f)
                if p not in _loaded_qt_fonts:
                    QtGui.QFontDatabase.addApplicationFont(p)
                    _loaded_qt_fonts.add(p)

def resolve_qt_font_name(requested_name: str) -> str:
    fn = str(requested_name).lower()
    if "kantumruy" in fn:
        return "Kantumruy Pro"
    elif "battambang" in fn:
        return "Battambang"
    elif "noto" in fn:
        return "Noto Sans Khmer"
    elif "sangam" in fn or "mn" in fn:
        return "Khmer Sangam MN"
    return "Kantumruy Pro"


def _render_text_overlay_qt(text: str, font_name: str, font_size_pt: int, color_rgb: tuple, pos: tuple, scale_x: float, scale_y: float, width: int, height: int):
    """Pre-render static text overlay ONCE to (mask, bgr) for ultra-fast frame blending."""
    x = int(pos[0] * scale_x)
    y = int(pos[1] * scale_y)
    x = max(10, min(width - 30, x))
    y = max(20, min(height - 20, y))
    
    font_size_pt = max(12, int(font_size_pt * scale_y))
    font_family = resolve_qt_font_name(font_name)
    
    qimg = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    qimg.fill(Qt.transparent)
    
    painter = QtGui.QPainter(qimg)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
    
    font = QtGui.QFont(font_family, font_size_pt, QtGui.QFont.Bold)
    painter.setFont(font)
    fm = QtGui.QFontMetrics(font)
    text_w = fm.horizontalAdvance(text)
    text_h = fm.height()
    
    pad_x, pad_y = 14, 10
    bg_x = max(0, x - pad_x)
    bg_y = max(0, y - fm.ascent() - pad_y)
    bg_w = min(width - bg_x, text_w + pad_x * 2)
    bg_h = min(height - bg_y, text_h + pad_y * 2)
    
    painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 180)))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QtCore.QRect(bg_x, bg_y, bg_w, bg_h), 10, 10)
    
    path = QtGui.QPainterPath()
    path.addText(x, y, font, text)
    
    stroke_w = max(2, font_size_pt // 10)
    painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 255), stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    
    painter.setBrush(QtGui.QBrush(QtGui.QColor(color_rgb[0], color_rgb[1], color_rgb[2])))
    painter.setPen(Qt.NoPen)
    painter.drawPath(path)
    
    painter.end()
    
    qimg_rgb = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
    ptr = qimg_rgb.bits()
    if hasattr(ptr, 'setsize'): ptr.setsize(height * width * 3)
    arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
    text_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    mask = (arr > 0).any(axis=2)
    return mask, text_bgr


def _render_subtitle_overlay_qt(sub_text: str, font_name: str, font_size_pt: int, color_rgb: tuple, bg_opacity: float, width: int, height: int, scale_y: float):
    """Pre-render a subtitle segment overlay ONCE to (mask, bgr) for ultra-fast frame caching."""
    qimg = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
    qimg.fill(Qt.transparent)
    
    painter = QtGui.QPainter(qimg)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
    
    font_size_pt = max(14, int(font_size_pt * scale_y))
    font_family = resolve_qt_font_name(font_name)
    
    font = QtGui.QFont(font_family, font_size_pt, QtGui.QFont.Bold)
    painter.setFont(font)
    fm = QtGui.QFontMetrics(font)
    
    words = sub_text.split()
    lines = []
    curr_line = ""
    max_line_w = width - 80
    
    for word in words:
        test_line = f"{curr_line} {word}".strip()
        if fm.horizontalAdvance(test_line) <= max_line_w or not curr_line:
            curr_line = test_line
        else:
            lines.append(curr_line)
            curr_line = word
    if curr_line:
        lines.append(curr_line)
    
    line_height = fm.height() + 6
    total_h = len(lines) * line_height
    line_widths = [fm.horizontalAdvance(l) for l in lines]
    max_w = max(line_widths) if line_widths else 100
    
    margin_bottom = int(40 * scale_y)
    bg_x1 = max(10, (width - max_w) // 2 - 22)
    bg_x2 = min(width - 10, (width + max_w) // 2 + 22)
    bg_y1 = height - margin_bottom - total_h - 16
    bg_y2 = height - margin_bottom + 16
    
    bg_alpha = int(bg_opacity * 255)
    painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, bg_alpha)))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QtCore.QRect(bg_x1, bg_y1, bg_x2 - bg_x1, bg_y2 - bg_y1), 12, 12)
    
    curr_y = bg_y1 + fm.ascent() + 8
    stroke_w = max(2, font_size_pt // 10)
    
    for i, l in enumerate(lines):
        lx = (width - line_widths[i]) // 2
        path = QtGui.QPainterPath()
        path.addText(lx, curr_y, font, l)
        
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 255), stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        
        painter.setBrush(QtGui.QBrush(QtGui.QColor(color_rgb[0], color_rgb[1], color_rgb[2])))
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)
        
        curr_y += line_height
    
    painter.end()
    
    qimg_rgb = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
    ptr = qimg_rgb.bits()
    if hasattr(ptr, 'setsize'): ptr.setsize(height * width * 3)
    arr = np.frombuffer(ptr, np.uint8).reshape((height, width, 3))
    text_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    mask = (arr > 0).any(axis=2)
    return mask, text_bgr


class VideoProcessor:
    def __init__(self, video_path: str):
        self.video_path = video_path
        from services.video_service import VideoService
        self.service = VideoService(video_path)
        self.info = self.service.get_video_info(video_path)

    def extract_source_audio(self) -> str:
        """Extract audio stream from source video to 16kHz WAV."""
        from services.audio_extractor import AudioExtractor
        extractor = AudioExtractor()
        audio_temp_path = get_temp_path("original_audio.wav")
        result = extractor.extract_audio(self.video_path, audio_temp_path)
        if result and os.path.exists(result):
            return result
        raise RuntimeError(f"Failed to extract audio from video: {self.video_path}")

    def merge_dubbed_audio(
        self,
        dubbed_audio_path: str,
        output_video_path: str,
        music_audio_path: str = None,
        background_volume: float = 0.30
    ) -> bool:
        """Merge dubbed Khmer audio track with original video stream, preserving background music."""
        return self.service.merge_dubbed_audio(
            video_path=self.video_path,
            master_audio_path=dubbed_audio_path,
            output_video_path=output_video_path,
            music_audio_path=music_audio_path,
            background_volume=background_volume
        )

    def apply_effects_to_video(self, effects_config: dict, output_path: str) -> bool:
        """
        Apply effects (blur, text overlay, logo, burn subtitle) to video using ultra-fast 10x cached rendering.
        Provides 100% native HarfBuzz Khmer Unicode shaping during export.
        """
        if not effects_config:
            return False
        
        app = QApplication.instance() or QApplication(sys.argv)
        ensure_qt_fonts()
        
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            logger.error("Failed to open video for effects processing")
            return False
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        raw_effects_path = get_temp_path("raw_effects_uncompressed.mp4")
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(raw_effects_path, fourcc, fps, (width, height))
        
        preview_w, preview_h = effects_config.get("preview_size", (280, 260))
        scale_x = width / float(max(1, preview_w))
        scale_y = height / float(max(1, preview_h))
        
        blur_config = effects_config.get("blur", {})
        text_config = effects_config.get("text_overlay", {})
        logo_config = effects_config.get("logo", {})
        burn_sub_config = effects_config.get("burn_subtitle", {})
        segments = effects_config.get("segments", [])
        
        # 1. OPTIMIZATION: Pre-render Static Text Overlay ONCE before frame loop
        static_text_mask = None
        static_text_bgr = None
        if text_config.get("enabled", False) and text_config.get("text"):
            try:
                static_text_mask, static_text_bgr = _render_text_overlay_qt(
                    text=text_config.get("text", ""),
                    font_name=text_config.get("font_name", "Kantumruy Pro"),
                    font_size_pt=text_config.get("size_pt", 24),
                    color_rgb=text_config.get("color_rgb", (255, 255, 255)),
                    pos=text_config.get("position", (50, 80)),
                    scale_x=scale_x,
                    scale_y=scale_y,
                    width=width,
                    height=height
                )
            except Exception as e:
                logger.error(f"Error pre-rendering static text overlay: {e}")

        # 2. OPTIMIZATION: Pre-calculate Logo Overlay matrices ONCE before frame loop
        logo_blend_data = None
        logo_path = logo_config.get("path")
        if logo_path and os.path.exists(str(logo_path)):
            logo_w = max(10, int(logo_config.get("width", 100) * scale_x))
            logo_h = max(10, int(logo_config.get("height", 100) * scale_y))
            logo_x = max(0, int(logo_config.get("x", 233) * scale_x))
            logo_y = max(0, int(logo_config.get("y", 6) * scale_y))
            
            # Clip bounds to fit video frame boundaries
            if logo_x + logo_w > width:
                logo_w = width - logo_x
            if logo_y + logo_h > height:
                logo_h = height - logo_y
                
            if logo_w > 0 and logo_h > 0 and logo_x < width and logo_y < height:
                try:
                    img = cv2.imread(str(logo_path), cv2.IMREAD_UNCHANGED)
                    if img is not None:
                        img = cv2.resize(img, (logo_w, logo_h))
                        remove_green = logo_config.get("remove_green", False)
                        if remove_green:
                            hsv = cv2.cvtColor(img if img.shape[2] == 3 else img[:, :, :3], cv2.COLOR_BGR2HSV)
                            lower_green = np.array([35, 40, 40])
                            upper_green = np.array([85, 255, 255])
                            mask = cv2.inRange(hsv, lower_green, upper_green)
                            if img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                            img[mask > 0, 3] = 0
                        elif img.shape[2] == 3:
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                        
                        if img.shape[2] == 4:
                            alpha = (img[:, :, 3] / 255.0)[:, :, np.newaxis]
                            logo_rgb = img[:, :, :3]
                        else:
                            alpha = np.ones((logo_h, logo_w, 1))
                            logo_rgb = img
                        
                        logo_blend_data = (logo_x, logo_y, logo_w, logo_h, alpha, logo_rgb)
                        logger.info(f"✅ Pre-loaded Logo for export: {os.path.basename(str(logo_path))} at ({logo_x}, {logo_y}) [{logo_w}x{logo_h}]")
                except Exception as e:
                    logger.error(f"Error pre-loading logo for export: {e}")

        # 3. OPTIMIZATION: Subtitle Segment Cache dictionary for 10x-30x export speedup
        subtitle_cache = {}
        burn_enabled = burn_sub_config.get("enabled", False)
        
        logger.info(f"⚡ Applying ultra-fast cached effects (Blur, Text, Logo, Burn Subtitle) to {total_frames} frames...")
        
        frame_count = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 1. Apply Gaussian Blur to ROI (Fast downscaled blur)
            if blur_config.get("enabled", False) and blur_config.get("rect"):
                blur_rect = blur_config["rect"]
                intensity = blur_config.get("intensity", 30)
                x1 = max(0, int(blur_rect.x() * scale_x))
                y1 = max(0, int(blur_rect.y() * scale_y))
                x2 = min(width, int((blur_rect.x() + blur_rect.width()) * scale_x))
                y2 = min(height, int((blur_rect.y() + blur_rect.height()) * scale_y))
                if x1 < x2 and y1 < y2:
                    roi = frame[y1:y2, x1:x2]
                    if roi.size > 0:
                        # Fast downscaling blur
                        rh, rw = roi.shape[:2]
                        small = cv2.resize(roi, (max(1, rw // 2), max(1, rh // 2)))
                        ksize = max(3, int(intensity / 100.0 * 21.0) | 1)
                        blurred_small = cv2.GaussianBlur(small, (ksize, ksize), 0)
                        frame[y1:y2, x1:x2] = cv2.resize(blurred_small, (rw, rh))
            
            # 2. Apply Text Overlay (Pre-rendered static mask, <0.05ms)
            if static_text_mask is not None:
                frame[static_text_mask] = static_text_bgr[static_text_mask]
            
            # 3. Apply Logo Overlay (Pre-calculated alpha blend, <0.05ms)
            if logo_blend_data is not None:
                lx, ly, lw, lh, l_alpha, l_rgb = logo_blend_data
                roi = frame[ly:ly+lh, lx:lx+lw]
                frame[ly:ly+lh, lx:lx+lw] = (l_alpha * l_rgb + (1.0 - l_alpha) * roi).astype(np.uint8)
            
            # 4. Apply Burn Subtitle (Cached per segment, <0.05ms)
            if burn_enabled and segments:
                cur_sec = frame_count / max(1.0, fps)
                active_seg = None
                seg_idx = -1
                for idx, seg in enumerate(segments):
                    if seg.get("start", 0.0) <= cur_sec <= seg.get("end", 0.0):
                        active_seg = seg
                        seg_idx = idx
                        break
                
                if active_seg:
                    raw_sub = active_seg.get("khmer_text") or active_seg.get("original_text") or active_seg.get("text", "")
                    sub_text = re.sub(r'^\s*(?:\[|\()?\s*(ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)\s*(?:\]|\))?\s*[:：\-–—]?\s*', '', raw_sub, flags=re.IGNORECASE).strip()
                    if sub_text.startswith('[') and ']' in sub_text[:15]:
                        sub_text = re.sub(r'^\s*\[[^\]]+\]\s*', '', sub_text).strip()
                    if not sub_text:
                        sub_text = raw_sub.strip()
                    if sub_text:
                        if seg_idx not in subtitle_cache:
                            try:
                                sub_mask, sub_bgr = _render_subtitle_overlay_qt(
                                    sub_text=sub_text,
                                    font_name=burn_sub_config.get("font_name", "Kantumruy Pro"),
                                    font_size_pt=burn_sub_config.get("font_size", 20),
                                    color_rgb=burn_sub_config.get("color_rgb", (255, 255, 255)),
                                    bg_opacity=burn_sub_config.get("bg_opacity", 0.6),
                                    width=width,
                                    height=height,
                                    scale_y=scale_y
                                )
                                subtitle_cache[seg_idx] = (sub_mask, sub_bgr)
                            except Exception as e:
                                logger.error(f"Error caching burn subtitle for segment {seg_idx}: {e}")
                                subtitle_cache[seg_idx] = (None, None)
                        
                        sub_mask, sub_bgr = subtitle_cache.get(seg_idx, (None, None))
                        if sub_mask is not None:
                            frame[sub_mask] = sub_bgr[sub_mask]
            
            out.write(frame)
            frame_count += 1
            if frame_count % 150 == 0:
                logger.info(f"⚡ Fast Export Progress: {frame_count}/{total_frames} frames processed")
        
        cap.release()
        out.release()
        
        # Re-encode to universal H.264 MP4 with FFmpeg
        cmd = [
            "ffmpeg", "-y",
            "-i", raw_effects_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "19",
            output_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                if os.path.exists(raw_effects_path):
                    try: os.remove(raw_effects_path)
                    except Exception: pass
                logger.info(f"🎉 Universal H.264 Video Effects applied successfully: {output_path}")
                return True
        except Exception as e:
            logger.warning(f"FFmpeg H.264 encode fallback: {e}")
        
        # Fallback if ffmpeg failed
        if os.path.exists(raw_effects_path):
            shutil.move(raw_effects_path, output_path)
            return True
            
        logger.info(f"🎉 Ultra-Fast Video Effects applied to all {frame_count} frames successfully: {output_path}")
        return os.path.exists(output_path)
