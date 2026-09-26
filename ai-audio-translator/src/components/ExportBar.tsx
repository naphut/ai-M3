import React, { useState } from 'react';
import { Download, FileText, Code2, Film, Check, Eye, Copy, Sparkles } from 'lucide-react';
import { TranslationResult } from '../types/translator';
import { exportToSrt, exportToVtt, exportToTxt, exportToJson, downloadFile } from '../utils/subtitles';
import { sendSubtitlesToDesktopStudio } from '../utils/desktopBridge';

interface ExportBarProps {
  result: TranslationResult;
  fileName?: string;
}

export const ExportBar: React.FC<ExportBarProps> = ({ result, fileName = 'audio_translation' }) => {
  const [bilingualMode, setBilingualMode] = useState<boolean>(true);
  const [previewModal, setPreviewModal] = useState<'srt' | 'vtt' | 'txt' | 'json' | null>(null);
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null);

  const [isExportingToStudio, setIsExportingToStudio] = useState(false);
  const [studioExportSuccess, setStudioExportSuccess] = useState(false);

  const baseFileName = fileName.replace(/\.[^/.]+$/, '');

  const handleDownloadSrt = () => {
    const srt = exportToSrt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    downloadFile(srt, `${baseFileName}.srt`, 'application/x-subrip');
  };

  const handleDownloadVtt = () => {
    const vtt = exportToVtt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    downloadFile(vtt, `${baseFileName}.vtt`, 'text/vtt');
  };

  const handleDownloadTxt = () => {
    const txt = exportToTxt(result, bilingualMode ? 'bilingual' : 'translatedOnly');
    downloadFile(txt, `${baseFileName}_transcript.txt`, 'text/plain');
  };

  const handleDownloadJson = () => {
    const json = exportToJson(result);
    downloadFile(json, `${baseFileName}.json`, 'application/json');
  };

  const handleCopySrt = () => {
    const srt = exportToSrt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    navigator.clipboard.writeText(srt);
    setCopiedFormat('srt');
    setTimeout(() => setCopiedFormat(null), 2500);
  };

  const handleSendToDesktopStudio = async () => {
    setIsExportingToStudio(true);
    try {
      const srt = exportToSrt(result.segments, 'translated');
      const ok = await sendSubtitlesToDesktopStudio(srt, result.segments);
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

  const handleCopyAll = (format: 'srt' | 'vtt' | 'txt' | 'json') => {
    let content = '';
    if (format === 'srt') content = exportToSrt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    if (format === 'vtt') content = exportToVtt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    if (format === 'txt') content = exportToTxt(result, bilingualMode ? 'bilingual' : 'translatedOnly');
    if (format === 'json') content = exportToJson(result);

    navigator.clipboard.writeText(content);
    setCopiedFormat(format);
    setTimeout(() => setCopiedFormat(null), 2500);
  };

  const getPreviewContent = () => {
    if (previewModal === 'srt') return exportToSrt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    if (previewModal === 'vtt') return exportToVtt(result.segments, bilingualMode ? 'bilingual' : 'translated');
    if (previewModal === 'txt') return exportToTxt(result, bilingualMode ? 'bilingual' : 'translatedOnly');
    if (previewModal === 'json') return exportToJson(result);
    return '';
  };

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-6 shadow-2xl backdrop-blur-md">
      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4 pb-3 border-b border-slate-800/80">
        <div>
          <h4 className="text-base font-bold text-slate-100 flex items-center gap-2">
            <Download className="w-4 h-4 text-amber-400" />
            <span>ទាញយក និងនាំចេញ Subtitle (Export & Copy SRT)</span>
          </h4>
          <p className="text-xs text-slate-400 mt-0.5">
            ទាញយក ឬចម្លងកូដ Subtitle ទៅដាក់ក្នុង CapCut, Adobe Premiere, DaVinci ឬ VLC
          </p>
        </div>

        {/* Subtitle format toggle */}
        <div className="flex items-center gap-2 bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
          <span className="text-slate-400 px-2">Subtitle:</span>
          <button
            type="button"
            onClick={() => setBilingualMode(true)}
            className={`px-2.5 py-1 rounded-lg font-medium transition cursor-pointer ${
              bilingualMode
                ? 'bg-amber-500 text-slate-950 font-bold'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            ទ្វេភាសា (Bilingual)
          </button>
          <button
            type="button"
            onClick={() => setBilingualMode(false)}
            className={`px-2.5 py-1 rounded-lg font-medium transition cursor-pointer ${
              !bilingualMode
                ? 'bg-amber-500 text-slate-950 font-bold'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            ខ្មែរសុទ្ធ (Khmer Only)
          </button>
        </div>
      </div>

      {/* Prominent One-Click Copy SRT Hero Banner */}
      <div className="mb-4 p-3.5 rounded-2xl bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-amber-500/20 text-amber-400 shrink-0">
            <Film className="w-4 h-4" />
          </div>
          <div>
            <span className="text-xs font-bold text-amber-300">
              ចម្លងកូដ SRT ភ្លាមៗ (Quick Copy SRT to Clipboard)
            </span>
            <p className="text-[11px] text-slate-300">
              {bilingualMode ? 'ទម្រង់: ខ្មែរ + ភាសាដើម' : 'ទម្រង់: ភាសាខ្មែរសុទ្ធ'} • {result.segments.length} ឃ្លា Subtitles
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Send to Desktop Studio Button */}
          <button
            type="button"
            onClick={handleSendToDesktopStudio}
            disabled={isExportingToStudio}
            className={`px-4 py-2.5 rounded-xl font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer shadow-lg active:scale-95 ${
              studioExportSuccess
                ? 'bg-emerald-600 text-white shadow-emerald-500/20'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-500/20'
            }`}
            title="Send translated subtitles directly to PySide6 Desktop Dubbing Studio"
          >
            {studioExportSuccess ? (
              <>
                <Check className="w-4 h-4 text-white" />
                <span>បានបញ្ជូនទៅ Desktop Studio! 🎬</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4 text-amber-300" />
                <span>{isExportingToStudio ? 'កំពុងបញ្ជូន...' : '🚀 បញ្ជូនទៅ Desktop Studio'}</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleCopySrt}
            className={`px-5 py-2.5 rounded-xl font-bold text-xs flex items-center justify-center gap-2 transition-all cursor-pointer shadow-lg active:scale-95 ${
              copiedFormat === 'srt'
                ? 'bg-emerald-500 text-white shadow-emerald-500/20'
                : 'bg-amber-500 hover:bg-amber-400 text-slate-950 shadow-amber-500/20'
            }`}
          >
            {copiedFormat === 'srt' ? (
              <>
                <Check className="w-4 h-4 text-white" />
                <span>បានចម្លង SRT រួចរាល់! (Copied)</span>
              </>
            ) : (
              <>
                <Copy className="w-4 h-4" />
                <span>[ 📋 Copy SRT ភ្លាមៗ ]</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Buttons Row matching [ TXT ] [ SRT ] [ VTT ] [ JSON ] [ Export ] */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {/* TXT */}
        <button
          type="button"
          onClick={handleDownloadTxt}
          className="flex flex-col items-center justify-center gap-1.5 p-3.5 rounded-2xl bg-slate-800 hover:bg-slate-700/90 text-slate-100 border border-slate-700 hover:border-amber-500/40 transition active:scale-95 group cursor-pointer"
        >
          <FileText className="w-5 h-5 text-amber-400 group-hover:scale-110 transition" />
          <span className="text-sm font-bold">[ TXT ]</span>
          <span className="text-[10px] text-slate-400">Plain Transcript</span>
        </button>

        {/* SRT */}
        <button
          type="button"
          onClick={handleDownloadSrt}
          className="flex flex-col items-center justify-center gap-1.5 p-3.5 rounded-2xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 hover:border-amber-500/60 transition active:scale-95 group cursor-pointer shadow-lg shadow-amber-500/5"
        >
          <Film className="w-5 h-5 text-amber-400 group-hover:scale-110 transition" />
          <span className="text-sm font-bold">[ SRT ]</span>
          <span className="text-[10px] text-amber-400/80">Download .srt</span>
        </button>

        {/* VTT */}
        <button
          type="button"
          onClick={handleDownloadVtt}
          className="flex flex-col items-center justify-center gap-1.5 p-3.5 rounded-2xl bg-slate-800 hover:bg-slate-700/90 text-slate-100 border border-slate-700 hover:border-amber-500/40 transition active:scale-95 group cursor-pointer"
        >
          <Film className="w-5 h-5 text-sky-400 group-hover:scale-110 transition" />
          <span className="text-sm font-bold">[ VTT ]</span>
          <span className="text-[10px] text-slate-400">WebVTT Subtitle</span>
        </button>

        {/* JSON */}
        <button
          type="button"
          onClick={handleDownloadJson}
          className="flex flex-col items-center justify-center gap-1.5 p-3.5 rounded-2xl bg-slate-800 hover:bg-slate-700/90 text-slate-100 border border-slate-700 hover:border-amber-500/40 transition active:scale-95 group cursor-pointer"
        >
          <Code2 className="w-5 h-5 text-emerald-400 group-hover:scale-110 transition" />
          <span className="text-sm font-bold">[ JSON ]</span>
          <span className="text-[10px] text-slate-400">Structured Data</span>
        </button>

        {/* Quick Preview & All */}
        <button
          type="button"
          onClick={() => setPreviewModal('srt')}
          className="col-span-2 sm:col-span-1 flex flex-col items-center justify-center gap-1.5 p-3.5 rounded-2xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 hover:border-amber-500/40 transition active:scale-95 group cursor-pointer"
        >
          <Eye className="w-5 h-5 text-amber-400 group-hover:scale-110 transition" />
          <span className="text-sm font-extrabold">[ Preview ]</span>
          <span className="text-[10px] text-slate-400">ពិនិត្យកូដមុនទាញយក</span>
        </button>
      </div>

      {/* Preview Modal */}
      {previewModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-2xl w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-4">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-100 text-base">
                  Preview [{previewModal.toUpperCase()}]
                </span>
                <div className="flex items-center gap-1 ml-3 bg-slate-950 p-1 rounded-lg border border-slate-800">
                  {(['srt', 'vtt', 'txt', 'json'] as const).map((fmt) => (
                    <button
                      key={fmt}
                      type="button"
                      onClick={() => setPreviewModal(fmt)}
                      className={`px-2 py-0.5 text-xs font-mono font-semibold rounded-md transition ${
                        previewModal === fmt
                          ? 'bg-amber-500 text-slate-950'
                          : 'text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {fmt.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              <button
                type="button"
                onClick={() => setPreviewModal(null)}
                className="p-1 text-slate-400 hover:text-slate-200 rounded-lg cursor-pointer"
              >
                ✕
              </button>
            </div>

            <pre className="w-full bg-slate-950 rounded-2xl p-4 text-xs font-mono text-slate-300 max-h-96 overflow-y-auto border border-slate-800 whitespace-pre-wrap select-text">
              {getPreviewContent()}
            </pre>

            <div className="flex items-center justify-between mt-4">
              <span className="text-xs text-slate-400">
                {result.segments.length} segments formatted
              </span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => handleCopyAll(previewModal)}
                  className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold flex items-center gap-1.5 transition cursor-pointer"
                >
                  {copiedFormat === previewModal ? (
                    <>
                      <Check className="w-4 h-4 text-emerald-400" />
                      បានចម្លងរួចរាល់!
                    </>
                  ) : (
                    <>
                      <Copy className="w-4 h-4" />
                      ចម្លងកូដ (Copy Content)
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (previewModal === 'srt') handleDownloadSrt();
                    if (previewModal === 'vtt') handleDownloadVtt();
                    if (previewModal === 'txt') handleDownloadTxt();
                    if (previewModal === 'json') handleDownloadJson();
                  }}
                  className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold flex items-center gap-1.5 transition cursor-pointer"
                >
                  <Download className="w-4 h-4" />
                  ទាញយកឯកសារ (Download)
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
