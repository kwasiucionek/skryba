"""Prompty dla ekstrakcji metadanych.

Jedno wywołanie LLM robi klasyfikację i ekstrakcję naraz. Kluczowa lekcja:
nie wszystkie modele respektują wymuszenie schematu przez pole ``format``
(np. gemma na Ollama Cloud go ignoruje i zwraca własną strukturę). Dlatego
DOKŁADNĄ strukturę JSON — z nazwami kluczy — podajemy wprost w promkcie.
Wtedy model zwraca właściwy kształt niezależnie od wsparcia dla schematu.

Dla długich dokumentów bierzemy początek i koniec tekstu — najważniejsze
dane są zwykle na górze, a kwoty/podsumowania na końcu.
"""

from __future__ import annotations

from .schemas import DocumentType

_DOC_TYPES = ", ".join(t.value for t in DocumentType)

# Wzorzec oczekiwanej odpowiedzi — płaski obiekt, klucze po angielsku.
JSON_TEMPLATE = (
    "{\n"
    f'  "doc_type": "<jeden z: {_DOC_TYPES}>",\n'
    '  "doc_date": "<data dokumentu YYYY-MM-DD lub null>",\n'
    '  "doc_number": "<numer / sygnatura lub null>",\n'
    '  "counterparty": "<druga strona: kontrahent/nadawca/sąd/urząd lub null>",\n'
    '  "total_amount": <kwota całkowita jako liczba lub null>,\n'
    '  "currency": "<np. PLN, EUR lub null>",\n'
    '  "summary": "<zwięzłe streszczenie 1–2 zdania>",\n'
    '  "tags": ["<słowa kluczowe po polsku>"],\n'
    '  "confidence": <pewność klasyfikacji 0.0–1.0 lub null>\n'
    "}"
)

SYSTEM_PROMPT = (
    "Jesteś precyzyjnym asystentem do analizy polskich dokumentów. "
    "Zwracasz WYŁĄCZNIE jeden obiekt JSON o dokładnie takich kluczach, "
    "jak podany wzorzec — bez zagnieżdżania w innym obiekcie i bez zmiany "
    "nazw kluczy. Jeśli danej nie ma w tekście, wstawiasz null. Kwoty jako "
    "liczby (kropka dziesiętna, bez separatora tysięcy i symbolu waluty). "
    "Daty w formacie YYYY-MM-DD."
)

HEAD_CHARS = 6000
TAIL_CHARS = 2000


def build_user_prompt(full_text: str) -> str:
    text = full_text.strip()
    if len(text) > HEAD_CHARS + TAIL_CHARS:
        text = (
            text[:HEAD_CHARS]
            + "\n\n[...pominięto środek dokumentu...]\n\n"
            + text[-TAIL_CHARS:]
        )
    return (
        "Wyodrębnij metadane z dokumentu i zwróć WYŁĄCZNIE jeden obiekt JSON "
        "o DOKŁADNIE takich kluczach (nie zagnieżdżaj go w innym obiekcie, "
        "nie tłumacz nazw kluczy na polski):\n\n"
        f"{JSON_TEMPLATE}\n\n"
        "Wartości pól mogą być po polsku, ale NAZWY KLUCZY pozostaw po "
        "angielsku, dokładnie jak we wzorcu.\n\n"
        "=== TREŚĆ DOKUMENTU ===\n"
        f"{text}\n"
        "=== KONIEC TREŚCI ==="
    )
