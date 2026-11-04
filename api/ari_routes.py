"""Asterisk ARI WebSocket bridge.

Connects Asterisk (ARI externalMedia / Stasis) to the voice pipeline:

    audio in (PCM)  ->  STT  ->  Ollama  ->  TTS  ->  audio out (PCM)

Asterisk sends audio as binary WebSocket frames (16-bit PCM mono).
Control commands are text JSON frames:

    {"action": "flush"}   - transcribe buffered audio now
    {"action": "end"}     - close the stream

The server replies with text JSON (stt / reply metadata) followed by binary
PCM audio frames the PBX can play back to the caller.
"""
import json
import logging
import os
import tempfile
import uuid

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from llm import (
    CompletionError,
    LLMModelLoadError,
    UnknownLLMModelError,
    get_llm_model,
)
from stt import (
    ModelLoadError as STTModelLoadError,
    TranscriptionError,
    UnknownSTTModelError,
    get_stt_model,
)
from stt.base_stt import TARGET_SAMPLE_RATE
from tts import (
    SynthesisError,
    TTSModelLoadError,
    UnknownTTSModelError,
    get_tts_model,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Asterisk ARI"])

SAMPLE_RATE_IN = int(os.getenv("ARI_SAMPLE_RATE_IN", "8000"))
SAMPLE_RATE_OUT = int(os.getenv("ARI_SAMPLE_RATE_OUT", "8000"))
MAX_BUFFER_SECONDS = float(os.getenv("ARI_MAX_BUFFER_SECONDS", "6.0"))
MIN_UTTERANCE_SECONDS = float(os.getenv("ARI_MIN_UTTERANCE_SECONDS", "0.8"))
LANGUAGE = os.getenv("ARI_LANGUAGE", "ml")

DEFAULT_SYSTEM = (
    "You are a helpful voice assistant on a phone call. Reply in the same "
    "language as the caller (preferably Malayalam). Keep answers short and "
    "natural for text-to-speech. No markdown, no bullet points, no special "
    "characters—plain spoken text only."
)

BYTES_PER_SAMPLE = 2  # 16-bit PCM


def _pcm16_to_float32(data: bytes, sample_rate: int) -> np.ndarray:
    """Convert raw 16-bit PCM bytes to a mono float32 numpy array at 16 kHz."""
    if len(data) % BYTES_PER_SAMPLE != 0:
        data = data[: len(data) - (len(data) % BYTES_PER_SAMPLE)]
    arr = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if sample_rate != TARGET_SAMPLE_RATE:
        import librosa

        arr = librosa.resample(arr, orig_sr=sample_rate, target_sr=TARGET_SAMPLE_RATE)
    return arr


def _float32_to_pcm16(audio: np.ndarray, sample_rate: int, target_rate: int) -> bytes:
    """Convert a float32 numpy array to raw 16-bit PCM bytes."""
    audio = np.clip(audio, -1.0, 1.0)
    if sample_rate != target_rate:
        import librosa

        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_rate)
    pcm = (audio * 32767).astype(np.int16)
    return pcm.tobytes()


def _write_wav(audio: np.ndarray, sample_rate: int) -> str:
    """Write float32 audio to a temp WAV file and return its path."""
    import soundfile as sf

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio, sample_rate)
    return tmp.name


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _process_audio(
    ws: WebSocket,
    pcm_bytes: bytes,
    session_id: str,
    stt_model,
    llm_model,
    tts_model,
    system_prompt: str,
) -> None:
    """Run one STT -> LLM -> TTS pass on buffered PCM and stream audio back."""
    if len(pcm_bytes) < BYTES_PER_SAMPLE * SAMPLE_RATE_IN * MIN_UTTERANCE_SECONDS:
        await _send_json(
            ws,
            {
                "type": "skip",
                "session": session_id,
                "reason": "utterance too short",
            },
        )
        return

    audio = _pcm16_to_float32(pcm_bytes, SAMPLE_RATE_IN)

    # --- STT ---
    wav_path = _write_wav(audio, TARGET_SAMPLE_RATE)
    try:
        text = stt_model.transcribe(wav_path, LANGUAGE)
    except STTModelLoadError as exc:
        await _send_json(ws, {"type": "error", "stage": "stt", "detail": str(exc)})
        return
    except TranscriptionError as exc:
        await _send_json(ws, {"type": "error", "stage": "stt", "detail": str(exc)})
        return
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass

    if not text or not text.strip():
        await _send_json(ws, {"type": "stt", "session": session_id, "text": ""})
        return

    await _send_json(
        ws,
        {
            "type": "stt",
            "session": session_id,
            "text": text,
        },
    )
    logger.info("ARI[%s] STT: %s", session_id, text)

    # --- LLM ---
    try:
        reply = llm_model.complete(text, system_prompt)
    except LLMModelLoadError as exc:
        await _send_json(ws, {"type": "error", "stage": "llm", "detail": str(exc)})
        return
    except CompletionError as exc:
        await _send_json(ws, {"type": "error", "stage": "llm", "detail": str(exc)})
        return

    await _send_json(
        ws,
        {
            "type": "reply",
            "session": session_id,
            "text": reply,
        },
    )
    logger.info("ARI[%s] LLM: %s", session_id, reply)

    # --- TTS ---
    try:
        result = tts_model.synthesize(reply)
    except TTSModelLoadError as exc:
        await _send_json(ws, {"type": "error", "stage": "tts", "detail": str(exc)})
        return
    except SynthesisError as exc:
        await _send_json(ws, {"type": "error", "stage": "tts", "detail": str(exc)})
        return

    pcm_out = _float32_to_pcm16(result.waveform, int(result.sampling_rate), SAMPLE_RATE_OUT)

    # Stream audio back in chunks so Asterisk can play progressively.
    chunk = 320  # 20 ms @ 8kHz mono PCM16
    for i in range(0, len(pcm_out), chunk):
        await ws.send_bytes(pcm_out[i : i + chunk])
    await _send_json(ws, {"type": "done", "session": session_id})
    logger.info("ARI[%s] sent %d bytes of reply audio", session_id, len(pcm_out))


@router.websocket("/ari/stream")
async def ari_stream(ws: WebSocket) -> None:
    """WebSocket entry point for Asterisk ARI media streams."""
    await ws.accept()
    session_id = str(uuid.uuid4())[:8]
    logger.info("ARI stream connected: %s", session_id)

    # Resolve models lazily (weights load on first use).
    try:
        stt_model = get_stt_model(os.getenv("DEFAULT_STT_MODEL", "whisper"))
        llm_model = get_llm_model(os.getenv("DEFAULT_LLM_MODEL", "ollama"))
        tts_model = get_tts_model(os.getenv("DEFAULT_TTS_MODEL", "mms"))
    except (UnknownSTTModelError, UnknownLLMModelError, UnknownTTSModelError) as exc:
        await _send_json(ws, {"type": "error", "stage": "config", "detail": str(exc)})
        await ws.close(code=4000)
        return
    except (STTModelLoadError, LLMModelLoadError, TTSModelLoadError) as exc:
        await _send_json(ws, {"type": "error", "stage": "load", "detail": str(exc)})
        await ws.close(code=5003)
        return

    buffer = bytearray()
    last_flush = 0.0

    try:
        while True:
            msg = await ws.receive()

            if msg["type"] == "websocket.disconnect":
                break

            if msg.get("bytes"):
                buffer.extend(msg["bytes"])

                # Auto-flush when buffer exceeds max duration.
                secs = len(buffer) / (BYTES_PER_SAMPLE * SAMPLE_RATE_IN)
                if secs >= MAX_BUFFER_SECONDS:
                    await _process_audio(
                        ws,
                        bytes(buffer),
                        session_id,
                        stt_model,
                        llm_model,
                        tts_model,
                        DEFAULT_SYSTEM,
                    )
                    buffer = bytearray()
                    last_flush = 0.0

            if msg.get("text") is not None:
                try:
                    cmd = json.loads(msg["text"])
                except json.JSONDecodeError:
                    cmd = {}

                action = cmd.get("action")
                if action == "flush":
                    if buffer:
                        await _process_audio(
                            ws,
                            bytes(buffer),
                            session_id,
                            stt_model,
                            llm_model,
                            tts_model,
                            cmd.get("system", DEFAULT_SYSTEM),
                        )
                        buffer = bytearray()
                    last_flush = 0.0
                elif action == "end":
                    break
                elif action == "ping":
                    await _send_json(ws, {"type": "pong", "session": session_id})

    except WebSocketDisconnect:
        logger.info("ARI stream disconnected: %s", session_id)
    finally:
        if buffer:
            await _process_audio(
                ws,
                bytes(buffer),
                session_id,
                stt_model,
                llm_model,
                tts_model,
                DEFAULT_SYSTEM,
            )


@router.get("/ari/status", tags=["Asterisk ARI"])
def ari_status() -> dict:
    """ARI bridge configuration and model availability."""
    from llm import available_llm_models
    from stt import available_stt_models
    from tts import available_tts_models

    return {
        "websocket": "/ari/stream",
        "sample_rate_in": SAMPLE_RATE_IN,
        "sample_rate_out": SAMPLE_RATE_OUT,
        "max_buffer_seconds": MAX_BUFFER_SECONDS,
        "language": LANGUAGE,
        "stt_models": available_stt_models(),
        "llm_models": available_llm_models(),
        "tts_models": available_tts_models(),
    }
