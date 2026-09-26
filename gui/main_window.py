import os
import sys
import re
import shutil
import subprocess
from pathlib import Path
from qt_compat import (
    Qt, Slot, QThread, Signal, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QLineEdit, QFileDialog, QMessageBox, QGroupBox,
    QSplitter, QFrame, QDoubleSpinBox, QSpinBox, QSlider, QInputDialog, QTabWidget, QMenu, QDialog,
    QApplication, QMimeData, QTimer, QUrl, QKeySequence, QDesktopServices, QShortcut
)

from gui.widgets import (
    VideoPreviewWidget, SubtitleTableWidget, 
    TimelineEditorWidget, VideoEffectsWidget, LogConsoleWidget,
    GeminiApiKeyDialog, PasteSRTDialog
)
from core.dubbing import DubbingWorker
from utils.file_utils import OUTPUT_DIR, get_output_path, get_temp_path
from utils.logger import setup_logger, logger
from utils.config_manager import get_gemini_api_key

def clean_speaker_tag(text: str) -> tuple:
    """
    Parses subtitle text for speaker tags like [ក្មេង], [ស្រី], [ប្រុស], [Child], (ក្មេង), etc.
    Returns: (clean_text, speaker_display, gender, voice_preset)
    """
    raw = (text or "").strip()
    if not raw:
        return "", "👨 ប្រុស", "male", "Khmer Male - Piseth"

    tag_pattern = r'^\s*(?:\[|\()?\s*(ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)\s*(?:\]|\))?\s*[:：\-–—]?\s*'
    match = re.match(tag_pattern, raw, flags=re.IGNORECASE)

    gender = "male"
    spk_display = "👨 ប្រុស"
    voice = "Khmer Male - Piseth"
    clean_text = raw

    if match:
        tag_word = match.group(1).lower()
        clean_text = raw[match.end():].strip()
        
        if any(w in tag_word for w in ['ក្មេង', 'កូន', 'child', 'kid', 'boy', 'girl']):
            gender = "child"
            spk_display = "🧒 ក្មេង"
            voice = "Khmer Child - Boy (Vannak)"
        elif any(w in tag_word for w in ['ស្រី', 'female', 'woman', 'lady']):
            gender = "female"
            spk_display = "👩 ស្រី"
            voice = "Khmer Female - Sreymom"
        elif any(w in tag_word for w in ['ចាស់', 'elder', 'លោកតា', 'លោកយាយ']):
            gender = "elder"
            spk_display = "👵👴 មនុស្សចាស់"
            voice = "Khmer Elder - Male (Grandfather)"
        elif any(w in tag_word for w in ['ប្រុស', 'male', 'man', 'guy']):
            gender = "male"
            spk_display = "👨 ប្រុស"
            voice = "Khmer Male - Piseth"
        elif 'speaker' in tag_word:
            spk_display = match.group(1).title()
            voice = "Khmer Male - Piseth"
    else:
        bracket_match = re.match(r'^\s*\[(.*?)\]\s*(.*)$', raw)
        if bracket_match:
            b_tag = bracket_match.group(1).lower()
            remainder = bracket_match.group(2).strip()
            if any(w in b_tag for w in ['ក្មេង', 'child', 'kid', 'boy', 'girl']):
                gender = "child"
                spk_display = "🧒 ក្មេង"
                voice = "Khmer Child - Boy (Vannak)"
                clean_text = remainder
            elif any(w in b_tag for w in ['ស្រី', 'female', 'woman']):
                gender = "female"
                spk_display = "👩 ស្រី"
                voice = "Khmer Female - Sreymom"
                clean_text = remainder
            elif any(w in b_tag for w in ['ប្រុស', 'male', 'man']):
                gender = "male"
                spk_display = "👨 ប្រុស"
                voice = "Khmer Male - Piseth"
                clean_text = remainder

    if clean_text.startswith('[') and ']' in clean_text[:15]:
        clean_text = re.sub(r'^\s*\[[^\]]+\]\s*', '', clean_text).strip()

    return clean_text, spk_display, gender, voice


class GenerateVoicesWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, segments: list, total_duration: float, voice_name: str = "Khmer Female - Sreymom"):
        super().__init__()
        self.segments = segments
        self.total_duration = total_duration
        self.voice_name = voice_name
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            from core.tts import TextToSpeech
            from core.dialogue_sync import DialogueSyncEngine
            from utils.file_utils import get_temp_path
            import os

            total = len(self.segments)
            if total == 0:
                self.error.emit("គ្មាន Subtitle សម្រាប់សំយោគសំឡេងទេ (No subtitles to synthesize)")
                return

            self.progress.emit(5, f"🔊 កំពុងចាប់ផ្តើមសំយោគសំឡេង {total} ឃ្លា (Parallel Workers=3)...")

            # Ensure every segment has a voice
            for seg in self.segments:
                if not seg.get("voice"):
                    char = str(seg.get("character") or "").lower()
                    g = str(seg.get("gender") or "").lower()
                    if "ស្រី" in char or g == "female":
                        seg["voice"] = "Khmer Female - Sreymom"
                    elif "ក្មេង" in char or g == "child":
                        seg["voice"] = "Khmer Child - Boy (Vannak)"
                    else:
                        seg["voice"] = "Khmer Male - Piseth"

            tts_engine = TextToSpeech(voice_name=self.voice_name)

            def _tts_cb(completed, tot, info):
                pct = 5 + int(80 * (completed / float(max(1, tot))))
                self.progress.emit(pct, f"🔊 TTS: កំពុងសំយោគសំឡេង... ({completed}/{tot})")

            raw_audio_paths = tts_engine.generate_all_segments(
                self.segments,
                progress_callback=_tts_cb,
                max_workers=3,
                is_cancelled_fn=lambda: self._is_cancelled
            )

            if self._is_cancelled:
                self.error.emit("ដំណើរការសំយោគសំឡេងត្រូវបានផ្អាក")
                return

            self.progress.emit(88, "⏱ កំពុងផ្គុំ និងតម្រឹមសំឡេងតាម Timeline (Dialogue Sync Engine)...")
            sync_engine = DialogueSyncEngine()
            master_khmer_wav = get_temp_path("master_khmer_voice.wav")

            # Remove stale master if exists
            if os.path.exists(master_khmer_wav):
                try:
                    os.remove(master_khmer_wav)
                except Exception:
                    pass

            out_path = sync_engine.sync_dialogue_timeline(
                segments=self.segments,
                seg_audio_paths=raw_audio_paths,
                total_duration_sec=self.total_duration,
                output_master_path=master_khmer_wav
            )

            if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
                self.error.emit("ការផ្គុំសំឡេងបរាជ័យ (Audio Sync Failed)")
                return

            self.progress.emit(100, "✅ សំយោគសំឡេងជោគជ័យ!")
            self.finished.emit(out_path)
        except Exception as e:
            self.error.emit(f"កំហុសក្នុងការសំយោគសំឡេង: {str(e)}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎬 AI Video Dubber - Ultimate Edition")
        self.resize(1380, 920)
        self.setMinimumSize(1080, 750)
        
        self.worker = None
        self.transcribe_worker = None
        self.translate_worker = None
        self.react_worker = None
        self.video_path = None
        self.output_dir = str(OUTPUT_DIR)
        self.transcribed_segments = []  # Store segments after Transcription
        self.extracted_mp3_path = None
        self.mp3_worker = None
        self.current_project_file = None
        self.voice_worker = None
        self.setAcceptDrops(True)
        
        self._init_ui()
        self._load_stylesheet()
        
        # Thread-safe logger
        setup_logger(callback=self.log_console.append_log)

        # Background watcher disabled to prevent unexpected subtitle collisions
        # User imports explicitly via '📋 Paste SRT' button or Cmd+V
        # self._setup_web_studio_watcher()

        # Global Shortcut for Cmd+V / Ctrl+V to paste Subtitles anywhere
        self.paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        self.paste_shortcut.activated.connect(self._on_paste_sub_button_clicked)

        # Global Shortcuts for Save & Open Project (Cmd+S / Ctrl+S, Cmd+O / Ctrl+O)
        self.save_shortcut = QShortcut(QKeySequence.Save, self)
        self.save_shortcut.activated.connect(lambda: self._save_project())

        self.open_shortcut = QShortcut(QKeySequence.Open, self)
        self.open_shortcut.activated.connect(lambda: self._open_project())

    def _load_stylesheet(self):
        qss_path = Path(__file__).resolve().parent / "styles.qss"
        if qss_path.exists():
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(8, 8, 8, 8)

        # ---------------- 1. TOP HEADER & GUIDED WORKFLOW BAR ----------------
        top_header = QFrame(self)
        top_header.setObjectName("topHeader")
        th_lay = QHBoxLayout(top_header)
        th_lay.setContentsMargins(10, 6, 10, 6)
        th_lay.setSpacing(10)

        # App Logo & Title (Left)
        title_lbl = QLabel("🎬 Khmer Dubber Studio", self)
        title_lbl.setObjectName("titleLabel")
        ver_badge = QLabel(" v3.0 Pro", self)
        ver_badge.setStyleSheet("background-color: #1e293b; color: #38bdf8; font-size: 10px; font-weight: bold; border-radius: 4px; padding: 2px 6px;")
        th_lay.addWidget(title_lbl)
        th_lay.addWidget(ver_badge)

        sep1 = QFrame(self)
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("background-color: #1e2942; max-height: 22px;")
        th_lay.addWidget(sep1)

        # 4-STEP STUDIO WORKFLOW BAR (Center)
        workflow_bar = QFrame(self)
        workflow_bar.setObjectName("workflowBar")
        wf_lay = QHBoxLayout(workflow_bar)
        wf_lay.setContentsMargins(6, 3, 6, 3)
        wf_lay.setSpacing(6)

        # Step 1: Open Video & Copy MP3
        b1 = QLabel("1", self)
        b1.setProperty("class", "step-badge")
        self.load_vid_btn = QPushButton("📂 Open Video", self)
        self.load_vid_btn.setProperty("class", "btn-primary")
        self.load_vid_btn.clicked.connect(self._browse_video)

        self.copy_mp3_btn = QPushButton("📋 Copy MP3", self)
        self.copy_mp3_btn.setProperty("class", "btn-mp3")
        self.copy_mp3_btn.setToolTip("Upload video to auto-generate MP3. Click to copy MP3 file to clipboard!")
        self.copy_mp3_btn.setEnabled(False)
        self.copy_mp3_btn.clicked.connect(self._copy_mp3_to_clipboard)
        self.copy_mp3_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.copy_mp3_btn.customContextMenuRequested.connect(self._show_mp3_context_menu)

        wf_lay.addWidget(b1)
        wf_lay.addWidget(self.load_vid_btn)
        wf_lay.addWidget(self.copy_mp3_btn)

        # Divider
        w_sep1 = QFrame(self)
        w_sep1.setFrameShape(QFrame.VLine)
        w_sep1.setStyleSheet("background-color: #1e2942; max-height: 18px;")
        wf_lay.addWidget(w_sep1)

        # Step 2: AI Translate & Paste SRT
        b2 = QLabel("2", self)
        b2.setProperty("class", "step-badge")

        self.open_web_ui_btn = QPushButton("🌐 Web Studio", self)
        self.open_web_ui_btn.setProperty("class", "btn-gray")
        self.open_web_ui_btn.setToolTip("បើក React Web Studio (http://localhost:3000) ក្នុង Browser")
        self.open_web_ui_btn.clicked.connect(self._open_web_studio)

        self.paste_sub_top_btn = QPushButton("📋 Paste SRT", self)
        self.paste_sub_top_btn.setProperty("class", "btn-purple")
        self.paste_sub_top_btn.setToolTip("បើកប្រអប់ Paste SRT ដើម្បីបិទភ្ជាប់ Subtitle ចូល Desktop Studio (Cmd+V)")
        self.paste_sub_top_btn.clicked.connect(self._on_paste_sub_button_clicked)
        self.paste_sub_btn = self.paste_sub_top_btn  # Single unified reference

        wf_lay.addWidget(b2)
        wf_lay.addWidget(self.open_web_ui_btn)
        wf_lay.addWidget(self.paste_sub_top_btn)

        th_lay.addWidget(workflow_bar)

        # Tools Menu & Settings (Right)
        self.save_proj_btn = QPushButton("💾 Save", self)
        self.save_proj_btn.setProperty("class", "btn-gray")
        self.save_proj_btn.setToolTip("រក្សាទុកគម្រោង (Save Project .vproj) - Cmd+S")
        self.save_proj_btn.clicked.connect(lambda: self._save_project())

        self.open_proj_btn = QPushButton("📂 Open", self)
        self.open_proj_btn.setProperty("class", "btn-gray")
        self.open_proj_btn.setToolTip("បើកគម្រោង (Open Project .vproj) - Cmd+O")
        self.open_proj_btn.clicked.connect(lambda: self._open_project())

        self.tools_menu_btn = QPushButton("🛠 Tools ▾", self)
        self.tools_menu_btn.setProperty("class", "btn-gray")
        tools_menu = QMenu(self)
        tools_menu.addAction("💾 Save Project (Cmd+S)", lambda: self._save_project())
        tools_menu.addAction("📂 Open Project (Cmd+O)", lambda: self._open_project())
        tools_menu.addAction("🔄 Restore Auto-saved Project", self._restore_autosave)
        tools_menu.addSeparator()
        tools_menu.addAction("🔊 Generate Voices (Dubbing Preview)", self._generate_all_voices)
        tools_menu.addAction("📁 Open Video", self._browse_video)
        tools_menu.addAction("⚡ Run React Engine Direct", self._run_transcription_only)
        tools_menu.addAction("🔑 Configure Gemini API Key", self._open_gemini_settings)
        tools_menu.addAction("🧹 Clear Cache & Temp Files", self._clear_temp_cache)
        self.tools_menu_btn.setMenu(tools_menu)

        self.settings_btn = QPushButton("⚙ Settings", self)
        self.settings_btn.setProperty("class", "btn-gray")
        self.settings_btn.clicked.connect(self._open_settings)

        th_lay.addWidget(self.save_proj_btn)
        th_lay.addWidget(self.open_proj_btn)
        th_lay.addWidget(self.tools_menu_btn)
        th_lay.addWidget(self.settings_btn)

        main_layout.addWidget(top_header)

        # ---------------- 2. MAIN SPLITTER (LEFT / RIGHT) ----------------
        main_splitter = QSplitter(Qt.Horizontal, self)

        # LEFT COLUMN (Video Preview Player)
        left_widget = QWidget(self)
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        self.video_preview = VideoPreviewWidget(self)
        left_lay.addWidget(self.video_preview, stretch=1)

        main_splitter.addWidget(left_widget)

        # RIGHT COLUMN (Subtitle Table, Timeline directly below, Video Effects)
        right_widget = QWidget(self)
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        right_splitter = QSplitter(Qt.Vertical, self)

        # 1. Subtitle Table (Top)
        self.subtitle_table = SubtitleTableWidget(self)
        right_splitter.addWidget(self.subtitle_table)

        # 2. Timeline Editor (Directly below Subtitle Table)
        self.timeline_editor = TimelineEditorWidget(self)
        right_splitter.addWidget(self.timeline_editor)

        # Connect Video Playhead indicator to Timeline Editor and interactive Timeline seeking
        self.video_preview.playhead_moved.connect(self.timeline_editor.set_playhead_position)
        if hasattr(self.timeline_editor, 'waveform_canvas'):
            self.timeline_editor.waveform_canvas.seek_requested.connect(self.video_preview.seek_to_time_sec)
        
        # Connect Subtitle Table row click to Video Preview seeking
        self.subtitle_table.seek_requested.connect(self.video_preview.seek_to_time_sec)
        self.subtitle_table.generate_voices_requested.connect(self._generate_all_voices)

        # 3. Video Effects (Bottom)
        self.video_effects = VideoEffectsWidget(self)
        self.video_effects.blur_toggled.connect(self._on_blur_toggled)
        self.video_effects.blur_intensity_changed.connect(self._on_blur_intensity_changed)
        self.video_effects.reset_blur_requested.connect(self._on_reset_blur_requested)
        self.video_effects.text_toggled.connect(self._on_text_toggled)
        self.video_effects.text_updated.connect(self._on_text_updated)
        self.video_effects.text_position_changed.connect(self._on_text_position_changed)
        self.video_effects.logo_toggled.connect(self._on_logo_toggled)
        self.video_effects.logo_updated.connect(self._on_logo_updated)
        self.video_effects.burn_subtitle_toggled.connect(self._on_burn_subtitle_toggled)
        self.video_effects.burn_subtitle_updated.connect(self._on_burn_subtitle_updated)
        
        self.video_preview.text_moved.connect(self.video_effects.update_text_position_spinboxes)
        self.video_preview.logo_moved.connect(self.video_effects.update_logo_spinboxes)
        
        right_splitter.addWidget(self.video_effects)
        right_splitter.setSizes([480, 140, 110])

        right_lay.addWidget(right_splitter)

        main_splitter.addWidget(right_widget)
        main_splitter.setSizes([420, 960])

        main_layout.addWidget(main_splitter, stretch=1)

        # ---------------- 3. UNIFIED STUDIO BOTTOM FOOTER & EXPORT TOOLBAR ----------------
        bot_bar = QFrame(self)
        bot_bar.setStyleSheet("""
            QFrame {
                background-color: #0c111e;
                border: 1px solid #1a233a;
                border-radius: 8px;
                padding: 4px 8px;
            }
        """)
        bot_lay = QHBoxLayout(bot_bar)
        bot_lay.setContentsMargins(6, 4, 6, 4)
        bot_lay.setSpacing(8)

        # SRT Subtitles Group (Left)
        # Subtitles Export Group (Left)
        self.export_srt_btn = QPushButton("📤 Export SRT", self)
        self.export_srt_btn.setProperty("class", "btn-gray")
        self.export_srt_btn.setToolTip("រក្សាទុក Subtitle ជា File .SRT")
        self.export_srt_btn.clicked.connect(self._export_srt)

        bot_lay.addWidget(self.export_srt_btn)

        sep2 = QFrame(self)
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("background-color: #1e2942; max-height: 22px;")
        bot_lay.addWidget(sep2)

        # Output Target Folder (Middle)
        out_dir_lbl = QLabel("📁 Output:", self)
        out_dir_lbl.setStyleSheet("font-weight: 700; color: #94a3b8; font-size: 11px;")
        
        self.output_path_input = QLineEdit(str(self.output_dir), self)
        self.output_path_input.setReadOnly(True)
        self.output_path_input.setMinimumWidth(200)
        self.output_path_input.setStyleSheet("background-color: #080c16; border: 1px solid #1e2942; color: #f1f5f9; font-size: 11px; padding: 4px 8px;")
        
        self.select_output_dir_btn = QPushButton("📂 Browse...", self)
        self.select_output_dir_btn.setProperty("class", "btn-gray")
        self.select_output_dir_btn.clicked.connect(self._browse_output_dir)
        
        bot_lay.addWidget(out_dir_lbl)
        bot_lay.addWidget(self.output_path_input, stretch=1)
        bot_lay.addWidget(self.select_output_dir_btn)

        # Background Music Volume (BGM)
        bgm_lbl = QLabel("🎶 BGM:", self)
        bgm_lbl.setStyleSheet("font-weight: 700; color: #38bdf8; font-size: 11px;")
        self.bgm_vol_spin = QSpinBox(self)
        self.bgm_vol_spin.setRange(0, 100)
        self.bgm_vol_spin.setValue(30)
        self.bgm_vol_spin.setSuffix("%")
        self.bgm_vol_spin.setToolTip("Background Music Volume level (0% = Mute, 30% = Balanced background)")
        self.bgm_vol_spin.setStyleSheet("background-color: #080c16; border: 1px solid #1e2942; color: #38bdf8; font-weight: bold; font-size: 11px; padding: 3px 6px;")
        bot_lay.addWidget(bgm_lbl)
        bot_lay.addWidget(self.bgm_vol_spin)
        self.bgm_vol_spin.valueChanged.connect(self._on_bgm_volume_changed)

        sep3 = QFrame(self)
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet("background-color: #1e2942; max-height: 22px;")
        bot_lay.addWidget(sep3)

        # Export Action Buttons (Right)
        self.export_mp3_btn = QPushButton("🎵 Export MP3", self)
        self.export_mp3_btn.setProperty("class", "btn-gold")
        self.export_mp3_btn.clicked.connect(self._export_mp3)

        self.export_video_btn = QPushButton("🎬 EXPORT FINAL VIDEO", self)
        self.export_video_btn.setProperty("class", "btn-primary")
        self.export_video_btn.setStyleSheet("font-weight: 800; padding: 6px 18px;")
        self.export_video_btn.clicked.connect(self._export_final_video)

        self.cancel_export_btn = QPushButton("⛔ Cancel", self)
        self.cancel_export_btn.setProperty("class", "btn-red")
        self.cancel_export_btn.clicked.connect(self._cancel_export)

        bot_lay.addWidget(self.export_mp3_btn)
        bot_lay.addWidget(self.export_video_btn)
        bot_lay.addWidget(self.cancel_export_btn)

        main_layout.addWidget(bot_bar)

        # Pipeline Stepper & Progress
        stepper_box = QFrame(self)
        stepper_box.setStyleSheet("""
            QFrame {
                background-color: #090d18;
                border: 1px solid #161f36;
                border-radius: 6px;
                padding: 1px 4px;
            }
        """)
        stepper_lay = QHBoxLayout(stepper_box)
        stepper_lay.setContentsMargins(4, 2, 4, 2)
        stepper_lay.setSpacing(6)

        self.step_labels = []
        steps_info = [
            ("audio", "1. 🎵 Audio"),
            ("stt", "2. 🎙 STT"),
            ("trans", "3. 🌐 Translate"),
            ("tts", "4. 🔊 Parallel TTS"),
            ("sync", "5. ⏱ Sync"),
            ("export", "6. 🎬 Export")
        ]
        for key, text in steps_info:
            lbl = QLabel(text, self)
            lbl.setStyleSheet("color: #64748b; background-color: #0c111e; border: 1px solid #1e2942; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 600;")
            stepper_lay.addWidget(lbl)
            self.step_labels.append((key, lbl, text))

        stepper_lay.addStretch()

        prog_lay = QHBoxLayout()
        self.status_lbl = QLabel("Ready.", self)
        self.status_lbl.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 11px;")
        
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setValue(0)

        prog_lay.addWidget(self.status_lbl)
        prog_lay.addWidget(self.progress_bar, stretch=1)

        main_layout.addWidget(stepper_box)
        main_layout.addLayout(prog_lay)

        # Log console drawer
        self.log_console = LogConsoleWidget(self)
        self.log_console.setFixedHeight(75)
        main_layout.addWidget(self.log_console)

    def _set_processing_state(self, is_running: bool, status_msg: str = ""):
        """Enable or disable workflow buttons to prevent race conditions and multiple triggers."""
        buttons_to_toggle = [
            getattr(self, 'load_vid_btn', None),
            getattr(self, 'auto_trans_btn', None),
            getattr(self, 'transcribe_btn', None),
            getattr(self, 'translate_btn', None),
            getattr(self, 'ai_voice_studio_btn', None),
            getattr(self, 'top_export_btn', None),
            getattr(self, 'one_click_dub_btn', None),
            getattr(self, 'export_video_btn', None),
            getattr(self, 'export_mp3_btn', None),
            getattr(self, 'import_srt_btn', None),
            getattr(self, 'import_web_sub_btn', None),
            getattr(self, 'tools_menu_btn', None),
        ]
        for btn in buttons_to_toggle:
            if btn is not None:
                btn.setEnabled(not is_running)

        if hasattr(self, 'cancel_export_btn'):
            self.cancel_export_btn.setEnabled(is_running)

        if status_msg:
            self.status_lbl.setText(status_msg)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                fpath = url.toLocalFile()
                if fpath.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                fpath = url.toLocalFile()
                if fpath.lower().endswith(('.mp4', '.mkv', '.avi', '.mov', '.webm')):
                    self._load_video_file(fpath)
                    event.acceptProposedAction()
                    return

    def keyPressEvent(self, event):
        # Support Cmd+V / Ctrl+V to paste Subtitle text or SRT anywhere in Desktop Studio
        if (event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)) and event.key() == Qt.Key_V:
            clipboard = QApplication.clipboard()
            text = (clipboard.text() or "").strip()
            if text and ("-->" in text or text.startswith("[") or text.startswith("{")):
                if self._paste_subtitles_from_clipboard(text):
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _paste_subtitles_from_clipboard(self, text: str) -> bool:
        """Parse pasted SRT or JSON subtitles from clipboard and populate timeline/table."""
        segs = []
        if text.startswith("[") or text.startswith("{"):
            try:
                import json
                raw = json.loads(text)
                raw_segs = raw if isinstance(raw, list) else raw.get("segments", [])
                for s in raw_segs:
                    st = float(s.get("startSeconds", s.get("start", 0.0)))
                    et = float(s.get("endSeconds", s.get("end", st + 2.0)))
                    if et <= st: et = st + 2.0
                    orig = (s.get("sourceText") or s.get("original_text") or "").strip()
                    khmer = (s.get("translatedText") or s.get("khmer_text") or orig).strip()

                    clean_khmer, spk, gender, voice = clean_speaker_tag(khmer)
                    clean_orig, _, _, _ = clean_speaker_tag(orig)

                    raw_gender = (s.get("gender") or "").lower().strip()
                    orig_spk = str(s.get("speaker") or "").lower()
                    if raw_gender == "child" or any(w in orig_spk for w in ['child', 'kid', 'boy', 'baby', 'ក្មេង']):
                        gender = "child"
                        spk = "🧒 ក្មេង"
                        voice = "Khmer Child - Boy (Vannak)"
                    elif raw_gender == "female" or any(w in orig_spk for w in ['female', 'woman', 'girl', 'ស្រី']):
                        gender = "female"
                        spk = "👩 ស្រី"
                        voice = "Khmer Female - Sreymom"
                    elif raw_gender == "elder" or any(w in orig_spk for w in ['elder', 'ចាស់', 'យាយ', 'តា']):
                        gender = "elder"
                        spk = "👵👴 មនុស្សចាស់"
                        voice = "Khmer Elder - Male (Grandfather)"

                    persona = s.get("persona") or s.get("character") or spk
                    if persona not in PERSONA_CHOICES:
                        if gender == "child":
                            persona = "👦 Boy / Child"
                        elif gender == "female":
                            persona = "👩 Female Adult"
                        elif gender == "elder":
                            persona = "👴 Elderly Male"
                        else:
                            persona = "👨 Male Adult"
                    emotion = s.get("emotion") or "😐 Neutral"
                    style = s.get("speaking_style") or s.get("style") or "Normal"
                    voice = s.get("voice_id") or s.get("voice") or voice

                    segs.append({
                        "id": str(s.get("id", len(segs) + 1)),
                        "start": round(st, 2),
                        "end": round(et, 2),
                        "original_text": clean_orig or clean_khmer,
                        "khmer_text": clean_khmer,
                        "speaker": spk,
                        "speaker_id": s.get("speaker_id") or s.get("speakerId") or f"speaker_{1 + (len(segs) % 2):02d}",
                        "character": persona,
                        "persona": persona,
                        "emotion": emotion,
                        "speaking_style": style,
                        "gender": gender,
                        "voice": voice,
                        "voice_id": voice
                    })
            except Exception as e:
                self.log_console.append_log(f"⚠️ JSON clipboard parse error: {e}")

        if not segs and "-->" in text:
            try:
                from core.srt_translator import SRTTranslator
                st_trans = SRTTranslator()
                sub_segs = st_trans.parse_srt(text)
                for s in sub_segs:
                    clean_txt, spk, gender, voice = clean_speaker_tag(s.text)

                    # 1. If s.speaker was identified by SRTTranslator from prefix tags, prioritize it
                    if s.speaker:
                        s_spk = s.speaker.lower()
                        if any(w in s_spk for w in ['ក្មេង', 'child', 'kid', 'boy', 'baby', 'កូន']):
                            gender = "child"
                            spk = "🧒 ក្មេង"
                            voice = "Khmer Child - Boy (Vannak)"
                        elif any(w in s_spk for w in ['ស្រី', 'female', 'woman', 'girl', 'lady']):
                            gender = "female"
                            spk = "👩 ស្រី"
                            voice = "Khmer Female - Sreymom"
                        elif any(w in s_spk for w in ['ចាស់', 'elder', 'លោកតា', 'លោកយាយ']):
                            gender = "elder"
                            spk = "👵👴 មនុស្សចាស់"
                            voice = "Khmer Elder - Male (Grandfather)"
                        elif any(w in s_spk for w in ['ប្រុស', 'male', 'man', 'guy']):
                            gender = "male"
                            spk = "👨 ប្រុស"
                            voice = "Khmer Male - Piseth"

                    # 2. Failsafe: check if clean_txt or s.text still has prefix tags
                    combined_check = f"{clean_txt} {getattr(s, 'text', '')}".lower()
                    if spk == "👨 ប្រុស" and not (s.speaker and 'ប្រុស' in s.speaker):
                        if any(w in combined_check[:30] for w in ['[ក្មេង]', '(ក្មេង)', 'ក្មេង:', '[child]']):
                            gender = "child"
                            spk = "🧒 ក្មេង"
                            voice = "Khmer Child - Boy (Vannak)"
                        elif any(w in combined_check[:30] for w in ['[ស្រី]', '(ស្រី)', 'ស្រី:', '[female]']):
                            gender = "female"
                            spk = "👩 ស្រី"
                            voice = "Khmer Female - Sreymom"

                    matched_persona = "👦 Boy / Child" if gender == "child" else "👩 Female Adult" if gender == "female" else "👴 Elderly Male" if gender == "elder" else "👨 Male Adult"
                    segs.append({
                        "id": str(len(segs) + 1),
                        "start": s.start_seconds,
                        "end": s.end_seconds,
                        "original_text": clean_txt,
                        "khmer_text": clean_txt,
                        "speaker": spk,
                        "speaker_id": f"speaker_{1 + (len(segs) % 2):02d}",
                        "character": matched_persona,
                        "persona": matched_persona,
                        "emotion": "😐 Neutral",
                        "speaking_style": "Normal",
                        "gender": gender,
                        "voice": voice,
                        "voice_id": voice
                    })
            except Exception as e:
                self.log_console.append_log(f"⚠️ SRT clipboard parse error: {e}")

        if segs:
            self.subtitle_table.set_segments(segs)
            self.timeline_editor.set_segments(segs)
            self.video_preview.set_timeline_segments(segs)
            self.transcribed_segments = segs
            self.log_console.append_log(f"📋 [Clipboard Paste] Successfully pasted {len(segs)} segments into Desktop Studio!")
            self.status_lbl.setText(f"📋 Pasted {len(segs)} segments from Clipboard!")
            self._auto_save_project()
            QMessageBox.information(
                self,
                "បិទភ្ជាប់បានជោគជ័យ",
                f"✅ បានបិទភ្ជាប់ (Paste) Subtitles ចំនួន {len(segs)} segments ពី Clipboard ដោយជោគជ័យ!\nលោកអ្នកអាចចុច '🎙️ Export Dubbed Video' ដើម្បីបញ្ចូលសំឡេងបានភ្លាមៗ។"
            )
            return True
        return False

    def _on_paste_sub_button_clicked(self):
        """Action when user clicks '📋 Paste SRT' button or presses Cmd+V."""
        clipboard = QApplication.clipboard()
        text = (clipboard.text() or "").strip()
        dialog = PasteSRTDialog(self, initial_text=text)
        dialog.subtitles_applied.connect(self._paste_subtitles_from_clipboard)
        dialog.exec_()

    def _browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "", "Video Files (*.mp4 *.mkv *.avi *.mov *.webm)"
        )
        if file_path:
            self._load_video_file(file_path)

    def _load_video_file(self, file_path: str, clear_segments: bool = True):
        from utils.file_utils import ensure_accessible_video_file, get_temp_path
        if clear_segments:
            # Remove stale dubbed track to avoid audio collision across sessions
            stale_khmer_wav = get_temp_path("master_khmer_voice.wav")
            if os.path.exists(stale_khmer_wav):
                try:
                    os.remove(stale_khmer_wav)
                except Exception:
                    pass

        safe_file_path = ensure_accessible_video_file(file_path)
        self.video_path = safe_file_path

        # Reset preview audio track selector to original video audio
        if hasattr(self.video_preview, 'audio_track_combo'):
            self.video_preview.audio_track_combo.blockSignals(True)
            self.video_preview.audio_track_combo.setCurrentIndex(0)
            self.video_preview.audio_track_combo.blockSignals(False)

        if clear_segments:
            # Clear any leftover segments from previous project to prevent collision
            self.transcribed_segments = []
            self.subtitle_table.set_segments([])
            self.timeline_editor.set_segments([])

        success = self.video_preview.set_video_path(safe_file_path)
        if not success:
            base_name = os.path.basename(file_path)
            cached_path = get_temp_path(f"safe_input_{base_name}")
            if os.path.exists(cached_path) and cached_path != safe_file_path:
                safe_file_path = cached_path
                self.video_path = safe_file_path
                success = self.video_preview.set_video_path(safe_file_path)

        if not success:
            self.status_lbl.setText("❌ Error loading video")
            self.log_console.append_log(f"❌ Failed to load video: {file_path}")
            QMessageBox.warning(
                self, "Video Load Warning",
                f"មិនអាចបើកវីដេអូបានទេ:\n{file_path}\n\n"
                "មូលហេតុ៖ ប្រព័ន្ធ macOS មិនអនុញ្ញាតឱ្យបើក File ពីក្រៅ Workspace (Desktop/Downloads) ដោយសារសិទ្ធិ (Permission Denied)។\n\n"
                "ដំណោះស្រាយ៖ សូម Copy វីដេអូនោះមកដាក់ក្នុង Folder គម្រោង 'vide ai' រួចបើកម្តងទៀត។"
            )
            return

        self.status_lbl.setText(f"Loaded: {os.path.basename(file_path)}")
        self.log_console.append_log(f"📹 Loaded video: {file_path}")

        # AUTOMATICALLY GENERATE MP3 AUDIO IMMEDIATELY UPON UPLOAD
        self._generate_mp3_on_upload(safe_file_path)

    def _generate_mp3_on_upload(self, video_path: str):
        """Automatically extract high-quality stereo MP3 audio from the uploaded video in background."""
        from utils.file_utils import generate_unique_filename
        out_mp3 = generate_unique_filename(video_path, prefix="audio", extension=".mp3", custom_dir=self.output_dir)
        
        self.extracted_mp3_path = None
        self.copy_mp3_btn.setEnabled(False)
        self.copy_mp3_btn.setText("⏳ Generating MP3...")
        if hasattr(self, 'copy_mp3_btn_bot'):
            self.copy_mp3_btn_bot.setEnabled(False)
            self.copy_mp3_btn_bot.setText("⏳ Generating MP3...")
        
        self.status_lbl.setText("🎵 Generating MP3 audio...")
        self.log_console.append_log(f"🎵 [Auto-MP3] Extracting high-quality MP3 from: {os.path.basename(video_path)}...")

        class MP3Worker(QThread):
            finished = Signal(str)
            error = Signal(str)

            def __init__(self, in_vid, out_audio):
                super().__init__()
                self.in_vid = in_vid
                self.out_audio = out_audio
                self._cancelled = False

            def cancel(self):
                self._cancelled = True

            def run(self):
                try:
                    import subprocess
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", self.in_vid,
                        "-vn",
                        "-acodec", "libmp3lame",
                        "-q:a", "2",
                        self.out_audio
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if self._cancelled:
                        return
                    if res.returncode == 0 and os.path.exists(self.out_audio):
                        self.finished.emit(self.out_audio)
                    else:
                        self.error.emit(res.stderr or "FFmpeg error")
                except Exception as e:
                    self.error.emit(str(e))

        if getattr(self, 'mp3_worker', None) and self.mp3_worker.isRunning():
            try:
                self.mp3_worker.cancel()
                self.mp3_worker.quit()
                self.mp3_worker.wait(200)
            except Exception:
                pass

        self.mp3_worker = MP3Worker(video_path, out_mp3)
        self.mp3_worker.finished.connect(self._on_mp3_generated)
        self.mp3_worker.error.connect(lambda err: (
            self.log_console.append_log(f"⚠️ [Auto-MP3] Extraction error: {err}"),
            self.copy_mp3_btn.setText("📋 Copy MP3"),
            self.status_lbl.setText("⚠️ MP3 extraction issue")
        ))
        self.mp3_worker.start()

    def _on_mp3_generated(self, mp3_path: str):
        self.extracted_mp3_path = mp3_path
        size_mb = (os.path.getsize(mp3_path) / (1024.0 * 1024.0)) if os.path.exists(mp3_path) else 0.0
        
        self.copy_mp3_btn.setEnabled(True)
        self.copy_mp3_btn.setText("📋 Copy MP3")
        self.copy_mp3_btn.setToolTip(f"MP3 Ready ({size_mb:.1f} MB)\n{mp3_path}\nClick to copy MP3 file to clipboard!")
        
        if hasattr(self, 'copy_mp3_btn_bot'):
            self.copy_mp3_btn_bot.setEnabled(True)
            self.copy_mp3_btn_bot.setText("📋 Copy MP3")
            self.copy_mp3_btn_bot.setToolTip(f"MP3 Ready ({size_mb:.1f} MB)\n{mp3_path}\nClick to copy MP3 file to clipboard!")

        self.status_lbl.setText(f"✅ Video & MP3 Ready: {os.path.basename(mp3_path)}")
        self.log_console.append_log(f"✅ [Auto-MP3] Generated MP3: {mp3_path} ({size_mb:.1f} MB)")
        self.log_console.append_log("📋 [Auto-MP3] Click '📋 Copy MP3' to paste this audio file into Finder or any application!")

    def _copy_mp3_to_clipboard(self):
        """Copy the generated MP3 file and path to clipboard for Finder pasting or external use."""
        if not hasattr(self, 'extracted_mp3_path') or not self.extracted_mp3_path or not os.path.exists(self.extracted_mp3_path):
            QMessageBox.warning(self, "No MP3", "មិនទាន់មាន File MP3 នៅឡើយទេ។ សូម Upload Video ជាមុនសិន។")
            return

        mp3_path = os.path.abspath(self.extracted_mp3_path)
        clipboard = QApplication.clipboard()
        mime_data = QMimeData()
        # 1. File URL (for macOS Finder Cmd+V paste or dropping into Telegram/Premiere)
        mime_data.setUrls([QUrl.fromLocalFile(mp3_path)])
        # 2. Text path (for pasting in text editors, browser, or terminal)
        mime_data.setText(mp3_path)
        clipboard.setMimeData(mime_data)

        # Visual feedback on buttons
        self.copy_mp3_btn.setText("✅ Copied!")
        if hasattr(self, 'copy_mp3_btn_bot'):
            self.copy_mp3_btn_bot.setText("✅ Copied!")
        QTimer.singleShot(2500, lambda: (
            getattr(self, 'copy_mp3_btn', None) and self.copy_mp3_btn.setText("📋 Copy MP3"),
            getattr(self, 'copy_mp3_btn_bot', None) and self.copy_mp3_btn_bot.setText("📋 Copy MP3")
        ))

        self.log_console.append_log(f"📋 [Clipboard] Copied MP3 to clipboard: {os.path.basename(mp3_path)}")
        self.status_lbl.setText(f"📋 Copied MP3: {os.path.basename(mp3_path)} (Paste anywhere via Cmd+V)")

    def _show_mp3_context_menu(self, pos):
        """Right-click context menu for MP3 actions."""
        if not hasattr(self, 'extracted_mp3_path') or not self.extracted_mp3_path or not os.path.exists(self.extracted_mp3_path):
            return
        sender = self.sender()
        menu = QMenu(self)
        menu.addAction("📋 Copy MP3 File (Paste into Finder / Apps)", self._copy_mp3_to_clipboard)
        menu.addAction("📝 Copy File Path", self._copy_mp3_path_only)
        menu.addAction("📂 Reveal in Finder", self._reveal_mp3_in_finder)
        menu.addAction("▶️ Play MP3 Audio", self._play_extracted_mp3)
        menu.exec_(sender.mapToGlobal(pos))

    def _copy_mp3_path_only(self):
        if hasattr(self, 'extracted_mp3_path') and self.extracted_mp3_path:
            QApplication.clipboard().setText(os.path.abspath(self.extracted_mp3_path))
            self.log_console.append_log(f"📝 Copied MP3 file path to clipboard: {self.extracted_mp3_path}")
            self.status_lbl.setText("📝 Copied MP3 path to clipboard!")

    def _reveal_mp3_in_finder(self):
        if hasattr(self, 'extracted_mp3_path') and self.extracted_mp3_path and os.path.exists(self.extracted_mp3_path):
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", self.extracted_mp3_path], check=False)
            elif os.name == 'nt':
                subprocess.run(["explorer", f"/select,{self.extracted_mp3_path}"], check=False)
            else:
                subprocess.run(["xdg-open", os.path.dirname(self.extracted_mp3_path)], check=False)

    def _play_extracted_mp3(self):
        if hasattr(self, 'extracted_mp3_path') and self.extracted_mp3_path and os.path.exists(self.extracted_mp3_path):
            if sys.platform == "darwin":
                subprocess.run(["open", self.extracted_mp3_path], check=False)
            elif os.name == 'nt':
                os.startfile(self.extracted_mp3_path)
            else:
                subprocess.run(["xdg-open", self.extracted_mp3_path], check=False)

    def _run_one_click_auto_dub(self):
        """Execute complete automated pipeline: MP3 -> React Khmer SRT -> TTS -> Dialogue Sync -> Video Mux."""
        if not self.video_path:
            self._browse_video()
            if not self.video_path:
                return

        if not self._ensure_gemini_key_available():
            return

        self.log_console.append_log("⚡ [1-Click Fast Auto Dub] Starting End-to-End Pipeline with React AI Engine...")
        self._set_processing_state(True, "⚡ Auto Dubbing in progress via React Engine...")

        def on_trans_done(segs):
            effects_config = self.video_preview.get_effects_config() if hasattr(self.video_preview, 'get_effects_config') else None
            self._start_dubbing_worker(pre_edited_segments=segs, effects_config=effects_config)

        self._start_react_translation_worker(on_finish_callback=on_trans_done)

    def _run_auto_transcribe_and_translate(self):
        """Execute speech-to-text and automatically chain into Khmer translation."""
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return

        if not self._ensure_gemini_key_available():
            return

        self.log_console.append_log("⚡ Starting Step 2: Whisper STT & Auto Khmer Translation...")
        self.progress_bar.setValue(0)
        self._start_transcription_worker(auto_translate_next=True)

    def _update_gemini_btn_status(self):
        if not hasattr(self, 'gemini_key_btn'):
            return
        key = get_gemini_api_key()
        if key:
            self.gemini_key_btn.setText("🔑 Gemini AI (✓ Active)")
            self.gemini_key_btn.setStyleSheet("""
                QPushButton {
                    background-color: #064e3b;
                    color: #34d399;
                    border: 1px solid #059669;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: 700;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #047857;
                }
            """)
        else:
            self.gemini_key_btn.setText("🔑 Gemini API Key (!)")
            self.gemini_key_btn.setStyleSheet("""
                QPushButton {
                    background-color: #78350f;
                    color: #fde68a;
                    border: 1px solid #d97706;
                    border-radius: 6px;
                    padding: 4px 10px;
                    font-weight: 700;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #92400e;
                }
            """)

    def _open_gemini_settings(self):
        dlg = GeminiApiKeyDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._update_gemini_btn_status()
            self.log_console.append_log("🔑 Google Gemini API Key configured and verified successfully!")

    def _open_settings(self):
        self._open_gemini_settings()

    def _ensure_gemini_key_available(self) -> bool:
        key = get_gemini_api_key()
        if key:
            return True

        ret = QMessageBox.question(
            self,
            "Gemini API Key Required 🔑",
            "ដើម្បីបកប្រែពាក្យសំដីជាភាសាខ្មែរ (ភាសានិយាយ) ឱ្យពិរោះតាមបែប Gemini AI\n"
            "សូមបញ្ចូល Gemini API Key របស់អ្នកជាមុនសិន!\n\n"
            "តើអ្នកចង់បញ្ចូល Gemini API Key ឥឡូវនេះដែរឬទេ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if ret == QMessageBox.Yes:
            self._open_gemini_settings()
            return bool(get_gemini_api_key())
        return False

    # ==================== VIDEO BLUR HANDLERS ====================
    def _on_blur_toggled(self, enabled: bool):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_blur_enabled(enabled)
            status_text = "enabled" if enabled else "disabled"
            self.log_console.append_log(f"🔍 Video Blur effect {status_text}.")

    def _on_blur_intensity_changed(self, intensity: int):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_blur_intensity(intensity)

    def _on_reset_blur_requested(self):
        if hasattr(self, 'video_preview'):
            self.video_preview.reset_blur_position()
            self.log_console.append_log("🔍 Video Blur position reset to center.")

    # ==================== VIDEO TEXT OVERLAY HANDLERS ====================
    def _on_text_toggled(self, enabled: bool):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_text_overlay_enabled(enabled)
            status_text = "enabled" if enabled else "disabled"
            self.log_console.append_log(f"📝 Text Overlay effect {status_text}.")

    def _on_text_updated(self, text: str, color_hex: str, size: int, font_name: str = "Kantumruy Pro"):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_text_overlay_text(text)
            self.video_preview.set_text_overlay_color(color_hex)
            self.video_preview.set_text_overlay_size(size)
            if hasattr(self.video_preview, 'set_text_overlay_font'):
                self.video_preview.set_text_overlay_font(font_name)
            self.log_console.append_log(f"📝 Text Overlay updated: '{text}' (Font: {font_name}, Color: {color_hex}, Size: {size})")

    def _on_text_position_changed(self, x: int, y: int):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_text_overlay_position(x, y)

    # ==================== VIDEO LOGO OVERLAY HANDLERS ====================
    def _on_logo_toggled(self, enabled: bool):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_logo_enabled(enabled)
            status_text = "enabled" if enabled else "disabled"
            self.log_console.append_log(f"🖼 Logo Overlay effect {status_text}.")

    def _on_logo_updated(self, path: str, x: int, y: int, width: int, height: int, remove_green: bool):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_logo_path(path)
            self.video_preview.set_logo_position(x, y)
            self.video_preview.set_logo_size(width, height)
            self.video_preview.set_logo_remove_green(remove_green)
            self.log_console.append_log(f"🖼 Logo Overlay updated: '{os.path.basename(path)}' at ({x}, {y}) size {width}x{height}")

    # ==================== BURN SUBTITLE HANDLERS ====================
    def _on_burn_subtitle_toggled(self, enabled: bool):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_burn_subtitle_enabled(enabled)
            status_text = "enabled" if enabled else "disabled"
            self.log_console.append_log(f"🔥 Burn Subtitle effect {status_text}.")

    def _on_burn_subtitle_updated(self, enabled: bool, font_name: str, size: int, color_hex: str, bg_opacity: float):
        if hasattr(self, 'video_preview'):
            self.video_preview.set_burn_subtitle_config(enabled, font_name, size, color_hex, bg_opacity)

    def _get_selected_source_language(self) -> str:
        if not hasattr(self, 'preset_combo') or not self.preset_combo:
            return "auto"
        preset_text = self.preset_combo.currentText().lower()
        if "chinese" in preset_text or "中文" in preset_text:
            return "zh"
        elif "english" in preset_text or "អង់គ្លេស" in preset_text:
            return "en"
        elif "japanese" in preset_text or "日本語" in preset_text:
            return "ja"
        elif "french" in preset_text or "français" in preset_text:
            return "fr"
        elif "khmer" in preset_text or "ខ្មែរ" in preset_text:
            return "km"
        elif "thai" in preset_text or "ថៃ" in preset_text:
            return "th"
        elif "vietnam" in preset_text or "tiếng việt" in preset_text:
            return "vi"
        elif "korean" in preset_text or "한국어" in preset_text:
            return "ko"
        elif "spanish" in preset_text or "español" in preset_text:
            return "es"
        else:
            return "auto"

    # ==================== TRANSCRIPTION & TRANSLATION VIA REACT ENGINE ====================
    def _run_transcription_only(self):
        """Transcribe and translate using React/Express Engine (:3000) directly to Khmer SRT."""
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return

        if not self._ensure_gemini_key_available():
            return

        self.log_console.append_log("⚡ Starting Translation via React AI Engine (MP3 → Khmer SRT)...")
        self.status_lbl.setText("⏳ Processing with React AI Engine...")
        self.progress_bar.setValue(0)
        self._start_react_translation_worker()

    def _open_web_studio(self):
        """Ensure React server is online and open http://localhost:3000 in browser."""
        from services.react_translator_bridge import ReactTranslatorBridge
        bridge = ReactTranslatorBridge()
        self.status_lbl.setText("🌐 Connecting to Web Studio (:3000)...")
        QApplication.processEvents()

        if not bridge.is_server_running():
            self.log_console.append_log("🌐 Launching Web Studio server in background...")
            bridge.ensure_server_running()

        url = "http://localhost:3000"
        self.log_console.append_log(f"🌐 Opening Web Studio in browser: {url}")
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            import webbrowser
            webbrowser.open(url)
        self.status_lbl.setText("🌐 Web Studio opened in browser.")

    def _start_react_translation_worker(self, on_finish_callback=None):
        """Dedicated worker using ReactTranslatorBridge (:3000) for instant Khmer SRT."""
        target_audio = self.extracted_mp3_path if (hasattr(self, 'extracted_mp3_path') and self.extracted_mp3_path and os.path.exists(self.extracted_mp3_path)) else self.video_path
        source_lang = self._get_selected_source_language()

        self._set_processing_state(True, "🌐 Step 2: React Engine AI Translating to Khmer SRT...")

        class ReactWorker(QThread):
            progress = Signal(int, str)
            finished = Signal(list, str)
            error = Signal(str)
            log = Signal(str)

            def __init__(self, audio_path, src_lang):
                super().__init__()
                self.setStackSize(8 * 1024 * 1024)
                self.audio_path = audio_path
                self.src_lang = src_lang
                self._is_cancelled = False

            def cancel(self):
                self._is_cancelled = True

            def run(self):
                try:
                    from services.react_translator_bridge import ReactTranslatorBridge
                    bridge = ReactTranslatorBridge()

                    def cb(pct, msg):
                        self.progress.emit(pct, msg)
                        self.log.emit(f"⚡ [React Engine] {msg}")

                    segments, out_srt, srt_text = bridge.translate_audio(
                        self.audio_path,
                        source_lang=self.src_lang,
                        target_lang="Khmer",
                        speed_mode="turbo",
                        progress_callback=cb,
                        is_cancelled_fn=lambda: self._is_cancelled
                    )

                    if self._is_cancelled:
                        return

                    dict_segments = [s.to_dict() if hasattr(s, "to_dict") else s for s in segments]
                    self.finished.emit(dict_segments, out_srt)

                except Exception as e:
                    self.error.emit(str(e))

        if getattr(self, 'react_worker', None) and self.react_worker.isRunning():
            try:
                self.react_worker.cancel()
                self.react_worker.quit()
                self.react_worker.wait(200)
            except Exception:
                pass

        self.react_worker = ReactWorker(target_audio, source_lang)
        self.react_worker.progress.connect(lambda p, msg: (self.progress_bar.setValue(p), self.status_lbl.setText(msg)))
        self.react_worker.log.connect(self.log_console.append_log)
        self.react_worker.finished.connect(lambda segs, srt_p: self._on_react_translation_done(segs, srt_p, callback=on_finish_callback))
        self.react_worker.error.connect(lambda e: (
            self.log_console.append_log(f"❌ React Engine error: {e}"),
            self._set_processing_state(False, f"❌ Translation Error: {e}"),
            QMessageBox.warning(self, "Translation Error", f"React Engine Translation Error:\n{e}\n\nFalling back to local STT...")
        ))
        self.react_worker.start()

    def _on_react_translation_done(self, segments, srt_path, callback=None):
        dict_segments = [s.to_dict() if hasattr(s, "to_dict") else s for s in (segments or [])]
        self.transcribed_segments = dict_segments
        self.subtitle_table.set_segments(dict_segments)
        self.timeline_editor.set_segments(dict_segments)
        self.video_preview.set_timeline_segments(dict_segments)
        self.progress_bar.setValue(100)
        self.log_console.append_log(f"🎉 [React Engine] Extracted {len(dict_segments)} Khmer segments! Saved SRT: {srt_path}")
        self._set_processing_state(False, f"✅ React Translation Complete! {len(dict_segments)} Khmer segments loaded.")

        if callback:
            callback(dict_segments)

    def _start_transcription_worker(self, auto_translate_next: bool = False):
        """Dedicated QThread Worker for Gemini AI Multimodal Audio processing."""
        if not self._ensure_gemini_key_available():
            return

        self._set_processing_state(True, "⏳ Step 2: Processing Audio with Gemini AI...")
        
        class TranscribeWorker(QThread):
            progress = Signal(int, str)
            finished = Signal(list)
            error = Signal(str)
            log = Signal(str)
            
            def __init__(self, video_path, source_lang="auto"):
                super().__init__()
                self.setStackSize(8 * 1024 * 1024)
                self.video_path = video_path
                self.source_lang = source_lang
                self._is_cancelled = False
                
            def cancel(self):
                self._is_cancelled = True
                
            def run(self):
                try:
                    self.log.emit("🎵 Separating speech dialogue from background music...")
                    self.progress.emit(10, "Separating Audio...")
                    from services.audio_separator import AudioSeparationService
                    sep_service = AudioSeparationService()
                    sep_res = sep_service.extract_and_separate(self.video_path)
                    vocal_wav_path = sep_res.get("dialogue_audio") or sep_res["vocal_audio"]
                    
                    if self._is_cancelled:
                        return
                    
                    self.log.emit("🌐 Running Dedicated Gemini STT Pipeline (VAD + gemini-3.5-transcribe)...")
                    self.progress.emit(25, "Gemini STT Transcribing...")
                    
                    from services.stt_service import STTService
                    stt = STTService()
                    
                    def cb(pct, msg):
                        self.progress.emit(pct, msg)
                        self.log.emit(f"⚡ {msg}")
                        
                    segments = stt.transcribe(vocal_wav_path, source_lang=self.source_lang, progress_callback=cb, is_cancelled_fn=lambda: self._is_cancelled)
                    
                    if self._is_cancelled:
                        return
                    
                    dict_segments = [s.to_dict() if hasattr(s, "to_dict") else s for s in segments]
                    self.progress.emit(100, "STT Processing Complete!")
                    self.log.emit(f"✅ STT completed! {len(dict_segments)} timestamped segments extracted.")
                    self.finished.emit(dict_segments)
                    
                except Exception as e:
                    self.error.emit(str(e))

        source_lang = self._get_selected_source_language()
        self.transcribe_worker = TranscribeWorker(
            self.video_path,
            source_lang=source_lang
        )
        self.transcribe_worker.progress.connect(lambda p, msg: (self.progress_bar.setValue(p), self.status_lbl.setText(msg)))
        self.transcribe_worker.log.connect(self.log_console.append_log)
        self.transcribe_worker.finished.connect(lambda segs: self._on_transcription_done(segs, auto_translate_next=auto_translate_next))
        self.transcribe_worker.error.connect(lambda e: (
            self.log_console.append_log(f"❌ Speech-to-Text error: {e}"),
            self._set_processing_state(False, f"❌ Error: {e}")
        ))
        self.transcribe_worker.start()

    def _on_transcription_done(self, segments, auto_translate_next: bool = False):
        """Triggered upon STT transcription completion."""
        dict_segments = [s.to_dict() if hasattr(s, "to_dict") else s for s in (segments or [])]
        self.transcribed_segments = dict_segments
        self.subtitle_table.set_segments(dict_segments)
        self.timeline_editor.set_segments(dict_segments)
        self.video_preview.set_timeline_segments(dict_segments)
        self.progress_bar.setValue(100)
        self.log_console.append_log(f"🎉 Extracted {len(dict_segments)} speech segments with high-precision timestamps.")
        
        has_khmer = any(s.get("khmer_text") for s in dict_segments)
        if auto_translate_next and not has_khmer:
            self._run_translation()
        else:
            self._set_processing_state(False, "✅ STT Complete! Segments loaded. Click 'Translate to Khmer' to proceed.")



    # ==================== KHMER TRANSLATION (THREAD WORKER) ====================
    def _run_translation(self):
        """Translate segments into Khmer using background QThread worker with Gemini AI."""
        segs = self.subtitle_table.get_updated_segments()
        if not segs:
            QMessageBox.warning(self, "Warning", "No segments available to translate. Please transcribe first.")
            self._set_processing_state(False)
            return

        if not self._ensure_gemini_key_available():
            self._set_processing_state(False)
            return

        self._set_processing_state(True, "🌐 Translating segments into natural spoken Khmer via Gemini AI...")
        self.log_console.append_log("🌐 Translating segments to natural spoken Khmer using Gemini AI...")
        self.progress_bar.setValue(0)
        
        class TranslateWorker(QThread):
            progress = Signal(int, str)
            finished = Signal(list)
            error = Signal(str)
            log = Signal(str)
            
            def __init__(self, segments, source_lang="auto", api_key=None):
                super().__init__()
                self.setStackSize(8 * 1024 * 1024)
                self.segments = segments
                self.source_lang = source_lang
                self.api_key = api_key or get_gemini_api_key()
                self._is_cancelled = False
                
            def cancel(self):
                self._is_cancelled = True

            def run(self):
                try:
                    from services.translation_service import TranslationService
                    ts = TranslationService(api_key=self.api_key)
                    self.log.emit(f"🌐 Translating {len(self.segments)} segments to natural spoken Khmer using Gemini AI...")
                    
                    def cb(pct, msg):
                        self.progress.emit(pct, msg)
                        self.log.emit(f"⚡ {msg}")

                    translated_segs = ts.translate_segments(
                        self.segments,
                        source_lang=self.source_lang,
                        target_lang="km",
                        progress_callback=cb,
                        is_cancelled_fn=lambda: self._is_cancelled
                    )
                    
                    if self._is_cancelled:
                        return

                    # Convert Segment models to dicts for existing UI components
                    result_dicts = [s.to_dict() if hasattr(s, "to_dict") else s for s in translated_segs]

                    self.progress.emit(100, "Translation Complete!")
                    self.finished.emit(result_dicts)
                except Exception as e:
                    self.error.emit(str(e))

        
        source_lang = self._get_selected_source_language()
        self.translate_worker = TranslateWorker(segs, source_lang=source_lang, api_key=get_gemini_api_key())
        self.translate_worker.progress.connect(lambda p, msg: (self.progress_bar.setValue(p), self.status_lbl.setText(msg)))
        self.translate_worker.log.connect(self.log_console.append_log)
        self.translate_worker.finished.connect(self._on_translation_done)
        self.translate_worker.error.connect(lambda e: (
            self.log_console.append_log(f"❌ Translation error: {e}"),
            self._set_processing_state(False, f"❌ Translation error: {e}")
        ))
        self.translate_worker.start()

    def _on_translation_done(self, translated_segments):
        self.subtitle_table.set_segments(translated_segments)
        self.timeline_editor.set_segments(translated_segments)
        self.video_preview.set_timeline_segments(translated_segments)
        self.transcribed_segments = translated_segments
        self.progress_bar.setValue(100)
        self._set_processing_state(False, "✅ Translation Completed! English text replaced with Khmer text.")
        self.log_console.append_log(f"🎉 Translated {len(translated_segments)} segments into Khmer successfully! (Original text replaced with Khmer text)")

    def _open_ai_voice_studio(self):
        from gui.widgets import AIVoiceStudioDialog
        dlg = AIVoiceStudioDialog(self)
        dlg.exec()

    def _browse_output_dir(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Target Export Folder", self.output_dir)
        if folder_path:
            self.output_dir = folder_path
            self.output_path_input.setText(folder_path)
            self.log_console.append_log(f"📁 Target export directory set to: {folder_path}")

    def _extract_vid_to_mp3(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return
        from utils.file_utils import generate_unique_filename
        out_mp3 = generate_unique_filename(self.video_path, prefix="audio", extension=".mp3", custom_dir=self.output_dir)
        from utils.ffmpeg import extract_audio
        if extract_audio(self.video_path, out_mp3):
            self.log_console.append_log(f"🎵 Audio extracted to unique MP3: {out_mp3}")
            QMessageBox.information(self, "Audio Extracted", f"MP3 Audio File Saved:\n{out_mp3}")

    def _export_mp3(self):
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return
        from utils.file_utils import generate_unique_filename, get_temp_path
        out_mp3 = generate_unique_filename(self.video_path, prefix="khmer_audio", extension=".mp3", custom_dir=self.output_dir)
        master_wav = get_temp_path("master_khmer_voice.wav")
        if os.path.exists(master_wav):
            from utils.ffmpeg import extract_audio
            extract_audio(master_wav, out_mp3)
            QMessageBox.information(self, "Success", f"Khmer Dubbed Audio Exported:\n{out_mp3}")
        else:
            self._extract_vid_to_mp3()

    # ==================== EXPORT FINAL VIDEO ====================
    def _export_final_video(self):
        """Export Video - executes TTS, Audio Sync, and Video Merging using table segments."""
        if not self.video_path:
            QMessageBox.warning(self, "Warning", "Please load a video file first.")
            return
        
        segs = self.subtitle_table.get_updated_segments()
        if not segs:
            QMessageBox.warning(self, "Warning", "No segments available. Please transcribe first.")
            return
        
        has_khmer = any(seg.get("khmer_text", "") for seg in segs)
        if not has_khmer:
            reply = QMessageBox.question(
                self, 
                "Warning", 
                "No Khmer translation found. Do you want to translate first?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._run_translation()
                return
        
        effects_config = self.video_preview.get_effects_config() if hasattr(self.video_preview, 'get_effects_config') else None
        if effects_config:
            effects_config["segments"] = segs
        
        self.log_console.append_log("🎬 Exporting Final Khmer Video with Dubbed Audio and Effects...")
        self._start_dubbing_worker(pre_edited_segments=segs, effects_config=effects_config)

    def _cancel_export(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
        if self.transcribe_worker and self.transcribe_worker.isRunning():
            self.transcribe_worker.cancel()
        if self.translate_worker and self.translate_worker.isRunning():
            self.translate_worker.cancel()
        self._set_processing_state(False, "⚠️ Process canceled by user.")
        self.log_console.append_log("⚠️ Pipeline process canceled by user.")

    def _start_dubbing_worker(self, pre_edited_segments=None, effects_config=None):
        from utils.file_utils import generate_unique_filename
        out_path = generate_unique_filename(self.video_path, prefix="khmer_dub", extension=".mp4", custom_dir=self.output_dir)

        self.log_console.append_log(f"📂 Output unique file path: {out_path}")
        self._set_processing_state(True, "🎬 Exporting Khmer Dubbed Video...")

        source_lang = self._get_selected_source_language()
        bg_vol = (self.bgm_vol_spin.value() / 100.0) if hasattr(self, 'bgm_vol_spin') else 0.30
        self.worker = DubbingWorker(
            video_path=self.video_path,
            output_path=out_path,
            source_lang=source_lang,
            target_lang="km",
            whisper_model="small",
            voice_name="VoxCPM2-Khmer",
            api_key=get_gemini_api_key(),
            background_volume=bg_vol,
            pre_translated_segments=pre_edited_segments,
            effects_config=effects_config
        )
        self.worker.progress_changed.connect(self._update_stepper_progress)
        self.worker.segments_ready.connect(self.subtitle_table.set_segments)
        self.worker.log_emitted.connect(self.log_console.append_log)
        self.worker.pipeline_finished.connect(self._on_finished)
        self.worker.pipeline_error.connect(lambda e: (
            self.log_console.append_log(f"❌ Video Dubbing error: {e}"),
            self._set_processing_state(False, f"❌ Export failed: {e}")
        ))
        self.worker.start()

    def _update_stepper_progress(self, progress: int, desc: str):
        self.progress_bar.setValue(progress)
        self.status_lbl.setText(desc)
        
        # Determine active step index: 0=audio, 1=stt, 2=trans, 3=tts, 4=sync, 5=export
        active_idx = 0
        desc_lower = desc.lower()
        if "extract" in desc_lower or "audio" in desc_lower:
            active_idx = 0
        elif "whisper" in desc_lower or "speech to text" in desc_lower or "stt" in desc_lower:
            active_idx = 1
        elif "translat" in desc_lower or "khmer" in desc_lower:
            active_idx = 2
        elif "tts" in desc_lower or "voice" in desc_lower or "synthes" in desc_lower:
            active_idx = 3
        elif "sync" in desc_lower or "stitch" in desc_lower:
            active_idx = 4
        elif "combin" in desc_lower or "merge" in desc_lower or "effect" in desc_lower or "done" in desc_lower:
            active_idx = 5

        for i, (k, lbl, orig_text) in enumerate(self.step_labels):
            if i < active_idx:
                lbl.setText(f"✓ {orig_text}")
                lbl.setStyleSheet("color: #00e676; background-color: #062b16; border: 1px solid #00c853; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;")
            elif i == active_idx:
                lbl.setText(f"⏳ {orig_text}")
                lbl.setStyleSheet("color: #ffffff; background-color: #1d4ed8; border: 1px solid #3b82f6; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;")
            else:
                lbl.setText(orig_text)
                lbl.setStyleSheet("color: #64748b; background-color: #0c111e; border: 1px solid #1e2942; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 600;")

    def _on_finished(self, output_path: str):
        self.progress_bar.setValue(100)
        self._set_processing_state(False, "🎉 Video Dubbing Complete!")
        for i, (k, lbl, orig_text) in enumerate(self.step_labels):
            lbl.setText(f"✓ {orig_text}")
            lbl.setStyleSheet("color: #00e676; background-color: #062b16; border: 1px solid #00c853; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;")

        # Automatically select the newly created Khmer dubbed audio track for preview
        if hasattr(self.video_preview, 'audio_track_combo'):
            self.video_preview.audio_track_combo.blockSignals(True)
            self.video_preview.audio_track_combo.setCurrentIndex(1)
            self.video_preview.audio_track_combo.blockSignals(False)
            self.video_preview._load_audio_for_player()

        res = QMessageBox.information(self, "Success 🇰🇭", f"Khmer Dubbed Video Exported:\n{output_path}\n\nPlay Video Now?", QMessageBox.Yes | QMessageBox.No)
        if res == QMessageBox.Yes:
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(output_path)
                else:  # macOS/Linux
                    subprocess.run(["open", output_path] if sys.platform == "darwin" else ["xdg-open", output_path], check=False)
            except Exception:
                pass

    def _clear_temp_cache(self):
        """Clean all cached temporary audio and video files."""
        from utils.file_utils import TEMP_DIR
        count = 0
        if os.path.exists(TEMP_DIR):
            for fname in os.listdir(TEMP_DIR):
                fpath = os.path.join(TEMP_DIR, fname)
                try:
                    if os.path.isfile(fpath):
                        os.remove(fpath)
                        count += 1
                except Exception:
                    pass
        self.log_console.append_log(f"🧹 Cleared {count} temporary cache files.")
        QMessageBox.information(self, "Cache Cleared", f"បានលុប File បណ្តោះអាសន្នចំនួន {count} Files រួចរាល់!")

    def _import_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import SRT", "", "Subtitle Files (*.srt)")
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            from core.srt_translator import SRTTranslator
            st = SRTTranslator()
            sub_segs = st.parse_srt(content)
            segs = [{"start": s.start_seconds, "end": s.end_seconds, "original_text": s.text, "khmer_text": s.text} for s in sub_segs]
            self.subtitle_table.set_segments(segs)
            self.timeline_editor.set_segments(segs)
            self.transcribed_segments = segs
            self.log_console.append_log(f"📥 Imported {len(segs)} segments from SRT: {file_path}")

    def _setup_web_studio_watcher(self):
        """Monitor output folder for exported subtitles from Web Studio and live auto-load them."""
        try:
            self.web_watcher = QFileSystemWatcher(self)
            out_path = str(self.output_dir)
            if os.path.exists(out_path):
                self.web_watcher.addPath(out_path)
            json_file = os.path.join(out_path, "latest_web_subtitles.json")
            if os.path.exists(json_file):
                self.web_watcher.addPath(json_file)
            self.web_watcher.fileChanged.connect(self._on_web_subtitles_auto_sync)
            self.web_watcher.directoryChanged.connect(self._on_web_dir_changed)
            self._last_web_sync_time = 0
            self.log_console.append_log("🌐 [Live Sync] Web Studio auto-sync listener active.")
        except Exception as e:
            self.log_console.append_log(f"⚠️ Web Studio auto-sync listener warning: {e}")

    def _on_web_dir_changed(self, path):
        json_file = os.path.join(path, "latest_web_subtitles.json")
        if os.path.exists(json_file):
            if hasattr(self, 'web_watcher') and json_file not in self.web_watcher.files():
                self.web_watcher.addPath(json_file)
            self._on_web_subtitles_auto_sync(json_file)

    def _on_web_subtitles_auto_sync(self, file_path):
        import time
        now = time.time()
        if now - getattr(self, '_last_web_sync_time', 0) < 1.0:
            return
        self._last_web_sync_time = now
        # Re-add path if removed on atomic write
        if hasattr(self, 'web_watcher') and os.path.exists(file_path) and file_path not in self.web_watcher.files():
            self.web_watcher.addPath(file_path)
        self._import_from_web_studio(silent_if_not_found=True)

    def _import_from_web_studio(self, silent_if_not_found: bool = False):
        """Directly import subtitles exported from the Web Studio (ai-audio-translator)."""
        json_path = os.path.join(self.output_dir, "latest_web_subtitles.json")
        srt_path = os.path.join(self.output_dir, "latest_web_subtitles.srt")

        segs = []
        if os.path.exists(json_path):
            try:
                import json
                with open(json_path, "r", encoding="utf-8") as f:
                    raw_segs = json.load(f)
                for s in raw_segs:
                    st = float(s.get("startSeconds", s.get("start", 0.0)))
                    et = float(s.get("endSeconds", s.get("end", st + 2.0)))
                    if et <= st:
                        et = st + 2.0
                    orig = (s.get("sourceText") or s.get("original_text") or "").strip()
                    khmer = (s.get("translatedText") or s.get("khmer_text") or orig).strip()
                    
                    clean_khmer, spk, gender, voice = clean_speaker_tag(khmer)
                    clean_orig, _, _, _ = clean_speaker_tag(orig)

                    raw_gender = (s.get("gender") or "").lower().strip()
                    orig_spk = str(s.get("speaker") or "").lower()
                    if raw_gender == "child" or any(w in orig_spk for w in ['child', 'kid', 'boy', 'baby', 'ក្មេង']):
                        gender = "child"
                        spk = "🧒 ក្មេង"
                        voice = "Khmer Child - Boy (Vannak)"
                    elif raw_gender == "female" or any(w in orig_spk for w in ['female', 'woman', 'girl', 'ស្រី']):
                        gender = "female"
                        spk = "👩 ស្រី"
                        voice = "Khmer Female - Sreymom"
                    elif raw_gender == "elder" or any(w in orig_spk for w in ['elder', 'ចាស់', 'យាយ', 'តា']):
                        gender = "elder"
                        spk = "👵👴 មនុស្សចាស់"
                        voice = "Khmer Elder - Male (Grandfather)"

                    persona = s.get("persona") or s.get("character") or spk
                    if persona not in PERSONA_CHOICES:
                        if gender == "child":
                            persona = "👦 Boy / Child"
                        elif gender == "female":
                            persona = "👩 Female Adult"
                        elif gender == "elder":
                            persona = "👴 Elderly Male"
                        else:
                            persona = "👨 Male Adult"
                    emotion = s.get("emotion") or "😐 Neutral"
                    style = s.get("speaking_style") or s.get("style") or "Normal"
                    voice = s.get("voice_id") or s.get("voice") or voice

                    segs.append({
                        "id": str(s.get("id", len(segs) + 1)),
                        "start": round(st, 2),
                        "end": round(et, 2),
                        "original_text": clean_orig or clean_khmer,
                        "khmer_text": clean_khmer,
                        "speaker": spk,
                        "speaker_id": s.get("speaker_id") or s.get("speakerId") or f"speaker_{1 + (len(segs) % 2):02d}",
                        "character": persona,
                        "persona": persona,
                        "emotion": emotion,
                        "speaking_style": style,
                        "gender": gender,
                        "voice": voice,
                        "voice_id": voice
                    })
            except Exception as e:
                self.log_console.append_log(f"⚠️ Error reading JSON from Web Studio: {e}")

        if not segs and os.path.exists(srt_path):
            try:
                with open(srt_path, "r", encoding="utf-8") as f:
                    content = f.read()
                from core.srt_translator import SRTTranslator
                st = SRTTranslator()
                sub_segs = st.parse_srt(content)
                segs = []
                for s in sub_segs:
                    clean_txt, spk, gender, voice = clean_speaker_tag(s.text)
                    segs.append({
                        "start": s.start_seconds,
                        "end": s.end_seconds,
                        "original_text": clean_txt,
                        "khmer_text": clean_txt,
                        "speaker": spk,
                        "character": spk,
                        "gender": gender,
                        "voice": voice
                    })
            except Exception as e:
                self.log_console.append_log(f"⚠️ Error reading SRT from Web Studio: {e}")

        if not segs:
            if not silent_if_not_found:
                QMessageBox.information(
                    self,
                    "Web Studio Subtitles",
                    "មិនទាន់មានទិន្នន័យ Subtitles ពី Web Studio នៅឡើយទេ!\n\n"
                    "សូមបើក '🌐 Web Studio' បកប្រែរួចចុចប៊ូតុង '🚀 បញ្ជូនទៅ Desktop Studio' ជាមុនសិន។"
                )
            return

        self.subtitle_table.set_segments(segs)
        self.timeline_editor.set_segments(segs)
        self.video_preview.set_timeline_segments(segs)
        self.transcribed_segments = segs
        self.log_console.append_log(f"🌐 [Web Studio Live Sync] Successfully loaded {len(segs)} Khmer segments!")
        self.status_lbl.setText(f"🎉 Web Studio: {len(segs)} segments auto-synced!")
        if not silent_if_not_found:
            QMessageBox.information(
                self,
                "នាំចូលបានជោគជ័យ",
                f"✅ បាននាំចូលអត្ថបទបកប្រែចំនួន {len(segs)} segments ពី Web Studio រួចរាល់!\nលោកអ្នកអាចចុច '🎙️ Export Dubbed Video' ដើម្បីបញ្ចូលសំឡេងបានភ្លាមៗ។"
            )

    def _export_srt(self):
        segs = self.subtitle_table.get_updated_segments()
        if not segs: return
        file_path, _ = QFileDialog.getSaveFileName(self, "Export SRT", "subtitles_khmer.srt", "Subtitle Files (*.srt)")
        if file_path:
            from core.srt_translator import SRTTranslator
            st = SRTTranslator()
            sub_segs = st.parse_segment_dicts(segs)
            st.save_srt(sub_segs, file_path)
            self.log_console.append_log(f"📤 Exported SRT file: {file_path}")

    # ==================== BATCH VOICE GENERATION (PREVIEW IN PLAYER) ====================
    def _generate_all_voices(self):
        """Synthesize all Khmer segment voices in parallel and load into Video Preview player."""
        if not self.video_path or not os.path.exists(self.video_path):
            QMessageBox.information(
                self, "Video Required",
                "សូមបើកវីដេអូជាមុនសិន មុននឹងសំយោគសំឡេង (Please open a video first)."
            )
            return

        segments = self.subtitle_table.get_updated_segments()
        if not segments:
            QMessageBox.information(
                self, "Subtitles Required",
                "មិនទាន់មាន Subtitle ក្នុងតារាងទេ! សូម Paste SRT ឬ Transcribe ជាមុនសិន។"
            )
            return

        # Check total duration from video_preview
        total_duration = 10.0
        try:
            if hasattr(self.video_preview, 'total_frames') and hasattr(self.video_preview, 'fps'):
                total_duration = max(1.0, self.video_preview.total_frames / max(1.0, self.video_preview.fps))
        except Exception:
            pass

        # Disable button during generation
        if hasattr(self.subtitle_table, 'generate_voices_btn'):
            self.subtitle_table.generate_voices_btn.setEnabled(False)
            self.subtitle_table.generate_voices_btn.setText("⏳ Synthesizing...")

        self.progress_bar.setValue(0)
        self.status_lbl.setText("🔊 Synthesizing Khmer voices...")
        self.log_console.append_log(f"🔊 [VoiceGen] Synthesizing Khmer voices for {len(segments)} segments...")

        self.voice_worker = GenerateVoicesWorker(segments, total_duration)
        self.voice_worker.progress.connect(self._on_voice_gen_progress)
        self.voice_worker.finished.connect(self._on_voice_gen_finished)
        self.voice_worker.error.connect(self._on_voice_gen_error)
        self.voice_worker.start()

    def _on_voice_gen_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_lbl.setText(msg)
        self.log_console.append_log(msg)

    def _on_voice_gen_finished(self, master_wav: str):
        self.last_master_wav = master_wav
        if hasattr(self.subtitle_table, 'generate_voices_btn'):
            self.subtitle_table.generate_voices_btn.setEnabled(True)
            self.subtitle_table.generate_voices_btn.setText("🔊 Generate Voices")

        self.progress_bar.setValue(100)
        self.status_lbl.setText("✅ Khmer voices ready! Switched to Khmer Dubbed Audio.")
        self.log_console.append_log(f"✅ [VoiceGen] Khmer dubbed track generated: {os.path.basename(master_wav)}")

        # Automatically switch video preview audio track to "🇰🇭 Khmer Dubbed" (index 1) and reload mixed audio
        if hasattr(self.video_preview, 'audio_track_combo'):
            self.video_preview.audio_track_combo.setCurrentIndex(1)
            if hasattr(self.video_preview, 'reload_mixed_audio'):
                self.video_preview.reload_mixed_audio()
            else:
                self.video_preview._load_audio_for_player()

        # Trigger background auto-save so user never loses generated audio state
        self._auto_save_project()

        QMessageBox.information(
            self, "Voice Generation Complete",
            f"✅ សំយោគសំឡេងខ្មែរគ្រប់ជួរ ({len(self.subtitle_table.get_updated_segments())} ឃ្លា) បានជោគជ័យ!\n\n"
            "ប្រព័ន្ធបានប្តូរទៅចាក់សំឡេង '🇰🇭 Khmer Dubbed' ដោយស្វ័យប្រវត្តិ។\n"
            "លោកអ្នកអាចចុច Play (Space) លើវីដេអូដើម្បីស្តាប់សាកល្បងបានភ្លាមៗ!"
        )

    def _on_voice_gen_error(self, err_msg: str):
        if hasattr(self.subtitle_table, 'generate_voices_btn'):
            self.subtitle_table.generate_voices_btn.setEnabled(True)
            self.subtitle_table.generate_voices_btn.setText("🔊 Generate Voices")

        self.status_lbl.setText(f"❌ {err_msg}")
        self.log_console.append_log(f"❌ [VoiceGen Error] {err_msg}")
        QMessageBox.warning(self, "Voice Generation Error", err_msg)

    def _on_bgm_volume_changed(self, val: int):
        self.status_lbl.setText(f"🎶 BGM Volume: {val}%")
        if hasattr(self, 'video_preview') and hasattr(self.video_preview, 'reload_mixed_audio'):
            if hasattr(self.video_preview, 'audio_track_combo') and self.video_preview.audio_track_combo.currentIndex() == 1:
                self.video_preview.reload_mixed_audio()

    # ==================== PROJECT SAVE & OPEN (.VPROJ) ====================
    def _auto_save_project(self):
        """Silently auto-save current state to output/autosave_project.vproj for disaster recovery."""
        try:
            import json
            segments = self.subtitle_table.get_updated_segments()
            if not segments and not self.video_path:
                return
            auto_path = Path(self.output_dir) / "autosave_project.vproj"
            effects_state = self.video_effects.get_state() if hasattr(self, 'video_effects') else {}
            bgm_vol = self.bgm_vol_spin.value() if hasattr(self, 'bgm_vol_spin') else 30
            project_data = {
                "format": "VideAI_Project",
                "version": "1.1",
                "video_path": self.video_path,
                "output_dir": self.output_dir,
                "bgm_volume": bgm_vol,
                "segments": segments,
                "effects": effects_state,
                "master_wav": getattr(self, 'last_master_wav', "")
            }
            with open(auto_path, "w", encoding="utf-8") as f:
                json.dump(project_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"[AutoSave] Project saved to {auto_path}")
        except Exception as e:
            logger.debug(f"[AutoSave] Silent error: {e}")

    def _restore_autosave(self):
        """Restore project from the latest autosave_project.vproj file."""
        auto_path = Path(self.output_dir) / "autosave_project.vproj"
        if not auto_path.exists():
            QMessageBox.information(
                self, "Restore Auto-save",
                "មិនមានឯកសារ Auto-save ត្រូវបានរកឃើញពីមុនមកទេ។"
            )
            return
        self._open_project(str(auto_path))

    def _save_project(self, file_path: str = None):
        """Save entire project state into a .vproj (JSON) file."""
        import json

        segments = self.subtitle_table.get_updated_segments()
        if not self.video_path and not segments:
            QMessageBox.information(
                self, "Save Project",
                "គ្មានទិន្នន័យគម្រោងដែលត្រូវរក្សាទុកទេ (សូមបើកវីដេអូ ឬនាំចូល Subtitle ជាមុនសិន)។"
            )
            return

        target_file = file_path or self.current_project_file
        if not target_file:
            base_stem = Path(self.video_path).stem if self.video_path else "khmer_translation"
            default_name = f"{base_stem}_project.vproj"
            target_file, _ = QFileDialog.getSaveFileName(
                self, "Save Vide AI Project",
                str(Path(self.output_dir) / default_name),
                "Vide AI Project (*.vproj *.json)"
            )
            if not target_file:
                return

        # Ensure .vproj extension if none provided
        if not target_file.endswith(".vproj") and not target_file.endswith(".json"):
            target_file += ".vproj"

        effects_state = self.video_effects.get_state() if hasattr(self, 'video_effects') else {}
        bgm_vol = self.bgm_vol_spin.value() if hasattr(self, 'bgm_vol_spin') else 30

        # Pillar 1 & 2: Aggregate Speaker Profiles dictionary
        speakers = {}
        for seg in segments:
            spk_id = seg.get("speaker_id") or "speaker_01"
            if spk_id not in speakers:
                persona = seg.get("persona") or seg.get("character") or "👨 Male Adult"
                speakers[spk_id] = {
                    "id": spk_id,
                    "display_name": f"Speaker {spk_id.replace('speaker_', '')}",
                    "persona": persona,
                    "gender": "female" if ("ស្រី" in persona or "Female" in persona) else "male",
                    "age_group": "child" if ("ក្មេង" in persona or "Child" in persona) else "adult",
                    "voice_id": seg.get("voice_id") or seg.get("voice") or "Khmer Male - Piseth",
                    "default_emotion": seg.get("emotion") or "😐 Neutral",
                    "default_style": seg.get("speaking_style") or seg.get("style") or "Normal"
                }

        project_data = {
            "format": "VideAI_Project",
            "version": "2.0",
            "video_path": self.video_path,
            "output_dir": self.output_dir,
            "bgm_volume": bgm_vol,
            "speakers": speakers,
            "segments": segments,
            "effects": effects_state,
            "master_wav": getattr(self, 'last_master_wav', "")
        }

        try:
            with open(target_file, "w", encoding="utf-8") as f:
                json.dump(project_data, f, ensure_ascii=False, indent=2)

            self.current_project_file = target_file
            proj_name = Path(target_file).name
            self.setWindowTitle(f"🎬 Vide AI Studio - [{proj_name}]")
            self.status_lbl.setText(f"💾 Project saved: {proj_name}")
            self.log_console.append_log(f"💾 [Project] Saved project successfully: {target_file}")

            # Show brief confirmation if manually saved
            if not file_path:
                QMessageBox.information(
                    self, "Project Saved",
                    f"✅ គម្រោងត្រូវបានរក្សាទុកដោយជោគជ័យ!\n\n"
                    f"📁 ឯកសារ: {proj_name}\n"
                    f"📝 ចំនួនឃ្លា Subtitle: {len(segments)} ជួរ\n\n"
                    f"លោកអ្នកអាចបើកវាមកកែប្រែបន្តនៅពេលក្រោយបានគ្រប់ពេលវេលា (Cmd+O) ដោយមិនបាច់ចាប់ផ្តើមពីសូន្យឡើយ។"
                )
        except Exception as e:
            self.log_console.append_log(f"❌ [Project] Failed to save project: {e}")
            QMessageBox.critical(self, "Save Error", f"មិនអាចរក្សាទុកគម្រោងបានទេ:\n{str(e)}")

    def _open_project(self, file_path: str = None):
        """Open and restore project state from a .vproj (JSON) file."""
        import json

        target_file = file_path
        if not target_file:
            target_file, _ = QFileDialog.getOpenFileName(
                self, "Open Vide AI Project",
                self.output_dir,
                "Vide AI Project (*.vproj *.json)"
            )
            if not target_file:
                return

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            video_path = data.get("video_path")
            if video_path and not os.path.exists(video_path):
                # Try finding in the same folder as the project file
                proj_dir = Path(target_file).parent
                candidate = proj_dir / Path(video_path).name
                ws_candidate = Path(os.getcwd()) / Path(video_path).name
                temp_candidate = Path(os.getcwd()) / "temp" / f"safe_input_{Path(video_path).name}"

                if candidate.exists():
                    video_path = str(candidate)
                elif ws_candidate.exists():
                    video_path = str(ws_candidate)
                elif temp_candidate.exists():
                    video_path = str(temp_candidate)
                else:
                    reply = QMessageBox.question(
                        self, "Video File Missing",
                        f"មិនអាចរកឃើញឯកសារវីដេអូនៅទីតាំងដើម:\n{video_path}\n\n"
                        "តើលោកអ្នកចង់ជ្រើសរើសទីតាំងថ្មីនៃឯកសារវីដេអូនោះឥឡូវនេះទេ?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                    )
                    if reply == QMessageBox.Yes:
                        chosen, _ = QFileDialog.getOpenFileName(
                            self, "Locate Missing Video File",
                            str(proj_dir),
                            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm)"
                        )
                        if chosen and os.path.exists(chosen):
                            video_path = chosen
                        else:
                            video_path = None
                    else:
                        video_path = None

            # Load video file if available
            if video_path and os.path.exists(video_path):
                self._load_video_file(video_path, clear_segments=False)

            # Restore segments
            segments = data.get("segments", [])
            self.transcribed_segments = segments
            self.subtitle_table.set_segments(segments)
            self.timeline_editor.set_segments(segments)
            self.video_preview.set_timeline_segments(segments)

            # Restore BGM volume
            if "bgm_volume" in data and hasattr(self, 'bgm_vol_spin'):
                self.bgm_vol_spin.setValue(int(data["bgm_volume"]))

            # Restore Effects
            if "effects" in data and hasattr(self, 'video_effects'):
                self.video_effects.set_state(data["effects"])

            if "output_dir" in data:
                self.output_dir = data["output_dir"]
                if hasattr(self, 'out_dir_display'):
                    self.out_dir_display.setText(self.output_dir)

            # Restore Dubbed Audio track if previously generated
            master_wav = data.get("master_wav")
            if not master_wav or not os.path.exists(master_wav):
                default_temp_wav = os.path.join(os.getcwd(), "temp", "master_khmer_voice.wav")
                if os.path.exists(default_temp_wav):
                    master_wav = default_temp_wav

            if master_wav and os.path.exists(master_wav):
                self.last_master_wav = master_wav
                if hasattr(self.video_preview, 'audio_track_combo'):
                    self.video_preview.audio_track_combo.setCurrentIndex(1)
                    self.video_preview._load_audio_for_player()
                self.log_console.append_log(f"🔊 [Project] Restored synthesized audio track: {os.path.basename(master_wav)}")

            self.current_project_file = target_file
            proj_name = Path(target_file).name
            self.setWindowTitle(f"🎬 Vide AI Studio - [{proj_name}]")
            self.status_lbl.setText(f"📂 Opened project: {proj_name}")
            self.log_console.append_log(f"📂 [Project] Opened project: {target_file} ({len(segments)} segments loaded)")

            vid_info = Path(video_path).name if video_path else "មិនទាន់ភ្ជាប់វីដេអូ"
            QMessageBox.information(
                self, "Project Opened",
                f"✅ បានបើកគម្រោងដោយជោគជ័យ!\n\n"
                f"📁 ឯកសារ: {proj_name}\n"
                f"📹 វីដេអូ: {vid_info}\n"
                f"📝 ចំនួនឃ្លា Subtitle: {len(segments)} ជួរ\n\n"
                f"លោកអ្នកអាចបន្តកែប្រែ ឬបន្ថែមសំឡេងបានភ្លាមៗ!"
            )
        except Exception as e:
            self.log_console.append_log(f"❌ [Project] Failed to open project: {e}")
            QMessageBox.critical(self, "Open Error", f"មិនអាចបើកឯកសារគម្រោងបានទេ:\n{str(e)}")

    def closeEvent(self, event):
        """Cleanly terminate any background worker threads and auto-save current state."""
        try:
            self._auto_save_project()
        except Exception:
            pass
        for worker in [getattr(self, 'worker', None), getattr(self, 'voice_worker', None), getattr(self, 'transcribe_worker', None), getattr(self, 'translate_worker', None), getattr(self, 'mp3_worker', None), getattr(self, 'react_worker', None)]:
            if worker and worker.isRunning():
                try:
                    if hasattr(worker, 'cancel'):
                        worker.cancel()
                    worker.quit()
                    if not worker.wait(300):
                        worker.terminate()
                        worker.wait(200)
                except Exception:
                    pass
        event.accept()

