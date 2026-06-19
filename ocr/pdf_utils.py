"""Obsługa plików PDF (PyMuPDF / fitz).

Dwie kluczowe funkcje:
- ``pdf_page_count`` / ``render_page`` – render stron do PNG w zadanym DPI,
- ``extract_text_layer`` – jeśli PDF ma już warstwę tekstową (cyfrowy,
  nie skan), bierzemy tekst bezpośrednio i pomijamy kosztowny OCR.

DPI 300 jest domyślne, bo modele VLM i Tesseract dają najlepsze wyniki
przy rozdzielczości zbliżonej do natywnego skanu A4 300 DPI (~2480x3508).
"""

from __future__ import annotations

import fitz  # PyMuPDF

DEFAULT_DPI = 300
# Próg liczby znaków na stronę, powyżej którego uznajemy, że strona ma
# realną warstwę tekstową i nie wymaga OCR.
TEXT_LAYER_MIN_CHARS = 100


def pdf_page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_page(pdf_path: str, page_index: int, dpi: int = DEFAULT_DPI) -> bytes:
    """Renderuje pojedynczą stronę PDF do PNG (bytes)."""
    zoom = dpi / 72.0  # PDF natywnie operuje w 72 DPI (punktach)
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=matrix)
        return pix.tobytes("png")


def extract_text_layer(pdf_path: str, page_index: int) -> str | None:
    """Zwraca tekst warstwy tekstowej strony albo None, jeśli to skan.

    Pozwala pominąć OCR dla cyfrowych PDF-ów (oszczędność czasu i kosztów
    chmury). Jeśli tekstu jest mało, traktujemy stronę jako obrazową.
    """
    with fitz.open(pdf_path) as doc:
        text = doc[page_index].get_text().strip()
    if len(text) >= TEXT_LAYER_MIN_CHARS:
        return text
    return None
