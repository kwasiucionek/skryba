"""Wczytywanie zbiorów ewaluacyjnych z JSON.

Format RAG (lista obiektów):
    {"question": "...", "relevant_titles": ["..."], "expected_substrings": ["..."]}

Format OCR (lista obiektów):
    {"file": "skan.png", "ground_truth_file": "skan.txt", "mode": "quality"}
    albo z tekstem wzorcowym wprost:
    {"file": "skan.png", "ground_truth": "treść...", "mode": "fast"}

Ścieżki względne rozwiązywane są względem katalogu pliku zbioru.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RagCase:
    question: str
    relevant_titles: list[str]
    expected_substrings: list[str] = field(default_factory=list)


@dataclass
class OcrCase:
    path: str
    ground_truth: str
    mode: str = "fast"


def load_rag_cases(path: str | Path) -> list[RagCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = []
    for item in data:
        cases.append(
            RagCase(
                question=item["question"],
                relevant_titles=list(item.get("relevant_titles", [])),
                expected_substrings=list(item.get("expected_substrings", [])),
            )
        )
    return cases


def load_ocr_cases(path: str | Path) -> list[OcrCase]:
    path = Path(path)
    base = path.parent
    data = json.loads(path.read_text(encoding="utf-8"))

    cases = []
    for item in data:
        ground_truth = item.get("ground_truth")
        if ground_truth is None and item.get("ground_truth_file"):
            gt_path = base / item["ground_truth_file"]
            ground_truth = gt_path.read_text(encoding="utf-8")

        file_path = Path(item["file"])
        if not file_path.is_absolute():
            file_path = base / file_path

        cases.append(
            OcrCase(
                path=str(file_path),
                ground_truth=ground_truth or "",
                mode=item.get("mode", "fast"),
            )
        )
    return cases
