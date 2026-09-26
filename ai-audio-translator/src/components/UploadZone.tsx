import React, { useRef, useState } from 'react';
import {
  UploadCloud,
  FileAudio,
  Mic,
  Square,
  Plus,
  Loader2,
  FolderArchive,
  FolderOpen,
  Sparkles,
  Zap,
  Clipboard,
  ClipboardPaste,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import JSZip from 'jszip';
import { AudioFileState } from '../types/translator';

interface UploadZoneProps {
  onAudiosAdded: (audios: AudioFileState[], autoStart?: boolean) => void;
  queueCount: number;
  isProcessing: boolean;
}

const AUDIO_EXTENSIONS = /\.(mp3|wav|m4a|ogg|aac|webm|flac|wma|opus|amr|aiff|mp4|mov|mkv|avi)$/i;

const getMimeTypeFromExt = (fileName: string): string => {
  const ext = fileName.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'mp3':
      return 'audio/mp3';
    case 'wav':
      return 'audio/wav';
    case 'm4a':
      return 'audio/m4a';
    case 'ogg':
      return 'audio/ogg';
    case 'aac':
      return 'audio/aac';
    case 'webm':
      return 'audio/webm';
    case 'flac':
      return 'audio/flac';
    case 'mp4':
      return 'video/mp4';
    case 'mov':
      return 'video/quicktime';
    case 'mkv':
      return 'video/x-matroska';
    default:
      return 'audio/mp3';
  }
};

export const UploadZone: React.FC<UploadZoneProps> = ({
  onAudiosAdded,
  queueCount,
  isProcessing,
}) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const zipInputRef = useRef<HTMLInputElement | null>(null);

  const [isDragging, setIsDragging] = useState(false);
  const [isConverting, setIsConverting] = useState(false);
  const [convertingMessage, setConvertingMessage] = useState<string>('');
  const [convertingProgress, setConvertingProgress] = useState<{ current: number; total: number } | null>(null);
  const [autoStartOnUpload, setAutoStartOnUpload] = useState<boolean>(true);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);

  // Microphone recording
  const [isRecording, setIsRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const getAudioDuration = (url: string): Promise<number> => {
    return new Promise((resolve) => {
      const audio = new Audio(url);
      const timer = setTimeout(() => resolve(0), 1200);
      audio.onloadedmetadata = () => {
        clearTimeout(timer);
        resolve(isFinite(audio.duration) ? audio.duration : 0);
      };
      audio.onerror = () => {
        clearTimeout(timer);
        resolve(0);
      };
    });
  };

  const fileToBase64 = (file: File | Blob): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = reader.result as string;
        const base64 = result.split(',')[1] || '';
        resolve(base64);
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  };

  // Process list of files (including extracting from ZIPs)
  const processIncomingFiles = async (rawFiles: File[], autoStartOverride?: boolean) => {
    if (rawFiles.length === 0) return;

    setIsConverting(true);
    setConvertingMessage('កំពុងស្កេន និងទាញយកឯកសារ (Extracting files)...');

    const targetFiles: File[] = [];

    for (const f of rawFiles) {
      if (f.name.toLowerCase().endsWith('.zip')) {
        try {
          setConvertingMessage(`កំពុងពន្លា ZIP (Unpacking ${f.name})...`);
          const zip = new JSZip();
          const loadedZip = await zip.loadAsync(f);
          const entries = Object.keys(loadedZip.files);

          for (const relPath of entries) {
            const entry = loadedZip.files[relPath];
            if (!entry.dir && entry.name.match(AUDIO_EXTENSIONS)) {
              const blob = await entry.async('blob');
              const cleanName = entry.name.split('/').pop() || entry.name;
              const extractedFile = new File([blob], cleanName, {
                type: getMimeTypeFromExt(cleanName),
              });
              targetFiles.push(extractedFile);
            }
          }
        } catch (err) {
          console.error('Error unpacking zip:', err);
        }
      } else if (f.type.startsWith('audio/') || f.type.startsWith('video/') || f.name.match(AUDIO_EXTENSIONS)) {
        targetFiles.push(f);
      }
    }

    if (targetFiles.length === 0) {
      setIsConverting(false);
      setConvertingProgress(null);
      setConvertingMessage('');
      return;
    }

    setConvertingProgress({ current: 0, total: targetFiles.length });
    const states: AudioFileState[] = [];

    for (let i = 0; i < targetFiles.length; i++) {
      const file = targetFiles[i];
      setConvertingMessage(`កំពុងរៀបចំ: ${file.name}`);
      setConvertingProgress({ current: i + 1, total: targetFiles.length });

      const objectUrl = URL.createObjectURL(file);
      const duration = await getAudioDuration(objectUrl);
      // For large files (> 15MB), do not load full base64 into browser RAM; streaming FormData will be used
      const base64 = file.size < 15 * 1024 * 1024 ? await fileToBase64(file) : '';

      states.push({
        file,
        name: file.name,
        size: file.size,
        duration,
        objectUrl,
        base64,
        mimeType: file.type || getMimeTypeFromExt(file.name),
      });
    }

    setIsConverting(false);
    setConvertingProgress(null);
    setConvertingMessage('');
    onAudiosAdded(states, autoStartOverride !== undefined ? autoStartOverride : autoStartOnUpload);
  };

  // Recursive scan for directory drop
  const scanEntry = async (entry: any): Promise<File[]> => {
    if (!entry) return [];
    if (entry.isFile) {
      return new Promise((resolve) => {
        entry.file((file: File) => resolve([file]), () => resolve([]));
      });
    } else if (entry.isDirectory) {
      const dirReader = entry.createReader();
      const readAllEntries = async (): Promise<any[]> => {
        let all: any[] = [];
        let batch: any[] = await new Promise((res) => dirReader.readEntries(res, () => res([])));
        while (batch.length > 0) {
          all = all.concat(batch);
          batch = await new Promise((res) => dirReader.readEntries(res, () => res([])));
        }
        return all;
      };

      const entries = await readAllEntries();
      const filesNested = await Promise.all(entries.map(scanEntry));
      return filesNested.flat();
    }
    return [];
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const items = e.dataTransfer.items;
    if (items && items.length > 0) {
      const entries = Array.from(items)
        .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
        .filter(Boolean);

      if (entries.length > 0) {
        setIsConverting(true);
        setConvertingMessage('កំពុងស្កេនថតឯកសារ (Scanning dropped folders)...');
        const fileBatches = await Promise.all(entries.map(scanEntry));
        const allFiles = fileBatches.flat();
        await processIncomingFiles(allFiles);
        return;
      }
    }

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      await processIncomingFiles(Array.from(e.dataTransfer.files));
    }
  };

  const [pasteLoading, setPasteLoading] = useState(false);
  const [pasteStatus, setPasteStatus] = useState<string | null>(null);
  const [pasteInputText, setPasteInputText] = useState('');

  // 1. One-click button: Read system clipboard and paste MP3 file or path
  const handleClipboardPaste = async () => {
    setPasteLoading(true);
    setPasteStatus(null);
    try {
      // Try reading clipboard files if supported
      if (navigator.clipboard && navigator.clipboard.read) {
        try {
          const items = await navigator.clipboard.read();
          for (const item of items) {
            for (const type of item.types) {
              if (type.startsWith('audio/') || type.startsWith('video/')) {
                const blob = await item.getType(type);
                const file = new File([blob], `Pasted_Audio_${Date.now()}.${type.split('/')[1] || 'mp3'}`, { type });
                setPasteStatus(`✅ បានទទួល MP3: ${file.name}`);
                processIncomingFiles([file], true);
                setPasteLoading(false);
                return;
              }
            }
          }
        } catch (readErr) {
          console.warn('[Clipboard.read] Fallback to readText():', readErr);
        }
      }

      // Try reading text path (e.g. copied from Desktop Studio)
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = (await navigator.clipboard.readText()).trim();
        if (text) {
          const res = await fetch('/api/load-local-audio', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filePath: text }),
          });
          const data = await res.json();
          if (res.ok && data.status === 'ok') {
            const newItem: AudioFileState = {
              file: null,
              name: data.name,
              size: data.size,
              duration: 0,
              objectUrl: data.streamUrl,
              base64: '',
              mimeType: data.mimeType,
              localFilePath: data.filePath,
            };
            setPasteStatus(`✅ បានទទួល MP3: ${data.name} (${(data.size / (1024 * 1024)).toFixed(1)} MB)`);
            onAudiosAdded([newItem], true);
            setPasteLoading(false);
            return;
          }
        }
      }

      // Fallback: Fetch newest MP3 generated in Desktop Studio
      await handleFetchLatestDesktopMp3();
    } catch (err: any) {
      setPasteStatus(`⚠️ សូមចុចក្នុងប្រអប់ខាងក្រោម រួចចុច Cmd+V: ${err.message}`);
    } finally {
      setPasteLoading(false);
    }
  };

  // 2. One-click button: Auto-fetch latest MP3 from Desktop Studio
  const handleFetchLatestDesktopMp3 = async () => {
    setPasteLoading(true);
    setPasteStatus('កំពុងស្វែងរក MP3 ថ្មីពី Desktop Studio...');
    try {
      const res = await fetch('/api/latest-desktop-mp3');
      const data = await res.json();
      if (res.ok && data.status === 'ok') {
        const newItem: AudioFileState = {
          file: null,
          name: data.name,
          size: data.size,
          duration: 0,
          objectUrl: data.streamUrl,
          base64: '',
          mimeType: 'audio/mp3',
          localFilePath: data.filePath,
        };
        setPasteStatus(`✅ បានទាញយក MP3 ពី Desktop: ${data.name} (${(data.size / (1024 * 1024)).toFixed(1)} MB)`);
        onAudiosAdded([newItem], true);
      } else {
        setPasteStatus(`⚠️ ${data.error || 'រកមិនឃើញ File MP3 ថ្មីក្នុង Desktop ឡើយ'}`);
      }
    } catch (err: any) {
      setPasteStatus(`⚠️ បរាជ័យក្នុងការទាញយក MP3: ${err.message}`);
    } finally {
      setPasteLoading(false);
    }
  };

  // 3. Direct Paste inside the input field
  const handleDirectInputPaste = async (e: React.ClipboardEvent<HTMLInputElement>) => {
    const clipboardData = e.clipboardData;
    if (!clipboardData) return;

    if (clipboardData.files && clipboardData.files.length > 0) {
      e.preventDefault();
      const files = Array.from(clipboardData.files);
      setPasteStatus(`✅ បាន Paste ឯកសារ: ${files[0].name}`);
      processIncomingFiles(files, true);
      return;
    }

    const pastedText = clipboardData.getData('text/plain')?.trim();
    if (pastedText) {
      e.preventDefault();
      setPasteInputText(pastedText);
      setPasteLoading(true);
      try {
        const res = await fetch('/api/load-local-audio', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filePath: pastedText }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          const newItem: AudioFileState = {
            file: null,
            name: data.name,
            size: data.size,
            duration: 0,
            objectUrl: data.streamUrl,
            base64: '',
            mimeType: data.mimeType,
            localFilePath: data.filePath,
          };
          setPasteStatus(`✅ បានទទួល MP3: ${data.name} (${(data.size / (1024 * 1024)).toFixed(1)} MB)`);
          onAudiosAdded([newItem], true);
        } else {
          setPasteStatus(`⚠️ រកមិនឃើញឯកសារ: ${pastedText}`);
        }
      } catch (err: any) {
        setPasteStatus(`⚠️ កំហុស: ${err.message}`);
      } finally {
        setPasteLoading(false);
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processIncomingFiles(Array.from(e.target.files));
      e.target.value = '';
    }
  };

  // Start live microphone recording
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const objectUrl = URL.createObjectURL(audioBlob);
        const base64 = await fileToBase64(audioBlob);
        const newAudio: AudioFileState = {
          file: null,
          name: `Recording_${new Date().toLocaleTimeString().replace(/:/g, '-')}.webm`,
          size: audioBlob.size,
          duration: recordingSeconds,
          objectUrl,
          base64,
          mimeType: 'audio/webm',
        };
        onAudiosAdded([newAudio], autoStartOnUpload);
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorder.start(250);
      setIsRecording(true);
      setRecordingSeconds(0);
      recordingTimerRef.current = setInterval(() => {
        setRecordingSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('Microphone error:', err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
      }
    }
  };

  // When there are items in the queue, show a clean, sleek, compact 1-line bar (not messy)
  if (queueCount > 0) {
    return (
      <div className="space-y-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.aac,.webm,.flac,.wma,.opus,.mp4,.mov,.mkv,.zip"
          onChange={handleFileChange}
          className="hidden"
          disabled={isConverting}
        />
        <input
          ref={folderInputRef}
          type="file"
          // @ts-ignore
          webkitdirectory="true"
          directory="true"
          onChange={handleFileChange}
          className="hidden"
          disabled={isConverting}
        />
        <input
          ref={zipInputRef}
          type="file"
          accept=".zip,application/zip"
          onChange={handleFileChange}
          className="hidden"
          disabled={isConverting}
        />

        <div className="bg-slate-900/80 border border-slate-800 rounded-2xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shadow-md backdrop-blur-md">
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="font-semibold text-slate-300">
              📁 {queueCount} ឯកសារក្នុងជួរ
            </span>
            {pasteStatus && (
              <span className="hidden sm:inline-block text-[11px] text-cyan-300 font-mono max-w-xs truncate">
                • {pasteStatus}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleClipboardPaste}
              disabled={pasteLoading}
              className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-xs shadow transition active:scale-95 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              {pasteLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ClipboardPaste className="w-3.5 h-3.5" />}
              <span>📋 Paste MP3 & Generate</span>
            </button>

            <button
              type="button"
              onClick={handleFetchLatestDesktopMp3}
              disabled={pasteLoading}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 text-xs font-semibold transition active:scale-95 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              title="ទាញយក MP3 ចុងក្រោយដែលទើបបង្កើតក្នុង Desktop Studio"
            >
              <Zap className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
              <span>⚡ យកពី Desktop</span>
            </button>

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="px-2.5 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition active:scale-95 flex items-center gap-1"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>ថែមទៀត</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // When queue is empty: Clean, non-messy Hero Card with clear Paste & Generate action
  return (
    <div className="space-y-3">
      {/* Hidden file inputs for Multi-file, Folder and ZIP */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="audio/*,video/*,.mp3,.wav,.m4a,.ogg,.aac,.webm,.flac,.wma,.opus,.mp4,.mov,.mkv,.zip"
        onChange={handleFileChange}
        className="hidden"
        disabled={isConverting}
      />
      <input
        ref={folderInputRef}
        type="file"
        // @ts-ignore
        webkitdirectory="true"
        directory="true"
        onChange={handleFileChange}
        className="hidden"
        disabled={isConverting}
      />
      <input
        ref={zipInputRef}
        type="file"
        accept=".zip,application/zip"
        onChange={handleFileChange}
        className="hidden"
        disabled={isConverting}
      />

      {/* Upload Zone Hero Container */}
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative border-2 border-dashed rounded-3xl p-6 sm:p-7 transition-all text-center ${
          isDragging
            ? 'border-amber-400 bg-amber-500/10 scale-[1.01]'
            : 'border-slate-800 hover:border-slate-700 bg-slate-900/50'
        }`}
      >
        {isConverting ? (
          <div className="flex flex-col items-center py-6">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center mb-3 animate-spin">
              <Loader2 className="w-6 h-6" />
            </div>
            <h4 className="text-base font-bold text-slate-100 mb-1">
              កំពុងបញ្ចូល & រៀបចំឯកសារ...
            </h4>
            <p className="text-xs text-amber-300 font-mono mb-2">
              {convertingMessage}
            </p>
            {convertingProgress && (
              <p className="text-xs text-slate-400">
                ឯកសារ {convertingProgress.current} នៃ {convertingProgress.total}
              </p>
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center max-w-xl mx-auto">
            {/* Primary Action Card: Paste MP3 & Auto-Generate */}
            <div className="w-full bg-gradient-to-r from-cyan-950/40 via-slate-900/90 to-blue-950/40 border border-cyan-500/30 rounded-2xl p-4 sm:p-5 shadow-xl text-left">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <div className="flex items-center gap-2.5">
                  <div className="w-9 h-9 rounded-xl bg-cyan-500/20 border border-cyan-500/40 flex items-center justify-center text-cyan-300 shrink-0">
                    <ClipboardPaste className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm sm:text-base font-bold text-slate-100 flex items-center gap-2">
                      <span>📋 Paste MP3 & បកប្រែភ្លាមៗ</span>
                      <span className="px-2 py-0.5 rounded-md bg-cyan-500/20 text-cyan-300 text-[10px] font-bold border border-cyan-500/30">
                        Cmd + V
                      </span>
                    </h3>
                    <p className="text-[11px] text-slate-400">
                      Copy MP3 ពី Desktop Studio រួចចុច Paste នៅទីនេះដើម្បី Auto-Generate
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleClipboardPaste}
                    disabled={pasteLoading}
                    className="px-3.5 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-xs shadow-md shadow-cyan-500/20 transition active:scale-95 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    {pasteLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Clipboard className="w-3.5 h-3.5 stroke-[2.5]" />}
                    <span>📋 Paste MP3</span>
                  </button>

                  <button
                    type="button"
                    onClick={handleFetchLatestDesktopMp3}
                    disabled={pasteLoading}
                    className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 text-xs font-semibold transition active:scale-95 flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                    title="ទាញយក MP3 ចុងក្រោយដែលទើបបង្កើតនៅក្នុង Desktop Studio"
                  >
                    <Zap className="w-3.5 h-3.5 text-amber-400 fill-amber-400" />
                    <span>⚡ យកពី Desktop</span>
                  </button>
                </div>
              </div>

              {/* Direct Input Field */}
              <div className="relative">
                <input
                  type="text"
                  value={pasteInputText}
                  onChange={(e) => setPasteInputText(e.target.value)}
                  onPaste={handleDirectInputPaste}
                  placeholder="ចុចទីនេះ រួចចុច Cmd+V (Paste) ដើម្បីបញ្ចូល File ឬ Path..."
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-950/80 border border-slate-700 focus:border-cyan-400 text-xs text-slate-200 placeholder-slate-500 outline-none transition"
                />
              </div>

              {/* Status Message */}
              {pasteStatus && (
                <div className="mt-2.5 flex items-center gap-2 text-xs text-cyan-300 bg-cyan-950/60 border border-cyan-500/30 px-3 py-1.5 rounded-lg">
                  <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span>{pasteStatus}</span>
                </div>
              )}
            </div>

            {/* Quick Multi-Upload Button */}
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="px-4 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs shadow-md shadow-amber-500/20 transition active:scale-95 flex items-center gap-2 cursor-pointer"
              >
                <FileAudio className="w-4 h-4" />
                <span>📁 រើសឯកសារពីកុំព្យូទ័រ (Multi-Files)</span>
              </button>

              <button
                type="button"
                onClick={() => setShowAdvanced(!showAdvanced)}
                className="px-3 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-800 text-slate-400 hover:text-slate-200 text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer"
              >
                <span>ជម្រើសបន្ថែម (Folder / ZIP / Mic)</span>
                {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>
            </div>

            {/* Collapsible Advanced Options (Clean, non-messy) */}
            {showAdvanced && (
              <div className="mt-3 pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-center gap-2 w-full animate-fadeIn">
                <button
                  type="button"
                  onClick={() => folderInputRef.current?.click()}
                  className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium transition flex items-center gap-1.5"
                >
                  <FolderOpen className="w-3.5 h-3.5 text-amber-400" />
                  <span>📂 Upload Folder ទាំងមូល</span>
                </button>

                <button
                  type="button"
                  onClick={() => zipInputRef.current?.click()}
                  className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium transition flex items-center gap-1.5"
                >
                  <FolderArchive className="w-3.5 h-3.5 text-emerald-400" />
                  <span>📦 ពន្លា ZIP ឯកសារ</span>
                </button>

                <button
                  type="button"
                  onClick={isRecording ? stopRecording : startRecording}
                  disabled={isProcessing && !isRecording}
                  className={`px-3 py-2 rounded-xl text-xs font-medium transition flex items-center gap-1.5 ${
                    isRecording
                      ? 'bg-rose-500 text-white animate-pulse'
                      : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700'
                  }`}
                >
                  {isRecording ? (
                    <>
                      <Square className="w-3.5 h-3.5 fill-current" />
                      <span>ឈប់ថត ({recordingSeconds}s)</span>
                    </>
                  ) : (
                    <>
                      <Mic className="w-3.5 h-3.5 text-rose-400" />
                      <span>ថតសំឡេង (Mic)</span>
                    </>
                  )}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
