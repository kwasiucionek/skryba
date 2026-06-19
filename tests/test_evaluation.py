"""Testy harnessa ewaluacyjnego: metryki (czyste) i komendy (smoke)."""

from __future__ import annotations

import json
import types
from io import StringIO

import pytest
from django.core.management import call_command

from evaluation import (
    cer,
    hit_at_k,
    levenshtein,
    load_ocr_cases,
    load_rag_cases,
    recall_at_k,
    reciprocal_rank,
    wer,
)


# --- Metryki: odległość edycyjna i CER/WER ---

def test_levenshtein_basic():
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("abc", "abd") == 1
    assert levenshtein("abc", "ab") == 1
    assert levenshtein("", "abc") == 3


def test_cer_exact_and_partial():
    assert cer("kot", "kot") == 0.0
    assert cer("kot", "ko") == pytest.approx(1 / 3)
    assert cer("", "") == 0.0
    assert cer("", "x") == 1.0


def test_cer_normalization():
    # różnice wielkości liter i białych znaków znikają po normalizacji
    assert cer("KOT  Ala", "kot ala") == 0.0
    assert cer("KOT", "kot", normalize=False) > 0.0


def test_wer_word_level():
    assert wer("ala ma kota", "ala ma kota") == 0.0
    assert wer("ala ma kota", "ala ma psa") == pytest.approx(1 / 3)


# --- Metryki: retrieval ---

def test_recall_and_hit_at_k():
    assert recall_at_k(["a", "b", "c"], ["b"], 2) == 1.0
    assert recall_at_k(["a", "b", "c"], ["x"], 2) == 0.0
    assert hit_at_k(["a", "b", "c"], ["b"], 2) == 1.0
    assert hit_at_k(["a", "b", "c"], ["c"], 2) == 0.0  # c poza top2


def test_reciprocal_rank():
    assert reciprocal_rank(["a", "b", "c"], ["b"]) == pytest.approx(1 / 2)
    assert reciprocal_rank(["a", "b", "c"], ["a"]) == 1.0
    assert reciprocal_rank(["a", "b", "c"], ["z"]) == 0.0


# --- Wczytywanie zbiorów ---

def test_load_rag_cases(tmp_path):
    p = tmp_path / "rag.json"
    p.write_text(json.dumps([
        {"question": "Q1", "relevant_titles": ["Doc A"], "expected_substrings": ["x"]},
        {"question": "Q2", "relevant_titles": ["Doc B"]},
    ]), encoding="utf-8")
    cases = load_rag_cases(p)
    assert len(cases) == 2
    assert cases[0].expected_substrings == ["x"]
    assert cases[1].expected_substrings == []


def test_load_ocr_cases_with_inline_and_file(tmp_path):
    (tmp_path / "gt.txt").write_text("treść wzorcowa", encoding="utf-8")
    p = tmp_path / "ocr.json"
    p.write_text(json.dumps([
        {"file": "a.png", "ground_truth": "wprost", "mode": "fast"},
        {"file": "b.png", "ground_truth_file": "gt.txt", "mode": "quality"},
    ]), encoding="utf-8")
    cases = load_ocr_cases(p)
    assert cases[0].ground_truth == "wprost"
    assert cases[1].ground_truth == "treść wzorcowa"
    assert cases[1].path.endswith("b.png")  # ścieżka rozwinięta względem zbioru


# --- Smoke: komenda eval_ocr (z mockiem OCR) ---

def test_eval_ocr_command(tmp_path, monkeypatch):
    p = tmp_path / "ocr.json"
    p.write_text(json.dumps([
        {"file": "x.png", "ground_truth": "ala ma kota", "mode": "fast"},
    ]), encoding="utf-8")

    fake_result = types.SimpleNamespace(
        pages=[types.SimpleNamespace(text="ala ma kota")]
    )
    monkeypatch.setattr(
        "documents.management.commands.eval_ocr.ocr_file",
        lambda path, **k: fake_result,
    )
    out = StringIO()
    call_command("eval_ocr", str(p), stdout=out)
    text = out.getvalue()
    assert "CER=0.000" in text and "WER=0.000" in text
    assert "Średnio" in text


# --- Smoke: komenda eval_rag (z mockiem wyszukiwania) ---

@pytest.mark.django_db
def test_eval_rag_command(tmp_path, monkeypatch):
    from django.contrib.auth import get_user_model
    get_user_model().objects.create_user("evaluser", password="x")

    p = tmp_path / "rag.json"
    p.write_text(json.dumps([
        {"question": "Pytanie?", "relevant_titles": ["Dokument A"]},
    ]), encoding="utf-8")

    chunk = types.SimpleNamespace(
        document=types.SimpleNamespace(title="Dokument A"),
        page_number=1, text="fragment",
    )
    hit = types.SimpleNamespace(chunk=chunk, score=1.0)
    monkeypatch.setattr(
        "documents.management.commands.eval_rag.hybrid_search",
        lambda user, q, **k: [hit],
    )
    out = StringIO()
    call_command("eval_rag", str(p), "--user", "evaluser", stdout=out)
    text = out.getvalue()
    assert "hit@8=1" in text
    assert "MRR=1.00" in text
