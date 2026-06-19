"""Ewaluacja OCR: CER/WER na zbiorze (plik, tekst wzorcowy).

Uruchamia rzeczywisty OCR (Tesseract/VLM), więc wymaga skonfigurowanych
silników. Przykład:

    python manage.py eval_ocr evaluation/samples/ocr_samples.json
    python manage.py eval_ocr zbior.json --mode quality --out raport.md
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from evaluation import cer, load_ocr_cases, wer
from ocr.pipeline import ocr_file


class Command(BaseCommand):
    help = "Ewaluacja OCR (CER/WER) na zbiorze testowym."

    def add_arguments(self, parser):
        parser.add_argument("dataset", help="Ścieżka do JSON ze zbiorem OCR.")
        parser.add_argument("--mode", choices=["fast", "quality"],
                            help="Wymuś tryb dla wszystkich przypadków.")
        parser.add_argument("--out", help="Zapisz raport Markdown do pliku.")

    def handle(self, *args, **options):
        try:
            cases = load_ocr_cases(options["dataset"])
        except (OSError, ValueError) as exc:
            raise CommandError(f"Nie wczytano zbioru: {exc}")

        if not cases:
            raise CommandError("Zbiór jest pusty.")

        rows = []
        for case in cases:
            mode = options["mode"] or case.mode
            try:
                result = ocr_file(case.path, mode=mode)
                hypothesis = "\n".join(p.text for p in result.pages)
                c = cer(case.ground_truth, hypothesis)
                w = wer(case.ground_truth, hypothesis)
                rows.append((case.path, mode, c, w, ""))
            except Exception as exc:  # noqa: BLE001 — raportujemy, nie przerywamy
                rows.append((case.path, mode, None, None, str(exc)[:80]))

        ok = [r for r in rows if r[2] is not None]
        avg_cer = sum(r[2] for r in ok) / len(ok) if ok else 0.0
        avg_wer = sum(r[3] for r in ok) / len(ok) if ok else 0.0

        self.stdout.write(self.style.MIGRATE_HEADING("Wyniki OCR:"))
        for path, mode, c, w, err in rows:
            if err:
                self.stdout.write(self.style.ERROR(f"  {path} [{mode}] — BŁĄD: {err}"))
            else:
                self.stdout.write(f"  {path} [{mode}]  CER={c:.3f}  WER={w:.3f}")
        self.stdout.write(self.style.SUCCESS(
            f"Średnio: CER={avg_cer:.3f}  WER={avg_wer:.3f}  ({len(ok)}/{len(rows)} OK)"
        ))

        if options["out"]:
            lines = ["# Raport OCR\n", "| Plik | Tryb | CER | WER |", "|---|---|---|---|"]
            for path, mode, c, w, err in rows:
                if err:
                    lines.append(f"| {path} | {mode} | — | błąd |")
                else:
                    lines.append(f"| {path} | {mode} | {c:.3f} | {w:.3f} |")
            lines.append(f"\n**Średnio:** CER={avg_cer:.3f}, WER={avg_wer:.3f}\n")
            with open(options["out"], "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            self.stdout.write(f"Raport zapisany: {options['out']}")
