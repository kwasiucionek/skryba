"""Silnik FAST: Tesseract OCR (CPU, bez GPU, bez chmury).

Domyślny silnik dla self-hosterów bez karty graficznej.
Wymaga zainstalowanego w systemie pakietu `tesseract-ocr`
oraz pakietu językowego (np. `tesseract-ocr-pol`).
"""

from __future__ import annotations

import io
import time

from .base import EngineMode, OCREngine, OCRResult


class TesseractEngine(OCREngine):
    name = "tesseract"
    mode = EngineMode.FAST

    def __init__(self, lang: str = "pol+eng"):
        self.lang = lang

    def is_available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401

            import pytesseract as pt

            pt.get_tesseract_version()
            return True
        except Exception:
            return False

    def ocr_image(self, image_bytes: bytes, prompt: str | None = None) -> OCRResult:
        import pytesseract
        from PIL import Image

        start = time.perf_counter()
        image = Image.open(io.BytesIO(image_bytes))

        # image_to_data daje per-słowo confidence — uśredniamy do oceny jakości
        data = pytesseract.image_to_data(
            image, lang=self.lang, output_type=pytesseract.Output.DICT
        )
        text = pytesseract.image_to_string(image, lang=self.lang)

        confs = [int(c) for c in data.get("conf", []) if c not in ("-1", -1)]
        confidence = (sum(confs) / len(confs) / 100.0) if confs else None

        elapsed = time.perf_counter() - start
        return OCRResult(
            text=text.strip(),
            engine_name=self.name,
            mode=self.mode,
            confidence=confidence,
            meta={"lang": self.lang, "elapsed_s": round(elapsed, 2)},
        )
