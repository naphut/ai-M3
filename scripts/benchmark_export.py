#!/usr/bin/env python3
"""
Vide AI Studio - Export Pipeline Benchmark & Performance Profiler
Instruments VideoExportPipeline with low-overhead timers and system telemetry on macOS M2.
"""

import os
import sys
import time
import json
import csv
import subprocess
import threading
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

import psutil
import cv2
import numpy as np

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qt_compat import QApplication
# Initialize headless Qt Application if not present (required for QFont/QPainter text rendering)
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv[:1])

from core.export_engine import VideoExportPipeline, EffectsProcessor, compute_target_resolution
from utils.file_utils import get_temp_path
from utils.logger import logger


def get_mac_swap_mb() -> float:
    """Read macOS swap usage in MB via sysctl."""
    try:
        out = subprocess.check_output(["sysctl", "-n", "vm.swapusage"], text=True).strip()
        # Format: total = 2048.00M  used = 1003.69M  free = 1044.31M  (encrypted)
        for part in out.split():
            if part.endswith("M") or part.endswith("G") or part.endswith("K"):
                pass
        import re
        m = re.search(r"used\s*=\s*([\d\.]+)([MGK])", out)
        if m:
            val, unit = float(m.group(1)), m.group(2)
            if unit == "G": return val * 1024.0
            if unit == "K": return val / 1024.0
            return val
    except Exception:
        pass
    return 0.0


def get_mac_memory_pressure_level() -> str:
    """Read macOS memory pressure state (Normal, Warning, Critical)."""
    try:
        out = subprocess.check_output(["memory_pressure"], text=True, stderr=subprocess.DEVNULL)
        if "Critical" in out:
            return "Critical (Red)"
        elif "Warning" in out:
            return "Warning (Yellow)"
        return "Normal (Green)"
    except Exception:
        # Fallback to vm_stat
        try:
            vm = subprocess.check_output(["vm_stat"], text=True)
            import re
            m_free = re.search(r"Pages free:\s+(\d+)", vm)
            if m_free and int(m_free.group(1)) < 2000:
                return "Warning (Low Pages Free)"
            return "Normal (Green)"
        except Exception:
            return "Unknown"


class SystemTelemetrySampler:
    """Samples CPU, RSS, Memory Pressure, and Swap at regular intervals."""
    def __init__(self, interval_sec: float = 0.5, target_pids: Optional[List[int]] = None):
        self.interval_sec = interval_sec
        self.target_pids = target_pids or []
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

        self.samples: List[Dict[str, Any]] = []
        self.peak_py_rss_mb = 0.0
        self.peak_tree_rss_mb = 0.0
        self.peak_py_cpu = 0.0
        self.peak_ffmpeg_cpu = 0.0
        self.pressure_states: set = set()

    def start(self, ffmpeg_proc: Optional[subprocess.Popen] = None):
        self.ffmpeg_proc = ffmpeg_proc
        self.py_proc = psutil.Process(os.getpid())
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                # 1. Python Process RSS
                py_rss = self.py_proc.memory_info().rss / (1024.0 * 1024.0)
                py_cpu = self.py_proc.cpu_percent(interval=None)

                # 2. Total Process Tree RSS (Python + FFmpeg subprocesses)
                tree_rss = py_rss
                ffmpeg_cpu = 0.0
                try:
                    for child in self.py_proc.children(recursive=True):
                        try:
                            tree_rss += child.memory_info().rss / (1024.0 * 1024.0)
                            if "ffmpeg" in child.name().lower():
                                ffmpeg_cpu += child.cpu_percent(interval=None)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except Exception:
                    pass

                if self.ffmpeg_proc and self.ffmpeg_proc.poll() is None:
                    try:
                        f_proc = psutil.Process(self.ffmpeg_proc.pid)
                        ffmpeg_cpu = max(ffmpeg_cpu, f_proc.cpu_percent(interval=None))
                    except Exception:
                        pass

                # 3. System Memory Pressure & Swap
                pressure = get_mac_memory_pressure_level()
                swap_mb = get_mac_swap_mb()

                self.peak_py_rss_mb = max(self.peak_py_rss_mb, py_rss)
                self.peak_tree_rss_mb = max(self.peak_tree_rss_mb, tree_rss)
                self.peak_py_cpu = max(self.peak_py_cpu, py_cpu)
                self.peak_ffmpeg_cpu = max(self.peak_ffmpeg_cpu, ffmpeg_cpu)
                self.pressure_states.add(pressure)

                self.samples.append({
                    "timestamp": time.perf_counter(),
                    "py_rss_mb": round(py_rss, 2),
                    "tree_rss_mb": round(tree_rss, 2),
                    "py_cpu": round(py_cpu, 1),
                    "ffmpeg_cpu": round(ffmpeg_cpu, 1),
                    "pressure": pressure,
                    "swap_mb": round(swap_mb, 2)
                })
            except Exception:
                pass
            time.sleep(self.interval_sec)

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)


@dataclass
class BenchmarkResult:
    test_name: str
    description: str
    wall_clock_sec: float
    input_duration_sec: float
    output_duration_sec: float
    output_frame_count: int
    average_fps: float
    realtime_multiplier: float
    reader_time_sec: float
    processor_time_sec: float
    writer_time_sec: float
    reader_pct: float
    processor_pct: float
    writer_pct: float
    peak_py_rss_mb: float
    peak_tree_rss_mb: float
    peak_py_cpu: float
    peak_ffmpeg_cpu: float
    swap_before_mb: float
    swap_after_mb: float
    swap_delta_mb: float
    memory_pressure: str
    output_size_bytes: int
    output_resolution: str
    output_codec: str
    ffmpeg_exit_code: int
    errors: str


def run_single_benchmark(
    test_name: str,
    description: str,
    video_path: str,
    output_path: str,
    effects_config: Optional[dict] = None,
    master_audio_path: Optional[str] = None,
    music_audio_path: Optional[str] = None,
    background_volume: float = 0.30,
    export_mode: str = "BALANCED",
    target_resolution: str = "Original",
    max_frames: Optional[int] = None
) -> BenchmarkResult:
    """
    Executes an export under instrumented conditions with precision wall-clock
    and stage latency profiling.
    """
    import queue
    import subprocess
    import shutil

    if os.path.exists(output_path):
        try: os.remove(output_path)
        except Exception: pass

    # 1. Probe input video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if max_frames and max_frames > 0:
        total_frames = min(total_frames, max_frames)
    input_dur = total_frames / fps if fps > 0 else 0.0

    target_w, target_h = compute_target_resolution(orig_w, orig_h, target_resolution)
    need_resize = (target_w != orig_w or target_h != orig_h)

    # Telemetry before run
    swap_before = get_mac_swap_mb()
    telemetry = SystemTelemetrySampler(interval_sec=0.25)

    # Encoder parameters
    enc_params = VideoExportPipeline.get_encoder_params(export_mode, target_w, target_h)
    safe_temp_output = get_temp_path(f"bench_{os.path.basename(output_path)}")
    if os.path.exists(safe_temp_output):
        try: os.remove(safe_temp_output)
        except Exception: pass

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-threads", "0",
        "-thread_queue_size", "128",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{target_w}x{target_h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "-"
    ]

    has_audio = bool(master_audio_path and os.path.exists(master_audio_path))
    if has_audio:
        ffmpeg_cmd.extend(["-i", master_audio_path])
        if music_audio_path and os.path.exists(music_audio_path) and background_volume > 0.0:
            ffmpeg_cmd.extend(["-i", music_audio_path])
            bg_vol_str = f"{max(0.05, min(1.0, background_volume)):.2f}"
            filter_str = (
                f"[2:a]volume={bg_vol_str}[bgm_scaled];"
                f"[bgm_scaled][1:a]sidechaincompress=threshold=0.035:ratio=3.5:attack=35:release=280[ducked_bgm];"
                f"[1:a]volume=2.2[v_boost];"
                f"[v_boost][ducked_bgm]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.99[aout]"
            )
            ffmpeg_cmd.extend(["-filter_complex", filter_str, "-map", "0:v:0", "-map", "[aout]"])
        else:
            ffmpeg_cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])
    else:
        ffmpeg_cmd.extend(["-map", "0:v:0"])

    ffmpeg_cmd.extend(enc_params)
    if has_audio:
        ffmpeg_cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-shortest"])
    ffmpeg_cmd.extend(["-movflags", "+faststart", safe_temp_output])

    stderr_log = get_temp_path("bench_ffmpeg_stderr.log")
    stderr_file = open(stderr_log, "wb")
    pipe_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file,
        bufsize=32 * 1024 * 1024
    )

    telemetry.start(ffmpeg_proc=pipe_proc)

    # 4-stage instrumented pipeline
    queue_size = 20
    frame_in_queue = queue.Queue(maxsize=queue_size)
    frame_out_queue = queue.Queue(maxsize=queue_size)
    stop_event = threading.Event()

    stage_timings = {
        "reader_total": 0.0,
        "processor_total": 0.0,
        "writer_total": 0.0
    }

    def reader_worker():
        fc = 0
        while not stop_event.is_set():
            if max_frames and fc >= max_frames:
                break
            t0 = time.perf_counter()
            ret, f = cap.read()
            if not ret or f is None:
                break
            if need_resize:
                interp = cv2.INTER_AREA if (target_w < orig_w and target_h < orig_h) else cv2.INTER_LINEAR
                f = cv2.resize(f, (target_w, target_h), interpolation=interp)
            t1 = time.perf_counter()
            stage_timings["reader_total"] += (t1 - t0)

            while not stop_event.is_set():
                try:
                    frame_in_queue.put((fc, f), timeout=0.005)
                    fc += 1
                    break
                except queue.Full:
                    continue

        while not stop_event.is_set():
            try:
                frame_in_queue.put((None, None), timeout=0.005)
                break
            except queue.Full:
                continue

    def writer_worker():
        while True:
            try:
                f = frame_out_queue.get(timeout=0.005)
            except queue.Empty:
                if stop_event.is_set(): break
                continue
            if f is None: break

            t0 = time.perf_counter()
            try:
                if pipe_proc and pipe_proc.stdin:
                    pipe_proc.stdin.write(memoryview(f))
            except Exception:
                break
            t1 = time.perf_counter()
            stage_timings["writer_total"] += (t1 - t0)

    reader_thread = threading.Thread(target=reader_worker, daemon=True)
    writer_thread = threading.Thread(target=writer_worker, daemon=True)

    effects_engine = EffectsProcessor(
        effects_config or {}, target_w, target_h, fps,
        orig_w=orig_w, orig_h=orig_h
    )

    t_wall_start = time.perf_counter()
    reader_thread.start()
    writer_thread.start()

    frame_count = 0
    try:
        while True:
            try:
                fc, frame = frame_in_queue.get(timeout=0.005)
            except queue.Empty:
                if not reader_thread.is_alive() and frame_in_queue.empty():
                    break
                continue

            if frame is None:
                break

            cur_sec = fc / fps
            t0 = time.perf_counter()
            processed_frame = effects_engine.process_frame(frame, cur_sec)
            t1 = time.perf_counter()
            stage_timings["processor_total"] += (t1 - t0)

            while not stop_event.is_set():
                try:
                    frame_out_queue.put(processed_frame, timeout=0.005)
                    break
                except queue.Full:
                    continue
            frame_count += 1
    finally:
        try: frame_out_queue.put(None, timeout=0.1)
        except Exception: pass
        stop_event.set()
        writer_thread.join(timeout=15.0)
        reader_thread.join(timeout=3.0)
        cap.release()

        if pipe_proc and pipe_proc.stdin:
            try: pipe_proc.stdin.flush()
            except Exception: pass
            try: pipe_proc.stdin.close()
            except Exception: pass

        exit_code = pipe_proc.wait(timeout=30.0) if pipe_proc else -1
        if stderr_file and not stderr_file.closed:
            stderr_file.close()

    t_wall_end = time.perf_counter()
    wall_clock_sec = max(0.001, t_wall_end - t_wall_start)

    telemetry.stop()
    swap_after = get_mac_swap_mb()

    # Move output if successful
    output_size = 0
    if os.path.exists(safe_temp_output) and os.path.getsize(safe_temp_output) > 1000:
        shutil.move(safe_temp_output, output_path)
        output_size = os.path.getsize(output_path)

    # Calculate metrics
    avg_fps = frame_count / wall_clock_sec
    realtime_mult = input_dur / wall_clock_sec if wall_clock_sec > 0 else 0.0

    sum_stage_times = max(0.001, stage_timings["reader_total"] + stage_timings["processor_total"] + stage_timings["writer_total"])
    r_pct = round((stage_timings["reader_total"] / sum_stage_times) * 100.0, 1)
    p_pct = round((stage_timings["processor_total"] / sum_stage_times) * 100.0, 1)
    w_pct = round((stage_timings["writer_total"] / sum_stage_times) * 100.0, 1)

    errors = ""
    if os.path.exists(stderr_log):
        with open(stderr_log, "r", errors="ignore") as f:
            err_content = f.read()
            if "Error" in err_content or "fail" in err_content.lower():
                errors = err_content[-500:]

    pressure_summary = ", ".join(sorted(telemetry.pressure_states)) if telemetry.pressure_states else "Normal (Green)"

    return BenchmarkResult(
        test_name=test_name,
        description=description,
        wall_clock_sec=round(wall_clock_sec, 3),
        input_duration_sec=round(input_dur, 2),
        output_duration_sec=round(frame_count / fps, 2),
        output_frame_count=frame_count,
        average_fps=round(avg_fps, 1),
        realtime_multiplier=round(realtime_mult, 2),
        reader_time_sec=round(stage_timings["reader_total"], 3),
        processor_time_sec=round(stage_timings["processor_total"], 3),
        writer_time_sec=round(stage_timings["writer_total"], 3),
        reader_pct=r_pct,
        processor_pct=p_pct,
        writer_pct=w_pct,
        peak_py_rss_mb=round(telemetry.peak_py_rss_mb, 1),
        peak_tree_rss_mb=round(telemetry.peak_tree_rss_mb, 1),
        peak_py_cpu=round(telemetry.peak_py_cpu, 1),
        peak_ffmpeg_cpu=round(telemetry.peak_ffmpeg_cpu, 1),
        swap_before_mb=round(swap_before, 1),
        swap_after_mb=round(swap_after, 1),
        swap_delta_mb=round(swap_after - swap_before, 1),
        memory_pressure=pressure_summary,
        output_size_bytes=output_size,
        output_resolution=f"{target_w}x{target_h}",
        output_codec="h264_videotoolbox",
        ffmpeg_exit_code=exit_code,
        errors=errors
    )


def run_benchmark_suite(
    video_path: str,
    srt_path: str,
    master_audio_path: Optional[str] = None,
    output_dir: str = "output/benchmark",
    max_frames: int = 1800  # 60s @ 30fps representative slice
):
    os.makedirs(output_dir, exist_ok=True)
    logger.info("=" * 70)
    logger.info("🚀 STARTING VIDE AI STUDIO EXPORT BENCHMARK SUITE (APPLE SILICON M2 8GB)")
    logger.info(f"📹 Input Video: {video_path}")
    logger.info(f"📝 Subtitles: {srt_path}")
    logger.info(f"🎞 Target Slice: {max_frames} frames (~{max_frames/30.0:.1f}s)")
    logger.info("=" * 70)

    # Parse SRT segments
    raw_segments = []
    if os.path.exists(srt_path):
        from core.srt_translator import SRTTranslator
        with open(srt_path, "r", encoding="utf-8") as f:
            sub_objs = SRTTranslator().parse_srt(f.read())
        for idx, s in enumerate(sub_objs):
            raw_segments.append({
                "id": idx + 1,
                "start": float(s.start_seconds),
                "end": float(s.end_seconds),
                "text": s.text,
                "khmer_text": s.text
            })
    logger.info(f"Loaded {len(raw_segments)} Khmer subtitle segments.")

    results: List[BenchmarkResult] = []

    # Test A: Video-only baseline (no subtitles or effects, full hardware re-encode)
    logger.info("\n▶ Running Test A: Video-Only Baseline Re-encode (No effects)...")
    res_a = run_single_benchmark(
        test_name="Test_A_Baseline_VideoOnly",
        description="Re-encode via VideoToolbox with no effects or subtitles",
        video_path=video_path,
        output_path=os.path.join(output_dir, "test_a_baseline.mp4"),
        effects_config={"burn_subtitle": {"enabled": False}},
        max_frames=max_frames
    )
    results.append(res_a)
    logger.info(f"✅ Test A Completed: {res_a.average_fps:.1f} FPS | {res_a.wall_clock_sec:.2f}s | Peak Tree RSS: {res_a.peak_tree_rss_mb:.1f} MB")

    # Test B: Static Khmer subtitles (animation disabled)
    logger.info("\n▶ Running Test B: Static Khmer Subtitles (HarfBuzz SIMD, Anim=None)...")
    res_b = run_single_benchmark(
        test_name="Test_B_Static_Khmer_Subtitles",
        description="Hardcode HarfBuzz Khmer Unicode subtitles with animation=none",
        video_path=video_path,
        output_path=os.path.join(output_dir, "test_b_static_sub.mp4"),
        effects_config={
            "burn_subtitle": {
                "enabled": True,
                "font_name": "Kantumruy Pro",
                "font_size": 22,
                "color_rgb": (255, 255, 255),
                "anim_type": "none"
            },
            "segments": raw_segments
        },
        max_frames=max_frames
    )
    results.append(res_b)
    logger.info(f"✅ Test B Completed: {res_b.average_fps:.1f} FPS | {res_b.wall_clock_sec:.2f}s | Peak Tree RSS: {res_b.peak_tree_rss_mb:.1f} MB")

    # Test C: Khmer subtitles with animation (Pop/Bounce)
    logger.info("\n▶ Running Test C: Animated Khmer Subtitles (Pop/Bounce enabled)...")
    res_c = run_single_benchmark(
        test_name="Test_C_Animated_Khmer_Subtitles",
        description="Hardcode HarfBuzz Khmer subtitles with pop_bounce animation",
        video_path=video_path,
        output_path=os.path.join(output_dir, "test_c_animated_sub.mp4"),
        effects_config={
            "burn_subtitle": {
                "enabled": True,
                "font_name": "Kantumruy Pro",
                "font_size": 22,
                "color_rgb": (255, 255, 255),
                "anim_type": "pop_bounce",
                "anim_dur": 0.35
            },
            "segments": raw_segments
        },
        max_frames=max_frames
    )
    results.append(res_c)
    logger.info(f"✅ Test C Completed: {res_c.average_fps:.1f} FPS | {res_c.wall_clock_sec:.2f}s | Peak Tree RSS: {res_c.peak_tree_rss_mb:.1f} MB")

    # Test D: Full export (Khmer subtitles + Master Audio + Audio ducking)
    logger.info("\n▶ Running Test D: Full Production Export (Subtitles + Audio Muxing)...")
    res_d = run_single_benchmark(
        test_name="Test_D_Full_Production_Export",
        description="Full pipeline with Khmer subtitles + master dubbed audio",
        video_path=video_path,
        output_path=os.path.join(output_dir, "test_d_full_production.mp4"),
        effects_config={
            "burn_subtitle": {
                "enabled": True,
                "font_name": "Kantumruy Pro",
                "font_size": 22,
                "color_rgb": (255, 255, 255),
                "anim_type": "pop_bounce",
                "anim_dur": 0.35
            },
            "segments": raw_segments
        },
        master_audio_path=master_audio_path,
        max_frames=max_frames
    )
    results.append(res_d)
    logger.info(f"✅ Test D Completed: {res_d.average_fps:.1f} FPS | {res_d.wall_clock_sec:.2f}s | Peak Tree RSS: {res_d.peak_tree_rss_mb:.1f} MB")

    # Test E: Repeat consistency test (Repeating Test B)
    logger.info("\n▶ Running Test E: Repeat Consistency Test (Repeating Test B)...")
    res_e = run_single_benchmark(
        test_name="Test_E_Repeat_Consistency",
        description="Repeat Test B to verify measurement variance & thermal stability",
        video_path=video_path,
        output_path=os.path.join(output_dir, "test_e_repeat.mp4"),
        effects_config={
            "burn_subtitle": {
                "enabled": True,
                "font_name": "Kantumruy Pro",
                "font_size": 22,
                "color_rgb": (255, 255, 255),
                "anim_type": "none"
            },
            "segments": raw_segments
        },
        max_frames=max_frames
    )
    results.append(res_e)
    logger.info(f"✅ Test E Completed: {res_e.average_fps:.1f} FPS | {res_e.wall_clock_sec:.2f}s | Peak Tree RSS: {res_e.peak_tree_rss_mb:.1f} MB")

    # 4. Save JSON and CSV reports
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(output_dir, f"benchmark_report_{timestamp_str}.json")
    csv_path = os.path.join(output_dir, f"benchmark_report_{timestamp_str}.csv")

    json_data = [asdict(r) for r in results]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    if results:
        fieldnames = list(asdict(results[0]).keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))

    logger.info("\n" + "=" * 70)
    logger.info(f"📊 BENCHMARK COMPLETE. Saved reports to:")
    logger.info(f"   JSON: {json_path}")
    logger.info(f"   CSV:  {csv_path}")
    logger.info("=" * 70)

    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Test Name':<30} | {'FPS':<7} | {'Wall (s)':<8} | {'Tree RSS':<10} | {'Reader%':<8} | {'Proc%':<8} | {'Write%':<8}")
    print("-" * 90)
    for r in results:
        print(f"{r.test_name:<30} | {r.average_fps:<7.1f} | {r.wall_clock_sec:<8.2f} | {r.peak_tree_rss_mb:<8.1f}MB | {r.reader_pct:<7.1f}% | {r.processor_pct:<7.1f}% | {r.writer_pct:<7.1f}%")
    print("=" * 90 + "\n")

    return results


if __name__ == "__main__":
    vid = "temp/merged_铁皮棚里的庄园_EP32_14clips.mp4"
    srt = "output/timeline_composite_0b70231e8c21114c_khmer.srt"
    audio = "temp/master_khmer_voice.wav"
    run_benchmark_suite(video_path=vid, srt_path=srt, master_audio_path=audio)
