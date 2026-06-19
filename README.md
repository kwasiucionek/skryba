# Skryba

**Self-hosted archiwum dokumentów z OCR, które radzi sobie ze słabymi skanami.**

Większość narzędzi self-hosted (Paperless i pokrewne) używa Tesseracta i
zawodzi na kserokopiach, zdjęciach z telefonu czy dokumentach z artefaktami.
Skryba podchodzi do tego inaczej: ma **router silników**, który dla łatwych
dokumentów używa szybkiego Tesseracta na CPU, a dla trudnych — modelu
wizyjnego (VLM) przez Ollamę (lokalnie na GPU albo w chmurze). Dzięki temu
działa zarówno na słabym serwerze bez GPU, jak i daje topową jakość tam,
gdzie jej potrzeba.

> Status: wczesny etap (faza 1 — silnik OCR). Patrz [Mapa drogowa](#mapa-drogowa).

## Dlaczego

- **Słabe skany to norma, nie wyjątek.** Preprocessing (prostowanie metodą
  Hough Lines, CLAHE, skala szarości) + silniki VLM wyciągają tekst tam,
  gdzie klasyczny OCR się poddaje.
- **Działa bez GPU.** Tryb `fast` to czysty CPU. Tryb `quality` włączasz,
  gdy masz GPU lub subskrypcję Ollama Cloud.
- **Model-agnostyczne.** Ranking modeli VLM zmienia się co miesiąc —
  podmiana to jedna zmienna w `.env` (`OCR_OLLAMA_MODEL`), nie zmiana kodu.
- **Twoje dane zostają u Ciebie.** Self-hosted, jeden `docker compose up`.

## Architektura

```
                 ┌───────────────────────────────────────────┐
   plik (PDF/    │  pipeline.ocr_file()                       │
   obraz)  ───►  │   ├─ PDF? warstwa tekstowa → pomiń OCR     │
                 │   ├─ preprocessing (deskew, CLAHE, gray)   │
                 │   └─ router silników  get_engine(mode)     │
                 │        ├─ FAST     → Tesseract (CPU)        │
                 │        └─ QUALITY  → Ollama VLM (GPU/cloud) │
                 └───────────────────────────────────────────┘
                                │
        Django (web)  ◄── django-q2 worker ──►  baza (SQLite / PostgreSQL)
```

- **`ocr/`** — rdzeń niezależny od Django: silniki, preprocessing, PDF,
  pipeline. Można używać jako biblioteki.
- **`documents/`** — aplikacja Django: modele, upload, widoki (HTMX),
  zadanie OCR w tle.
- **`config/`** — projekt Django.

## Szybki start

```bash
git clone <repo> skryba && cd skryba
cp .env.example .env        # ustaw SECRET_KEY; opcjonalnie OLLAMA_API_KEY
docker compose up -d
docker compose exec web python manage.py createsuperuser
```

Aplikacja: <http://localhost:8000> · Panel admina: <http://localhost:8000/admin>

### Tryb QUALITY (Ollama)

W `.env`:

```
OCR_DEFAULT_MODE=quality
OCR_OLLAMA_MODEL=kimi-k2.6-cloud
OLLAMA_API_KEY=twoj-klucz        # tylko dla Ollama Cloud
```

Dla modelu lokalnego na GPU wskaż `OLLAMA_BASE_URL` na swoją instancję
i użyj taga bez sufiksu `-cloud`.

## Konfiguracja

Wszystko przez `.env` — pełna lista w `.env.example`. Najważniejsze:

| Zmienna | Znaczenie | Domyślnie |
|---|---|---|
| `OCR_DEFAULT_MODE` | `fast` (CPU) lub `quality` (VLM) | `fast` |
| `OCR_OLLAMA_MODEL` | model VLM dla trybu quality | `kimi-k2.6-cloud` |
| `OCR_TESSERACT_LANG` | języki Tesseracta | `pol+eng` |
| `DATABASE_URL` | puste = SQLite; `postgres://…` = PostgreSQL | SQLite |

## Mapa drogowa

- **Faza 1 — silnik OCR** *(gotowe)*: router fast/quality, preprocessing
  słabych skanów, upload, podgląd tekstu, przeszukiwalny PDF na wyjściu.
- **Faza 2 — archiwum** *(gotowe)*: klasyfikacja typu dokumentu i ekstrakcja
  pól (data, numer, kontrahent, kwota) + streszczenie i tagi przez LLM
  (Ollama, structured output), filtrowanie i wyszukiwanie, watcher folderu
  (`--profile inbox`).
- **Wyszukiwanie po polsku** *(gotowe)*: pełnotekstowy kanał używa
  konfiguracji `polish` ze stemmingiem hunspell — zapytanie „umowa"
  znajduje „umowy", „umów" itd. Słownik dostarcza obraz `db/Dockerfile`;
  ustaw `SEARCH_CONFIG=polish` (domyślne w `.env.example`).
- **Faza 3 — RAG** *(gotowe)*: PostgreSQL + pgvector, indeksacja (chunki +
  embeddingi przez Ollamę), wyszukiwanie hybrydowe (semantyka + pełny tekst,
  fuzja Reciprocal Rank Fusion) i strona „Zapytaj archiwum" — odpowiedzi LLM
  z odwołaniami do źródeł, w pełni lokalnie.

## Wdrożenie produkcyjne

Aplikacja jest skonfigurowana 12-factor (wszystko przez `.env`). Przed
wystawieniem na świat ustaw w `.env`:

- `DEBUG=false` — włącza zabezpieczenia (bezpieczne ciasteczka, HSTS,
  przekierowanie na HTTPS, `nosniff`, `X-Frame-Options: DENY`).
- `SECRET_KEY` — długi, losowy ciąg (50+ znaków). Przy `DEBUG=false`
  aplikacja **odmówi startu** z domyślnym kluczem.
- `ALLOWED_HOSTS` — Twoja domena, np. `archiwum.twojadomena.pl`.
- `CSRF_TRUSTED_ORIGINS` — pełny adres z `https://`.

Za reverse proxy (nginx) ustawiony jest `SECURE_PROXY_SSL_HEADER`, więc
Django rozpoznaje HTTPS po nagłówku `X-Forwarded-Proto`. Jeśli TLS
terminujesz gdzie indziej, możesz wyłączyć wymuszanie HTTPS przez
`SECURE_SSL_REDIRECT=false`. Weryfikacja konfiguracji:

```bash
docker compose exec web python manage.py check --deploy
```

## Testy

Testy wymagają PostgreSQL z pgvector (jak produkcja). Uruchomienie:

```bash
pip install -r requirements-dev.txt
DATABASE_URL=postgres://skryba:skryba@localhost:5432/skryba pytest
```

CI (GitHub Actions, `.github/workflows/ci.yml`) uruchamia testy przy każdym
push i pull requeście, wraz z kontrolą wdrożeniową `check --deploy`.

## Pola użytkownika (własne metadane z AI)

Poza wbudowanym schematem (typ, data, numer, kontrahent, kwota, tagi, streszczenie) możesz zdefiniować **własne pola** z indywidualnym promptem dla AI — np. „NIP sprzedawcy”, „numer sprawy”, „termin odwołania”. Każde pole ma typ (tekst/liczba/data) z automatyczną koercją wartości.

Wartości lądują w `Document.metadata['custom']` (bez migracji bazy per pole), są widoczne na stronie dokumentu i trafiają jako dodatkowe kolumny do eksportu CSV. Po dodaniu pola użyj „Ponów metadane” na istniejących dokumentach; nowe wypełnią się automatycznie.

## Własny prompt ekstrakcji

W „Ustawieniach” możesz dostosować instrukcję systemową, której AI używa przy wyodrębnianiu metadanych (np. wskazówki branżowe). Struktura wyjścia JSON pozostaje sterowana przez aplikację, więc nie da się jej przypadkiem zepsuć. Puste pole = prompt domyślny. Po zmianie użyj „Ponów metadane”, aby zastosować do istniejących dokumentów.

## Eksport danych

Twoje dane zostają twoje. Z poziomu listy dokumentów wyeksportujesz:

- **CSV** — metadane (tytuł, typ, data, numer, kontrahent, kwota, tagi, streszczenie, status), z BOM dla poprawnego otwarcia w Excelu.
- **ZIP** — całe archiwum: `metadane.csv` plus oryginalne pliki w `pliki/`.

Oba eksporty respektują aktywne filtry, więc możesz wyeksportować dokładnie ten wycinek archiwum, który masz przed sobą.

## Ewaluacja jakości

Harness w pakiecie `evaluation/` mierzy jakość OCR i RAG na własnych
zbiorach testowych (format JSON, przykłady w `evaluation/samples/`).

**OCR (CER/WER)** — porównuje rozpoznany tekst z wzorcem:

```bash
python manage.py eval_ocr evaluation/samples/ocr_samples.json --out raport_ocr.md
```

Zbiór OCR to lista `{"file": "skan.png", "ground_truth_file": "skan.txt", "mode": "quality"}` (lub `ground_truth` z tekstem wprost).

**RAG (recall@k, MRR)** — sprawdza, czy trafny dokument trafia do wyników
wyszukiwania; opcjonalnie (`--answer`) wywołuje LLM i weryfikuje, czy
odpowiedź zawiera oczekiwane fragmenty. Dokumenty ze zbioru muszą być
wcześniej w archiwum użytkownika (dopasowanie po tytule):

```bash
python manage.py eval_rag evaluation/samples/rag_questions.json --user kris --answer
```

Zbiór RAG to lista `{"question": "...", "relevant_titles": ["..."], "expected_substrings": ["..."]}`. Metryki to czyste funkcje (`evaluation/metrics.py`) pokryte testami.

## Rozwiązywanie problemów

**Tryb Jakość daje słaby/bełkotliwy tekst, nagłówek pokazuje „(ocr, tesseract)".**
Ollama jest nieosiągalna z kontenera, więc OCR poszedł Tesseractem. Na Linuksie
Ollama domyślnie słucha tylko na `127.0.0.1` — ustaw na hoście `OLLAMA_HOST=0.0.0.0`
(patrz komentarz w `.env.example`) i upewnij się, że `OLLAMA_BASE_URL` w `.env` to
`http://host.docker.internal:11434`. Test z kontenera:

```bash
docker compose exec worker python -c "import requests; print(requests.get('http://host.docker.internal:11434/api/tags').status_code)"
```

Powinno zwrócić `200`. Po naprawie usuń dokument i wgraj go ponownie — OCR rusza
od nowa dopiero przy nowym uploadzie.

**`password authentication failed` / web restartuje się w pętli.** Hasło Postgresa
jest ustawiane tylko przy pierwszej inicjalizacji wolumenu. Po zmianie hasła w `.env`
zresetuj bazę: `docker compose down -v && docker compose up -d --build` (kasuje dane).

**RAG nie zwraca odpowiedzi.** Sprawdź w adminie pole `indexed` przy dokumencie i
`indexing_error`. Najczęstsza przyczyna to niepobrany model embeddingów:
`ollama pull nomic-embed-text`.

## Licencja

AGPL-3.0 — patrz [LICENSE](LICENSE).
