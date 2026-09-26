import React, { useState, useEffect } from 'react';
import { ArrowRight, Wand2, Loader2, Zap, CheckCircle2, Gauge, Flame } from 'lucide-react';

interface LanguageSelectorProps {
  onStartTranslation: () => void;
  isProcessing: boolean;
  hasAudio: boolean;
  queueCount?: number;
  speedMode: 'turbo' | 'standard';
  onSpeedModeChange: (mode: 'turbo' | 'standard') => void;
}

export const LanguageSelector: React.FC<LanguageSelectorProps> = ({
  onStartTranslation,
  isProcessing,
  hasAudio,
  queueCount = 0,
  speedMode,
  onSpeedModeChange,
}) => {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    if (isProcessing) {
      setElapsed(0);
      timer = setInterval(() => {
        setElapsed((sec) => sec + 1);
      }, 1000);
    } else {
      setElapsed(0);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isProcessing]);

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-5">
        <div>
          <h4 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <span>AI Translation & SRT Speed / ការកំណត់ល្បឿនបកប្រែ</span>
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            ប្រព័ន្ធដំណើរការ Auto Detect គ្រប់ភាសា និងបកប្រែចេញជា Subtitle ខ្មែរ (SRT) យ៉ាងរហ័ស
          </p>
        </div>

        {/* Speed Mode Selector */}
        <div className="flex items-center p-1 bg-slate-950 rounded-xl border border-slate-800 shadow-inner self-start sm:self-auto">
          <button
            type="button"
            onClick={() => onSpeedModeChange('turbo')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
              speedMode === 'turbo'
                ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/25'
                : 'text-slate-400 hover:text-slate-200'
            }`}
            title="Turbo AI Mode: កាត់បន្ថយ Latency ដល់កម្រិតទាបបំផុត ដើម្បីបង្កើត SRT លឿនបំផុត"
          >
            <Flame className="w-3.5 h-3.5 fill-current" />
            <span>⚡ Turbo SRT (លឿនបំផុត)</span>
          </button>

          <button
            type="button"
            onClick={() => onSpeedModeChange('standard')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
              speedMode === 'standard'
                ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/25'
                : 'text-slate-400 hover:text-slate-200'
            }`}
            title="Standard Mode: បកប្រែជាមួយការពន្យល់លម្អិត"
          >
            <Gauge className="w-3.5 h-3.5" />
            <span>Standard (ធម្មតា)</span>
          </button>
        </div>
      </div>

      {/* Streamlined Language Display (Auto Detect -> 🇰🇭 Khmer) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-5">
        {/* From: Auto Detect */}
        <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 flex items-center justify-between">
          <div>
            <span className="text-xs text-slate-400 block mb-0.5">From (ភាសាដើម):</span>
            <div className="flex items-center gap-2">
              <span className="text-lg">🌐</span>
              <div>
                <span className="text-sm font-bold text-slate-200">Auto Detect (ស្វ័យប្រវត្តិ)</span>
                <p className="text-[11px] text-slate-400">
                  កូរ៉េ 🇰🇷, អង់គ្លេស 🇺🇸, ជប៉ុន 🇯🇵, ចិន 🇨🇳, ថៃ 🇹🇭...
                </p>
              </div>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded-md bg-slate-800 text-[10px] font-mono text-slate-300 border border-slate-700">
            AUTO
          </span>
        </div>

        {/* To: Khmer Only */}
        <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-between">
          <div>
            <span className="text-xs text-amber-400/90 block mb-0.5">To (បកប្រែជា Subtitle ខ្មែរ):</span>
            <div className="flex items-center gap-2">
              <span className="text-xl">🇰🇭</span>
              <div>
                <span className="text-sm font-extrabold text-amber-300">ភាសាខ្មែរ (Khmer SRT)</span>
                <p className="text-[11px] text-amber-400/70">
                  បកប្រែត្រឹមត្រូវតាមពេលវេលា Subtitle ជាមួយវេយ្យាករណ៍ខ្មែរ
                </p>
              </div>
            </div>
          </div>
          <span className="px-2 py-0.5 rounded-md bg-amber-500/20 text-[10px] font-mono font-bold text-amber-300 border border-amber-500/30 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" />
            SRT
          </span>
        </div>
      </div>

      {/* Turbo Fast Notice */}
      {speedMode === 'turbo' && (
        <div className="mb-4 px-3.5 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs flex items-center gap-2 text-amber-300">
          <Zap className="w-4 h-4 text-amber-400 shrink-0 fill-current" />
          <span>
            <strong>មុខងារ Turbo SRT បានបើក:</strong> ប្រើប្រាស់ AI Minimal Latency Pipeline ដើម្បីទាញយក Subtitle SRT បានលឿនជាងមុន 3x ទៅ 5x!
          </span>
        </div>
      )}

      {/* Start Translation Button */}
      <button
        type="button"
        onClick={onStartTranslation}
        disabled={!hasAudio || isProcessing}
        className={`w-full py-4 px-6 rounded-2xl font-bold text-base transition-all flex items-center justify-center gap-3 shadow-xl ${
          isProcessing
            ? 'bg-amber-600/50 text-amber-200 cursor-wait'
            : hasAudio
            ? 'bg-gradient-to-r from-amber-500 via-amber-400 to-amber-300 hover:from-amber-400 hover:to-amber-200 text-slate-950 shadow-amber-500/25 active:scale-[0.99] cursor-pointer'
            : 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700/50'
        }`}
      >
        {isProcessing ? (
          <>
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>
              {speedMode === 'turbo' ? '⚡ Turbo AI' : 'AI'} កំពុងបកប្រែជា SRT... ({elapsed}s)
            </span>
          </>
        ) : (
          <>
            {speedMode === 'turbo' ? (
              <Zap className="w-5 h-5 fill-current text-slate-950" />
            ) : (
              <Wand2 className="w-5 h-5" />
            )}
            <span>
              {speedMode === 'turbo' ? '[ ⚡ ចាប់ផ្តើមបកប្រែជា SRT លឿនបំផុត ]' : '[ Start AI Translation ]'}
              {queueCount > 1 ? ` (${queueCount} ឯកសារក្នុងជួរ)` : ''}
            </span>
            <ArrowRight className="w-4 h-4 ml-1" />
          </>
        )}
      </button>

      {!hasAudio && (
        <p className="text-center text-xs text-slate-500 mt-2.5">
          * សូម Upload ឯកសារ MP3 / Audio ដើម្បីចាប់ផ្តើមបកប្រែជា SRT
        </p>
      )}
    </div>
  );
};
