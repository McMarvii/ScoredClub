# Deployment

ScoredClub hat drei deploybare Teile: die **CLI/Pipeline** (Batch-Läufe), die **API**
(Lese-Service) und das **Dashboard** (Static-Site). Dazu kommen CI und Scheduling.

## Docker

Das Image installiert das Paket und startet standardmäßig die API.

```bash
docker compose up --build         # API auf :8000, SQLite in ./data
```

Einmaliger Pipeline-Lauf im Container:

```bash
docker compose run app scoredclub run --research data/research/latest.json
```

Volumes (in `docker-compose.yml`): `./output` und `./data` werden gemountet, damit
Reports und SQLite-DB persistent bleiben.

### PostgreSQL statt SQLite

`docker-compose.yml` enthält einen optionalen `postgres`-Service unter einem
Compose-Profil:

```bash
docker compose --profile postgres up
```

Dann `DATABASE_URL` auf Postgres umstellen (im Compose-File ist ein Beispiel
auskommentiert):

```
DATABASE_URL=postgresql+psycopg2://scoredclub:scoredclub@postgres:5432/scoredclub
```

> Postgres-Unterstützung bedeutet in V1 Connection-String-Kompatibilität (kein
> Alembic-Migrationspfad; Tabellen werden via `create_all` angelegt).

## API-Betrieb (ohne Docker)

```bash
pip install .
DATABASE_URL=postgresql+psycopg2://... uvicorn scoredclub.api.app:app --host 0.0.0.0 --port 8000
```

Hinter einen Reverse-Proxy (nginx/Caddy) setzen und dort TLS + Auth terminieren, falls
die API über localhost hinaus erreichbar sein soll (sie hat selbst keine Auth).

## GitHub Actions

Drei Workflows liegen unter `.github/workflows/`:

| Workflow | Trigger | Zweck |
|----------|---------|-------|
| `ci.yml` | Push/PR (jeder Branch) | pytest + Offline-Pipeline-Smoke |
| `monthly-run.yml` | Cron (monatlich) + manuell | Pipeline-Lauf, committet Reports + State-DB, Artifact-Upload |
| `pages.yml` | Push auf Default-Branch + manuell | Dashboard-Daten regenerieren und auf GitHub Pages deployen |

> **Wichtige GitHub-Einschränkung:** `schedule` und `workflow_dispatch` laufen **nur für
> Workflows auf dem Default-Branch**. Solange `monthly-run.yml`/`pages.yml` nur auf einem
> Feature-Branch liegen, lassen sie sich weder planen noch auslösen (API-404). Nach dem
> Merge auf den Default-Branch werden sie aktiv. `ci.yml` (Push-Trigger) läuft auf jedem
> Branch.

### Monatlicher Lauf & Historie

`monthly-run.yml` schreibt die SQLite-DB nach `state/scoredclub.db` und committet sie
zurück, damit Score-Historie und Alerts über Läufe hinweg bestehen. Optionales Secret
`SCOREDCLUB_WEBHOOK_URL` aktiviert Alert-Webhooks.

## GitHub Pages (Dashboard)

1. Repo-**Settings → Pages → Source: „GitHub Actions"** wählen (einmalig).
2. `pages.yml` auf den Default-Branch bringen.
3. Bei Push (oder manuell) regeneriert der Workflow die Daten aus der jüngsten
   Research-Datei und deployt `frontend/`.

> Private Repos benötigen einen Plan, der GitHub Pages einschließt.

### Alternativer Static-Host

Jeder Static-Host funktioniert (Netlify, Cloudflare Pages, S3, nginx):

```bash
python scripts/refresh_frontend_data.py
# frontend/ ausliefern (z. B. rsync nach /var/www, oder netlify deploy)
```

## Scheduling ohne GitHub

Cron auf einem eigenen Server:

```cron
0 4 1 * * cd /opt/scoredclub && /opt/scoredclub/.venv/bin/scoredclub run --research data/research/latest.json
```

`output/next_run.json` dokumentiert den nächsten geplanten Termin
(`run.next_run_interval_days`, Standard +30 Tage).

## Persistenz-Checkliste

| Was | Wo | Versionieren? |
|-----|----|--------------:|
| Reports | `output/` | ja (Artefakt) |
| Research-Daten | `data/research/` | ja |
| SQLite-DB (lokal) | `data/scoredclub.db` | nein (gitignored) |
| SQLite-DB (CI-Historie) | `state/scoredclub.db` | ja (vom Workflow committet) |
| Dashboard-Daten | `frontend/data/entities.json` | ja |
