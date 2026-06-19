"""Ekstrakcja metadanych przez LLM (Ollama).

Ten sam wzorzec co router OCR: model i endpoint w pełni konfigurowalne
przez env, więc podmiana modelu nie wymaga zmian w kodzie. Korzysta ze
structured output Ollamy (pole ``format`` = schemat JSON z Pydantic),
z fallbackiem na zwykły tryb JSON.

Parsowanie jest odporne na typowe „brudy" w odpowiedzi modeli:
- bloki rozumowania <think>...</think> (modele reasoning, np. kimi/deepseek),
- obramowanie ```json ... ```,
- tekst wokół właściwego obiektu JSON.
Gdy nie da się sparsować, zgłaszamy czytelny błąd z nazwą modelu.
"""

from __future__ import annotations

import json
import os
import re

import requests

from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import ExtractedMetadata

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _extract_json_object(content: str | None) -> dict:
    """Wyłuskuje obiekt JSON z (potencjalnie zaśmieconej) odpowiedzi modelu."""
    if not content or not content.strip():
        raise ValueError("model zwrócił pustą odpowiedź")

    text = _THINK_RE.sub("", content).strip()  # usuń rozumowanie

    if text.startswith("```"):  # usuń obramowanie kodu
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    if not text:
        raise ValueError("odpowiedź pusta po usunięciu rozumowania/obramowania")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ostatnia szansa: wytnij najbardziej zewnętrzny obiekt { ... }
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("nie znaleziono obiektu JSON w odpowiedzi")


def _validate(obj: dict) -> ExtractedMetadata:
    """Waliduje wynik; jeśli model zagnieździł dane w pojedynczym kluczu
    (np. {"dokument_metadane": {...}}), próbuje rozpakować wnętrze.
    """
    try:
        return ExtractedMetadata.model_validate(obj)
    except Exception:
        if isinstance(obj, dict) and len(obj) == 1:
            inner = next(iter(obj.values()))
            if isinstance(inner, dict):
                return ExtractedMetadata.model_validate(inner)
        raise


def _post(base_url: str, payload: dict, api_key: str | None, timeout: int) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:  # wymagane dla Ollama Cloud
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama zwróciła {resp.status_code}: {resp.text[:500]}")
    return resp.json().get("message", {}).get("content", "")


def extract_metadata(
    full_text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    system_prompt: str | None = None,
    timeout: int = 180,
) -> ExtractedMetadata:
    """Klasyfikuje dokument i wyciąga metadane z jego treści."""
    model = model or os.getenv("EXTRACT_OLLAMA_MODEL", "gemma4:31b-cloud")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    api_key = api_key or os.getenv("OLLAMA_API_KEY")

    messages = [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(full_text)},
    ]
    base_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.0},
    }

    # Dwa formaty: schemat JSON (pewniejszy, gdy wspierany) i zwykły JSON.
    formats = [ExtractedMetadata.model_json_schema(), "json"]
    last_error: Exception | None = None

    for fmt in formats:
        try:
            content = _post(base_url, {**base_payload, "format": fmt}, api_key, timeout)
            return _validate(_extract_json_object(content))
        except Exception as exc:  # noqa: BLE001 — próbujemy kolejnego formatu
            last_error = exc

    raise RuntimeError(
        f"Nie udało się uzyskać metadanych z modelu '{model}'. "
        f"Sprawdź, czy model obsługuje wyjście JSON (structured output). "
        f"Szczegóły: {last_error}"
    )
