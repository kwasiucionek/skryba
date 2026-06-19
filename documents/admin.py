from django.contrib import admin

from .models import Chunk, Document, Page, CustomField, UserSettings


class PageInline(admin.TabularInline):
    model = Page
    extra = 0
    readonly_fields = ["page_number", "source", "engine_name", "confidence"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        "title", "doc_type", "doc_date", "counterparty",
        "amount", "currency", "status", "indexed", "created_at",
    ]
    list_filter = ["doc_type", "status", "indexed", "mode", "doc_date", "created_at"]
    search_fields = ["title", "full_text", "counterparty", "doc_number", "summary"]
    readonly_fields = [
        "status", "full_text", "searchable_pdf", "metadata",
        "extraction_error", "indexed", "indexing_error",
        "error_message", "created_at", "updated_at",
    ]
    inlines = [PageInline]
    fieldsets = [
        (None, {"fields": ["owner", "title", "file", "mode", "status"]}),
        ("Metadane", {
            "fields": [
                "doc_type", "doc_date", "doc_number", "counterparty",
                "amount", "currency", "summary",
            ]
        }),
        ("RAG / indeksacja", {
            "fields": ["indexed", "indexing_error"],
        }),
        ("Wyniki", {
            "fields": [
                "searchable_pdf", "full_text", "metadata",
                "extraction_error", "error_message",
            ],
            "classes": ["collapse"],
        }),
    ]


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ["document", "page_number", "source", "engine_name", "confidence"]
    list_filter = ["source", "engine_name"]


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    """Podgląd fragmentów RAG — pozwala sprawdzić, czy embeddingi powstały."""

    list_display = ["document", "page_number", "chunk_index", "has_embedding"]
    list_filter = ["document"]
    search_fields = ["text"]
    readonly_fields = ["document", "page_number", "chunk_index", "text"]
    exclude = ["embedding"]  # wektor 768-wymiarowy — bez sensu w formularzu

    @admin.display(boolean=True, description="Embedding")
    def has_embedding(self, obj) -> bool:
        return obj.embedding is not None


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "field_type", "owner")
    list_filter = ("field_type",)
    search_fields = ("name", "key")


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
