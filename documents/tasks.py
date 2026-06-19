"""Zadania w tle (django-q2).

Przepływ jest wieloetapowy i rozłączny — każdy etap niezależny, by błąd
jednego nie psuł pozostałych:
  run_ocr        -> OCR + searchable PDF, zleca ekstrakcję i indeksację
  run_extraction -> klasyfikacja i metadane (LLM)
  run_indexing   -> chunki + embeddingi do wyszukiwania semantycznego / RAG
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile
from types import SimpleNamespace

from django.core.files import File
from django_q.tasks import async_task

from extraction import FieldSpec, extract_custom_fields, extract_metadata
from ocr.pdf_output import build_searchable_pdf
from ocr.pipeline import ocr_file
from rag import chunk_pages, embed_texts

from .models import Chunk, CustomField, Document, Page, UserSettings

EMBED_BATCH = 32


def _parse_date(value: str | None) -> dt.date | None:
    """Parsuje datę z odpowiedzi LLM (ISO YYYY-MM-DD lub polskie DD.MM.YYYY)."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def run_ocr(document_id: int) -> None:
    """OCR dokumentu + generowanie searchable PDF. Wołane przez django-q2."""
    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return

    doc.status = Document.Status.PROCESSING
    doc.save(update_fields=["status", "updated_at"])

    try:
        result = ocr_file(doc.file.path, mode=doc.mode)

        # Pełne wypełnienie od nowa — usuwamy stare strony, by uniknąć duplikatów.
        doc.pages.all().delete()
        Page.objects.bulk_create(
            [
                Page(
                    document=doc,
                    page_number=p.page_number,
                    text=p.text,
                    source=p.source,
                    engine_name=p.engine_name or "",
                    confidence=p.confidence,
                )
                for p in result.pages
            ]
        )

        doc.full_text = result.full_text

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        try:
            build_searchable_pdf(doc.file.path, result, tmp_path)
            with open(tmp_path, "rb") as fh:
                pdf_name = (
                    f"{os.path.splitext(os.path.basename(doc.file.name))[0]}_ocr.pdf"
                )
                doc.searchable_pdf.save(pdf_name, File(fh), save=False)
        finally:
            os.unlink(tmp_path)

        doc.status = Document.Status.DONE
        doc.error_message = ""
        doc.save(
            update_fields=[
                "full_text", "searchable_pdf", "status",
                "error_message", "updated_at",
            ]
        )

        # Kolejne etapy jako niezależne zadania w kolejce.
        async_task("documents.tasks.run_extraction", doc.id)
        async_task("documents.tasks.run_indexing", doc.id)

    except Exception as exc:  # noqa: BLE001
        doc.status = Document.Status.FAILED
        doc.error_message = str(exc)
        doc.save(update_fields=["status", "error_message", "updated_at"])


def run_extraction(document_id: int) -> None:
    """Klasyfikacja i ekstrakcja metadanych z rozpoznanego tekstu (best-effort)."""
    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return

    if not doc.full_text.strip():
        return

    try:
        custom_prompt = None
        if doc.owner_id:
            us = UserSettings.objects.filter(user=doc.owner).first()
            if us and us.extraction_prompt.strip():
                custom_prompt = us.extraction_prompt.strip()
        meta = extract_metadata(doc.full_text, system_prompt=custom_prompt)
        doc.doc_type = meta.doc_type.value
        doc.doc_date = _parse_date(meta.doc_date)
        doc.doc_number = meta.doc_number or ""
        doc.counterparty = meta.counterparty or ""
        doc.amount = meta.total_amount
        doc.currency = meta.currency or ""
        doc.summary = meta.summary or ""
        metadata = meta.model_dump()
        # Pola użytkownika (best-effort) — nie wywalają standardowej ekstrakcji.
        specs = [
            FieldSpec(key=cf.key, prompt=cf.prompt, type=cf.field_type)
            for cf in CustomField.objects.filter(owner=doc.owner)
        ] if doc.owner_id else []
        if specs:
            try:
                metadata["custom"] = extract_custom_fields(doc.full_text, specs)
            except Exception:  # noqa: BLE001 — pola własne są opcjonalne
                metadata["custom"] = {}
        doc.metadata = metadata
        doc.extraction_error = ""
        doc.save(
            update_fields=[
                "doc_type", "doc_date", "doc_number", "counterparty",
                "amount", "currency", "summary", "metadata",
                "extraction_error", "updated_at",
            ]
        )
    except Exception as exc:  # noqa: BLE001
        doc.extraction_error = str(exc)
        doc.save(update_fields=["extraction_error", "updated_at"])


def run_indexing(document_id: int) -> None:
    """Dzieli tekst na fragmenty, liczy embeddingi i zapisuje do bazy wektorowej.

    Best-effort: błąd nie zmienia statusu dokumentu. Pełne wypełnienie od
    nowa — stare fragmenty kasujemy, by ponowna indeksacja nie dublowała.
    """
    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return

    pages = list(doc.pages.values_list("page_number", "text"))
    if not pages:
        return

    try:
        chunks = chunk_pages(pages)
        if not chunks:
            return

        # Embeddingi w paczkach, by nie przeładować jednego żądania.
        embeddings: list[list[float]] = []
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start:start + EMBED_BATCH]
            embeddings.extend(embed_texts([c.text for c in batch]))

        doc.chunks.all().delete()
        Chunk.objects.bulk_create(
            [
                Chunk(
                    document=doc,
                    page_number=c.page_number,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    embedding=emb,
                )
                for c, emb in zip(chunks, embeddings)
            ]
        )

        doc.indexed = True
        doc.indexing_error = ""
        doc.save(update_fields=["indexed", "indexing_error", "updated_at"])

    except Exception as exc:  # noqa: BLE001
        doc.indexing_error = str(exc)
        doc.save(update_fields=["indexing_error", "updated_at"])


def rebuild_searchable_pdf(document_id: int) -> None:
    """Odtwarza przeszukiwalny PDF po edycji rozpoznanego tekstu (best-effort).

    Warstwa tekstowa pobieranego PDF inaczej zostałaby nieaktualna po edycji.
    Strony cyfrowe (source='text_layer') i tak kopiowane są z oryginału bez zmian.
    """
    try:
        doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        return
    if not doc.file or not doc.pages.exists():
        return

    try:
        result = SimpleNamespace(pages=[
            SimpleNamespace(page_number=p.page_number, source=p.source, text=p.text)
            for p in doc.pages.all().order_by("page_number")
        ])
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.pdf")
            build_searchable_pdf(doc.file.path, result, out_path)
            pdf_name = (
                f"{os.path.splitext(os.path.basename(doc.file.name))[0]}_ocr.pdf"
            )
            if doc.searchable_pdf:
                doc.searchable_pdf.delete(save=False)
            with open(out_path, "rb") as fh:
                doc.searchable_pdf.save(pdf_name, File(fh), save=False)
        doc.save(update_fields=["searchable_pdf", "updated_at"])
    except Exception:  # noqa: BLE001 — regeneracja jest best-effort
        pass
