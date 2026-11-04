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


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _resolve_device(torch) -> str:
    """Pick ``cuda:0`` only when enough GPU memory is actually free."""
    requested = os.getenv("WHISPER_DEVICE", "auto").strip().lower()
    if requested == "cpu":
        return "cpu"

    if not torch.cuda.is_available():
        if requested.startswith("cuda"):
            logger.warning("WHISPER_DEVICE=%s but CUDA is unavailable; using CPU", requested)
        return "cpu"

    if requested in ("cuda", "cuda:0"):
        return "cuda:0"

    min_free_gb = _env_float("WHISPER_MIN_GPU_FREE_GB", 4.0)
    try:
        free, _ = torch.cuda.mem_get_info()
        free_gb = free / (1024**3)
    except Exception as exc:
        logger.warning("Could not query GPU memory (%s); using CPU for Whisper", exc)
        return "cpu"

    if free_gb < min_free_gb:
        logger.warning(
            "GPU has only %.2f GiB free (Whisper needs >= %.2f GiB); using CPU. "
            "Free GPU memory or set WHISPER_DEVICE=cuda to force GPU.",
            free_gb,
            min_free_gb,
        )
        return "cpu"
    return "cuda:0"


def _resolve_dtype(torch, device: str):
    if device == "cpu":
        return torch.float32
    requested = os.getenv("WHISPER_DTYPE", "auto").strip().lower()
    if requested in ("float32", "fp32"):
        return torch.float32
    if requested in ("bfloat16", "bf16"):
        return torch.bfloat16
    return torch.float16


def _is_oom(exc: Exception, torch) -> bool:
    oom_class = getattr(torch.cuda, "OutOfMemoryError", ())
    return isinstance(exc, oom_class) or "out of memory" in str(exc).lower()


class WhisperSTT(BaseSTT):
    name = "whisper"

    def __init__(self, model_id: str | None = None) -> None:
        super().__init__()
        # whisper-small is a reasonable CPU default; use whisper-large-v3 on a GPU for better Malayalam.
        self.model_id = os.path.expanduser(
            model_id or os.getenv("WHISPER_MODEL_ID", "openai/whisper-small")
        )
        self._pipe = None

    def _build_pipeline(self, pipeline, torch, device: str, dtype):
        return pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            device=device,
            torch_dtype=dtype,
            model_kwargs={"low_cpu_mem_usage": True},
            chunk_length_s=30,  # allows audio longer than 30 seconds
        )

    def _load(self) -> None:
        import torch
        from transformers import pipeline

        device = _resolve_device(torch)
        dtype = _resolve_dtype(torch, device)
        logger.info("Loading Whisper '%s' on %s (%s)", self.model_id, device, dtype)

        try:
            self._pipe = self._build_pipeline(pipeline, torch, device, dtype)
        except RuntimeError as exc:
            if device == "cpu" or not _is_oom(exc, torch):
                raise
            logger.warning(
                "CUDA out of memory loading Whisper '%s'; falling back to CPU. "
                "Free GPU memory to use the GPU again.",
                self.model_id,
            )
            torch.cuda.empty_cache()
            self._pipe = self._build_pipeline(pipeline, torch, "cpu", torch.float32)
            device, dtype = "cpu", torch.float32

        logger.info("Whisper '%s' ready on %s (%s)", self.model_id, device, dtype)

    def _transcribe(self, audio_path: str, language: str) -> str:
        audio = load_audio(audio_path)
        lang = LANGUAGE_NAMES.get(language.lower(), language.lower())
        result = self._pipe(
            {"raw": audio, "sampling_rate": TARGET_SAMPLE_RATE},
            generate_kwargs={"language": lang, "task": "transcribe"},
        )
        return result["text"]
