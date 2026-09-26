/**
 * Desktop Studio Bridge Helper
 * Connects Web Studio (both on localhost:3000 and hosted on https://ai.studio/apps/...)
 * to the PySide6 Desktop Studio background backend at http://127.0.0.1:3000
 */

export const LOCAL_SERVER_BASE = 'http://127.0.0.1:3000';

export const isRunningLocally = (): boolean => {
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  return host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0';
};

// Fast ping to check if local Desktop Studio server is running
export async function pingLocalServer(timeoutMs = 1200): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const res = await fetch(`${LOCAL_SERVER_BASE}/api/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timer);
    return res.ok;
  } catch {
    return false;
  }
}

// Fetch helper with fallback between local Desktop Studio server and current host
export async function fetchWithDesktopFallback(
  endpoint: string,
  options?: RequestInit,
  timeoutMs = 3000
): Promise<{ res: Response; isLocal: boolean }> {
  // If we are already running on localhost, directly fetch relative path
  if (isRunningLocally()) {
    const res = await fetch(endpoint, options);
    return { res, isLocal: true };
  }

  // If running on cloud (e.g. https://ai.studio/apps/cba70a44-052d-4127-835e-c868a8c6f4ab):
  // 1. Try local Desktop Studio backend at http://127.0.0.1:3000 first
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const localRes = await fetch(`${LOCAL_SERVER_BASE}${endpoint}`, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (localRes.ok) {
      return { res: localRes, isLocal: true };
    }
  } catch {
    // Local server not reachable on 127.0.0.1:3000
  }

  // 2. Fallback to current host endpoint
  const fallbackRes = await fetch(endpoint, options);
  return { res: fallbackRes, isLocal: false };
}

// Fetch the latest MP3 file generated in Desktop Studio as a true in-memory File object
export async function fetchLatestDesktopMp3File(): Promise<{
  file: File;
  name: string;
  size: number;
  objectUrl: string;
  filePath: string;
  isLocalServer: boolean;
}> {
  const { res, isLocal } = await fetchWithDesktopFallback('/api/latest-desktop-mp3');
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.error || `Server responded with ${res.status}`);
  }

  const data = await res.json();
  if (data.status !== 'ok' || !data.filePath) {
    throw new Error(data.error || 'រកមិនឃើញ File MP3 ថ្មីក្នុង Desktop Studio ឡើយ');
  }

  // Resolve audio streaming URL
  const baseUrl = isLocal && !isRunningLocally() ? LOCAL_SERVER_BASE : '';
  const audioStreamUrl = `${baseUrl}${data.streamUrl}`;

  // Download the audio data as a real binary Blob
  const audioResp = await fetch(audioStreamUrl);
  if (!audioResp.ok) {
    throw new Error(`បរាជ័យក្នុងការទាញយកសំឡេង MP3 (${audioResp.status})`);
  }

  const blob = await audioResp.blob();
  const file = new File([blob], data.name, { type: data.mimeType || 'audio/mp3' });
  const objectUrl = URL.createObjectURL(file);

  return {
    file,
    name: data.name,
    size: data.size || blob.size,
    objectUrl,
    filePath: data.filePath,
    isLocalServer: isLocal,
  };
}

// Load a local file path and convert to a real in-memory File object
export async function loadLocalAudioFilePath(filePath: string): Promise<{
  file: File;
  name: string;
  size: number;
  objectUrl: string;
  filePath: string;
  isLocalServer: boolean;
}> {
  const { res, isLocal } = await fetchWithDesktopFallback('/api/load-local-audio', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filePath }),
  });

  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.error || `Server error (${res.status})`);
  }

  const data = await res.json();
  if (data.status !== 'ok') {
    throw new Error(data.error || 'Failed to load local file');
  }

  const baseUrl = isLocal && !isRunningLocally() ? LOCAL_SERVER_BASE : '';
  const audioStreamUrl = `${baseUrl}${data.streamUrl}`;

  const audioResp = await fetch(audioStreamUrl);
  if (!audioResp.ok) {
    throw new Error(`បរាជ័យក្នុងការទាញយកទិន្នន័យសំឡេង (${audioResp.status})`);
  }

  const blob = await audioResp.blob();
  const file = new File([blob], data.name, { type: data.mimeType || 'audio/mp3' });
  const objectUrl = URL.createObjectURL(file);

  return {
    file,
    name: data.name,
    size: data.size || blob.size,
    objectUrl,
    filePath: data.filePath,
    isLocalServer: isLocal,
  };
}

// Send subtitles directly to Desktop Studio with clipboard fallback
export async function sendSubtitlesToDesktopStudio(srtText: string, segments: any[]): Promise<boolean> {
  // Always copy to clipboard immediately so Cmd+V in Desktop Studio works instantly
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(srtText);
    }
  } catch (clipErr) {
    console.warn('[Clipboard] Could not write to clipboard:', clipErr);
  }

  try {
    const { res } = await fetchWithDesktopFallback(
      '/api/export-to-studio',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ srtText, segments }),
      },
      3000
    );
    return res.ok;
  } catch (err) {
    console.warn('[DesktopBridge] Export to studio failed:', err);
    return false;
  }
}
