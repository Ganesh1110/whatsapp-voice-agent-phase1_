"""Request/response models and the shared API error type."""
import os

from pydantic import BaseModel, Field, field_validator


class APIError(Exception):
    """Raise from routes to return a consistent JSON error: {"error": ..., "detail": ...}."""

    def __init__(self, status_code: int, error: str, detail: str = "") -> None:
        super().__init__(detail or error)
        self.status_code = status_code
        self.error = error
        self.detail = detail


class ErrorResponse(BaseModel):
    error: str = Field(..., examples=["Unsupported audio format"])
    detail: str = Field("", examples=["Allowed formats: .wav, .mp3, ..."])


class STTResponse(BaseModel):
    text: str = Field(..., description="Recognised text")
    model: str = Field(..., description="STT model that produced the text")
    language: str
    processing_seconds: float


class STTModelsResponse(BaseModel):
    models: list[str]
    default: str


class TTSRequest(BaseModel):
    text: str = Field(..., description="Malayalam text to speak", examples=["നമസ്കാരം, സുഖമാണോ?"])
    model: str | None = Field(None, description="TTS model name; defaults to DEFAULT_TTS_MODEL")

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must not be empty.")
        max_chars = int(os.getenv("TTS_MAX_CHARS", "1000"))
        if len(value) > max_chars:
            raise ValueError(f"Text is too long ({len(value)} characters, max {max_chars}).")
        return value


class LLMRequest(BaseModel):
    text: str = Field(..., description="Prompt to send to the LLM", examples=["എന്താണ് നിങ്ങുടെ പേര്?"])
    model: str | None = Field(None, description="LLM model name; defaults to DEFAULT_LLM_MODEL")
    system: str | None = Field(
        None,
        description="Optional system instruction",
        examples=["You are a helpful assistant. Reply in Malayalam."],
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Text must not be empty.")
        return value


class LLMResponse(BaseModel):
    reply: str = Field(..., description="The model's reply")
    model: str = Field(..., description="LLM model that produced the reply")
    processing_seconds: float


class HealthResponse(BaseModel):
    status: str = "ok"
    stt_models: list[str]
    tts_models: list[str]
    llm_models: list[str] = Field(default_factory=list)
    loaded_models: list[str] = Field(default_factory=list)
