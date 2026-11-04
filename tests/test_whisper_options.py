"""Whisper device/dtype selection tests. No torch or weights required."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stt.whisper_stt import _resolve_device, _resolve_dtype  # noqa: E402


class FakeCuda:
    def __init__(self, free_bytes=0, available=True, fail=False):
        self.free_bytes = free_bytes
        self.available = available
        self.fail = fail
        self.OutOfMemoryError = RuntimeError

    def is_available(self):
        return self.available

    def mem_get_info(self):
        if self.fail:
            raise RuntimeError("CUDA error: out of memory")
        return self.free_bytes, 16 * 1024**3


class FakeTorch:
    float16 = "float16"
    float32 = "float32"
    bfloat16 = "bfloat16"

    def __init__(self, **kwargs):
        self.cuda = FakeCuda(**kwargs)


def test_auto_uses_cpu_when_gpu_low(monkeypatch):
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)
    monkeypatch.setenv("WHISPER_MIN_GPU_FREE_GB", "4")
    assert _resolve_device(FakeTorch(free_bytes=1 * 1024**3)) == "cpu"


def test_auto_uses_gpu_when_enough_memory(monkeypatch):
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)
    monkeypatch.setenv("WHISPER_MIN_GPU_FREE_GB", "4")
    assert _resolve_device(FakeTorch(free_bytes=10 * 1024**3)) == "cuda:0"


def test_memory_query_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.delenv("WHISPER_DEVICE", raising=False)
    assert _resolve_device(FakeTorch(fail=True)) == "cpu"


def test_explicit_cpu_and_cuda(monkeypatch):
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    assert _resolve_device(FakeTorch(free_bytes=10 * 1024**3)) == "cpu"
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    assert _resolve_device(FakeTorch(free_bytes=0)) == "cuda:0"


def test_dtype_defaults(monkeypatch):
    torch = FakeTorch()
    monkeypatch.delenv("WHISPER_DTYPE", raising=False)
    assert _resolve_dtype(torch, "cpu") == torch.float32
    assert _resolve_dtype(torch, "cuda:0") == torch.float16
    monkeypatch.setenv("WHISPER_DTYPE", "bfloat16")
    assert _resolve_dtype(torch, "cuda:0") == torch.bfloat16
