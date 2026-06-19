"""Testy pól użytkownika: ekstrakcja (czysta), zarządzanie, integracja, eksport."""

from __future__ import annotations

import json
import types

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from documents.models import CustomField, Document


# --- Pure: ekstrakcja własnych pól + koercja typów ---

def _run_custom(monkeypatch, content, fields):
    import extraction.custom_fields as CF

    monkeypatch.setattr(CF, "_post", lambda *a, **k: content)
    return CF.extract_custom_fields("treść", fields)


def test_custom_fields_coercion(monkeypatch):
    from extraction import FieldSpec

    content = json.dumps({
        "nip": "5260250274",
        "netto": "1 234,56",
        "termin": "2026-03-14",
        "puste": None,
    })
    res = _run_custom(monkeypatch, content, [
        FieldSpec("nip", "NIP", "text"),
        FieldSpec("netto", "kwota netto", "number"),
        FieldSpec("termin", "termin", "date"),
        FieldSpec("puste", "czego nie ma", "text"),
    ])
    assert res["nip"] == "5260250274"
    assert res["netto"] == 1234.56          # spacje i przecinek skoercowane
    assert res["termin"] == "2026-03-14"
    assert res["puste"] is None


def test_custom_fields_invalid_date_becomes_null(monkeypatch):
    from extraction import FieldSpec

    res = _run_custom(monkeypatch, json.dumps({"d": "nie-data"}),
                      [FieldSpec("d", "data", "date")])
    assert res["d"] is None


def test_custom_fields_empty_list_skips_call():
    from extraction import extract_custom_fields

    assert extract_custom_fields("treść", []) == {}


def test_custom_fields_unwraps_wrapper(monkeypatch):
    from extraction import FieldSpec

    wrapped = json.dumps({"pola": {"nip": "123"}})
    res = _run_custom(monkeypatch, wrapped, [FieldSpec("nip", "NIP", "text")])
    assert res["nip"] == "123"


# --- DB: zarządzanie polami ---

pytestmark_db = pytest.mark.django_db


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("cfuser", password="x")


@pytest.fixture
def client_logged(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
def test_add_custom_field_slugifies_key(client_logged, user):
    client_logged.post("/fields/", {
        "name": "NIP sprzedawcy", "field_type": "text", "prompt": "Wyodrębnij NIP",
    })
    field = CustomField.objects.get(owner=user)
    assert field.key == "nip-sprzedawcy"
    assert field.field_type == "text"


@pytest.mark.django_db
def test_add_duplicate_key_rejected(client_logged, user):
    CustomField.objects.create(owner=user, name="NIP", key="nip", prompt="p")
    client_logged.post("/fields/", {"name": "Nip", "field_type": "text", "prompt": "q"})
    # slug "Nip" -> "nip" już istnieje, więc nadal jedno pole
    assert CustomField.objects.filter(owner=user).count() == 1


@pytest.mark.django_db
def test_field_requires_name_and_prompt(client_logged, user):
    client_logged.post("/fields/", {"name": "", "prompt": "", "field_type": "text"})
    assert CustomField.objects.filter(owner=user).count() == 0


@pytest.mark.django_db
def test_delete_custom_field(client_logged, user):
    field = CustomField.objects.create(owner=user, name="X", key="x", prompt="p")
    client_logged.post(f"/fields/{field.pk}/delete/")
    assert not CustomField.objects.filter(pk=field.pk).exists()


@pytest.mark.django_db
def test_field_isolation(user):
    field = CustomField.objects.create(owner=user, name="X", key="x", prompt="p")
    other = get_user_model().objects.create_user("intruz_cf", password="x")
    c = Client()
    c.force_login(other)
    assert c.post(f"/fields/{field.pk}/delete/").status_code == 404


# --- Integracja: run_extraction zapisuje metadata['custom'] ---

@pytest.mark.django_db
def test_run_extraction_stores_custom(monkeypatch, user):
    import documents.tasks as tasks

    CustomField.objects.create(owner=user, name="NIP", key="nip", prompt="Wyodrębnij NIP")
    doc = Document.objects.create(owner=user, title="F", status="done", full_text="NIP 123")

    fake_meta = types.SimpleNamespace(
        doc_type=types.SimpleNamespace(value="faktura"), doc_date=None,
        doc_number="1", counterparty="X", total_amount=None, currency="PLN",
        summary="s", model_dump=lambda: {"doc_type": "faktura", "tags": ["t"]},
    )
    monkeypatch.setattr(tasks, "extract_metadata", lambda t, **k: fake_meta)
    monkeypatch.setattr(tasks, "extract_custom_fields", lambda t, s, **k: {"nip": "5260250274"})

    tasks.run_extraction(doc.id)
    doc.refresh_from_db()
    assert doc.custom == {"nip": "5260250274"}
    assert doc.metadata.get("tags") == ["t"]   # standardowe metadane nietknięte
    assert doc.extraction_error == ""


@pytest.mark.django_db
def test_detail_shows_custom_values(client_logged, user):
    CustomField.objects.create(owner=user, name="NIP sprzedawcy", key="nip", prompt="p")
    doc = Document.objects.create(
        owner=user, title="F", status="done",
        metadata={"custom": {"nip": "5260250274"}},
    )
    html = client_logged.get(f"/{doc.id}/").content.decode()
    assert "NIP sprzedawcy" in html and "5260250274" in html


@pytest.mark.django_db
def test_export_csv_includes_custom_column(client_logged, user):
    CustomField.objects.create(owner=user, name="NIP sprzedawcy", key="nip", prompt="p")
    Document.objects.create(
        owner=user, title="F", status="done",
        metadata={"custom": {"nip": "5260250274"}},
    )
    body = client_logged.get("/export/csv/").content.decode("utf-8")
    assert "NIP sprzedawcy" in body and "5260250274" in body
