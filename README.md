# Voice App – Phase 1 (STT + TTS)

A standalone Malayalam voice-processing service: **Speech-to-Text** (Whisper, AI4Bharat IndicConformer) and **Text-to-Speech** (`facebook/mms-tts-mal`), exposed through a FastAPI backend with a simple web frontend.

This is **Phase 1** of a WhatsApp AI agent. WhatsApp, n8n and LLM-agent integration are intentionally *not* included; they come in Phase 2.

## Features

- `POST /stt` – upload audio, choose a model, get text back
- `POST /tts` – send Malayalam text, get a WAV file back
- `GET /health` – health check (also lists registered/loaded models)
- Swagger UI at `/docs`
- Responsive frontend (tabs for STT and TTS, loading states, error messages, audio player and download)
- Plugin-style model registries, so new models can be added without touching the API

## Project structure

```
voice-app/
├── stt/        # base_stt.py (interface), whisper_stt.py, indicconformer_stt.py, registry in __init__.py
├── tts/        # base_tts.py (interface), mms_tts.py, registry in __init__.py
├── api/        # main.py (app, CORS, errors), stt_routes.py, tts_routes.py, schemas.py
├── frontend/   # index.html, style.css, script.js
├── outputs/    # generated audio (git-ignored)
├── tests/      # test_stt.py, test_tts.py
├── requirements.txt, .env.example, .gitignore
```

## Requirements

- Python 3.10+
- **ffmpeg** (needed to decode mp3 / m4a / webm / opus uploads)
  - macOS: `brew install ffmpeg` · Ubuntu: `sudo apt install ffmpeg` · Windows: `winget install ffmpeg`
- ~2–6 GB of disk for model weights (downloaded from Hugging Face on first use and cached outside the repo)
- A GPU is optional; models fall back to CPU automatically

## Installation

```bash
git clone <your-repo-url> whatsapp-voice-agent-phase1
cd whatsapp-voice-agent-phase1

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # then edit if needed
```

## Model setup

Weights are **not** stored in the repo. By default, models download automatically the first time they are used. For Whisper, you can download the snapshot into this machine before starting the API, then run from that local copy (including offline):

```bash
source .venv/bin/activate
python scripts/download_whisper.py
```

This saves the configured model (`openai/whisper-small` by default) to `models/whisper-small`. The app detects that directory and loads it locally. Set `WHISPER_MODEL_PATH=/your/path/to/model` in `.env` to use a different directory. To switch model versions, change `WHISPER_MODEL_ID` before running the download command. Downloading requires internet access once; STT inference afterward uses the local files. You can also preload the model at server startup with `PRELOAD_MODELS=whisper` in `.env`.

| Model | Hugging Face ID | Notes |
|---|---|---|
| Whisper | `openai/whisper-small` (default) | Set `WHISPER_MODEL_ID=openai/whisper-large-v3` before downloading for better Malayalam accuracy (needs more RAM/GPU) |
| IndicConformer | `ai4bharat/indic-conformer-600m-multilingual` | Loaded with `trust_remote_code=True`. If you get a 401/403, accept the model's terms on its Hugging Face page and set `HF_TOKEN` in `.env`. If loading fails on a missing package, check the model card for its current requirements. |
| MMS TTS | `facebook/mms-tts-mal` | Malayalam, VITS-based, outputs 16 kHz audio |

> The IndicConformer integration follows the usage shown on its model card. It has not been run end-to-end in the environment this project was generated in, so test it on your machine and adjust `stt/indicconformer_stt.py` if the model's interface has changed.

## Running

```bash
uvicorn api.main:app --reload --port 8000
```

- Frontend: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- Health: http://localhost:8000/health

## API usage

### `POST /stt`

Multipart form: `file` (required), `model` (`whisper` | `indicconformer`, optional), `language` (default `ml`).

```bash
curl -X POST http://localhost:8000/stt \
  -F "file=@sample.wav" \
  -F "model=whisper"
```

```json
{ "text": "…", "model": "whisper", "language": "ml", "processing_seconds": 3.42 }
```

Supported formats: wav, mp3, ogg, opus, m4a, mp4, flac, webm, aac (max `MAX_UPLOAD_MB`, default 25). The browser frontend can also record from your microphone; microphone access requires localhost or HTTPS.

### `POST /tts`

JSON body; returns `audio/wav`.

```bash
curl -X POST http://localhost:8000/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "നമസ്കാരം, സുഖമാണോ?", "model": "mms"}' \
  --output speech.wav
```

### Errors

All errors share one shape:

```json
{ "error": "Unsupported audio format", "detail": "Got '.txt'. Allowed: .aac, .flac, ..." }
```

| Status | Meaning |
|---|---|
| 400 | Unsupported format, empty file, or unknown model |
| 413 | Upload larger than `MAX_UPLOAD_MB` |
| 422 | Invalid request (e.g. empty or too-long text, missing file) |
| 500 | Transcription / speech generation failed |
| 503 | Model could not be loaded (missing weights, no network, auth) |

## Configuration

All settings are environment variables; see `.env.example`. Key ones: `DEFAULT_STT_MODEL`, `WHISPER_MODEL_ID`, `INDICCONFORMER_DECODER` (`ctc`/`rnnt`), `MMS_TTS_MODEL_ID`, `CORS_ORIGINS`, `PRELOAD_MODELS`, `OUTPUT_DIR`, `MAX_UPLOAD_MB`, `TTS_MAX_CHARS`.

## Tests

```bash
pytest -v
```

Tests use fake models, so they run quickly and download nothing.

## Adding a new model

1. Subclass `BaseSTT` (or `BaseTTS`) and implement `_load()` and `_transcribe()` (or `_synthesize()`).
2. Register it in the package's `_BUILTIN` dict, or call `register_stt_model("name", MyClass)` / `register_tts_model(...)`.
3. It is immediately selectable via the `model` parameter, e.g. for Indic Parler-TTS or VITS in later phases.

## Notes

- Generated audio is saved in `outputs/` and never committed. Delete old files whenever you like.
- `CORS_ORIGINS=*` is for local development; set explicit origins before deploying.

## Phase 2 (not implemented here)

WhatsApp Business Cloud API, n8n workflows, an LLM agent, and sending voice replies. The `/stt` and `/tts` endpoints are designed to be called from n8n as plain HTTP requests.
