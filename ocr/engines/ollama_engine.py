"""Silnik QUALITY: model wizyjny przez API Ollama.

Działa zarówno z modelem lokalnym (GPU), jak i z Ollama Cloud
(model z sufiksem `-cloud`). Nazwa modelu jest w pełni
konfigurowalna przez env (OCR_OLLAMA_MODEL), bo ranking modeli
VLM zmienia się co miesiąc — dziś kimi-k2.6, jutro coś innego.
"""

from __future__ import annotations

import base64
import time

import requests

from .base import EngineMode, OCREngine, OCRResult

DEFAULT_PROMPT = (
    "Przepisz dokładnie cały tekst widoczny na obrazie. "
    "Zachowaj oryginalny układ: akapity, nagłówki, listy oraz tabele "
    "(tabele jako markdown). Nie streszczaj, nie tłumacz, nie dodawaj "
    "komentarzy — zwróć wyłącznie wierny tekst dokumentu."
)


class OllamaEngine(OCREngine):
    name = "ollama"
    mode = EngineMode.QUALITY

    def __init__(
        self,
        model: str = "kimi-k2.6:cloud",
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
        timeout: int = 300,
        temperature: float = 0.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:  # wymagane dla Ollama Cloud
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def ocr_image(self, image_bytes: bytes, prompt: str | None = None) -> OCRResult:
        prompt = prompt or DEFAULT_PROMPT
        image_b64 = base64.b64encode(image_bytes).decode()

        start = time.perf_counter()
        resp = requests.post(
            f"{self.base_url}/api/chat",
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [
                    {"role": "user", "content": prompt, "images": [image_b64]}
                ],
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    # przeciwdziała zapętlaniu powtórzeń na słabych skanach
                    "repeat_penalty": 1.15,
                },
            },
            timeout=self.timeout,
        )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Ollama zwróciła {resp.status_code}: {resp.text[:500]}"
            )

        text = resp.json()["message"]["content"]
        elapsed = time.perf_counter() - start
        return OCRResult(
            text=text.strip(),
            engine_name=self.name,
            mode=self.mode,
            confidence=None,  # VLM nie zwraca confidence
            meta={"model": self.model, "elapsed_s": round(elapsed, 2)},
        )
