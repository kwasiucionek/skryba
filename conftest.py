"""Konfiguracja środowiska testów.

Ustawiamy zmienne PRZED inicjalizacją Django. DEBUG=True wyłącza blok
bezpieczeństwa produkcyjnego (m.in. SSL redirect), który psułby klienta
testowego. Testy bazodanowe wymagają PostgreSQL z pgvector — w CI
dostarcza go usługa, lokalnie ustaw DATABASE_URL.
"""

import os

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")
os.environ.setdefault("SEARCH_CONFIG", "simple")  # testy bez słownika hunspell
