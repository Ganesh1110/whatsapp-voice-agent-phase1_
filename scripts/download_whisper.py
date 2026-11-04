"""Download the configured Whisper model into a local directory for offline use."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import snapshot_download


def main() -> None:
    load_dotenv()
    model_id = os.getenv("WHISPER_MODEL_ID", "openai/whisper-small")
    target = Path(os.getenv("WHISPER_MODEL_PATH", "models/whisper-small")).expanduser()
    token = os.getenv("HF_TOKEN") or None

    print(f"Downloading {model_id} to {target.resolve()} ...")
    snapshot_download(repo_id=model_id, local_dir=str(target), token=token)
    print("Download complete. Set WHISPER_MODEL_PATH to this directory and restart the API.")


if __name__ == "__main__":
    main()
