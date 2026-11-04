"""LLM configuration tests. No network or model weights are used."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.remote import RemoteLLM, _normalize_host, _normalize_model  # noqa: E402


def test_host_with_v1_is_normalized():
    llm = RemoteLLM(model_id="m", host="https://example.com/v1/", api_style="openai")
    assert llm.host == "https://example.com"
    assert llm._chat_url == "https://example.com/v1/chat/completions"
    assert llm._models_url == "https://example.com/v1/models"


def test_host_with_base_path_preserved():
    llm = RemoteLLM(model_id="m", host="https://example.com/api-llm", api_style="openai")
    assert llm._chat_url == "https://example.com/api-llm/v1/chat/completions"


def test_ollama_api_suffix_is_normalized():
    llm = RemoteLLM(model_id="m", host="http://localhost:11434/api", api_style="ollama")
    assert llm.host == "http://localhost:11434"
    assert llm._chat_url == "http://localhost:11434/api/chat"


def test_model_extracted_from_models_url():
    assert (
        _normalize_model("https://example.com/v1/models/google/gemma-4-E4B-it")
        == "google/gemma-4-E4B-it"
    )


def test_bare_model_name_unchanged():
    assert _normalize_model("google/gemma-4-E4B-it") == "google/gemma-4-E4B-it"


def test_host_normalization_helper_plain_host():
    assert _normalize_host("https://example.com/", "openai") == "https://example.com"


def test_full_chat_endpoint_is_normalized():
    llm = RemoteLLM(
        model_id="m",
        host="https://example.com/v1/chat/completions",
        api_style="openai",
    )
    assert llm.host == "https://example.com"
    assert llm._chat_url == "https://example.com/v1/chat/completions"


def test_max_tokens_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "123")
    llm = RemoteLLM(model_id="m", host="https://example.com", api_style="openai")
    assert llm.max_tokens == 123
