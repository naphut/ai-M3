# ai-M3 🎬🇰🇭
### Ultra-Fast AI Video & Audio to Khmer Translation & SRT Subtitle Generator

An intelligent full-stack AI web application powered by **Google Gemini AI** and **FFmpeg** that automatically converts long-form video (MP4, MKV, MOV) and audio files into natural, fluent **Khmer (ភាសាខ្មែរ)** subtitles with synchronized **SRT (SubRip)** formatting.

---

## ⚡ 3-Stage Generation Pipeline

```
           📹 Video / Audio Input
                     │
                     ▼
      ⚡ ជំហានទី ១: AI Translation
      (Detect spoken language & verbatim speech recognition)
                     │
                     ▼
      🇰🇭 ជំហានទី ២: Khmer Translation
      (Natural conversational translation into ភាសាខ្មែរ)
                     │
                     ▼
      📄 ជំហានទី ៣: SRT Subtitles
      (Standard SubRip timestamps & in-app live sync video player)
```

---

## 🚀 Key Features

- **Long-form Video Support:** Handles 50+ minute videos (300MB+) smoothly via automated server-side FFmpeg compression (extracts speech to lightweight 24kbps mono MP3 in seconds).
- **Fast Generation:** Ultra-fast translation with minimal latency.
- **Direct SRT Output:** Copy or download standard `.srt` subtitles ready for CapCut, Premiere Pro, DaVinci Resolve, or VLC.
- **Live Video Player with Subtitle Overlay:** Preview video with Khmer subtitles displayed directly over the video stream.
- **Multi-Format Export:** Export as `.srt`, `.vtt`, `.txt`, and `.json`.

---

## 🛠️ Getting Started

### 1. Prerequisites
- **Node.js**: v18.0.0 or higher
- **FFmpeg**: Installed and available in your system PATH

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/naphut/ai-M3.git
cd ai-M3

# Install dependencies
npm install
```

### 3. Environment Variables
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY="your_gemini_api_key_here"
PORT=3000
```
Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

### 4. Run Development Server
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 📂 Project Structure

- `server.ts` - Express backend with FFmpeg optimizer & Gemini AI subtitle generator.
- `src/App.tsx` - Main React application, queue management, real upload tracking.
- `src/components/UploadZone.tsx` - File dropzone, folder upload, mic recording.
- `src/components/GenerationPipelineBanner.tsx` - Visual 3-stage generation pipeline indicator.
- `src/components/SrtCodeView.tsx` - Formatted SRT subtitle code viewer & exporter.
- `src/components/AudioPlayer.tsx` - Synchronized video/audio player with live subtitle overlay.
- `src/utils/subtitles.ts` - SRT, VTT, and timestamp utilities.

---

## 📄 License
MIT License
