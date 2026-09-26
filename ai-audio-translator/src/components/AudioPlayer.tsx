import React, { useRef, useEffect, useState } from 'react';
import { Play, Pause, Volume2, VolumeX, RotateCcw, FastForward, Music, Film, Maximize2 } from 'lucide-react';
import { formatTimeDisplay } from '../utils/subtitles';

interface AudioPlayerProps {
  audioUrl: string | null;
  audioName?: string;
  currentTime: number;
  onTimeUpdate: (time: number) => void;
  seekToTime?: number | null;
  onSeekComplete?: () => void;
  activeSubtitleText?: string;
}

export const AudioPlayer: React.FC<AudioPlayerProps> = ({
  audioUrl,
  audioName = 'Audio File',
  currentTime,
  onTimeUpdate,
  seekToTime,
  onSeekComplete,
  activeSubtitleText,
}) => {
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);

  const isVideo = audioName.match(/\.(mp4|mov|webm|mkv|avi)$/i);
  const [showVideoScreen, setShowVideoScreen] = useState<boolean>(!!isVideo);

  useEffect(() => {
    if (seekToTime !== null && seekToTime !== undefined && mediaRef.current) {
      mediaRef.current.currentTime = seekToTime;
      onTimeUpdate(seekToTime);
      if (!isPlaying) {
        mediaRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
      }
      if (onSeekComplete) onSeekComplete();
    }
  }, [seekToTime]);

  useEffect(() => {
    setIsPlaying(false);
    if (mediaRef.current) {
      mediaRef.current.currentTime = 0;
    }
    if (isVideo) {
      setShowVideoScreen(true);
    }
  }, [audioUrl, audioName]);

  const togglePlay = () => {
    if (!mediaRef.current) return;
    if (isPlaying) {
      mediaRef.current.pause();
      setIsPlaying(false);
    } else {
      mediaRef.current.play().then(() => setIsPlaying(true)).catch(console.error);
    }
  };

  const handleTimeUpdate = () => {
    if (mediaRef.current) {
      onTimeUpdate(mediaRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (mediaRef.current) {
      setDuration(mediaRef.current.duration || 0);
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (mediaRef.current) {
      mediaRef.current.currentTime = time;
      onTimeUpdate(time);
    }
  };

  const toggleMute = () => {
    if (!mediaRef.current) return;
    const nextMuted = !isMuted;
    mediaRef.current.muted = nextMuted;
    setIsMuted(nextMuted);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value);
    setVolume(val);
    if (mediaRef.current) {
      mediaRef.current.volume = val;
      mediaRef.current.muted = val === 0;
      setIsMuted(val === 0);
    }
  };

  const handleSpeedChange = () => {
    const speeds = [0.75, 1.0, 1.25, 1.5, 2.0];
    const nextIndex = (speeds.indexOf(playbackRate) + 1) % speeds.length;
    const nextSpeed = speeds[nextIndex];
    setPlaybackRate(nextSpeed);
    if (mediaRef.current) {
      mediaRef.current.playbackRate = nextSpeed;
    }
  };

  const handleSkip = (seconds: number) => {
    if (mediaRef.current) {
      const nextTime = Math.max(0, Math.min(duration, mediaRef.current.currentTime + seconds));
      mediaRef.current.currentTime = nextTime;
      onTimeUpdate(nextTime);
    }
  };

  if (!audioUrl) return null;

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-3xl p-4 sm:p-5 shadow-2xl backdrop-blur-md space-y-3">
      {/* Video Screen with Synced Subtitle Overlay (if video format) */}
      {isVideo && showVideoScreen ? (
        <div className="relative rounded-2xl overflow-hidden bg-black aspect-video max-h-[420px] mx-auto flex items-center justify-center border border-slate-800 shadow-2xl">
          <video
            ref={mediaRef as React.RefObject<HTMLVideoElement>}
            src={audioUrl}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
            onEnded={() => setIsPlaying(false)}
            onClick={togglePlay}
            className="w-full h-full object-contain cursor-pointer"
          />

          {/* Real-time Khmer Subtitle Overlay at the bottom */}
          {activeSubtitleText && (
            <div className="absolute bottom-6 left-4 right-4 text-center pointer-events-none transition-all">
              <span className="inline-block px-4 py-2 rounded-xl bg-slate-950/90 text-amber-300 font-extrabold text-sm sm:text-base border border-amber-500/30 shadow-2xl backdrop-blur-md max-w-[90%] leading-relaxed">
                {activeSubtitleText}
              </span>
            </div>
          )}

          {/* Toggle Screen Button */}
          <button
            type="button"
            onClick={() => setShowVideoScreen(false)}
            className="absolute top-3 right-3 px-2.5 py-1 rounded-lg bg-slate-950/80 hover:bg-slate-900 text-slate-300 border border-slate-700 text-xs font-medium backdrop-blur-sm transition"
            title="បិទផ្ទាំងវីដេអូ (ប្តូរមក Audio Mode)"
          >
            បង្រួមតូច
          </button>
        </div>
      ) : (
        <audio
          ref={mediaRef as React.RefObject<HTMLAudioElement>}
          src={audioUrl}
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onEnded={() => setIsPlaying(false)}
        />
      )}

      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 shrink-0">
            {isVideo ? <Film className="w-4 h-4" /> : <Music className="w-4 h-4" />}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-100 truncate">{audioName}</p>
            <p className="text-xs text-slate-400 font-mono">
              {formatTimeDisplay(currentTime)} / {formatTimeDisplay(duration)}
            </p>
          </div>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {isVideo && !showVideoScreen && (
            <button
              type="button"
              onClick={() => setShowVideoScreen(true)}
              className="text-xs font-semibold px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-amber-400 border border-slate-700 transition flex items-center gap-1 cursor-pointer"
            >
              <Film className="w-3.5 h-3.5" />
              <span>មើលវីដេអូ</span>
            </button>
          )}

          <button
            onClick={handleSpeedChange}
            type="button"
            className="text-xs font-mono font-bold px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition cursor-pointer"
            title="ផ្លាស់ប្តូរល្បឿនចាក់សំឡេង (Playback Speed)"
          >
            {playbackRate}x
          </button>
        </div>
      </div>

      {/* Progress Track */}
      <div className="relative group">
        <div className="w-full bg-slate-800 h-2.5 rounded-full overflow-hidden">
          <div
            className="bg-gradient-to-r from-amber-500 to-amber-400 h-full rounded-full transition-all duration-75 relative"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <input
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          aria-label="Timeline seeker"
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
      </div>

      {/* Controls Bar */}
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-1.5 sm:gap-2">
          <button
            type="button"
            onClick={() => handleSkip(-5)}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition cursor-pointer"
            title="ថយក្រោយ 5 វិនាទី (-5s)"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <button
            type="button"
            onClick={togglePlay}
            className="p-3 bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold rounded-2xl shadow-lg shadow-amber-500/25 transition active:scale-95 cursor-pointer"
            title={isPlaying ? 'ផ្អាក (Pause)' : 'ចាក់ (Play)'}
          >
            {isPlaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
          </button>

          <button
            type="button"
            onClick={() => handleSkip(5)}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition cursor-pointer"
            title="ទៅមុខ 5 វិនាទី (+5s)"
          >
            <FastForward className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleMute}
            className="p-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-xl transition cursor-pointer"
            title={isMuted ? 'បើកសំឡេង' : 'បិទសំឡេង'}
          >
            {isMuted || volume === 0 ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={isMuted ? 0 : volume}
            onChange={handleVolumeChange}
            aria-label="Volume controller"
            className="w-16 sm:w-24 accent-amber-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
          />
        </div>
      </div>
    </div>
  );
};
