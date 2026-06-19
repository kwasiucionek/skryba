"""Ekstrakcja pól zdefiniowanych przez użytkownika.

Niezależne od Django: przyjmuje listę specyfikacji pól (klucz, prompt, typ)
i zwraca słownik {klucz: wartość}. Korzysta z tego samego odpornego parsera
JSON i wywołania Ollamy co standardowa ekstrakcja metadanych.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from .extractor import _extract_json_object, _post

_MAX_CHARS = 8000


@dataclass
class FieldSpec:
    key: str
    prompt: str
    type: str = "text"  # text | number | date


def _coerce(value, field_type: str):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if field_type == "number":
        try:
            return float(str(value).replace(",", ".").replace(" ", ""))
        except (TypeError, ValueError):
            return None
    if field_type == "date":
        s = str(value).strip()
        try:
            date.fromisoformat(s)
            return s
        except ValueError:
            return None
    return str(value).strip()


def extract_custom_fields(
    full_text: str,
    fields: list[FieldSpec],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> dict:
    """Wyodrębnia wartości pól użytkownika z treści dokumentu."""
    if not fields:
        return {}

    model = model or os.getenv("EXTRACT_OLLAMA_MODEL", "gemma4:31b-cloud")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    api_key = api_key or os.getenv("OLLAMA_API_KEY")

    text = full_text.strip()
    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS // 2] + "\n\n[...]\n\n" + text[-_MAX_CHARS // 2 :]

    lines = "\n".join(f'- "{f.key}": {f.prompt} (typ: {f.type})' for f in fields)
    keys = ", ".join(f.key for f in fields)
    system = (
        "Wyodrębniasz dodatkowe pola z polskiego dokumentu. Zwracasz WYŁĄCZNIE "
        "jeden obiekt JSON o dokładnie podanych kluczach. Brak danych => null. "
        "Daty w formacie YYYY-MM-DD, liczby jako liczby (kropka dziesiętna)."
    )
    user = (
        f"Wyodrębnij poniższe pola i zwróć WYŁĄCZNIE obiekt JSON z kluczami: {keys}.\n\n"
        f"Pola:\n{lines}\n\n"
        f"=== TREŚĆ DOKUMENTU ===\n{text}\n=== KONIEC TREŚCI ==="
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
        "format": "json",
    }

    content = _post(base_url, payload, api_key, timeout)
    obj = _extract_json_object(content)
    if isinstance(obj, dict) and len(obj) == 1:  # rozpakuj ewentualne opakowanie
        inner = next(iter(obj.values()))
        if isinstance(inner, dict):
            obj = inner

    return {f.key: _coerce(obj.get(f.key), f.type) for f in fields}
