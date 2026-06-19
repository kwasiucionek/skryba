"""Harness ewaluacyjny dla Skryby.

Czyste metryki (``metrics``) i wczytywanie zbiorów (``datasets``) są
niezależne od Django — można je testować w izolacji. Właściwe przebiegi
uruchamiają komendy zarządzania ``eval_ocr`` i ``eval_rag``.
"""

from .datasets import OcrCase, RagCase, load_ocr_cases, load_rag_cases
from .metrics import (
    cer,
    hit_at_k,
    levenshtein,
    recall_at_k,
    reciprocal_rank,
    wer,
)

__all__ = [
    "OcrCase",
    "RagCase",
    "load_ocr_cases",
    "load_rag_cases",
    "cer",
    "wer",
    "levenshtein",
    "recall_at_k",
    "hit_at_k",
    "reciprocal_rank",
]
