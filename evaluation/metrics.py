"""Metryki ewaluacji — czyste funkcje, bez zależności od Django.

OCR: CER/WER w oparciu o odległość edycyjną Levenshteina (bez zewnętrznych
bibliotek — harness jest samowystarczalny). RAG: recall@k, hit@k, MRR.
"""

from __future__ import annotations

from typing import Sequence


def levenshtein(a: Sequence, b: Sequence) -> int:
    """Odległość edycyjna między dwiema sekwencjami (znaki albo słowa)."""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n

    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m]


def _normalize(text: str, *, lowercase: bool = True, collapse_ws: bool = True) -> str:
    if lowercase:
        text = text.lower()
    if collapse_ws:
        text = " ".join(text.split())
    return text.strip()


def cer(reference: str, hypothesis: str, *, normalize: bool = True) -> float:
    """Character Error Rate = edycje(znaki) / długość referencji (znaki)."""
    if normalize:
        reference = _normalize(reference)
        hypothesis = _normalize(hypothesis)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


def wer(reference: str, hypothesis: str, *, normalize: bool = True) -> float:
    """Word Error Rate = edycje(słowa) / liczba słów referencji."""
    if normalize:
        reference = _normalize(reference)
        hypothesis = _normalize(hypothesis)
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return levenshtein(ref_words, hyp_words) / len(ref_words)


def recall_at_k(retrieved: Sequence, relevant: Sequence, k: int) -> float:
    """Udział trafnych pozycji odnalezionych w pierwszych k wynikach."""
    rel = set(relevant)
    if not rel:
        return 0.0
    found = set(retrieved[:k]) & rel
    return len(found) / len(rel)


def hit_at_k(retrieved: Sequence, relevant: Sequence, k: int) -> float:
    """1.0 jeśli choć jedna trafna pozycja jest w pierwszych k wynikach."""
    return 1.0 if set(retrieved[:k]) & set(relevant) else 0.0


def reciprocal_rank(retrieved: Sequence, relevant: Sequence) -> float:
    """Odwrotność pozycji pierwszej trafnej pozycji (0.0 gdy brak)."""
    rel = set(relevant)
    for i, item in enumerate(retrieved, start=1):
        if item in rel:
            return 1.0 / i
    return 0.0
