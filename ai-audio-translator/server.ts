import express from 'express';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import { exec } from 'child_process';
import util from 'util';
import multer from 'multer';
import { GoogleGenAI, Type, ThinkingLevel } from '@google/genai';

dotenv.config();

const execPromise = util.promisify(exec);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const isProd = process.env.NODE_ENV === 'production';
const PORT = process.env.PORT || 3000;

const app = express();

// Ensure /tmp/uploads exists
if (!fs.existsSync('/tmp/uploads')) {
  fs.mkdirSync('/tmp/uploads', { recursive: true });
}

// Multer for streaming large audio/video files (up to 1GB)
const upload = multer({
  dest: '/tmp/uploads/',
  limits: { fileSize: 1024 * 1024 * 1024 }, // 1GB limit
});

// JSON and URL-encoded parsers for base64 fallback
app.use(express.json({ limit: '100mb' }));
app.use(express.urlencoded({ extended: true, limit: '100mb' }));

// Initialize Google GenAI client
const apiKey = process.env.GEMINI_API_KEY || '';
const ai = new GoogleGenAI({
  apiKey,
  httpOptions: {
    headers: {
      'User-Agent': 'aistudio-build',
    },
  },
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    hasApiKey: !!process.env.GEMINI_API_KEY,
    timestamp: new Date().toISOString(),
  });
});

// Format seconds to SRT format HH:MM:SS,mmm
function formatSecondsToSrt(seconds: number): string {
  if (isNaN(seconds) || seconds < 0) seconds = 0;
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

// Helper to clean and sanitize Khmer subtitle text (remove residual foreign words, fix spacing & punctuation)
export function sanitizeKhmerText(text: string): string {
  if (!text) return '';
  let cleaned = text
    // Replace residual Thai words that AI occasionally retains
    .replace(/\bดีណាស់\b|ดีណាស់/g, 'ល្អណាស់')
    .replace(/\bดี\b|ดี/g, 'ល្អ')
    .replace(/\bปล่อย\b|ปล่อย/g, 'លែង')
    .replace(/\bท่าทางแบบนั้น\b|ท่าทางแบบนั้น/g, 'ឫកពារបែបនោះ')
    .replace(/\bท่าทาง\b|ท่าทาง/g, 'ឫកពារ')
    .replace(/\bเรื่อง\b|เรื่อง/g, 'រឿង')
    .replace(/\bแบก\b|แบ/g, 'ទ្រ')
    .replace(/\bไม่ใช่\b|ไม่ใช่/g, 'មិនមែន')
    .replace(/[\u0E00-\u0E7F]+/g, '') // Strip any remaining Thai characters
    // Clean up double punctuation & fix spacing after ? and !
    .replace(/([?!។])(?=[^\s\d])/g, '$1 ')
    .replace(/\s+([?!។])/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();

  return cleaned;
}

// Helper to clean speaker prefix tags from subtitle text safely
export function cleanSpeakerTagFromText(text: string): string {
  if (!text) return '';
  const noPrefix = text
    // Strip bracketed or parenthesized tags like [ស្រី], (Male), [speaker_01], etc.
    .replace(/^\s*\[[^\]]+\]\s*/g, '')
    .replace(/^\s*\([^\)]+\)\s*/g, '')
    // Strip tags followed by colon or dash like "ស្រី: ", "ក្មេង - ", "Speaker 1: "
    .replace(/^\s*(?:ក្មេង(?:ប្រុស|ស្រី)?|កូន|child(?:ren)?|kid|boy|girl|ស្រី|female|woman|lady|ប្រុស|male|man|guy|មនុស្សចាស់|ចាស់|elder|លោកតា|លោកយាយ|speaker\s*\d+)[\s]*[:：\-–—]\s*/i, '')
    .trim();
  return sanitizeKhmerText(noPrefix);
}

// Generate ready-to-use SRT text with optional speaker tagging [ប្រុស], [ស្រី], [ក្មេង]
// Generate ready-to-use SRT text with optional speaker tagging [ប្រុស], [ស្រី], [ក្មេង]
function buildSrtString(segments: any[], includeSpeakerTag: boolean = true): string {
  if (!Array.isArray(segments)) return '';

  const expandedSegments: any[] = [];

  for (const seg of segments) {
    const rawClean = cleanSpeakerTagFromText(seg.translatedText || '');
    if (!rawClean) continue;

    const startSec = typeof seg.startSeconds === 'number' ? seg.startSeconds : 0;
    const endSec = typeof seg.endSeconds === 'number' && seg.endSeconds > startSec ? seg.endSeconds : startSec + 2.5;
    const dur = endSec - startSec;

    // If segment is too long (> 7.5s) and contains sentence separators, split naturally
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
      // If duration exceeds 7.0s with single sentence, cap it reasonably to avoid lingering subtitle
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
      const start = formatSecondsToSrt(seg.startSeconds || 0);
      const end = formatSecondsToSrt(
        seg.endSeconds > seg.startSeconds ? seg.endSeconds : (seg.startSeconds || 0) + 2.5
      );
      const cleanText = cleanSpeakerTagFromText(seg.translatedText || '');
      let lineText = cleanText;
      if (includeSpeakerTag) {
        const gender = (seg.gender || '').toLowerCase();
        const spk = seg.speaker || '';
        let speakerTag = '[ប្រុស]';
        if (gender === 'child' || spk.includes('ក្មេង') || spk.toLowerCase().includes('child') || spk.toLowerCase().includes('kid')) {
          speakerTag = '[ក្មេង]';
        } else if (gender === 'female' || spk.includes('ស្រី') || spk.toLowerCase().includes('female') || spk.toLowerCase().includes('woman')) {
          speakerTag = '[ស្រី]';
        } else if (gender === 'elder' || spk.includes('ចាស់') || spk.toLowerCase().includes('elder')) {
          speakerTag = '[ចាស់]';
        }
        lineText = `${speakerTag} ${cleanText}`;
      }
      return `${idx + 1}\n${start} --> ${end}\n${lineText}\n`;
    })
    .join('\n');
}

// Helper to call Gemini for an audio buffer
async function callGeminiForAudioChunk(
  audioBase64: string,
  mimeType: string,
  isTurbo: boolean,
  sourceLang: string = 'Auto',
  targetLang: string = 'Khmer'
): Promise<{
  detectedLanguage: string;
  targetLanguage: string;
  summary: string;
  segments: any[];
  model: string;
  usageMetadata: any;
}> {
  const audioPart = {
    inlineData: {
      mimeType: mimeType || 'audio/mp3',
      data: audioBase64,
    },
  };

  const promptText = isTurbo
    ? `You are an expert audio subtitle transcriber, speaker classifier, and Khmer translator.
CRITICAL MANDATE: COMPLETE & EXHAUSTIVE SPEECH COVERAGE (100% DIALOGUE CAPTURE)
1. You must transcribe EVERY SINGLE spoken utterance, phrase, dialogue turn, whisper, shout, question, and reaction across this audio timeline.
2. STRICT RULE: DO NOT SKIP, SUMMARIZE, DROP, OR OMIT ANY SPOKEN WORDS. Every character who speaks must have their line captured.
3. Break speech into natural, chronological subtitle segments of 1.5 to 5.0 seconds with exact startSeconds and endSeconds timestamps (NEVER exceed 6 seconds per segment).
4. Transcribe original spoken text verbatim into 'sourceText' (${sourceLang === 'Auto' ? 'auto-detect language' : sourceLang}).
5. Translate each segment accurately, emotionally, and 100% directly into natural, fluent Khmer (ភាសាខ្មែរ) into 'translatedText'. STRICT RULE: NEVER leave Thai (ภาษาไทย), English, or Chinese words in 'translatedText'. Every single word must be in proper Khmer script.
6. Listen carefully to each voice and classify 'gender': strictly 'male', 'female', or 'child'.
7. Label 'speaker' as 'ប្រុស (Male)', 'ស្រី (Female)', or 'ក្មេង (Child)'.
8. Set 'speakerId' (e.g. 'speaker_01', 'speaker_02').
9. Classify 'persona' as '👨 Male Adult', '👩 Female Adult', '👦 Boy / Child', '👧 Girl / Child', '👴 Elderly Male', '👵 Elderly Female', '👨‍🦱 Young Male', '👩‍🦰 Young Female', '🎭 Narrator', '🤖 AI / Robot', '📢 Announcer', or '👥 Crowd / Group'.
10. Classify 'emotion' as '😐 Neutral', '😊 Happy', '😢 Sad', '😡 Angry', '😨 Fear', '🤩 Excited', '🥰 Romantic', '😭 Crying', or '😲 Surprised'.
11. Classify 'speakingStyle' as 'Normal', 'Fast', 'Slow', 'Soft', 'Loud', 'Whisper', 'Serious', or 'Dramatic'.
Return strictly valid JSON.`
    : `You are an expert audio transcriber, speaker diarization specialist, and multilingual translator.
CRITICAL MANDATE: COMPLETE & EXHAUSTIVE SPEECH COVERAGE (100% DIALOGUE CAPTURE)
1. Transcribe EVERY SINGLE spoken utterance verbatim across this audio (Source: ${sourceLang === 'Auto' ? 'auto-detect' : sourceLang}). NEVER skip or omit any dialogue turns.
2. Break the transcript into chronological speech segments with precise start and end timestamps. Keep segment length between 1.5 to 5.0 seconds (do not create long segments over 6 seconds).
3. Translate each segment accurately and naturally into ${targetLang} (ភាសាខ្មែរ / Khmer). STRICT RULE: NEVER leave any untranslated foreign words in 'translatedText'; write 100% in natural Khmer script.
4. Identify speaker voice characteristics: classify 'gender' strictly as 'male', 'female', or 'child'.
5. Set 'speaker' to 'ប្រុស (Male)', 'ស្រី (Female)', or 'ក្មេង (Child)'.
6. Set 'speakerId' consistently across dialogue (e.g. 'speaker_01', 'speaker_02').
7. Set 'persona' (e.g. '👨 Male Adult', '👩 Female Adult', '👦 Boy / Child', etc.).
8. Set 'emotion' (e.g. '😐 Neutral', '😊 Happy', '😢 Sad', etc.).
9. Set 'speakingStyle' (e.g. 'Normal', 'Fast', 'Slow', 'Whisper', etc.).
10. Provide a concise summary of the audio content in Khmer.
Return strictly valid JSON.`;

  const candidateModels = isTurbo
    ? [
        'gemini-3.5-flash-lite',
        'gemini-flash-lite-latest',
        'gemini-3.5-flash',
        'gemini-3.6-flash',
        'gemini-3.8-flash',
      ]
    : [
        'gemini-3.5-flash-lite',
        'gemini-3.5-flash',
        'gemini-flash-lite-latest',
        'gemini-3.6-flash',
        'gemini-3.8-flash',
      ];

  let lastError: any = null;

  for (const modelName of candidateModels) {
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        const response = await ai.models.generateContent({
          model: modelName,
          contents: {
            parts: [
              audioPart,
              { text: promptText },
            ],
          },
          config: {
            systemInstruction: isTurbo
              ? 'CRITICAL: Exhaustive 100% speech-to-Khmer subtitle generator. Transcribe and translate every single spoken utterance across the audio without skipping or dropping any dialogue.'
              : 'CRITICAL: Exhaustive professional audio transcriber and Khmer subtitle translator. Transcribe and translate every single utterance across the entire audio with precise timestamps and speaker personas.',
            temperature: 0.1,
            thinkingConfig: {
              thinkingLevel: ThinkingLevel.MINIMAL,
            },
            responseMimeType: 'application/json',
            responseSchema: {
              type: Type.OBJECT,
              properties: {
                detectedLanguage: {
                  type: Type.STRING,
                  description: 'The primary spoken language detected in the audio',
                },
                targetLanguage: {
                  type: Type.STRING,
                  description: 'The target translation language (Khmer)',
                },
                summary: {
                  type: Type.STRING,
                  description: 'Brief 1-sentence summary of audio in Khmer',
                },
                segments: {
                  type: Type.ARRAY,
                  description: 'Subtitle segments with timestamps, persona, emotion, and style',
                  items: {
                    type: Type.OBJECT,
                    properties: {
                      id: { type: Type.INTEGER },
                      startSeconds: { type: Type.NUMBER },
                      endSeconds: { type: Type.NUMBER },
                      speaker: { type: Type.STRING, description: "Character identification strictly as 'ក្មេង (Child)', 'ស្រី (Female)', or 'ប្រុស (Male)'" },
                      speakerId: { type: Type.STRING, description: "Consistent speaker identifier across dialogue, e.g. 'speaker_01', 'speaker_02'" },
                      persona: { type: Type.STRING, description: "Speaker persona e.g. '👨 Male Adult', '👩 Female Adult', '👦 Boy / Child', '👧 Girl / Child', '👴 Elderly Male', '👵 Elderly Female', '🎭 Narrator'" },
                      emotion: { type: Type.STRING, description: "Emotion: '😐 Neutral', '😊 Happy', '😢 Sad', '😡 Angry', '😨 Fear', '🤩 Excited', '🥰 Romantic', '😭 Crying', '😲 Surprised'" },
                      speakingStyle: { type: Type.STRING, description: "Style: 'Normal', 'Fast', 'Slow', 'Soft', 'Loud', 'Whisper', 'Serious', 'Dramatic'" },
                      gender: { type: Type.STRING, enum: ['male', 'female', 'child'], description: "Must be 'male', 'female', or 'child' based on audio voice pitch" },
                      sourceText: { type: Type.STRING },
                      translatedText: { type: Type.STRING },
                    },
                    required: [
                      'startSeconds',
                      'endSeconds',
                      'sourceText',
                      'translatedText',
                      'speaker',
                      'gender',
                    ],
                  },
                },
              },
              required: ['segments'],
            },
          },
        });

        if (response.text) {
          const parsed = JSON.parse(response.text);
          const rawSegs = Array.isArray(parsed) ? parsed : (parsed.segments || []);
          const segments = rawSegs.map((s: any, idx: number) => {
            const st = typeof s.startSeconds === 'number' ? s.startSeconds : idx * 3;
            const et = typeof s.endSeconds === 'number' ? s.endSeconds : st + 2.5;

            let gender = (s.gender || '').toLowerCase().trim();
            const spkLower = (s.speaker || '').toLowerCase();
            const combinedText = `${s.sourceText || ''} ${s.translatedText || ''}`.toLowerCase();

            // Refined gender detection from speaker tag and voice context
            if (!['male', 'female', 'child'].includes(gender)) {
              if (spkLower.includes('child') || spkLower.includes('kid') || spkLower.includes('baby') || spkLower.includes('boy') || spkLower.includes('ក្មេង') || spkLower.includes('កូន')) {
                gender = 'child';
              } else if (spkLower.includes('female') || spkLower.includes('woman') || spkLower.includes('girl') || spkLower.includes('lady') || spkLower.includes('ស្រី')) {
                gender = 'female';
              } else if (spkLower.includes('elder') || spkLower.includes('ចាស់') || spkLower.includes('យាយ') || spkLower.includes('តា')) {
                gender = 'elder';
              } else if (combinedText.includes('ក្មេង') || combinedText.includes('កូន') || /\b(child|kid|boy|little)\b/i.test(combinedText)) {
                gender = 'child';
              } else if (combinedText.includes('ស្រី') || combinedText.includes('នាង') || combinedText.includes('អ្នកស្រី') || /\b(she|her|woman|girl|lady)\b/i.test(combinedText)) {
                gender = 'female';
              } else {
                gender = 'male';
              }
            }

            let speakerLabel = s.speaker || '';
            if (!speakerLabel || speakerLabel.toLowerCase().includes('speaker')) {
              speakerLabel = gender === 'child' ? '🧒 ក្មេង (Child)' : gender === 'female' ? '👩 ស្រី (Female)' : '👨 ប្រុស (Male)';
            } else if (gender === 'child' && !speakerLabel.includes('ក្មេង')) {
              speakerLabel = `🧒 ក្មេង (${speakerLabel})`;
            } else if (gender === 'female' && !speakerLabel.includes('ស្រី')) {
              speakerLabel = `👩 ស្រី (${speakerLabel})`;
            } else if (gender === 'male' && !speakerLabel.includes('ប្រុស')) {
              speakerLabel = `👨 ប្រុស (${speakerLabel})`;
            }

            let persona = s.persona;
            if (!persona) {
              if (gender === 'child') persona = '👦 Boy / Child';
              else if (gender === 'female') persona = '👩 Female Adult';
              else if (gender === 'elder') persona = '👴 Elderly Male';
              else persona = '👨 Male Adult';
            }

            const emotion = s.emotion || '😐 Neutral';
            const speakingStyle = s.speakingStyle || 'Normal';
            const speakerId = s.speakerId || `speaker_${gender === 'female' ? '02' : '01'}`;

            return {
              id: s.id || idx + 1,
              startTime: s.startTime || formatSecondsToSrt(st).split(',')[0],
              endTime: s.endTime || formatSecondsToSrt(et).split(',')[0],
              startSeconds: Math.round(st * 100) / 100,
              endSeconds: Math.round(Math.max(et, st + 0.5) * 100) / 100,
              speaker: speakerLabel,
              speakerId: speakerId,
              persona: persona,
              emotion: emotion,
              speakingStyle: speakingStyle,
              gender: gender,
              sourceText: (s.sourceText || s.text || '').trim(),
              translatedText: sanitizeKhmerText(s.translatedText || s.khmer || s.sourceText || '').trim(),
            };
          });

          return {
            detectedLanguage: parsed.detectedLanguage || 'Auto',
            targetLanguage: parsed.targetLanguage || 'Khmer',
            summary: parsed.summary || '',
            segments,
            model: modelName,
            usageMetadata: response.usageMetadata,
          };
        }
      } catch (err: any) {
        lastError = err;
        const errMsg = err?.message || String(err);
        const isQuotaError = errMsg.includes('429') || errMsg.includes('RESOURCE_EXHAUSTED') || errMsg.includes('quota');
        const isDemandError = errMsg.includes('503') || errMsg.includes('UNAVAILABLE') || errMsg.includes('high demand');
        if (isQuotaError && attempt < 2) {
          console.warn(`[Gemini Quota 429] Rate limit on ${modelName}, backing off for ${attempt * 2}s before retry...`);
          await new Promise((resolve) => setTimeout(resolve, attempt * 2000));
        } else if (isDemandError && attempt < 2) {
          console.warn(`[Gemini 503] Spikes in demand on ${modelName}, retrying in 1s...`);
          await new Promise((resolve) => setTimeout(resolve, 1000));
        } else {
          console.warn(`[Gemini Fail] ${modelName} attempt ${attempt} skipped: ${errMsg.slice(0, 100)}`);
          break;
        }
      }
    }
  }

  throw lastError || new Error('Failed to get response from Gemini models');
}

// Bridge endpoint to export subtitles to PySide6 Desktop Studio
app.post('/api/export-to-studio', (req, res) => {
  try {
    const { srtText, segments } = req.body;
    const outputDir = path.resolve(__dirname, '..', 'output');
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    const srtFile = path.join(outputDir, 'latest_web_subtitles.srt');
    const jsonFile = path.join(outputDir, 'latest_web_subtitles.json');
    if (srtText) fs.writeFileSync(srtFile, srtText, 'utf-8');
    if (segments) {
      const cleanSegments = segments.map((s: any) => ({
        ...s,
        translatedText: cleanSpeakerTagFromText(s.translatedText || ''),
        sourceText: cleanSpeakerTagFromText(s.sourceText || ''),
      }));
      fs.writeFileSync(jsonFile, JSON.stringify(cleanSegments, null, 2), 'utf-8');
    }
    return res.json({ status: 'ok', srtFile, jsonFile, segmentCount: segments?.length || 0 });
  } catch (err: any) {
    return res.status(500).json({ error: err.message });
  }
});

// Endpoint to find latest MP3 generated in Desktop Studio (output/ or temp/)
app.get('/api/latest-desktop-mp3', (req, res) => {
  try {
    const searchDirs = [
      path.resolve(__dirname, '..', 'output'),
      path.resolve(__dirname, '..', 'temp'),
    ];

    let newestFile: { path: string; name: string; mtime: number; size: number } | null = null;

    for (const dir of searchDirs) {
      if (!fs.existsSync(dir)) continue;
      const files = fs.readdirSync(dir);
      for (const file of files) {
        if (/\.(mp3|wav|m4a)$/i.test(file)) {
          const fullPath = path.join(dir, file);
          try {
            const stat = fs.statSync(fullPath);
            if (!newestFile || stat.mtimeMs > newestFile.mtime) {
              newestFile = {
                path: fullPath,
                name: file,
                mtime: stat.mtimeMs,
                size: stat.size,
              };
            }
          } catch {}
        }
      }
    }

    if (!newestFile) {
      return res.status(404).json({ error: 'រកមិនឃើញ File MP3 នៅក្នុង Folder output ឬ temp ឡើយ' });
    }

    return res.json({
      status: 'ok',
      name: newestFile.name,
      filePath: newestFile.path,
      size: newestFile.size,
      mtime: newestFile.mtime,
      streamUrl: `/api/stream-audio?path=${encodeURIComponent(newestFile.path)}`,
    });
  } catch (err: any) {
    return res.status(500).json({ error: err.message });
  }
});

// Endpoint to inspect and validate a pasted local file path
app.post('/api/load-local-audio', (req, res) => {
  try {
    let filePath = (req.body.filePath || '').trim();
    if (filePath.startsWith('file://')) {
      filePath = decodeURIComponent(filePath.replace(/^file:\/\//, ''));
    }
    filePath = filePath.replace(/^["']|["']$/g, '');

    if (!filePath || !fs.existsSync(filePath)) {
      return res.status(404).json({ error: `រកមិនឃើញឯកសារ: ${filePath}` });
    }

    const stat = fs.statSync(filePath);
    const fileName = path.basename(filePath);
    const ext = fileName.split('.').pop()?.toLowerCase();
    const mimeType = ext === 'wav' ? 'audio/wav' : ext === 'm4a' ? 'audio/m4a' : 'audio/mp3';

    return res.json({
      status: 'ok',
      filePath,
      name: fileName,
      size: stat.size,
      mimeType,
      streamUrl: `/api/stream-audio?path=${encodeURIComponent(filePath)}`,
    });
  } catch (err: any) {
    return res.status(500).json({ error: err.message });
  }
});

// Endpoint to stream local audio directly to browser audio player
app.get('/api/stream-audio', (req, res) => {
  try {
    let filePath = String(req.query.path || '').trim();
    if (filePath.startsWith('file://')) {
      filePath = decodeURIComponent(filePath.replace(/^file:\/\//, ''));
    }
    filePath = filePath.replace(/^["']|["']$/g, '');

    if (!filePath || !fs.existsSync(filePath)) {
      return res.status(404).send('File not found');
    }

    const stat = fs.statSync(filePath);
    const total = stat.size;
    const range = req.headers.range;

    const ext = path.extname(filePath).toLowerCase();
    const contentType = ext === '.wav' ? 'audio/wav' : ext === '.m4a' ? 'audio/m4a' : 'audio/mp3';

    if (range) {
      const parts = range.replace(/bytes=/, '').split('-');
      const partialStart = parts[0];
      const partialEnd = parts[1];

      const start = parseInt(partialStart, 10);
      const end = partialEnd ? parseInt(partialEnd, 10) : total - 1;
      const chunkSize = end - start + 1;

      const fileStream = fs.createReadStream(filePath, { start, end });
      res.writeHead(206, {
        'Content-Range': `bytes ${start}-${end}/${total}`,
        'Accept-Ranges': 'bytes',
        'Content-Length': chunkSize,
        'Content-Type': contentType,
      });
      fileStream.pipe(res);
    } else {
      res.writeHead(200, {
        'Content-Length': total,
        'Content-Type': contentType,
      });
      fs.createReadStream(filePath).pipe(res);
    }
  } catch (err: any) {
    res.status(500).send(err.message);
  }
});

// Unified Audio & Video Fast SRT Translation Endpoint
app.post('/api/translate-audio', upload.single('audioFile'), async (req, res) => {
  const tempFilesToClean: string[] = [];

  try {
    if (!process.env.GEMINI_API_KEY) {
      return res.status(500).json({
        error: 'GEMINI_API_KEY is not configured on the server.',
      });
    }

    const speedMode = req.body.speedMode || 'turbo';
    const sourceLang = req.body.sourceLang || 'Auto';
    const targetLang = req.body.targetLang || 'Khmer';
    const isTurbo = speedMode === 'turbo';

    let inputFilePath: string | null = null;

    if (req.file) {
      inputFilePath = req.file.path;
      tempFilesToClean.push(inputFilePath);
    } else if (req.body.localFilePath) {
      let localPath = (req.body.localFilePath || '').trim();
      if (localPath.startsWith('file://')) {
        localPath = decodeURIComponent(localPath.replace(/^file:\/\//, ''));
      }
      localPath = localPath.replace(/^["']|["']$/g, '');
      if (fs.existsSync(localPath)) {
        inputFilePath = localPath;
      }
    } else if (req.body.audioBase64) {
      const cleanBase64 = req.body.audioBase64.replace(/^data:[^;]+;base64,/, '');
      const rawBuffer = Buffer.from(cleanBase64, 'base64');
      const tempInput = `/tmp/uploads/raw_${Date.now()}_${Math.random().toString(36).slice(2)}.bin`;
      fs.writeFileSync(tempInput, rawBuffer);
      inputFilePath = tempInput;
      tempFilesToClean.push(tempInput);
    }

    if (!inputFilePath || !fs.existsSync(inputFilePath)) {
      return res.status(400).json({ error: 'No audio or video data provided' });
    }

    const requestStartTime = Date.now();

    // 1. High-speed audio extraction & speech optimization (24kHz mono 48k MP3 for crisp voice clarity)
    const optimizedAudioPath = `/tmp/uploads/opt_${Date.now()}_${Math.random().toString(36).slice(2)}.mp3`;
    tempFilesToClean.push(optimizedAudioPath);

    console.log(`[Audio Optimizer] Extracting high-clarity voice audio from ${inputFilePath}...`);
    try {
      await execPromise(`ffmpeg -y -threads 0 -i "${inputFilePath}" -vn -ac 1 -ar 24000 -b:a 48k -f mp3 "${optimizedAudioPath}"`);
    } catch (ffmpegErr: any) {
      console.warn('[Audio Optimizer] FFmpeg convert warning, fallback copy...', ffmpegErr.message);
      fs.copyFileSync(inputFilePath, optimizedAudioPath);
    }

    // Measure total duration
    let totalDurationSeconds = 0;
    try {
      const { stdout } = await execPromise(
        `ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "${optimizedAudioPath}"`
      );
      totalDurationSeconds = parseFloat(stdout.trim()) || 0;
    } catch {
      totalDurationSeconds = 0;
    }

    const audioFileSize = fs.statSync(optimizedAudioPath).size;
    const audioFileSizeMB = audioFileSize / (1024 * 1024);
    console.log(`[Audio Optimizer] Duration: ${totalDurationSeconds.toFixed(1)}s (~${(totalDurationSeconds/60).toFixed(1)} mins), Compressed Size: ${audioFileSizeMB.toFixed(2)} MB`);

    let allSegments: any[] = [];
    let detectedLanguage = 'Auto';
    let summary = '';
    let successfulModel = 'gemini-3.5-flash-lite';
    let totalCandidatesTokens = 0;
    let totalPromptTokens = 0;

    // If audio is short (<= 75s), process in ONE single high-speed pass!
    // If longer, chunk into 60s segments with 4s overlap to ensure 100% speech coverage with zero timestamp drift!
    if (totalDurationSeconds <= 75) {
      console.log(`[Fast AI SRT] Short audio (${totalDurationSeconds.toFixed(1)}s <= 75s). Processing in single pass...`);
      const audioBuffer = fs.readFileSync(optimizedAudioPath);
      const audioBase64 = audioBuffer.toString('base64');

      const result = await callGeminiForAudioChunk(
        audioBase64,
        'audio/mp3',
        isTurbo,
        sourceLang,
        targetLang
      );

      detectedLanguage = result.detectedLanguage;
      summary = result.summary;
      successfulModel = result.model;
      if (result.usageMetadata) {
        totalCandidatesTokens = result.usageMetadata.candidatesTokenCount || 0;
        totalPromptTokens = result.usageMetadata.promptTokenCount || 0;
      }

      allSegments = (result.segments || []).map((seg: any, idx: number) => {
        const sSec = typeof seg.startSeconds === 'number' ? seg.startSeconds : idx * 3;
        const eSec = typeof seg.endSeconds === 'number' ? seg.endSeconds : sSec + 2.5;
        return {
          id: seg.id || idx + 1,
          startTime: seg.startTime || formatSecondsToSrt(sSec).split(',')[0],
          endTime: seg.endTime || formatSecondsToSrt(eSec).split(',')[0],
          startSeconds: Math.round(sSec * 100) / 100,
          endSeconds: Math.round(eSec * 100) / 100,
          speaker: seg.speaker || undefined,
          speakerId: seg.speakerId || 'speaker_01',
          persona: seg.persona || '👨 Male Adult',
          emotion: seg.emotion || '😐 Neutral',
          speakingStyle: seg.speakingStyle || 'Normal',
          gender: seg.gender || 'male',
          sourceText: seg.sourceText || '',
          translatedText: seg.translatedText || '',
        };
      });
    } else {
      // Chunk audio into 60s windows with 4s overlap for 100% speech coverage, sample-accurate timestamps, and zero truncation
      const CHUNK_DURATION = 60;
      const OVERLAP = 4;
      const numChunks = Math.ceil(totalDurationSeconds / CHUNK_DURATION);
      const CONCURRENCY = 6;
      console.log(`[Audio Chunking] Audio duration: ${(totalDurationSeconds / 60).toFixed(1)} mins (${totalDurationSeconds.toFixed(1)}s). Processing ${numChunks} chunks of ${CHUNK_DURATION}s (concurrency=${CONCURRENCY})...`);

      const chunksToProcess = [];
      for (let i = 0; i < numChunks; i++) {
        const startSec = i * CHUNK_DURATION;
        const isLastChunk = i === numChunks - 1;
        const chunkDuration = isLastChunk
          ? Math.max(1, totalDurationSeconds - startSec)
          : Math.min(totalDurationSeconds - startSec, CHUNK_DURATION + OVERLAP);
        const chunkPath = `/tmp/uploads/chk_${i}_${Date.now()}.mp3`;
        tempFilesToClean.push(chunkPath);
        chunksToProcess.push({ index: i, startSec, chunkDuration, isLastChunk, chunkPath });
      }

      const chunkResults: any[] = [];
      const queue = [...chunksToProcess];

      const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
        while (queue.length > 0) {
          const item = queue.shift();
          if (!item) break;
          const { index, startSec, chunkDuration, isLastChunk, chunkPath } = item;
          try {
            console.log(`[Audio Chunking] Processing chunk ${index + 1}/${numChunks} (${startSec}s - ${(startSec + chunkDuration).toFixed(1)}s)...`);
            // Clean frame-accurate MP3 slice with libmp3lame
            await execPromise(`ffmpeg -y -ss ${startSec} -t ${chunkDuration} -i "${optimizedAudioPath}" -c:a libmp3lame -b:a 48k "${chunkPath}"`);
            const chunkBuffer = fs.readFileSync(chunkPath);
            const chunkBase64 = chunkBuffer.toString('base64');
            const res = await callGeminiForAudioChunk(
              chunkBase64,
              'audio/mp3',
              isTurbo,
              sourceLang,
              targetLang
            );
            chunkResults.push({ index, startSec, isLastChunk, res });
            await new Promise((r) => setTimeout(r, 150));
          } catch (chunkErr: any) {
            console.error(`[Audio Chunking] Chunk ${index + 1}/${numChunks} warning:`, chunkErr);
          }
        }
      });

      await Promise.all(workers);
      chunkResults.sort((a, b) => a.index - b.index);

      const rawAllSegments: any[] = [];

      for (const item of chunkResults) {
        const { index, startSec, isLastChunk, res } = item;
        if (detectedLanguage === 'Auto' && res.detectedLanguage) {
          detectedLanguage = res.detectedLanguage;
        }
        if (!summary && res.summary) {
          summary = res.summary;
        }
        successfulModel = res.model;
        if (res.usageMetadata) {
          totalCandidatesTokens += res.usageMetadata.candidatesTokenCount || 0;
          totalPromptTokens += res.usageMetadata.promptTokenCount || 0;
        }

        const nextChunkWindowStart = (index + 1) * CHUNK_DURATION;

        for (const seg of res.segments) {
          const segStart = typeof seg.startSeconds === 'number' ? seg.startSeconds : 0;
          const segEnd = typeof seg.endSeconds === 'number' ? seg.endSeconds : segStart + 2.5;

          const realStart = startSec + segStart;
          const realEnd = startSec + segEnd;

          // Boundary filter: if not the last chunk, let the next chunk handle segments that begin in its window
          if (!isLastChunk && realStart >= nextChunkWindowStart) {
            continue;
          }

          const rawTrans = seg.translatedText || '';
          const rawSrc = seg.sourceText || '';
          const cleanTrans = cleanSpeakerTagFromText(rawTrans);
          const cleanSrc = cleanSpeakerTagFromText(rawSrc);

          const gender = (seg.gender || '').toLowerCase();
          const spk = seg.speaker || '';
          let finalSpk = seg.speaker || (gender === 'female' ? 'ស្រី (Female)' : gender === 'child' ? 'ក្មេង (Child)' : 'ប្រុស (Male)');
          let finalGender = seg.gender || 'male';
          if (gender === 'child' || spk.includes('ក្មេង') || rawTrans.includes('[ក្មេង]')) {
            finalSpk = 'ក្មេង (Child)';
            finalGender = 'child';
          } else if (gender === 'female' || spk.includes('ស្រី') || rawTrans.includes('[ស្រី]')) {
            finalSpk = 'ស្រី (Female)';
            finalGender = 'female';
          }

          rawAllSegments.push({
            startTime: formatSecondsToSrt(realStart).split(',')[0],
            endTime: formatSecondsToSrt(realEnd).split(',')[0],
            startSeconds: Math.round(realStart * 100) / 100,
            endSeconds: Math.round(Math.max(realEnd, realStart + 0.5) * 100) / 100,
            speaker: finalSpk,
            speakerId: seg.speakerId || (finalGender === 'female' ? 'speaker_02' : 'speaker_01'),
            persona: seg.persona || (finalGender === 'child' ? '👦 Boy / Child' : finalGender === 'female' ? '👩 Female Adult' : '👨 Male Adult'),
            emotion: seg.emotion || '😐 Neutral',
            speakingStyle: seg.speakingStyle || 'Normal',
            gender: finalGender,
            sourceText: cleanSrc || rawSrc,
            translatedText: cleanTrans || rawTrans,
          });
        }
      }

      // 1. Sort strictly by chronological startSeconds to ensure zero backwards jumps
      rawAllSegments.sort((a, b) => a.startSeconds - b.startSeconds);

      // 2. Normalize timestamps, remove boundary duplicates, and eliminate overlaps
      const normalizedSegments: any[] = [];
      for (const curr of rawAllSegments) {
        if (!curr.translatedText && !curr.sourceText) continue;

        if (normalizedSegments.length === 0) {
          normalizedSegments.push({ ...curr, id: 1 });
          continue;
        }

        const prev = normalizedSegments[normalizedSegments.length - 1];

        // Detect duplicate boundary segments from overlap region
        const isDuplicateText =
          curr.sourceText && prev.sourceText &&
          (curr.sourceText.trim().toLowerCase() === prev.sourceText.trim().toLowerCase() ||
           curr.translatedText.trim() === prev.translatedText.trim());
        const isOverlappingClose = curr.startSeconds < prev.endSeconds;

        if (isDuplicateText && isOverlappingClose) {
          if (curr.endSeconds > prev.endSeconds) {
            prev.endSeconds = curr.endSeconds;
            prev.endTime = formatSecondsToSrt(prev.endSeconds).split(',')[0];
          }
          continue;
        }

        // If overlapping timestamps, adjust smoothly to prevent audio collision
        if (curr.startSeconds < prev.endSeconds) {
          const overlapSec = prev.endSeconds - curr.startSeconds;
          if (overlapSec > 0.05) {
            if (curr.startSeconds - prev.startSeconds >= 1.0) {
              prev.endSeconds = Math.round(curr.startSeconds * 100) / 100;
              prev.endTime = formatSecondsToSrt(prev.endSeconds).split(',')[0];
            } else {
              curr.startSeconds = Math.round(prev.endSeconds * 100) / 100;
              curr.startTime = formatSecondsToSrt(curr.startSeconds).split(',')[0];
              if (curr.endSeconds <= curr.startSeconds) {
                curr.endSeconds = Math.round((curr.startSeconds + 1.5) * 100) / 100;
                curr.endTime = formatSecondsToSrt(curr.endSeconds).split(',')[0];
              }
            }
          }
        }

        curr.id = normalizedSegments.length + 1;
        normalizedSegments.push(curr);
      }

      allSegments = normalizedSegments;

      if (allSegments.length === 0 && numChunks > 0) {
        throw new Error('ការតភ្ជាប់ទៅកាន់ Gemini AI បរាជ័យ (Connection Error / Network DNS Failure)។ សូមពិនិត្យមើលការភ្ជាប់អ៊ីនធឺណិត ឬ API Key។');
      }
    }

    const totalProcessingTimeMs = Date.now() - requestStartTime;
    const readySrt = buildSrtString(allSegments);

    const tokensPerSecond =
      totalCandidatesTokens && totalProcessingTimeMs > 0
        ? Math.round((totalCandidatesTokens / (totalProcessingTimeMs / 1000)) * 10) / 10
        : null;

    // Auto-save to output directory for instant Desktop Studio sync (Project JSON format)
    try {
      const outputDir = path.resolve(__dirname, '..', 'output');
      if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });
      fs.writeFileSync(path.join(outputDir, 'latest_web_subtitles.srt'), readySrt, 'utf-8');

      const enrichedSegments = allSegments.map((s, idx) => ({
        id: s.id || idx + 1,
        speaker_id: s.speakerId || 'speaker_01',
        speaker: s.speaker || '👨 Male Adult',
        persona: s.persona || (s.gender === 'child' ? '👦 Boy / Child' : s.gender === 'female' ? '👩 Female Adult' : '👨 Male Adult'),
        emotion: s.emotion || '😐 Neutral',
        speaking_style: s.speakingStyle || 'Normal',
        gender: s.gender || 'male',
        voice: s.gender === 'female' ? 'Khmer Female - Sreymom' : s.gender === 'child' ? 'Khmer Child - Boy (Vannak)' : 'Khmer Male - Piseth',
        voice_id: s.gender === 'female' ? 'Khmer Female - Sreymom' : s.gender === 'child' ? 'Khmer Child - Boy (Vannak)' : 'Khmer Male - Piseth',
        startSeconds: s.startSeconds,
        endSeconds: s.endSeconds,
        start: s.startSeconds,
        end: s.endSeconds,
        startTime: s.startTime,
        endTime: s.endTime,
        sourceText: s.sourceText,
        translatedText: s.translatedText,
        original_text: s.sourceText,
        khmer_text: s.translatedText,
      }));

      fs.writeFileSync(path.join(outputDir, 'latest_web_subtitles.json'), JSON.stringify(enrichedSegments, null, 2), 'utf-8');
      console.log(`[Auto-Sync] Successfully saved ${enrichedSegments.length} enriched segments to output/latest_web_subtitles.json (${(totalProcessingTimeMs / 1000).toFixed(1)}s)`);
    } catch (saveErr: any) {
      console.warn('[Auto-Sync] Warning saving output files:', saveErr.message);
    }

    return res.json({
      detectedLanguage: detectedLanguage || 'Auto',
      targetLanguage: targetLang || 'Khmer',
      summary: summary || 'ការបកប្រែ Subtitle ជាភាសាខ្មែរជោគជ័យ',
      totalDurationEstimate: formatSecondsToSrt(totalDurationSeconds).split(',')[0],
      segments: allSegments,
      srtText: readySrt,
      flashUsage: {
        model: successfulModel,
        processingTimeMs: totalProcessingTimeMs,
        promptTokenCount: totalPromptTokens || null,
        candidatesTokenCount: totalCandidatesTokens || null,
        totalTokenCount: (totalPromptTokens + totalCandidatesTokens) || null,
        isTurbo,
        tokensPerSecond,
      },
    });
  } catch (error: any) {
    for (const f of tempFilesToClean) {
      fs.unlink(f, () => {});
    }

    console.error('Translation error:', error);
    let userMessage = error.message || 'Failed to process and translate audio';
    let isHighDemand = false;

    const causeStr = error.cause ? String(error.cause) : '';
    const fullErrStr = `${userMessage} ${causeStr} ${error.toString()}`.toLowerCase();

    if (fullErrStr.includes('enotfound') || fullErrStr.includes('econnrefused') || fullErrStr.includes('fetch failed')) {
      userMessage = 'មិនអាចតភ្ជាប់ទៅកាន់ Google Gemini AI បានទេ (DNS / Network Connection Error)។ សូមពិនិត្យមើលការភ្ជាប់អ៊ីនធឺណិត ឬ Firewall។';
    } else if (fullErrStr.includes('429') || fullErrStr.includes('quota') || fullErrStr.includes('resource_exhausted')) {
      userMessage = 'ប្រព័ន្ធ AI ប្រើប្រាស់លើសកូតា (Rate Limit 429)។ សូមរង់ចាំបន្តិច រួចសាកល្បងម្ដងទៀត។';
    } else if (fullErrStr.includes('503') || fullErrStr.includes('high demand') || fullErrStr.includes('unavailable')) {
      isHighDemand = true;
      userMessage = 'ម៉ាស៊ីនបម្រើ AI កំពុងមានអ្នកប្រើប្រាស់ច្រើនក្នុងពេលតែមួយ (503)។ សូមរង់ចាំបន្តិច រួចសាកល្បងម្ដងទៀត។';
    }

    return res.status(500).json({
      error: userMessage,
      isHighDemand,
      details: error.toString(),
    });
  }
});

// Vite or Static files setup
async function startServer() {
  if (!isProd) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static(path.resolve(__dirname, 'dist')));
    app.get('*', (req, res) => {
      res.sendFile(path.resolve(__dirname, 'dist', 'index.html'));
    });
  }

  app.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
  });
}

startServer();
