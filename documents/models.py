"""Modele archiwum dokumentów.

Faza 3 dokłada model Chunk z polem wektorowym (pgvector) do wyszukiwania
semantycznego oraz RAG. Wymiar wektora bierzemy z ustawień (EMBED_DIM) i
indeksujemy HNSW po odległości cosinusowej.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from pgvector.django import HnswIndex, VectorField

User = get_user_model()


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Oczekuje"
        PROCESSING = "processing", "Przetwarzanie"
        DONE = "done", "Gotowe"
        FAILED = "failed", "Błąd"

    class Mode(models.TextChoices):
        FAST = "fast", "Szybki (CPU)"
        QUALITY = "quality", "Jakość (GPU/chmura)"

    class DocType(models.TextChoices):
        FAKTURA = "faktura", "Faktura"
        UMOWA = "umowa", "Umowa"
        PISMO_SADOWE = "pismo_sadowe", "Pismo sądowe"
        PISMO_URZEDOWE = "pismo_urzedowe", "Pismo urzędowe"
        PARAGON = "paragon", "Paragon"
        OFERTA = "oferta", "Oferta"
        KORESPONDENCJA = "korespondencja", "Korespondencja"
        INNE = "inne", "Inne"

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="documents", null=True, blank=True
    )
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.FAST)

    # --- Wynik OCR ---
    full_text = models.TextField(blank=True)
    searchable_pdf = models.FileField(
        upload_to="searchable/%Y/%m/", blank=True, null=True
    )

    # --- Metadane z ekstrakcji LLM (faza 2) ---
    doc_type = models.CharField(max_length=20, choices=DocType.choices, blank=True)
    doc_date = models.DateField(null=True, blank=True)
    doc_number = models.CharField(max_length=120, blank=True)
    counterparty = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=10, blank=True)
    summary = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    extraction_error = models.TextField(blank=True)

    # --- Indeksacja RAG (faza 3) ---
    indexed = models.BooleanField(default=False)
    indexing_error = models.TextField(blank=True)

    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["doc_type"]),
            models.Index(fields=["doc_date"]),
        ]

    def __str__(self) -> str:
        return self.title or f"Dokument #{self.pk}"

    @property
    def tags(self) -> list[str]:
        return self.metadata.get("tags", []) if isinstance(self.metadata, dict) else []

    @property
    def custom(self) -> dict:
        """Wartości pól użytkownika wyodrębnione przez AI (metadata['custom'])."""
        return self.metadata.get("custom", {}) if isinstance(self.metadata, dict) else {}


class CustomField(models.Model):
    """Zdefiniowane przez użytkownika pole metadanych z własnym promptem AI.

    Wartości lądują w ``Document.metadata['custom'][key]``, więc nowe pola nie
    wymagają migracji bazy. Klucz (``key``) to identyfikator w JSON i w promkcie.
    """

    class FieldType(models.TextChoices):
        TEXT = "text", "Tekst"
        NUMBER = "number", "Liczba"
        DATE = "date", "Data"

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="custom_fields"
    )
    name = models.CharField(max_length=80)
    key = models.SlugField(max_length=60)
    field_type = models.CharField(
        max_length=10, choices=FieldType.choices, default=FieldType.TEXT
    )
    prompt = models.TextField(help_text="Instrukcja dla AI: co dokładnie wyodrębnić.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="uniq_owner_field_key")
        ]

    def __str__(self) -> str:
        return self.name


class Page(models.Model):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="pages"
    )
    page_number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    source = models.CharField(max_length=20, default="ocr")  # ocr | text_layer
    engine_name = models.CharField(max_length=50, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["document", "page_number"]
        unique_together = ["document", "page_number"]

    def __str__(self) -> str:
        return f"{self.document} – strona {self.page_number}"


class Chunk(models.Model):
    """Fragment dokumentu z embeddingiem — jednostka wyszukiwania i RAG."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="chunks"
    )
    page_number = models.PositiveIntegerField(default=1)
    chunk_index = models.PositiveIntegerField(default=0)
    text = models.TextField()
    embedding = VectorField(dimensions=settings.EMBED_DIM, null=True, blank=True)

    class Meta:
        ordering = ["document", "chunk_index"]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document} – fragment {self.chunk_index}"


class UserSettings(models.Model):
    """Ustawienia użytkownika. Na razie: własny prompt systemowy ekstrakcji.

    Pusty ``extraction_prompt`` oznacza prompt domyślny. Struktura wyjścia JSON
    pozostaje sterowana przez aplikację — użytkownik dostosowuje tylko instrukcję.
    """

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="settings"
    )
    extraction_prompt = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Ustawienia: {self.user}"
