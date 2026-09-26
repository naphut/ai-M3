import React, { useState } from 'react';
import { Film, Copy, Check, Download, Search, CheckCircle2, FileCode, Sparkles } from 'lucide-react';
import { TranslationResult } from '../types/translator';
import { exportToSrt, downloadFile, cleanSpeakerTagFromText } from '../utils/subtitles';
import { sendSubtitlesToDesktopStudio } from '../utils/desktopBridge';

interface SrtCodeViewProps {
  result: TranslationResult;
  fileName?: string;
}

export const SrtCodeView: React.FC<SrtCodeViewProps> = ({
  result,
  fileName = 'subtitles',
}) => {
  const [bilingual, setBilingual] = useState<boolean>(false);
  const [includeSpeakerTag, setIncludeSpeakerTag] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);
  const [search, setSearch] = useState<string>('');
  const [isExportingToStudio, setIsExportingToStudio] = useState(false);
  const [studioExportSuccess, setStudioExportSuccess] = useState(false);

  const baseName = fileName.replace(/\.[^/.]+$/, '');
  const srtContent = exportToSrt(result.segments, bilingual ? 'bilingual' : 'translated', includeSpeakerTag);

  const handleCopy = () => {
    navigator.clipboard.writeText(srtContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    downloadFile(srtContent, `${baseName}_khmer.srt`, 'application/x-subrip');
  };

  const handleSendToDesktopStudio = async () => {
    setIsExportingToStudio(true);
    try {
      const cleanSegments = result.segments.map((s) => ({
        ...s,
        translatedText: cleanSpeakerTagFromText(s.translatedText),
        sourceText: cleanSpeakerTagFromText(s.sourceText),
      }));
      const ok = await sendSubtitlesToDesktopStudio(srtContent, cleanSegments);
      if (ok) {
        setStudioExportSuccess(true);
        setTimeout(() => setStudioExportSuccess(false), 3000);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsExportingToStudio(false);
    }
  };

  // Filter segments if searching
  const displayedSegments = search.trim()
    ? result.segments.filter(
        (s) =>
          s.translatedText.toLowerCase().includes(search.toLowerCase()) ||
          s.sourceText.toLowerCase().includes(search.toLowerCase()) ||
          s.startTime.includes(search) ||
          (s.gender || '').toLowerCase().includes(search.toLowerCase()) ||
          (s.speaker || '').toLowerCase().includes(search.toLowerCase())
      )
    : result.segments;

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-5 sm:p-6 shadow-2xl space-y-4">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
            <FileCode className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <span>📄 កូដ Subtitle SRT (Direct SRT Output)</span>
            </h3>
            <p className="text-xs text-slate-400">
              ទម្រង់ SubRip (.srt) ជាមួយការសម្គាល់សំឡេង <strong className="text-amber-300">ប្រុស • ស្រី • ក្មេង</strong> ស្វ័យប្រវត្តិ
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Speaker Tag Toggle */}
          <button
            type="button"
            onClick={() => setIncludeSpeakerTag(!includeSpeakerTag)}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer border ${
              includeSpeakerTag
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-sm'
                : 'bg-slate-800 text-slate-400 border-slate-700'
            }`}
            title="ដាក់ស្លាក [ប្រុស], [ស្រី], [ក្មេង] ក្នុងកូដ SRT"
          >
            <span>👥 ដាក់ឈ្មោះតួអង្គ (Speaker Tags)</span>
            <span className={`px-1.5 py-0.2 rounded text-[10px] ${includeSpeakerTag ? 'bg-cyan-400 text-slate-950 font-extrabold' : 'bg-slate-700 text-slate-300'}`}>
              {includeSpeakerTag ? 'ON' : 'OFF'}
            </span>
          </button>

          {/* Format Toggle */}
          <div className="flex items-center p-1 bg-slate-950 rounded-xl border border-slate-800 text-xs">
            <button
              type="button"
              onClick={() => setBilingual(false)}
              className={`px-3 py-1 rounded-lg font-bold transition cursor-pointer ${
                !bilingual
                  ? 'bg-amber-500 text-slate-950 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              🇰🇭 ខ្មែរសុទ្ធ
            </button>
            <button
              type="button"
              onClick={() => setBilingual(true)}
              className={`px-3 py-1 rounded-lg font-bold transition cursor-pointer ${
                bilingual
                  ? 'bg-amber-500 text-slate-950 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              🌐+🇰🇭 ទ្វេភាសា (Bilingual)
            </button>
          </div>

          {/* Copy Button */}
          <button
            type="button"
            onClick={handleCopy}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer shadow-lg active:scale-95 ${
              copied
                ? 'bg-emerald-500 text-white'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-100 border border-slate-700'
            }`}
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>បានចម្លងរួចរាល់!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" />
                <span>📋 Copy SRT (Cmd+C)</span>
              </>
            )}
          </button>

          {/* Send to Desktop Studio Button */}
          <button
            type="button"
            onClick={handleSendToDesktopStudio}
            disabled={isExportingToStudio}
            className={`px-4 py-2 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer shadow-lg active:scale-95 ${
              studioExportSuccess
                ? 'bg-emerald-500 text-slate-950 font-extrabold'
                : 'bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-extrabold shadow-cyan-500/20'
            }`}
          >
            {studioExportSuccess ? (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>បានបញ្ជូនទៅ Desktop រួចរាល់!</span>
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                <span>🚀 បញ្ជូនទៅ Desktop Studio</span>
              </>
            )}
          </button>

          {/* Download Button */}
          <button
            type="button"
            onClick={handleDownload}
            className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold text-xs transition active:scale-95 flex items-center gap-1.5 cursor-pointer"
          >
            <Download className="w-3.5 h-3.5" />
            <span>.SRT</span>
          </button>
        </div>
      </div>

      {/* Search Input Bar */}
      <div className="relative">
        <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="ស្វែងរកក្នុងកូដ Subtitle SRT ឬតាមតួអង្គ (ប្រុស / ស្រី / ក្មេង)..."
          className="w-full bg-slate-950/80 border border-slate-800 focus:border-emerald-500/50 rounded-xl pl-9 pr-4 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none transition font-mono"
        />
      </div>

      {/* SRT Code Viewer */}
      <div className="bg-slate-950 rounded-2xl border border-slate-800 p-4 font-mono text-xs overflow-x-auto max-h-[460px] overflow-y-auto space-y-4 selection:bg-emerald-500/30 selection:text-emerald-200">
        {displayedSegments.map((seg, idx) => {
          const gender = (seg.gender || '').toLowerCase();
          const spk = seg.speaker || '';
          const isFemale = gender === 'female' || spk.includes('ស្រី') || spk.toLowerCase().includes('female');
          const isChild = gender === 'child' || spk.includes('ក្មេង') || spk.toLowerCase().includes('child');
          const speakerBadge = isFemale
            ? { label: '👩 ស្រី (Female)', color: 'bg-rose-500/20 text-rose-300 border-rose-500/40', tag: '[ស្រី]' }
            : isChild
            ? { label: '🧒 ក្មេង (Child)', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40', tag: '[ក្មេង]' }
            : { label: '👨 ប្រុស (Male)', color: 'bg-blue-500/20 text-cyan-300 border-blue-500/40', tag: '[ប្រុស]' };

          return (
            <div
              key={seg.id}
              className="p-3 rounded-xl bg-slate-900/50 hover:bg-slate-900 border border-slate-800/80 hover:border-emerald-500/30 transition group"
            >
              <div className="flex items-center justify-between mb-1">
                {/* SRT Index */}
                <div className="text-slate-500 font-bold">{idx + 1}</div>

                {/* Speaker Identity Badge */}
                <div className="flex items-center gap-1.5">
                  <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold border ${speakerBadge.color}`}>
                    {speakerBadge.label}
                  </span>
                </div>
              </div>

              {/* Timestamps */}
              <div className="text-amber-400 font-bold tracking-wide">
                {seg.startTime},000 --&gt; {seg.endTime},000
              </div>

              {/* Translated Khmer Subtitle with Tag */}
              <div className="text-emerald-300 font-sans text-sm font-semibold mt-1.5 flex items-start gap-1.5">
                {includeSpeakerTag && (
                  <span className="font-mono text-xs font-bold text-amber-300 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded shrink-0">
                    {speakerBadge.tag}
                  </span>
                )}
                <span>{seg.translatedText}</span>
              </div>

              {/* Original Spoken Text if Bilingual */}
              {bilingual && seg.sourceText && (
                <div className="text-slate-400 font-sans text-xs mt-1 opacity-80 pl-1 border-l-2 border-slate-700">
                  {seg.sourceText}
                </div>
              )}
            </div>
          );
        })}

        {displayedSegments.length === 0 && (
          <p className="text-center text-slate-500 py-6 font-sans">
            មិនមានកូដ Subtitle ដែលត្រូវនឹងពាក្យស្វែងរកឡើយ
          </p>
        )}
      </div>

      {/* Footer Info */}
      <div className="flex items-center justify-between text-[11px] text-slate-500 px-1">
        <span>កូដ SRT ស្របតាមស្តង់ដារ UTF-8 គាំទ្រពុម្ពអក្សរខ្មែរគ្រប់កម្មវិធីកាត់ត</span>
        <span className="font-mono text-slate-400">{result.segments.length} Subtitle Blocks</span>
      </div>
    </div>
  );
};
