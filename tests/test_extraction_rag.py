"""Testy ekstrakcji metadanych i rdzenia RAG (bez bazy)."""

from __future__ import annotations

import json
import types

import pytest


class _Resp:
    status_code = 200

    def __init__(self, content):
        self._c = content

    def json(self):
        return {"message": {"content": self._c}}


_SAMPLE = {
    "doc_type": "faktura",
    "doc_date": "2026-03-14",
    "doc_number": "FV/2026/03/0042",
    "counterparty": "Neurosoft Sp. z o.o.",
    "total_amount": 1234.56,
    "currency": "PLN",
    "summary": "Faktura za usługi.",
    "tags": ["faktura"],
    "confidence": 0.9,
}


# --- Ekstrakcja ---

def test_extraction_structured_output(monkeypatch):
    from extraction import extract_metadata
    from extraction import extractor

    monkeypatch.setattr(
        extractor, "requests",
        types.SimpleNamespace(post=lambda *a, **k: _Resp(json.dumps(_SAMPLE))),
    )
    meta = extract_metadata("Faktura ...")
    assert meta.doc_type.value == "faktura"
    assert meta.total_amount == 1234.56
    assert meta.tags == ["faktura"]


def test_extraction_fallback_on_bad_first_response(monkeypatch):
    """Pierwsza próba (schemat) zwraca śmieci -> fallback na format=json."""
    from extraction import extract_metadata
    from extraction import extractor

    calls = {"n": 0}

    def post(*a, **k):
        calls["n"] += 1
        return _Resp("nie-json") if calls["n"] == 1 else _Resp(json.dumps(_SAMPLE))

    monkeypatch.setattr(extractor, "requests", types.SimpleNamespace(post=post))
    meta = extract_metadata("x")
    assert meta.doc_number == "FV/2026/03/0042"
    assert calls["n"] == 2


def test_extraction_coerces_amount_string(monkeypatch):
    from extraction import extract_metadata
    from extraction import extractor

    partial = {"doc_type": "pismo_sadowe", "total_amount": "999.9", "summary": "x"}
    monkeypatch.setattr(
        extractor, "requests",
        types.SimpleNamespace(post=lambda *a, **k: _Resp(json.dumps(partial))),
    )
    meta = extract_metadata("x")
    assert meta.total_amount == 999.9
    assert meta.counterparty is None
    assert meta.tags == []


# --- RAG: chunking ---

def test_chunking_preserves_pages_and_global_index():
    from rag import chunk_pages

    pages = [(1, "Ala ma kota. " * 200), (2, "Krótki tekst.")]
    chunks = chunk_pages(pages, max_chars=300, overlap=50)
    assert len(chunks) > 2
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert any(c.page_number == 2 for c in chunks)


def test_chunking_short_text_single_chunk():
    from rag.chunking import _split_page

    assert _split_page("krótki", 300, 50) == ["krótki"]


# --- RAG: embeddingi ---

def test_embeddings_batch(monkeypatch):
    from rag import embeddings as E

    monkeypatch.setattr(
        E, "requests",
        types.SimpleNamespace(post=lambda *a, **k: types.SimpleNamespace(
            status_code=200,
            json=lambda: {"embeddings": [[0.1, 0.2, 0.3]] * len(k["json"]["input"])},
        )),
    )
    vecs = E.embed_texts(["a", "b", "c"])
    assert len(vecs) == 3 and len(vecs[0]) == 3


def test_embeddings_empty_returns_empty():
    from rag import embed_texts

    assert embed_texts([]) == []


# --- RAG: generacja ---

def test_generation_uses_context(monkeypatch):
    from rag import answer_question, Context
    from rag import generation as G

    monkeypatch.setattr(
        G, "requests",
        types.SimpleNamespace(post=lambda *a, **k: _Resp("Termin to 14 dni [1].")),
    )
    ans = answer_question("Jaki termin?", [Context(1, "W.pdf", 1, "termin 14 dni")])
    assert "[1]" in ans


# --- Wyszukiwanie: fuzja RRF ---

def test_rrf_fusion_ranking():
    from documents.search import _rrf

    # id=5 na 1. miejscu w obu rankingach -> najwyższy wynik
    scores = _rrf([[5, 3, 9], [5, 9, 3]])
    top = max(scores, key=scores.get)
    assert top == 5


# --- Ekstrakcja: odporne parsowanie odpowiedzi modelu ---

_VALID = '{"doc_type":"faktura","total_amount":100.0,"summary":"x","tags":[]}'


def _run_extraction(monkeypatch, content):
    from extraction import extract_metadata
    from extraction import extractor

    monkeypatch.setattr(
        extractor, "requests",
        types.SimpleNamespace(post=lambda *a, **k: _Resp(content)),
    )
    return extract_metadata("tekst")


def test_extraction_strips_think_block(monkeypatch):
    """Modele reasoning wstawiają <think>...</think> przed JSON."""
    meta = _run_extraction(monkeypatch, "<think>to faktura</think>\n" + _VALID)
    assert meta.doc_type.value == "faktura"
    assert meta.total_amount == 100.0


def test_extraction_strips_code_fences(monkeypatch):
    meta = _run_extraction(monkeypatch, "```json\n" + _VALID + "\n```")
    assert meta.doc_type.value == "faktura"


def test_extraction_handles_prose_around_json(monkeypatch):
    meta = _run_extraction(monkeypatch, "Oto dane:\n" + _VALID + "\nDziękuję.")
    assert meta.doc_type.value == "faktura"


def test_extraction_empty_response_raises_clear_error(monkeypatch):
    """Pusta odpowiedź -> czytelny błąd z nazwą modelu, nie 'Expecting value'."""
    monkeypatch.setenv("EXTRACT_OLLAMA_MODEL", "jakis-model:cloud")
    with pytest.raises(RuntimeError) as exc:
        _run_extraction(monkeypatch, "")
    assert "jakis-model:cloud" in str(exc.value)
    assert "Expecting value" not in str(exc.value)


def test_extraction_unwraps_single_wrapper_key(monkeypatch):
    """Model zagnieżdża dane w jednym kluczu -> parser rozpakowuje wnętrze."""
    wrapped = json.dumps({"dokument_metadane": {
        "doc_type": "faktura", "doc_date": "2021-06-01",
        "total_amount": 50.0, "summary": "x", "tags": [],
    }})
    meta = _run_extraction(monkeypatch, wrapped)
    assert meta.doc_type.value == "faktura"
    assert meta.doc_date == "2021-06-01"
    assert meta.total_amount == 50.0


def test_prompt_communicates_exact_keys():
    """Prompt musi zawierać dokładne nazwy kluczy i opcje typu dokumentu."""
    from extraction.prompts import build_user_prompt
    from extraction.schemas import DocumentType

    p = build_user_prompt("dokument")
    for key in ["doc_type", "doc_date", "counterparty", "total_amount", "summary", "tags"]:
        assert key in p
    for t in DocumentType:
        assert t.value in p


def test_extract_metadata_uses_custom_system_prompt(monkeypatch):
    from extraction import extract_metadata
    from extraction import extractor

    captured = {}

    def post(*a, **k):
        captured["payload"] = k.get("json")
        return _Resp(json.dumps(_SAMPLE))

    monkeypatch.setattr(extractor, "requests", types.SimpleNamespace(post=post))
    extract_metadata("x", system_prompt="NIESTANDARDOWY PROMPT")
    assert captured["payload"]["messages"][0]["content"] == "NIESTANDARDOWY PROMPT"
