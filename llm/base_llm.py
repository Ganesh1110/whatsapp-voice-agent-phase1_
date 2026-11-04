"""Base class and shared helpers for Large Language Models.

Every LLM model implements `BaseLLM`. Models are contacted lazily (on first
use) so the API starts fast and never blocks on a remote model being down.
"""
import logging
import threading
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base error for all LLM problems."""


class LLMModelLoadError(LLMError):
    """The model could not be reached / loaded."""


class CompletionError(LLMError):
    """The model failed to produce a reply."""


class BaseLLM(ABC):
    """Interface every LLM model must follow."""

    name: str = "base"

    def __init__(self) -> None:
        self._ready = False
        self._lock = threading.Lock()

    @property
    def is_ready(self) -> bool:
        return self._ready

    @abstractmethod
    def _load(self) -> None:
        """Verify the model is reachable. Heavy imports go here."""

    @abstractmethod
    def _complete(self, prompt: str, system: str | None) -> str:
        """Run inference and return the reply text."""

    def load(self) -> None:
        """Check the model once; safe to call from multiple threads."""
        with self._lock:
            if self._ready:
                return
            logger.info("Checking LLM model '%s'...", self.name)
            try:
                self._load()
            except Exception as exc:
                logger.exception("Failed to reach LLM model '%s'", self.name)
                raise LLMModelLoadError(f"Could not reach LLM model '{self.name}': {exc}") from exc
            self._ready = True
            logger.info("LLM model '%s' ready.", self.name)

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Get a reply for the given prompt."""
        if not prompt or not prompt.strip():
            raise CompletionError("Prompt is empty.")
        self.load()
        try:
            return self._complete(prompt.strip(), system).strip()
        except LLMError:
            raise
        except Exception as exc:
            logger.exception("Completion failed in '%s'", self.name)
            raise CompletionError(f"Completion failed: {exc}") from exc
