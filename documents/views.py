"""Widoki archiwum."""

from __future__ import annotations

import csv
import io
import os
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django_q.tasks import async_task

from rag import Context, answer_question

from .models import CustomField, Document, UserSettings
from .search import hybrid_search


def _rebuild_full_text(doc: Document) -> str:
    """Składa full_text z tekstów stron — w tym samym formacie co pipeline OCR."""
    return "\n\n".join(
        f"--- Strona {p.page_number} ---\n{p.text}"
        for p in doc.pages.all()
    )


def _parse_date(value: str):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_decimal(value: str):
    try:
        return Decimal(value) if value else None
    except (InvalidOperation, ValueError):
        return None


def _collect_tags(docs) -> list[str]:
    """Zbiera unikalne tagi z metadanych dokumentów użytkownika."""
    tags: set[str] = set()
    for meta in docs.values_list("metadata", flat=True):
        if isinstance(meta, dict):
            for t in meta.get("tags", []):
                if isinstance(t, str):
                    tags.add(t)
    return sorted(tags)


def _query_documents(user, g):
    """Wspólna logika filtrowania dla listy i eksportu.

    Zwraca: (przefiltrowane dokumenty, wszystkie dokumenty użytkownika,
             surowe wartości filtrów do formularza, czy filtr aktywny).
    """
    owned = Document.objects.filter(owner=user)
    docs = owned

    doc_type = g.get("type", "")
    query = g.get("q", "").strip()
    date_from = _parse_date(g.get("date_from", ""))
    date_to = _parse_date(g.get("date_to", ""))
    amount_min = _parse_decimal(g.get("amount_min", ""))
    amount_max = _parse_decimal(g.get("amount_max", ""))
    tag = g.get("tag", "").strip()

    if doc_type:
        docs = docs.filter(doc_type=doc_type)
    if query:
        docs = docs.filter(
            Q(title__icontains=query)
            | Q(full_text__icontains=query)
            | Q(counterparty__icontains=query)
            | Q(doc_number__icontains=query)
            | Q(summary__icontains=query)
        )
    if date_from:
        docs = docs.filter(doc_date__gte=date_from)
    if date_to:
        docs = docs.filter(doc_date__lte=date_to)
    if amount_min is not None:
        docs = docs.filter(amount__gte=amount_min)
    if amount_max is not None:
        docs = docs.filter(amount__lte=amount_max)
    if tag:
        docs = docs.filter(metadata__tags__contains=[tag])

    has_filters = any([
        doc_type, query, date_from, date_to,
        amount_min is not None, amount_max is not None, tag,
    ])
    f = {
        "q": query, "type": doc_type,
        "date_from": g.get("date_from", ""), "date_to": g.get("date_to", ""),
        "amount_min": g.get("amount_min", ""), "amount_max": g.get("amount_max", ""),
        "tag": tag,
    }
    return docs, owned, f, has_filters


def _documents_csv(docs, custom_fields=None) -> str:
    """Buduje CSV z metadanych dokumentów (nagłówek + wiersze).

    ``custom_fields`` to lista (klucz, etykieta) — dokładana jako dodatkowe
    kolumny z wartościami z ``Document.metadata['custom']``.
    """
    custom_fields = custom_fields or []
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Tytuł", "Typ", "Data", "Numer", "Kontrahent",
            "Kwota", "Waluta", "Tagi", "Streszczenie", "Status", "Dodano",
        ]
        + [name for _key, name in custom_fields]
    )
    for d in docs:
        row = [
            d.title,
            d.get_doc_type_display() if d.doc_type else "",
            d.doc_date.isoformat() if d.doc_date else "",
            d.doc_number,
            d.counterparty,
            "" if d.amount is None else f"{d.amount}",
            d.currency,
            ", ".join(d.tags),
            " ".join((d.summary or "").split()),
            d.get_status_display(),
            d.created_at.strftime("%Y-%m-%d %H:%M"),
        ]
        custom = d.custom
        for key, _name in custom_fields:
            val = custom.get(key)
            row.append("" if val is None else str(val))
        writer.writerow(row)
    return buf.getvalue()


@login_required
def document_list(request):
    docs, owned, f, has_filters = _query_documents(request.user, request.GET)
    context = {
        "documents": docs,
        "count": docs.count(),
        "doc_types": Document.DocType.choices,
        "available_tags": _collect_tags(owned),
        "has_filters": has_filters,
        "f": f,
    }
    return render(request, "documents/list.html", context)


@login_required
def export_csv(request):
    """Eksport metadanych (z aktywnymi filtrami) do CSV."""
    docs, *_ = _query_documents(request.user, request.GET)
    custom = [(c.key, c.name) for c in request.user.custom_fields.all()]
    stamp = timezone.now().strftime("%Y%m%d")
    # BOM, aby Excel poprawnie odczytał polskie znaki w UTF-8.
    response = HttpResponse("\ufeff" + _documents_csv(docs, custom), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="skryba-eksport-{stamp}.csv"'
    return response


@login_required
def export_zip(request):
    """Eksport całego (przefiltrowanego) archiwum: metadane CSV + oryginalne pliki."""
    docs = list(_query_documents(request.user, request.GET)[0])
    custom = [(c.key, c.name) for c in request.user.custom_fields.all()]
    stamp = timezone.now().strftime("%Y%m%d")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadane.csv", "\ufeff" + _documents_csv(docs, custom))
        for d in docs:
            if d.file and os.path.exists(d.file.path):
                arcname = f"pliki/{d.id}_{os.path.basename(d.file.name)}"
                zf.write(d.file.path, arcname)

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="skryba-archiwum-{stamp}.zip"'
    return response


@login_required
def document_upload(request):
    if request.method == "POST":
        files = request.FILES.getlist("files")
        if not files:
            messages.error(request, "Wybierz przynajmniej jeden plik.")
            return redirect("documents:upload")

        mode = request.POST.get("mode", Document.Mode.FAST)
        if mode not in dict(Document.Mode.choices):
            mode = Document.Mode.FAST

        # Tytuł stosujemy tylko przy pojedynczym pliku; przy wielu — nazwy plików.
        title_override = request.POST.get("title", "").strip()
        single = len(files) == 1

        created_ids = []
        for upload in files:
            title = title_override if (single and title_override) else upload.name
            doc = Document.objects.create(
                owner=request.user, title=title, file=upload, mode=mode,
            )
            async_task("documents.tasks.run_ocr", doc.id)
            created_ids.append(doc.id)

        if len(created_ids) == 1:
            return redirect("documents:detail", pk=created_ids[0])

        messages.success(
            request, f"Dodano {len(created_ids)} dokumentów. Trwa przetwarzanie."
        )
        return redirect("documents:list")

    return render(request, "documents/upload.html")


@login_required
def document_detail(request, pk):
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    labels = {c.key: c.name for c in request.user.custom_fields.all()}
    custom_rows = [
        {"label": labels.get(k, k), "value": v}
        for k, v in doc.custom.items()
        if v not in (None, "")
    ]
    return render(
        request, "documents/detail.html",
        {"document": doc, "custom_rows": custom_rows},
    )


@login_required
def document_status(request, pk):
    """Mały fragment HTML ze statusem — do pollingu HTMX."""
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    return render(request, "documents/_status.html", {"document": doc})


@login_required
def document_edit(request, pk):
    """Edycja rozpoznanego tekstu (per strona). Po zapisie przeindeksowuje RAG."""
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    pages = list(doc.pages.all())

    if request.method == "POST":
        for page in pages:
            new_text = request.POST.get(f"page_{page.id}")
            if new_text is not None and new_text != page.text:
                page.text = new_text
                page.save(update_fields=["text"])

        doc.full_text = _rebuild_full_text(doc)
        doc.save(update_fields=["full_text", "updated_at"])
        async_task("documents.tasks.run_indexing", doc.id)
        async_task("documents.tasks.rebuild_searchable_pdf", doc.id)
        messages.success(request, "Zapisano tekst. Trwa ponowne indeksowanie i odświeżanie PDF.")
        return redirect("documents:detail", pk=doc.pk)

    return render(request, "documents/edit.html", {"document": doc, "pages": pages})


@login_required
@require_POST
def document_reprocess(request, pk, step):
    """Ponowne uruchomienie etapu przetwarzania: ocr | extraction | indexing."""
    doc = get_object_or_404(Document, pk=pk, owner=request.user)

    if step == "ocr":
        doc.status = Document.Status.PENDING
        doc.error_message = ""
        doc.save(update_fields=["status", "error_message", "updated_at"])
        async_task("documents.tasks.run_ocr", doc.id)
        messages.info(
            request,
            "Zlecono ponowny OCR. Nadpisze on obecny tekst, metadane i indeks RAG.",
        )

    elif step == "extraction":
        if not doc.full_text.strip():
            messages.error(request, "Brak rozpoznanego tekstu — najpierw uruchom OCR.")
        else:
            doc.extraction_error = ""
            doc.save(update_fields=["extraction_error", "updated_at"])
            async_task("documents.tasks.run_extraction", doc.id)
            messages.info(request, "Zlecono ponowną ekstrakcję metadanych.")

    elif step == "indexing":
        if not doc.pages.exists():
            messages.error(request, "Brak stron — najpierw uruchom OCR.")
        else:
            doc.indexed = False
            doc.indexing_error = ""
            doc.save(update_fields=["indexed", "indexing_error", "updated_at"])
            async_task("documents.tasks.run_indexing", doc.id)
            messages.info(request, "Zlecono ponowne indeksowanie (RAG).")

    else:
        messages.error(request, "Nieznana operacja.")

    return redirect("documents:detail", pk=doc.pk)


@login_required
@require_POST
def document_delete(request, pk):
    """Usuwa dokument wraz z plikami z dysku (rekordy stron/chunków kaskadowo)."""
    doc = get_object_or_404(Document, pk=pk, owner=request.user)

    if doc.file:
        doc.file.delete(save=False)
    if doc.searchable_pdf:
        doc.searchable_pdf.delete(save=False)

    doc.delete()
    messages.success(request, "Dokument został usunięty.")
    return redirect("documents:list")


@login_required
def user_settings(request):
    """Ustawienia użytkownika — m.in. własny prompt ekstrakcji."""
    cfg, _ = UserSettings.objects.get_or_create(user=request.user)
    if request.method == "POST":
        cfg.extraction_prompt = request.POST.get("extraction_prompt", "").strip()
        cfg.save(update_fields=["extraction_prompt", "updated_at"])
        messages.success(
            request,
            "Zapisano ustawienia. Użyj „Ponów metadane” na dokumentach, "
            "aby zastosować zmianę.",
        )
        return redirect("documents:settings")

    from extraction.prompts import SYSTEM_PROMPT
    return render(
        request, "documents/settings.html",
        {"cfg": cfg, "default_prompt": SYSTEM_PROMPT},
    )


@login_required
def custom_fields(request):
    """Zarządzanie polami użytkownika: lista + dodawanie."""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        prompt = request.POST.get("prompt", "").strip()
        ftype = request.POST.get("field_type", "text")
        if ftype not in dict(CustomField.FieldType.choices):
            ftype = "text"
        if not name or not prompt:
            messages.error(request, "Podaj nazwę pola i prompt.")
        else:
            key = slugify(name)
            if not key:
                messages.error(request, "Nazwa musi zawierać znaki alfanumeryczne.")
            else:
                try:
                    with transaction.atomic():
                        CustomField.objects.create(
                            owner=request.user, name=name, key=key,
                            prompt=prompt, field_type=ftype,
                        )
                    messages.success(
                        request,
                        f"Dodano pole „{name}”. Użyj „Ponów metadane” na dokumentach, "
                        "aby je wypełnić.",
                    )
                except IntegrityError:
                    messages.error(request, f"Pole o kluczu „{key}” już istnieje.")
        return redirect("documents:custom_fields")

    return render(
        request, "documents/fields.html",
        {
            "fields": request.user.custom_fields.all(),
            "field_types": CustomField.FieldType.choices,
        },
    )


@login_required
@require_POST
def custom_field_delete(request, pk):
    field = get_object_or_404(CustomField, pk=pk, owner=request.user)
    name = field.name
    field.delete()
    messages.success(request, f"Usunięto pole „{name}”.")
    return redirect("documents:custom_fields")


@login_required
def ask(request):
    """RAG: pytanie do całego archiwum użytkownika."""
    question = request.GET.get("q", "").strip()
    answer = None
    sources = []

    if question:
        hits = hybrid_search(request.user, question)
        if hits:
            contexts = [
                Context(
                    label=i + 1,
                    title=h.chunk.document.title,
                    page_number=h.chunk.page_number,
                    text=h.chunk.text,
                )
                for i, h in enumerate(hits)
            ]
            answer = answer_question(question, contexts)
            sources = [
                {
                    "label": c.label,
                    "title": c.title,
                    "page": c.page_number,
                    "doc_id": h.chunk.document_id,
                }
                for c, h in zip(contexts, hits)
            ]
        else:
            answer = "Nie znalazłem w archiwum fragmentów pasujących do pytania."

    return render(
        request,
        "documents/ask.html",
        {"question": question, "answer": answer, "sources": sources},
    )
