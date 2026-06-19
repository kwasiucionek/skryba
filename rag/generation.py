"""Generowanie odpowiedzi na pytania w oparciu o znalezione fragmenty (RAG).

Model dostaje wyłącznie wyszukany kontekst i ma odpowiadać tylko na jego
podstawie, z odwołaniem do numerów źródeł. Jeśli kontekst nie zawiera
odpowiedzi, model ma to wprost powiedzieć — zamiast zmyślać.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

SYSTEM_PROMPT = (
    "Jesteś asystentem odpowiadającym na pytania na podstawie archiwum "
    "dokumentów użytkownika. Odpowiadaj wyłącznie na podstawie podanych "
    "fragmentów. Powołuj się na źródła w nawiasach kwadratowych, np. [1], [2]. "
    "Jeśli w kontekście nie ma odpowiedzi, napisz wprost, że nie znalazłeś "
    "jej w dokumentach. Nie zmyślaj. Odpowiadaj po polsku, zwięźle."
)


@dataclass
class Context:
    label: int           # numer źródła do cytowania, np. 1
    title: str
    page_number: int
    text: str


def _build_prompt(question: str, contexts: list[Context]) -> str:
    blocks = []
    for c in contexts:
        blocks.append(
            f"[{c.label}] (dokument: {c.title}, strona {c.page_number})\n{c.text}"
        )
    context_text = "\n\n".join(blocks) if blocks else "(brak dopasowanych fragmentów)"
    return (
        "Fragmenty z archiwum:\n\n"
        f"{context_text}\n\n"
        f"Pytanie: {question}\n\n"
        "Odpowiedź (z odwołaniami do numerów źródeł):"
    )


def answer_question(
    question: str,
    contexts: list[Context],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: int = 180,
) -> str:
    model = model or os.getenv("RAG_OLLAMA_MODEL", "gemma4:31b-cloud")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    api_key = api_key or os.getenv("OLLAMA_API_KEY")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.post(
        f"{base_url.rstrip('/')}/api/chat",
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _build_prompt(question, contexts)},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Ollama zwróciła {resp.status_code}: {resp.text[:500]}")
    return resp.json()["message"]["content"].strip()
