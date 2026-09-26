import { Segment, TranslationResult } from '../types/translator';

/**
 * Format seconds into HH:MM:SS,mmm (for SRT)
 */
export function formatTimeSrt(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) seconds = 0;
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);

  const hh = String(hrs).padStart(2, '0');
  const mm = String(mins).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');
  const mmm = String(ms).padStart(3, '0');

  return `${hh}:${mm}:${ss},${mmm}`;
}

/**
 * Format seconds into HH:MM:SS.mmm (for VTT)
 */
export function formatTimeVtt(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) seconds = 0;
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);

  const hh = String(hrs).padStart(2, '0');
  const mm = String(mins).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');
  const mmm = String(ms).padStart(3, '0');

  return `${hh}:${mm}:${ss}.${mmm}`;
}

/**
 * Format seconds into compact display 00:01:02 or 01:02
 */
export function formatTimeDisplay(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) seconds = 0;
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  const hh = String(hrs).padStart(2, '0');
  const mm = String(mins).padStart(2, '0');
  const ss = String(secs).padStart(2, '0');

  if (hrs > 0) {
    return `${hh}:${mm}:${ss}`;
  }
  return `${mm}:${ss}`;
}

/**
 * Sanitize Khmer subtitle text (remove residual foreign words, fix spacing & punctuation)
 */
export function sanitizeKhmerText(text: string): string {
  if (!text) return '';
  return text
    .replace(/\bดีណាស់\b|ดีណាស់/g, 'ល្អណាស់')
    .replace(/\bดี\b|ดี/g, 'ល្អ')
    .replace(/\bปล่อย\b|ปล่อย/g, 'លែង')
    .replace(/\bท่าทางแบบนั้น\b|ท่าทางแบบนั้น/g, 'ឫកពារបែបនោះ')
    .replace(/\bท่าทาง\b|ท่าทาง/g, 'ឫកពារ')
    .replace(/\bเรื่อง\b|เรื่อง/g, 'រឿង')
    .replace(/\bแบก\b|แบ/g, 'ទ្រ')
    .replace(/\bไม่ใช่\b|ไม่ใช่/g, 'មិនមែន')
    .replace(/[\u0E00-\u0E7F]+/g, '')
    .replace(/([?!។])(?=[^\s\d])/g, '$1 ')
    .replace(/\s+([?!។])/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * Strip speaker prefix tags from subtitle text
 */
export function cleanSpeakerTagFromText(text: string): string {
  if (!text) return '';
  const noPrefix = text
    .replace(/^\s*(?:\[|\()?(\s*ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)\s*(?:\]|\))?\s*[:：\-–—]?\s*/i, '')
    .replace(/^\s*\[[^\]]+\]\s*/, '')
    .trim();
  return sanitizeKhmerText(noPrefix);
}

/**
 * Generate SubRip (.srt) subtitle file
 */
export function exportToSrt(
  segments: Segment[],
  mode: 'translated' | 'bilingual' = 'translated',
  includeSpeaker: boolean = true
): string {
  const expandedSegments: Segment[] = [];

  for (const seg of segments) {
    const rawClean = cleanSpeakerTagFromText(seg.translatedText || '');
    if (!rawClean) continue;

    const startSec = typeof seg.startSeconds === 'number' ? seg.startSeconds : 0;
    const endSec = typeof seg.endSeconds === 'number' && seg.endSeconds > startSec ? seg.endSeconds : startSec + 2.5;
    const dur = endSec - startSec;

    // Split overly long segments (> 7.5s) if multiple sentences exist
    const sentences = rawClean.split(/(?<=[។!?])\s+/).filter((s) => s.trim().length > 0);
    if (dur > 7.5 && sentences.length > 1) {
      const stepDur = dur / sentences.length;
      sentences.forEach((sent, sIdx) => {
        const subStart = startSec + sIdx * stepDur;
        const subEnd = subStart + stepDur;
        expandedSegments.push({
          ...seg,
          startSeconds: Math.round(subStart * 100) / 100,
          endSeconds: Math.round(subEnd * 100) / 100,
          translatedText: sent.trim(),
        });
      });
    } else {
      const safeEnd = dur > 7.0 ? startSec + Math.min(dur, Math.max(3.5, rawClean.length * 0.15)) : endSec;
      expandedSegments.push({
        ...seg,
        startSeconds: startSec,
        endSeconds: Math.round(safeEnd * 100) / 100,
        translatedText: rawClean,
      });
    }
  }

  return expandedSegments
    .map((seg, idx) => {
      const start = formatTimeSrt(seg.startSeconds);
      const end = formatTimeSrt(seg.endSeconds > seg.startSeconds ? seg.endSeconds : seg.startSeconds + 2);
      
      const cleanTrans = cleanSpeakerTagFromText(seg.translatedText || '');
      const cleanSrc = cleanSpeakerTagFromText(seg.sourceText || '');

      let speakerPrefix = '';
      if (includeSpeaker) {
        const gender = (seg.gender || '').toLowerCase();
        const spk = (seg.speaker || '').toLowerCase();
        const raw = ((seg.translatedText || '') + ' ' + (seg.sourceText || '')).toLowerCase();
        if (gender === 'child' || spk.includes('ក្មេង') || spk.includes('child') || spk.includes('kid') || raw.includes('[ក្មេង]')) {
          speakerPrefix = '[ក្មេង] ';
        } else if (gender === 'female' || spk.includes('ស្រី') || spk.includes('female') || spk.includes('woman') || raw.includes('[ស្រី]')) {
          speakerPrefix = '[ស្រី] ';
        } else if (gender === 'elder' || spk.includes('ចាស់') || spk.includes('elder') || raw.includes('[ចាស់]')) {
          speakerPrefix = '[ចាស់] ';
        } else {
          speakerPrefix = '[ប្រុស] ';
        }
      }

      let text = `${speakerPrefix}${cleanTrans}`;
      if (mode === 'bilingual' && cleanSrc) {
        text = `${speakerPrefix}${cleanTrans}\n${cleanSrc}`;
      }
      return `${idx + 1}\n${start} --> ${end}\n${text}\n`;
    })
    .join('\n');
}

/**
 * Generate WebVTT (.vtt) subtitle file
 */
export function exportToVtt(segments: Segment[], mode: 'translated' | 'bilingual' = 'translated'): string {
  let content = 'WEBVTT\n\n';
  content += segments
    .map((seg, idx) => {
      const start = formatTimeVtt(seg.startSeconds);
      const end = formatTimeVtt(seg.endSeconds > seg.startSeconds ? seg.endSeconds : seg.startSeconds + 2);
      let text = seg.translatedText;
      if (mode === 'bilingual' && seg.sourceText) {
        text = `${seg.translatedText}\n${seg.sourceText}`;
      }
      return `${idx + 1}\n${start} --> ${end}\n${text}\n`;
    })
    .join('\n');
  return content;
}

/**
 * Generate Plain Text (.txt) transcript
 */
export function exportToTxt(result: TranslationResult, mode: 'bilingual' | 'translatedOnly' | 'sourceOnly' = 'bilingual'): string {
  let output = `🎬 AI Audio Translator - Transcript\n`;
  output += `==============================================\n`;
  output += `Detected Language: ${result.detectedLanguage}\n`;
  output += `Target Language: ${result.targetLanguage}\n`;
  if (result.summary) {
    output += `Summary / សង្ខេប: ${result.summary}\n`;
  }
  output += `Total Segments: ${result.segments.length}\n`;
  output += `==============================================\n\n`;

  result.segments.forEach((seg, index) => {
    const time = `${formatTimeDisplay(seg.startSeconds)} - ${formatTimeDisplay(seg.endSeconds)}`;
    const speaker = seg.speaker ? ` [${seg.speaker}]` : '';
    output += `[${index + 1}] ${time}${speaker}\n`;

    if (mode === 'bilingual') {
      output += `Original:    ${seg.sourceText}\n`;
      output += `Translation: 👉 ${seg.translatedText}\n\n`;
    } else if (mode === 'translatedOnly') {
      output += `${seg.translatedText}\n\n`;
    } else {
      output += `${seg.sourceText}\n\n`;
    }
  });

  return output;
}

/**
 * Generate structured JSON (.json)
 */
export function exportToJson(result: TranslationResult): string {
  return JSON.stringify(result, null, 2);
}

/**
 * Browser file download helper
 */
export function downloadFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
