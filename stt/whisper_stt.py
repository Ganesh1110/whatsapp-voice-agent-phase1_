"""OpenAI Whisper STT (via Hugging Face transformers)."""
import logging
import os

from .base_stt import TARGET_SAMPLE_RATE, BaseSTT, load_audio

logger = logging.getLogger(__name__)

# Whisper expects full language names rather than ISO codes.
LANGUAGE_NAMES = {
    "ml": "malayalam",
    "en": "english",
    "hi": "hindi",
    "ta": "tamil",
    "te": "telugu",
    "kn": "kannada",
}


class WhisperSTT(BaseSTT):
    name = "whisper"

    def __init__(self, model_id: str | None = None) -> None:
        super().__init__()
        # whisper-small is a reasonable CPU default; use whisper-large-v3 on a GPU for better Malayalam.
        self.model_id = model_id or os.getenv("WHISPER_MODEL_ID", "openai/whisper-small")
        self._pipe = None

    def _load(self) -> None:
        import torch
        from transformers import pipeline

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info("Whisper '%s' on %s", self.model_id, device)
        self._pipe = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=device,
            chunk_length_s=30,  # allows audio longer than 30 seconds
        )

    def _transcribe(self, audio_path: str, language: str) -> str:
        audio = load_audio(audio_path)
        lang = LANGUAGE_NAMES.get(language.lower(), language.lower())
        result = self._pipe(
            {"raw": audio, "sampling_rate": TARGET_SAMPLE_RATE},
            generate_kwargs={"language": lang, "task": "transcribe"},
        )
        return result["text"]
