"""LLM package: registry so new models can be plugged in later."""
import importlib
import threading

from .base_llm import (
    BaseLLM,
    CompletionError,
    LLMError,
    LLMModelLoadError,
)

__all__ = [
    "BaseLLM",
    "CompletionError",
    "LLMError",
    "LLMModelLoadError",
    "UnknownLLMModelError",
    "available_llm_models",
    "get_llm_model",
    "register_llm_model",
]


class UnknownLLMModelError(LLMError):
    """Requested model name is not registered."""


# name -> "module:Class" (imported lazily) or a class registered at runtime.
_BUILTIN: dict[str, object] = {
    "ollama": "llm.ollama:OllamaLLM",
}
_instances: dict[str, BaseLLM] = {}
_lock = threading.Lock()


def register_llm_model(name: str, model_cls: type[BaseLLM]) -> None:
    """Register (or replace) an LLM model class under `name`."""
    with _lock:
        _BUILTIN[name] = model_cls
        _instances.pop(name, None)


def available_llm_models() -> list[str]:
    return sorted(_BUILTIN)


def get_llm_model(name: str) -> BaseLLM:
    """Return a cached model instance (connection checked on first use)."""
    with _lock:
        if name not in _BUILTIN:
            raise UnknownLLMModelError(
                f"Unknown LLM model '{name}'. Available: {', '.join(available_llm_models())}"
            )
        if name not in _instances:
            target = _BUILTIN[name]
            if isinstance(target, str):
                module_name, class_name = target.split(":")
                target = getattr(importlib.import_module(module_name), class_name)
            _instances[name] = target()
        return _instances[name]
