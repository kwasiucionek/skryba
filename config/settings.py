"""Ustawienia Django dla projektu Skryba.

Konfiguracja sterowana zmiennymi środowiskowymi (12-factor), żeby
self-hoster konfigurował wszystko przez .env / docker-compose, bez
ruszania kodu. Domyślnie SQLite; PostgreSQL włącza się ustawieniem
zmiennej DATABASE_URL (przyda się przy RAG / pełnotekstowym wyszukiwaniu).
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes", "on")


SECRET_KEY = os.getenv("SECRET_KEY", "dev-niebezpieczny-klucz-zmien-w-produkcji")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_q",
    "documents",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Baza danych -----------------------------------------------------------
# Domyślnie SQLite. Ustaw DATABASE_URL=postgres://... aby przełączyć
# (np. przy wejściu w RAG / pgvector w fazie 3).
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "data" / "db.sqlite3",
        }
    }

# --- RAG / wektory ---
# Wymiar embeddingu musi zgadzać się z modelem (nomic-embed-text = 768).
# Zmiana na model o innym wymiarze wymaga nowej migracji kolumny wektorowej.
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))
# Konfiguracja pełnotekstowego wyszukiwania Postgresa.
# 'simple' nie wymaga słowników; dla polskiego stemmingu można podmienić.
SEARCH_CONFIG = os.getenv("SEARCH_CONFIG", "simple")

# --- Kolejka zadań (django-q2) ---------------------------------------------
# Backend ORM = brak Redisa, mniej kontenerów dla self-hostera.
Q_CLUSTER = {
    "name": "skryba",
    "workers": int(os.getenv("Q_WORKERS", "2")),
    "timeout": int(os.getenv("Q_TIMEOUT", "1800")),  # OCR bywa długi
    "retry": int(os.getenv("Q_RETRY", "2000")),
    "orm": "default",
    "catch_up": False,
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "pl"
TIME_ZONE = os.getenv("TIME_ZONE", "Europe/Warsaw")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "data" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "admin:login"
LOGIN_REDIRECT_URL = "documents:list"



# --- Bezpieczeństwo produkcyjne (aktywne gdy DEBUG=False) ---
# Za reverse proxy (nginx) Django musi rozpoznać, że ruch przyszedł po HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    # Wymuś własny SECRET_KEY w produkcji — domyślny jest jawnie niebezpieczny.
    if SECRET_KEY == "dev-niebezpieczny-klucz-zmien-w-produkcji":
        raise ImproperlyConfigured(
            "Ustaw własny SECRET_KEY (zmienna środowiskowa SECRET_KEY) "
            "przed uruchomieniem z DEBUG=False."
        )
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "2592000"))  # 30 dni
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
