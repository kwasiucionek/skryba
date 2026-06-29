"""Testy widoków archiwum (wymagają PostgreSQL z pgvector).

Kolejka (async_task) oraz wywołania LLM/embeddingów są mockowane, aby
testy nie zależały od działającego workera ani Ollamy.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import Client

from documents.models import Document, Page

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("tester", password="x")


@pytest.fixture
def client_logged(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture
def captured_tasks(monkeypatch):
    """Przechwytuje zlecenia do kolejki zamiast je wykonywać."""
    calls = []
    monkeypatch.setattr(
        "documents.views.async_task", lambda name, *a, **k: calls.append(name)
    )
    return calls


def _make_done_doc(user, text="rozpoznany tekst"):
    doc = Document.objects.create(
        owner=user, title="dok.pdf", status=Document.Status.DONE, full_text=text
    )
    Page.objects.create(document=doc, page_number=1, text=text)
    return doc


def test_upload_creates_document_and_enqueues_ocr(client_logged, captured_tasks, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("skan.png", b"obraz", content_type="image/png")
    resp = client_logged.post("/upload/", {"files": upload, "mode": "quality"})
    assert resp.status_code == 302
    doc = Document.objects.get()
    assert doc.mode == "quality"
    assert "documents.tasks.run_ocr" in captured_tasks


def test_detail_shows_reprocess_actions(client_logged, user):
    doc = _make_done_doc(user)
    html = client_logged.get(f"/{doc.id}/").content.decode()
    assert "Ponów OCR" in html
    assert "Przeindeksuj" in html


def test_edit_saves_text_and_reindexes(client_logged, user, captured_tasks):
    doc = _make_done_doc(user, text="błędny tekst")
    page = doc.pages.get()
    resp = client_logged.post(f"/{doc.id}/edit/", {f"page_{page.id}": "poprawiony tekst"})
    assert resp.status_code == 302
    page.refresh_from_db()
    doc.refresh_from_db()
    assert page.text == "poprawiony tekst"
    assert "poprawiony" in doc.full_text
    assert "--- Strona 1 ---" in doc.full_text
    assert "documents.tasks.run_indexing" in captured_tasks


def test_delete_removes_document_files_and_cascade(client_logged, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    doc = _make_done_doc(user)
    doc.file.save("plik.txt", ContentFile(b"x"), save=True)
    doc.searchable_pdf.save("plik_ocr.pdf", ContentFile(b"x"), save=True)
    fpath, spath = doc.file.path, doc.searchable_pdf.path
    did = doc.id

    resp = client_logged.post(f"/{did}/delete/")
    assert resp.status_code == 302
    assert not Document.objects.filter(id=did).exists()
    assert Page.objects.filter(document_id=did).count() == 0
    import os
    assert not os.path.exists(fpath)
    assert not os.path.exists(spath)


def test_delete_requires_post(client_logged, user):
    doc = _make_done_doc(user)
    assert client_logged.get(f"/{doc.id}/delete/").status_code == 405


@pytest.mark.parametrize("step,task", [
    ("ocr", "documents.tasks.run_ocr"),
    ("extraction", "documents.tasks.run_extraction"),
    ("indexing", "documents.tasks.run_indexing"),
])
def test_reprocess_enqueues_correct_task(client_logged, user, captured_tasks, step, task):
    doc = _make_done_doc(user)
    resp = client_logged.post(f"/{doc.id}/reprocess/{step}/")
    assert resp.status_code == 302
    assert task in captured_tasks


def test_reprocess_ocr_sets_pending(client_logged, user, captured_tasks):
    doc = _make_done_doc(user)
    client_logged.post(f"/{doc.id}/reprocess/ocr/")
    doc.refresh_from_db()
    assert doc.status == Document.Status.PENDING


def test_reprocess_indexing_resets_indexed(client_logged, user, captured_tasks):
    doc = _make_done_doc(user)
    doc.indexed = True
    doc.save(update_fields=["indexed"])
    client_logged.post(f"/{doc.id}/reprocess/indexing/")
    doc.refresh_from_db()
    assert doc.indexed is False


def test_other_user_cannot_access(user):
    doc = _make_done_doc(user)
    other = get_user_model().objects.create_user("obcy", password="x")
    c = Client()
    c.force_login(other)
    assert c.get(f"/{doc.id}/").status_code == 404
    assert c.post(f"/{doc.id}/delete/").status_code == 404
    assert c.post(f"/{doc.id}/reprocess/ocr/").status_code == 404


def test_ask_renders_answer_and_sources(client_logged, user, monkeypatch):
    doc = _make_done_doc(user)
    from documents.search import SearchHit
    from documents.models import Chunk

    chunk = Chunk(document=doc, page_number=1, chunk_index=0, text="termin 14 dni")
    monkeypatch.setattr(
        "documents.views.hybrid_search",
        lambda u, q, **k: [SearchHit(chunk=chunk, score=1.0)],
    )
    monkeypatch.setattr(
        "documents.views.answer_question",
        lambda q, contexts, **k: "Termin to 14 dni [1].",
    )
    html = client_logged.get("/ask/", {"q": "jaki termin?"}).content.decode()
    assert "Termin to 14 dni" in html
    assert "dok.pdf" in html  # źródło


def test_ask_empty_query(client_logged, user):
    assert client_logged.get("/ask/").status_code == 200


# --- Filtry listy ---

import datetime as _dt
import re as _re


def _count_on_list(client, params):
    html = client.get("/", params).content.decode()
    m = _re.search(r"Znaleziono: (\d+)", html)
    return int(m.group(1))


@pytest.fixture
def filter_docs(user):
    def mk(title, **kw):
        return Document.objects.create(owner=user, title=title, status="done", **kw)
    mk("Faktura A", doc_type="faktura", doc_date=_dt.date(2026, 3, 10),
       amount=100, currency="PLN", metadata={"tags": ["it", "marzec"]})
    mk("Faktura B", doc_type="faktura", doc_date=_dt.date(2026, 5, 20),
       amount=2500, currency="PLN", metadata={"tags": ["sprzet"]})
    mk("Umowa C", doc_type="umowa", doc_date=_dt.date(2025, 12, 1),
       amount=None, metadata={"tags": ["it"]})
    return user


def test_filter_by_type(client_logged, filter_docs):
    assert _count_on_list(client_logged, {"type": "faktura"}) == 2


def test_filter_by_date_range(client_logged, filter_docs):
    assert _count_on_list(client_logged, {"date_from": "2026-01-01"}) == 2
    assert _count_on_list(client_logged, {"date_to": "2026-04-01"}) == 2


def test_filter_by_amount_range(client_logged, filter_docs):
    assert _count_on_list(client_logged, {"amount_min": "1000"}) == 1
    assert _count_on_list(client_logged, {"amount_min": "50", "amount_max": "500"}) == 1


def test_filter_by_tag(client_logged, filter_docs):
    assert _count_on_list(client_logged, {"tag": "it"}) == 2
    assert _count_on_list(client_logged, {"tag": "sprzet"}) == 1


def test_filter_combined(client_logged, filter_docs):
    assert _count_on_list(client_logged, {"type": "faktura", "tag": "it"}) == 1


def test_filter_available_tags_listed(client_logged, filter_docs):
    html = client_logged.get("/").content.decode()
    assert all(t in html for t in ["it", "marzec", "sprzet"])


def test_filter_invalid_values_ignored(client_logged, filter_docs):
    # błędna data/kwota nie wywala widoku, po prostu są ignorowane
    assert _count_on_list(client_logged, {"date_from": "zła-data", "amount_min": "abc"}) == 3


# --- Eksport CSV / ZIP ---

import io as _io
import zipfile as _zipfile


def test_export_csv_contents_and_bom(client_logged, filter_docs):
    r = client_logged.get("/export/csv/")
    assert "text/csv" in r["Content-Type"]
    body = r.content.decode("utf-8")
    assert body.startswith("\ufeff")  # BOM dla Excela
    assert "Tytuł,Typ,Data" in body
    assert "Faktura A" in body and "Umowa C" in body
    assert "skryba-eksport-" in r["Content-Disposition"]


def test_export_csv_respects_filters(client_logged, filter_docs):
    body = client_logged.get("/export/csv/?type=faktura").content.decode("utf-8")
    assert "Faktura A" in body and "Faktura B" in body
    assert "Umowa C" not in body


def test_export_csv_flattens_summary(client_logged, user):
    Document.objects.create(owner=user, title="Wielolinijka", status="done",
                            summary="Pierwsza\nDruga")
    body = client_logged.get("/export/csv/").content.decode("utf-8")
    assert "Pierwsza Druga" in body


def test_export_zip_includes_metadata_and_files(client_logged, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.base import ContentFile
    doc = Document.objects.create(owner=user, title="Z plikiem", status="done")
    doc.file.save("akta.txt", ContentFile(b"tresc"), save=True)

    r = client_logged.get("/export/zip/")
    assert r["Content-Type"] == "application/zip"
    zf = _zipfile.ZipFile(_io.BytesIO(r.content))
    names = zf.namelist()
    assert "metadane.csv" in names
    assert any(n.startswith("pliki/") and "akta.txt" in n for n in names)


def test_export_isolation(user):
    Document.objects.create(owner=user, title="Tajne", status="done")
    other = get_user_model().objects.create_user("intruz", password="x")
    c = Client()
    c.force_login(other)
    body = c.get("/export/csv/").content.decode("utf-8")
    assert "Tajne" not in body


# --- Wsadowy upload ---

def test_upload_multiple_files(client_logged, captured_tasks, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile
    f1 = SimpleUploadedFile("a.png", b"a", content_type="image/png")
    f2 = SimpleUploadedFile("b.png", b"b", content_type="image/png")

    resp = client_logged.post("/upload/", {"files": [f1, f2], "mode": "fast"})
    assert resp.status_code == 302  # przekierowanie na listę
    assert Document.objects.count() == 2
    assert set(Document.objects.values_list("title", flat=True)) == {"a.png", "b.png"}
    assert captured_tasks.count("documents.tasks.run_ocr") == 2


def test_upload_single_uses_title_and_redirects_to_detail(client_logged, captured_tasks, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile
    f = SimpleUploadedFile("plik.png", b"x", content_type="image/png")

    resp = client_logged.post("/upload/", {"files": f, "title": "Mój tytuł", "mode": "fast"})
    assert resp.status_code == 302
    doc = Document.objects.get()
    assert doc.title == "Mój tytuł"  # tytuł działa przy pojedynczym pliku
    assert f"/{doc.id}/" in resp["Location"]


def test_upload_title_ignored_for_multiple(client_logged, captured_tasks, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile
    f1 = SimpleUploadedFile("a.png", b"a", content_type="image/png")
    f2 = SimpleUploadedFile("b.png", b"b", content_type="image/png")

    client_logged.post("/upload/", {"files": [f1, f2], "title": "Ignorowany", "mode": "fast"})
    titles = set(Document.objects.values_list("title", flat=True))
    assert titles == {"a.png", "b.png"}  # nazwy plików, nie wspólny tytuł


def test_upload_no_files_shows_error(client_logged):
    resp = client_logged.post("/upload/", {"mode": "fast"})
    assert resp.status_code == 302
    assert Document.objects.count() == 0


# --- Ustawienia: prompt ekstrakcji ---

@pytest.mark.django_db
def test_settings_saves_prompt(client_logged, user):
    from documents.models import UserSettings
    r = client_logged.post("/settings/", {"extraction_prompt": "Wskazówka branżowa"})
    assert r.status_code == 302
    assert UserSettings.objects.get(user=user).extraction_prompt == "Wskazówka branżowa"


@pytest.mark.django_db
def test_run_extraction_uses_custom_prompt(monkeypatch, user):
    import types as _types
    import documents.tasks as tasks
    from documents.models import UserSettings

    UserSettings.objects.create(user=user, extraction_prompt="MÓJ PROMPT")
    doc = Document.objects.create(owner=user, title="F", status="done", full_text="x")

    captured = {}
    fake_meta = _types.SimpleNamespace(
        doc_type=_types.SimpleNamespace(value="inne"), doc_date=None, doc_number="",
        counterparty="", total_amount=None, currency="", summary="",
        model_dump=lambda: {},
    )

    def fake_extract(text, *, system_prompt=None):
        captured["sp"] = system_prompt
        return fake_meta

    monkeypatch.setattr(tasks, "extract_metadata", fake_extract)
    monkeypatch.setattr(tasks, "extract_custom_fields", lambda *a, **k: {})
    tasks.run_extraction(doc.id)
    assert captured["sp"] == "MÓJ PROMPT"


# --- Regeneracja searchable PDF po edycji ---

@pytest.mark.django_db
def test_edit_enqueues_pdf_rebuild(client_logged, user, captured_tasks):
    doc = Document.objects.create(owner=user, title="D", status=Document.Status.DONE,
                                  full_text="tekst")
    from documents.models import Page
    page = Page.objects.create(document=doc, page_number=1, text="stary", source="ocr")
    client_logged.post(f"/{doc.id}/edit/", {f"page_{page.id}": "nowy"})
    assert "documents.tasks.rebuild_searchable_pdf" in captured_tasks


@pytest.mark.django_db
def test_rebuild_searchable_pdf_saves_file(monkeypatch, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.base import ContentFile
    from documents.models import Page
    import documents.tasks as tasks

    doc = Document.objects.create(owner=user, title="D", status="done")
    doc.file.save("src.pdf", ContentFile(b"%PDF-1.4"), save=True)
    Page.objects.create(document=doc, page_number=1, text="tekst", source="ocr")

    def fake_build(src, result, out_path, **k):
        # builder dostaje odtworzony wynik z rekordów Page
        assert result.pages[0].text == "tekst"
        with open(out_path, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return out_path

    monkeypatch.setattr(tasks, "build_searchable_pdf", fake_build)
    tasks.rebuild_searchable_pdf(doc.id)
    doc.refresh_from_db()
    assert doc.searchable_pdf
    assert doc.searchable_pdf.name.endswith("_ocr.pdf")


# --- Chronione pobieranie plików ---

@pytest.mark.django_db
def test_protected_pdf_download(client_logged, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.base import ContentFile
    doc = Document.objects.create(owner=user, title="D", status="done")
    doc.searchable_pdf.save("d_ocr.pdf", ContentFile(b"%PDF-1.4"), save=True)
    r = client_logged.get(f"/{doc.id}/pdf/")
    assert r.status_code == 200
    assert r["Content-Disposition"].startswith("attachment")


@pytest.mark.django_db
def test_protected_pdf_owner_only(user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.base import ContentFile
    doc = Document.objects.create(owner=user, title="D", status="done")
    doc.searchable_pdf.save("d_ocr.pdf", ContentFile(b"%PDF"), save=True)
    other = get_user_model().objects.create_user("intruz_dl", password="x")
    c = Client()
    c.force_login(other)
    assert c.get(f"/{doc.id}/pdf/").status_code == 404


@pytest.mark.django_db
def test_protected_pdf_requires_login(user):
    doc = Document.objects.create(owner=user, title="D", status="done")
    assert Client().get(f"/{doc.id}/pdf/").status_code == 302  # redirect do logowania


@pytest.mark.django_db
def test_protected_file_download(client_logged, user, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.base import ContentFile
    doc = Document.objects.create(owner=user, title="D", status="done")
    doc.file.save("orig.pdf", ContentFile(b"%PDF-1.4"), save=True)
    r = client_logged.get(f"/{doc.id}/file/")
    assert r.status_code == 200


# --- Strona logowania (demo) ---

@pytest.mark.django_db
def test_login_page_shows_demo_credentials(client):
    r = client.get("/login/")
    assert r.status_code == 200
    body = r.content.decode()
    assert "Konto demo" in body
    assert "<code>test</code>" in body
    assert "<code>testskryba</code>" in body


@pytest.mark.django_db
def test_login_flow_redirects_to_list(client, django_user_model):
    django_user_model.objects.create_user(username="test", password="testskryba")
    r = client.post("/login/", {"username": "test", "password": "testskryba"})
    assert r.status_code == 302
    assert r.url == "/"


@pytest.mark.django_db
def test_login_redirects_authenticated_user(client_logged):
    assert client_logged.get("/login/").status_code == 302


@pytest.mark.django_db
def test_logout_post(client_logged):
    assert client_logged.post("/logout/").status_code == 302


@pytest.mark.django_db
def test_nav_logout_only_when_authenticated(client, client_logged):
    assert "nav-logout" not in client.get("/login/").content.decode()
    assert "nav-logout" in client_logged.get("/").content.decode()
