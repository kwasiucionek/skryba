"""Bazowy interfejs silnika OCR.

Każdy silnik (Tesseract, Ollama, dots.ocr, ...) implementuje ten sam
kontrakt, dzięki czemu reszta aplikacji nie wie, jakiego silnika używa.
To pozwala podmieniać model/silnik wyłącznie przez konfigurację (env).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class EngineMode(str, Enum):
    """Tryb pracy silnika.

    FAST    – działa na CPU, bez GPU i bez chmury (Tesseract).
    QUALITY – wysoka jakość, wymaga GPU lokalnie albo Ollama Cloud (VLM).
    """

    FAST = "fast"
    QUALITY = "quality"


@dataclass
class OCRResult:
    """Wynik OCR pojedynczego obrazu (jednej strony)."""

    text: str
    engine_name: str
    mode: EngineMode
    confidence: float | None = None  # 0.0–1.0, jeśli silnik potrafi policzyć
    meta: dict = field(default_factory=dict)  # czas, model, parametry itp.


class OCREngine(ABC):
    """Wspólny interfejs każdego silnika OCR."""

    name: str = "base"
    mode: EngineMode = EngineMode.FAST

    @abstractmethod
    def ocr_image(self, image_bytes: bytes, prompt: str | None = None) -> OCRResult:
        """Rozpoznaje tekst z pojedynczego obrazu (PNG/JPEG jako bytes).

        Parametr ``prompt`` ma sens tylko dla silników VLM (Ollama);
        silniki klasyczne (Tesseract) go ignorują.
        """
        raise NotImplementedError

    def is_available(self) -> bool:
        """Czy silnik jest gotowy do użycia w tym środowisku.

        Pozwala routerowi zrobić fallback, gdy np. brak Tesseracta
        w systemie albo Ollama nie odpowiada.
        """
        return True
