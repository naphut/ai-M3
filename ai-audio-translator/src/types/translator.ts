export interface Segment {
  id: number;
  startTime: string; // e.g. "00:01:02" or "00:01:02.000"
  endTime: string;
  startSeconds: number;
  endSeconds: number;
  speaker?: string;
  speakerId?: string;
  persona?: string;
  emotion?: string;
  speakingStyle?: string;
  gender?: 'male' | 'female' | 'child' | 'elder' | string;
  sourceText: string;
  translatedText: string;
}

export const PERSONA_OPTIONS = [
  '👨 Male Adult',
  '👩 Female Adult',
  '👦 Boy / Child',
  '👧 Girl / Child',
  '👴 Elderly Male',
  '👵 Elderly Female',
  '👨‍🦱 Young Male',
  '👩‍🦰 Young Female',
  '🎭 Narrator',
  '🤖 AI / Robot',
  '📢 Announcer',
  '👥 Crowd / Group'
];

export const EMOTION_OPTIONS = [
  '😐 Neutral',
  '😊 Happy',
  '😢 Sad',
  '😡 Angry',
  '😨 Fear',
  '🤩 Excited',
  '🥰 Romantic',
  '😭 Crying',
  '😲 Surprised'
];

export const STYLE_OPTIONS = [
  'Normal',
  'Fast',
  'Slow',
  'Soft',
  'Loud',
  'Whisper',
  'Serious',
  'Dramatic'
];

export interface FlashUsage {
  model: string;
  processingTimeMs: number;
  promptTokenCount?: number | null;
  candidatesTokenCount?: number | null;
  totalTokenCount?: number | null;
  isTurbo?: boolean;
  tokensPerSecond?: number | null;
}

export interface TranslationResult {
  detectedLanguage: string;
  targetLanguage: string;
  summary: string;
  totalDurationEstimate?: string;
  segments: Segment[];
  srtText?: string;
  flashUsage?: FlashUsage;
}

export type QueueItemStatus = 'pending' | 'converting' | 'processing' | 'completed' | 'error';

export interface QueueItem {
  id: string;
  file: File | null;
  name: string;
  size: number;
  duration: number;
  objectUrl: string;
  base64: string;
  mimeType: string;
  status: QueueItemStatus;
  progress: number; // 0 to 100
  progressStep: string;
  result: TranslationResult | null;
  localFilePath?: string;
  error: string | null;
  createdAt: number;
  startedAt?: number;
  completedAt?: number;
}

export interface AudioFileState {
  file: File | null;
  name: string;
  size: number;
  duration: number;
  objectUrl: string;
  base64: string;
  mimeType: string;
  localFilePath?: string;
}

export interface LanguageOption {
  code: string;
  name: string;
  nativeName: string;
  flag: string;
}

export const SOURCE_LANGUAGES: LanguageOption[] = [
  { code: 'Auto', name: 'Auto Detect', nativeName: 'ស្វ័យប្រវត្តិ (Auto)', flag: '🌐' },
  { code: 'Korean', name: 'Korean', nativeName: '한국어 (Korean)', flag: '🇰🇷' },
  { code: 'English', name: 'English', nativeName: 'English (US/UK)', flag: '🇺🇸' },
  { code: 'Japanese', name: 'Japanese', nativeName: '日本語 (Japanese)', flag: '🇯🇵' },
  { code: 'Chinese', name: 'Chinese', nativeName: '中文 (Chinese)', flag: '🇨🇳' },
  { code: 'Thai', name: 'Thai', nativeName: 'ภาษาไทย (Thai)', flag: '🇹🇭' },
  { code: 'Vietnamese', name: 'Vietnamese', nativeName: 'Tiếng Việt', flag: '🇻🇳' },
  { code: 'French', name: 'French', nativeName: 'Français', flag: '🇫🇷' },
  { code: 'Spanish', name: 'Spanish', nativeName: 'Español', flag: '🇪🇸' },
  { code: 'German', name: 'German', nativeName: 'Deutsch', flag: '🇩🇪' },
  { code: 'Khmer', name: 'Khmer', nativeName: 'ភាសាខ្មែរ (Khmer)', flag: '🇰🇭' },
];

export const TARGET_LANGUAGES: LanguageOption[] = [
  { code: 'Khmer', name: 'Khmer', nativeName: 'ភាសាខ្មែរ', flag: '🇰🇭' },
  { code: 'English', name: 'English', nativeName: 'English', flag: '🇬🇧' },
  { code: 'Korean', name: 'Korean', nativeName: '한국어', flag: '🇰🇷' },
  { code: 'Japanese', name: 'Japanese', nativeName: '日本語', flag: '🇯🇵' },
  { code: 'Chinese', name: 'Chinese', nativeName: '中文', flag: '🇨🇳' },
  { code: 'French', name: 'French', nativeName: 'Français', flag: '🇫🇷' },
];
