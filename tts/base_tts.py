"""Base class and helpers for Text-to-Speech models."""
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """Base error for all TTS problems."""


class TTSModelLoadError(TTSError):
    """The model could not be loaded."""


class SynthesisError(TTSError):
    """Speech could not be generated from the given text."""


@dataclass
class SynthesisResult:
    """Raw audio produced by a TTS model."""

    waveform: "numpy.ndarray"  # noqa: F821 - mono float32 in [-1, 1]
    sampling_rate: int


def save_wav(result: SynthesisResult, path: str) -> None:
    """Write a SynthesisResult to a 16-bit PCM WAV file."""
    import numpy as np
    from scipy.io import wavfile

    samples = np.clip(result.waveform, -1.0, 1.0)
    wavfile.write(path, result.sampling_rate, (samples * 32767).astype(np.int16))


class BaseTTS(ABC):
    """Interface every TTS model must follow."""

    name: str = "base"

    def __init__(self) -> None:
        self._loaded = False
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @abstractmethod
    def _load(self) -> None:
        """Load weights into memory."""

    @abstractmethod
    def _synthesize(self, text: str) -> SynthesisResult:
        """Run inference."""

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            logger.info("Loading TTS model '%s'...", self.name)
            try:
                self._load()
            except Exception as exc:
                logger.exception("Failed to load TTS model '%s'", self.name)
                raise TTSModelLoadError(f"Could not load TTS model '{self.name}': {exc}") from exc
            self._loaded = True
            logger.info("TTS model '%s' ready.", self.name)

    def synthesize(self, text: str) -> SynthesisResult:
        """Convert text to speech."""
        if not text or not text.strip():
            raise SynthesisError("Text is empty.")
        self.load()
        try:
            return self._synthesize(text.strip())
        except TTSError:
            raise
        except Exception as exc:
            logger.exception("Synthesis failed in '%s'", self.name)
            raise SynthesisError(f"Speech generation failed: {exc}") from exc
