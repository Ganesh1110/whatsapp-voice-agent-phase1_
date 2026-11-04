"""Remote LLM client for models served on a GPU server (e.g. AWS gemma-4-E4B-it).

Talks to a remote inference endpoint over HTTP. Two API styles are supported:

* ``ollama`` (default) — POST ``{host}/api/chat``  (works with Ollama running on AWS)
* ``openai``           — POST ``{host}/v1/chat/completions`` (works with vLLM / TGI / any
  OpenAI-compatible server)

Set these in ``.env``::

    LLM_HOST=https://YOUR_AWS_GPU_SERVER
    LLM_MODEL=google/gemma-4-E4B-it
    LLM_API_STYLE=openai          # or ollama
    LLM_API_KEY=                  # optional bearer token for OpenAI-compatible servers
    LLM_REQUEST_TIMEOUT=300

No extra Python package is needed beyond ``httpx`` (already a project dependency).
"""
import logging
import os
import urllib.parse

import httpx

from .base_llm import BaseLLM, CompletionError, LLMModelLoadError

logger = logging.getLogger(__name__)

_ENDPOINT_SUFFIXES = ("/v1/chat/completions", "/api/chat", "/v1/models", "/api/tags")
_OPENAI_SUFFIXES = ("/v1",)
_OLLAMA_SUFFIXES = ("/api",)


def _normalize_host(raw: str, api_style: str) -> str:
    """Return a base URL from any of the URLs users commonly paste.

    Accepts a bare host, a host with ``/v1`` (or ``/api``), or a full endpoint
    such as ``https://server/v1/chat/completions`` without producing duplicated
    path segments like ``/v1/v1/chat/completions``.
    """
    host = raw.strip().rstrip("/")
    if not host:
        return ""
    parsed = urllib.parse.urlparse(host)
    if not parsed.scheme or not parsed.netloc:
        return host
    path = parsed.path.rstrip("/")
    for suffix in _ENDPOINT_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    suffixes = _OPENAI_SUFFIXES if api_style == "openai" else _OLLAMA_SUFFIXES
    if path.endswith(suffixes):
        path = path[: path.rfind("/")]
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _normalize_model(raw: str) -> str:
    """Accept a bare model id, or extract it from a ``.../models/<id>`` URL."""
    model = raw.strip()
    if not model.startswith(("http://", "https://")):
        return model
    parts = [p for p in urllib.parse.urlparse(model).path.split("/") if p]
    if "models" in parts:
        model_id = "/".join(parts[parts.index("models") + 1 :])
        if model_id:
            return model_id
    logger.warning(
        "LLM_MODEL '%s' looks like a URL, but no model id could be extracted. "
        "Expected a model name such as 'google/gemma-4-E4B-it'.",
        model,
    )
    return model


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
        self.api_style = (api_style or os.getenv("LLM_API_STYLE", "openai")).strip().lower()
        self.model_id = _normalize_model(model_id or os.getenv("LLM_MODEL", "google/gemma-4-E4B-it"))
        self.host = _normalize_host(host or os.getenv("LLM_HOST", ""), self.api_style)
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.timeout = timeout or float(os.getenv("LLM_REQUEST_TIMEOUT", "300"))
        try:
            self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "200"))
        except ValueError:
            self.max_tokens = 200
        self._client = None

    @property
    def _chat_url(self) -> str:
        if self.api_style == "openai":
            return f"{self.host}/v1/chat/completions"
        return f"{self.host}/api/chat"

    @property
    def _models_url(self) -> str:
        if self.api_style == "openai":
            return f"{self.host}/v1/models"
        return f"{self.host}/api/tags"

    def _load(self) -> None:
        if not self.host:
            raise LLMModelLoadError("LLM_HOST is not set. Point it at your AWS GPU server.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=10.0), headers=headers
        )
        try:
            # Best-effort reachability check. Some servers do not expose a
            # listing endpoint, but connection errors still surface here.
            resp = self._client.get(self._models_url)
            resp.raise_for_status()
        except httpx.RequestError as exc:
            self._client = None
            raise LLMModelLoadError(
                f"Remote LLM not reachable at {self.host}. Is the GPU server up and model "
                f"'{self.model_id}' loaded? ({exc})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            if self.api_style == "openai" and exc.response.status_code in (401, 403):
                self._client = None
                raise LLMModelLoadError(
                    f"Remote LLM rejected the request ({exc.response.status_code}). "
                    "Check LLM_API_KEY."
                ) from exc
            # Other errors (e.g. missing /api/tags) are fine; completion will
            # report a real failure if the chat endpoint is unavailable.
        logger.info(
            "Remote LLM '%s' targeting %s (style=%s)", self.model_id, self.host, self.api_style
        )

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
                json={
                    "model": self.model_id,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_predict": self.max_tokens},
                },
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CompletionError(f"Remote LLM returned {exc.response.status_code}: {exc.response.text.strip()}") from exc
        except httpx.RequestError as exc:
            raise CompletionError(f"Remote LLM request failed: {exc}") from exc

        data = resp.json()
        reply = (data.get("message") or {}).get("content", "")
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
                    "max_tokens": self.max_tokens,
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
