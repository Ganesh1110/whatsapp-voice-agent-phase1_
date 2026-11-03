"""AI4Bharat IndicConformer STT.

The model ships custom code on the Hugging Face Hub, so it is loaded with
`trust_remote_code=True`. The repo may be gated: accept its terms on the model
page and set HF_TOKEN in your .env if loading fails with a 401/403.
"""
import logging
import os

from .base_stt import BaseSTT, load_audio

logger = logging.getLogger(__name__)


class IndicConformerSTT(BaseSTT):
    name = "indicconformer"

    def __init__(self, model_id: str | None = None, decoder: str | None = None) -> None:
        super().__init__()
        self.model_id = model_id or os.getenv(
            "INDICCONFORMER_MODEL_ID", "ai4bharat/indic-conformer-600m-multilingual"
        )
        # The model supports "ctc" and "rnnt" decoding.
        self.decoder = (decoder or os.getenv("INDICCONFORMER_DECODER", "ctc")).lower()
        self._model = None

    def _load(self) -> None:
        from transformers import AutoModel

        self._model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)

    def _transcribe(self, audio_path: str, language: str) -> str:
        import torch

        audio = load_audio(audio_path)
        wav = torch.from_numpy(audio).unsqueeze(0)  # shape (1, samples), 16 kHz mono
        # Call signature from the model card: model(wav, language_code, decoder)
        text = self._model(wav, language.lower(), self.decoder)
        return text if isinstance(text, str) else str(text)
