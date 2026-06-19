"""Pipeline OCR — wysokopoziomowe API dla reszty aplikacji.

Spina cały przepływ:
    plik (PDF/obraz) -> [warstwa tekstowa?] -> [preprocessing] -> silnik -> scalanie

WAŻNE: preprocessing (skala szarości, CLAHE, deskew) pomaga klasycznym
silnikom (Tesseract), ale modelom wizyjnym (VLM, tryb QUALITY) zwykle
SZKODZI — są trenowane na naturalnych, kolorowych obrazach. Dlatego
domyślnie preprocessing stosujemy tylko dla trybu FAST, a dla QUALITY
wysyłamy surowy render (jak w testach modeli). Można to wymusić
parametrem do_preprocess=True/False.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .engines import EngineMode, get_engine
from .pdf_utils import (
    DEFAULT_DPI,
    extract_text_layer,
    pdf_page_count,
    render_page,
)
from .preprocessing import preprocess

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class PageResult:
    page_number: int  # 1-indeksowany
    text: str
    source: str  # "text_layer" | "ocr"
    engine_name: str | None = None
    confidence: float | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class DocumentResult:
    pages: list[PageResult]
    mode: EngineMode

    @property
    def full_text(self) -> str:
        return "\n\n".join(
            f"--- Strona {p.page_number} ---\n{p.text}" for p in self.pages
        )


def _ocr_image_bytes(image_bytes: bytes, engine, *, do_preprocess: bool) -> PageResult:
    processed = preprocess(image_bytes) if do_preprocess else image_bytes
    result = engine.ocr_image(processed)
    return PageResult(
        page_number=0,  # ustawiane przez wywołującego
        text=result.text,
        source="ocr",
        engine_name=result.engine_name,
        confidence=result.confidence,
        meta=result.meta,
    )


def ocr_file(
    file_path: str,
    *,
    mode: EngineMode | str | None = None,
    dpi: int = DEFAULT_DPI,
    do_preprocess: bool | None = None,
    skip_text_layer: bool = False,
) -> DocumentResult:
    """Przetwarza cały plik (PDF lub obraz) i zwraca wynik dla dokumentu.

    do_preprocess:
        None  -> auto: preprocessing tylko dla trybu FAST (Tesseract),
                 pominięty dla QUALITY (VLM) — surowy obraz daje lepsze wyniki,
        True  -> wymuś preprocessing niezależnie od trybu,
        False -> wymuś brak preprocessingu.
    """
    engine = get_engine(mode)

    # Auto-decyzja: VLM dostaje surowy obraz, Tesseract — przetworzony.
    if do_preprocess is None:
        do_preprocess = engine.mode == EngineMode.FAST

    suffix = Path(file_path).suffix.lower()
    pages: list[PageResult] = []

    if suffix == ".pdf":
        count = pdf_page_count(file_path)
        for i in range(count):
            if not skip_text_layer:
                layer = extract_text_layer(file_path, i)
                if layer is not None:
                    pages.append(
                        PageResult(
                            page_number=i + 1,
                            text=layer,
                            source="text_layer",
                        )
                    )
                    continue
            image_bytes = render_page(file_path, i, dpi=dpi)
            page = _ocr_image_bytes(image_bytes, engine, do_preprocess=do_preprocess)
            page.page_number = i + 1
            pages.append(page)

    elif suffix in IMAGE_SUFFIXES:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
        page = _ocr_image_bytes(image_bytes, engine, do_preprocess=do_preprocess)
        page.page_number = 1
        pages.append(page)

    else:
        raise ValueError(f"Nieobsługiwany format pliku: {suffix}")

    return DocumentResult(pages=pages, mode=engine.mode)
