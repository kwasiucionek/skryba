"""Dzielenie tekstu na fragmenty (chunki) do indeksacji wektorowej.

Chunkujemy per strona, żeby zachować informację o numerze strony przy
każdym fragmencie (przydatne do cytowania źródeł w odpowiedziach RAG).
Okno znakowe z zakładką (overlap), z preferencją cięcia na granicy
białego znaku, żeby nie rozrywać słów.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP = 200


@dataclass
class Chunk:
    page_number: int
    chunk_index: int  # kolejność fragmentu w obrębie całego dokumentu
    text: str


def _split_page(text: str, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        # spróbuj przyciąć do najbliższej spacji w tył, by nie ciąć słowa
        if end < n:
            space = text.rfind(" ", start + max_chars - overlap, end)
            if space != -1 and space > start:
                end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_pages(
    pages: list[tuple[int, str]],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Dzieli listę (numer_strony, tekst) na fragmenty z globalną numeracją."""
    result: list[Chunk] = []
    idx = 0
    for page_number, text in pages:
        for piece in _split_page(text, max_chars, overlap):
            result.append(Chunk(page_number=page_number, chunk_index=idx, text=piece))
            idx += 1
    return result
