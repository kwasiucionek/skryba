# Wdrożenie na Mikr.us

Skryba to Django + django-q2 (kolejka na ORM Postgresa) + PostgreSQL/pgvector.
**Brak OpenSearcha, Redisa, Celery** — wyszukiwanie to FTS Postgresa + pgvector,
a kolejka chodzi na bazie. Stack jest więc lżejszy niż TaxPilot.

Aplikacja, worker i baza chodzą w Dockerze. Domenę (`skryba.cytr.us`) wpinasz
przez **nginx na hoście słuchający na Twoim porcie z Mikrusa** — tak jak w
pozostałych aplikacjach cytr.us.

## 1. Kod na serwerze

```bash
ssh <twoj-serwer>
git clone https://github.com/<login>/skryba.git
cd skryba
```

## 2. Konfiguracja `.env`

```bash
cp .env.example .env
python3 -c "import secrets; print('SECRET_KEY='+secrets.token_urlsafe(64))"
nano .env
```

Minimum:

```ini
DEBUG=false
SECRET_KEY=<wygenerowany>
ALLOWED_HOSTS=skryba.cytr.us,pro01.mikr.us
CSRF_TRUSTED_ORIGINS=https://skryba.cytr.us
SECURE_SSL_REDIRECT=false          # Cloudflare->origin idzie po HTTP (patrz §5)

POSTGRES_PASSWORD=<silne-haslo>
DATABASE_URL=postgres://skryba:<silne-haslo>@db:5432/skryba
SEARCH_CONFIG=polish

# Ollama — patrz §3. Skryba liczy embeddingi przez Ollamę, więc potrzebny
# jest LOKALNY daemon na hoście (inaczej niż w TaxPilocie).
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_API_KEY=<klucz-ollama-cloud>
```

## 3. Ollama na hoście

Różnica wobec TaxPilota: tam embeddingi robi lokalny stella-pl-mini, a Ollama
Cloud służy tylko do generacji (przez `OLLAMA_CLOUD_API_KEY`). **Skryba używa
Ollamy także do embeddingów** (`nomic-embed-text` przez `/api/embed`), więc na
Mikrusie musi działać lokalny daemon Ollamy. Modele `*:cloud` i tak liczą się
po stronie chmury (nie zżerają RAM), a `nomic-embed-text` jest lekki (~274 MB).

```bash
sudo systemctl edit ollama     # [Service]\n Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl daemon-reload && sudo systemctl restart ollama
ollama pull nomic-embed-text
```

Kontener łączy się przez `host.docker.internal` (już w compose przez
`extra_hosts`). Test: `docker compose exec worker python -c "import requests;
print(requests.get('http://host.docker.internal:11434/api/tags').status_code)"`.

## 4. Start (web tylko na localhost, za nginx)

```bash
cp docker-compose.override.example.yml docker-compose.override.yml   # web -> 127.0.0.1:8000
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
curl -I http://127.0.0.1:8000/      # oczekiwane: 302 (redirect do logowania)
```

(Migracje i `collectstatic` wykonują się automatycznie przy starcie web.)

## 5. nginx + domena

```bash
cp deploy/nginx-skryba.conf /etc/nginx/sites-available/skryba
# dostosuj `listen` do Twojego portu (np. 44332) i ewentualnie server_name
ln -s /etc/nginx/sites-available/skryba /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

nginx słucha na porcie z Mikrusa, podnosi limit uploadu (`client_max_body_size
50M` — skany bywają duże) i proxuje do kontenera. Statyki serwuje WhiteNoise w
aplikacji, więc nie ma osobnego `location /static/`.

W panelu Mikrusa / Cloudflare skieruj `skryba.cytr.us` na `<serwer>.mikr.us:<port>`
(tak jak inne Twoje aplikacje). Cloudflare terminuje TLS i łączy się z originem
po HTTP — dlatego `SECURE_SSL_REDIRECT=false` (inaczej pętla przekierowań).
`SECURE_PROXY_SSL_HEADER` jest już ustawiony w `settings.py`.

## Alternatywa: bez nginx (prościej, mniej kontroli)

Jeśli nie chcesz nginx, pomiń override i §5 — ustaw w `.env` `WEB_PORT=<port>`,
wtedy kontener web wystawia się wprost na port Mikrusa. Tracisz kontrolę nad
limitem uploadu i nagłówkami na poziomie proxy, ale dla małego ruchu wystarczy.

## 6. Aktualizacje

```bash
git pull && docker compose up -d --build
```
