"""Remote LLM client for models served on a GPU server (e.g. AWS gemma-4-E4B-it).

Talks to a remote inference endpoint over HTTP. Two API styles are supported:

* ``ollama`` (default) — POST ``{host}/api/chat``  (works with Ollama running on AWS)
* ``openai``           — POST ``{host}/v1/chat/completions`` (works with vLLM / TGI / any
  OpenAI-compatible server)

Set these in ``.env``::

    LLM_HOST=https://YOUR_AWS_GPU_SERVER
    LLM_MODEL=google/gemma-4-E4B-it
    LLM_API_STYLE=ollama          # or openai
    LLM_REQUEST_TIMEOUT=300

No extra Python package is needed beyond ``httpx`` (already a project dependency).
"""
import logging
import os

import httpx

from .base_llm import BaseLLM, CompletionError, LLMModelLoadError

logger = logging.getLogger(__name__)


class RemoteLLM(BaseLLM):
    name = "remote"

    def __init__(
        self,
        model_id: str | None = None,
        host: str | None = None,
        api_style: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__()
        self.model_id = model_id or os.getenv("LLM_MODEL", "google/gemma-4-E4B-it")
        self.host = (host or os.getenv("LLM_HOST", "")).rstrip("/")
        self.api_style = (api_style or os.getenv("LLM_API_STYLE", "ollama")).lower()
        self.timeout = timeout or float(os.getenv("LLM_REQUEST_TIMEOUT", "300"))
        self._client = None

    @property
    def _chat_url(self) -> str:
        if self.api_style == "openai":
            return f"{self.host}/v1/chat/completions"
        return f"{self.host}/api/chat"

    def _load(self) -> None:
        if not self.host:
            raise LLMModelLoadError("LLM_HOST is not set. Point it at your AWS GPU server.")
        self._client = httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0))
        try:
            # Lightweight reachability check (best-effort; some servers lack /api/tags).
            if self.api_style == "ollama":
                resp = self._client.get(f"{self.host}/api/tags")
                resp.raise_for_status()
        except httpx.RequestError as exc:
            self._client = None
            raise LLMModelLoadError(
                f"Remote LLM not reachable at {self.host}. Is the GPU server up and model "
                f"'{self.model_id}' loaded? ({exc})"
            ) from exc
        except httpx.HTTPStatusError:
            # /api/tags may not exist on non-Ollama servers; that's fine.
            pass
        logger.info("Remote LLM '%s' targeting %s (style=%s)", self.model_id, self.host, self.api_style)

    def _complete(self, prompt: str, system: str | None = None) -> str:
        if self.api_style == "openai":
            return self._complete_openai(prompt, system)
        return self._complete_ollama(prompt, system)

    def _complete_ollama(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self._client.post(
                self._chat_url,
                json={"model": self.model_id, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CompletionError(f"Remote LLM returned {exc.response.status_code}: {exc.response.text.strip()}") from exc
        except httpx.RequestError as exc:
            raise CompletionError(f"Remote LLM request failed: {exc}") from exc

        data = resp.json()
        if self.api_style == "ollama":
            reply = (data.get("message") or {}).get("content", "")
        else:
            reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not reply:
            raise CompletionError("Remote LLM returned an empty reply.")
        return reply

    def _complete_openai(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            resp = self._client.post(
                self._chat_url,
                json={
                    "model": self.model_id,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CompletionError(f"Remote LLM returned {exc.response.status_code}: {exc.response.text.strip()}") from exc
        except httpx.RequestError as exc:
            raise CompletionError(f"Remote LLM request failed: {exc}") from exc

        data = resp.json()
        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not reply:
            raise CompletionError("Remote LLM returned an empty reply.")
        return reply
