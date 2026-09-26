import React, { useState } from 'react';
import {
  ListMusic,
  Play,
  Pause,
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  RotateCw,
  Trash2,
  Eye,
  Archive,
  Volume2,
  Film,
  Zap,
  Flame,
} from 'lucide-react';
import JSZip from 'jszip';
import { QueueItem } from '../types/translator';
import { exportToSrt, downloadFile } from '../utils/subtitles';

interface AudioQueueManagerProps {
  queue: QueueItem[];
  activeItemId: string | null;
  isQueueRunning: boolean;
  isPaused: boolean;
  speedMode: 'turbo' | 'standard';
  onSpeedModeChange: (mode: 'turbo' | 'standard') => void;
  onSelectActiveItem: (id: string) => void;
  onStartQueue: () => void;
  onPauseQueue: () => void;
  onResumeQueue: () => void;
  onRetryItem: (id: string) => void;
  onRetryAllFailed: () => void;
  onRemoveItem: (id: string) => void;
  onClearCompleted: () => void;
  onClearAll: () => void;
}

export const AudioQueueManager: React.FC<AudioQueueManagerProps> = ({
  queue,
  activeItemId,
  isQueueRunning,
  isPaused,
  speedMode,
  onSpeedModeChange,
  onSelectActiveItem,
  onStartQueue,
  onPauseQueue,
  onResumeQueue,
  onRetryItem,
  onRetryAllFailed,
  onRemoveItem,
  onClearCompleted,
  onClearAll,
}) => {
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null);
  const [audioElement, setAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isExportingZip, setIsExportingZip] = useState(false);

  if (queue.length === 0) {
    return null;
  }

  // Calculate statistics
  const totalCount = queue.length;
  const completedCount = queue.filter((i) => i.status === 'completed').length;
  const pendingCount = queue.filter((i) => i.status === 'pending').length;
  const processingCount = queue.filter((i) => i.status === 'processing').length;
  const failedCount = queue.filter((i) => i.status === 'error').length;

  const overallPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  // Audio preview playback toggle
  const togglePlayAudio = (item: QueueItem) => {
    if (playingAudioId === item.id) {
      audioElement?.pause();
      setPlayingAudioId(null);
    } else {
      if (audioElement) {
        audioElement.pause();
      }
      const audio = new Audio(item.objectUrl);
      audio.onended = () => setPlayingAudioId(null);
      audio.play().catch(() => setPlayingAudioId(null));
      setAudioElement(audio);
      setPlayingAudioId(item.id);
    }
  };

  // Helper format seconds
  const formatDuration = (seconds: number) => {
    if (!seconds || isNaN(seconds)) return '00:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Direct 1-click download of single item's SRT
  const handleDownloadSingleSrt = (item: QueueItem) => {
    if (!item.result) return;
    const baseName = item.name.replace(/\.[^/.]+$/, '');
    const srtContent = item.result.srtText || exportToSrt(item.result.segments, 'translated');
    downloadFile(srtContent, `${baseName}_khmer.srt`, 'application/x-subrip');
  };

  // Batch Export all completed transcripts as a ZIP archive
  const handleExportZip = async () => {
    const completedItems = queue.filter((i) => i.status === 'completed' && i.result);
    if (completedItems.length === 0) return;

    setIsExportingZip(true);
    try {
      const zip = new JSZip();
      const folder = zip.folder('khmer_transcripts_batch');

      completedItems.forEach((item, index) => {
        if (!item.result) return;
        const baseName = item.name.replace(/\.[^/.]+$/, '');
        const filePrefix = `${(index + 1).toString().padStart(2, '0')}_${baseName}`;

        // 1. SRT file (Pre-computed or generated)
        const srtContent = item.result.srtText || exportToSrt(item.result.segments, 'translated');
        folder?.file(`${filePrefix}.srt`, srtContent);

        // 2. Bilingual SRT file
        const bilingualSrt = exportToSrt(item.result.segments, 'bilingual');
        folder?.file(`${filePrefix}_bilingual.srt`, bilingualSrt);

        // 3. Full Khmer Text
        let txtContent = `ឯកសារ: ${item.name}\nសេចក្តីសង្ខេប: ${item.result.summary}\nភាសាដើម: ${item.result.detectedLanguage}\n\n`;
        item.result.segments.forEach((seg) => {
          txtContent += `[${seg.startTime} - ${seg.endTime}] ${seg.speaker ? `${seg.speaker}: ` : ''}${seg.translatedText}\n`;
        });
        folder?.file(`${filePrefix}_khmer.txt`, txtContent);

        // 4. JSON structured data
        folder?.file(`${filePrefix}.json`, JSON.stringify(item.result, null, 2));
      });

      const content = await zip.generateAsync({ type: 'blob' });
      const url = URL.createObjectURL(content);
      const a = document.createElement('a');
      a.href = url;
      a.download = `Khmer_Audio_Transcripts_Batch_${new Date().toISOString().slice(0, 10)}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export zip:', err);
    } finally {
      setIsExportingZip(false);
    }
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-5 sm:p-6 shadow-xl space-y-5">
      {/* Top Header of Queue */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 flex items-center justify-center">
            <ListMusic className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold text-slate-100">
                ជួរឯកសារដំណើរការ (Audio Queue)
              </h3>
              <span className="px-2 py-0.5 rounded-full bg-slate-800 text-amber-400 text-xs font-bold border border-slate-700">
                {totalCount} ឯកសារ
              </span>
              {speedMode === 'turbo' && (
                <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[10px] font-bold border border-amber-500/30 flex items-center gap-1">
                  <Zap className="w-3 h-3 fill-current" />
                  Turbo SRT
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              ដំណើរការបកប្រែជា Subtitle ខ្មែរ (SRT) យ៉ាងរហ័ស ជាមួយ Minimal Latency Pipeline
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Turbo toggle in queue */}
          <button
            type="button"
            onClick={() => onSpeedModeChange(speedMode === 'turbo' ? 'standard' : 'turbo')}
            className={`px-3 py-2 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
              speedMode === 'turbo'
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 shadow-sm'
                : 'bg-slate-800 text-slate-400 border border-slate-700'
            }`}
            title="ចុចដើម្បីប្តូររវាង Turbo SRT Mode និង Standard Mode"
          >
            <Flame className="w-3.5 h-3.5 fill-current text-amber-400" />
            <span>{speedMode === 'turbo' ? '⚡ Turbo Mode ON' : 'Turbo Mode OFF'}</span>
          </button>

          {/* Main Run / Pause / Resume Button */}
          {!isQueueRunning ? (
            <button
              type="button"
              onClick={onStartQueue}
              disabled={pendingCount === 0 && failedCount === 0}
              className="px-5 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-400 disabled:bg-slate-800 disabled:text-slate-600 disabled:border-slate-800 text-slate-950 font-bold text-xs shadow-lg shadow-amber-500/20 transition active:scale-95 flex items-center gap-2 cursor-pointer"
            >
              <Zap className="w-4 h-4 fill-current" />
              <span>
                {completedCount > 0 && pendingCount > 0
                  ? `បន្តបកប្រែ ${pendingCount} ឯកសារទៀត`
                  : '⚡ បកប្រែជា SRT ទាំងអស់ (Process All)'}
              </span>
            </button>
          ) : isPaused ? (
            <button
              type="button"
              onClick={onResumeQueue}
              className="px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs transition active:scale-95 flex items-center gap-1.5 cursor-pointer shadow-lg shadow-emerald-500/20"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>បន្តដំណើរការ (Resume)</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onPauseQueue}
              className="px-4 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-400 border border-amber-500/40 font-bold text-xs transition active:scale-95 flex items-center gap-1.5 cursor-pointer"
            >
              <Pause className="w-3.5 h-3.5 fill-current" />
              <span>ផ្អាកបណ្តោះអាសន្ន (Pause)</span>
            </button>
          )}

          {/* Retry all failed */}
          {failedCount > 0 && !isQueueRunning && (
            <button
              type="button"
              onClick={onRetryAllFailed}
              className="px-3.5 py-2 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer"
              title="សាកល្បងឯកសារដែលបរាជ័យឡើងវិញ"
            >
              <RotateCw className="w-3.5 h-3.5" />
              <span>សាកល្បងបរាជ័យ ({failedCount})</span>
            </button>
          )}

          {/* Batch Export Zip */}
          {completedCount > 0 && (
            <button
              type="button"
              onClick={handleExportZip}
              disabled={isExportingZip}
              className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer"
              title="ទាញយកអត្ថបទបកប្រែទាំងអស់ជាឯកសារ ZIP (SRT, TXT, JSON)"
            >
              {isExportingZip ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
              ) : (
                <Archive className="w-3.5 h-3.5 text-amber-400" />
              )}
              <span>ទាញយកទាំងអស់ (.ZIP)</span>
            </button>
          )}

          {/* Clear Completed */}
          {completedCount > 0 && !isQueueRunning && (
            <button
              type="button"
              onClick={onClearCompleted}
              className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition cursor-pointer"
              title="សម្អាតឯកសារដែលរួចរាល់"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}

          {/* Clear All */}
          {!isQueueRunning && (
            <button
              type="button"
              onClick={onClearAll}
              className="px-3 py-2 text-xs font-medium text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl transition cursor-pointer"
            >
              លុបទាំងអស់
            </button>
          )}
        </div>
      </div>

      {/* Global Queue Progress Bar */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-3">
            <span className="font-semibold text-slate-300">
              វឌ្ឍនភាពសរុប (Overall Progress):
            </span>
            <span className="text-amber-400 font-mono font-bold">
              {completedCount} / {totalCount} បានបញ្ចប់ ({overallPercent}%)
            </span>
          </div>

          <div className="flex items-center gap-3 text-slate-400 text-[11px]">
            {processingCount > 0 && (
              <span className="flex items-center gap-1 text-amber-400">
                <Loader2 className="w-3 h-3 animate-spin" /> កំពុងដំណើរការ 1
              </span>
            )}
            {pendingCount > 0 && <span>រង់ចាំ: {pendingCount}</span>}
            {failedCount > 0 && <span className="text-rose-400">បរាជ័យ: {failedCount}</span>}
          </div>
        </div>

        {/* Bar */}
        <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden relative">
          <div
            className={`h-full transition-all duration-500 rounded-full ${
              overallPercent === 100
                ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
                : 'bg-gradient-to-r from-amber-500 to-orange-400'
            }`}
            style={{ width: `${overallPercent}%` }}
          />
        </div>
      </div>

      {/* Queue Items List */}
      <div className="space-y-2.5 max-h-[380px] overflow-y-auto pr-1">
        {queue.map((item, index) => {
          const isActive = activeItemId === item.id;
          const isPlayingThis = playingAudioId === item.id;

          return (
            <div
              key={item.id}
              className={`group p-3.5 rounded-2xl border transition-all ${
                isActive
                  ? 'bg-slate-800/80 border-amber-500/60 shadow-lg shadow-amber-500/5'
                  : 'bg-slate-900/60 hover:bg-slate-850 border-slate-800/80 hover:border-slate-700'
              }`}
            >
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                {/* Left: Index + Play Button + File Info */}
                <div className="flex items-center gap-3 min-w-0 flex-1">
                  <div className="w-6 h-6 rounded-lg bg-slate-800 text-slate-400 text-xs font-mono font-bold flex items-center justify-center shrink-0 border border-slate-700/60">
                    {index + 1}
                  </div>

                  <button
                    type="button"
                    onClick={() => togglePlayAudio(item)}
                    className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition cursor-pointer ${
                      isPlayingThis
                        ? 'bg-amber-500 text-slate-950 font-bold'
                        : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'
                    }`}
                    title={isPlayingThis ? 'ផ្អាកសំឡេង' : 'ស្តាប់សំឡេងដើម'}
                  >
                    {isPlayingThis ? (
                      <Pause className="w-4 h-4 fill-current" />
                    ) : (
                      <Volume2 className="w-4 h-4" />
                    )}
                  </button>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-slate-100 truncate">
                        {item.name}
                      </p>
                      {isActive && (
                        <span className="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-400 text-[10px] font-bold border border-amber-500/30 shrink-0">
                          កំពុងមើល
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {(item.size / (1024 * 1024)).toFixed(2)} MB • {formatDuration(item.duration)} •{' '}
                      <span className="uppercase">{item.mimeType.split('/')[1] || 'AUDIO'}</span>
                    </p>
                  </div>
                </div>

                {/* Right: Status Badge & Row Action Buttons */}
                <div className="flex items-center gap-2 shrink-0 self-end sm:self-center flex-wrap">
                  {/* Status Badge */}
                  {item.status === 'completed' && (
                    <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-emerald-500/10 text-emerald-400 text-xs font-semibold border border-emerald-500/20">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>បានបញ្ចប់</span>
                      {item.completedAt && item.startedAt && (
                        <span className="text-[10px] font-mono text-amber-300 ml-0.5">
                          ⚡ {((item.completedAt - item.startedAt) / 1000).toFixed(1)}s
                        </span>
                      )}
                    </span>
                  )}

                  {item.status === 'processing' && (
                    <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-amber-500/10 text-amber-400 text-xs font-semibold border border-amber-500/30 animate-pulse">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>{item.progressStep || 'កំពុងបកប្រែ...'}</span>
                      <span className="font-mono">{item.progress}%</span>
                    </span>
                  )}

                  {item.status === 'pending' && (
                    <span className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-slate-800 text-slate-400 text-xs font-semibold border border-slate-700">
                      <Clock className="w-3.5 h-3.5" />
                      <span>រង់ចាំក្នុងជួរ</span>
                    </span>
                  )}

                  {item.status === 'error' && (
                    <span
                      className="flex items-center gap-1.5 px-3 py-1 rounded-xl bg-rose-500/10 text-rose-400 text-xs font-semibold border border-rose-500/20"
                      title={item.error || 'កំហុស'}
                    >
                      <AlertCircle className="w-3.5 h-3.5" />
                      <span>បរាជ័យ</span>
                    </span>
                  )}

                  {/* 1-Click Fast SRT Download Button for completed items */}
                  {item.result && (
                    <button
                      type="button"
                      onClick={() => handleDownloadSingleSrt(item)}
                      className="px-2.5 py-1.5 rounded-xl text-xs font-bold bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 transition flex items-center gap-1 cursor-pointer shadow-sm"
                      title="ទាញយក SRT ឯកសារនេះភ្លាមៗ"
                    >
                      <Film className="w-3.5 h-3.5 text-amber-400" />
                      <span>⚡ SRT</span>
                    </button>
                  )}

                  {/* View Result button */}
                  {item.result && (
                    <button
                      type="button"
                      onClick={() => onSelectActiveItem(item.id)}
                      className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition flex items-center gap-1.5 cursor-pointer ${
                        isActive
                          ? 'bg-amber-500 text-slate-950 font-bold'
                          : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700'
                      }`}
                      title="មើលលទ្ធផលបកប្រែ និង Subtitles"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      <span>មើលលទ្ធផល</span>
                    </button>
                  )}

                  {/* Retry Single Item */}
                  {item.status === 'error' && !isQueueRunning && (
                    <button
                      type="button"
                      onClick={() => onRetryItem(item.id)}
                      className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-amber-400 border border-slate-700 transition cursor-pointer"
                      title="សាកល្បងបកប្រែឯកសារនេះម្តងទៀត"
                    >
                      <RotateCw className="w-3.5 h-3.5" />
                    </button>
                  )}

                  {/* Remove Item */}
                  {!isQueueRunning && (
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item.id)}
                      className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition cursor-pointer"
                      title="លុបឯកសារនេះចេញពីជួរ"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>

              {/* Individual Item Progress Bar */}
              {(item.status === 'processing' || item.status === 'converting') && (
                <div className="mt-3 space-y-1">
                  <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-amber-400 transition-all duration-300 rounded-full"
                      style={{ width: `${Math.max(5, item.progress)}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Error message detail if failed */}
              {item.status === 'error' && item.error && (
                <div className="mt-2 text-[11px] text-rose-400/90 bg-rose-500/5 border border-rose-500/20 rounded-lg p-2">
                  {item.error}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
