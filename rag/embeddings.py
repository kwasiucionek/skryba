"""Generowanie embeddingów przez Ollamę.

Ten sam wzorzec env-driven co reszta projektu. Domyślnie nomic-embed-text
(768 wymiarów) — sprawdzony, lekki model do wyszukiwania semantycznego.
Uwaga: wymiar embeddingu (EMBED_DIM) musi zgadzać się z kolumną wektorową
w bazie; zmiana modelu na inny wymiar wymaga nowej migracji.
"""

from __future__ import annotations

import os

import requests


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 120,
) -> list[list[float]]:
    """Zwraca listę wektorów dla listy tekstów (batch w jednym żądaniu)."""
    if not texts:
        return []

    model = model or os.getenv("EMBED_OLLAMA_MODEL", "nomic-embed-text")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    api_key = api_key or os.getenv("OLLAMA_API_KEY")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(
        f"{base_url.rstrip('/')}/api/embed",
        headers=headers,
        json={"model": model, "input": texts},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama embed zwróciła {resp.status_code}: {resp.text[:500]}")

    embeddings = resp.json().get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise RuntimeError("Nieoczekiwana odpowiedź embeddingów z Ollamy")
    return embeddings


def embed_one(text: str, **kwargs) -> list[float]:
    return embed_texts([text], **kwargs)[0]
