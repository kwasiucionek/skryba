"""Ewaluacja RAG: recall@k, MRR oraz (opcjonalnie) trafienia odpowiedzi.

Wymaga, by dokumenty ze zbioru były już w archiwum wskazanego użytkownika
(dopasowanie po tytule). Przykład:

    python manage.py eval_rag evaluation/samples/rag_questions.json --user kris
    python manage.py eval_rag zbior.json --user kris --answer --k 8 --out raport.md
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from documents.search import hybrid_search
from evaluation import hit_at_k, load_rag_cases, recall_at_k, reciprocal_rank
from rag import Context, answer_question


def _ordered_unique(items):
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


class Command(BaseCommand):
    help = "Ewaluacja RAG (recall@k, MRR, trafienia odpowiedzi)."

    def add_arguments(self, parser):
        parser.add_argument("dataset", help="Ścieżka do JSON ze zbiorem RAG.")
        parser.add_argument("--user", required=True, help="Nazwa użytkownika (właściciel dokumentów).")
        parser.add_argument("--k", type=int, default=8, help="Liczba wyników do oceny (domyślnie 8).")
        parser.add_argument("--answer", action="store_true",
                            help="Wywołaj LLM i sprawdź expected_substrings w odpowiedzi.")
        parser.add_argument("--out", help="Zapisz raport Markdown do pliku.")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            raise CommandError(f"Brak użytkownika: {options['user']}")

        try:
            cases = load_rag_cases(options["dataset"])
        except (OSError, ValueError) as exc:
            raise CommandError(f"Nie wczytano zbioru: {exc}")

        k = options["k"]
        rows = []
        for case in cases:
            hits = hybrid_search(user, case.question, top_k=k)
            doc_titles = _ordered_unique(h.chunk.document.title for h in hits)

            recall = recall_at_k(doc_titles, case.relevant_titles, k)
            hit = hit_at_k(doc_titles, case.relevant_titles, k)
            rr = reciprocal_rank(doc_titles, case.relevant_titles)

            ans_hit = None
            if options["answer"] and case.expected_substrings:
                contexts = [
                    Context(label=i + 1, title=h.chunk.document.title,
                            page_number=h.chunk.page_number, text=h.chunk.text)
                    for i, h in enumerate(hits)
                ]
                answer = answer_question(case.question, contexts) if contexts else ""
                low = answer.lower()
                ans_hit = all(sub.lower() in low for sub in case.expected_substrings)

            rows.append((case.question, recall, hit, rr, ans_hit))

        n = len(rows) or 1
        avg_recall = sum(r[1] for r in rows) / n
        avg_hit = sum(r[2] for r in rows) / n
        avg_mrr = sum(r[3] for r in rows) / n
        answered = [r[4] for r in rows if r[4] is not None]
        avg_ans = (sum(answered) / len(answered)) if answered else None

        self.stdout.write(self.style.MIGRATE_HEADING(f"Wyniki RAG (k={k}):"))
        for q, recall, hit, rr, ans_hit in rows:
            extra = "" if ans_hit is None else f"  odpowiedź={'✓' if ans_hit else '✗'}"
            self.stdout.write(f"  hit@{k}={hit:.0f}  RR={rr:.2f}  recall={recall:.2f}{extra}  — {q[:60]}")
        summary = f"Średnio: hit@{k}={avg_hit:.2f}  MRR={avg_mrr:.2f}  recall@{k}={avg_recall:.2f}"
        if avg_ans is not None:
            summary += f"  trafność odpowiedzi={avg_ans:.2f}"
        self.stdout.write(self.style.SUCCESS(summary))

        if options["out"]:
            lines = [f"# Raport RAG (k={k})\n",
                     f"| Pytanie | hit@{k} | RR | recall@{k} | odpowiedź |",
                     "|---|---|---|---|---|"]
            for q, recall, hit, rr, ans_hit in rows:
                a = "—" if ans_hit is None else ("✓" if ans_hit else "✗")
                lines.append(f"| {q} | {hit:.0f} | {rr:.2f} | {recall:.2f} | {a} |")
            lines.append(f"\n**Średnio:** {summary}\n")
            with open(options["out"], "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            self.stdout.write(f"Raport zapisany: {options['out']}")
