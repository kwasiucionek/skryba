"""Schematy danych dla ekstrakcji metadanych.

Pydantic daje walidację i koercję typów z odpowiedzi LLM, a
``model_json_schema()`` służy jako schemat structured output dla Ollamy.
Jeden uniwersalny schemat z polami opcjonalnymi — model wypełnia te,
które pasują do danego typu dokumentu. Prostsze i pewniejsze niż
osobny schemat na każdy typ.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    FAKTURA = "faktura"
    UMOWA = "umowa"
    PISMO_SADOWE = "pismo_sadowe"
    PISMO_URZEDOWE = "pismo_urzedowe"
    PARAGON = "paragon"
    OFERTA = "oferta"
    KORESPONDENCJA = "korespondencja"
    INNE = "inne"


class ExtractedMetadata(BaseModel):
    """Ustrukturyzowane metadane wyciągnięte z treści dokumentu."""

    doc_type: DocumentType = Field(description="Typ dokumentu")
    doc_date: str | None = Field(
        default=None,
        description="Data dokumentu w formacie YYYY-MM-DD, jeśli występuje",
    )
    doc_number: str | None = Field(
        default=None, description="Numer dokumentu / sygnatura, jeśli występuje"
    )
    counterparty: str | None = Field(
        default=None,
        description="Druga strona: kontrahent, nadawca, sąd, urząd lub firma",
    )
    total_amount: float | None = Field(
        default=None, description="Kwota całkowita / do zapłaty, jeśli występuje"
    )
    currency: str | None = Field(
        default=None, description="Waluta kwoty, np. PLN, EUR"
    )
    summary: str = Field(
        default="", description="Zwięzłe streszczenie dokumentu (1–2 zdania)"
    )
    tags: list[str] = Field(
        default_factory=list, description="Kilka słów kluczowych po polsku"
    )
    confidence: float | None = Field(
        default=None, description="Pewność klasyfikacji typu, 0.0–1.0"
    )
