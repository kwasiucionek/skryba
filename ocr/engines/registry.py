"""Router silników OCR.

Centralne miejsce, w którym aplikacja prosi o silnik dla danego trybu.
Reszta kodu nie tworzy silników ręcznie — woła `get_engine(mode)`.
Konfiguracja idzie z env, więc zmiana modelu czy trybu nie wymaga
ruszania kodu.

WAŻNE: gdy wskazany silnik jest niedostępny, zgłaszamy CZYTELNY BŁĄD,
zamiast po cichu spadać na inny silnik. Cichy fallback (np. z QUALITY/VLM
na FAST/Tesseract) dawał mylące wyniki — dokument wyglądał na przetworzony
trybem Jakość, a faktycznie zrobił go Tesseract. Lepiej, żeby zadanie
jawnie zawiodło z informacją, co naprawić.
"""

from __future__ import annotations

import os

from .base import EngineMode, OCREngine
from .ollama_engine import OllamaEngine
from .tesseract_engine import TesseractEngine


def _build_fast() -> OCREngine:
    return TesseractEngine(lang=os.getenv("OCR_TESSERACT_LANG", "pol+eng"))


def _build_quality() -> OCREngine:
    return OllamaEngine(
        model=os.getenv("OCR_OLLAMA_MODEL", "kimi-k2.6:cloud"),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        api_key=os.getenv("OLLAMA_API_KEY"),
        timeout=int(os.getenv("OCR_OLLAMA_TIMEOUT", "300")),
    )


_BUILDERS = {
    EngineMode.FAST: _build_fast,
    EngineMode.QUALITY: _build_quality,
}


def get_engine(mode: EngineMode | str | None = None) -> OCREngine:
    """Zwraca silnik dla wskazanego trybu lub zgłasza czytelny błąd.

    Jeśli tryb nie podany, bierze OCR_DEFAULT_MODE z env (domyślnie 'fast').
    """
    if mode is None:
        mode = os.getenv("OCR_DEFAULT_MODE", EngineMode.FAST.value)
    mode = EngineMode(mode)

    engine = _BUILDERS[mode]()
    if engine.is_available():
        return engine

    if mode == EngineMode.QUALITY:
        base_url = getattr(engine, "base_url", "?")
        raise RuntimeError(
            f"Silnik QUALITY (Ollama) niedostępny pod {base_url}. "
            "Sprawdź, czy Ollama działa i czy OLLAMA_BASE_URL wskazuje na host "
            "(w Dockerze zwykle http://host.docker.internal:11434, nie localhost)."
        )
    raise RuntimeError(
        "Silnik FAST (Tesseract) niedostępny. Sprawdź instalację pakietu "
        "tesseract-ocr (oraz tesseract-ocr-pol dla języka polskiego)."
    )
