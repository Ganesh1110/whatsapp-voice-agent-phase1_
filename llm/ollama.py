"""Ollama LLM client.

Talks to a local Ollama instance (default http://localhost:11434) using its
HTTP API, so no extra Python package is required beyond `httpx` (already a
project dependency).

Set these in `.env`:
  OLLAMA_HOST=http://localhost:11434
  OLLAMA_MODEL=llama3.1:8b
"""
import logging
import os

from .base_llm import BaseLLM, CompletionError, LLMModelLoadError

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    name = "ollama"

    def __init__(self, model_id: str | None = None, host: str | None = None) -> None:
        super().__init__()
        self.model_id = model_id or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self._client = None

    def _load(self) -> None:
        import httpx

        self._client = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
        try:
            resp = self._client.get(f"{self.host}/api/tags")
            resp.raise_for_status()
        except Exception as exc:
            self._client = None
            raise LLMModelLoadError(
                f"Ollama not reachable at {self.host}. Is `ollama serve` running and model '{self.model_id}' pulled? ({exc})"
            ) from exc
        logger.info("Ollama '%s' reachable at %s", self.model_id, self.host)

    def _complete(self, prompt: str, system: str | None = None) -> str:
        import httpx

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self._client.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model_id,
                    "messages": messages,
                    "stream": False,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CompletionError(f"Ollama returned {exc.response.status_code}: {exc.response.text.strip()}") from exc
        except httpx.RequestError as exc:
            raise CompletionError(f"Ollama request failed: {exc}") from exc

        data = resp.json()
        message = data.get("message", {})
        reply = message.get("content", "")
        if not reply:
            raise CompletionError("Ollama returned an empty reply.")
        return reply
