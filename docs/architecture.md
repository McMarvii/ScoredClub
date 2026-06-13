# Architektur

## Komponenten

```
                ┌─────────────────────────────────────────────────────────┐
                │                        CLI (Typer)                       │
                │   init-db · seed · ingest · score · run · report · …     │
                └───────────────┬─────────────────────────────────────────┘
                                │
   research.json ──► ingest ──► │
   Collectors    ──► collect ─► │   Pipeline (pipeline/run.py)
                                ▼
        normalize/merge ──► DB (SQLAlchemy) ──► scoring (engine + rubric)
                                │                       │
                                ▼                       ▼
                         diff vs. Vorlauf         Score-Snapshots
                                │                       │
                                ▼                       ▼
                          alerts (+Webhook)        reports/render
                                                        │
                          ┌─────────────────────────────┼──────────────────┐
                          ▼                             ▼                  ▼
                   output/*.md                 output/*.json        next_run.json
                                                        │
                                            scripts/refresh_frontend_data.py
                                                        ▼
                                            frontend/ (Static Dashboard)

                   API (FastAPI) ──► liest dieselbe DB (read-only)
```

## Module (`src/scoredclub/`)

| Modul | Verantwortung |
|-------|---------------|
| `schemas.py` | Pydantic-Modelle (`EntityProfile` + verschachtelte Typen). Kanonisches Datenformat. |
| `config.py` | Konfigurations- und Settings-Laden (JSON + Umgebungsvariablen). |
| `normalize.py` | Namensnormalisierung, Alias-Tabelle, Dedup-Matching, Merge-Politik. |
| `db/models.py` | ORM-Tabellen: `entities`, `entity_aliases`, `runs`, `score_snapshots`, `alerts`. |
| `db/session.py` | Engine/Session aus `DATABASE_URL`, `init_db()`. |
| `db/repo.py` | Upsert (mit Dedup/Merge), Queries, Snapshots, Alerts. |
| `scoring/rubric.py` | Reine Funktionen pro Dimension A–G, Bonus/Malus. |
| `scoring/engine.py` | Gewichtung, Gesamt-Score, Tier-Klassifizierung, Konfidenz. |
| `scoring/confidence.py` | Datenkonfidenz (Presence, Vollständigkeit, Frische) — confidence-aware. |
| `trending.py` | Trend-Analyse über die Score-Historie (Richtung, Momentum, Ränge, Movers). |
| `compare.py` | A/B-Vergleich zweier Scoring-Konfigurationen (Score-/Rang-Diff, Tier-Wechsel, Spearman). |
| `collectors/` | `base` (Protokoll), `clubcommission`, `resident_advisor`, `reddit`, `llm_research` (agentischer Claude-Collector), `llm_ingest`. |
| `pipeline/run.py` | Orchestrierung des kompletten Laufs. |
| `pipeline/diff.py` | Vergleich Lauf vs. Vorlauf. |
| `pipeline/alerts.py` | Alert-Erzeugung + Webhook-Zustellung. |
| `reports/render.py` | Markdown (Jinja2) + JSON + `next_run.json`. |
| `api/app.py` | Read-only FastAPI. |
| `cli.py` | Typer-Einstiegspunkt. |

## Datenmodell (DB)

- **`entities`** — eine Zeile je Entität; abfragbare Felder typisiert
  (`name_normalized`, `type`, `status`, `district`, `tier`, `current_score`,
  `last_event_date`), das vollständige Profil als JSON-Spalte (portabel SQLite/Postgres).
- **`entity_aliases`** — normalisierte Aliase (eindeutig) für schnelles Dedup.
- **`runs`** — ein Lauf (Start/Ende, Zähler, Report-Pfade).
- **`score_snapshots`** — Score je Entität je Lauf (Grundlage der Historie/Diffs),
  eindeutig pro `(run_id, entity_id)`.
- **`trend_snapshots`** — persistierte Trend-Kennzahlen je Entität je Lauf (Rang, Score-/
  Rang-Delta, Momentum, Richtung); eindeutig pro `(run_id, entity_id)`. Siehe [Trending](trending.md).
- **`alerts`** — erzeugte Alerts mit Typ und Webhook-Status.

## Designentscheidungen

- **LLM-Research als maßgebliche Quelle.** Social-Media-Zahlen (Instagram/RA) sind ohne
  API-Zugang nicht zuverlässig scrapebar. Statt fragiler Scraper befüllt ein Research-Agent
  das Schema; das System validiert, dedupliziert und scored. Netzwerk-Collector reichern
  best-effort an und brechen nie ab.
- **Reine Scoring-Funktionen.** Die Rubriken sind seiteneffektfrei und ohne DB testbar —
  der Großteil der Tests sichert das Scoring an den Bandgrenzen ab.
- **Profil als JSON-Spalte.** Das verschachtelte, sich entwickelnde Schema wird als JSON
  gespeichert; nur abfragbare Felder sind eigene Spalten. Portabel über SQLite und Postgres.
- **Fehlertolerante Collector.** Jeder Collector fängt alle Fehler ab und liefert
  Warnungen — so läuft die Pipeline auch in Sandbox-/Offline-Umgebungen durch.
- **Statisches Frontend.** Das Dashboard liest die committete JSON-Exportdatei. Kein
  Backend nötig, überall hostbar, XSS-sicher implementiert.

## Bewusste V1-Vereinfachungen

- Keine Alembic-Migrationen (`create_all`); Postgres = Connection-String-Kompatibilität.
- Geo-Koordinaten optional, kein Geocoding; Bezirk ist die Orts-Granularität.
- Community-Sentiment ist ein Researcher-Hint (Enum), kein NLP.
- RA-Collector scheitert erwartbar an Bot-Protection; LLM-Research ist die maßgebliche Quelle.
- API ohne Auth (lokaler/Docker-Betrieb).
- Kein eingebauter Scheduler — Cron/GitHub Actions übernehmen das.
