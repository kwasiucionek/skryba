"""Wyszukiwanie hybrydowe nad fragmentami dokumentów.

Łączy dwa kanały:
- semantyczny: odległość cosinusowa embeddingu zapytania do embeddingów
  fragmentów (pgvector, indeks HNSW),
- leksykalny: pełnotekstowe wyszukiwanie Postgresa (SearchVector/SearchRank)
  z konfiguracją językową `SEARCH_CONFIG` (domyślnie 'polish' w Dockerze —
  ze stemmingiem hunspell; 'simple' jako bezpieczny fallback).

Wyniki łączymy metodą Reciprocal Rank Fusion (RRF) — sumujemy 1/(k+pozycja)
z obu rankingów. RRF nie wymaga normalizacji wyników i dobrze radzi sobie,
gdy oba kanały mają różne skale. Rozwiązuje typowy problem, w którym sama
semantyka gubi dokładne dopasowania (numery, sygnatury), a sam keyword gubi
parafrazy.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import transaction
from pgvector.django import CosineDistance

from rag import embed_one

from .models import Chunk

RRF_K = 60  # stała wygładzająca RRF (typowa wartość)


@dataclass
class SearchHit:
    chunk: Chunk
    score: float


def _rrf(rankings: list[list[int]]) -> dict[int, float]:
    """Reciprocal Rank Fusion: łączy listy id wg pozycji w rankingach."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position)
    return scores


def _fts_ids(base, query: str, config: str, limit: int) -> list[int]:
    """Pełnotekstowe id-ki dla danej konfiguracji językowej."""
    search_query = SearchQuery(query, config=config)
    return list(
        base.annotate(
            rank=SearchRank(SearchVector("text", config=config), search_query)
        )
        .filter(rank__gt=0)
        .order_by("-rank")
        .values_list("id", flat=True)[:limit]
    )


def _fts_ids_resilient(base, query: str, limit: int) -> list[int]:
    """Próbuje skonfigurowanej konfiguracji FTS; przy jej braku spada na 'simple'.

    Użycie savepointu (atomic) sprawia, że błąd nieistniejącej konfiguracji
    nie psuje bieżącej transakcji — po prostu ponawiamy z 'simple'.
    """
    config = settings.SEARCH_CONFIG
    try:
        with transaction.atomic():
            return _fts_ids(base, query, config, limit)
    except Exception:
        if config == "simple":
            return []
        try:
            with transaction.atomic():
                return _fts_ids(base, query, "simple", limit)
        except Exception:
            return []


def hybrid_search(user, query: str, *, top_k: int = 8, pool: int = 24) -> list[SearchHit]:
    """Zwraca najtrafniejsze fragmenty z dokumentów danego użytkownika."""
    query = query.strip()
    if not query:
        return []

    base = Chunk.objects.filter(document__owner=user)

    # Kanał semantyczny.
    query_embedding = embed_one(query)
    vector_ids = list(
        base.filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", query_embedding))
        .order_by("distance")
        .values_list("id", flat=True)[:pool]
    )

    # Kanał pełnotekstowy (ze stemmingiem, odporny na brak konfiguracji).
    fts_ids = _fts_ids_resilient(base, query, pool)

    fused = _rrf([vector_ids, fts_ids])
    if not fused:
        return []

    top_ids = sorted(fused, key=fused.get, reverse=True)[:top_k]
    chunks = {
        c.id: c
        for c in Chunk.objects.filter(id__in=top_ids).select_related("document")
    }
    return [SearchHit(chunk=chunks[i], score=fused[i]) for i in top_ids if i in chunks]
