"""Generowanie przeszukiwalnego PDF (searchable PDF).

Tworzy PDF, który wygląda jak oryginał (obraz strony), ale ma pod spodem
niewidoczną warstwę tekstową — dzięki temu dokument można przeszukiwać
(Ctrl+F) i kopiować z niego tekst.

Uwaga o pozycjonowaniu: silniki VLM (Ollama) zwracają sam tekst, bez
współrzędnych słów, więc warstwa tekstowa jest pozycjonowana na poziomie
strony, nie słowa. To wystarcza do wyszukiwania i kopiowania — zaznaczanie
nie pokrywa się idealnie z obrazem, ale treść jest w pełni dostępna.

Polskie znaki wymagają fontu Unicode (Helvetica z base-14 nie ma ł, ą, ę…),
dlatego używamy DejaVuSans. Ścieżkę można nadpisać przez env OCR_PDF_FONT.
"""

from __future__ import annotations

import os
from pathlib import Path

import fitz  # PyMuPDF

from .pdf_utils import DEFAULT_DPI, render_page

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

# Typowe lokalizacje fontu DejaVuSans (Docker: fonts-dejavu-core).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/DejaVuSans.ttf",
]

_TEXT_MARGIN = 20  # punkty od krawędzi strony dla warstwy tekstowej


def _find_font() -> str | None:
    """Zwraca ścieżkę do fontu Unicode albo None (wtedy fallback na helv)."""
    override = os.getenv("OCR_PDF_FONT")
    if override and Path(override).is_file():
        return override
    for path in _FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    return None


def _fit_fontsize(page_rect: fitz.Rect, text: str, font_path: str | None) -> float:
    """Dobiera największy rozmiar fontu, przy którym cały tekst mieści się
    w obszarze strony. Pomiar na stronie tymczasowej, by nie rysować
    nadmiarowych warstw na docelowej stronie.
    """
    rect = page_rect + (_TEXT_MARGIN, _TEXT_MARGIN, -_TEXT_MARGIN, -_TEXT_MARGIN)
    fontname = "F0" if font_path else "helv"
    tmp = fitz.open()
    try:
        for fontsize in (9, 8, 7, 6, 5, 4, 3, 2, 1):
            page = tmp.new_page(width=page_rect.width, height=page_rect.height)
            leftover = page.insert_textbox(
                rect, text, fontsize=fontsize,
                fontname=fontname, fontfile=font_path, render_mode=3,
            )
            if leftover >= 0:
                return fontsize
        return 1
    finally:
        tmp.close()


def _add_image_page_with_text(
    out: fitz.Document, image_bytes: bytes, text: str,
    dpi: int, font_path: str | None,
) -> None:
    """Dodaje stronę: obraz jako tło + niewidoczna warstwa tekstowa."""
    pix = fitz.Pixmap(image_bytes)
    width_pt = pix.width * 72.0 / dpi
    height_pt = pix.height * 72.0 / dpi

    page = out.new_page(width=width_pt, height=height_pt)
    page.insert_image(page.rect, stream=image_bytes)

    if text.strip():
        fontname = "F0" if font_path else "helv"
        fontsize = _fit_fontsize(page.rect, text, font_path)
        rect = page.rect + (_TEXT_MARGIN, _TEXT_MARGIN, -_TEXT_MARGIN, -_TEXT_MARGIN)
        page.insert_textbox(
            rect, text, fontsize=fontsize,
            fontname=fontname, fontfile=font_path, render_mode=3,  # 3 = niewidoczny
        )


def build_searchable_pdf(
    source_path: str,
    document_result,
    output_path: str,
    *,
    dpi: int = DEFAULT_DPI,
) -> str:
    """Buduje przeszukiwalny PDF z wyniku OCR i pliku źródłowego.

    - strony OCR: obraz strony + niewidoczna warstwa tekstowa,
    - strony z warstwą tekstową (cyfrowy PDF): kopiujemy oryginalną stronę
      bez zmian (ma już idealny tekst i jakość).
    """
    suffix = Path(source_path).suffix.lower()
    font_path = _find_font()

    out = fitz.open()
    src = fitz.open(source_path) if suffix == ".pdf" else None
    try:
        for page in document_result.pages:
            idx = page.page_number - 1  # 1-indeks -> 0-indeks

            if page.source == "text_layer" and src is not None:
                out.insert_pdf(src, from_page=idx, to_page=idx)
                continue

            if suffix == ".pdf":
                image_bytes = render_page(source_path, idx, dpi=dpi)
            elif suffix in IMAGE_SUFFIXES:
                with open(source_path, "rb") as f:
                    image_bytes = f.read()
            else:
                raise ValueError(f"Nieobsługiwany format pliku: {suffix}")

            _add_image_page_with_text(out, image_bytes, page.text, dpi, font_path)

        out.save(output_path, garbage=4, deflate=True)
        return output_path
    finally:
        out.close()
        if src is not None:
            src.close()
