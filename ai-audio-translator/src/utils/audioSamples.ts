import { TranslationResult } from '../types/translator';

export interface SampleAudio {
  id: string;
  title: string;
  sourceLang: string;
  targetLang: string;
  flag: string;
  description: string;
  durationSeconds: number;
  mockResult: TranslationResult;
}

export const SAMPLE_AUDIOS: SampleAudio[] = [
  {
    id: 'korean-daily',
    title: 'Korean Daily Chat (한국어)',
    sourceLang: 'Korean',
    targetLang: 'Khmer',
    flag: '🇰🇷',
    description: 'ការសន្ទនាប្រចាំថ្ងៃ: "오늘 뭐 하고 있어요?"',
    durationSeconds: 9,
    mockResult: {
      detectedLanguage: 'Korean (한국어)',
      targetLanguage: 'Khmer (ភាសាខ្មែរ)',
      summary: 'ការសន្ទនាសាកសួរអំពីសកម្មភាពប្រចាំថ្ងៃ និងផែនការញ៉ាំអាហារពេលល្ងាចជាមួយគ្នា។',
      totalDurationEstimate: '00:00:09',
      flashUsage: {
        model: 'gemini-3.8-flash',
        processingTimeMs: 1420,
        promptTokenCount: 110,
        candidatesTokenCount: 195,
        totalTokenCount: 305,
      },
      segments: [
        {
          id: 1,
          startTime: '00:00:01',
          endTime: '00:00:03',
          startSeconds: 1.0,
          endSeconds: 3.2,
          speaker: 'Speaker 1',
          sourceText: '안녕하세요! 오늘 뭐 하고 있어요?',
          translatedText: 'សួស្តី! តើឥឡូវនេះអ្នកកំពុងធ្វើអ្វី?',
        },
        {
          id: 2,
          startTime: '00:00:03',
          endTime: '00:00:06',
          startSeconds: 3.5,
          endSeconds: 6.1,
          speaker: 'Speaker 2',
          sourceText: '저는 지금 회사에서 일하고 있어요. 퇴근 후에 시간 있어요?',
          translatedText: 'ខ្ញុំកំពុងធ្វើការនៅក្រុមហ៊ុន។ តើអ្នកមានពេលទំនេរទេក្រោយចេញពីធ្វើការ?',
        },
        {
          id: 3,
          startTime: '00:00:06',
          endTime: '00:00:09',
          startSeconds: 6.4,
          endSeconds: 9.0,
          speaker: 'Speaker 1',
          sourceText: '네! 같이 맛있는 저녁 식사하러 가요.',
          translatedText: 'បាទ/ចាស! តោះទៅញ៉ាំអាហារពេលល្ងាចឆ្ងាញ់ៗជាមួយគ្នា។',
        },
      ],
    },
  },
  {
    id: 'english-tech',
    title: 'English AI Introduction',
    sourceLang: 'English',
    targetLang: 'Khmer',
    flag: '🇺🇸',
    description: 'Introduction to Next-Gen AI transcription',
    durationSeconds: 11,
    mockResult: {
      detectedLanguage: 'English',
      targetLanguage: 'Khmer (ភាសាខ្មែរ)',
      summary: 'ការណែនាំអំពីបច្ចេកវិទ្យា AI ជំនាន់ថ្មីក្នុងការបំប្លែងសំឡេងទៅជាអត្ថបទ និងការបកប្រែពហុភាសា។',
      totalDurationEstimate: '00:00:11',
      flashUsage: {
        model: 'gemini-3.8-flash',
        processingTimeMs: 1650,
        promptTokenCount: 140,
        candidatesTokenCount: 220,
        totalTokenCount: 360,
      },
      segments: [
        {
          id: 1,
          startTime: '00:00:00',
          endTime: '00:00:03',
          startSeconds: 0.5,
          endSeconds: 3.4,
          speaker: 'Speaker 1',
          sourceText: 'Welcome everyone! Today we introduce the next-generation AI audio translator.',
          translatedText: 'សូមស្វាគមន៍អ្នកទាំងអស់គ្នា! ថ្ងៃនេះយើងសូមណែនាំកម្មវិធីបកប្រែសំឡេង AI ជំនាន់ថ្មី។',
        },
        {
          id: 2,
          startTime: '00:00:03',
          endTime: '00:00:07',
          startSeconds: 3.8,
          endSeconds: 7.2,
          speaker: 'Speaker 1',
          sourceText: 'It automatically converts spoken words into accurate timecoded subtitles.',
          translatedText: 'វាបំប្លែងពាក្យសំដីទៅជាចំណងជើងរង (Subtitles) ដែលមានកំណត់ម៉ោងយ៉ាងសុក្រឹតដោយស្វ័យប្រវត្តិ។',
        },
        {
          id: 3,
          startTime: '00:00:07',
          endTime: '00:00:11',
          startSeconds: 7.5,
          endSeconds: 11.0,
          speaker: 'Speaker 1',
          sourceText: 'You can export to SRT, VTT, and plain text formats with one single click.',
          translatedText: 'អ្នកអាចទាញយកឯកសារជាទម្រង់ SRT, VTT និង Text បានយ៉ាងងាយស្រួលដោយគ្រាន់តែចុចមួយដងប៉ុណ្ណោះ។',
        },
      ],
    },
  },
  {
    id: 'japanese-greetings',
    title: 'Japanese Casual (日本語)',
    sourceLang: 'Japanese',
    targetLang: 'Khmer',
    flag: '🇯🇵',
    description: 'ការសន្ទនាបែបជប៉ុន: "こんにちは、お元気ですか？"',
    durationSeconds: 8,
    mockResult: {
      detectedLanguage: 'Japanese (日本語)',
      targetLanguage: 'Khmer (ភាសាខ្មែរ)',
      summary: 'ការសួរសុខទុក្ខ និងការណែនាំខ្លួនជាភាសាជប៉ុន។',
      totalDurationEstimate: '00:00:08',
      flashUsage: {
        model: 'gemini-3.8-flash',
        processingTimeMs: 1380,
        promptTokenCount: 95,
        candidatesTokenCount: 160,
        totalTokenCount: 255,
      },
      segments: [
        {
          id: 1,
          startTime: '00:00:00',
          endTime: '00:00:03',
          startSeconds: 0.8,
          endSeconds: 3.2,
          speaker: 'Speaker 1',
          sourceText: 'こんにちは！お元気ですか？',
          translatedText: 'សួស្តី! តើអ្នកសុខសប្បាយជាទេ?',
        },
        {
          id: 2,
          startTime: '00:00:03',
          endTime: '00:00:08',
          startSeconds: 3.5,
          endSeconds: 7.8,
          speaker: 'Speaker 2',
          sourceText: 'はい、元気です！カンボジアへの旅行をとても楽しみにしています。',
          translatedText: 'បាទ/ចាស ខ្ញុំសុខសប្បាយទេ! ខ្ញុំពិតជារំភើបចិត្តខ្លាំងណាស់ក្នុងការធ្វើដំណើរទៅកាន់ប្រទេសកម្ពុជា។',
        },
      ],
    },
  },
];

/**
 * Generate a synthetic audio WAV blob in-browser so users can play and test
 * immediately without needing to upload an external file.
 */
export function createSyntheticSampleAudio(durationSeconds: number = 8): { blob: Blob; url: string; base64Promise: Promise<string> } {
  const sampleRate = 22050;
  const numChannels = 1;
  const numSamples = Math.floor(sampleRate * durationSeconds);
  const bytesPerSample = 2; // 16-bit PCM
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = numSamples * blockAlign;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  // RIFF chunk descriptor
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');

  // fmt sub-chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
  view.setUint16(20, 1, true); // AudioFormat (1 for PCM)
  view.setUint16(22, numChannels, true); // NumChannels
  view.setUint32(24, sampleRate, true); // SampleRate
  view.setUint32(28, byteRate, true); // ByteRate
  view.setUint16(32, blockAlign, true); // BlockAlign
  view.setUint16(34, 16, true); // BitsPerSample

  // data sub-chunk
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // Write synthesized audio waveform (harmonic tones resembling speech prosody)
  let offset = 44;
  for (let i = 0; i < numSamples; i++) {
    const t = i / sampleRate;
    // Formant-like frequencies with cadence envelope
    const envelope = Math.sin(Math.PI * (t % 1.5) / 1.5) * (t < durationSeconds - 0.2 ? 1 : 0);
    const f1 = 220 + 30 * Math.sin(2 * Math.PI * 3 * t);
    const f2 = 440 + 60 * Math.sin(2 * Math.PI * 1.5 * t);
    const s1 = Math.sin(2 * Math.PI * f1 * t);
    const s2 = Math.sin(2 * Math.PI * f2 * t) * 0.5;
    const sample = Math.max(-1, Math.min(1, (s1 + s2) * 0.3 * Math.max(0, envelope)));
    const int16 = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(offset, int16, true);
    offset += 2;
  }

  const blob = new Blob([buffer], { type: 'audio/wav' });
  const url = URL.createObjectURL(blob);

  const base64Promise = new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const res = reader.result as string;
      const base64 = res.split(',')[1] || '';
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });

  return { blob, url, base64Promise };
}

function writeString(view: DataView, offset: number, string: string) {
  for (let i = 0; i < string.length; i++) {
    view.setUint8(offset + i, string.charCodeAt(i));
  }
}
