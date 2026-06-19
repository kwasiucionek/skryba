"""Obserwator katalogu INBOX — automatyczne wciąganie dokumentów.

Cyklicznie skanuje katalog (env INBOX_DIR). Każdy nowy plik staje się
dokumentem i trafia do kolejki OCR, a oryginał jest przenoszony do
podkatalogu `processed/`, żeby nie został wciągnięty ponownie.

Uruchamianie (lokalnie):  python manage.py watch_inbox
W Dockerze: osobna usługa w docker-compose (profil 'inbox').
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django_q.tasks import async_task

from documents.models import Document

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


class Command(BaseCommand):
    help = "Obserwuje katalog INBOX i dodaje nowe pliki jako dokumenty."

    def handle(self, *args, **options):
        inbox = Path(os.getenv("INBOX_DIR", "/app/data/inbox"))
        processed = inbox / "processed"
        inbox.mkdir(parents=True, exist_ok=True)
        processed.mkdir(parents=True, exist_ok=True)

        interval = int(os.getenv("INBOX_POLL_SECONDS", "10"))
        mode = os.getenv("INBOX_MODE", Document.Mode.FAST)

        User = get_user_model()
        owner = User.objects.filter(is_superuser=True).order_by("id").first()

        self.stdout.write(self.style.SUCCESS(
            f"Obserwuję {inbox} co {interval}s (tryb OCR: {mode})"
        ))

        while True:
            for path in sorted(inbox.iterdir()):
                if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                    continue
                try:
                    self._ingest(path, owner, mode)
                    shutil.move(str(path), str(processed / path.name))
                    self.stdout.write(f"  + wciągnięto: {path.name}")
                except Exception as exc:  # noqa: BLE001
                    self.stderr.write(f"  ! błąd dla {path.name}: {exc}")
            time.sleep(interval)

    def _ingest(self, path: Path, owner, mode: str) -> None:
        doc = Document(owner=owner, title=path.name, mode=mode)
        with open(path, "rb") as fh:
            doc.file.save(path.name, File(fh), save=True)
        async_task("documents.tasks.run_ocr", doc.id)
