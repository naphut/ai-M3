#!/usr/bin/env python3
"""
Khmer Video Dubbing & Pure OpenBMB VoxCPM2 Multi-Speaker Voice Cloning Pipeline.
Executes Step 1 through Step 9 end-to-end.
"""

import os
import sys
import json
from pathlib import Path
from utils.logger import logger

from services.audio_extractor import AudioExtractor
from services.whisper_service import WhisperService
from services.vad_service import VADService
from services.speaker_service import SpeakerService
from services.translation_service import Translator
from services.voice_cleaner import VoiceCleaner
from services.voice_profile_service import VoiceProfileService
from services.voxcpm_service import VoxCPM2Runner
from services.video_service import VideoService
from core.audio_processor import AudioProcessor


def run_pure_voxcpm2_dubbing_pipeline(
    video_path: str,
    source_lang: str = "en",
    target_lang: str = "km",
    output_dir: str = "output"
) -> str:
    """
    Execute 9-Step Clean Dubbing Pipeline with Strict OpenBMB VoxCPM2 Voice Cloning.
    """
    logger.info("=" * 65)
    logger.info("🎬 STARTING PURE VOXCPM2 KHMER VIDEO DUBBING PIPELINE")
    logger.info("=" * 65)
    logger.info(f"Input Video : {video_path}")
    logger.info(f"Languages   : {source_lang} -> {target_lang}")

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video not found: {video_path}")

    os.makedirs(output_dir, exist_ok=True)
    temp_dir = Path("temp")
    temp_dir.mkdir(exist_ok=True)

    # ----------------------------------------------------
    # STEP 1: AUDIO EXTRACTION (FFmpeg)
    # ----------------------------------------------------
    logger.info("\n--- [STEP 1/9] Audio Extraction (16kHz PCM WAV) ---")
    extractor = AudioExtractor()
    extracted_audio = str(temp_dir / "extracted_original_audio.wav")
    audio_path = extractor.extract_audio(video_path, extracted_audio)
    if not audio_path or not os.path.exists(audio_path):
        raise RuntimeError("Audio extraction failed.")

    # ----------------------------------------------------
    # STEP 2: WHISPER STT (Transcribe & Timestamps)
    # ----------------------------------------------------
    logger.info("\n--- [STEP 2/9] Whisper Speech-to-Text Transcription ---")
    whisper_svc = WhisperService(model_size="base")
    segments = whisper_svc.transcribe(audio_path, language=source_lang)
    if not segments:
        raise RuntimeError("Whisper STT returned no subtitle segments.")
    logger.info(f"✅ Whisper transcribed {len(segments)} segments.")

    # ----------------------------------------------------
    # STEP 3: VAD & SPEAKER DIARIZATION
    # ----------------------------------------------------
    logger.info("\n--- [STEP 3/9] VAD & Speaker Diarization ---")
    speaker_svc = SpeakerService()
    labeled_segments = speaker_svc.identify_speaker_clusters(audio_path, segments)
    
    unique_speakers = list(set([seg.get("speaker", "SPEAKER_00") for seg in labeled_segments]))
    logger.info(f"✅ Identified {len(unique_speakers)} unique speaker(s): {unique_speakers}")

    # ----------------------------------------------------
    # STEP 4: KHMER TRANSLATION
    # ----------------------------------------------------
    logger.info("\n--- [STEP 4/9] Khmer Translation ---")
    translator = Translator()
    translated_segments = translator.process(labeled_segments, source_lang=source_lang, target_lang=target_lang)
    logger.info("✅ Translation to Khmer completed.")

    # ----------------------------------------------------
    # STEP 5 & 6: PER-SPEAKER VOICE CLEANING & VOICE PROFILES
    # ----------------------------------------------------
    logger.info("\n--- [STEP 5 & 6/9] Per-Speaker Voice Cleaning & Profiles ---")
    voice_profile_svc = VoiceProfileService()
    voice_cleaner = VoiceCleaner()
    vad_svc = VADService()

    speaker_profiles = {}
    for spk_id in unique_speakers:
        spk_segs = [s for s in labeled_segments if s.get("speaker") == spk_id]
        if not spk_segs:
            continue
        
        # Best speech reference for this speaker
        best_seg = max(spk_segs, key=lambda s: s["end"] - s["start"])
        ref_start, ref_end = best_seg["start"], best_seg["end"]
        ref_text = best_seg.get("text", "")

        # Extract raw segment audio
        raw_spk_wav = str(temp_dir / f"raw_{spk_id}.wav")
        from services.audio_extractor import extract_segment_audio
        extract_segment_audio(audio_path, ref_start, ref_end, raw_spk_wav)

        # Create persistent profile
        profile = voice_profile_svc.create_voice_profile(
            name=spk_id,
            reference_audio_path=raw_spk_wav,
            prompt_text=ref_text
        )
        speaker_profiles[spk_id] = {
            "reference_audio": str(Path("storage/voices") / profile["voice_id"] / "reference.wav"),
            "prompt_text": ref_text
        }
        logger.info(f"✅ Voice Profile Ready for {spk_id}: {speaker_profiles[spk_id]['reference_audio']}")

    # ----------------------------------------------------
    # STEP 7: PURE OPENBMB VOXCPM2 KHMER NEURAL TTS
    # ----------------------------------------------------
    logger.info("\n--- [STEP 7/9] Pure OpenBMB VoxCPM2 Zero-Shot Synthesis ---")
    voxcpm_runner = VoxCPM2Runner()
    voxcpm_runner.load_model()

    synth_audio_segments = []
    for idx, seg in enumerate(translated_segments):
        spk_id = seg.get("speaker", "SPEAKER_00")
        spk_info = speaker_profiles.get(spk_id, list(speaker_profiles.values())[0])
        
        khmer_text = seg.get("khmer_text") or seg.get("translated_text", "")
        out_wav = str(temp_dir / f"voxcpm_seg_{idx:03d}.wav")

        logger.info(f"🎙️ Synthesizing Segment {idx+1}/{len(translated_segments)} for {spk_id}: '{khmer_text[:30]}...'")
        voxcpm_runner.generate(
            text=khmer_text,
            prompt_audio=spk_info["reference_audio"],
            prompt_text=spk_info["prompt_text"],
            output_path=out_wav
        )

        synth_audio_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "audio_path": out_wav,
            "speaker": spk_id
        })

    # ----------------------------------------------------
    # STEP 8: AUDIO SYNC & TIMELINE STITCHING
    # ----------------------------------------------------
    logger.info("\n--- [STEP 8/9] Audio Timeline Stitching & Sync ---")
    audio_proc = AudioProcessor()
    master_audio_path = str(temp_dir / "master_khmer_audio.wav")
    audio_proc.sync_and_stitch_segments(synth_audio_segments, master_audio_path)
    logger.info(f"✅ Master Khmer Audio Assembled: {master_audio_path}")

    # ----------------------------------------------------
    # STEP 9: FFmpeg VIDEO-AUDIO MULTIPLEXING
    # ----------------------------------------------------
    logger.info("\n--- [STEP 9/9] Final Video-Audio Multiplexing ---")
    video_svc = VideoService()
    final_video_path = os.path.join(output_dir, f"dubbed_khmer_{Path(video_path).stem}.mp4")
    success = video_svc.merge_dubbed_audio(video_path, master_audio_path, final_video_path)
    
    if not success:
        raise RuntimeError("Final video multiplexing failed.")

    logger.info("=" * 65)
    logger.info(f"🎉 FINAL DUBBED KHMER VIDEO CREATED: {final_video_path}")
    logger.info("=" * 65)
    return final_video_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 pipeline.py <video_path>")
        sys.exit(1)

    video_input = sys.argv[1]
    run_pure_voxcpm2_dubbing_pipeline(video_input)
