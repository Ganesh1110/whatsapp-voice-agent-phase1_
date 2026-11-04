"""POST /llm - chat with the LLM (Ollama)."""
import logging
import time

from fastapi import APIRouter

from llm import (
    CompletionError,
    LLMModelLoadError,
    UnknownLLMModelError,
    available_llm_models,
    get_llm_model,
)

from .schemas import APIError, ErrorResponse, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Large Language Model"])


def _default_model() -> str:
    import os

    return os.getenv("DEFAULT_LLM_MODEL", "ollama")


@router.get("/llm/models", response_model=dict, summary="List LLM models")
def list_llm_models() -> dict:
    return {"models": available_llm_models(), "default": _default_model()}


@router.post(
    "/llm",
    response_model=LLMResponse,
    summary="Get a reply from the LLM",
    responses={
        400: {"model": ErrorResponse, "description": "Empty prompt or unknown model"},
        500: {"model": ErrorResponse, "description": "Completion failed"},
        503: {"model": ErrorResponse, "description": "Model could not be reached"},
    },
)
def complete(request: LLMRequest) -> LLMResponse:
    model_name = (request.model or _default_model()).strip().lower()
    try:
        llm = get_llm_model(model_name)
    except UnknownLLMModelError as exc:
        raise APIError(400, "Unknown LLM model", str(exc)) from exc

    start = time.perf_counter()
    try:
        reply = llm.complete(request.text, request.system)
    except LLMModelLoadError as exc:
        raise APIError(503, "LLM unavailable", str(exc)) from exc
    except CompletionError as exc:
        raise APIError(500, "Completion failed", str(exc)) from exc
    elapsed = round(time.perf_counter() - start, 2)
    logger.info("LLM '%s' finished in %.2fs (%d chars)", model_name, elapsed, len(reply))
    return LLMResponse(reply=reply, model=model_name, processing_seconds=elapsed)
