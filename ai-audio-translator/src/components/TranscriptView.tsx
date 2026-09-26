import React, { useState, useRef } from 'react';
import {
  Play,
  Copy,
  Check,
  Edit2,
  Search,
  Sparkles,
  Volume2,
  Film,
  Trash2,
  Columns,
  Rows,
  Save,
  X,
  Languages,
  Loader2,
} from 'lucide-react';
import { Segment, TranslationResult, PERSONA_OPTIONS, EMOTION_OPTIONS, STYLE_OPTIONS } from '../types/translator';
import { formatTimeDisplay, exportToSrt } from '../utils/subtitles';

interface TranscriptViewProps {
  result: TranslationResult;
  currentTime: number;
  onJumpToTime: (seconds: number) => void;
  onUpdateSegment: (id: number, translatedText: string, sourceText?: string, speaker?: string, gender?: string) => void;
  onDeleteSegment: (id: number) => void;
  onClearAll?: () => void;
}

export type ViewMode = 'split' | 'stacked';

export const TranscriptView: React.FC<TranscriptViewProps> = ({
  result,
  currentTime,
  onJumpToTime,
  onUpdateSegment,
  onDeleteSegment,
  onClearAll,
}) => {
  const [viewMode, setViewMode] = useState<ViewMode>('split');
  const [searchQuery, setSearchQuery] = useState('');
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [copiedType, setCopiedType] = useState<string | null>(null);
  const [copiedSrt, setCopiedSrt] = useState(false);

  // Editing state supporting both source & translated text
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTranslated, setEditTranslated] = useState('');
  const [editSource, setEditSource] = useState('');

  const handleCopySrtQuick = () => {
    const srt = exportToSrt(result.segments, 'bilingual');
    navigator.clipboard.writeText(srt);
    setCopiedSrt(true);
    setTimeout(() => setCopiedSrt(false), 2000);
  };

  const handleToggleSpeaker = (seg: Segment) => {
    const currentGender = (seg.gender || '').toLowerCase();
    const currentSpk = (seg.speaker || '').toLowerCase();
    let nextGender: 'male' | 'female' | 'child' | 'elder' = 'child';
    let nextSpeaker = '🧒 ក្មេង (Child)';

    if (currentGender === 'child' || currentSpk.includes('ក្មេង')) {
      nextGender = 'female';
      nextSpeaker = '👩 ស្រី (Female)';
    } else if (currentGender === 'female' || currentSpk.includes('ស្រី')) {
      nextGender = 'male';
      nextSpeaker = '👨 ប្រុស (Male)';
    } else if (currentGender === 'male' || currentSpk.includes('ប្រុស')) {
      nextGender = 'elder';
      nextSpeaker = '👵👴 មនុស្សចាស់ (Elder)';
    } else {
      nextGender = 'child';
      nextSpeaker = '🧒 ក្មេង (Child)';
    }

    seg.gender = nextGender;
    seg.speaker = nextSpeaker;
    if (onUpdateSegment) {
      onUpdateSegment(seg.id, seg.translatedText, seg.sourceText, nextSpeaker, nextGender);
    }
  };

  const handleCopySegment = (seg: Segment, type: 'both' | 'khmer' | 'source' = 'both') => {
    let text = '';
    if (type === 'both') {
      text = `${seg.sourceText}\n👉 ${seg.translatedText}`;
    } else if (type === 'khmer') {
      text = seg.translatedText;
    } else {
      text = seg.sourceText;
    }
    navigator.clipboard.writeText(text);
    setCopiedId(seg.id);
    setCopiedType(type);
    setTimeout(() => {
      setCopiedId(null);
      setCopiedType(null);
    }, 2000);
  };

  const startEditing = (seg: Segment) => {
    setEditingId(seg.id);
    setEditTranslated(seg.translatedText);
    setEditSource(seg.sourceText);
  };

  const saveEdit = (id: number) => {
    onUpdateSegment(id, editTranslated, editSource);
    setEditingId(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  // Active playing audio state
  const [playingId, setPlayingId] = useState<number | null>(null);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);

  // High-quality Khmer Text-to-Speech (TTS) playback using /api/tts with Google TTS fallback
  const speakText = (seg: Segment) => {
    const text = (seg.translatedText || '').trim();
    if (!text) return;

    if (audioPlayerRef.current) {
      audioPlayerRef.current.pause();
      audioPlayerRef.current = null;
    }

    setPlayingId(seg.id);
    const gender = (seg.gender || 'female').toLowerCase();
    const ttsUrl = `/api/tts?text=${encodeURIComponent(text)}&gender=${encodeURIComponent(gender)}`;

    const audio = new Audio(ttsUrl);
    audioPlayerRef.current = audio;

    audio.onended = () => {
      setPlayingId(null);
      audioPlayerRef.current = null;
    };

    audio.onerror = () => {
      // Fallback directly to Google Translate Khmer TTS
      const fallbackUrl = `https://translate.google.com/translate_tts?ie=UTF-8&q=${encodeURIComponent(text)}&tl=km&client=tw-ob`;
      const fallbackAudio = new Audio(fallbackUrl);
      audioPlayerRef.current = fallbackAudio;
      fallbackAudio.onended = () => {
        setPlayingId(null);
        audioPlayerRef.current = null;
      };
      fallbackAudio.play().catch(() => setPlayingId(null));
    };

    audio.play().catch(() => {
      setPlayingId(null);
    });
  };

  const filteredSegments = result.segments.filter((seg) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      seg.sourceText.toLowerCase().includes(query) ||
      seg.translatedText.toLowerCase().includes(query) ||
      seg.startTime.toLowerCase().includes(query)
    );
  });

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 sm:p-6 shadow-xl backdrop-blur-md">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <h3 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              <span>Transcript / អត្ថបទបកប្រែ</span>
            </h3>
            <span className="text-xs font-mono font-medium px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
              {result.segments.length} Segments
            </span>
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
              {result.detectedLanguage.toUpperCase()} ➔ KHMER
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            ចុចលើម៉ោង <span className="text-amber-400 font-mono">00:01:02</span> ដើម្បីស្តាប់សំឡេងត្រង់ចំណុចនោះ
          </p>
        </div>

        {/* View Mode Toggle, Search, Copy SRT & Actions */}
        <div className="flex flex-wrap items-center gap-2.5">
          {/* Split-View / Stacked-View Switcher */}
          <div className="flex items-center p-1 bg-slate-950/80 border border-slate-700/80 rounded-xl shadow-inner">
            <button
              type="button"
              onClick={() => setViewMode('split')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                viewMode === 'split'
                  ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Split-View Mode: បង្ហាញភាសាដើម និងភាសាខ្មែរទន្ទឹមគ្នា (Side-by-Side)"
            >
              <Columns className="w-3.5 h-3.5" />
              <span>Split-View (ទន្ទឹមគ្នា)</span>
            </button>

            <button
              type="button"
              onClick={() => setViewMode('stacked')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                viewMode === 'stacked'
                  ? 'bg-amber-500 text-slate-950 shadow-md shadow-amber-500/20'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
              title="Stacked Mode: បង្ហាញភាសាដើមនៅខាងលើ និងភាសាខ្មែរនៅខាងក្រោម"
            >
              <Rows className="w-3.5 h-3.5" />
              <span>Stacked (បញ្ឈរ)</span>
            </button>
          </div>

          {/* Quick Copy SRT */}
          <button
            type="button"
            onClick={handleCopySrtQuick}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer shadow-sm ${
              copiedSrt
                ? 'bg-emerald-500 text-white'
                : 'bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30'
            }`}
            title="ចម្លង Subtitle SRT ទាំងអស់ភ្លាមៗ"
          >
            {copiedSrt ? (
              <>
                <Check className="w-3.5 h-3.5 text-white" />
                <span>បានចម្លង SRT!</span>
              </>
            ) : (
              <>
                <Film className="w-3.5 h-3.5 text-amber-400" />
                <span>Copy SRT</span>
              </>
            )}
          </button>

          {/* Search box */}
          <div className="relative min-w-[170px] flex-1 sm:flex-initial">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              placeholder="ស្វែងរកពាក្យ..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-xl text-xs text-slate-200 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Clear button if provided */}
          {onClearAll && (
            <button
              type="button"
              onClick={onClearAll}
              className="p-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 border border-slate-800 hover:border-rose-500/30 transition cursor-pointer"
              title="លុបអត្ថបទបកប្រែទាំងអស់ចោល"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Summary Box if present */}
      {result.summary && (
        <div className="mb-5 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-slate-200">
          <div className="flex items-center gap-2 text-xs font-bold text-amber-400 uppercase tracking-wider mb-1">
            <Sparkles className="w-3.5 h-3.5" />
            <span>សង្ខេបអត្ថន័យរួម (AI Summary):</span>
          </div>
          <p className="text-sm leading-relaxed text-slate-200">{result.summary}</p>
        </div>
      )}

      {/* Split-View Column Legend if Split mode active */}
      {viewMode === 'split' && filteredSegments.length > 0 && (
        <div className="hidden sm:grid grid-cols-2 gap-4 px-4 py-2 mb-2 bg-slate-950/60 rounded-xl border border-slate-800/80 text-xs font-bold">
          <div className="flex items-center gap-2 text-slate-400">
            <Languages className="w-3.5 h-3.5 text-blue-400" />
            <span>អត្ថបទដើម (Original Speech - {result.detectedLanguage.toUpperCase()})</span>
          </div>
          <div className="flex items-center gap-2 text-amber-300">
            <span className="text-amber-400 select-none">👉</span>
            <span>អត្ថបទបកប្រែជាភាសាខ្មែរ (Khmer Translation)</span>
          </div>
        </div>
      )}

      {/* Segments List Container */}
      <div className="space-y-3.5 max-h-[580px] overflow-y-auto pr-1">
        {filteredSegments.length === 0 ? (
          <div className="py-12 text-center text-slate-500 text-sm">
            មិនមានទិន្នន័យត្រូវគ្នានឹងពាក្យស្វែងរកឡើយ
          </div>
        ) : (
          filteredSegments.map((seg) => {
            const isActive =
              currentTime >= seg.startSeconds &&
              currentTime <=
                (seg.endSeconds > seg.startSeconds ? seg.endSeconds : seg.startSeconds + 2.5);
            const isEditing = editingId === seg.id;

            return (
              <div
                key={seg.id}
                className={`group relative rounded-2xl p-4 sm:p-4.5 transition-all border ${
                  isActive
                    ? 'bg-amber-500/10 border-amber-500/60 shadow-lg shadow-amber-500/10 ring-1 ring-amber-500/30'
                    : 'bg-slate-950/70 border-slate-800/80 hover:border-slate-700 hover:bg-slate-950'
                }`}
              >
                {/* Top Row: Timestamp, Speaker, Audio Jump & Action Buttons */}
                <div className="flex items-center justify-between gap-2 mb-2.5 pb-2 border-b border-slate-800/60">
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* Timestamp clickable badge */}
                    <button
                      type="button"
                      onClick={() => onJumpToTime(seg.startSeconds)}
                      className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-mono font-semibold transition active:scale-95 cursor-pointer ${
                        isActive
                          ? 'bg-amber-500 text-slate-950 font-bold'
                          : 'bg-slate-800 hover:bg-amber-500/20 text-amber-400 hover:text-amber-300 border border-slate-700'
                      }`}
                      title="ចុចដើម្បីស្តាប់សំឡេងត្រង់ចំណុចនេះ"
                    >
                      <Play className="w-3 h-3 fill-current" />
                      <span>{formatTimeDisplay(seg.startSeconds)}</span>
                      <span className="text-[10px] opacity-70">
                        ({formatTimeDisplay(seg.endSeconds)})
                      </span>
                    </button>

                    {(() => {
                      const g = (seg.gender || '').toLowerCase();
                      const spk = (seg.speaker || '').toLowerCase();
                      const isChild = g === 'child' || spk.includes('ក្មេង') || spk.includes('child');
                      const isFemale = g === 'female' || spk.includes('ស្រី') || spk.includes('female');
                      const isElder = g === 'elder' || spk.includes('ចាស់') || spk.includes('elder');

                      let badgeClass = "bg-sky-500/15 text-sky-300 border-sky-500/30 hover:bg-sky-500/30";
                      let icon = "👨";
                      let label = seg.speaker || 'ប្រុស (Male)';

                      if (isChild) {
                        badgeClass = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/30";
                        icon = "🧒";
                        label = seg.speaker || 'ក្មេង (Child)';
                      } else if (isFemale) {
                        badgeClass = "bg-rose-500/15 text-rose-300 border-rose-500/30 hover:bg-rose-500/30";
                        icon = "👩";
                        label = seg.speaker || 'ស្រី (Female)';
                      } else if (isElder) {
                        badgeClass = "bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/30";
                        icon = "👵👴";
                        label = seg.speaker || 'មនុស្សចាស់ (Elder)';
                      }

                      return (
                        <button
                          type="button"
                          onClick={() => handleToggleSpeaker(seg)}
                          className={`flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-0.5 rounded-lg border transition cursor-pointer active:scale-95 ${badgeClass}`}
                          title="ចុចដើម្បីប្តូរតួអង្គ (ក្មេង ➔ ស្រី ➔ ប្រុស ➔ មនុស្សចាស់)"
                        >
                          <span>{icon}</span>
                          <span>{label}</span>
                          <span className="text-[9px] opacity-60">▾</span>
                        </button>
                      );
                    })()}

                    {/* Persona Selector */}
                    <select
                      value={seg.persona || '👨 Male Adult'}
                      onChange={(e) => {
                        seg.persona = e.target.value;
                        if (onUpdateSegment) onUpdateSegment(seg.id, seg.translatedText, seg.sourceText, seg.speaker, seg.gender);
                      }}
                      className="bg-slate-900 border border-sky-500/30 text-sky-300 text-[11px] font-semibold rounded-lg px-2 py-0.5 outline-none cursor-pointer hover:border-sky-400"
                      title="ជ្រើសរើស Persona តួអង្គ"
                    >
                      {PERSONA_OPTIONS.map((p) => (
                        <option key={p} value={p} className="bg-slate-900 text-slate-200">{p}</option>
                      ))}
                    </select>

                    {/* Emotion Selector */}
                    <select
                      value={seg.emotion || '😐 Neutral'}
                      onChange={(e) => {
                        seg.emotion = e.target.value;
                        if (onUpdateSegment) onUpdateSegment(seg.id, seg.translatedText, seg.sourceText, seg.speaker, seg.gender);
                      }}
                      className="bg-slate-900 border border-amber-500/30 text-amber-300 text-[11px] font-semibold rounded-lg px-2 py-0.5 outline-none cursor-pointer hover:border-amber-400"
                      title="ជ្រើសរើសអារម្មណ៍ (Emotion)"
                    >
                      {EMOTION_OPTIONS.map((em) => (
                        <option key={em} value={em} className="bg-slate-900 text-slate-200">{em}</option>
                      ))}
                    </select>

                    {/* Speaking Style Selector */}
                    <select
                      value={seg.speakingStyle || 'Normal'}
                      onChange={(e) => {
                        seg.speakingStyle = e.target.value;
                        if (onUpdateSegment) onUpdateSegment(seg.id, seg.translatedText, seg.sourceText, seg.speaker, seg.gender);
                      }}
                      className="bg-slate-900 border border-purple-500/30 text-purple-300 text-[11px] font-semibold rounded-lg px-2 py-0.5 outline-none cursor-pointer hover:border-purple-400"
                      title="ជ្រើសរើសទម្រង់នៃការនិយាយ (Speaking Style)"
                    >
                      {STYLE_OPTIONS.map((st) => (
                        <option key={st} value={st} className="bg-slate-900 text-slate-200">{st}</option>
                      ))}
                    </select>

                    {viewMode === 'split' && (
                      <span className="hidden sm:inline-block text-[10px] font-mono text-slate-500">
                        Segment #{seg.id}
                      </span>
                    )}
                  </div>

                  {/* Actions for this segment */}
                  <div className="flex items-center gap-1 opacity-80 group-hover:opacity-100 transition">
                    <button
                      type="button"
                      onClick={() => speakText(seg)}
                      className={`p-1.5 rounded-lg transition cursor-pointer ${
                        playingId === seg.id
                          ? 'text-amber-300 bg-amber-500/20 ring-1 ring-amber-400/50'
                          : 'text-slate-400 hover:text-amber-400 hover:bg-slate-800'
                      }`}
                      title="ស្តាប់សំឡេងអានភាសាខ្មែរ (TTS)"
                    >
                      {playingId === seg.id ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-amber-400" />
                      ) : (
                        <Volume2 className="w-3.5 h-3.5" />
                      )}
                    </button>

                    {!isEditing && (
                      <button
                        type="button"
                        onClick={() => startEditing(seg)}
                        className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition cursor-pointer"
                        title="កែសម្រួលអត្ថបទ (Edit comparison)"
                      >
                        <Edit2 className="w-3.5 h-3.5" />
                      </button>
                    )}

                    <button
                      type="button"
                      onClick={() => handleCopySegment(seg, 'both')}
                      className="p-1.5 text-slate-400 hover:text-emerald-400 hover:bg-slate-800 rounded-lg transition cursor-pointer"
                      title="ចម្លងទាំងភាសាដើម និងខ្មែរ"
                    >
                      {copiedId === seg.id && copiedType === 'both' ? (
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => onDeleteSegment(seg.id)}
                      className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition cursor-pointer"
                      title="លុបឃ្លានេះចោល (Delete)"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Content Display based on ViewMode */}
                {viewMode === 'split' ? (
                  /* SPLIT-VIEW MODE: Side-by-Side Grid */
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                    {/* Left Column: Original Text */}
                    <div className="bg-slate-900/60 rounded-xl p-3 border border-slate-800/80 flex flex-col justify-between">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                          ភាសាដើម (Original)
                        </span>
                        <button
                          type="button"
                          onClick={() => handleCopySegment(seg, 'source')}
                          className="text-[10px] text-slate-400 hover:text-slate-200 flex items-center gap-1 cursor-pointer"
                          title="ចម្លងតែអត្ថបទដើម"
                        >
                          {copiedId === seg.id && copiedType === 'source' ? (
                            <Check className="w-3 h-3 text-emerald-400" />
                          ) : (
                            <Copy className="w-3 h-3" />
                          )}
                          <span>Copy</span>
                        </button>
                      </div>

                      {isEditing ? (
                        <textarea
                          value={editSource}
                          onChange={(e) => setEditSource(e.target.value)}
                          rows={3}
                          className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-blue-400 font-sans leading-relaxed"
                          placeholder="កែសម្រួលអត្ថបទដើម..."
                        />
                      ) : (
                        <div className="text-xs sm:text-sm font-medium text-slate-300 leading-relaxed select-text font-sans">
                          {seg.sourceText}
                        </div>
                      )}
                    </div>

                    {/* Right Column: Translated Khmer Text */}
                    <div className="bg-amber-500/5 rounded-xl p-3 border border-amber-500/20 flex flex-col justify-between">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1">
                          <span>👉</span>
                          <span>ភាសាខ្មែរ (Khmer)</span>
                        </span>
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => speakText(seg)}
                            className={`text-[10px] flex items-center gap-0.5 cursor-pointer p-0.5 rounded ${
                              playingId === seg.id
                                ? 'text-amber-300 bg-amber-500/20'
                                : 'text-amber-400/80 hover:text-amber-300'
                            }`}
                            title="ស្តាប់សំឡេង"
                          >
                            {playingId === seg.id ? (
                              <Loader2 className="w-3 h-3 animate-spin text-amber-400" />
                            ) : (
                              <Volume2 className="w-3 h-3" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleCopySegment(seg, 'khmer')}
                            className="text-[10px] text-amber-400/80 hover:text-amber-300 flex items-center gap-1 cursor-pointer"
                            title="ចម្លងតែភាសាខ្មែរ"
                          >
                            {copiedId === seg.id && copiedType === 'khmer' ? (
                              <Check className="w-3 h-3 text-emerald-400" />
                            ) : (
                              <Copy className="w-3 h-3" />
                            )}
                            <span>Copy</span>
                          </button>
                        </div>
                      </div>

                      {isEditing ? (
                        <textarea
                          value={editTranslated}
                          onChange={(e) => setEditTranslated(e.target.value)}
                          rows={3}
                          className="w-full bg-slate-950 border border-amber-500 rounded-lg p-2.5 text-xs sm:text-sm text-amber-200 focus:outline-none font-medium leading-relaxed"
                          placeholder="កែសម្រួលអត្ថបទបកប្រែជាភាសាខ្មែរ..."
                        />
                      ) : (
                        <div className="text-sm sm:text-base font-medium text-amber-300 leading-relaxed select-text">
                          {seg.translatedText}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  /* STACKED MODE: Original top, Khmer bottom */
                  <div className="space-y-2">
                    {/* Original Source Text */}
                    {isEditing ? (
                      <div className="space-y-1">
                        <label className="text-[10px] font-bold text-slate-400">អត្ថបទដើម:</label>
                        <textarea
                          value={editSource}
                          onChange={(e) => setEditSource(e.target.value)}
                          rows={2}
                          className="w-full bg-slate-900 border border-slate-700 rounded-xl p-2.5 text-xs text-slate-200 focus:outline-none"
                        />
                      </div>
                    ) : (
                      <div className="text-sm font-medium text-slate-300 pl-1 mb-2 select-text font-sans leading-relaxed">
                        {seg.sourceText}
                      </div>
                    )}

                    {/* Translated Text in Khmer */}
                    {isEditing ? (
                      <div className="space-y-1">
                        <label className="text-[10px] font-bold text-amber-400">អត្ថបទខ្មែរ:</label>
                        <textarea
                          value={editTranslated}
                          onChange={(e) => setEditTranslated(e.target.value)}
                          rows={2}
                          className="w-full bg-slate-900 border border-amber-500 rounded-xl p-2.5 text-sm text-slate-100 focus:outline-none"
                        />
                      </div>
                    ) : (
                      <div className="flex items-start gap-2 pl-1 py-1 rounded-xl text-base text-amber-300 font-medium leading-relaxed bg-amber-500/5 px-2.5 border border-amber-500/10 select-text">
                        <span className="text-amber-400 shrink-0 select-none">👉</span>
                        <span>{seg.translatedText}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Edit Action Bar when editing */}
                {isEditing && (
                  <div className="flex items-center gap-2 justify-end mt-3 pt-2 border-t border-slate-800">
                    <button
                      type="button"
                      onClick={cancelEdit}
                      className="px-3.5 py-1.5 text-xs rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center gap-1.5 transition cursor-pointer"
                    >
                      <X className="w-3.5 h-3.5" />
                      <span>បោះបង់ (Cancel)</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => saveEdit(seg.id)}
                      className="px-4 py-1.5 text-xs rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold flex items-center gap-1.5 shadow-md shadow-amber-500/20 transition cursor-pointer"
                    >
                      <Save className="w-3.5 h-3.5" />
                      <span>រក្សាទុក (Save)</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
