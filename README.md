# 🇰🇭 Khmer Video Dubbing Desktop Application

A state-of-the-art Python & PySide6 desktop application for video transcription, AI translation, Khmer voice synthesis, and timestamped audio-video dubbing.

```text
┌─────────────────────────────────────────────────────────────┐
│ 🇰🇭 Khmer Video Translator                         ⚙ Settings │
├─────────────────────────────────────────────────────────────┤
│ VIDEO                                                       │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 🎬  No video selected                                   │ │
│ └─────────────────────────────────────────────────────────┘ │
│ [ 📁 Browse ]                                               │
│                                                             │
│ Source Language: [ English ▼ ]                              │
│ Target Language: [ Khmer 🇰🇭 ▼ ]                            │
│ Voice:           [ VoxCPM2 Khmer ▼ ]                        │
│                                                             │
│ TRANSLATION (SEGMENTS)                                      │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 00:00 - 00:04 | Hello everyone... | សួស្តីអ្នកទាំងអស់គ្នា...│ │
│ └─────────────────────────────────────────────────────────┘ │
│ [ 🎙 Test Voice ]                                           │
│                                                             │
│ PROGRESS                                                    │
│ ████████████████████░░░░░░░░░░ 65%                          │
│ Translating...                                              │
│ [ ▶ Start ] [ ⏸ Pause ] [ ⛔ Stop ]                        │
│ [ 🎬 CREATE KHMER VIDEO ]                                  │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Features

- **PySide6 Dark Glassmorphic Interface**: Responsive desktop UI with drag-and-drop video dropzone.
- **Timestamp Segment-Based Processing**: Avoids out-of-sync audio by segmenting video into `[start, end]` timestamps.
- **Whisper Speech-to-Text**: Automatic speech recognition for video transcripts.
- **Gemini & AI Translation**: Multi-backend translation into fluent Khmer (`km`).
- **VoxCPM2 Khmer TTS Integration**: High quality Khmer speech synthesis.
- **Interactive Segment Editor**: Edit original and Khmer translation cards before video compilation.
- **FFmpeg Audio-Video Synchronization**: Automatic speed adjustment (`atempo`), silent padding, and video multiplexing.

## 📁 Directory Structure

```text
vide ai/
├── main.py                     # Entry point
├── requirements.txt
├── README.md
├── gui/                        # PySide6 GUI Components
│   ├── main_window.py          # Main QMainWindow
│   ├── widgets.py              # Segment editor, drop zone, log console
│   └── styles.qss              # Glassmorphic QSS theme
├── core/                       # Core Pipeline Engine
│   ├── video_processor.py
│   ├── audio_processor.py
│   ├── transcriber.py
│   ├── translator.py
│   ├── tts.py
│   └── dubbing.py              # QThread pipeline orchestrator
├── services/                   # Service Abstractions
│   ├── whisper_service.py
│   ├── translation_service.py
│   └── voxcpm_service.py
├── utils/                      # Helper Utilities
│   ├── ffmpeg.py
│   ├── logger.py
│   └── file_utils.py
├── temp/                       # Temporary segment WAVs
└── output/                     # Final dubbed MP4 output
```

## 🛠️ Requirements & Installation

1. **FFmpeg System Dependency**:
   Ensure `ffmpeg` and `ffprobe` are installed on your system.

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Application**:
   ```bash
   python3 main.py
   ```
