"""
Audio Synchronization Engine (Compatibility Bridge to DialogueSyncEngine)
"""
from core.dialogue_sync import DialogueSyncEngine

class AudioSyncEngine(DialogueSyncEngine):
    """
    Backward-compatible wrapper for DialogueSyncEngine.
    """
    def sync_audio_to_video(
        self,
        audio_segments,
        seg_audio_paths,
        video_duration,
        output_path
    ) -> str:
        return self.sync_dialogue_timeline(
            segments=audio_segments,
            seg_audio_paths=seg_audio_paths,
            total_duration_sec=video_duration,
            output_master_path=output_path
        )

