"""ARI voice-stream helpers: VAD/utterance detection. No network is used."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import ari_routes  # noqa: E402


def _pcm(amplitude: float, frames: int) -> bytes:
    samples = np.full(ari_routes.FRAME_BYTES // 2 * frames, int(amplitude * 32767), dtype="<i2")
    return samples.tobytes()


def test_silence_produces_no_utterance():
    detector = ari_routes._UtteranceDetector()
    assert detector.push(b"\x00\x00" * (ari_routes.FRAME_BYTES // 2) * 10) is None
    assert detector.flush() == b""


def test_speech_then_silence_completes_utterance():
    detector = ari_routes._UtteranceDetector()
    speech_frames = int(ari_routes.VAD_MIN_SPEECH_SECONDS * 1000 / ari_routes.FRAME_MS) + 5
    silence_frames = int(ari_routes.VAD_SILENCE_SECONDS * 1000 / ari_routes.FRAME_MS) + 5

    assert detector.push(_pcm(0.5, speech_frames)) is None
    utterance = detector.push(_pcm(0.0, silence_frames))

    assert utterance is not None
    assert len(utterance) >= speech_frames * ari_routes.FRAME_BYTES


def test_preroll_keeps_speech_onset():
    detector = ari_routes._UtteranceDetector()
    preroll_frames = 3
    speech_frames = 20
    detector.push(_pcm(0.001, preroll_frames))
    detector.push(_pcm(0.5, speech_frames))
    utterance = detector.flush()
    assert len(utterance) >= (preroll_frames + speech_frames) * ari_routes.FRAME_BYTES


def test_short_blip_is_dropped():
    detector = ari_routes._UtteranceDetector()
    detector.push(_pcm(0.5, 2))
    assert detector.flush() == b""
