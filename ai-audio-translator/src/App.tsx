/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useRef } from 'react';
import { UploadZone } from './components/UploadZone';
import { LanguageSelector } from './components/LanguageSelector';
import { AudioPlayer } from './components/AudioPlayer';
import { TranscriptView } from './components/TranscriptView';
import { ExportBar } from './components/ExportBar';
import { FlashUsageCard } from './components/FlashUsageCard';
import { TechnicalAnalysisModal } from './components/TechnicalAnalysisModal';
import { AudioQueueManager } from './components/AudioQueueManager';
import { GenerationPipelineBanner } from './components/GenerationPipelineBanner';
import { SrtCodeView } from './components/SrtCodeView';
import { AudioFileState, QueueItem, TranslationResult } from './types/translator';
import { Film, Info, AlertCircle, RefreshCw, FileText, CheckCircle2, Loader2 } from 'lucide-react';
import {
  loadLocalAudioFilePath,
  isRunningLocally,
  LOCAL_SERVER_BASE,
  pingLocalServer,
} from './utils/desktopBridge';

export default function App() {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [isQueueRunning, setIsQueueRunning] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [speedMode, setSpeedMode] = useState<'turbo' | 'standard'>('turbo');
  const [pipelineTab, setPipelineTab] = useState<'khmer' | 'srt' | 'preview'>('srt');

  // Playback sync
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [seekToTime, setSeekToTime] = useState<number | null>(null);
  const [showAnalysis, setShowAnalysis] = useState<boolean>(false);

  // Refs for stable async loop access
  const isQueueRunningRef = useRef<boolean>(false);
  const isPausedRef = useRef<boolean>(false);
  const queueRef = useRef<QueueItem[]>([]);
  queueRef.current = queue;
  const speedModeRef = useRef<'turbo' | 'standard'>('turbo');
  speedModeRef.current = speedMode;

  // Active item lookup
  const activeItem = queue.find((i) => i.id === activeItemId) || queue[0] || null;
  const result: TranslationResult | null = activeItem?.result || null;

  // Compute live active subtitle for video player overlay
  const currentSegment = result?.segments.find(
    (s) => currentTime >= s.startSeconds && currentTime <= s.endSeconds
  );
  const activeSubtitleText = currentSegment?.translatedText || '';

  // Add new audios into the queue
  const handleAudiosAdded = (newAudios: AudioFileState[], autoStart: boolean = false) => {
    const newItems: QueueItem[] = newAudios.map((audio, idx) => ({
      id: `audio_${Date.now()}_${idx}_${Math.random().toString(36).substring(2, 7)}`,
      file: audio.file,
      name: audio.name,
      size: audio.size,
      duration: audio.duration,
      objectUrl: audio.objectUrl,
      base64: audio.base64,
      mimeType: audio.mimeType,
      localFilePath: audio.localFilePath,
      status: 'pending',
      progress: 0,
      progressStep: 'រង់ចាំក្នុងជួរ',
      result: null,
      error: null,
      createdAt: Date.now(),
    }));

    const updatedQueue = [...queueRef.current, ...newItems];
    queueRef.current = updatedQueue;

    setQueue(updatedQueue);
    if (!activeItemId && updatedQueue.length > 0) {
      setActiveItemId(updatedQueue[0].id);
    }
    setErrorMessage(null);

    if (autoStart) {
      startSequentialQueue(updatedQueue);
    }
  };

  // Global Cmd+V / Ctrl+V paste support for MP3/Audio from Desktop Studio
  React.useEffect(() => {
    const handlePaste = async (e: ClipboardEvent) => {
      const clipboardData = e.clipboardData;
      if (!clipboardData) return;

      // 1. Check if binary files are present in clipboard
      const files: File[] = [];
      if (clipboardData.files && clipboardData.files.length > 0) {
        for (let i = 0; i < clipboardData.files.length; i++) {
          const item = clipboardData.files[i];
          if (
            item.type.startsWith('audio/') ||
            item.type.startsWith('video/') ||
            /\.(mp3|wav|m4a|mp4|mov|mkv|aac|ogg|flac)$/i.test(item.name)
          ) {
            files.push(item);
          }
        }
      }

      if (files.length > 0) {
        e.preventDefault();
        const states: AudioFileState[] = [];
        for (const file of files) {
          const objectUrl = URL.createObjectURL(file);
          states.push({
            file,
            name: file.name,
            size: file.size,
            duration: 0,
            objectUrl,
            base64: '',
            mimeType: file.type || 'audio/mp3',
          });
        }
        handleAudiosAdded(states, true);
        return;
      }

      // 2. Check if text clipboard is a file path or URL (e.g. copied from Desktop Studio)
      const pastedText = (clipboardData.getData('text/plain') || '').trim();
      if (
        pastedText &&
        (/\.(mp3|wav|m4a|mp4|mov|mkv)$/i.test(pastedText) ||
          pastedText.startsWith('/') ||
          pastedText.startsWith('file://'))
      ) {
        e.preventDefault();
        try {
          const loaded = await loadLocalAudioFilePath(pastedText);
          const item: AudioFileState = {
            file: loaded.file,
            name: loaded.name,
            size: loaded.size,
            duration: 0,
            objectUrl: loaded.objectUrl,
            base64: '',
            mimeType: loaded.file.type || 'audio/mp3',
            localFilePath: loaded.filePath,
          };
          handleAudiosAdded([item], true);
          return;
        } catch (err) {
          console.warn('[Paste] Could not resolve local file path via bridge:', err);
        }
      }
    };

    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, []);

  // Sequential Queue Processing Engine
  const startSequentialQueue = async (customList?: any) => {
    if (Array.isArray(customList)) {
      queueRef.current = customList;
    }
    if (isQueueRunningRef.current) return;
    isQueueRunningRef.current = true;
    setIsQueueRunning(true);
    isPausedRef.current = false;
    setIsPaused(false);
    setErrorMessage(null);

    while (true) {
      // Check if paused
      if (isPausedRef.current) {
        break;
      }

      // Find next pending or error item
      const currentList = queueRef.current;
      const nextItem = currentList.find((i) => i.status === 'pending');

      if (!nextItem) {
        // All items processed
        break;
      }

      const itemId = nextItem.id;
      setActiveItemId(itemId);

      // Set to processing
      const startTime = Date.now();
      setQueue((prev) =>
        prev.map((i) =>
          i.id === itemId
            ? {
                ...i,
                status: 'processing',
                startedAt: startTime,
                progress: 5,
                progressStep: 'កំពុងចាប់ផ្តើម...',
                error: null,
              }
            : i
        )
      );

      try {
        const isLocalOnline = !isRunningLocally() ? await pingLocalServer() : false;
        const apiBase = isLocalOnline ? LOCAL_SERVER_BASE : '';
        const data: TranslationResult = await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open('POST', `${apiBase}/api/translate-audio`);

          // Track accurate real upload progress
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable && event.total > 0) {
              const loadedMB = (event.loaded / (1024 * 1024)).toFixed(1);
              const totalMB = (event.total / (1024 * 1024)).toFixed(1);
              const percent = Math.min(60, Math.round((event.loaded / event.total) * 60));

              setQueue((prev) =>
                prev.map((i) =>
                  i.id === itemId
                    ? {
                        ...i,
                        progress: Math.max(5, percent),
                        progressStep:
                          event.loaded < event.total
                            ? `កំពុង Upload (${loadedMB} MB / ${totalMB} MB)...`
                            : 'Upload រួចរាល់! FFmpeg កំពុងស្រង់យកសំឡេង...',
                      }
                    : i
                )
              );
            }
          };

          // When upload is done, server is extracting audio and running AI
          xhr.upload.onload = () => {
            setQueue((prev) =>
              prev.map((i) =>
                i.id === itemId
                  ? {
                      ...i,
                      progress: 70,
                      progressStep: 'FFmpeg កំពុងច្រោះរូបភាព & បង្រួមសំឡេង (~9MB)...',
                    }
                  : i
              )
            );

            // After 2.5s, update step to AI translation
            setTimeout(() => {
              setQueue((prev) =>
                prev.map((i) =>
                  i.id === itemId && i.status === 'processing'
                    ? {
                        ...i,
                        progress: 88,
                        progressStep: 'AI Gemini Turbo កំពុងបកប្រែជា Subtitle ខ្មែរ (SRT)...',
                      }
                    : i
                )
              );
            }, 2500);
          };

          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              try {
                const parsed = JSON.parse(xhr.responseText);
                resolve(parsed);
              } catch (e) {
                reject(new Error('Invalid JSON response from server'));
              }
            } else {
              try {
                const errData = JSON.parse(xhr.responseText);
                reject(new Error(errData.error || `Server status ${xhr.status}`));
              } catch {
                reject(new Error(`Server error (${xhr.status}): ${xhr.statusText}`));
              }
            }
          };

          xhr.onerror = () => {
            reject(new Error('Network error during upload or translation'));
          };

          // Send data
          if (nextItem.localFilePath) {
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(
              JSON.stringify({
                localFilePath: nextItem.localFilePath,
                sourceLang: 'Auto',
                targetLang: 'Khmer',
                speedMode: speedModeRef.current,
              })
            );
          } else if (nextItem.file) {
            const formData = new FormData();
            formData.append('audioFile', nextItem.file);
            formData.append('sourceLang', 'Auto');
            formData.append('targetLang', 'Khmer');
            formData.append('speedMode', speedModeRef.current);
            formData.append('mimeType', nextItem.mimeType);
            xhr.send(formData);
          } else {
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(
              JSON.stringify({
                audioBase64: nextItem.base64,
                mimeType: nextItem.mimeType,
                sourceLang: 'Auto',
                targetLang: 'Khmer',
                speedMode: speedModeRef.current,
              })
            );
          }
        });

        const endTime = Date.now();

        // Mark this item completed
        setQueue((prev) =>
          prev.map((i) =>
            i.id === itemId
              ? {
                  ...i,
                  status: 'completed',
                  progress: 100,
                  progressStep: 'បកប្រែជោគជ័យ',
                  result: data,
                  completedAt: endTime,
                  error: null,
                }
              : i
          )
        );
      } catch (err: any) {
        console.error(`Item ${nextItem.name} failed:`, err);
        const errMsg = err.message || 'កំហុសបកប្រែ';
        setQueue((prev) =>
          prev.map((i) =>
            i.id === itemId
              ? {
                  ...i,
                  status: 'error',
                  progress: 0,
                  progressStep: 'បរាជ័យ',
                  error: errMsg,
                }
              : i
          )
        );
      }

      // Small delay between queue items to optimize throughput and API stability
      await new Promise((resolve) => setTimeout(resolve, 400));
    }

    isQueueRunningRef.current = false;
    setIsQueueRunning(false);
  };

  const handlePauseQueue = () => {
    isPausedRef.current = true;
    setIsPaused(true);
  };

  const handleResumeQueue = () => {
    isPausedRef.current = false;
    setIsPaused(false);
    startSequentialQueue();
  };

  const handleRetryItem = (id: string) => {
    setQueue((prev) =>
      prev.map((i) =>
        i.id === id
          ? {
              ...i,
              status: 'pending',
              progress: 0,
              progressStep: 'រង់ចាំក្នុងជួរ',
              error: null,
            }
          : i
      )
    );
    if (!isQueueRunningRef.current) {
      setTimeout(startSequentialQueue, 150);
    }
  };

  const handleRetryAllFailed = () => {
    setQueue((prev) =>
      prev.map((i) =>
        i.status === 'error'
          ? {
              ...i,
              status: 'pending',
              progress: 0,
              progressStep: 'រង់ចាំក្នុងជួរ',
              error: null,
            }
          : i
      )
    );
    if (!isQueueRunningRef.current) {
      setTimeout(startSequentialQueue, 150);
    }
  };

  const handleRemoveItem = (id: string) => {
    setQueue((prev) => {
      const updated = prev.filter((i) => i.id !== id);
      if (activeItemId === id) {
        setActiveItemId(updated.length > 0 ? updated[0].id : null);
      }
      return updated;
    });
  };

  const handleClearCompleted = () => {
    setQueue((prev) => {
      const updated = prev.filter((i) => i.status !== 'completed');
      if (activeItemId && !updated.find((i) => i.id === activeItemId)) {
        setActiveItemId(updated.length > 0 ? updated[0].id : null);
      }
      return updated;
    });
  };

  const handleClearAll = () => {
    setQueue([]);
    setActiveItemId(null);
    setCurrentTime(0);
    setSeekToTime(null);
    setErrorMessage(null);
  };

  // Jump to specific segment timestamp
  const handleJumpToTime = (seconds: number) => {
    setSeekToTime(seconds);
    setCurrentTime(seconds);
  };

  // Update a segment inline in the currently active item
  const handleUpdateSegment = (
    id: number,
    translatedText: string,
    sourceText?: string,
    speaker?: string,
    gender?: string
  ) => {
    if (!activeItemId) return;
    setQueue((prev) =>
      prev.map((item) => {
        if (item.id !== activeItemId || !item.result) return item;
        const updatedSegments = item.result.segments.map((seg) => {
          if (seg.id === id) {
            return {
              ...seg,
              translatedText,
              sourceText: sourceText !== undefined ? sourceText : seg.sourceText,
              speaker: speaker !== undefined ? speaker : seg.speaker,
              gender: gender !== undefined ? gender : seg.gender,
            };
          }
          return seg;
        });
        return {
          ...item,
          result: {
            ...item.result,
            segments: updatedSegments,
          },
        };
      })
    );
  };

  // Delete a specific segment in the active item
  const handleDeleteSegment = (id: number) => {
    if (!activeItemId) return;
    setQueue((prev) =>
      prev.map((item) => {
        if (item.id !== activeItemId || !item.result) return item;
        const remaining = item.result.segments.filter((seg) => seg.id !== id);
        return {
          ...item,
          result:
            remaining.length === 0
              ? null
              : {
                  ...item.result,
                  segments: remaining,
                },
        };
      })
    );
  };

  // Clear all results of active item
  const handleClearTranscript = () => {
    if (!activeItemId) return;
    setQueue((prev) =>
      prev.map((item) =>
        item.id === activeItemId ? { ...item, result: null } : item
      )
    );
  };

  const completedQueueItems = queue.filter((i) => i.status === 'completed' && i.result);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center py-6 px-3 sm:px-6 relative overflow-x-hidden selection:bg-amber-500/30 selection:text-amber-200">
      {/* Background Ambient Glow */}
      <div className="fixed top-0 left-1/2 -translate-x-1/2 w-[800px] h-[300px] bg-gradient-to-b from-amber-500/10 via-amber-500/5 to-transparent blur-3xl pointer-events-none -z-10" />

      {/* Main Container constrained to clean wireframe proportion */}
      <div className="w-full max-w-4xl space-y-6">
        {/* Top Header matching 🎬 AI Audio Translator */}
        <header className="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 sm:p-7 shadow-2xl backdrop-blur-xl relative overflow-hidden">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3.5">
              <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center shadow-lg shadow-amber-500/10 shrink-0">
                <Film className="w-6 h-6" />
              </div>
              <div>
                <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-100 tracking-tight flex items-center gap-2">
                  <span>🎬 AI Audio Translator</span>
                </h1>
                <p className="text-xs sm:text-sm text-slate-400 mt-0.5">
                  ការបកប្រែ MP3 ច្រើនឯកសារតាមជួរ (Batch Queue) ទៅជាអត្ថបទ & Subtitle ខ្មែរ
                </p>
              </div>
            </div>

            {/* Header Action Button: Technical Analysis */}
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => setShowAnalysis(true)}
                className="px-3.5 py-2 rounded-xl bg-slate-800/80 hover:bg-slate-800 text-slate-200 border border-slate-700 hover:border-amber-500/40 text-xs font-bold transition flex items-center gap-1.5 cursor-pointer shadow-sm"
              >
                <Info className="w-4 h-4 text-amber-400" />
                <span>វិភាគបច្ចេកទេស (Analysis)</span>
              </button>
            </div>
          </div>
        </header>

        {/* Multi-file Upload Zone Section */}
        <UploadZone
          onAudiosAdded={handleAudiosAdded}
          queueCount={queue.length}
          isProcessing={isQueueRunning}
        />

        {/* Audio Queue Manager: Only show if multiple items OR when queue is actively running or no result yet */}
        {queue.length > 0 && (queue.length > 1 || isQueueRunning || !result) && (
          <AudioQueueManager
            queue={queue}
            activeItemId={activeItemId}
            isQueueRunning={isQueueRunning}
            isPaused={isPaused}
            speedMode={speedMode}
            onSpeedModeChange={setSpeedMode}
            onSelectActiveItem={(id) => setActiveItemId(id)}
            onStartQueue={startSequentialQueue}
            onPauseQueue={handlePauseQueue}
            onResumeQueue={handleResumeQueue}
            onRetryItem={handleRetryItem}
            onRetryAllFailed={handleRetryAllFailed}
            onRemoveItem={handleRemoveItem}
            onClearCompleted={handleClearCompleted}
            onClearAll={handleClearAll}
          />
        )}

        {/* Language Selection: Only display if queue is not running and not yet completed */}
        {queue.length > 0 && !isQueueRunning && !result && (
          <LanguageSelector
            onStartTranslation={startSequentialQueue}
            isProcessing={isQueueRunning}
            hasAudio={queue.length > 0}
            queueCount={queue.length}
            speedMode={speedMode}
            onSpeedModeChange={setSpeedMode}
          />
        )}

        {/* Active Audio / Video Player (when an active item is selected) */}
        {activeItem && (
          <AudioPlayer
            audioUrl={activeItem.objectUrl}
            audioName={activeItem.name}
            currentTime={currentTime}
            onTimeUpdate={(t) => setCurrentTime(t)}
            seekToTime={seekToTime}
            onSeekComplete={() => setSeekToTime(null)}
            activeSubtitleText={activeSubtitleText}
          />
        )}

        {/* Active Transcript Switcher Tab (if multiple files are completed) */}
        {completedQueueItems.length > 1 && (
          <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
              <FileText className="w-4 h-4 text-amber-400" />
              <span>ជ្រើសរើសឯកសារដើម្បីមើលលទ្ធផល:</span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {completedQueueItems.map((item, idx) => {
                const isSelected = item.id === activeItemId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setActiveItemId(item.id)}
                    className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer ${
                      isSelected
                        ? 'bg-amber-500 text-slate-950 font-bold shadow-md shadow-amber-500/20'
                        : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'
                    }`}
                  >
                    <span>#{idx + 1}</span>
                    <span className="max-w-[120px] truncate">{item.name}</span>
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Currently Processing Status Card if active item is processing */}
        {activeItem && activeItem.status === 'processing' && (
          <div className="p-8 rounded-3xl bg-slate-900/80 border border-amber-500/30 text-center space-y-4">
            <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center mx-auto animate-spin">
              <Loader2 className="w-7 h-7" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-100">
                {activeItem.name}
              </h3>
              <p className="text-xs text-amber-400 mt-1 font-medium">
                {activeItem.progressStep || 'កំពុងដំណើរការបកប្រែជាបន្តបន្ទាប់...'} ({activeItem.progress}%)
              </p>
            </div>
            <div className="w-full max-w-md mx-auto h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-400 transition-all duration-300 rounded-full"
                style={{ width: `${Math.max(10, activeItem.progress)}%` }}
              />
            </div>
          </div>
        )}

        {/* Error Alert if general error */}
        {errorMessage && (
          <div className="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 text-amber-200">
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div className="flex-1 text-xs sm:text-sm">
                <p className="font-bold text-amber-300 mb-1">
                  ការជូនដំណឹងពីប្រព័ន្ធ AI (AI Service Notice):
                </p>
                <p className="text-slate-300 leading-relaxed mb-3">
                  {errorMessage}
                </p>

                <div className="flex flex-wrap items-center gap-2.5">
                  <button
                    type="button"
                    onClick={startSequentialQueue}
                    className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-slate-950 rounded-xl text-xs font-bold transition flex items-center gap-1.5 shadow-md shadow-amber-500/20 cursor-pointer"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>សាកល្បងម្ដងទៀត (Retry AI Translation)</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Results: Clean, Sleek, Direct View */}
        {result && activeItem && (
          <div className="space-y-4">
            {/* Direct SRT Output (clean, focused, not cluttered) */}
            {pipelineTab === 'srt' ? (
              <SrtCodeView
                result={result}
                fileName={activeItem.name || 'translation_output'}
              />
            ) : (
              <>
                <TranscriptView
                  result={result}
                  currentTime={currentTime}
                  onJumpToTime={handleJumpToTime}
                  onUpdateSegment={handleUpdateSegment}
                  onDeleteSegment={handleDeleteSegment}
                  onClearAll={handleClearTranscript}
                />
                <ExportBar
                  result={result}
                  fileName={activeItem.name || 'translation_output'}
                />
              </>
            )}
          </div>
        )}

        {/* Initial Empty state hint if no files uploaded */}
        {queue.length === 0 && (
          <div className="border border-slate-800/80 rounded-3xl p-8 text-center bg-slate-900/40">
            <p className="text-slate-400 text-sm">
              មិនទាន់មានឯកសារក្នុងជួរនៅឡើយទេ។ សូម Upload ឯកសារ MP3 / Audio ម្តងមួយ ឬច្រើនក្នុងពេលតែមួយ រួចចុច <strong>[ Start AI Translation ]</strong>
            </p>
          </div>
        )}

        {/* Footer info */}
        <footer className="text-center text-xs text-slate-500 py-4">
          <p>
            🎬 AI Audio Translator • Sequential Queue System • Auto Detect to Khmer
          </p>
        </footer>
      </div>

      {/* Architecture & Technical Analysis Modal */}
      <TechnicalAnalysisModal
        isOpen={showAnalysis}
        onClose={() => setShowAnalysis(false)}
      />
    </div>
  );
}
