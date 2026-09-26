import sys
import os

# Prevent OpenBLAS / PyTorch multi-threaded stack allocation crash on macOS ARM64
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from PIL import ImageFont
from qt_compat import QApplication, Qt
from gui.main_window import MainWindow
from utils.file_utils import ensure_directories
from utils.ffmpeg import is_ffmpeg_available

def check_khmer_fonts():
    font_paths = [
        'fonts/KhmerOS.ttf',
        'fonts/KhmerOSBattambang.ttf',
        'fonts/KantumruyPro.ttf',
        'fonts/NotoSansKhmer.ttf',
        'fonts/Battambang.ttf',
        '/System/Library/Fonts/Supplemental/Khmer Sangam MN.ttf',
    ]
    
    found = []
    for path in font_paths:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, 24)
                found.append(f"✅ {path}")
            except Exception as e:
                found.append(f"⚠️ {path} (error: {e})")
        else:
            found.append(f"❌ {path} (not found)")
    
    print("\n=== Khmer Font Check ===")
    for f in found:
        print(f)
    print("========================\n")

def main():
    check_khmer_fonts()

    # High DPI scaling support
    if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Khmer Video Translator")
    app.setOrganizationName("KhmerAI")

    # Ensure output and temp dirs exist
    ensure_directories()

    # Warn if FFmpeg is missing
    if not is_ffmpeg_available():
        print("WARNING: FFmpeg command not found in system PATH. Video combination features require FFmpeg.")

    window = MainWindow()
    window.show()

    sys.exit(app.exec_() if hasattr(app, 'exec_') else app.exec())

if __name__ == "__main__":
    main()
