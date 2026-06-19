"""Testy rdzenia OCR: router silników i logika preprocessingu."""

from __future__ import annotations

import pytest

from ocr.engines import registry
from ocr.engines.base import EngineMode, OCREngine, OCRResult


class _StubEngine(OCREngine):
    def __init__(self, mode, available=True, base_url="http://x"):
        self.mode = mode
        self.name = mode.value
        self.base_url = base_url
        self._available = available
        self.seen = None

    def is_available(self):
        return self._available

    def ocr_image(self, image_bytes, prompt=None):
        self.seen = image_bytes
        return OCRResult(text="x", engine_name=self.name, mode=self.mode)


def test_router_returns_available_engine(monkeypatch):
    eng = _StubEngine(EngineMode.QUALITY, available=True)
    monkeypatch.setitem(registry._BUILDERS, EngineMode.QUALITY, lambda: eng)
    assert registry.get_engine("quality") is eng


def test_router_raises_for_unavailable_quality_no_fallback(monkeypatch):
    """Niedostępny QUALITY ma rzucać czytelny błąd, NIE spadać na Tesseract."""
    eng = _StubEngine(EngineMode.QUALITY, available=False)
    monkeypatch.setitem(registry._BUILDERS, EngineMode.QUALITY, lambda: eng)
    with pytest.raises(RuntimeError) as exc:
        registry.get_engine("quality")
    assert "host.docker.internal" in str(exc.value)


def test_router_raises_for_unavailable_fast(monkeypatch):
    eng = _StubEngine(EngineMode.FAST, available=False)
    monkeypatch.setitem(registry._BUILDERS, EngineMode.FAST, lambda: eng)
    with pytest.raises(RuntimeError) as exc:
        registry.get_engine("fast")
    assert "Tesseract" in str(exc.value)


def _setup_pipeline(monkeypatch, mode):
    from ocr import pipeline as P

    eng = _StubEngine(mode)
    monkeypatch.setattr(P, "get_engine", lambda m=None: eng)
    monkeypatch.setattr(P, "preprocess", lambda b, **k: b"PRZETWORZONE")
    return P, eng


def test_quality_skips_preprocessing(monkeypatch, tmp_path):
    """VLM (QUALITY) dostaje surowy obraz — bez preprocessingu."""
    P, eng = _setup_pipeline(monkeypatch, EngineMode.QUALITY)
    img = tmp_path / "skan.png"
    img.write_bytes(b"SUROWY")
    P.ocr_file(str(img))
    assert eng.seen == b"SUROWY"


def test_fast_applies_preprocessing(monkeypatch, tmp_path):
    """Tesseract (FAST) dostaje przetworzony obraz."""
    P, eng = _setup_pipeline(monkeypatch, EngineMode.FAST)
    img = tmp_path / "skan.png"
    img.write_bytes(b"SUROWY")
    P.ocr_file(str(img))
    assert eng.seen == b"PRZETWORZONE"


def test_force_preprocess_overrides_mode(monkeypatch, tmp_path):
    P, eng = _setup_pipeline(monkeypatch, EngineMode.QUALITY)
    img = tmp_path / "skan.png"
    img.write_bytes(b"SUROWY")
    P.ocr_file(str(img), do_preprocess=True)
    assert eng.seen == b"PRZETWORZONE"
