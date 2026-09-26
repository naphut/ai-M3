import React from 'react';
import { ArrowDown, ArrowRight, Sparkles, CheckCircle2, Film, FileText, Zap } from 'lucide-react';
import { TranslationResult, QueueItemStatus } from '../types/translator';

interface GenerationPipelineBannerProps {
  status?: QueueItemStatus;
  progressStep?: string;
  result: TranslationResult | null;
  activeTab: 'khmer' | 'srt' | 'preview';
  onTabChange: (tab: 'khmer' | 'srt' | 'preview') => void;
  fileName?: string;
}

export const GenerationPipelineBanner: React.FC<GenerationPipelineBannerProps> = ({
  status = 'pending',
  progressStep = '',
  result,
  activeTab,
  onTabChange,
  fileName = '',
}) => {
  const isVideo = fileName.match(/\.(mp4|mov|webm|mkv|avi)$/i);
  const isCompleted = !!result;
  const isProcessing = status === 'processing';

  // Determine which step is currently active
  const isStage1Active = isProcessing && (!progressStep || progressStep.includes('Upload') || progressStep.includes('FFmpeg') || progressStep.includes('AI'));
  const isStage2Active = isProcessing && (progressStep.includes('បកប្រែ') || progressStep.includes('ភាសាខ្មែរ'));
  const isStage3Active = isCompleted;

  return (
    <div className="bg-gradient-to-b from-slate-900 to-slate-950 border border-slate-800 rounded-3xl p-5 sm:p-6 shadow-2xl space-y-4">
      {/* Title */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-800/80">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center">
            <Zap className="w-5 h-5 fill-current" />
          </div>
          <div>
            <h4 className="text-base font-extrabold text-slate-100 flex items-center gap-2">
              <span>ដំណើរការបំប្លែង ៣ ជំហាន (3-Stage Generation Pipeline)</span>
            </h4>
            <p className="text-xs text-slate-400">
              {isVideo ? 'វីដេអូ MP4' : 'សំឡេង Audio'} ➔ AI Translation ➔ 🇰🇭 Khmer Translation ➔ 📄 SRT Subtitles
            </p>
          </div>
        </div>

        {isCompleted && (
          <span className="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs font-bold border border-emerald-500/30 flex items-center gap-1.5 self-start sm:self-auto">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>បង្កើត SRT រួចរាល់ ១០០%</span>
          </span>
        )}
      </div>

      {/* Visual Pipeline requested by user:
          AI Translation
               │
               ▼
          🇰🇭 Khmer Translation
               │
               ▼
          📄 SRT
      */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 relative">
        {/* Stage 1: AI Translation */}
        <div
          className={`p-4 rounded-2xl border transition-all ${
            isStage1Active
              ? 'bg-blue-500/10 border-blue-500/50 shadow-lg shadow-blue-500/10 scale-[1.02]'
              : isCompleted
              ? 'bg-slate-900/90 border-slate-800'
              : 'bg-slate-950/60 border-slate-800/60 opacity-80'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-blue-500/20 text-blue-400 border border-blue-500/30">
              STAGE 1
            </span>
            {isCompleted && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          </div>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-blue-400" />
            <h5 className="text-sm font-bold text-slate-100">AI Translation</h5>
          </div>
          <p className="text-xs text-slate-400">
            ស្ដាប់ និងចាប់សំឡេងនិយាយដើម ({result ? result.detectedLanguage : 'Auto Detect'})
          </p>
        </div>

        {/* Stage 2: Khmer Translation */}
        <div
          className={`p-4 rounded-2xl border transition-all ${
            isStage2Active
              ? 'bg-amber-500/10 border-amber-500/50 shadow-lg shadow-amber-500/10 scale-[1.02]'
              : isCompleted
              ? 'bg-amber-500/5 border-amber-500/30'
              : 'bg-slate-950/60 border-slate-800/60 opacity-80'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-amber-500/20 text-amber-300 border border-amber-500/30">
              STAGE 2
            </span>
            {isCompleted && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          </div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-base">🇰🇭</span>
            <h5 className="text-sm font-bold text-amber-300">Khmer Translation</h5>
          </div>
          <p className="text-xs text-slate-400">
            បកប្រែជាភាសាខ្មែរតាមឃ្លាសន្ទនាធម្មជាតិ និងត្រឹមត្រូវ
          </p>
        </div>

        {/* Stage 3: SRT Generation */}
        <div
          className={`p-4 rounded-2xl border transition-all ${
            isStage3Active
              ? 'bg-emerald-500/10 border-emerald-500/40 shadow-lg shadow-emerald-500/10 scale-[1.02]'
              : 'bg-slate-950/60 border-slate-800/60 opacity-80'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
              STAGE 3
            </span>
            {isCompleted && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
          </div>
          <div className="flex items-center gap-2 mb-1">
            <FileText className="w-4 h-4 text-emerald-400" />
            <h5 className="text-sm font-bold text-emerald-300">📄 SRT Subtitles</h5>
          </div>
          <p className="text-xs text-slate-400">
            បង្កើតកូដ Subtitle SRT ជាមួយម៉ោង Timestamp ស្រេចភ្លាមៗ
          </p>
        </div>
      </div>

      {/* Tabs Navigation for Completed Result */}
      {isCompleted && (
        <div className="pt-2 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center p-1 bg-slate-950 rounded-xl border border-slate-800 text-xs">
            <button
              type="button"
              onClick={() => onTabChange('khmer')}
              className={`px-3.5 py-1.5 rounded-lg font-bold transition cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'khmer'
                  ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <span>🇰🇭 អត្ថបទបកប្រែខ្មែរ</span>
              <span className="text-[10px] opacity-80 font-mono">({result.segments.length})</span>
            </button>

            <button
              type="button"
              onClick={() => onTabChange('srt')}
              className={`px-3.5 py-1.5 rounded-lg font-bold transition cursor-pointer flex items-center gap-1.5 ${
                activeTab === 'srt'
                  ? 'bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>📄 កូដ SRT ស្រេច (SRT Output)</span>
            </button>

            {isVideo && (
              <button
                type="button"
                onClick={() => onTabChange('preview')}
                className={`px-3.5 py-1.5 rounded-lg font-bold transition cursor-pointer flex items-center gap-1.5 ${
                  activeTab === 'preview'
                    ? 'bg-sky-500 text-slate-950 shadow-md shadow-sky-500/20'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Film className="w-3.5 h-3.5" />
                <span>🎬 មើលជាមួយវីដេអូ</span>
              </button>
            )}
          </div>

          <div className="text-xs text-slate-400 font-mono">
            {result.segments.length} ឃ្លា • {result.detectedLanguage} ➔ ភាសាខ្មែរ
          </div>
        </div>
      )}
    </div>
  );
};
