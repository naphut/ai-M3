import os
import sys
import re
import shutil
import wave
import subprocess
import cv2
import math
import numpy as np
from qt_compat import (
    Qt, Signal, Slot, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QLineEdit, QAbstractItemView, QSlider, QCheckBox, QRadioButton, QSpinBox,
    QDoubleSpinBox, QComboBox, QGroupBox, QScrollArea, QMediaPlayer, QAudioOutput, QProgressBar,
    QUrl, create_media_content, QtGui, QtCore, QScrollBar, QTabWidget, QColorDialog,
    QMenu, QAction, QToolButton, QStyledItemDelegate, QStyleOptionViewItem,
    QDialog, QDialogButtonBox, QMessageBox
)
from services.voxcpm_service import (
    VOICE_PRESETS, VOICE_NAMES, VOICE_CATEGORIES, VoxCPMService, 
    add_custom_voice_preset, export_mp3, preprocess_reference_audio,
    extract_audio_from_video, extract_best_speech_segment, extract_segment_audio
)
from utils.file_utils import get_temp_path
from utils.logger import logger
from core.models import (
    PERSONA_CHOICES, EMOTION_CHOICES, STYLE_CHOICES, PERSONA_DEFAULT_VOICE,
    SpeakerProfile, Segment, ProjectData
)

# ==================== QT KHMER FONT REGISTRATION ====================
_loaded_qt_fonts = set()
def ensure_qt_fonts():
    """Register all project TrueType fonts into Qt QFontDatabase for native HarfBuzz Khmer Unicode shaping."""
    font_dir = os.path.abspath('fonts')
    if os.path.exists(font_dir):
        for f in os.listdir(font_dir):
            if f.endswith('.ttf') or f.endswith('.otf'):
                p = os.path.join(font_dir, f)
                if p not in _loaded_qt_fonts:
                    QtGui.QFontDatabase.addApplicationFont(p)
                    _loaded_qt_fonts.add(p)

def resolve_qt_font_name(requested_name: str) -> str:
    """Map dropdown selection to exact registered Qt font family name."""
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


# ==================== AUDIO WAVEFORM CANVAS ====================
class AudioWaveformCanvas(QWidget):
    """
    Developer-Grade Interactive Audio Waveform Canvas & Time Ruler.
    Renders timeline tracks, speech waveform peaks, and live playhead line.
    """
    seek_requested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.zoom_factor = 1.0
        self.playhead_pos_sec = 0.0
        self.total_duration_sec = 60.0
        self.setFixedHeight(100)
        self.setMinimumWidth(800)

    def set_data(self, segments: list, playhead_sec: float = None, zoom: float = None):
        if segments is not None:
            self.segments = segments
            if segments:
                self.total_duration_sec = max(30.0, segments[-1].get("end", 30.0) + 5.0)
        if playhead_sec is not None:
            self.playhead_pos_sec = playhead_sec
        if zoom is not None:
            self.zoom_factor = zoom
            
        pixels_per_sec = 40 * self.zoom_factor
        self.setMinimumWidth(int(max(800, self.total_duration_sec * pixels_per_sec)))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        pixels_per_sec = 40 * self.zoom_factor
        
        # 1. Canvas Background
        painter.fillRect(0, 0, width, height, QtGui.QColor("#0a0e1a"))
        
        # 2. Time Ruler Bar
        painter.fillRect(0, 0, width, 22, QtGui.QColor("#11162a"))
        painter.setPen(QtGui.QColor("#1f2a44"))
        painter.drawLine(0, 22, width, 22)
        
        ruler_step = 5 if pixels_per_sec > 20 else 10
        sec = 0.0
        while sec <= self.total_duration_sec:
            x = int(sec * pixels_per_sec)
            painter.setPen(QtGui.QColor("#00f0ff" if sec % 10 == 0 else "#4a5a7a"))
            painter.drawLine(x, 8 if sec % 10 == 0 else 14, x, 22)
            
            m = int(sec // 60)
            s = int(sec % 60)
            painter.setFont(QtGui.QFont("monospace", 8, QtGui.QFont.Bold if sec % 10 == 0 else QtGui.QFont.Normal))
            painter.drawText(x + 3, 17, f"{m:02d}:{s:02d}")
            sec += ruler_step

        # 3. Audio Tracks & Speech Waveform Peak Blocks
        y_top = 28
        track_h = height - y_top - 6
        center_y = y_top + track_h / 2.0
        
        # Track lane background
        painter.fillRect(0, y_top, width, track_h, QtGui.QColor("#0d1122"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#1a2240"), 1, Qt.DashLine))
        painter.drawLine(0, int(center_y), width, int(center_y))

        # High-Speed Viewport Culling: Only render segments within visible horizontal rect
        visible_rect = event.rect()
        v_left = visible_rect.left() - 50
        v_right = visible_rect.right() + 50

        for idx, seg in enumerate(self.segments):
            st = seg.get("start", 0.0)
            et = seg.get("end", 0.0)
            x_start = int(st * pixels_per_sec)
            x_end = int(et * pixels_per_sec)

            # Skip if segment is completely off-screen (saves 95% CPU on 700+ segments)
            if x_end < v_left or x_start > v_right:
                continue

            seg_w = max(6, x_end - x_start)
            
            is_cyan = (idx % 2 == 0)
            bg_color = QtGui.QColor("#00f0ff" if is_cyan else "#7c4dff")
            bg_color.setAlpha(45)
            border_color = QtGui.QColor("#00f0ff" if is_cyan else "#9166ff")
            
            # Segment block background
            painter.setBrush(QtGui.QBrush(bg_color))
            painter.setPen(QtGui.QPen(border_color, 1.5))
            rect = QtCore.QRect(x_start, y_top + 2, seg_w, track_h - 4)
            painter.drawRoundedRect(rect, 4, 4)
            
            # Draw Audio Waveform Peak lines inside segment (step 5px instead of 3px for high speed)
            painter.setPen(QtGui.QPen(border_color.lighter(130), 1))
            num_bars = int(seg_w / 5)
            for b in range(num_bars):
                bx = x_start + b * 5
                amp = (math.sin(b * 0.4) * 0.4 + math.sin(b * 0.95) * 0.35 + 0.25) * (track_h / 2.0 - 6)
                painter.drawLine(bx, int(center_y - amp), bx, int(center_y + amp))
                
            # Text Preview inside track block
            text_str = seg.get("khmer_text", seg.get("original_text", seg.get("text", "")))
            if seg_w > 40:
                painter.setPen(QtGui.QColor("#ffffff"))
                painter.setFont(QtGui.QFont("Kantumruy Pro", 8, QtGui.QFont.Bold))
                painter.drawText(QtCore.QRect(x_start + 4, y_top + 4, seg_w - 8, 14), Qt.AlignLeft | Qt.AlignVCenter, text_str)

        # 4. Interactive Red Playhead Vertical Indicator
        playhead_x = int(self.playhead_pos_sec * pixels_per_sec)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ff1744"), 2))
        painter.drawLine(playhead_x, 0, playhead_x, height)
        
        # Red Playhead Top Handle Polygon
        playhead_head = QtGui.QPolygon([
            QtCore.QPoint(playhead_x - 6, 0),
            QtCore.QPoint(playhead_x + 6, 0),
            QtCore.QPoint(playhead_x, 8)
        ])
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff1744")))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(playhead_head)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pixels_per_sec = 40 * self.zoom_factor
            if pixels_per_sec > 0:
                sec = max(0.0, event.pos().x() / pixels_per_sec)
                self.playhead_pos_sec = sec
                self.update()
                self.seek_requested.emit(sec)



# ==================== DEDICATED PASTE SRT DIALOG ====================
class PasteSRTDialog(QDialog):
    """Dedicated Dialog for pasting, reviewing, and applying SRT subtitles into Desktop Studio."""
    subtitles_applied = Signal(str)

    def __init__(self, parent=None, initial_text=""):
        super().__init__(parent)
        self.setWindowTitle("📋 កន្លែង Paste SRT Subtitle (Paste SRT Zone)")
        self.resize(760, 560)
        self.setMinimumSize(600, 420)
        self._init_ui(initial_text)

    def _init_ui(self, initial_text):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # 1. Header Banner
        header = QFrame(self)
        header.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1e1b4b, stop:1 #0f172a);
                border: 1px solid #6366f1;
                border-radius: 10px;
                padding: 8px;
            }
        """)
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(8, 4, 8, 4)

        icon_lbl = QLabel("📋", self)
        icon_lbl.setStyleSheet("font-size: 26px;")
        h_lay.addWidget(icon_lbl)

        info_lay = QVBoxLayout()
        title_lbl = QLabel("កន្លែង Paste អត្ថបទ SRT ចូល Desktop Studio", self)
        title_lbl.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 14px;")
        desc_lbl = QLabel("លោកអ្នកអាចចុច Cmd+V ឬចុច Mouse ស្ដាំ ➔ Paste អត្ថបទ SRT ពី Web Studio, ChatGPT ឬ File ចូលក្នុងប្រអប់ខាងក្រោម៖", self)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        info_lay.addWidget(title_lbl)
        info_lay.addWidget(desc_lbl)
        h_lay.addLayout(info_lay)
        h_lay.addStretch()

        layout.addWidget(header)

        # 2. Quick Action Toolbar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.paste_clip_btn = QPushButton("📋 Paste ពី Clipboard (Cmd+V)", self)
        self.paste_clip_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0284c7, stop:1 #0369a1);
                color: #ffffff; font-weight: bold; font-size: 11px; border-radius: 6px; padding: 6px 14px;
            }
            QPushButton:hover { background: #38bdf8; color: #000; }
        """)
        self.paste_clip_btn.clicked.connect(self._paste_from_clipboard)
        action_bar.addWidget(self.paste_clip_btn)

        self.fetch_web_btn = QPushButton("⚡ យក SRT ពី Web Studio", self)
        self.fetch_web_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857);
                color: #ffffff; font-weight: bold; font-size: 11px; border-radius: 6px; padding: 6px 14px;
            }
            QPushButton:hover { background: #34d399; color: #000; }
        """)
        self.fetch_web_btn.clicked.connect(self._fetch_from_web_studio)
        action_bar.addWidget(self.fetch_web_btn)

        self.open_file_btn = QPushButton("📂 បើក File SRT...", self)
        self.open_file_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #cbd5e1; font-size: 11px; border: 1px solid #334155; border-radius: 6px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #334155; color: #fff; }
        """)
        self.open_file_btn.clicked.connect(self._open_srt_file)
        action_bar.addWidget(self.open_file_btn)

        self.clear_btn = QPushButton("🧹 Clear", self)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #94a3b8; font-size: 11px; border: 1px solid #334155; border-radius: 6px; padding: 6px 10px;
            }
            QPushButton:hover { background-color: #475569; color: #fff; }
        """)
        self.clear_btn.clicked.connect(self._clear_text)
        action_bar.addWidget(self.clear_btn)

        action_bar.addStretch()

        self.status_lbl = QLabel("", self)
        self.status_lbl.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: bold;")
        action_bar.addWidget(self.status_lbl)

        layout.addLayout(action_bar)

        # 3. Big SRT Text Area
        self.text_edit = QTextEdit(self)
        self.text_edit.setPlaceholderText(
            "📋 ចុច Cmd+V ឬ Right-Click ➔ Paste អត្ថបទ SRT នៅទីនេះ...\n\n"
            "ទម្រង់គំរូ SRT:\n"
            "1\n"
            "00:00:01,000 --> 00:00:04,500\n"
            "[ប្រុស] សួស្តីអ្នកទាំងអស់គ្នា!\n\n"
            "2\n"
            "00:00:05,000 --> 00:00:08,200\n"
            "[ស្រី] ថ្ងៃនេះយើងនឹងសិក្សាអំពី AI..."
        )
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #030712;
                color: #e2e8f0;
                border: 2px solid #334155;
                border-radius: 8px;
                font-family: Menlo, Monaco, 'Courier New', monospace;
                font-size: 12px;
                padding: 10px;
                line-height: 1.4;
            }
        """)

        # Pre-create count_lbl before textChanged events can fire
        self.count_lbl = QLabel("0 segments", self)
        self.count_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")

        self.text_edit.textChanged.connect(self._update_segment_count)
        layout.addWidget(self.text_edit, stretch=1)

        # Pre-fill text if available
        if initial_text:
            self.text_edit.setPlainText(initial_text)
        else:
            from qt_compat import QApplication
            clip_txt = (QApplication.clipboard().text() or "").strip()
            if clip_txt and ("-->" in clip_txt or clip_txt.startswith("[") or clip_txt.startswith("{")):
                self.text_edit.setPlainText(clip_txt)
                self.status_lbl.setText("✅ បានទាញយកពី Clipboard ស្វ័យប្រវត្តិ!")

        # 4. Bottom Action Bar
        bot_bar = QHBoxLayout()
        bot_bar.addWidget(self.count_lbl)
        self._update_segment_count()

        bot_bar.addStretch()

        self.cancel_btn = QPushButton("បោះបង់ (Cancel)", self)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #1e293b; color: #94a3b8; font-weight: bold; border-radius: 6px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #334155; color: #fff; }
        """)
        self.cancel_btn.clicked.connect(self.reject)
        bot_bar.addWidget(self.cancel_btn)

        self.apply_btn = QPushButton("✅ នាំចូលទៅក្នុងតារាង (Import Subtitles)", self)
        self.apply_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #7c3aed, stop:1 #6d28d9);
                color: #ffffff; font-weight: bold; font-size: 12px; border-radius: 6px; padding: 8px 20px;
            }
            QPushButton:hover { background: #8b5cf6; }
        """)
        self.apply_btn.clicked.connect(self._apply_subtitles)
        bot_bar.addWidget(self.apply_btn)

        layout.addLayout(bot_bar)

    def _paste_from_clipboard(self):
        from qt_compat import QApplication
        txt = (QApplication.clipboard().text() or "").strip()
        if txt:
            self.text_edit.setPlainText(txt)
            self.status_lbl.setText("✅ បាន Paste ពី Clipboard!")
        else:
            self.status_lbl.setText("⚠️ មិនមានអត្ថបទក្នុង Clipboard ឡើយ")

    def _fetch_from_web_studio(self):
        from utils.file_utils import OUTPUT_DIR
        srt_file = os.path.join(str(OUTPUT_DIR), "latest_web_subtitles.srt")
        json_file = os.path.join(str(OUTPUT_DIR), "latest_web_subtitles.json")
        files_to_check = []
        if os.path.exists(json_file):
            files_to_check.append((os.path.getmtime(json_file), json_file, "JSON with Character Tags"))
        if os.path.exists(srt_file):
            files_to_check.append((os.path.getmtime(srt_file), srt_file, "SRT"))
        
        if files_to_check:
            files_to_check.sort(key=lambda x: x[0], reverse=True)
            chosen_file = files_to_check[0][1]
            label = files_to_check[0][2]
            try:
                with open(chosen_file, "r", encoding="utf-8") as f:
                    self.text_edit.setPlainText(f.read())
                self.status_lbl.setText(f"✅ បានទាញយកពី Web Studio ({label})!")
                return
            except Exception as e:
                pass
        self.status_lbl.setText("⚠️ រកមិនឃើញ Subtitle ថ្មីពី Web Studio ឡើយ")

    def _open_srt_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open SRT / Subtitle File", "", "Subtitle Files (*.srt *.vtt *.txt *.json)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.text_edit.setPlainText(f.read())
                self.status_lbl.setText(f"✅ បានបើក: {os.path.basename(file_path)}")
            except Exception as e:
                self.status_lbl.setText(f"⚠️ កំហុស: {e}")

    def _clear_text(self):
        self.text_edit.clear()
        self.status_lbl.setText("")

    def _update_segment_count(self):
        txt = self.text_edit.toPlainText().strip()
        if not txt:
            self.count_lbl.setText("0 segments")
            return
        c = txt.count("-->")
        if c > 0:
            self.count_lbl.setText(f"📊 រកឃើញ {c} subtitle segments")
        elif txt.startswith("[") or txt.startswith("{"):
            self.count_lbl.setText("📊 JSON format detected")
        else:
            lines = [l for l in txt.split("\n") if l.strip()]
            self.count_lbl.setText(f"📊 {len(lines)} lines")

    def _apply_subtitles(self):
        txt = self.text_edit.toPlainText().strip()
        if not txt:
            QMessageBox.warning(self, "Warning", "សូម Paste ឬបញ្ចូលអត្ថបទ SRT ជាមុនសិន។")
            return
        self.subtitles_applied.emit(txt)
        self.accept()


# ==================== SUBTITLE TABLE WITH VOICE ACTIONS & CLONE VOICE ====================
class SubtitleTableWidget(QWidget):
    """Enhanced Subtitle Table with Voice Actions, Speaker Detection, Voice Categories, and Voice Cloning"""
    seek_requested = Signal(float)
    generate_voices_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.clone_voice_samples = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Top Toolbar for Voice Actions & Cloning
        toolbar = QFrame(self)
        toolbar.setStyleSheet("""
            QFrame {
                background-color: #0c101d;
                border: 1px solid #1a233a;
                border-radius: 8px;
                padding: 2px 4px;
            }
        """)
        toolbar_lay = QHBoxLayout(toolbar)
        toolbar_lay.setContentsMargins(6, 3, 6, 3)
        toolbar_lay.setSpacing(6)

        # Voice Actions Label
        voice_actions_lbl = QLabel("🎙 Voices:", self)
        voice_actions_lbl.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        toolbar_lay.addWidget(voice_actions_lbl)

        # Generate All Voices Button
        self.generate_voices_btn = QPushButton("🔊 Generate Voices", self)
        self.generate_voices_btn.setProperty("class", "btn-primary")
        self.generate_voices_btn.setToolTip("សំយោគសំឡេងខ្មែរគ្រប់ជួរទាំងអស់ (Generate All Voices) ដើម្បីចាក់ស្តាប់សាកល្បងជាមួយវីដេអូ")
        self.generate_voices_btn.clicked.connect(self.generate_voices_requested.emit)
        toolbar_lay.addWidget(self.generate_voices_btn)


        # Separator
        sep = QFrame(self)
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background-color: #1e2942; max-height: 20px;")
        toolbar_lay.addWidget(sep)

        toolbar_lay.addStretch()

        # Voice Category Dropdown
        cat_lbl = QLabel("Cat:", self)
        cat_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        toolbar_lay.addWidget(cat_lbl)
        self.voice_category_combo = QComboBox(self)
        self.voice_category_combo.addItems(["All", "Adult Female", "Adult Male", "Child Boy", "Child Girl", "Elder", "Cartoon/Special"])
        self.voice_category_combo.currentTextChanged.connect(self._update_voice_presets)
        toolbar_lay.addWidget(self.voice_category_combo)

        # Voice Preset Dropdown
        self.voice_preset_combo = QComboBox(self)
        self.voice_preset_combo.addItems(list(VOICE_PRESETS.keys()))
        self.voice_preset_combo.setMinimumWidth(200)
        toolbar_lay.addWidget(self.voice_preset_combo)

        # Apply Voice to Selected
        self.apply_voice_btn = QPushButton("✓ Apply", self)
        self.apply_voice_btn.setProperty("class", "btn-primary")
        self.apply_voice_btn.clicked.connect(self._apply_voice_to_selected)
        toolbar_lay.addWidget(self.apply_voice_btn)

        # 2️⃣ Scene Preview Button (15-30s range)
        self.scene_preview_btn = QPushButton("🎬 2️⃣ Scene Preview", self)
        self.scene_preview_btn.setProperty("class", "btn-secondary")
        self.scene_preview_btn.setToolTip("2️⃣ Scene Preview: Preview dialogue for selected lines (15-30 seconds)")
        self.scene_preview_btn.clicked.connect(self._preview_scene)
        toolbar_lay.addWidget(self.scene_preview_btn)

        # 👥 Global Speaker Profiles Button
        self.spk_profiles_btn = QPushButton("👥 Speaker Profiles", self)
        self.spk_profiles_btn.setProperty("class", "btn-secondary")
        self.spk_profiles_btn.setToolTip("Manage Global Speaker Personas & Assigned Voices across the project")
        self.spk_profiles_btn.clicked.connect(self._show_speaker_profiles_dialog)
        toolbar_lay.addWidget(self.spk_profiles_btn)

        layout.addWidget(toolbar)

        # Table Widget (9 Columns: #, Start, End, Persona, Emotion, Style, Khmer Text, Voice, Action)
        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels([
            "#", "Start", "End", "Persona", "Emotion", "Style", "Khmer Text", "Voice", "Action"
        ])
        
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0d1122;
                border: 1px solid #1a2240;
                border-radius: 10px;
                gridline-color: #141a30;
                color: #e2e8f0;
                font-size: 12px;
                alternate-background-color: #11162a;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #161b2a;
            }
            QTableWidget::item:selected {
                background-color: #1a2240;
                color: #00e676;
            }
            QHeaderView::section {
                background-color: #11162a;
                color: #64b5f6;
                padding: 6px 8px;
                border: none;
                font-weight: 700;
                font-size: 10px;
                text-transform: uppercase;
            }
        """)

        self.table.itemClicked.connect(self._on_table_item_clicked)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        layout.addWidget(self.table)

    def _on_table_item_clicked(self, item):
        if not item:
            return
        row = item.row()
        if 0 <= row < len(self.segments):
            start_sec = float(self.segments[row].get("start", 0.0))
            self.seek_requested.emit(start_sec)

    def _update_voice_presets(self, category: str):
        """Update voice preset dropdown based on selected category"""
        self.voice_preset_combo.clear()
        if category == "All":
            self.voice_preset_combo.addItems(list(VOICE_PRESETS.keys()))
        else:
            voices = VOICE_CATEGORIES.get(category, [])
            self.voice_preset_combo.addItems(voices if voices else list(VOICE_PRESETS.keys()))

    def set_segments(self, segments: list):
        self.segments = [s.to_dict() if hasattr(s, 'to_dict') else s for s in (segments or [])]
        
        # High Performance UI Optimization: Disable updates and batch rows
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(self.segments))

            for i, seg in enumerate(self.segments):
                self._insert_segment_row(i, seg)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)


    def _insert_segment_row(self, row: int, seg: dict):
        if row >= self.table.rowCount():
            self.table.insertRow(row)
        
        # 0: Index #
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
        idx_item.setTextAlignment(Qt.AlignCenter)
        idx_item.setForeground(QtGui.QColor("#8fa0c0"))
        self.table.setItem(row, 0, idx_item)
        
        # 1: Start
        start_val = seg.get('start', 0.0)
        start_str = f"{start_val:.2f}s"
        item_start = QTableWidgetItem(start_str)
        item_start.setFlags(item_start.flags() & ~Qt.ItemIsEditable)
        item_start.setForeground(QtGui.QColor("#00f0ff"))
        self.table.setItem(row, 1, item_start)

        # 2: End
        end_val = seg.get('end', 0.0)
        end_str = f"{end_val:.2f}s"
        item_end = QTableWidgetItem(end_str)
        item_end.setFlags(item_end.flags() & ~Qt.ItemIsEditable)
        item_end.setForeground(QtGui.QColor("#00f0ff"))
        self.table.setItem(row, 2, item_end)

        # 3: Persona / Speaker Persona Combo
        persona_combo = QComboBox(self)
        persona_combo.addItems(PERSONA_CHOICES)
        cur_persona = seg.get("persona") or seg.get("character") or "👨 Male Adult"
        if cur_persona in PERSONA_CHOICES:
            persona_combo.setCurrentText(cur_persona)
        else:
            persona_combo.setCurrentIndex(0)
        persona_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1122; border: 1px solid #1f2a44; border-radius: 4px;
                padding: 2px 6px; color: #38bdf8; font-size: 10px; font-weight: bold;
            }
            QComboBox::drop-down { border: none; width: 16px; }
        """)
        self.table.setCellWidget(row, 3, persona_combo)

        # 4: Emotion Combo (9 Emotions)
        emotion_combo = QComboBox(self)
        emotion_combo.addItems(EMOTION_CHOICES)
        cur_emotion = seg.get("emotion") or "😐 Neutral"
        if cur_emotion in EMOTION_CHOICES:
            emotion_combo.setCurrentText(cur_emotion)
        else:
            emotion_combo.setCurrentIndex(0)
        emotion_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1122; border: 1px solid #1f2a44; border-radius: 4px;
                padding: 2px 6px; color: #facc15; font-size: 10px;
            }
            QComboBox::drop-down { border: none; width: 16px; }
        """)
        self.table.setCellWidget(row, 4, emotion_combo)

        # 5: Speaking Style Combo (8 Styles)
        style_combo = QComboBox(self)
        style_combo.addItems(STYLE_CHOICES)
        cur_style = seg.get("speaking_style") or seg.get("style") or "Normal"
        if cur_style in STYLE_CHOICES:
            style_combo.setCurrentText(cur_style)
        else:
            style_combo.setCurrentIndex(0)
        style_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1122; border: 1px solid #1f2a44; border-radius: 4px;
                padding: 2px 6px; color: #a78bfa; font-size: 10px;
            }
            QComboBox::drop-down { border: none; width: 16px; }
        """)
        self.table.setCellWidget(row, 5, style_combo)

        # 6: Khmer Text (Editable)
        disp_text = seg.get("khmer_text", "")
        if not disp_text:
            disp_text = seg.get("original_text", seg.get("text", ""))
        text_item = QTableWidgetItem(disp_text)
        self.table.setItem(row, 6, text_item)

        # 7: Voice Selector Combo
        v_combo = QComboBox(self)
        v_combo.addItems(list(VOICE_PRESETS.keys()))
        
        current_voice = seg.get("voice_id") or seg.get("voice")
        if not current_voice or current_voice not in VOICE_PRESETS:
            current_voice = PERSONA_DEFAULT_VOICE.get(cur_persona, "Khmer Male - Piseth")

        if current_voice in VOICE_PRESETS:
            v_combo.setCurrentText(current_voice)
        else:
            v_combo.setCurrentIndex(0)
        
        v_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1122;
                border: 1px solid #1f2a44;
                border-radius: 4px;
                padding: 2px 6px;
                color: #e2e8f0;
                font-size: 10px;
            }
            QComboBox::drop-down {
                border: none;
                width: 16px;
            }
        """)
        self.table.setCellWidget(row, 7, v_combo)

        # Auto-suggest default voice when persona changes
        persona_combo.currentTextChanged.connect(
            lambda new_p, vc=v_combo: vc.setCurrentText(PERSONA_DEFAULT_VOICE.get(new_p, "Khmer Male - Piseth"))
        )

        # 8: Action Buttons (▶ Line Preview, 🎙 Regen)
        action_widget = QWidget(self)
        action_lay = QHBoxLayout(action_widget)
        action_lay.setContentsMargins(2, 2, 2, 2)
        action_lay.setSpacing(4)

        play_btn = QPushButton("▶", self)
        play_btn.setToolTip("1️⃣ Line Preview: Synthesize and play this line (1 Subtitle)")
        play_btn.setFixedSize(26, 22)
        play_btn.setStyleSheet("""
            QPushButton {
                background-color: #00c853;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #00e676; }
        """)
        play_btn.clicked.connect(lambda _, r=row: self._preview_tts(r))
        action_lay.addWidget(play_btn)

        regen_btn = QPushButton("🎙", self)
        regen_btn.setToolTip("Re-synthesize this line with new emotion/style")
        regen_btn.setFixedSize(26, 22)
        regen_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c4dff;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 10px;
            }
            QPushButton:hover { background-color: #9166ff; }
        """)
        regen_btn.clicked.connect(lambda _, r=row: self._preview_tts(r))
        action_lay.addWidget(regen_btn)

        action_lay.addStretch()
        self.table.setCellWidget(row, 8, action_widget)

    def get_updated_segments(self) -> list:
        updated = []
        for i in range(self.table.rowCount()):
            start_item = self.table.item(i, 1)
            end_item = self.table.item(i, 2)
            persona_widget = self.table.cellWidget(i, 3)
            emotion_widget = self.table.cellWidget(i, 4)
            style_widget = self.table.cellWidget(i, 5)
            text_item = self.table.item(i, 6)
            voice_widget = self.table.cellWidget(i, 7)
            
            try:
                st_str = start_item.text().replace("s", "") if start_item else f"{i * 3.0}"
                et_str = end_item.text().replace("s", "") if end_item else f"{(i + 1) * 3.0}"
                st = float(st_str)
                et = float(et_str)
            except Exception:
                st, et = i * 3.0, (i + 1) * 3.0

            curr_text = text_item.text() if text_item else ""
            persona = persona_widget.currentText() if persona_widget else "👨 Male Adult"
            emotion = emotion_widget.currentText() if emotion_widget else "😐 Neutral"
            style = style_widget.currentText() if style_widget else "Normal"
            voice = voice_widget.currentText() if voice_widget else PERSONA_DEFAULT_VOICE.get(persona, "Khmer Male - Piseth")
            
            orig_seg = self.segments[i] if i < len(self.segments) else {}
            orig_text = orig_seg.get("original_text", orig_seg.get("text", curr_text))
            spk_id = orig_seg.get("speaker_id") or orig_seg.get("speaker") or f"speaker_{1 + (i % 2):02d}"

            seg_obj = Segment(
                id=str(orig_seg.get("id", i + 1)),
                start=st,
                end=et,
                speaker_id=spk_id,
                persona=persona,
                emotion=emotion,
                speaking_style=style,
                original_text=orig_text,
                translated_text=curr_text,
                voice_id=voice,
                tts_audio=orig_seg.get("tts_audio")
            )
            updated.append(seg_obj.to_dict())
        return updated

    # ==================== VOICE PROMPT DESIGNER DIALOG ====================
    def _open_voice_prompt_designer(self):
        """Open the AI Voice Studio Dialog (Prompt -> Text -> Generate -> Result)"""
        dialog = AIVoiceStudioDialog(self)
        dialog.exec()
        # Always refresh voice presets dropdowns
        self._update_voice_presets("All")

    # ==================== CLONE VOICE & ADD VOICE STUDIO ====================
    def _add_custom_voice_dialog(self, initial_audio=None, initial_text=None, initial_name=None):
        """Developer-Grade VoxCPM2 Voice Clone Studio Dialog"""
        from utils.file_utils import get_temp_path
        from services.voxcpm_service import (
            VOICE_PRESETS, VOICE_NAMES, VOICE_CATEGORIES, 
            add_custom_voice_preset, preprocess_reference_audio,
            extract_best_speech_segment, extract_segment_audio,
            extract_audio_from_video, export_mp3, VoxCPM2Runner
        )
        
        dialog = QDialog(self)
        dialog.setWindowTitle("🎙️ VoxCPM2 Neural Voice Clone & Voice Studio")
        dialog.setMinimumSize(680, 700)
        dialog.resize(720, 720)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #080c16;
                color: #f1f5f9;
                font-family: 'Segoe UI', 'Kantumruy Pro', 'Khmer OS Battambang', sans-serif;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
            }
            QLineEdit, QTextEdit {
                background-color: #0c101d;
                border: 1px solid #1e2942;
                border-radius: 6px;
                padding: 7px 10px;
                color: #f1f5f9;
                font-size: 12px;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #38bdf8;
            }
            QTabWidget::pane {
                border: 1px solid #1e2942;
                border-radius: 8px;
                background-color: #0a0e1a;
                top: -1px;
            }
            QTabBar::tab {
                background: #080c16;
                color: #94a3b8;
                border: 1px solid #1e2942;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                margin-right: 2px;
                font-weight: 600;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #0a0e1a;
                color: #38bdf8;
                border-color: #2563eb;
                border-bottom: 2px solid #38bdf8;
            }
            QGroupBox {
                background-color: #0c101d;
                border: 1px solid #1a233a;
                border-radius: 8px;
                padding: 12px;
                margin-top: 10px;
                font-size: 11px;
                font-weight: bold;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
            }
            QScrollArea {
                border: 1px solid #1e2942;
                border-radius: 8px;
                background-color: #080c16;
            }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Title Banner
        banner = QFrame(dialog)
        banner.setStyleSheet("background-color: #0c101d; border: 1px solid #1a233a; border-radius: 8px; padding: 6px 12px;")
        ban_lay = QHBoxLayout(banner)
        ban_lay.setContentsMargins(4, 4, 4, 4)
        
        ban_title = QLabel("🎙️ VoxCPM2 Neural Voice Clone & Studio", banner)
        ban_title.setStyleSheet("color: #38bdf8; font-size: 15px; font-weight: 800;")
        ban_sub = QLabel("Zero-Shot Timbre Cloning • 8-Band Formant EQ • Multi-Speaker Studio", banner)
        ban_sub.setStyleSheet("color: #64748b; font-size: 11px;")
        
        ban_col = QVBoxLayout()
        ban_col.addWidget(ban_title)
        ban_col.addWidget(ban_sub)
        ban_lay.addLayout(ban_col)
        ban_lay.addStretch()
        
        layout.addWidget(banner)

        # Non-blocking audio playback helper
        _current_audio_proc = [None]
        def _play_audio_non_blocking(audio_path: str):
            if not audio_path or not os.path.exists(audio_path):
                return
            try:
                if _current_audio_proc[0] and _current_audio_proc[0].poll() is None:
                    try: _current_audio_proc[0].terminate()
                    except Exception: pass
                
                if sys.platform == "darwin":
                    _current_audio_proc[0] = subprocess.Popen(["afplay", audio_path])
                elif sys.platform.startswith("linux"):
                    _current_audio_proc[0] = subprocess.Popen(["aplay", audio_path])
                elif sys.platform == "win32":
                    os.startfile(audio_path)
            except Exception as e:
                logger.error(f"Playback error: {e}")

        def _process_and_extract_ref_audio(file_path, name="RefVoice"):
            if not file_path or not os.path.exists(file_path):
                return None
            
            clean_audio = get_temp_path(f"clone_clean_{name}.wav")
            audio_path = file_path
            
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.mp4', '.mov', '.mkv', '.avi', '.webm']:
                from services.audio_extractor import AudioExtractor
                temp_extracted = get_temp_path(f"clone_extract_{name}.wav")
                extracted = AudioExtractor().extract_audio(file_path, temp_extracted)
                if extracted and os.path.exists(extracted):
                    audio_path = extracted

            from services.vad_service import VADService
            best_seg = VADService().extract_best_speech_segment(audio_path)
            if not best_seg:
                logger.error(f"❌ [VAD] No human speech segments detected in '{audio_path}'")
                return None

            start_sec, end_sec = best_seg
            seg_audio = get_temp_path(f"clone_segment_{name}.wav")
            if extract_segment_audio(audio_path, start_sec, end_sec, seg_audio):
                audio_path = seg_audio

            from services.voice_cleaner import VoiceCleaner
            cleaned = VoiceCleaner().clean_reference_audio(audio_path, clean_audio)
            if cleaned and os.path.exists(cleaned):
                return cleaned

            return audio_path

        # Main Tab Widget
        tabs = QTabWidget(dialog)

        # ==================== TAB 1: CLONE NEW VOICE ====================
        clone_tab = QWidget()
        c_lay = QVBoxLayout(clone_tab)
        c_lay.setContentsMargins(12, 12, 12, 12)
        c_lay.setSpacing(10)

        # Step 1: Voice Info Box
        step1_box = QGroupBox("1. Voice Profile & Identity", clone_tab)
        s1_lay = QHBoxLayout(step1_box)
        s1_lay.setSpacing(10)

        s1_lay.addWidget(QLabel("Voice Name:", step1_box))
        vn_input = QLineEdit(initial_name or "", step1_box)
        vn_input.setPlaceholderText("e.g. Khmer Male - Alex, Sokha Narrator...")
        s1_lay.addWidget(vn_input, stretch=2)

        s1_lay.addWidget(QLabel("Gender:", step1_box))
        gender_combo = QComboBox(step1_box)
        gender_combo.addItems(["male", "female"])
        s1_lay.addWidget(gender_combo)

        s1_lay.addWidget(QLabel("Category:", step1_box))
        cat_combo = QComboBox(step1_box)
        cat_combo.addItems(["Cloned Voices", "Adult Male", "Adult Female", "Child Boy", "Child Girl", "Elder", "Cartoon/Special"])
        s1_lay.addWidget(cat_combo)

        c_lay.addWidget(step1_box)

        # Step 2: Reference Audio Source
        step2_box = QGroupBox("2. Reference Audio / Video Source (5s - 30s Speech)", clone_tab)
        s2_lay = QVBoxLayout(step2_box)
        s2_lay.setSpacing(8)

        s2_row1 = QHBoxLayout()
        ref_input = QLineEdit(initial_audio or "", step2_box)
        ref_input.setPlaceholderText("Upload reference audio (*.wav, *.mp3, *.m4a) or video (*.mp4, *.mov)...")
        s2_row1.addWidget(ref_input, 1)

        upload_btn = QPushButton("📂 Browse...", step2_box)
        upload_btn.setProperty("class", "btn-gray")
        def _upload_file():
            f_path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Select Reference Audio or Video",
                "",
                "Supported Files (*.wav *.mp3 *.m4a *.flac *.mp4 *.mov *.mkv *.avi);;All Files (*.*)"
            )
            if f_path:
                ref_input.setText(f_path)
        upload_btn.clicked.connect(_upload_file)
        s2_row1.addWidget(upload_btn)

        clean_voice_btn = QPushButton("🧹 Clean VAD", step2_box)
        clean_voice_btn.setProperty("class", "btn-green")
        def _clean_voice_action():
            f_path = ref_input.text().strip()
            if not f_path or not os.path.exists(f_path):
                QMessageBox.warning(dialog, "Warning", "Please select a reference audio or video file first.")
                return
            v_name = vn_input.text().strip() or "RefVoice"
            clean_audio = _process_and_extract_ref_audio(f_path, v_name)
            if clean_audio and os.path.exists(clean_audio):
                ref_status_lbl.setText(f"✓ Clean Speech Extracted: {os.path.basename(clean_audio)}")
                ref_status_lbl.setStyleSheet("color: #10b981; font-weight: bold;")
                _play_audio_non_blocking(clean_audio)
            else:
                QMessageBox.warning(dialog, "Error", "Failed to extract clean speech clip.")
        clean_voice_btn.clicked.connect(_clean_voice_action)
        s2_row1.addWidget(clean_voice_btn)

        play_ref_btn = QPushButton("▶ Audition", step2_box)
        play_ref_btn.setProperty("class", "btn-primary")
        def _play_ref_file():
            f_path = ref_input.text().strip()
            if not f_path or not os.path.exists(f_path):
                QMessageBox.warning(dialog, "Warning", "Please select a reference audio or video file first.")
                return
            clean_audio = _process_and_extract_ref_audio(f_path, vn_input.text().strip() or "RefVoice")
            if clean_audio and os.path.exists(clean_audio):
                _play_audio_non_blocking(clean_audio)
        play_ref_btn.clicked.connect(_play_ref_file)
        s2_row1.addWidget(play_ref_btn)

        s2_lay.addLayout(s2_row1)

        ref_status_lbl = QLabel("💡 Tip: Upload a clear speech clip without background music for best neural clone accuracy.", step2_box)
        ref_status_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        s2_lay.addWidget(ref_status_lbl)

        c_lay.addWidget(step2_box)

        # Step 3: Reference Transcript (Prompt Text)
        step3_box = QGroupBox("3. Reference Transcript (Original Spoken Text)", clone_tab)
        s3_lay = QHBoxLayout(step3_box)
        s3_lay.setSpacing(8)

        ref_txt_input = QLineEdit(step3_box)
        ref_txt_input.setPlaceholderText("អត្ថបទដើមរបស់ Reference Audio... (Optional: Leave blank for auto-transcribe)")
        s3_lay.addWidget(ref_txt_input, 1)

        lang_combo = QComboBox(step3_box)
        lang_combo.addItems(["Auto Detect", "English (en)", "Khmer (km)", "Chinese (zh)", "Japanese (ja)"])
        s3_lay.addWidget(lang_combo)

        transcribe_ref_btn = QPushButton("📝 Transcribe Ref", step3_box)
        transcribe_ref_btn.setProperty("class", "btn-purple")
        def _transcribe_ref_action():
            f_path = ref_input.text().strip()
            if not f_path or not os.path.exists(f_path):
                QMessageBox.warning(dialog, "Warning", "Please select a reference file first.")
                return
            v_name = vn_input.text().strip() or "RefVoice"
            clean_audio = _process_and_extract_ref_audio(f_path, v_name)
            if not clean_audio:
                QMessageBox.warning(dialog, "Warning", "Could not extract clean audio.")
                return
            lang_map = {"English (en)": "en", "Khmer (km)": "km", "Chinese (zh)": "zh", "Japanese (ja)": "ja", "Auto Detect": "auto"}
            sel_lang = lang_map.get(lang_combo.currentText(), "auto")
            from services.whisper_service import WhisperService
            try:
                txt = WhisperService().transcribe_reference(clean_audio, language=sel_lang)
                if txt:
                    ref_txt_input.setText(txt)
                    ref_status_lbl.setText(f"✓ Transcribed ({sel_lang.upper()}): {txt[:40]}...")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", f"Transcription error: {e}")
        transcribe_ref_btn.clicked.connect(_transcribe_ref_action)
        s3_lay.addWidget(transcribe_ref_btn)

        c_lay.addWidget(step3_box)

        # Step 4: Live Test & Audition
        step4_box = QGroupBox("4. Test Neural Synthesis & Audition", clone_tab)
        s4_lay = QVBoxLayout(step4_box)
        s4_lay.setSpacing(8)

        s4_row = QHBoxLayout()
        test_input = QLineEdit(step4_box)
        test_input.setPlaceholderText("បញ្ចូលអត្ថបទខ្មែរដើម្បីធ្វើតេស្តសំឡេង...")
        test_input.setText("សួស្តីអ្នកទាំងអស់គ្នា! នេះជាសំឡេងដែលបាន Clone ចេញពី Video។")
        s4_row.addWidget(test_input, 1)

        eval_mode_combo = QComboBox(step4_box)
        eval_mode_combo.addItems(["Full Neural + F0 + EQ (Mode C)", "Neural + F0 Pitch (Mode B)", "Pure Neural (Mode A)"])
        s4_row.addWidget(eval_mode_combo)

        test_run_btn = QPushButton("▶ Test Clone Voice", step4_box)
        test_run_btn.setProperty("class", "btn-gold")
        def _test_clone_action():
            name = vn_input.text().strip() or "TestVoice"
            f_path = ref_input.text().strip()
            if not f_path or not os.path.exists(f_path):
                QMessageBox.warning(dialog, "Warning", "Please select a reference audio/video file first.")
                return
            clean_audio = _process_and_extract_ref_audio(f_path, name)
            if not clean_audio:
                QMessageBox.warning(dialog, "Warning", "No clean speech audio found in reference.")
                return
            
            manual_ref_txt = ref_txt_input.text().strip()
            mode_map = {
                "Full Neural + F0 + EQ (Mode C)": "full_c",
                "Neural + F0 Pitch (Mode B)": "f0_b",
                "Pure Neural (Mode A)": "pure_a"
            }
            mode_key = mode_map.get(eval_mode_combo.currentText(), "full_c")

            test_run_btn.setEnabled(False)
            test_run_btn.setText("⏳ Synthesizing...")
            QApplication.processEvents()

            try:
                runner = VoxCPM2Runner()
                test_text = test_input.text().strip() or "សួស្តីអ្នកទាំងអស់គ្នា!"
                out_wav = get_temp_path(f"clone_audition_{hash(name)}.wav")
                if runner.generate(test_text, clean_audio, manual_ref_txt, out_wav, mode=mode_key):
                    _play_audio_non_blocking(out_wav)
                else:
                    QMessageBox.warning(dialog, "Error", "Failed to synthesize cloned sample.")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", f"Test synthesis error: {e}")
            finally:
                test_run_btn.setEnabled(True)
                test_run_btn.setText("▶ Test Clone Voice")

        test_run_btn.clicked.connect(_test_clone_action)
        s4_row.addWidget(test_run_btn)
        s4_lay.addLayout(s4_row)

        c_lay.addWidget(step4_box)

        # Primary CTA Save Button
        save_clone_btn = QPushButton("💾 Save Cloned Voice to Presets", clone_tab)
        save_clone_btn.setProperty("class", "btn-primary")
        save_clone_btn.setStyleSheet("font-weight: 800; font-size: 13px; padding: 10px 20px;")
        def _save_clone_voice():
            name = vn_input.text().strip()
            if not name:
                QMessageBox.warning(dialog, "Warning", "Please enter a Voice Name.")
                return
            f_path = ref_input.text().strip()
            if not f_path or not os.path.exists(f_path):
                QMessageBox.warning(dialog, "Warning", "Please select a reference audio or video file.")
                return
            clean_audio = _process_and_extract_ref_audio(f_path, name)
            if not clean_audio:
                QMessageBox.warning(dialog, "Warning", "No clean speech detected in reference.")
                return
            
            manual_ref_txt = ref_txt_input.text().strip()
            from services.voice_profile_service import VoiceProfileService
            VoiceProfileService().create_voice_profile(name, clean_audio, prompt_text=manual_ref_txt)

            voice_key = add_custom_voice_preset(
                name=name,
                prompt_audio_path=clean_audio,
                prompt_text=manual_ref_txt,
                category=cat_combo.currentText(),
                gender=gender_combo.currentText(),
                age="adult"
            )

            self._apply_cloned_voice_to_table(voice_key, target_char=name)
            _refresh_voice_list()
            QMessageBox.information(dialog, "Voice Cloned 🎉", f"✅ Voice '{voice_key}' has been added to Presets and is ready for Dubbing!")
            tabs.setCurrentIndex(1)

        save_clone_btn.clicked.connect(_save_clone_voice)
        c_lay.addWidget(save_clone_btn)

        tabs.addTab(clone_tab, "🎙️ Clone New Voice")

        # ==================== TAB 2: VOICE LIBRARY & MANAGEMENT ====================
        lib_tab = QWidget()
        lib_lay = QVBoxLayout(lib_tab)
        lib_lay.setContentsMargins(12, 12, 12, 12)
        lib_lay.setSpacing(10)

        lib_header = QLabel("📋 Active Voice Library & Preset Bank", lib_tab)
        lib_header.setStyleSheet("color: #38bdf8; font-size: 13px; font-weight: bold;")
        lib_lay.addWidget(lib_header)

        scroll = QScrollArea(lib_tab)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: #080c16;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(6, 6, 6, 6)
        scroll_layout.setSpacing(6)
        scroll.setWidget(scroll_content)
        lib_lay.addWidget(scroll, 1)

        def _refresh_voice_list():
            while scroll_layout.count():
                child = scroll_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            idx = 1
            for name, preset in list(VOICE_PRESETS.items()):
                is_clone = preset.get("is_clone", False)
                type_tag = "[Custom Clone]" if is_clone else "[Standard Preset]"

                card = QFrame()
                card.setStyleSheet("""
                    QFrame {
                        background-color: #0c101d;
                        border: 1px solid #1a233a;
                        border-radius: 6px;
                    }
                    QFrame:hover {
                        border: 1px solid #38bdf8;
                        background-color: #0f1527;
                    }
                """)
                card_lay = QHBoxLayout(card)
                card_lay.setContentsMargins(10, 6, 10, 6)
                card_lay.setSpacing(8)

                lbl_text = f"{idx}. {name}"
                item_lbl = QLabel(lbl_text, card)
                item_lbl.setStyleSheet("color: #f1f5f9; font-size: 12px; font-weight: 700; background: transparent; border: none;")
                card_lay.addWidget(item_lbl)

                tag_lbl = QLabel(type_tag, card)
                tag_style = "color: #38bdf8; font-weight: bold;" if is_clone else "color: #64748b;"
                tag_lbl.setStyleSheet(f"{tag_style} font-size: 10px; background: transparent; border: none;")
                card_lay.addWidget(tag_lbl)
                card_lay.addStretch()

                # Audition Button
                play_btn = QPushButton("▶ Audition", card)
                play_btn.setProperty("class", "btn-gray")
                play_btn.setStyleSheet("font-size: 11px; padding: 4px 8px;")

                def _make_play_handler(vname, p_audio):
                    def _play():
                        if p_audio and os.path.exists(p_audio):
                            _play_audio_non_blocking(p_audio)
                        else:
                            from services.voxcpm_service import VoxCPMService
                            svc = VoxCPMService(voice_name=vname)
                            out = get_temp_path(f"preview_{abs(hash(vname))}.wav")
                            if svc.synthesize("សួស្តី! នេះគឺជាសំឡេងគំរូ។", out):
                                _play_audio_non_blocking(out)
                    return _play
                
                play_btn.clicked.connect(_make_play_handler(name, preset.get("prompt_audio_path")))
                card_lay.addWidget(play_btn)

                if is_clone:
                    # Rename Button
                    rename_btn = QPushButton("✏ Rename", card)
                    rename_btn.setProperty("class", "btn-gray")
                    rename_btn.setStyleSheet("font-size: 11px; padding: 4px 8px;")
                    
                    def _make_rename_handler(old_name):
                        def _rename():
                            from qt_compat import QInputDialog
                            new_name, ok = QInputDialog.getText(dialog, "Rename Voice", "Enter new voice name:", QLineEdit.Normal, old_name)
                            if ok and new_name.strip() and new_name.strip() != old_name:
                                new_key = new_name.strip()
                                VOICE_PRESETS[new_key] = VOICE_PRESETS.pop(old_name)
                                VOICE_PRESETS[new_key]["name"] = new_key
                                self._update_voice_presets("All")
                                _refresh_voice_list()
                        return _rename
                    
                    rename_btn.clicked.connect(_make_rename_handler(name))
                    card_lay.addWidget(rename_btn)

                    # Delete Button
                    del_btn = QPushButton("🗑 Delete", card)
                    del_btn.setProperty("class", "btn-red")
                    del_btn.setStyleSheet("font-size: 11px; padding: 4px 8px;")
                    
                    def _make_delete_handler(vname):
                        def _del():
                            if vname in VOICE_PRESETS:
                                del VOICE_PRESETS[vname]
                                if vname in VOICE_NAMES:
                                    VOICE_NAMES.remove(vname)
                                self._update_voice_presets("All")
                                _refresh_voice_list()
                        return _del
                    
                    del_btn.clicked.connect(_make_delete_handler(name))
                    card_lay.addWidget(del_btn)

                scroll_layout.addWidget(card)
                idx += 1

            scroll_layout.addStretch()

        _refresh_voice_list()
        tabs.addTab(lib_tab, "📚 Voice Library & Presets")

        layout.addWidget(tabs, 1)

        # Dialog Footer
        footer = QHBoxLayout()
        footer.addStretch()
        
        close_btn = QPushButton("Done", dialog)
        close_btn.setProperty("class", "btn-gray")
        close_btn.setStyleSheet("padding: 6px 18px; font-weight: bold;")
        close_btn.clicked.connect(dialog.accept)
        footer.addWidget(close_btn)
        
        layout.addLayout(footer)

        dialog.exec()

    def _apply_cloned_voice_to_table(self, voice_key: str, target_char: str = None):
        """Automatically update preset dropdowns and assign cloned voice to subtitle table rows"""
        self._update_voice_presets("All")
        
        # 1. Update toolbar combo
        idx = self.voice_preset_combo.findText(voice_key)
        if idx >= 0:
            self.voice_preset_combo.setCurrentIndex(idx)

        # 2. Update table rows
        selected_rows = list(set([item.row() for item in self.table.selectedItems()]))

        for r in range(self.table.rowCount()):
            v_combo = self.table.cellWidget(r, 7)
            if not v_combo:
                continue
            
            if v_combo.findText(voice_key) < 0:
                v_combo.addItem(voice_key)
            
            c_widget = self.table.cellWidget(r, 3)
            char_name = c_widget.currentText().strip() if c_widget else ""
            
            if (target_char and target_char.lower() in char_name.lower()) or (r in selected_rows) or (not selected_rows and not target_char):
                v_combo.setCurrentText(voice_key)
                if r < len(self.segments):
                    self.segments[r]["voice"] = voice_key

        logger.info(f"✅ Assigned Cloned Voice '{voice_key}' across matching subtitle rows!")

    def _clone_voice(self):
        """Clone voice from selected segment or open Add Voice Studio"""
        selected_rows = list(set([item.row() for item in self.table.selectedItems()]))
        init_audio, init_text, init_name = None, None, None
        
        main_win = self.window()
        vid_p = getattr(main_win, 'video_player', None)
        vid_path = getattr(vid_p, 'video_path', None) if vid_p else None

        if selected_rows:
            r = selected_rows[0]
            text_item = self.table.item(r, 4)
            char_item = self.table.item(r, 3)
            start_item = self.table.item(r, 1)
            end_item = self.table.item(r, 2)

            if text_item and text_item.text().strip():
                init_text = text_item.text().strip()
            if char_item and char_item.text().strip():
                init_name = f"Clone - {char_item.text().strip()}"
            else:
                init_name = f"Clone - Segment {r+1}"

            if vid_path and os.path.exists(vid_path) and start_item and end_item:
                try:
                    def _to_sec(ts):
                        parts = ts.split(':')
                        if len(parts) == 2:
                            return float(parts[0])*60 + float(parts[1])
                        elif len(parts) == 3:
                            return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                        return float(ts)
                    st = _to_sec(start_item.text())
                    et = _to_sec(end_item.text())
                    if et > st:
                        from services.voxcpm_service import extract_audio_from_video, extract_segment_audio
                        temp_v_audio = get_temp_path(f"video_full_{r}.wav")
                        temp_s_audio = get_temp_path(f"video_seg_{r}.wav")
                        if extract_audio_from_video(vid_path, temp_v_audio):
                            if extract_segment_audio(temp_v_audio, st, et, temp_s_audio):
                                init_audio = temp_s_audio
                except Exception as e:
                    logger.error(f"Error extracting row segment from video: {e}")
        
        if not init_audio and vid_path and os.path.exists(vid_path):
            init_audio = vid_path

        self._add_custom_voice_dialog(initial_audio=init_audio, initial_text=init_text, initial_name=init_name)

    def _clone_single_voice(self, row: int):
        """Clone voice from a single segment row"""
        text_item = self.table.item(row, 6)
        char_widget = self.table.cellWidget(row, 3)
        start_item = self.table.item(row, 1)
        end_item = self.table.item(row, 2)

        text = text_item.text().strip() if text_item else ""
        char = char_widget.currentText().strip() if char_widget else f"Segment {row+1}"
        init_name = f"Clone - {char}"
        init_audio = None

        main_win = self.window()
        vid_p = getattr(main_win, 'video_player', None)
        vid_path = getattr(vid_p, 'video_path', None) if vid_p else None

        if vid_path and os.path.exists(vid_path) and start_item and end_item:
            try:
                def _to_sec(ts):
                    parts = ts.split(':')
                    if len(parts) == 2:
                        return float(parts[0])*60 + float(parts[1])
                    elif len(parts) == 3:
                        return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                    return float(ts)
                st = _to_sec(start_item.text())
                et = _to_sec(end_item.text())
                if et > st:
                    from services.voxcpm_service import extract_audio_from_video, extract_segment_audio
                    temp_v_audio = get_temp_path(f"video_full_{row}.wav")
                    temp_s_audio = get_temp_path(f"video_seg_{row}.wav")
                    if extract_audio_from_video(vid_path, temp_v_audio):
                        if extract_segment_audio(temp_v_audio, st, et, temp_s_audio):
                            init_audio = temp_s_audio
            except Exception as e:
                logger.error(f"Error extracting row segment from video: {e}")

        if not init_audio and vid_path and os.path.exists(vid_path):
            init_audio = vid_path

        self._add_custom_voice_dialog(initial_audio=init_audio, initial_text=text, initial_name=init_name)

    # ==================== VOICE ACTIONS & SPEAKER DETECTION ====================
    def _detect_speakers(self):
        """Advanced Multi-Modal Speaker Detection (Male, Female, Child, Elder)"""
        from services.speaker_detector import SpeakerDetector
        from utils.file_utils import get_temp_path
        
        audio_path = get_temp_path("original_audio.wav")
        detector = SpeakerDetector(audio_wav_path=audio_path if os.path.exists(audio_path) else None)
        
        counts = {"Child": 0, "Elder": 0, "Male": 0, "Female": 0, "Other": 0}
        
        for i in range(self.table.rowCount()):
            persona_widget = self.table.cellWidget(i, 3)
            text_item = self.table.item(i, 6)
            voice_widget = self.table.cellWidget(i, 7)
            
            orig_seg = self.segments[i] if i < len(self.segments) else {}
            st = orig_seg.get("start", i * 3.0)
            et = orig_seg.get("end", (i + 1) * 3.0)
            orig_text = orig_seg.get("original_text", "")
            curr_text = text_item.text() if text_item else ""
            
            res = detector.detect_speaker_for_segment(
                khmer_text=curr_text,
                original_text=orig_text,
                start_sec=st,
                end_sec=et
            )
            
            spk_name = res["speaker_name"]
            clean_text = res["clean_khmer_text"]
            target_voice = res["voice"]
            spk_type = res["speaker_type"]
            
            if "Child" in spk_type:
                counts["Child"] += 1
                matched_persona = "👦 Boy / Child" if ("boy" in spk_name.lower() or "male" in spk_name.lower()) else "👧 Girl / Child"
            elif "Elder" in spk_type:
                counts["Elder"] += 1
                matched_persona = "👵 Elderly Female" if ("female" in spk_name.lower() or "ស្រី" in spk_name) else "👴 Elderly Male"
            elif "Female" in spk_type:
                counts["Female"] += 1
                matched_persona = "👩 Female Adult"
            else:
                counts["Male"] += 1
                matched_persona = "👨 Male Adult"
            
            if persona_widget and hasattr(persona_widget, 'setCurrentText'):
                if matched_persona in PERSONA_CHOICES:
                    persona_widget.setCurrentText(matched_persona)
            if text_item:
                text_item.setText(clean_text)
                
            if voice_widget:
                all_items = [voice_widget.itemText(idx) for idx in range(voice_widget.count())]
                if target_voice not in all_items:
                    voice_widget.addItem(target_voice)
                voice_widget.setCurrentText(target_voice)
                
            if i < len(self.segments):
                self.segments[i]["persona"] = matched_persona
                self.segments[i]["character"] = matched_persona
                self.segments[i]["khmer_text"] = clean_text
                self.segments[i]["voice"] = target_voice
                self.segments[i]["voice_id"] = target_voice

        summary_msg = (
            f"🎉 ស្វែងរក និងកំណត់សំឡេងតួអង្គជោគជ័យ!\n\n"
            f"👶 ក្មេង (Child): {counts['Child']} ជួរ\n"
            f"👵👴 មនុស្សចាស់ (Elder): {counts['Elder']} ជួរ\n"
            f"👨 មនុស្សប្រុស (Male): {counts['Male']} ជួរ\n"
            f"👩 មនុស្សស្រី (Female): {counts['Female']} ជួរ\n\n"
            f"សំឡេងខ្មែរត្រូវបានកំណត់ទៅតាមតួអង្គនីមួយៗរួចរាល់!"
        )
        QMessageBox.information(self, "Detect Speakers 🔍", summary_msg)

    def _open_paste_srt_dialog(self):
        """Open the dedicated PasteSRTDialog to let user paste and apply subtitles."""
        from qt_compat import QApplication
        text = (QApplication.clipboard().text() or "").strip()
        dialog = PasteSRTDialog(self, initial_text=text)

        def on_applied(srt_text):
            p = self.parent()
            while p and not hasattr(p, '_paste_subtitles_from_clipboard'):
                p = p.parent()
            if p and hasattr(p, '_paste_subtitles_from_clipboard'):
                p._paste_subtitles_from_clipboard(srt_text)

        dialog.subtitles_applied.connect(on_applied)
        dialog.exec_()

    def _assign_voices_to_characters(self):
        """Assign voices to characters based on character names and age/gender detection"""
        self._detect_speakers()

    def _auto_sync_voices(self):
        """Auto sync voices with character detection"""
        self._detect_speakers()

    def _apply_voice_to_selected(self):
        """Apply selected voice preset to currently selected rows or all rows"""
        preset = self.voice_preset_combo.currentText()
        if not preset:
            return

        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        if not selected_rows:
            for i in range(self.table.rowCount()):
                selected_rows.add(i)
        
        for row in selected_rows:
            voice_widget = self.table.cellWidget(row, 7)
            if voice_widget:
                all_items = [voice_widget.itemText(idx) for idx in range(voice_widget.count())]
                if preset not in all_items:
                    voice_widget.addItem(preset)
                voice_widget.setCurrentText(preset)
            
            if row < len(self.segments):
                self.segments[row]["voice"] = preset
                self.segments[row]["voice_id"] = preset
                
        QMessageBox.information(
            self,
            "Apply Voice Preset 🎯",
            f"Voice '{preset}' applied to {len(selected_rows)} segment(s) successfully!"
        )

    def _play_segment(self, row: int):
        """Play segment audio"""
        text_item = self.table.item(row, 6)
        if text_item and text_item.text().strip():
            self._preview_tts(row)

    def _preview_tts(self, row: int):
        """1️⃣ Line Preview: Preview TTS synthesis for a single row immediately."""
        if row < 0 or row >= self.table.rowCount():
            return
        
        text_item = self.table.item(row, 6)
        if not text_item or not text_item.text().strip():
            return
        
        text = text_item.text().strip()
        
        start_item = self.table.item(row, 1)
        end_item = self.table.item(row, 2)
        try:
            st = float(start_item.text().replace('s', '')) if start_item else float(row * 3.0)
            et = float(end_item.text().replace('s', '')) if end_item else float(st + 3.0)
        except Exception:
            st, et = float(row * 3.0), float((row + 1) * 3.0)

        persona_w = self.table.cellWidget(row, 3)
        emotion_w = self.table.cellWidget(row, 4)
        style_w = self.table.cellWidget(row, 5)
        voice_w = self.table.cellWidget(row, 7)
        
        persona = persona_w.currentText() if persona_w else "👨 Male Adult"
        emotion = emotion_w.currentText() if emotion_w else "😐 Neutral"
        speaking_style = style_w.currentText() if style_w else "Normal"
        voice_name = voice_w.currentText() if voice_w else PERSONA_DEFAULT_VOICE.get(persona, "Khmer Female - Sreymom")

        seg = {
            "khmer_text": text,
            "text": text,
            "voice": voice_name,
            "voice_id": voice_name,
            "persona": persona,
            "emotion": emotion,
            "speaking_style": speaking_style,
            "start": st,
            "end": et
        }

        from core.tts import TextToSpeech
        tts = TextToSpeech()
        out_wav = tts.synthesize_single_line(seg, row)
        if out_wav and os.path.exists(out_wav):
            try:
                # Stop any previous line preview to avoid overlapping audio
                if hasattr(self, '_preview_proc') and self._preview_proc and self._preview_proc.poll() is None:
                    try:
                        self._preview_proc.terminate()
                    except Exception:
                        pass

                if sys.platform == "darwin":
                    self._preview_proc = subprocess.Popen(["afplay", "-v", "1", out_wav])
                else:
                    self._preview_proc = subprocess.Popen(["xdg-open" if sys.platform != "win32" else "start", out_wav], shell=True)
            except Exception as e:
                logger.error(f"Playback error: {e}")

    def _preview_scene(self):
        """2️⃣ Scene Preview: Preview dialogue for selected lines or current scene range (15-30 seconds)."""
        selected_rows = sorted(list(set(item.row() for item in self.table.selectedItems())))
        if not selected_rows:
            curr = self.table.currentRow()
            if curr < 0:
                curr = 0
            start_time = None
            selected_rows = []
            for r in range(curr, min(self.table.rowCount(), curr + 10)):
                s_item = self.table.item(r, 1)
                e_item = self.table.item(r, 2)
                if not s_item or not e_item:
                    continue
                try:
                    s_t = float(s_item.text().replace('s', ''))
                    e_t = float(e_item.text().replace('s', ''))
                    if start_time is None:
                        start_time = s_t
                    if e_t - start_time > 30.0 and len(selected_rows) > 0:
                        break
                    selected_rows.append(r)
                except ValueError:
                    pass
        
        if not selected_rows:
            QMessageBox.information(self, "Scene Preview", "សូមជ្រើសរើសជួរ (Rows) សម្រាប់ Preview Scene!")
            return

        from core.tts import TextToSpeech
        from utils.file_utils import get_temp_path
        tts = TextToSpeech()
        
        scene_segs = []
        for r in selected_rows:
            text_item = self.table.item(r, 6)
            if not text_item or not text_item.text().strip():
                continue
            text = text_item.text().strip()
            s_item = self.table.item(r, 1)
            e_item = self.table.item(r, 2)
            try:
                st = float(s_item.text().replace('s', '')) if s_item else float(r * 3.0)
                et = float(e_item.text().replace('s', '')) if e_item else float(st + 3.0)
            except Exception:
                st, et = float(r * 3.0), float((r + 1) * 3.0)

            p_w = self.table.cellWidget(r, 3)
            em_w = self.table.cellWidget(r, 4)
            st_w = self.table.cellWidget(r, 5)
            v_w = self.table.cellWidget(r, 7)

            persona = p_w.currentText() if p_w else "👨 Male Adult"
            seg = {
                "khmer_text": text,
                "text": text,
                "voice": v_w.currentText() if v_w else PERSONA_DEFAULT_VOICE.get(persona, "Khmer Female - Sreymom"),
                "persona": persona,
                "emotion": em_w.currentText() if em_w else "😐 Neutral",
                "speaking_style": st_w.currentText() if st_w else "Normal",
                "start": st,
                "end": et
            }
            scene_segs.append((r, seg))

        if not scene_segs:
            return

        base_start = scene_segs[0][1]["start"]
        total_duration = max(0.5, scene_segs[-1][1]["end"] - base_start)
        scene_wav = get_temp_path(f"scene_preview_{selected_rows[0]}_{selected_rows[-1]}.wav")

        # Create blank master canvas for scene
        cmd_blank = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration + 1.0}",
            "-ar", "44100", "-ac", "2",
            scene_wav
        ]
        subprocess.run(cmd_blank, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        filter_inputs = ["-i", scene_wav]
        amix_filters = ["[0:a]"]
        input_count = 1

        for idx, (r, seg) in enumerate(scene_segs):
            wav = tts.generate_segment_audio(seg, r)
            if wav and os.path.exists(wav):
                offset_ms = int(max(0.0, seg["start"] - base_start) * 1000)
                filter_inputs.extend(["-i", wav])
                amix_filters.append(f"[{input_count}:a]adelay={offset_ms}|{offset_ms}[a{input_count}];")
                input_count += 1

        if input_count > 1:
            complex_filter = "".join(amix_filters[1:]) + "".join(f"[a{i}]" for i in range(1, input_count)) + f"[0:a]amix=inputs={input_count}:duration=first:dropout_transition=0[outa]"
            final_scene_wav = get_temp_path(f"scene_final_{selected_rows[0]}.wav")
            stitch_cmd = ["ffmpeg", "-y"] + filter_inputs + ["-filter_complex", complex_filter, "-map", "[outa]", "-ar", "44100", "-ac", "2", final_scene_wav]
            res = subprocess.run(stitch_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0 and os.path.exists(final_scene_wav):
                scene_wav = final_scene_wav

        try:
            if hasattr(self, '_preview_proc') and self._preview_proc and self._preview_proc.poll() is None:
                try:
                    self._preview_proc.terminate()
                except Exception:
                    pass

            if sys.platform == "darwin":
                self._preview_proc = subprocess.Popen(["afplay", "-v", "1", scene_wav])
            else:
                self._preview_proc = subprocess.Popen(["xdg-open" if sys.platform != "win32" else "start", scene_wav], shell=True)
        except Exception as e:
            logger.error(f"Scene playback error: {e}")

    def _show_speaker_profiles_dialog(self):
        """👥 Dialog to view and configure global Speaker Profiles across segments."""
        segs = self.get_updated_segments()
        if not segs:
            QMessageBox.information(self, "Speaker Profiles", "មិនមាន Subtitle ក្នុងតារាងទេ (No subtitles loaded).")
            return
        
        speaker_stats = {}
        for seg in segs:
            spk_id = seg.get("speaker_id") or "speaker_01"
            if spk_id not in speaker_stats:
                speaker_stats[spk_id] = {
                    "count": 0,
                    "persona": seg.get("persona", "👨 Male Adult"),
                    "emotion": seg.get("emotion", "😐 Neutral"),
                    "voice": seg.get("voice_id", "Khmer Male - Piseth")
                }
            speaker_stats[spk_id]["count"] += 1

        dlg = QDialog(self)
        dlg.setWindowTitle("👥 Global Speaker Profiles")
        dlg.resize(680, 420)
        dlg.setStyleSheet("""
            QDialog { background-color: #0b0f19; color: #f1f5f9; }
            QLabel { color: #cbd5e1; font-size: 11px; }
            QComboBox { background-color: #131b2e; border: 1px solid #1e2942; border-radius: 4px; padding: 4px; color: #e2e8f0; }
            QPushButton { background-color: #6366f1; border-radius: 6px; padding: 6px 14px; font-weight: bold; color: white; }
            QPushButton:hover { background-color: #4f46e5; }
        """)

        d_layout = QVBoxLayout(dlg)
        title = QLabel("<h3>👥 Speaker Persona & Voice Assignments</h3><p style='color:#94a3b8;'>Assign default Persona, Emotion, and Voice for each detected speaker across the project:</p>", dlg)
        d_layout.addWidget(title)

        spk_table = QTableWidget(len(speaker_stats), 5, dlg)
        spk_table.setHorizontalHeaderLabels(["Speaker ID", "Lines", "Persona", "Default Emotion", "Assigned Voice"])
        spk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        spk_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        spk_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        spk_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        spk_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        row_map = {}
        for r, (spk_id, stat) in enumerate(sorted(speaker_stats.items())):
            row_map[r] = spk_id
            spk_item = QTableWidgetItem(spk_id)
            spk_item.setFlags(spk_item.flags() & ~Qt.ItemIsEditable)
            spk_table.setItem(r, 0, spk_item)

            cnt_item = QTableWidgetItem(f"{stat['count']} lines")
            cnt_item.setFlags(cnt_item.flags() & ~Qt.ItemIsEditable)
            spk_table.setItem(r, 1, cnt_item)

            p_combo = QComboBox(dlg)
            p_combo.addItems(PERSONA_CHOICES)
            if stat["persona"] in PERSONA_CHOICES:
                p_combo.setCurrentText(stat["persona"])
            spk_table.setCellWidget(r, 2, p_combo)

            e_combo = QComboBox(dlg)
            e_combo.addItems(EMOTION_CHOICES)
            if stat["emotion"] in EMOTION_CHOICES:
                e_combo.setCurrentText(stat["emotion"])
            spk_table.setCellWidget(r, 3, e_combo)

            v_combo = QComboBox(dlg)
            v_combo.addItems(list(VOICE_PRESETS.keys()))
            if stat["voice"] in VOICE_PRESETS:
                v_combo.setCurrentText(stat["voice"])
            spk_table.setCellWidget(r, 4, v_combo)

            def _make_change_handler(vc=v_combo):
                return lambda new_p: vc.setCurrentText(PERSONA_DEFAULT_VOICE.get(new_p, vc.currentText()))
            p_combo.currentTextChanged.connect(_make_change_handler(v_combo))

        d_layout.addWidget(spk_table)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        cancel_btn = QPushButton("បោះបង់ (Cancel)", dlg)
        cancel_btn.setStyleSheet("background-color: #1e2942;")
        cancel_btn.clicked.connect(dlg.reject)
        btn_box.addWidget(cancel_btn)

        apply_btn = QPushButton("✓ អនុវត្តលើបន្ទាត់ទាំងអស់ (Apply to All Lines)", dlg)
        def _apply_all():
            for r, spk_id in row_map.items():
                p_c = spk_table.cellWidget(r, 2)
                e_c = spk_table.cellWidget(r, 3)
                v_c = spk_table.cellWidget(r, 4)
                if not (p_c and e_c and v_c):
                    continue
                new_p = p_c.currentText()
                new_e = e_c.currentText()
                new_v = v_c.currentText()

                for row_idx in range(self.table.rowCount()):
                    seg_spk = segs[row_idx].get("speaker_id") if row_idx < len(segs) else ""
                    if seg_spk == spk_id:
                        row_p = self.table.cellWidget(row_idx, 3)
                        row_e = self.table.cellWidget(row_idx, 4)
                        row_v = self.table.cellWidget(row_idx, 7)
                        if row_p: row_p.setCurrentText(new_p)
                        if row_e: row_e.setCurrentText(new_e)
                        if row_v: row_v.setCurrentText(new_v)
            dlg.accept()
            QMessageBox.information(self, "Speaker Profiles", "✅ បានអនុវត្ត Speaker Profiles ទៅលើបន្ទាត់ទាំងអស់រួចរាល់!")
        apply_btn.clicked.connect(_apply_all)
        btn_box.addWidget(apply_btn)

        d_layout.addLayout(btn_box)
        dlg.exec()

    def _show_table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= self.table.rowCount():
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #0c111e;
                border: 1px solid #1e2942;
                border-radius: 6px;
                padding: 4px;
                color: #f1f5f9;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1e2942;
                color: #38bdf8;
            }
        """)

        play_act = menu.addAction("▶ ស្តាប់សំឡេងកថាខណ្ឌនេះ (Preview Voice)")
        resynth_act = menu.addAction("🔊 បង្កើតសំឡេងឡើងវិញ (Re-synthesize Voice)")
        menu.addSeparator()
        condense_act = menu.addAction("✂️ AI Condense Shorter (បង្រួមពាក្យខ្មែរឱ្យខ្លី)")
        split_act = menu.addAction("✂️ បំបែកកថាខណ្ឌជាពីរ (Split Segment)")
        merge_act = menu.addAction("🔗 ច្របាច់ជាមួយជួរបន្ទាប់ (Merge with Next)")
        menu.addSeparator()
        del_act = menu.addAction("🗑 លុបកថាខណ្ឌនេះ (Delete Segment)")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == play_act:
            self._preview_tts(row)
        elif action == resynth_act:
            self._resynthesize_row(row)
        elif action == condense_act:
            self._condense_row_text(row)
        elif action == split_act:
            self._split_segment(row)
        elif action == merge_act:
            self._merge_segment_with_next(row)
        elif action == del_act:
            self._delete_segment(row)

    def _resynthesize_row(self, row: int):
        """Re-synthesize TTS audio for a single row and preview it."""
        updated = self.get_updated_segments()
        if 0 <= row < len(updated):
            seg = updated[row]
            from core.tts import TextToSpeech
            tts = TextToSpeech(voice_name=seg.get("voice", "Khmer Female - Sreymom"))
            out_path = tts.generate_segment_audio(seg, row)
            if out_path and os.path.exists(out_path):
                try:
                    if sys.platform == "darwin":
                        subprocess.Popen(["afplay", out_path])
                    else:
                        subprocess.Popen(["xdg-open" if sys.platform != "win32" else "start", out_path], shell=True)
                except Exception as e:
                    logger.debug(f"Playback error: {e}")

    def _condense_row_text(self, row: int):
        """Use AI to shorten/condense Khmer text to fit segment duration exactly."""
        updated = self.get_updated_segments()
        if 0 <= row < len(updated):
            seg = updated[row]
            khmer_text = seg.get("khmer_text", "")
            st = seg.get("start", 0.0)
            et = seg.get("end", 3.0)
            dur = max(0.5, et - st)
            if not khmer_text:
                return

            from services.translation_service import TranslationService
            svc = TranslationService()
            shorter = svc.condense_khmer_text(khmer_text, target_duration=dur)
            if shorter and shorter != khmer_text:
                seg["khmer_text"] = shorter
                item = self.table.item(row, 6)
                if item:
                    item.setText(shorter)
                self.segments = updated

    def _split_segment(self, row: int):
        """Split segment at midpoint into two segments."""
        updated = self.get_updated_segments()
        if not (0 <= row < len(updated)):
            return

        seg = updated[row]
        st = seg.get("start", 0.0)
        et = seg.get("end", 3.0)
        dur = et - st
        if dur < 0.6:
            QMessageBox.warning(self, "Split", "កថាខណ្ឌនេះខ្លីពេកមិនអាចបំបែកបានទេ (< 0.6s)!")
            return

        mid = round(st + dur / 2.0, 2)
        text = seg.get("khmer_text", "")
        orig_text = seg.get("original_text", "")
        
        words = text.split(" ")
        if len(words) > 1:
            mid_idx = len(words) // 2
            text1 = " ".join(words[:mid_idx])
            text2 = " ".join(words[mid_idx:])
        else:
            half = max(1, len(text) // 2)
            text1 = text[:half]
            text2 = text[half:]

        orig_words = orig_text.split(" ")
        if len(orig_words) > 1:
            m_idx = len(orig_words) // 2
            orig1 = " ".join(orig_words[:m_idx])
            orig2 = " ".join(orig_words[m_idx:])
        else:
            orig1 = orig_text
            orig2 = orig_text

        seg1 = dict(seg)
        seg1["start"] = st
        seg1["end"] = mid
        seg1["khmer_text"] = text1
        seg1["original_text"] = orig1

        seg2 = dict(seg)
        seg2["start"] = mid
        seg2["end"] = et
        seg2["khmer_text"] = text2
        seg2["original_text"] = orig2

        updated.pop(row)
        updated.insert(row, seg2)
        updated.insert(row, seg1)

        self.set_segments(updated)

    def _merge_segment_with_next(self, row: int):
        """Merge segment with the next segment."""
        updated = self.get_updated_segments()
        if not (0 <= row < len(updated) - 1):
            QMessageBox.information(self, "Merge", "មិនមានជួរបន្ទាប់សម្រាប់បញ្ចូលគ្នាទេ!")
            return

        seg1 = updated[row]
        seg2 = updated[row + 1]

        merged = dict(seg1)
        merged["end"] = seg2.get("end", seg1.get("end", 0.0))
        merged["khmer_text"] = f"{seg1.get('khmer_text', '')} {seg2.get('khmer_text', '')}".strip()
        merged["original_text"] = f"{seg1.get('original_text', '')} {seg2.get('original_text', '')}".strip()

        updated.pop(row + 1)
        updated[row] = merged

        self.set_segments(updated)

    def _delete_segment(self, row: int):
        """Delete segment from table."""
        updated = self.get_updated_segments()
        if not (0 <= row < len(updated)):
            return

        ret = QMessageBox.question(
            self, "Delete Segment",
            f"តើអ្នកពិតជាចង់លុបកថាខណ្ឌ #{row + 1} នេះមែនទេ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            updated.pop(row)
            self.set_segments(updated)


# ==================== VIDEO PREVIEW WIDGET ====================
class VideoPreviewWidget(QWidget):
    file_dropped = Signal(str)
    playhead_moved = Signal(float)
    text_moved = Signal(int, int)
    logo_moved = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_path = None
        self.cap = None
        self.fps = 30.0
        self.total_frames = 0
        self.current_frame = 0
        self._is_playing = False
        self._duration = 0
        self._timeline_segments = []
        
        # Interaction state
        self._active_target = None
        self._active_handle = None
        self._drag_start_pos = None
        self._drag_start_rect = None
        self._drag_start_text_pos = None
        
        # Blur settings
        self.blur_enabled = False
        self.blur_intensity = 30
        self.blur_rect = None
        
        # Text Overlay settings
        self.text_overlay_enabled = False
        self.text_overlay = "សង្សារមនុស្សល្អរបស់ប្រពន្ធខ្ញុំ"
        self.text_font_name = "Kantumruy Pro"
        self.raw_text_size = 24
        self.text_size = 1.2
        self.text_color_bgr = (255, 255, 255)
        self.text_color_rgb = (255, 255, 255)
        self.text_position = (50, 80)
        self.text_rect = None
        
        # Logo Overlay settings
        self.logo_enabled = False
        self.logo_path = None
        self.logo_image = None
        self.logo_x = 233
        self.logo_y = 6
        self.logo_width = 100
        self.logo_height = 100
        self.logo_rect = QtCore.QRect(233, 6, 100, 100)
        self.logo_alpha = 0.8
        self.logo_remove_green = False
        
        # Burn Subtitle settings
        self.burn_subtitle_enabled = True
        self.burn_subtitle_font_name = "Kantumruy Pro"
        self.burn_subtitle_font_size = 20
        self.burn_subtitle_color_rgb = (255, 255, 255)
        self.burn_subtitle_bg_opacity = 0.6
        
        self.play_timer = QtCore.QTimer(self)
        self.play_timer.timeout.connect(self._render_next_frame)
        
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self._pending_audio_pos_ms = None
        self._pending_play = False
        try:
            from PySide6.QtMultimedia import QMediaDevices
            def_dev = QMediaDevices.defaultAudioOutput()
            if def_dev and not def_dev.isNull():
                self.audio_output.setDevice(def_dev)
        except Exception:
            pass
        if hasattr(self.player, 'setAudioOutput'):
            self.audio_output.setVolume(1.0)
            if hasattr(self.audio_output, 'setMuted'):
                self.audio_output.setMuted(False)
            self.player.setAudioOutput(self.audio_output)
        if hasattr(self.player, 'mediaStatusChanged'):
            self.player.mediaStatusChanged.connect(self._on_media_status_changed)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Video Preview Screen Frame
        self.screen_frame = QFrame(self)
        self.screen_frame.setObjectName("videoPreviewFrame")
        self.screen_frame.setMinimumSize(280, 260)
        self.screen_frame.setMouseTracking(True)
        self.screen_frame.mousePressEvent = self._on_mouse_press
        self.screen_frame.mouseMoveEvent = self._on_mouse_move
        self.screen_frame.mouseReleaseEvent = self._on_mouse_release
        
        screen_lay = QVBoxLayout(self.screen_frame)
        screen_lay.setContentsMargins(2, 2, 2, 2)
        screen_lay.setAlignment(Qt.AlignCenter)

        self.placeholder_lbl = QLabel("🎥\nNo Video\nLoaded", self.screen_frame)
        self.placeholder_lbl.setObjectName("videoPlaceholderText")
        self.placeholder_lbl.setAlignment(Qt.AlignCenter)
        self.placeholder_lbl.setScaledContents(True)
        screen_lay.addWidget(self.placeholder_lbl)

        layout.addWidget(self.screen_frame, stretch=1)

        # Slider Position Bar
        self.seek_slider = QSlider(Qt.Horizontal, self)
        self.seek_slider.setRange(0, 100)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        layout.addWidget(self.seek_slider)

        # Playback Controls Bar
        ctrl_lay = QHBoxLayout()
        ctrl_lay.setSpacing(6)

        self.play_btn = QPushButton("▶ Play", self)
        self.play_btn.setProperty("class", "btn-green")
        self.play_btn.clicked.connect(self._toggle_play)
        
        self.stop_btn = QPushButton("⏹ Stop", self)
        self.stop_btn.setProperty("class", "btn-red")
        self.stop_btn.clicked.connect(self._stop_video)

        self.time_lbl = QLabel("00:00 / 00:00", self)
        self.time_lbl.setStyleSheet("font-family: monospace; font-size: 11px; font-weight: bold; color: #475569;")

        ctrl_lay.addWidget(self.play_btn)
        ctrl_lay.addWidget(self.stop_btn)
        ctrl_lay.addWidget(self.time_lbl)

        # Audio Track Switcher
        self.audio_track_combo = QComboBox(self)
        self.audio_track_combo.addItems(["🔊 Original Audio", "🇰🇭 Khmer Dubbed"])
        self.audio_track_combo.setStyleSheet("font-size: 11px; padding: 2px 4px; max-width: 140px;")
        self.audio_track_combo.setToolTip("Choose audio to play during video preview")
        self.audio_track_combo.currentIndexChanged.connect(self._on_audio_track_changed)
        ctrl_lay.addWidget(self.audio_track_combo)

        # Volume Slider
        ctrl_lay.addWidget(QLabel("🔊", self))
        self.vol_slider = QSlider(Qt.Horizontal, self)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(65)
        self.vol_slider.setToolTip("Preview Audio Volume")
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        ctrl_lay.addWidget(self.vol_slider)

        ctrl_lay.addStretch()
        layout.addLayout(ctrl_lay)

    def _on_volume_changed(self, val: int):
        if hasattr(self, 'audio_output') and hasattr(self.audio_output, 'setVolume'):
            self.audio_output.setVolume(val / 100.0)

    def _on_media_status_changed(self, status):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if status in [QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia]:
                if hasattr(self, '_pending_audio_pos_ms') and self._pending_audio_pos_ms is not None:
                    self.player.setPosition(self._pending_audio_pos_ms)
                    self._pending_audio_pos_ms = None
                if getattr(self, '_pending_play', False) or (self._is_playing and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState):
                    self._pending_play = False
                    if hasattr(self, 'audio_output'):
                        if hasattr(self.audio_output, 'setMuted'):
                            self.audio_output.setMuted(False)
                        vol = self.vol_slider.value() / 100.0 if hasattr(self, 'vol_slider') else 1.0
                        self.audio_output.setVolume(vol)
                    self.player.play()
                    logger.info("🔊 [VideoPreview] Audio playback resumed from LoadedMedia status.")
        except Exception as e:
            logger.debug(f"Media status changed handler: {e}")

    def _on_audio_track_changed(self, index=0):
        was_playing = self._is_playing
        pos_ms = int((self.current_frame / max(1.0, self.fps)) * 1000)
        self._pending_audio_pos_ms = pos_ms
        self._load_audio_for_player()
        try:
            self.player.setPosition(pos_ms)
            if was_playing:
                if hasattr(self, 'audio_output') and hasattr(self.audio_output, 'setMuted'):
                    self.audio_output.setMuted(False)
                self.player.play()
        except Exception:
            pass

    def _extract_preview_audio_for_video(self, video_path: str) -> str:
        """Extract dedicated, verified preview audio track for the loaded video."""
        import hashlib
        vid_id = hashlib.md5(video_path.encode()).hexdigest()[:10]
        from utils.file_utils import get_temp_path
        out_wav = get_temp_path(f"preview_track_{vid_id}.wav")
        if not os.path.exists(out_wav) or os.path.getsize(out_wav) < 1000:
            logger.info(f"🎙 [VideoPreview] Extracting fresh audio for preview from {os.path.basename(video_path)}...")
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ar", "44100", "-ac", "2",
                out_wav
            ]
            subprocess.run(cmd, capture_output=True, check=False)
        return out_wav

    def reload_mixed_audio(self):
        """Force re-generate and reload the mixed preview audio track."""
        if not self.video_path:
            return
        was_playing = self._is_playing
        pos_ms = int((self.current_frame / max(1.0, self.fps)) * 1000)
        self._pending_audio_pos_ms = pos_ms
        self._load_audio_for_player()
        if hasattr(self, 'player'):
            try:
                self.player.setPosition(pos_ms)
                if was_playing:
                    if hasattr(self, 'audio_output') and hasattr(self.audio_output, 'setMuted'):
                        self.audio_output.setMuted(False)
                    self.player.play()
            except Exception:
                pass

    def _load_audio_for_player(self):
        if not self.video_path:
            return

        from utils.file_utils import get_temp_path
        use_khmer = (self.audio_track_combo.currentIndex() == 1) if hasattr(self, 'audio_track_combo') else False
        
        main_win = self.window()
        last_master = getattr(main_win, 'last_master_wav', None)
        default_master = get_temp_path("master_khmer_voice.wav")
        if last_master and os.path.exists(last_master) and os.path.getsize(last_master) > 1000:
            master_khmer_wav = last_master
        else:
            master_khmer_wav = default_master

        target_audio_file = None
        if use_khmer and os.path.exists(master_khmer_wav) and os.path.getsize(master_khmer_wav) > 1000:
            bgm_spin = getattr(main_win, 'bgm_vol_spin', None)
            bgm_vol = (bgm_spin.value() / 100.0) if bgm_spin else 0.35

            orig_audio = self._extract_preview_audio_for_video(self.video_path)
            segments = []
            if hasattr(main_win, 'subtitle_table') and hasattr(main_win.subtitle_table, 'get_updated_segments'):
                segments = main_win.subtitle_table.get_updated_segments()

            if orig_audio and os.path.exists(orig_audio) and bgm_vol > 0.0:
                from services.audio_separator import create_clean_background_track
                cleaned_bg = get_temp_path("preview_bg_cleaned.wav")
                try:
                    create_clean_background_track(
                        orig_audio_path=orig_audio,
                        segments=segments,
                        output_bgm_path=cleaned_bg,
                        bgm_volume=bgm_vol,
                        duck_speech_db=-45.0
                    )
                    # Overlay master Khmer voice on top of cleaned background track
                    # Boost Khmer voice volume by 1.45x so dialogue is crisp, loud, and prominent over BGM
                    mixed_wav = get_temp_path("preview_khmer_mixed.wav")
                    cmd_mix = [
                        "ffmpeg", "-y",
                        "-i", master_khmer_wav,
                        "-i", cleaned_bg,
                        "-filter_complex", "[0:a]volume=1.45[v0];[1:a]volume=1.0[v1];[v0][v1]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.99[aout]",
                        "-map", "[aout]",
                        "-ar", "44100",
                        "-ac", "2",
                        mixed_wav
                    ]
                    res = subprocess.run(cmd_mix, capture_output=True, check=False)
                    if res.returncode == 0 and os.path.exists(mixed_wav) and os.path.getsize(mixed_wav) > 1000:
                        target_audio_file = mixed_wav
                    else:
                        target_audio_file = master_khmer_wav
                except Exception as e_mix:
                    logger.error(f"Error creating mixed preview: {e_mix}")
                    target_audio_file = master_khmer_wav
            else:
                target_audio_file = master_khmer_wav
        else:
            target_audio_file = self._extract_preview_audio_for_video(self.video_path)

        if target_audio_file and os.path.exists(target_audio_file) and os.path.getsize(target_audio_file) > 1000:
            # Ensure standard 44.1kHz stereo format for 100% macOS / CoreAudio / Qt6 compatibility
            try:
                import wave
                with wave.open(target_audio_file, 'rb') as wf:
                    fr = wf.getframerate()
                    ch = wf.getnchannels()
                if fr != 44100 or ch != 2:
                    from pydub import AudioSegment
                    norm_audio = AudioSegment.from_file(target_audio_file).set_frame_rate(44100).set_channels(2)
                    norm_audio.export(target_audio_file, format="wav")
            except Exception as e_norm:
                logger.debug(f"Audio norm check: {e_norm}")

            logger.info(f"🔊 [VideoPreview] Loaded preview audio track: {os.path.basename(target_audio_file)} ({os.path.getsize(target_audio_file)/1024:.1f} KB)")
            url = QUrl.fromLocalFile(os.path.abspath(target_audio_file))
            if hasattr(self, 'audio_output'):
                if hasattr(self.audio_output, 'setMuted'):
                    self.audio_output.setMuted(False)
                if hasattr(self.audio_output, 'setVolume'):
                    self.audio_output.setVolume(self.vol_slider.value() / 100.0 if hasattr(self, 'vol_slider') else 1.0)
            if hasattr(self, 'player') and hasattr(self.player, 'setSource'):
                self.player.setSource(url)
            elif hasattr(self, 'player') and hasattr(self.player, 'setMedia'):
                content = create_media_content(url)
                self.player.setMedia(content)

    def set_video_path(self, video_path: str) -> bool:
        """Set loaded video path, initialize OpenCV VideoCapture & render frame 0."""
        self.video_path = video_path
        if not video_path or not os.path.exists(video_path):
            logger.error(f"❌ Video path is invalid or does not exist: {video_path}")
            return False

        if self.cap:
            self.cap.release()

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            logger.error(f"❌ OpenCV cannot open video file: {video_path}")
            return False

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame = 0

        self._load_audio_for_player()

        self._display_frame_at(0)
        self._update_time_label(0)
        self.play_btn.setText("▶ Play")
        self._is_playing = False
        return True

    def set_timeline_segments(self, segments: list):
        """Set timeline segments for waveform and burn subtitle display"""
        self._timeline_segments = segments
        self._update_display()

    def _get_blur_handle_at(self, pos):
        if not self.blur_rect:
            return None
        r = self.blur_rect
        m = 10
        if QtCore.QRect(r.left() - m, r.top() - m, m * 2, m * 2).contains(pos): return "top_left"
        if QtCore.QRect(r.right() - m, r.top() - m, m * 2, m * 2).contains(pos): return "top_right"
        if QtCore.QRect(r.left() - m, r.bottom() - m, m * 2, m * 2).contains(pos): return "bottom_left"
        if QtCore.QRect(r.right() - m, r.bottom() - m, m * 2, m * 2).contains(pos): return "bottom_right"
        if abs(pos.y() - r.top()) <= m and r.left() <= pos.x() <= r.right(): return "top"
        if abs(pos.y() - r.bottom()) <= m and r.left() <= pos.x() <= r.right(): return "bottom"
        if abs(pos.x() - r.left()) <= m and r.top() <= pos.y() <= r.bottom(): return "left"
        if abs(pos.x() - r.right()) <= m and r.top() <= pos.y() <= r.bottom(): return "right"
        if r.contains(pos): return "move"
        return None

    def _get_logo_handle_at(self, pos):
        r = QtCore.QRect(self.logo_x, self.logo_y, self.logo_width, self.logo_height)
        m = 10
        if QtCore.QRect(r.left() - m, r.top() - m, m * 2, m * 2).contains(pos): return "top_left"
        if QtCore.QRect(r.right() - m, r.top() - m, m * 2, m * 2).contains(pos): return "top_right"
        if QtCore.QRect(r.left() - m, r.bottom() - m, m * 2, m * 2).contains(pos): return "bottom_left"
        if QtCore.QRect(r.right() - m, r.bottom() - m, m * 2, m * 2).contains(pos): return "bottom_right"
        if r.contains(pos): return "move"
        return None

    def _get_hit_target_at(self, pos):
        if self.blur_enabled and self.blur_rect:
            h = self._get_blur_handle_at(pos)
            if h: return ("blur", h)
        
        if self.logo_enabled:
            h = self._get_logo_handle_at(pos)
            if h: return ("logo", h)
            
        if self.text_overlay_enabled and self.text_rect:
            if self.text_rect.contains(pos):
                return ("text", "move")
                
        return (None, None)

    def _on_mouse_press(self, event):
        pos = event.pos()
        target, handle = self._get_hit_target_at(pos)
        if target:
            self._active_target = target
            self._active_handle = handle
            self._drag_start_pos = pos
            if target == "blur":
                self._drag_start_rect = QtCore.QRect(self.blur_rect)
            elif target == "logo":
                self._drag_start_rect = QtCore.QRect(self.logo_x, self.logo_y, self.logo_width, self.logo_height)
            elif target == "text":
                self._drag_start_text_pos = (self.text_position[0], self.text_position[1])

    def _on_mouse_move(self, event):
        pos = event.pos()
        
        if not self._active_target:
            target, handle = self._get_hit_target_at(pos)
            if target in ("blur", "logo"):
                if handle in ("top_left", "bottom_right"): self.setCursor(Qt.SizeFDiagCursor)
                elif handle in ("top_right", "bottom_left"): self.setCursor(Qt.SizeBDiagCursor)
                elif handle in ("left", "right"): self.setCursor(Qt.SizeHorCursor)
                elif handle in ("top", "bottom"): self.setCursor(Qt.SizeVerCursor)
                elif handle == "move": self.setCursor(Qt.SizeAllCursor)
            elif target == "text":
                self.setCursor(Qt.SizeAllCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
            return

        dx = pos.x() - self._drag_start_pos.x()
        dy = pos.y() - self._drag_start_pos.y()
        min_w, min_h = 20, 20

        if self._active_target == "blur" and self.blur_rect:
            r = QtCore.QRect(self._drag_start_rect)
            if self._active_handle == "move": r.translate(dx, dy)
            elif self._active_handle == "top_left":
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._active_handle == "top_right":
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._active_handle == "bottom_left":
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._active_handle == "bottom_right":
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._active_handle == "top": r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._active_handle == "bottom": r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._active_handle == "left": r.setLeft(min(r.right() - min_w, r.left() + dx))
            elif self._active_handle == "right": r.setRight(max(r.left() + min_w, r.right() + dx))
            self.blur_rect = r
            self._update_display()

        elif self._active_target == "logo":
            r = QtCore.QRect(self._drag_start_rect)
            if self._active_handle == "move": r.translate(dx, dy)
            elif self._active_handle == "top_left":
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._active_handle == "top_right":
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._active_handle == "bottom_left":
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._active_handle == "bottom_right":
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            
            self.logo_x = max(0, r.x())
            self.logo_y = max(0, r.y())
            self.logo_width = max(20, r.width())
            self.logo_height = max(20, r.height())
            self.logo_moved.emit(self.logo_x, self.logo_y, self.logo_width, self.logo_height)
            self._update_display()

        elif self._active_target == "text":
            new_x = max(0, self._drag_start_text_pos[0] + dx)
            new_y = max(0, self._drag_start_text_pos[1] + dy)
            self.text_position = (new_x, new_y)
            self.text_moved.emit(new_x, new_y)
            self._update_display()

    def _on_mouse_release(self, event):
        self._active_target = None
        self._active_handle = None
        self._drag_start_pos = None
        self._drag_start_rect = None
        self.setCursor(Qt.ArrowCursor)

    # ==================== BLUR FUNCTIONS ====================
    def set_blur_enabled(self, enabled: bool):
        self.blur_enabled = enabled
        if enabled and self.blur_rect is None:
            w = max(120, int(self.screen_frame.width() * 0.4))
            h = max(90, int(self.screen_frame.height() * 0.3))
            cx = max(10, (self.screen_frame.width() - w) // 2)
            cy = max(10, (self.screen_frame.height() - h) // 2)
            self.blur_rect = QtCore.QRect(cx, cy, w, h)
        self._update_display()

    def set_blur_intensity(self, intensity: int):
        self.blur_intensity = max(1, intensity)
        if self.blur_enabled:
            self._update_display()

    def reset_blur_position(self):
        w = max(120, int(self.screen_frame.width() * 0.4))
        h = max(90, int(self.screen_frame.height() * 0.3))
        cx = max(10, (self.screen_frame.width() - w) // 2)
        cy = max(10, (self.screen_frame.height() - h) // 2)
        self.blur_rect = QtCore.QRect(cx, cy, w, h)
        self._update_display()

    def _apply_blur_to_frame(self, frame):
        if not self.blur_enabled or not self.blur_rect:
            return frame
        
        h, w, ch = frame.shape
        label_w = max(1, self.screen_frame.width())
        label_h = max(1, self.screen_frame.height())
        scale_x = w / label_w
        scale_y = h / label_h
        
        x1 = max(0, int(self.blur_rect.x() * scale_x))
        y1 = max(0, int(self.blur_rect.y() * scale_y))
        x2 = min(w, int((self.blur_rect.x() + self.blur_rect.width()) * scale_x))
        y2 = min(h, int((self.blur_rect.y() + self.blur_rect.height()) * scale_y))
        
        if x1 >= x2 or y1 >= y2:
            return frame
        
        roi = frame[y1:y2, x1:x2]
        if roi.size > 0:
            ksize = max(3, int(self.blur_intensity / 100.0 * 31.0) | 1)
            ksize = min(ksize, 31)
            if ksize % 2 == 0: ksize += 1
            blurred_roi = cv2.GaussianBlur(roi, (ksize, ksize), 0)
            frame[y1:y2, x1:x2] = blurred_roi
        return frame

    def _draw_blur_rectangle(self, frame):
        if not self.blur_enabled or not self.blur_rect:
            return frame
        
        h, w, ch = frame.shape
        label_w = max(1, self.screen_frame.width())
        label_h = max(1, self.screen_frame.height())
        scale_x = w / label_w
        scale_y = h / label_h
        
        x1 = int(self.blur_rect.x() * scale_x)
        y1 = int(self.blur_rect.y() * scale_y)
        x2 = int((self.blur_rect.x() + self.blur_rect.width()) * scale_x)
        y2 = int((self.blur_rect.y() + self.blur_rect.height()) * scale_y)
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 240, 255), 2)
        hs = 6
        cv2.rectangle(frame, (x1-hs, y1-hs), (x1+hs, y1+hs), (0, 230, 118), -1)
        cv2.rectangle(frame, (x2-hs, y1-hs), (x2+hs, y1+hs), (0, 230, 118), -1)
        cv2.rectangle(frame, (x1-hs, y2-hs), (x1+hs, y2+hs), (0, 230, 118), -1)
        cv2.rectangle(frame, (x2-hs, y2-hs), (x2+hs, y2+hs), (0, 230, 118), -1)
        return frame

    # ==================== TEXT OVERLAY FUNCTIONS ====================
    def set_text_overlay_enabled(self, enabled: bool):
        self.text_overlay_enabled = enabled
        self._update_display()

    def set_text_overlay_text(self, text: str):
        self.text_overlay = text
        if self.text_overlay_enabled:
            self._update_display()

    def set_text_overlay_font(self, font_name: str):
        self.text_font_name = font_name
        if self.text_overlay_enabled:
            self._update_display()

    def set_text_overlay_color(self, color_hex: str):
        hex_color = color_hex.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            self.text_color_bgr = (b, g, r)
            self.text_color_rgb = (r, g, b)
            if self.text_overlay_enabled:
                self._update_display()

    def set_text_overlay_size(self, size: int):
        self.raw_text_size = size
        self.text_size = max(0.5, size / 20.0)
        if self.text_overlay_enabled:
            self._update_display()

    def set_text_overlay_position(self, x: int, y: int):
        self.text_position = (x, y)
        if self.text_overlay_enabled:
            self._update_display()

    def _apply_text_overlay(self, frame):
        """Apply text overlay to frame using Qt QPainter with 100% native HarfBuzz Khmer shaping"""
        if not self.text_overlay_enabled or not self.text_overlay:
            return frame
        
        try:
            ensure_qt_fonts()
            h, w, ch = frame.shape
            label_w = max(1, self.screen_frame.width())
            label_h = max(1, self.screen_frame.height())
            scale_x = w / label_w
            scale_y = h / label_h
            
            x = int(self.text_position[0] * scale_x)
            y = int(self.text_position[1] * scale_y)
            x = max(10, min(w - 30, x))
            y = max(20, min(h - 20, y))
            
            font_size_pt = max(12, int(getattr(self, 'raw_text_size', 24) * scale_y))
            font_family = resolve_qt_font_name(getattr(self, 'text_font_name', 'Kantumruy Pro'))
            
            qimg = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
            qimg.fill(Qt.transparent)
            
            painter = QtGui.QPainter(qimg)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
            
            font = QtGui.QFont(font_family, font_size_pt, QtGui.QFont.Bold)
            painter.setFont(font)
            
            fm = QtGui.QFontMetrics(font)
            text_w = fm.horizontalAdvance(self.text_overlay)
            text_h = fm.height()
            
            pad_x, pad_y = 14, 10
            bg_x = max(0, x - pad_x)
            bg_y = max(0, y - fm.ascent() - pad_y)
            bg_w = min(w - bg_x, text_w + pad_x * 2)
            bg_h = min(h - bg_y, text_h + pad_y * 2)
            
            screen_bg_x = int(bg_x / scale_x)
            screen_bg_y = int(bg_y / scale_y)
            screen_bg_w = int(bg_w / scale_x)
            screen_bg_h = int(bg_h / scale_y)
            self.text_rect = QtCore.QRect(screen_bg_x, screen_bg_y, screen_bg_w, screen_bg_h)
            
            painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 180)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRect(bg_x, bg_y, bg_w, bg_h), 10, 10)
            
            path = QtGui.QPainterPath()
            path.addText(x, y, font, self.text_overlay)
            
            stroke_w = max(2, font_size_pt // 10)
            painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 255), stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            
            rgb_color = getattr(self, 'text_color_rgb', (255, 255, 255))
            painter.setBrush(QtGui.QBrush(QtGui.QColor(rgb_color[0], rgb_color[1], rgb_color[2])))
            painter.setPen(Qt.NoPen)
            painter.drawPath(path)
            
            painter.end()
            
            qimg_rgb = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
            ptr = qimg_rgb.bits()
            if hasattr(ptr, 'setsize'): ptr.setsize(h * w * 3)
            arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 3))
            text_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            
            mask = (arr > 0).any(axis=2)
            frame[mask] = text_bgr[mask]
            
            cv2.rectangle(frame, (bg_x, bg_y), (bg_x + bg_w, bg_y + bg_h), (255, 0, 255), 1)
            return frame
        except Exception as e:
            print(f"Error applying Qt text overlay: {e}")
            return frame

    # ==================== LOGO OVERLAY FUNCTIONS ====================
    def set_logo_enabled(self, enabled: bool):
        self.logo_enabled = enabled
        if enabled and self.logo_path:
            self._load_logo()
        self._update_display()

    def set_logo_path(self, path: str):
        self.logo_path = path
        if self.logo_enabled:
            self._load_logo()
            self._update_display()

    def set_logo_position(self, x: int, y: int):
        self.logo_x = x
        self.logo_y = y
        self._update_display()

    def set_logo_size(self, width: int, height: int):
        self.logo_width = max(10, width)
        self.logo_height = max(10, height)
        if self.logo_enabled:
            self._load_logo()
            self._update_display()

    def set_logo_remove_green(self, remove: bool):
        self.logo_remove_green = remove
        if self.logo_enabled:
            self._load_logo()
            self._update_display()

    def _load_logo(self):
        if not self.logo_path or not os.path.exists(self.logo_path):
            self.logo_image = None
            return
        try:
            img = cv2.imread(self.logo_path, cv2.IMREAD_UNCHANGED)
            if img is None:
                self.logo_image = None
                return
            img = cv2.resize(img, (self.logo_width, self.logo_height))
            if self.logo_remove_green:
                hsv = cv2.cvtColor(img if img.shape[2] == 3 else img[:, :, :3], cv2.COLOR_BGR2HSV)
                lower_green = np.array([35, 40, 40])
                upper_green = np.array([85, 255, 255])
                mask = cv2.inRange(hsv, lower_green, upper_green)
                if img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
                img[mask > 0, 3] = 0
            if img.shape[2] == 3: img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            self.logo_image = img
        except Exception as e:
            print(f"Error loading logo: {e}")
            self.logo_image = None

    def _apply_logo_overlay(self, frame):
        if not self.logo_enabled or self.logo_image is None:
            return frame
        
        h, w, ch = frame.shape
        logo_h, logo_w, logo_ch = self.logo_image.shape
        
        label_w = max(1, self.screen_frame.width())
        label_h = max(1, self.screen_frame.height())
        scale_x = w / label_w
        scale_y = h / label_h
        
        x = int(self.logo_x * scale_x)
        y = int(self.logo_y * scale_y)
        
        if x + logo_w > w: logo_w = w - x
        if y + logo_h > h: logo_h = h - y
        if logo_w <= 0 or logo_h <= 0: return frame
        
        if logo_w != self.logo_image.shape[1] or logo_h != self.logo_image.shape[0]:
            logo_resized = cv2.resize(self.logo_image, (logo_w, logo_h))
        else:
            logo_resized = self.logo_image
        
        if logo_resized.shape[2] == 4:
            alpha = logo_resized[:, :, 3] / 255.0
            logo_rgb = logo_resized[:, :, :3]
        else:
            alpha = np.ones((logo_h, logo_w))
            logo_rgb = logo_resized
        
        roi = frame[y:y+logo_h, x:x+logo_w]
        if roi.shape[0] > 0 and roi.shape[1] > 0:
            for c in range(3):
                roi[:, :, c] = (alpha * logo_rgb[:, :, c] + (1 - alpha) * roi[:, :, c]).astype(np.uint8)
            frame[y:y+logo_h, x:x+logo_w] = roi
        
        x1 = x
        y1 = y
        x2 = x + logo_w
        y2 = y + logo_h
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 230, 118), 2)
        hs = 5
        cv2.rectangle(frame, (x1-hs, y1-hs), (x1+hs, y1+hs), (255, 255, 255), -1)
        cv2.rectangle(frame, (x2-hs, y1-hs), (x2+hs, y1+hs), (255, 255, 255), -1)
        cv2.rectangle(frame, (x1-hs, y2-hs), (x1+hs, y2+hs), (255, 255, 255), -1)
        cv2.rectangle(frame, (x2-hs, y2-hs), (x2+hs, y2+hs), (255, 255, 255), -1)
        
        return frame

    # ==================== BURN SUBTITLE FUNCTIONS ====================
    def set_burn_subtitle_enabled(self, enabled: bool):
        self.burn_subtitle_enabled = enabled
        self._update_display()

    def set_burn_subtitle_config(self, enabled: bool, font_name: str, font_size: int, color_hex: str, bg_opacity: float):
        self.burn_subtitle_enabled = enabled
        self.burn_subtitle_font_name = font_name
        self.burn_subtitle_font_size = font_size
        self.burn_subtitle_bg_opacity = bg_opacity
        hex_c = color_hex.lstrip('#')
        if len(hex_c) == 6:
            r = int(hex_c[0:2], 16)
            g = int(hex_c[2:4], 16)
            b = int(hex_c[4:6], 16)
            self.burn_subtitle_color_rgb = (r, g, b)
        self._update_display()

    def _apply_burn_subtitle(self, frame, cur_sec: float):
        """Render active Khmer subtitle using Qt QPainter for 100% Native HarfBuzz Unicode Shaping"""
        if not self.burn_subtitle_enabled or not self._timeline_segments:
            return frame
        
        ensure_qt_fonts()
        
        active_seg = None
        for seg in self._timeline_segments:
            st = seg.get("start", 0.0)
            et = seg.get("end", 0.0)
            if st <= cur_sec <= et:
                active_seg = seg
                break
        
        if not active_seg:
            return frame
        
        raw_sub = active_seg.get("khmer_text") or active_seg.get("original_text") or active_seg.get("text", "")
        # Clean any leading speaker tags like [ក្មេង], [ប្រុស], [ស្រី] from burned subtitle text
        sub_text = re.sub(r'^\s*(?:\[|\()?\s*(ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)\s*(?:\]|\))?\s*[:：\-–—]?\s*', '', raw_sub, flags=re.IGNORECASE).strip()
        if sub_text.startswith('[') and ']' in sub_text[:15]:
            sub_text = re.sub(r'^\s*\[[^\]]+\]\s*', '', sub_text).strip()
        if not sub_text:
            sub_text = raw_sub.strip()
        if not sub_text:
            return frame
        
        try:
            h, w, ch = frame.shape
            label_w = max(1, self.screen_frame.width())
            label_h = max(1, self.screen_frame.height())
            scale_y = h / label_h
            
            font_size_pt = max(14, int(getattr(self, 'burn_subtitle_font_size', 20) * scale_y))
            font_family = resolve_qt_font_name(getattr(self, 'burn_subtitle_font_name', 'Kantumruy Pro'))
            
            qimg = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
            qimg.fill(Qt.transparent)
            
            painter = QtGui.QPainter(qimg)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
            
            font = QtGui.QFont(font_family, font_size_pt, QtGui.QFont.Bold)
            painter.setFont(font)
            fm = QtGui.QFontMetrics(font)
            
            words = sub_text.split()
            lines = []
            curr_line = ""
            max_line_w = w - 80
            
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
            bg_x1 = max(10, (w - max_w) // 2 - 22)
            bg_x2 = min(w - 10, (w + max_w) // 2 + 22)
            bg_y1 = h - margin_bottom - total_h - 16
            bg_y2 = h - margin_bottom + 16
            
            bg_alpha = int(getattr(self, 'burn_subtitle_bg_opacity', 0.6) * 255)
            painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, bg_alpha)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QtCore.QRect(bg_x1, bg_y1, bg_x2 - bg_x1, bg_y2 - bg_y1), 12, 12)
            
            rgb_color = getattr(self, 'burn_subtitle_color_rgb', (255, 255, 255))
            curr_y = bg_y1 + fm.ascent() + 8
            
            stroke_w = max(2, font_size_pt // 10)
            for i, l in enumerate(lines):
                lx = (w - line_widths[i]) // 2
                path = QtGui.QPainterPath()
                path.addText(lx, curr_y, font, l)
                
                painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 255), stroke_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)
                
                painter.setBrush(QtGui.QBrush(QtGui.QColor(rgb_color[0], rgb_color[1], rgb_color[2])))
                painter.setPen(Qt.NoPen)
                painter.drawPath(path)
                
                curr_y += line_height
            
            painter.end()
            
            qimg_rgb = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
            ptr = qimg_rgb.bits()
            if hasattr(ptr, 'setsize'): ptr.setsize(h * w * 3)
            arr = np.frombuffer(ptr, np.uint8).reshape((h, w, 3))
            text_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            
            mask = (arr > 0).any(axis=2)
            frame[mask] = text_bgr[mask]
            return frame
        except Exception as e:
            print(f"Error applying burn subtitle: {e}")
            return frame

    def get_effects_config(self) -> dict:
        preview_w = max(1, self.screen_frame.width())
        preview_h = max(1, self.screen_frame.height())
        
        has_text = bool(self.text_overlay and self.text_overlay.strip())
        has_logo = bool(self.logo_path and os.path.exists(str(self.logo_path)))
        has_segments = bool(self._timeline_segments)
        
        return {
            "preview_size": (preview_w, preview_h),
            "blur": {
                "enabled": self.blur_enabled and bool(self.blur_rect),
                "intensity": self.blur_intensity,
                "rect": self.blur_rect
            },
            "text_overlay": {
                "enabled": self.text_overlay_enabled or has_text,
                "text": self.text_overlay,
                "font_name": getattr(self, 'text_font_name', 'Kantumruy Pro'),
                "color_rgb": getattr(self, 'text_color_rgb', (255, 255, 255)),
                "size_pt": getattr(self, 'raw_text_size', 24),
                "position": self.text_position
            },
            "logo": {
                "enabled": self.logo_enabled and has_logo,
                "path": self.logo_path,
                "x": self.logo_x,
                "y": self.logo_y,
                "width": self.logo_width,
                "height": self.logo_height,
                "remove_green": self.logo_remove_green
            },
            "burn_subtitle": {
                "enabled": self.burn_subtitle_enabled and has_segments,
                "font_name": self.burn_subtitle_font_name,
                "font_size": self.burn_subtitle_font_size,
                "color_rgb": self.burn_subtitle_color_rgb,
                "bg_opacity": self.burn_subtitle_bg_opacity
            },
            "segments": self._timeline_segments
        }

    def _apply_all_effects(self, frame):
        cur_sec = self.current_frame / max(1.0, self.fps)
        
        if self.blur_enabled:
            frame = self._apply_blur_to_frame(frame)
            frame = self._draw_blur_rectangle(frame)
        
        if self.text_overlay_enabled:
            frame = self._apply_text_overlay(frame)
        
        if self.logo_enabled:
            frame = self._apply_logo_overlay(frame)
            
        if self.burn_subtitle_enabled:
            frame = self._apply_burn_subtitle(frame, cur_sec)
        
        return frame

    def _update_display(self):
        if self.cap and self.cap.isOpened():
            self._display_frame_at(self.current_frame)

    def _toggle_play(self):
        if not self.video_path or not self.cap or not self.cap.isOpened():
            return

        if self._is_playing:
            self.play_timer.stop()
            self.player.pause()
            self._is_playing = False
            self._pending_play = False
            self.play_btn.setText("▶ Play")
            logger.info("⏸ [VideoPreview] Playback paused.")
        else:
            if hasattr(self.player, 'source') and self.player.source().isEmpty():
                self._load_audio_for_player()

            pos_ms = int((self.current_frame / max(1.0, self.fps)) * 1000)
            try:
                self.player.setPosition(pos_ms)
            except Exception:
                pass
            interval = int(1000.0 / max(10.0, self.fps))
            self.play_timer.start(interval)
            try:
                if hasattr(self, 'audio_output'):
                    if hasattr(self.audio_output, 'setMuted'):
                        self.audio_output.setMuted(False)
                    if hasattr(self.audio_output, 'setVolume'):
                        vol = self.vol_slider.value() / 100.0 if hasattr(self, 'vol_slider') else 1.0
                        self.audio_output.setVolume(vol)
                self.player.play()
                if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                    self._pending_play = True
                logger.info(f"▶ [VideoPreview] Playback started at {pos_ms/1000.0:.1f}s (Volume: {self.audio_output.volume():.0%})")
            except Exception as e:
                logger.warning(f"Player play exception: {e}")
            self._is_playing = True
            self.play_btn.setText("⏸ Pause")

    def _stop_video(self):
        self.play_timer.stop()
        self.player.stop()
        try:
            self.player.setPosition(0)
        except Exception:
            pass
        self._is_playing = False
        self.play_btn.setText("▶ Play")
        self.current_frame = 0
        self._display_frame_at(0)
        self.seek_slider.setValue(0)
        self._update_time_label(0)
        self.playhead_moved.emit(0.0)

    def _render_next_frame(self):
        if not self.cap or not self.cap.isOpened():
            self._stop_video()
            return

        # Audio Master Clock Synchronization: lock video frame to audio position to prevent lip drift
        try:
            if hasattr(self, 'player') and self.player and self._is_playing:
                audio_pos_ms = self.player.position()
                if audio_pos_ms > 0:
                    expected_frame = int((audio_pos_ms / 1000.0) * max(1.0, self.fps))
                    # If video lags or leads audio by more than 2 frames, resync
                    if abs(expected_frame - self.current_frame) > 2 and expected_frame < self.total_frames:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, expected_frame)
        except Exception:
            pass

        ret, frame = self.cap.read()
        if not ret:
            self._stop_video()
            return

        self.current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        
        frame = self._apply_all_effects(frame)
        self._show_frame_mat(frame)
        
        cur_sec = self.current_frame / max(1.0, self.fps)
        self.playhead_moved.emit(cur_sec)

        if self.total_frames > 0:
            val = int((self.current_frame / float(self.total_frames)) * 100)
            self.seek_slider.setValue(val)
            self._update_time_label(self.current_frame)

    def _display_frame_at(self, frame_idx: int):
        if not self.cap or not self.cap.isOpened():
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            frame = self._apply_all_effects(frame)
            self._show_frame_mat(frame)

    def _show_frame_mat(self, frame):
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        qimg = QtGui.QImage(rgb_frame.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qimg)
        self.placeholder_lbl.setPixmap(pixmap)

    def _update_time_label(self, frame_idx: int):
        cur_sec = int(frame_idx / max(1.0, self.fps))
        dur_sec = int(self.total_frames / max(1.0, self.fps))
        c_m, c_s = cur_sec // 60, cur_sec % 60
        d_m, d_s = dur_sec // 60, dur_sec % 60
        self.time_lbl.setText(f"{c_m:02d}:{c_s:02d} / {d_m:02d}:{d_s:02d}")

    def _on_seek_moved(self, value: int):
        if self.total_frames > 0 and self.cap:
            target_frame = int((value / 100.0) * self.total_frames)
            self.current_frame = target_frame
            self._display_frame_at(target_frame)
            self._update_time_label(target_frame)
            cur_sec = target_frame / max(1.0, self.fps)
            self.playhead_moved.emit(cur_sec)
            pos_ms = int(cur_sec * 1000)
            try:
                self.player.setPosition(pos_ms)
            except Exception:
                pass

    def seek_to_time_sec(self, sec: float):
        """Programmatic video frame seek to exact timestamp in seconds."""
        if self.total_frames > 0 and self.cap and self.fps > 0:
            target_frame = int(sec * self.fps)
            target_frame = max(0, min(self.total_frames - 1, target_frame))
            self.current_frame = target_frame
            self._display_frame_at(target_frame)
            self._update_time_label(target_frame)
            val = int((target_frame / float(self.total_frames)) * 100)
            self.seek_slider.blockSignals(True)
            self.seek_slider.setValue(val)
            self.seek_slider.blockSignals(False)
            pos_ms = int(sec * 1000)
            try:
                self.player.setPosition(pos_ms)
            except Exception:
                pass


# ==================== TOOLS PANEL ====================
class ToolsPanelWidget(QGroupBox):
    blur_enabled = Signal(bool)
    blur_intensity_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__("⚙ Tools", parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        row1 = QHBoxLayout()
        self.auto_sync_btn = QPushButton("⚡ Auto-Sync", self)
        self.auto_sync_btn.setProperty("class", "btn-orange")
        self.auto_speed_btn = QPushButton("Auto-Speed", self)
        self.auto_speed_btn.setProperty("class", "btn-orange")
        row1.addWidget(self.auto_sync_btn)
        row1.addWidget(self.auto_speed_btn)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.video_sync_btn = QPushButton("🎬 Video Sync", self)
        self.video_sync_btn.setProperty("class", "btn-purple")
        self.cutter_btn = QPushButton(">< Cutter", self)
        self.cutter_btn.setProperty("class", "btn-purple")
        row2.addWidget(self.video_sync_btn)
        row2.addWidget(self.cutter_btn)
        layout.addLayout(row2)

        lic_lbl = QLabel("🔑 License: 379 ថ្ងៃ", self)
        lic_lbl.setStyleSheet("color: #0284c7; font-weight: bold; font-size: 12px; margin-top: 4px;")
        layout.addWidget(lic_lbl)

        self.chk_auto_speed = QCheckBox("Auto Sync Video Speed", self)
        self.chk_auto_speed.setChecked(True)
        self.chk_lock_speed = QCheckBox("Lock Speed (+25%)", self)
        self.chk_lock_speed.setChecked(True)
        self.chk_sync_tts = QCheckBox("Sync TTS to Original Video", self)
        self.chk_sync_tts.setChecked(True)
        self.chk_auto_vocal = QCheckBox("Auto remove Vocal", self)
        self.chk_auto_vocal.setChecked(True)

        layout.addWidget(self.chk_auto_speed)
        layout.addWidget(self.chk_lock_speed)
        layout.addWidget(self.chk_sync_tts)
        layout.addWidget(self.chk_auto_vocal)


# ==================== TIMELINE EDITOR ====================
class TimelineEditorWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("⏱ Timeline Editor - Subtitle Waveform Tracks", parent)
        self.segments = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        ctrl_lay = QHBoxLayout()
        ctrl_lay.setSpacing(8)

        ctrl_lay.addWidget(QLabel("Zoom:", self))
        self.zoom_slider = QSlider(Qt.Horizontal, self)
        self.zoom_slider.setRange(10, 250)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(100)
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        ctrl_lay.addWidget(self.zoom_slider)

        self.align_btn = QPushButton("Align to Playhead", self)
        self.align_btn.setProperty("class", "btn-teal")
        self.align_btn.clicked.connect(self._align_to_playhead)
        ctrl_lay.addWidget(self.align_btn)

        ctrl_lay.addStretch()
        layout.addLayout(ctrl_lay)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setMinimumHeight(105)
        self.scroll_area.setMaximumHeight(130)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #0a0e1a;
                border: 1px solid #1a2238;
                border-radius: 8px;
            }
        """)

        self.waveform_canvas = AudioWaveformCanvas(self.scroll_area)
        self.scroll_area.setWidget(self.waveform_canvas)

        layout.addWidget(self.scroll_area)

    def _apply_voice_to_all(self):
        selected_voice = self.voice_combo.currentText()
        if self.segments:
            for s in self.segments:
                s["voice_key"] = selected_voice
            self.set_segments(self.segments)
            logger.info(f"Applied voice '{selected_voice}' to all timeline segments.")

    def _align_to_playhead(self):
        if hasattr(self.waveform_canvas, 'playhead_pos_sec'):
            logger.info(f"Aligned timeline view to playhead: {self.waveform_canvas.playhead_pos_sec:.2f}s")

    def set_segments(self, segments: list):
        self.segments = segments
        zoom = self.zoom_slider.value() / 100.0
        self.waveform_canvas.set_data(segments=segments, zoom=zoom)

    def set_playhead_position(self, playhead_sec: float):
        self.waveform_canvas.set_data(segments=None, playhead_sec=playhead_sec)

    def _on_zoom_changed(self, value: int):
        zoom = value / 100.0
        self.waveform_canvas.set_data(segments=None, zoom=zoom)


# ==================== VIDEO EFFECTS WIDGET ====================
class VideoEffectsWidget(QWidget):
    """Video effects control panel with Blur, Text Overlays, Logo, and Burn Subtitle"""
    
    blur_toggled = Signal(bool)
    blur_intensity_changed = Signal(int)
    reset_blur_requested = Signal()
    text_toggled = Signal(bool)
    text_updated = Signal(str, str, int, str)
    text_position_changed = Signal(int, int)
    logo_toggled = Signal(bool)
    logo_updated = Signal(str, int, int, int, int, bool)
    burn_subtitle_toggled = Signal(bool)
    burn_subtitle_updated = Signal(bool, str, int, str, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_color = "#FFFFFF"
        self._current_text = "សង្សារមនុស្សល្អរបស់ប្រពន្ធខ្ញុំ"
        self._current_font = "Kantumruy Pro"
        self._current_size = 24
        self._burn_color = "#FFFFFF"
        self._init_ui()

    def _init_ui(self):
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(2)

        self.effect_tabs = QTabWidget(self)

        # ---------------- 1. TAB: BLUR MASK ----------------
        blur_tab = QWidget()
        b_lay = QHBoxLayout(blur_tab)
        b_lay.setContentsMargins(12, 10, 12, 10)
        b_lay.setSpacing(14)

        self.blur_checkbox = QCheckBox("Enable Blur Mask", self)
        self.blur_checkbox.setChecked(False)
        self.blur_checkbox.toggled.connect(self._on_blur_toggled)
        b_lay.addWidget(self.blur_checkbox)

        b_lay.addWidget(QLabel("Intensity:", self))
        self.blur_slider = QSlider(Qt.Horizontal, self)
        self.blur_slider.setRange(1, 100)
        self.blur_slider.setValue(30)
        self.blur_slider.setFixedWidth(120)
        self.blur_slider.valueChanged.connect(self._on_blur_intensity_changed)
        b_lay.addWidget(self.blur_slider)

        self.blur_value_lbl = QLabel("30%", self)
        self.blur_value_lbl.setStyleSheet("color: #38bdf8; font-weight: bold; min-width: 35px;")
        b_lay.addWidget(self.blur_value_lbl)

        reset_btn = QPushButton("↺ Reset Box", self)
        reset_btn.setProperty("class", "btn-gray")
        reset_btn.clicked.connect(self._reset_blur_position)
        b_lay.addWidget(reset_btn)

        info_lbl = QLabel("💡 Drag yellow mask on video screen to position", self)
        info_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        b_lay.addWidget(info_lbl)
        b_lay.addStretch()

        self.effect_tabs.addTab(blur_tab, "🔍 Blur Mask")

        # ---------------- 2. TAB: TEXT OVERLAYS ----------------
        txt_tab = QWidget()
        t_lay = QHBoxLayout(txt_tab)
        t_lay.setContentsMargins(12, 10, 12, 10)
        t_lay.setSpacing(10)

        self.text_checkbox = QCheckBox("Enable", self)
        self.text_checkbox.setChecked(False)
        self.text_checkbox.toggled.connect(self._on_text_toggled)
        t_lay.addWidget(self.text_checkbox)

        t_lay.addWidget(QLabel("Text:", self))
        self.text_input = QLineEdit("សង្សារមនុស្សល្អរបស់ប្រពន្ធខ្ញុំ", self)
        self.text_input.setMinimumWidth(160)
        self.text_input.textChanged.connect(self._on_text_changed)
        t_lay.addWidget(self.text_input)

        t_lay.addWidget(QLabel("Font:", self))
        self.text_font_combo = QComboBox(self)
        self.text_font_combo.addItems(["Kantumruy Pro", "Noto Sans Khmer", "Battambang", "Khmer Sangam MN"])
        self.text_font_combo.currentTextChanged.connect(self._on_font_changed)
        t_lay.addWidget(self.text_font_combo)

        t_lay.addWidget(QLabel("Size:", self))
        self.size_spin = QSpinBox(self)
        self.size_spin.setRange(8, 72)
        self.size_spin.setValue(24)
        self.size_spin.valueChanged.connect(self._on_size_changed)
        t_lay.addWidget(self.size_spin)

        t_lay.addWidget(QLabel("Color:", self))
        self.color_btn = QPushButton("🎨", self)
        self.color_btn.setFixedSize(30, 26)
        self.color_btn.setStyleSheet("background-color: #FFFFFF; border: 1px solid #64748b; border-radius: 4px;")
        self.color_btn.clicked.connect(self._pick_color)
        t_lay.addWidget(self.color_btn)

        t_lay.addWidget(QLabel("X:", self))
        self.pos_x = QSpinBox(self)
        self.pos_x.setRange(0, 999)
        self.pos_x.setValue(50)
        self.pos_x.valueChanged.connect(self._on_position_changed)
        t_lay.addWidget(self.pos_x)

        t_lay.addWidget(QLabel("Y:", self))
        self.pos_y = QSpinBox(self)
        self.pos_y.setRange(0, 999)
        self.pos_y.setValue(80)
        self.pos_y.valueChanged.connect(self._on_position_changed)
        t_lay.addWidget(self.pos_y)

        apply_btn = QPushButton("✓ Apply", self)
        apply_btn.setProperty("class", "btn-primary")
        apply_btn.clicked.connect(self._apply_text)
        t_lay.addWidget(apply_btn)

        self.text_status = QLabel("Ready", self)
        self.text_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
        t_lay.addWidget(self.text_status)

        self.effect_tabs.addTab(txt_tab, "📝 Text Overlays")

        # ---------------- 3. TAB: LOGO OVERLAY ----------------
        logo_tab = QWidget()
        l_lay = QHBoxLayout(logo_tab)
        l_lay.setContentsMargins(12, 10, 12, 10)
        l_lay.setSpacing(10)

        self.logo_checkbox = QCheckBox("Enable", self)
        self.logo_checkbox.setChecked(False)
        self.logo_checkbox.toggled.connect(self._on_logo_toggled)
        l_lay.addWidget(self.logo_checkbox)

        self.logo_path_edit = QLineEdit("logo.png", self)
        self.logo_path_edit.setMinimumWidth(120)
        self.logo_path_edit.textChanged.connect(self._on_logo_path_changed)
        l_lay.addWidget(self.logo_path_edit)

        browse_btn = QPushButton("📂 Browse...", self)
        browse_btn.setProperty("class", "btn-gray")
        browse_btn.clicked.connect(self._browse_logo)
        l_lay.addWidget(browse_btn)

        l_lay.addWidget(QLabel("X:", self))
        self.logo_x = QSpinBox(self)
        self.logo_x.setRange(0, 999)
        self.logo_x.setValue(233)
        self.logo_x.valueChanged.connect(self._on_logo_changed)
        l_lay.addWidget(self.logo_x)

        l_lay.addWidget(QLabel("Y:", self))
        self.logo_y = QSpinBox(self)
        self.logo_y.setRange(0, 999)
        self.logo_y.setValue(6)
        self.logo_y.valueChanged.connect(self._on_logo_changed)
        l_lay.addWidget(self.logo_y)

        l_lay.addWidget(QLabel("W:", self))
        self.logo_w = QSpinBox(self)
        self.logo_w.setRange(10, 500)
        self.logo_w.setValue(100)
        self.logo_w.valueChanged.connect(self._on_logo_changed)
        l_lay.addWidget(self.logo_w)

        l_lay.addWidget(QLabel("H:", self))
        self.logo_h = QSpinBox(self)
        self.logo_h.setRange(10, 500)
        self.logo_h.setValue(100)
        self.logo_h.valueChanged.connect(self._on_logo_changed)
        l_lay.addWidget(self.logo_h)

        self.remove_green_chk = QCheckBox("Key Green Screen", self)
        self.remove_green_chk.toggled.connect(self._on_logo_changed)
        l_lay.addWidget(self.remove_green_chk)

        apply_logo_btn = QPushButton("✓ Apply Logo", self)
        apply_logo_btn.setProperty("class", "btn-primary")
        apply_logo_btn.clicked.connect(self._apply_logo)
        l_lay.addWidget(apply_logo_btn)

        self.logo_status = QLabel("Ready", self)
        self.logo_status.setStyleSheet("color: #38bdf8; font-size: 11px;")
        l_lay.addWidget(self.logo_status)

        self.effect_tabs.addTab(logo_tab, "🖼 Logo Overlay")

        # ---------------- 4. TAB: BURN SUBTITLE ----------------
        burn_tab = QWidget()
        burn_lay = QHBoxLayout(burn_tab)
        burn_lay.setContentsMargins(12, 10, 12, 10)
        burn_lay.setSpacing(12)

        self.burn_sub_checkbox = QCheckBox("Burn Subtitles to Video", self)
        self.burn_sub_checkbox.setChecked(True)
        self.burn_sub_checkbox.toggled.connect(self._on_burn_sub_toggled)
        burn_lay.addWidget(self.burn_sub_checkbox)

        burn_lay.addWidget(QLabel("Font:", self))
        self.burn_sub_font_combo = QComboBox(self)
        self.burn_sub_font_combo.addItems(["Kantumruy Pro", "Noto Sans Khmer", "Battambang", "Khmer Sangam MN"])
        self.burn_sub_font_combo.currentTextChanged.connect(self._on_burn_sub_changed)
        burn_lay.addWidget(self.burn_sub_font_combo)

        burn_lay.addWidget(QLabel("Size:", self))
        self.burn_sub_size_spin = QSpinBox(self)
        self.burn_sub_size_spin.setRange(8, 60)
        self.burn_sub_size_spin.setValue(20)
        self.burn_sub_size_spin.valueChanged.connect(self._on_burn_sub_changed)
        burn_lay.addWidget(self.burn_sub_size_spin)

        burn_lay.addWidget(QLabel("Color:", self))
        self.burn_sub_color_btn = QPushButton("🎨", self)
        self.burn_sub_color_btn.setFixedSize(30, 26)
        self.burn_sub_color_btn.setStyleSheet("background-color: #FFFFFF; border: 1px solid #64748b; border-radius: 4px;")
        self.burn_sub_color_btn.clicked.connect(self._pick_burn_sub_color)
        burn_lay.addWidget(self.burn_sub_color_btn)

        burn_lay.addWidget(QLabel("BG Opacity:", self))
        self.burn_sub_bg_slider = QSlider(Qt.Horizontal, self)
        self.burn_sub_bg_slider.setRange(0, 100)
        self.burn_sub_bg_slider.setValue(60)
        self.burn_sub_bg_slider.setFixedWidth(90)
        self.burn_sub_bg_slider.valueChanged.connect(self._on_burn_sub_changed)
        burn_lay.addWidget(self.burn_sub_bg_slider)

        self.burn_sub_status = QLabel("Enabled ✓", self)
        self.burn_sub_status.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px;")
        burn_lay.addWidget(self.burn_sub_status)
        burn_lay.addStretch()

        self.effect_tabs.addTab(burn_tab, "💬 Burn Subtitles")

        main_lay.addWidget(self.effect_tabs)

    # ==================== BLUR SIGNALS ====================
    def _on_blur_toggled(self, checked: bool):
        self.blur_toggled.emit(checked)
        self.blur_value_lbl.setText(f"{self.blur_slider.value()}%" if checked else "Disabled")

    def _on_blur_intensity_changed(self, value: int):
        self.blur_value_lbl.setText(f"{value}%")
        self.blur_intensity_changed.emit(value)

    def _reset_blur_position(self):
        self.reset_blur_requested.emit()

    # ==================== TEXT OVERLAY SIGNALS ====================
    def _on_text_toggled(self, checked: bool):
        self.text_toggled.emit(checked)
        self.text_status.setText("Status: Enabled ✓" if checked else "Status: Disabled")

    def _on_text_changed(self, text: str):
        self._current_text = text
        if self.text_checkbox.isChecked():
            self.text_updated.emit(text, self._current_color, self._current_size, self._current_font)

    def _on_font_changed(self, font_name: str):
        self._current_font = font_name
        self.text_status.setText(f"Font: {font_name}")
        if self.text_checkbox.isChecked():
            self.text_updated.emit(self._current_text, self._current_color, self._current_size, font_name)

    def _on_size_changed(self, size: int):
        self._current_size = size
        if self.text_checkbox.isChecked():
            self.text_updated.emit(self._current_text, self._current_color, size, self._current_font)

    def _on_position_changed(self):
        x = self.pos_x.value()
        y = self.pos_y.value()
        self.text_status.setText(f"Position: ({x}, {y})")
        self.text_position_changed.emit(x, y)

    def update_text_position_spinboxes(self, x: int, y: int):
        self.pos_x.blockSignals(True)
        self.pos_y.blockSignals(True)
        self.pos_x.setValue(x)
        self.pos_y.setValue(y)
        self.pos_x.blockSignals(False)
        self.pos_y.blockSignals(False)
        self.text_status.setText(f"Position: ({x}, {y}) [Dragged]")

    def update_logo_spinboxes(self, x: int, y: int, w: int, h: int):
        self.logo_x.blockSignals(True)
        self.logo_y.blockSignals(True)
        self.logo_w.blockSignals(True)
        self.logo_h.blockSignals(True)
        self.logo_x.setValue(x)
        self.logo_y.setValue(y)
        self.logo_w.setValue(w)
        self.logo_h.setValue(h)
        self.logo_x.blockSignals(False)
        self.logo_y.blockSignals(False)
        self.logo_w.blockSignals(False)
        self.logo_h.blockSignals(False)
        self.logo_status.setText(f"Position: ({x}, {y}) {w}x{h} [Dragged]")

    def _pick_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._current_color = hex_color
            self.color_btn.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #666;")
            if self.text_checkbox.isChecked():
                self.text_updated.emit(self._current_text, hex_color, self._current_size, self._current_font)

    def _apply_text(self):
        text = self.text_input.text()
        color = self._current_color
        size = self.size_spin.value()
        font_name = self.text_font_combo.currentText()
        x = self.pos_x.value()
        y = self.pos_y.value()
        
        self._current_text = text
        self._current_size = size
        self._current_font = font_name
        
        self.text_status.setText(f"Applied: '{text[:20]}...' at ({x}, {y})")
        self.text_position_changed.emit(x, y)
        self.text_updated.emit(text, color, size, font_name)
        
        if not self.text_checkbox.isChecked():
            self.text_checkbox.setChecked(True)

    # ==================== LOGO SIGNALS ====================
    def _on_logo_toggled(self, checked: bool):
        self.logo_toggled.emit(checked)
        self.logo_status.setText("Status: Enabled ✓" if checked else "Status: Disabled")

    def _on_logo_path_changed(self, path: str):
        if path and os.path.exists(path):
            self.logo_status.setText(f"Status: Loaded {os.path.basename(path)}")
        else:
            self.logo_status.setText("Status: File not found")
        if self.logo_checkbox.isChecked() and path:
            self._apply_logo()

    def _on_logo_changed(self):
        if self.logo_checkbox.isChecked():
            self._apply_logo()

    def _apply_logo(self):
        path = self.logo_path_edit.text()
        x = self.logo_x.value()
        y = self.logo_y.value()
        w = self.logo_w.value()
        h = self.logo_h.value()
        remove_green = self.remove_green_chk.isChecked()
        
        if not path:
            self.logo_status.setText("Status: No file selected")
            return
        
        if not os.path.exists(path):
            self.logo_status.setText("Status: File not found")
            return
        
        self.logo_status.setText(f"Applied: {os.path.basename(path)} at ({x}, {y})")
        self.logo_updated.emit(path, x, y, w, h, remove_green)
        
        if not self.logo_checkbox.isChecked():
            self.logo_checkbox.setChecked(True)

    def _browse_logo(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo Image", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if file_path:
            self.logo_path_edit.setText(file_path)

    # ==================== BURN SUBTITLE SIGNALS ====================
    def _on_burn_sub_toggled(self, checked: bool):
        self.burn_subtitle_toggled.emit(checked)
        self.burn_sub_status.setText("Status: Enabled ✓" if checked else "Status: Disabled")
        self._emit_burn_sub_updated()

    def _on_burn_sub_changed(self):
        self._emit_burn_sub_updated()

    def _pick_burn_sub_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            hex_color = color.name()
            self._burn_color = hex_color
            self.burn_sub_color_btn.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #666;")
            self._emit_burn_sub_updated()

    def _emit_burn_sub_updated(self):
        enabled = self.burn_sub_checkbox.isChecked()
        font_name = self.burn_sub_font_combo.currentText()
        size = self.burn_sub_size_spin.value()
        color_hex = self._burn_color
        bg_opacity = self.burn_sub_bg_slider.value() / 100.0
        self.burn_subtitle_updated.emit(enabled, font_name, size, color_hex, bg_opacity)

    def get_state(self) -> dict:
        """Serialize current effects settings for project file saving."""
        return {
            "blur_enabled": self.blur_checkbox.isChecked(),
            "blur_intensity": self.blur_slider.value(),
            "text_enabled": self.text_checkbox.isChecked(),
            "text_content": self.text_input.text(),
            "text_font": self.text_font_combo.currentText(),
            "text_size": self.size_spin.value(),
            "text_color": self._current_color,
            "text_x": self.pos_x.value(),
            "text_y": self.pos_y.value(),
            "logo_enabled": self.logo_checkbox.isChecked(),
            "logo_path": self.logo_path_edit.text(),
            "logo_x": self.logo_x.value(),
            "logo_y": self.logo_y.value(),
            "logo_w": self.logo_w.value(),
            "logo_h": self.logo_h.value(),
            "logo_remove_green": self.remove_green_chk.isChecked(),
            "burn_sub_enabled": self.burn_sub_checkbox.isChecked(),
            "burn_sub_font": self.burn_sub_font_combo.currentText(),
            "burn_sub_size": self.burn_sub_size_spin.value() if hasattr(self, 'burn_sub_size_spin') else 18,
            "burn_sub_color": self._burn_color,
            "burn_sub_opacity": self.burn_sub_bg_slider.value() if hasattr(self, 'burn_sub_bg_slider') else 50,
        }

    def set_state(self, state: dict):
        """Restore effects settings from a saved project file."""
        if not isinstance(state, dict):
            return
        if "blur_enabled" in state:
            self.blur_checkbox.setChecked(bool(state["blur_enabled"]))
        if "blur_intensity" in state:
            self.blur_slider.setValue(int(state["blur_intensity"]))
        if "text_enabled" in state:
            self.text_checkbox.setChecked(bool(state["text_enabled"]))
        if "text_content" in state:
            self.text_input.setText(str(state["text_content"]))
        if "text_font" in state:
            idx = self.text_font_combo.findText(state["text_font"])
            if idx >= 0:
                self.text_font_combo.setCurrentIndex(idx)
        if "text_size" in state:
            self.size_spin.setValue(int(state["text_size"]))
        if "text_color" in state:
            self._current_color = str(state["text_color"])
            self.color_btn.setStyleSheet(f"background-color: {self._current_color}; border: 1px solid #64748b; border-radius: 4px;")
        if "text_x" in state:
            self.pos_x.setValue(int(state["text_x"]))
        if "text_y" in state:
            self.pos_y.setValue(int(state["text_y"]))
        if "logo_enabled" in state:
            self.logo_checkbox.setChecked(bool(state["logo_enabled"]))
        if "logo_path" in state:
            self.logo_path_edit.setText(str(state["logo_path"]))
        if "logo_x" in state:
            self.logo_x.setValue(int(state["logo_x"]))
        if "logo_y" in state:
            self.logo_y.setValue(int(state["logo_y"]))
        if "logo_w" in state:
            self.logo_w.setValue(int(state["logo_w"]))
        if "logo_h" in state:
            self.logo_h.setValue(int(state["logo_h"]))
        if "logo_remove_green" in state:
            self.remove_green_chk.setChecked(bool(state["logo_remove_green"]))
        if "burn_sub_enabled" in state:
            self.burn_sub_checkbox.setChecked(bool(state["burn_sub_enabled"]))
        if "burn_sub_font" in state:
            idx = self.burn_sub_font_combo.findText(state["burn_sub_font"])
            if idx >= 0:
                self.burn_sub_font_combo.setCurrentIndex(idx)
        if "burn_sub_size" in state and hasattr(self, 'burn_sub_size_spin'):
            self.burn_sub_size_spin.setValue(int(state["burn_sub_size"]))
        if "burn_sub_color" in state:
            self._burn_color = str(state["burn_sub_color"])
            if hasattr(self, 'burn_sub_color_btn'):
                self.burn_sub_color_btn.setStyleSheet(f"background-color: {self._burn_color}; border: 1px solid #666;")
        if "burn_sub_opacity" in state and hasattr(self, 'burn_sub_bg_slider'):
            self.burn_sub_bg_slider.setValue(int(state["burn_sub_opacity"]))
        
        # Re-apply updated configurations
        if self.text_checkbox.isChecked():
            self._apply_text()
        if self.logo_checkbox.isChecked() and self.logo_path_edit.text():
            self._apply_logo()
        self._emit_burn_sub_updated()


# ==================== DROP ZONE ====================
class DropZoneWidget(QFrame):
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.selected_path = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setAlignment(Qt.AlignCenter)

        self.icon_label = QLabel("🎬", self)
        self.icon_label.setStyleSheet("font-size: 38px;")
        self.icon_label.setAlignment(Qt.AlignCenter)

        self.info_label = QLabel("Drag & Drop Video Here or Click to Browse", self)
        self.info_label.setStyleSheet("font-weight: 700; font-size: 14px; color: #ffffff;")
        self.info_label.setAlignment(Qt.AlignCenter)

        self.browse_btn = QPushButton("📁 Select Video File...", self)
        self.browse_btn.setFixedWidth(180)
        self.browse_btn.clicked.connect(self._browse_file)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.browse_btn, alignment=Qt.AlignCenter)

    def _browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mkv *.avi *.mov *.webm)"
        )
        if file_path:
            self.set_file_path(file_path)

    def set_file_path(self, path: str):
        self.selected_path = path
        self.file_dropped.emit(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                self.set_file_path(file_path)


# ==================== SEGMENT EDITOR ====================
class SegmentEditorWidget(QWidget):
    segments_updated = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        tools_lay = QHBoxLayout()
        
        tools_lbl = QLabel("Transcript Segments Editor", self)
        tools_lbl.setStyleSheet("font-weight: bold; color: #8fa0c0; font-size: 12px;")
        tools_lay.addWidget(tools_lbl)
        tools_lay.addStretch()

        self.add_row_btn = QPushButton("➕ Add Row", self)
        self.add_row_btn.clicked.connect(self._add_empty_row)
        
        self.del_row_btn = QPushButton("🗑 Delete Row", self)
        self.del_row_btn.clicked.connect(self._delete_selected_row)

        self.import_srt_btn = QPushButton("📥 Import SRT", self)
        self.import_srt_btn.clicked.connect(self._import_srt)

        self.export_srt_btn = QPushButton("📤 Export SRT", self)
        self.export_srt_btn.clicked.connect(self._export_srt)

        tools_lay.addWidget(self.add_row_btn)
        tools_lay.addWidget(self.del_row_btn)
        tools_lay.addWidget(self.import_srt_btn)
        tools_lay.addWidget(self.export_srt_btn)

        layout.addLayout(tools_lay)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["TIMELINE", "ORIGINAL SPEECH (STT)", "KHMER TRANSLATION 🇰🇭 (DOUBLE-CLICK TO EDIT)", "ACTION"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

        layout.addWidget(self.table)

    def set_segments(self, segments: list):
        self.segments = segments
        self.table.setRowCount(0)

        for i, seg in enumerate(segments):
            self._insert_segment_row(i, seg)

    def _insert_segment_row(self, row: int, seg: dict):
        self.table.insertRow(row)
        
        start = seg.get("start", 0.0)
        end = seg.get("end", 0.0)
        time_str = f"⏱ [{start:05.2f}s → {end:05.2f}s]"
        t_item = QTableWidgetItem(time_str)
        t_item.setFlags(t_item.flags() & ~Qt.ItemIsEditable)
        t_item.setForeground(Qt.GlobalColor.cyan)
        self.table.setItem(row, 0, t_item)

        orig_text = seg.get("original_text", seg.get("text", ""))
        orig_item = QTableWidgetItem(orig_text)
        orig_item.setFlags(orig_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 1, orig_item)

        khmer_text = seg.get("khmer_text", "")
        khmer_item = QTableWidgetItem(khmer_text)
        self.table.setItem(row, 2, khmer_item)

        preview_btn = QPushButton("🔊 Test Voice", self)
        preview_btn.setFixedWidth(95)
        preview_btn.clicked.connect(lambda _, r=row: self._preview_segment_tts(r))
        self.table.setCellWidget(row, 3, preview_btn)

    def _add_empty_row(self):
        row_count = self.table.rowCount()
        last_end = self.segments[-1]["end"] if self.segments else 0.0
        new_seg = {
            "start": round(last_end, 2),
            "end": round(last_end + 3.0, 2),
            "original_text": "New transcript line...",
            "khmer_text": "អត្ថបទខ្មែរថ្មី..."
        }
        self.segments.append(new_seg)
        self._insert_segment_row(row_count, new_seg)

    def _delete_selected_row(self):
        curr_row = self.table.currentRow()
        if curr_row >= 0:
            self.table.removeRow(curr_row)
            if curr_row < len(self.segments):
                self.segments.pop(curr_row)

    def get_updated_segments(self) -> list:
        updated = []
        for i in range(self.table.rowCount()):
            time_item = self.table.item(i, 0)
            orig_item = self.table.item(i, 1)
            khmer_item = self.table.item(i, 2)
            
            orig_seg = self.segments[i] if i < len(self.segments) else {}
            updated.append({
                "start": orig_seg.get("start", i * 3.0),
                "end": orig_seg.get("end", (i + 1) * 3.0),
                "original_text": orig_item.text() if orig_item else "",
                "khmer_text": khmer_item.text() if khmer_item else ""
            })
        return updated

    def _preview_segment_tts(self, row: int):
        khmer_item = self.table.item(row, 2)
        if not khmer_item or not khmer_item.text().strip():
            return
        
        khmer_text = khmer_item.text().strip()
        from utils.file_utils import get_temp_path
        
        svc = VoxCPMService()
        out_wav = get_temp_path(f"preview_row_{row}.wav")
        if svc.synthesize(khmer_text, out_wav):
            try:
                subprocess.run(["afplay", out_wav], check=False)
            except Exception:
                pass

    def _import_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import SRT Subtitle File", "", "Subtitle Files (*.srt)")
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                from core.srt_translator import SRTTranslator
                translator = SRTTranslator()
                sub_segs = translator.parse_srt(content)
                
                new_segments = []
                for seg in sub_segs:
                    new_segments.append({
                        "start": seg.start_seconds,
                        "end": seg.end_seconds,
                        "original_text": seg.text,
                        "khmer_text": seg.text
                    })
                self.set_segments(new_segments)
            except Exception as e:
                print(f"Error importing SRT: {e}")

    def _export_srt(self):
        updated = self.get_updated_segments()
        if not updated:
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Translated SRT", "khmer_subtitles.srt", "Subtitle Files (*.srt)")
        if file_path:
            try:
                from core.srt_translator import SRTTranslator
                translator = SRTTranslator()
                sub_segs = translator.parse_segment_dicts(updated)
                translator.save_srt(sub_segs, file_path)
            except Exception as e:
                print(f"Error exporting SRT: {e}")


# ==================== LOG CONSOLE ====================
class LogConsoleWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logConsole")
        self.setReadOnly(True)

    def append_log(self, text: str):
        self.append(text)
        sb = self.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())


# ==================== VOICE PROMPT & CHARACTER DESIGNER ====================
class VoicePromptEditor(QWidget):
    """
    Voice Prompt Editor for Character Voice Design.
    Extracts structured voice profile from natural language prompts.
    """
    voice_profile_updated = Signal(object)
    
    def __init__(self, parent=None, character_name: str = None):
        super().__init__(parent)
        self.character_name = character_name or "New Character"
        self.current_profile = None
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Character Name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("👤 Character Name:", self))
        self.name_input = QLineEdit(self.character_name, self)
        self.name_input.setPlaceholderText("e.g., Grandfather, Young Narrator, Police Officer...")
        self.name_input.textChanged.connect(self._on_name_changed)
        name_layout.addWidget(self.name_input, 1)
        layout.addLayout(name_layout)
        
        # Voice Prompt Input
        prompt_layout = QVBoxLayout()
        prompt_layout.addWidget(QLabel("🎭 Voice Prompt (Natural Language):", self))
        self.prompt_input = QTextEdit(self)
        self.prompt_input.setPlaceholderText(
            "Describe the voice characteristics in English or Khmer...\n\n"
            "Examples:\n"
            "- Cambodian male, deep voice, calm narrator, slow and confident\n"
            "- Young female, soft and warm, friendly conversational tone\n"
            "- មនុស្សប្រុស សំឡេងធំ គ្រលរ និយាយរឿងនិទាន ស្ងប់ស្ងាត់\n"
            "- ក្មេងស្រី សំឡេងខ្ពស់ រីករាយ រហ័សរហួន"
        )
        self.prompt_input.setMinimumHeight(100)
        self.prompt_input.textChanged.connect(self._on_prompt_changed)
        prompt_layout.addWidget(self.prompt_input)
        layout.addLayout(prompt_layout)
        
        # Quick Presets
        presets_box = QGroupBox("⚡ Quick Voice Prompt Presets", self)
        presets_box.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; color: #38bdf8; }")
        presets_layout = QHBoxLayout(presets_box)
        presets_layout.setSpacing(6)
        
        preset_buttons = [
            ("🎙️ Narrator", "Male, deep voice, calm, professional narrator, medium speed"),
            ("👩 Friendly Female", "Female, warm, friendly, conversational, natural Khmer"),
            ("😡 Intense/Angry", "Male, intense, angry, fast speaking, powerful delivery"),
            ("👧 Little Girl", "Child female, cute, energetic, happy, high pitch"),
            ("👴 Grandfather", "Elderly male, slow, wise, gentle, deep voice"),
        ]
        
        for label, prompt in preset_buttons:
            btn = QPushButton(label, self)
            btn.setProperty("class", "btn-gray")
            btn.setStyleSheet("font-size: 10px; padding: 4px 8px;")
            btn.clicked.connect(lambda _, p=prompt: self.prompt_input.setText(p))
            presets_layout.addWidget(btn)
        
        presets_layout.addStretch()
        layout.addWidget(presets_box)
        
        # Profile Preview Group
        self.profile_preview = QGroupBox("📋 Extracted Character Profile Parameters", self)
        self.profile_preview.setStyleSheet("""
            QGroupBox {
                background-color: #0c101d;
                border: 1px solid #1a233a;
                border-radius: 8px;
                padding: 10px;
                font-weight: bold;
                color: #38bdf8;
            }
        """)
        preview_layout = QVBoxLayout(self.profile_preview)
        self.profile_text = QLabel("Type a prompt above or pick a preset to extract profile parameters.", self)
        self.profile_text.setWordWrap(True)
        self.profile_text.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: monospace;")
        preview_layout.addWidget(self.profile_text)
        layout.addWidget(self.profile_preview)
        
        # Reference Audio (Optional for voice cloning)
        ref_group = QGroupBox("🎵 Reference Audio Sample (Optional for Zero-Shot Clone)", self)
        ref_group.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; color: #a855f7; }")
        ref_layout = QHBoxLayout(ref_group)
        
        self.ref_path_input = QLineEdit(self)
        self.ref_path_input.setPlaceholderText("Optional: reference audio path for speaker timbre cloning...")
        ref_layout.addWidget(self.ref_path_input, 1)
        
        browse_ref_btn = QPushButton("📂 Browse", self)
        browse_ref_btn.setProperty("class", "btn-gray")
        browse_ref_btn.clicked.connect(self._browse_reference)
        ref_layout.addWidget(browse_ref_btn)
        
        layout.addWidget(ref_group)

        # Test Generation Row
        test_box = QGroupBox("🔊 Live Voice Test Synthesis", self)
        test_box.setStyleSheet("QGroupBox { font-size: 11px; font-weight: bold; color: #10b981; }")
        test_lay = QHBoxLayout(test_box)
        
        self.test_text_input = QLineEdit("សួស្តីអ្នកទាំងអស់គ្នា! នេះជាសំឡេងដែលបានបង្កើតចេញពី Voice Prompt។", self)
        test_lay.addWidget(self.test_text_input, 1)
        
        self.test_btn = QPushButton("▶ Test Voice", self)
        self.test_btn.setProperty("class", "btn-gold")
        self.test_btn.clicked.connect(self._test_voice)
        test_lay.addWidget(self.test_btn)
        
        layout.addWidget(test_box)

    def _on_name_changed(self, text: str):
        self.character_name = text.strip() or "New Character"
        self._extract_profile()

    def _on_prompt_changed(self):
        prompt = self.prompt_input.toPlainText().strip()
        if len(prompt) >= 3:
            self._extract_profile()

    def _extract_profile(self):
        from services.voice_prompt_processor import VoicePromptProcessor
        prompt = self.prompt_input.toPlainText().strip()
        if not prompt:
            self.profile_text.setText("⚠️ Please enter a voice prompt.")
            self.current_profile = None
            return
        
        try:
            profile = VoicePromptProcessor.process_prompt(
                prompt,
                name=self.character_name
            )
            self.current_profile = profile
            
            ref_path = self.ref_path_input.text().strip()
            if ref_path and os.path.exists(ref_path):
                self.current_profile.reference_audio = ref_path
                self.current_profile.is_clone = True
            
            preview_text = (
                f"👤 Name: {profile.name}\n"
                f"├─ Gender: {profile.gender.upper()}  |  Age: {profile.age.upper()}\n"
                f"├─ Emotion: {profile.emotion.upper()}  |  Style: {profile.style.upper()}\n"
                f"├─ Pitch: {profile.pitch.upper()} (Shift: {profile.pitch_shift:.2f}x)  |  Speed: {profile.speed:.2f}x\n"
                f"└─ Acoustic Model: {'Zero-Shot Clone' if profile.is_clone else 'Neural Voice Design'}\n\n"
                f"📝 Description: {profile.voice_description[:160]}..."
            )
            self.profile_text.setText(preview_text)
            self.voice_profile_updated.emit(profile)
        except Exception as e:
            self.profile_text.setText(f"❌ Extraction error: {e}")

    def _browse_reference(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Reference Audio/Video",
            "",
            "All Supported Files (*.wav *.mp3 *.m4a *.flac *.mp4 *.mov *.mkv)"
        )
        if file_path:
            self.ref_path_input.setText(file_path)
            if self.current_profile:
                self.current_profile.reference_audio = file_path
                self.current_profile.is_clone = True
                self._extract_profile()

    def _test_voice(self):
        from utils.file_utils import get_temp_path
        from services.voxcpm_service import VoxCPM2Runner
        import subprocess

        if not self.current_profile:
            self._extract_profile()

        if not self.current_profile:
            return

        test_text = self.test_text_input.text().strip() or "សួស្តីអ្នកទាំងអស់គ្នា!"
        out_wav = get_temp_path("test_character_voice.wav")
        
        self.test_btn.setEnabled(False)
        self.test_btn.setText("⏳ Generating...")
        QApplication.processEvents()

        try:
            runner = VoxCPM2Runner()
            success = runner.generate_with_profile(
                text=test_text,
                profile=self.current_profile,
                reference_audio=self.current_profile.reference_audio,
                reference_text=self.current_profile.reference_text,
                output_path=out_wav,
                mode="full_c"
            )
            if success and os.path.exists(out_wav):
                try:
                    subprocess.Popen(["afplay", out_wav])
                except Exception:
                    pass
        except Exception as e:
            print(f"Error during voice test: {e}")
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("▶ Test Voice")


class VoicePromptDialog(QDialog):
    """Dialog wrapping VoicePromptEditor to save characters to storage"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎭 Voice Prompt & Character Voice Designer")
        self.setMinimumSize(640, 680)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 12, 12, 12)

        self.editor = VoicePromptEditor(self)
        layout.addWidget(self.editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setProperty("class", "btn-gray")
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("💾 Save Character Profile", self)
        self.save_btn.setProperty("class", "btn-primary")
        self.save_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.save_btn.clicked.connect(self._save_and_accept)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)

    def _save_and_accept(self):
        from services.character_voice_manager import CharacterVoiceManager
        from services.voxcpm_service import add_custom_voice_preset
        
        profile = self.editor.current_profile
        if not profile:
            self.editor._extract_profile()
            profile = self.editor.current_profile

        if profile:
            manager = CharacterVoiceManager()
            manager._save_character(profile)
            manager._characters_cache[profile.name] = profile
            
            preset_dict = manager.get_voxcpm_preset(profile.name)
            if preset_dict:
                add_custom_voice_preset(profile.name, preset_dict)
            
            QMessageBox.information(
                self,
                "Character Saved",
                f"✅ Character '{profile.name}' has been saved and is ready for dubbing!"
            )
            self.accept()
        else:
            QMessageBox.warning(self, "Warning", "Please provide a valid voice prompt first.")


# ==================== 🎙️ AI VOICE STUDIO (PROMPT -> TEXT -> GENERATE -> RESULT) ====================
class VoiceStudioWorker(QtCore.QThread):
    """Background Worker for Asynchronous Voice Generation with Real-Time Percentage"""
    progress = Signal(int, str)  # (percent, status_message)
    finished = Signal(str, object)  # (out_wav_path, profile)
    error = Signal(str)

    def __init__(self, prompt_text: str, speech_text: str, parent=None):
        super().__init__(parent)
        self.prompt_text = prompt_text
        self.speech_text = speech_text

    def run(self):
        try:
            from services.voice_prompt_processor import VoicePromptProcessor
            from services.voxcpm_service import VoxCPM2Runner
            from utils.file_utils import get_temp_path
            import time

            # Step 1: Parse prompt
            self.progress.emit(15, "15% • Parsing Voice Prompt & Identity...")
            time.sleep(0.15)
            profile = VoicePromptProcessor.process_prompt(self.prompt_text or "Female Khmer voice", name="Studio Character")
            
            # Step 2: Acoustic Conditioning
            self.progress.emit(35, f"35% • Conditioning Pitch ({profile.pitch_shift:.2f}x) & Timbre...")
            time.sleep(0.15)
            
            # Step 3: VoxCPM2 Neural Synthesis
            self.progress.emit(65, "65% • Synthesizing Neural Speech (VoxCPM2)...")
            out_wav = get_temp_path("ai_voice_studio_output.wav")
            runner = VoxCPM2Runner()
            success = runner.generate_with_profile(
                text=self.speech_text,
                profile=profile,
                output_path=out_wav,
                mode="full_c"
            )

            # Step 4: Mastering & Export
            self.progress.emit(88, "88% • Mastering Audio & Normalizing Loudness...")
            time.sleep(0.1)

            if success and os.path.exists(out_wav):
                self.progress.emit(100, "100% • Generated Successfully! 🎉")
                self.finished.emit(out_wav, profile)
            else:
                self.error.emit("Failed to synthesize audio output.")
        except Exception as e:
            self.error.emit(str(e))


class AIVoiceStudioWidget(QWidget):
    """
    Dedicated AI Character Voice Design Studio:
    - 🎭 Character Voice Attributes (Name, Gender, Age, Voice Type, Tone, Emotion, Style, Speed, Additional)
    - 🤖 Auto-Prompt Builder (Live AI Prompt Generation)
    - 📝 Text to Speak (Khmer Text Input)
    - [ 🎙️ GENERATE VOICE ] (Action Button + 0%-100% Percentage Progress)
    - 🔊 Result (Audio Player with ▶/⏸, Progress Bar, Time, and Save Profile)
    """
    voice_generated = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_audio_path = None
        self.current_profile = None
        self.audio_duration_sec = 0.0
        self.current_pos_sec = 0.0
        self._proc = None
        self._is_playing = False
        self._worker = None
        self._custom_prompt_edited = False
        
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_playback_progress)
        
        self._init_ui()
        self._build_prompt_from_form()

    def _init_ui(self):
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(16, 16, 16, 16)
        main_lay.setSpacing(10)

        # Studio Container Card with Scroll Area to support all screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        card = QFrame()
        card.setStyleSheet("""
            QFrame#studioCard {
                background-color: #080c16;
                border: 1px solid #1e2942;
                border-radius: 12px;
                padding: 14px;
            }
        """)
        card.setObjectName("studioCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(10)

        # Header: 🎙️ AI Voice Studio
        header_lay = QHBoxLayout()
        icon_lbl = QLabel("🎙️", card)
        icon_lbl.setStyleSheet("font-size: 22px;")
        
        title_box = QVBoxLayout()
        title_lbl = QLabel("AI Character Voice Studio", card)
        title_lbl.setStyleSheet("color: #38bdf8; font-size: 16px; font-weight: 800; letter-spacing: 0.5px;")
        sub_lbl = QLabel("Character Attributes → Auto-Prompt Builder → VoxCPM2 Neural Speech", card)
        sub_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(sub_lbl)
        
        header_lay.addWidget(icon_lbl)
        header_lay.addLayout(title_box)
        header_lay.addStretch()
        
        c_lay.addLayout(header_lay)

        # Divider
        sep1 = QFrame(card)
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("background-color: #1a233a; max-height: 1px;")
        c_lay.addWidget(sep1)

        # ==================== 1. CHARACTER ATTRIBUTES FORM ====================
        attr_box = QGroupBox("🎭 Create Character Voice Attributes", card)
        attr_box.setStyleSheet("""
            QGroupBox {
                background-color: #0c101d;
                border: 1px solid #1e2942;
                border-radius: 8px;
                padding: 12px;
                margin-top: 6px;
                font-weight: bold;
                color: #38bdf8;
                font-size: 12px;
            }
        """)
        a_lay = QVBoxLayout(attr_box)
        a_lay.setSpacing(8)

        # Row 1: Character Name, Gender, Age
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Name:", attr_box))
        self.name_input = QLineEdit("Dara", attr_box)
        self.name_input.setPlaceholderText("Character Name (e.g. Dara)")
        self.name_input.textChanged.connect(self._on_form_changed)
        r1.addWidget(self.name_input, stretch=2)

        r1.addWidget(QLabel("Gender:", attr_box))
        self.gender_combo = QComboBox(attr_box)
        self.gender_combo.addItems(["Male", "Female"])
        self.gender_combo.currentIndexChanged.connect(self._on_form_changed)
        r1.addWidget(self.gender_combo, stretch=1)

        r1.addWidget(QLabel("Age:", attr_box))
        self.age_spin = QSpinBox(attr_box)
        self.age_spin.setRange(5, 95)
        self.age_spin.setValue(30)
        self.age_spin.valueChanged.connect(self._on_form_changed)
        r1.addWidget(self.age_spin, stretch=1)

        a_lay.addLayout(r1)

        # Row 2: Voice Type, Tone, Emotion
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Voice Type:", attr_box))
        self.type_combo = QComboBox(attr_box)
        self.type_combo.addItems(["Deep", "Soft", "Raspy", "Crisp", "Resonant", "Warm", "Bright"])
        self.type_combo.currentIndexChanged.connect(self._on_form_changed)
        r2.addWidget(self.type_combo, 1)

        r2.addWidget(QLabel("Tone:", attr_box))
        self.tone_combo = QComboBox(attr_box)
        self.tone_combo.addItems(["Warm", "Bright", "Dark", "Calm", "Gentle", "Authoritative"])
        self.tone_combo.currentIndexChanged.connect(self._on_form_changed)
        r2.addWidget(self.tone_combo, 1)

        r2.addWidget(QLabel("Emotion:", attr_box))
        self.emotion_combo = QComboBox(attr_box)
        self.emotion_combo.addItems(["Calm", "Friendly", "Confident", "Happy", "Intense/Angry", "Sad", "Mysterious"])
        self.emotion_combo.currentIndexChanged.connect(self._on_form_changed)
        r2.addWidget(self.emotion_combo, 1)

        a_lay.addLayout(r2)

        # Row 3: Speaking Style, Speed, Additional Description
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Style:", attr_box))
        self.style_combo = QComboBox(attr_box)
        self.style_combo.addItems(["Natural Conversation", "Professional Narrator", "Storytelling", "Dramatic Movie", "Casual Dialogue"])
        self.style_combo.currentIndexChanged.connect(self._on_form_changed)
        r3.addWidget(self.style_combo, stretch=2)

        r3.addWidget(QLabel("Speed:", attr_box))
        self.speed_combo = QComboBox(attr_box)
        self.speed_combo.addItems(["Slow (0.85x)", "Medium (1.0x)", "Fast (1.15x)"])
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.currentIndexChanged.connect(self._on_form_changed)
        r3.addWidget(self.speed_combo, stretch=1)

        a_lay.addLayout(r3)

        # Row 4: Additional Description
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("Details:", attr_box))
        self.additional_input = QLineEdit("Professional Cambodian narrator", attr_box)
        self.additional_input.setPlaceholderText("Additional voice details (optional)...")
        self.additional_input.textChanged.connect(self._on_form_changed)
        r4.addWidget(self.additional_input, 1)
        a_lay.addLayout(r4)

        c_lay.addWidget(attr_box)

        # ==================== 2. GENERATED PROMPT VIEWER ====================
        p_hdr = QHBoxLayout()
        prompt_lbl = QLabel("🎙️ Generated Natural Language Prompt", card)
        prompt_lbl.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 12px;")
        p_hdr.addWidget(prompt_lbl)
        p_hdr.addStretch()

        self.edit_prompt_toggle = QPushButton("✏️ Custom Edit", card)
        self.edit_prompt_toggle.setProperty("class", "btn-gray")
        self.edit_prompt_toggle.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        def _toggle_edit():
            self._custom_prompt_edited = True
            self.prompt_input.setReadOnly(False)
            self.prompt_input.setFocus()
        self.edit_prompt_toggle.clicked.connect(_toggle_edit)
        p_hdr.addWidget(self.edit_prompt_toggle)
        c_lay.addLayout(p_hdr)

        self.prompt_input = QTextEdit(card)
        self.prompt_input.setPlaceholderText("Auto-generated prompt will appear here...")
        self.prompt_input.setMinimumHeight(60)
        self.prompt_input.setMaximumHeight(75)
        self.prompt_input.setStyleSheet("""
            QTextEdit {
                background-color: #0c101d;
                border: 1px solid #1e2942;
                border-radius: 8px;
                padding: 6px 10px;
                color: #f1f5f9;
                font-size: 11px;
                font-family: monospace;
            }
            QTextEdit:focus {
                border: 1px solid #38bdf8;
            }
        """)
        c_lay.addWidget(self.prompt_input)

        # ==================== 3. TARGET TEXT TO SPEAK ====================
        t_hdr = QLabel("📝 Text to Speak (Khmer Script)", card)
        t_hdr.setStyleSheet("color: #f1f5f9; font-size: 12px; font-weight: 700; margin-top: 2px;")
        c_lay.addWidget(t_hdr)

        self.text_input = QTextEdit(card)
        self.text_input.setPlaceholderText("បញ្ចូលអត្ថបទខ្មែរដែលត្រូវបង្កើតសំឡេង (Khmer text to synthesize)...")
        self.text_input.setText("សួស្តីអ្នកទាំងអស់គ្នា! ថ្ងៃនេះខ្ញុំនឹងបង្ហាញអំពីបច្ចេកវិទ្យាបង្កើតសំឡេងតាម AI Voice Studio។")
        self.text_input.setMinimumHeight(60)
        self.text_input.setMaximumHeight(75)
        self.text_input.setStyleSheet("""
            QTextEdit {
                background-color: #0c101d;
                border: 1px solid #1e2942;
                border-radius: 8px;
                padding: 6px 10px;
                color: #f1f5f9;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #2563eb;
            }
        """)
        c_lay.addWidget(self.text_input)

        # ==================== 4. GENERATE 🔊 ACTION ====================
        gen_box = QHBoxLayout()
        gen_box.addStretch()
        
        self.generate_btn = QPushButton("🎙️ GENERATE VOICE 🔊", card)
        self.generate_btn.setMinimumHeight(44)
        self.generate_btn.setMinimumWidth(240)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2563eb, stop:1 #1d4ed8);
                border: 1px solid #3b82f6;
                border-radius: 8px;
                color: #ffffff;
                font-size: 14px;
                font-weight: 800;
                padding: 10px 24px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
                border-color: #60a5fa;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                border-color: #334155;
                color: #64748b;
            }
        """)
        self.generate_btn.clicked.connect(self._run_generation)
        gen_box.addWidget(self.generate_btn)
        gen_box.addStretch()
        
        c_lay.addLayout(gen_box)

        # Percentage Progress Bar
        self.progress_bar = QProgressBar(card)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready (0%)")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0c101d;
                border: 1px solid #1e2942;
                border-radius: 8px;
                height: 20px;
                text-align: center;
                color: #f1f5f9;
                font-size: 11px;
                font-weight: 700;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
                border-radius: 7px;
            }
        """)
        self.progress_bar.setVisible(False)
        c_lay.addWidget(self.progress_bar)

        # ==================== 5. RESULT AUDIO PLAYER ====================
        sec4_box = QFrame(card)
        sec4_box.setStyleSheet("""
            QFrame {
                background-color: #0c101d;
                border: 1px solid #1a233a;
                border-radius: 10px;
                padding: 8px 12px;
            }
        """)
        s4_lay = QVBoxLayout(sec4_box)
        s4_lay.setContentsMargins(6, 6, 6, 6)
        s4_lay.setSpacing(6)

        r_header_lay = QHBoxLayout()
        r_lbl = QLabel("🔊 Generated Audio Result", sec4_box)
        r_lbl.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 12px;")
        r_header_lay.addWidget(r_lbl)
        
        self.badge_lbl = QLabel("Ready to generate", sec4_box)
        self.badge_lbl.setStyleSheet("color: #64748b; font-size: 11px;")
        r_header_lay.addStretch()
        r_header_lay.addWidget(self.badge_lbl)
        s4_lay.addLayout(r_header_lay)

        # Player Row: [ ▶ Play ] [ ━━━━━━━━━━━━ Progress Slider ] [ 00:00 / 00:04 ]
        player_lay = QHBoxLayout()
        player_lay.setSpacing(10)

        self.play_pause_btn = QPushButton("▶", sec4_box)
        self.play_pause_btn.setFixedSize(36, 36)
        self.play_pause_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                border: 1px solid #3b82f6;
                border-radius: 18px;
                color: #ffffff;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                border-color: #334155;
                color: #64748b;
            }
        """)
        self.play_pause_btn.setEnabled(False)
        self.play_pause_btn.clicked.connect(self._toggle_playback)
        player_lay.addWidget(self.play_pause_btn)

        self.seek_slider = QSlider(Qt.Horizontal, sec4_box)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #1e2942;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #38bdf8;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 2px solid #38bdf8;
                width: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        player_lay.addWidget(self.seek_slider, stretch=1)

        self.time_lbl = QLabel("00:00 / 00:00", sec4_box)
        self.time_lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: monospace; min-width: 80px;")
        player_lay.addWidget(self.time_lbl)

        s4_lay.addLayout(player_lay)

        # Actions below player: Save to Profile & Export
        action_row = QHBoxLayout()
        action_row.addStretch()

        self.save_char_btn = QPushButton("💾 Save Character Profile", sec4_box)
        self.save_char_btn.setProperty("class", "btn-primary")
        self.save_char_btn.setStyleSheet("font-size: 11px; padding: 5px 14px; font-weight: bold;")
        self.save_char_btn.setEnabled(False)
        self.save_char_btn.clicked.connect(self._save_to_character_profile)
        action_row.addWidget(self.save_char_btn)

        self.export_audio_btn = QPushButton("📤 Download WAV", sec4_box)
        self.export_audio_btn.setProperty("class", "btn-gray")
        self.export_audio_btn.setStyleSheet("font-size: 11px; padding: 5px 12px;")
        self.export_audio_btn.setEnabled(False)
        self.export_audio_btn.clicked.connect(self._export_audio)
        action_row.addWidget(self.export_audio_btn)

        s4_lay.addLayout(action_row)
        c_lay.addWidget(sec4_box)

        scroll.setWidget(card)
        main_lay.addWidget(scroll)

    def _on_form_changed(self):
        if not self._custom_prompt_edited:
            self._build_prompt_from_form()

    def _build_prompt_from_form(self):
        from services.voice_prompt_processor import VoicePromptProcessor
        prompt = VoicePromptProcessor.build_natural_prompt(
            gender=self.gender_combo.currentText(),
            age=self.age_spin.value(),
            voice_type=self.type_combo.currentText(),
            tone=self.tone_combo.currentText(),
            emotion=self.emotion_combo.currentText(),
            style=self.style_combo.currentText(),
            speed=self.speed_combo.currentText().split()[0],
            additional=self.additional_input.text().strip()
        )
        self.prompt_input.setPlainText(prompt)

    def _run_generation(self):
        prompt_text = self.prompt_input.toPlainText().strip()
        speech_text = self.text_input.toPlainText().strip()

        if not speech_text:
            QMessageBox.warning(self, "Warning", "Please enter speech text to synthesize.")
            return

        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("⏳ Generating...")
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.progress_bar.setFormat("5% • Initializing Engine...")
        
        self.badge_lbl.setText("Starting generation...")
        self.badge_lbl.setStyleSheet("color: #38bdf8;")

        char_name = self.name_input.text().strip() or "Dara"
        self._worker = VoiceStudioWorker(prompt_text, speech_text, self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_progress(self, percent: int, msg: str):
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(msg)
        self.badge_lbl.setText(msg)

    def _on_worker_finished(self, out_wav: str, profile):
        import wave
        self.current_audio_path = out_wav
        self.current_profile = profile
        char_name = self.name_input.text().strip() or "Dara"
        self.current_profile.name = char_name

        try:
            with wave.open(out_wav, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                self.audio_duration_sec = frames / float(rate)
        except Exception:
            self.audio_duration_sec = 4.0

        self.badge_lbl.setText(f"✓ Generated • {self.audio_duration_sec:.1f}s • {profile.gender.capitalize()} {profile.age} (Pitch: {profile.pitch_shift:.2f}x)")
        self.badge_lbl.setStyleSheet("color: #10b981; font-weight: bold;")
        
        self.play_pause_btn.setEnabled(True)
        self.save_char_btn.setEnabled(True)
        self.export_audio_btn.setEnabled(True)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("🎙️ GENERATE VOICE 🔊")
        
        # Reset player & start audition
        self._stop_playback()
        self._start_playback()
        self.voice_generated.emit(out_wav, profile)

    def _on_worker_error(self, err_msg: str):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("🎙️ GENERATE VOICE 🔊")
        self.badge_lbl.setText(f"Error: {err_msg}")
        self.badge_lbl.setStyleSheet("color: #ef4444;")
        self.progress_bar.setFormat("Generation Failed ❌")
        QMessageBox.critical(self, "Error", f"Voice generation error: {err_msg}")

    def _toggle_playback(self):
        if self._is_playing:
            self._pause_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            return
        
        try:
            if self._proc and self._proc.poll() is None:
                try: self._proc.terminate()
                except Exception: pass
            
            if sys.platform == "darwin":
                self._proc = subprocess.Popen(["afplay", "-v", "1", self.current_audio_path])
            elif sys.platform.startswith("linux"):
                self._proc = subprocess.Popen(["aplay", self.current_audio_path])

            self._is_playing = True
            self.play_pause_btn.setText("⏸")
            self._timer.start()
        except Exception as e:
            print(f"Playback error: {e}")

    def _pause_playback(self):
        if self._proc and self._proc.poll() is None:
            try: self._proc.terminate()
            except Exception: pass
        self._is_playing = False
        self.play_pause_btn.setText("▶")
        self._timer.stop()

    def _stop_playback(self):
        self._pause_playback()
        self.current_pos_sec = 0.0
        self.seek_slider.setValue(0)
        self._update_time_label()

    def _update_playback_progress(self):
        if not self._is_playing:
            return
        
        if self._proc and self._proc.poll() is not None:
            # Playback finished
            self._stop_playback()
            return

        self.current_pos_sec += 0.1
        if self.audio_duration_sec > 0:
            val = int((self.current_pos_sec / self.audio_duration_sec) * 1000)
            self.seek_slider.setValue(min(1000, val))
        self._update_time_label()

    def _on_seek_moved(self, value: int):
        if self.audio_duration_sec > 0:
            self.current_pos_sec = (value / 1000.0) * self.audio_duration_sec
            self._update_time_label()

    def _update_time_label(self):
        pos_m = int(self.current_pos_sec // 60)
        pos_s = int(self.current_pos_sec % 60)
        dur_m = int(self.audio_duration_sec // 60)
        dur_s = int(self.audio_duration_sec % 60)
        self.time_lbl.setText(f"{pos_m:02d}:{pos_s:02d} / {dur_m:02d}:{dur_s:02d}")

    def _save_to_character_profile(self):
        if not self.current_profile:
            return
        
        from qt_compat import QInputDialog
        from services.character_voice_manager import CharacterVoiceManager
        from services.voxcpm_service import add_custom_voice_preset

        char_name, ok = QInputDialog.getText(self, "Save Character", "Enter Character Name:", QLineEdit.Normal, self.current_profile.name)
        if ok and char_name.strip():
            self.current_profile.name = char_name.strip()
            manager = CharacterVoiceManager()
            manager._save_character(self.current_profile)
            manager._characters_cache[self.current_profile.name] = self.current_profile
            
            preset = manager.get_voxcpm_preset(self.current_profile.name)
            if preset:
                add_custom_voice_preset(self.current_profile.name, preset)
            
            QMessageBox.information(self, "Saved", f"✅ Character '{self.current_profile.name}' saved to Character Profiles & Presets!")

    def _export_audio(self):
        if not self.current_audio_path or not os.path.exists(self.current_audio_path):
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export Synthesized Audio", "ai_voice_studio.wav", "WAV Audio (*.wav);;MP3 Audio (*.mp3)")
        if file_path:
            try:
                import shutil
                shutil.copyfile(self.current_audio_path, file_path)
                QMessageBox.information(self, "Exported", f"✅ Audio exported to:\n{file_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to export: {e}")


class AIVoiceStudioDialog(QDialog):
    """Unified Dialog for AI Voice Studio & Character Designer"""
    def __init__(self, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("🎙️ AI Voice Studio & Character Voice Designer")
        self.setMinimumSize(680, 720)
        self.resize(720, 740)
        self.setStyleSheet("""
            QDialog {
                background-color: #080c16;
                color: #f1f5f9;
                font-family: 'Segoe UI', 'Kantumruy Pro', 'Khmer OS Battambang', sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #1e2942;
                border-radius: 8px;
                background-color: #0a0e1a;
                top: -1px;
            }
            QTabBar::tab {
                background: #080c16;
                color: #94a3b8;
                border: 1px solid #1e2942;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 16px;
                margin-right: 2px;
                font-weight: 600;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #0a0e1a;
                color: #38bdf8;
                border-color: #2563eb;
                border-bottom: 2px solid #38bdf8;
            }
        """)
        
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(12, 12, 12, 12)
        main_lay.setSpacing(10)

        self.tabs = QTabWidget(self)
        
        # Tab 1: AI Voice Studio
        self.studio = AIVoiceStudioWidget(self)
        self.tabs.addTab(self.studio, "🎙️ AI Voice Studio (Prompt → Audio)")

        # Tab 2: Character Profile Designer
        self.designer_container = QWidget()
        d_lay = QVBoxLayout(self.designer_container)
        d_lay.setContentsMargins(8, 8, 8, 8)
        self.editor = VoicePromptEditor(self.designer_container)
        d_lay.addWidget(self.editor, 1)

        d_actions = QHBoxLayout()
        d_actions.addStretch()
        
        save_profile_btn = QPushButton("💾 Save Character Profile", self.designer_container)
        save_profile_btn.setProperty("class", "btn-primary")
        save_profile_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        def _save_designer_profile():
            from services.character_voice_manager import CharacterVoiceManager
            from services.voxcpm_service import add_custom_voice_preset
            
            profile = self.editor.current_profile
            if not profile:
                self.editor._extract_profile()
                profile = self.editor.current_profile

            if profile:
                manager = CharacterVoiceManager()
                manager._save_character(profile)
                manager._characters_cache[profile.name] = profile
                
                preset_dict = manager.get_voxcpm_preset(profile.name)
                if preset_dict:
                    add_custom_voice_preset(profile.name, preset_dict)
                
                QMessageBox.information(
                    self,
                    "Character Saved",
                    f"✅ Character '{profile.name}' has been saved and is ready for dubbing!"
                )
                self.accept()
            else:
                QMessageBox.warning(self, "Warning", "Please provide a valid voice prompt first.")

        save_profile_btn.clicked.connect(_save_designer_profile)
        d_actions.addWidget(save_profile_btn)
        d_lay.addLayout(d_actions)

        self.tabs.addTab(self.designer_container, "🎭 Character Profile Designer")
        self.tabs.setCurrentIndex(initial_tab)

        main_lay.addWidget(self.tabs, 1)

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Close", self)
        close_btn.setProperty("class", "btn-gray")
        close_btn.setStyleSheet("padding: 6px 18px; font-weight: bold;")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        main_lay.addLayout(footer)


# ==================== GEMINI API KEY DIALOG ====================
class GeminiApiKeyDialog(QDialog):
    """
    Dedicated dialog for persistent Google Gemini API Key configuration,
    instant connection testing, and one-click key registration.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔑 Google Gemini API Key - ភាសាខ្មែរ AI Translation")
        self.resize(530, 290)
        self.setStyleSheet("""
            QDialog {
                background-color: #0b0f19;
                color: #e2e8f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            }
        """)
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        # Header Title
        title_lbl = QLabel("🌐 Google Gemini AI Translation API Key", self)
        title_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #38bdf8;")
        lay.addWidget(title_lbl)

        # Description
        desc_lbl = QLabel(
            "បញ្ចូល Gemini API Key ដើម្បីបកប្រែពាក្យសំដី (Speech to Khmer) ទៅជាភាសាខ្មែរនិយាយបែបធម្មជាតិ "
            "(Conversational Spoken Khmer) ពិរោះ និងស័ក្តិសមជាមួយវីដេអូបែប Dubbing:",
            self
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4;")
        lay.addWidget(desc_lbl)

        # Input Box Row
        from utils.config_manager import get_gemini_api_key
        current_key = get_gemini_api_key()

        input_box = QFrame(self)
        input_box.setStyleSheet("background-color: #060911; border: 1px solid #1e2942; border-radius: 8px; padding: 4px;")
        input_lay = QHBoxLayout(input_box)
        input_lay.setContentsMargins(6, 4, 6, 4)
        input_lay.setSpacing(6)

        key_icon = QLabel("🔑", input_box)
        input_lay.addWidget(key_icon)

        self.key_input = QLineEdit(current_key, input_box)
        self.key_input.setPlaceholderText("Paste your Gemini API Key here (e.g. AIzaSy...)")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setStyleSheet("background: transparent; border: none; color: #00e676; font-size: 13px; font-family: monospace;")
        input_lay.addWidget(self.key_input, 1)

        self.toggle_eye_btn = QPushButton("👁", input_box)
        self.toggle_eye_btn.setFixedSize(30, 26)
        self.toggle_eye_btn.setStyleSheet("background-color: #1e2942; color: #ffffff; border: none; border-radius: 4px;")
        self.toggle_eye_btn.clicked.connect(self._toggle_echo)
        input_lay.addWidget(self.toggle_eye_btn)

        lay.addWidget(input_box)

        # Status Label for Test Results
        self.status_lbl = QLabel("", self)
        self.status_lbl.setStyleSheet("font-size: 11px; font-weight: bold;")
        lay.addWidget(self.status_lbl)

        # Get Free Key Link
        link_lbl = QLabel(
            "<a href='https://aistudio.google.com/app/apikey' style='color: #60a5fa; text-decoration: none; font-weight: 600;'>👉 ចុចទីនេះដើម្បីយក Free Gemini API Key (Google AI Studio)</a>",
            self
        )
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setStyleSheet("font-size: 11px;")
        lay.addWidget(link_lbl)

        lay.addStretch()

        # Action Buttons
        btn_lay = QHBoxLayout()
        self.test_btn = QPushButton("⚡ Test Connection", self)
        self.test_btn.setProperty("class", "btn-purple")
        self.test_btn.clicked.connect(self._test_key)
        btn_lay.addWidget(self.test_btn)

        btn_lay.addStretch()

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setProperty("class", "btn-gray")
        cancel_btn.clicked.connect(self.reject)
        btn_lay.addWidget(cancel_btn)

        save_btn = QPushButton("💾 Save API Key", self)
        save_btn.setProperty("class", "btn-primary")
        save_btn.setStyleSheet("font-weight: 700; padding: 6px 18px;")
        save_btn.clicked.connect(self._save_key)
        btn_lay.addWidget(save_btn)

        lay.addLayout(btn_lay)

    def _toggle_echo(self):
        if self.key_input.echoMode() == QLineEdit.Password:
            self.key_input.setEchoMode(QLineEdit.Normal)
            self.toggle_eye_btn.setText("🔒")
        else:
            self.key_input.setEchoMode(QLineEdit.Password)
            self.toggle_eye_btn.setText("👁")

    def _test_key(self):
        key = self.key_input.text().strip()
        if not key:
            self.status_lbl.setText("⚠️ សូមបញ្ចូល API Key សិន!")
            self.status_lbl.setStyleSheet("color: #f59e0b; font-weight: bold;")
            return

        self.status_lbl.setText("⏳ កំពុងតេស្តភ្ជាប់ទៅកាន់ Google Gemini...")
        self.status_lbl.setStyleSheet("color: #38bdf8;")
        QApplication.processEvents()

        from utils.config_manager import test_gemini_api_key
        ok, msg = test_gemini_api_key(key)
        if ok:
            self.status_lbl.setText(msg)
            self.status_lbl.setStyleSheet("color: #00e676; font-weight: bold;")
        else:
            self.status_lbl.setText(msg)
            self.status_lbl.setStyleSheet("color: #ef4444; font-weight: bold;")

    def _save_key(self):
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Warning", "សូមបញ្ចូល API Key មុននឹង Save!")
            return

        from utils.config_manager import save_gemini_api_key
        if save_gemini_api_key(key):
            QMessageBox.information(self, "Success", "🎉 បានរក្សាទុក Gemini API Key រួចរាល់ដោយជោគជ័យ!")
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "មិនអាចរក្សាទុក API Key បានទេ។")


