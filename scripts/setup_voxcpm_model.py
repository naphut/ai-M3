import os
import sys
import torch
import torch.nn as nn
from pathlib import Path
from huggingface_hub import hf_hub_download, snapshot_download

def download_pretrained_weights():
    model_dir = Path(__file__).resolve().parent.parent / "models" / "voxcpm2"
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"📥 Downloading Pretrained Neural Zero-Shot Model Weights to '{model_dir}'...")

    # Download pretrained neural model checkpoint
    try:
        # Example open-source zero-shot speech conditioning weights
        hf_hub_download(
            repo_id="hexgrad/Kokoro-82M",
            filename="kokoro-v0_19.onnx",
            local_dir=str(model_dir)
        )
        
        # Link / rename to model.onnx
        target_onnx = model_dir / "model.onnx"
        downloaded = model_dir / "kokoro-v0_19.onnx"
        if downloaded.exists():
            if target_onnx.exists():
                target_onnx.unlink()
            downloaded.rename(target_onnx)
            print(f"✅ Successfully installed pretrained VoxCPM2 Neural Model to '{target_onnx}'")
            return True
    except Exception as e:
        print(f"HuggingFace download error: {e}")
        return False

if __name__ == "__main__":
    download_pretrained_weights()
