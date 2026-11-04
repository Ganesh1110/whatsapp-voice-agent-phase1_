"""Indic Parler-TTS (ai4bharat/indic-parler-tts) for Malayalam.

A multilingual Indic TTS that takes two inputs:
  * ``prompt``     — the text to speak
  * ``description`` — a natural-language description of the speaking style

Requires the ``parler-tts`` library::

    pip install git+https://github.com/huggingface/parler-tts.git

Set in ``.env``::

    INDIC_PARLER_TTS_MODEL_ID=ai4bharat/indic-parler-tts
    # Optional style description (Malayalam female speaker, clear/close recording).
    INDIC_PARLER_TTS_DESCRIPTION="Anjali speaks clearly in a close-sounding environment with excellent recording quality, neutral tone and moderate pace."
"""
import logging
import os

from .base_tts import BaseTTS, SynthesisError, SynthesisResult

logger = logging.getLogger(__name__)

DEFAULT_DESCRIPTION = (
    "Anjali speaks clearly in a close-sounding environment with excellent recording "
    "quality, neutral tone and moderate pace."
)


class IndicParlerTTS(BaseTTS):
    name = "indic-parler-tts"

    def __init__(self, model_id: str | None = None) -> None:
        super().__init__()
        self.model_id = model_id or os.getenv("INDIC_PARLER_TTS_MODEL_ID", "ai4bharat/indic-parler-tts")
        self.description = os.getenv("INDIC_PARLER_TTS_DESCRIPTION", DEFAULT_DESCRIPTION)
        self._model = None
        self._tokenizer = None
        self._description_tokenizer = None
        self._device = "cpu"

    def _load(self) -> None:
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Indic Parler-TTS '%s' on %s", self.model_id, self._device)
        self._model = ParlerTTSForConditionalGeneration.from_pretrained(self.model_id).to(self._device).eval()
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        enc_name = getattr(self._model.config.text_encoder, "_name_or_path", self.model_id)
        self._description_tokenizer = AutoTokenizer.from_pretrained(enc_name)

    def _synthesize(self, text: str) -> SynthesisResult:
        import torch

        if self._model is None:
            raise SynthesisError("Indic Parler-TTS model not loaded.")

        description_input_ids = self._description_tokenizer(
            self.description, return_tensors="pt"
        ).to(self._device)
        prompt_input_ids = self._tokenizer(text, return_tensors="pt").to(self._device)

        with torch.no_grad():
            generation = self._model.generate(
                input_ids=description_input_ids.input_ids,
                attention_mask=description_input_ids.attention_mask,
                prompt_input_ids=prompt_input_ids.input_ids,
                prompt_attention_mask=prompt_input_ids.attention_mask,
            )

        audio = generation.cpu().numpy().squeeze().astype("float32")
        sampling_rate = int(getattr(self._model.config, "sampling_rate", 24000))
        if audio.size == 0:
            raise SynthesisError("Indic Parler-TTS produced no audio.")
        return SynthesisResult(waveform=audio, sampling_rate=sampling_rate)
