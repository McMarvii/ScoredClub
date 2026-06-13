# ScoredClub

**Berlin Techno Collective & Club Intelligence System** — trackt Berliner Techno-Clubs,
Kollektive, Labels und Partyreihen, berechnet einen Relevanz-Score (0–100), hält die
Score-Historie über Runs hinweg fest und erzeugt menschen- wie maschinenlesbare Reports
inklusive Alerts bei starken Score- oder Status-Änderungen.

> 📖 **Ausführliche Dokumentation:** [`docs/`](docs/README.md) — Installation, ein
> komplettes [How-To](docs/howto.md), [Scoring-Modell](docs/scoring.md),
> [Trending](docs/trending.md), [A/B-Testing](docs/ab-testing.md),
> [Datenschema](docs/schema.md), [CLI](docs/cli.md), [API](docs/api.md),
> [Dashboard](docs/frontend.md), [Konfiguration](docs/configuration.md),
> [Deployment](docs/deployment.md) und [Troubleshooting](docs/troubleshooting.md).

## Architektur

```
LLM-Research (Claude + WebSearch)  ──┐
Clubcommission-Scraper               ├──► Ingest/Dedup ──► SQLite/PostgreSQL ──► Scoring ──► Diff/Alerts ──► Reports (MD+JSON)
Resident-Advisor-Collector (best effort) ┘                                          │
                                                                              Webhook (optional)
```

- **Hybrid-Datenerhebung:** Der zuverlässige Pfad ist der *LLM-Research-Ingest*
  (`scoredclub ingest research.json`): ein Research-Agent befüllt das Entity-Schema per
  Webrecherche, das System validiert und merged. Netzwerk-Collector sind best effort und
  degradieren bei Fehlern zu Warnungen — sie brechen einen Run nie ab:
  - *Discovery-Collector* (Clubcommission, RA-GraphQL) finden ggf. neue Entitäten.
  - *Enrichment-Collector* reichern bestehende Entitäten an: der **agentische
    `LLMResearchCollector`** (optional, `[llm]`-Extra + `ANTHROPIC_API_KEY`) recherchiert pro
    Entität via Claude-API + web_search und befüllt das Schema automatisch — er ersetzt den
    manuellen Research-Schritt; der Reddit-Collector füllt `community.reddit_threads` (Dimension D).
    In Sandbox-/Offline-Umgebungen sind diese Quellen oft geblockt; dann degradieren sie zu Warnungen.
- **Dedup:** Namensnormalisierung (Diacritics, Sonderzeichen, Füllwörter), Alias-Tabelle
  für die Seed-Entitäten, konservatives Fuzzy-Matching (nur mit Korroboration über
  Bezirk/Website/Instagram).
- **Historie:** Jeder Run schreibt Score-Snapshots; der Vergleich zum Vor-Run erzeugt
  Alerts (Score-Änderung > ±10, Statuswechsel, neue Entität) — optional per Webhook.

## Scoring-Modell

Jede Dimension liefert einen normalisierten Subscore 0–100; der Basis-Score ist die
gewichtete Summe (Gewichte summieren zu 1.0, konfigurierbar). Die im Report gezeigten
*Punkte* sind `Gewicht × Subscore`, sodass die Maxima der Spec entsprechen:

| Dim | Dimension            | Gewicht | Max Punkte |
|-----|----------------------|--------:|-----------:|
| A   | Event-Aktivität      |    0.20 |         20 |
| B   | Online-Reichweite    |    0.20 |         20 |
| C   | Presse-Präsenz       |    0.15 |         15 |
| D   | Community-Resonanz   |    0.15 |         15 |
| E   | Szene-Vernetzung     |    0.10 |         10 |
| F   | Kontinuität          |    0.10 |         10 |
| G   | Safety & Inclusivity |    0.10 |         10 |

`SCORE = clamp(Σ(wᵢ·subscoreᵢ) + Bonus − Malus, 0, 100)`

- **Bonus** (+5 je Kriterium, max +15): Clubcommission/UNESCO/Kulturförderung · eigenes
  Label/Podcast-Reihe · internationales Booking.
- **Malus** (−5 je Vorfall, Cap konfigurierbar): dokumentierte Vorfälle, Inaktivität.
- **Tiers:** TOP-TIER ≥ 75 · MID-TIER 50–74 · EMERGING 25–49 · INAKTIV/GESCHLOSSEN < 25
  oder > 180 Tage ohne Event oder Status inactive/closed.

Details und Bänder: `src/scoredclub/scoring/rubric.py`. Gewichte/Schwellwerte:
`config/berlin_techno_agent_config.json`.

## Installation & Nutzung

```bash
pip install -e ".[dev]"          # Entwicklung (inkl. pytest)
pytest                           # Tests

scoredclub init-db               # Tabellen anlegen
scoredclub seed                  # 20 Berliner Seed-Entitäten laden
scoredclub ingest research.json --dry-run   # Research-JSON validieren
scoredclub run --research research.json     # kompletter Pipeline-Run
scoredclub run --skip-collectors            # ohne Netzwerk-Collector (Sandbox/CI)
scoredclub list --tier TOP-TIER
scoredclub show berghain         # Profil + Score-Historie
scoredclub trending              # Auf-/Absteiger + Leaderboard (braucht ≥2 Runs)
scoredclub compare --config-b config/variants/reach_heavy.json   # Scoring-A/B-Vergleich
scoredclub serve                 # FastAPI auf http://127.0.0.1:8000
```

Outputs pro Run:

- `output/berlin_techno_check_[DATUM].md` — Report nach Tiers mit Score-Details und Zusammenfassung
- `output/berlin_techno_entities_[DATUM].json` — alle Profile + Score-Breakdowns
- `output/next_run.json` — Scheduling-Metadaten, Score-Änderungen, Alerts

## Research-JSON (LLM-Pfad)

Format: JSON-Array oder `{"entities": [...]}` mit Objekten gemäß
`scoredclub.schemas.EntityProfile` (siehe `tests/fixtures/sample_research.json`).
Unbekannte Felder werden ignoriert, unbekannte Werte bleiben `null` — die Rubriken
tolerieren fehlende Daten. Ungültige Einträge werden mit Index gemeldet, gültige
trotzdem ingestiert (partial ingest).

## API

Read-only (V1 ohne Auth — für lokalen/Docker-Betrieb gedacht):

- `GET /entities?type=&tier=&status=&min_score=`
- `GET /entities/{entity_id}` — Profil, letzter Breakdown, Score-Historie
- `GET /entities/{entity_id}/trend` — Trend-Historie (Sparkline)
- `GET /trending`, `GET /trending/movers?limit=` — Leaderboard & Auf-/Absteiger
- `GET /runs`, `GET /runs/{id}`, `GET /runs/latest/report` (Markdown)
- `GET /alerts?run_id=`
- `GET /health`

## Docker

```bash
docker compose up --build               # API auf :8000, SQLite in ./data
docker compose run app scoredclub run   # einmaliger Pipeline-Run
docker compose --profile postgres up    # mit PostgreSQL (DATABASE_URL umstellen)
```

## Konfiguration

`config/berlin_techno_agent_config.json` (Pfad via `SCOREDCLUB_CONFIG` überschreibbar);
Env-Variablen haben Vorrang:

- `DATABASE_URL` — z. B. `postgresql+psycopg2://user:pass@host/db` (Default: SQLite)
- `SCOREDCLUB_WEBHOOK_URL` — Webhook-Endpoint für Alerts (Slack/Matrix/Telegram-Bridge)

## Dashboard (Frontend)

Ein statisches, dauerhaft hostbares Web-Dashboard liegt unter `frontend/` (reines
HTML/CSS/JS, kein Build-Schritt). Es visualisiert die Score-Daten mit Tier-/Typ-Filtern,
Suche und Detail-Dialogen (Score-Breakdown A–G, Bonus/Malus, Quellen). Deployment via
GitHub Pages (`.github/workflows/pages.yml`) oder jeden Static-Host. Details:
[`frontend/README.md`](frontend/README.md).

## CI & Scheduling

Zwei GitHub-Workflows liegen unter `.github/workflows/`:

- **`ci.yml`** — pytest + Offline-Pipeline-Smoke bei jedem Push/PR (läuft auf jedem Branch).
- **`monthly-run.yml`** — monatlicher Lauf (Cron) bzw. manuell via `workflow_dispatch`;
  committet Reports und die State-DB unter `state/` zurück und lädt Reports als Artifact hoch.
  **GitHub-Einschränkung:** `schedule` und `workflow_dispatch` laufen nur für Workflows auf
  dem **Default-Branch**. Solange `monthly-run.yml` nur auf einem Feature-Branch liegt, lässt
  er sich weder planen noch auslösen (API-404) — dafür auf den Default-Branch mergen.

Ohne GitHub Actions reicht ein lokaler Cron (`output/next_run.json` dokumentiert die Kadenz,
+30 Tage, konfigurierbar):

```cron
0 4 1 * * cd /opt/scoredclub && scoredclub run --research data/research/latest.json
```

## Bewusste V1-Vereinfachungen

- Keine Alembic-Migrationen (`create_all`); Postgres = Connection-String-Kompatibilität.
- Geo-Koordinaten optional, kein Geocoding; Bezirk ist die Orts-Granularität.
- Community-Sentiment ist ein Researcher-Hint (Enum), kein NLP.
- RA-Collector scheitert erwartbar an Bot-Protection; der LLM-Research-Pfad ist die
  maßgebliche Quelle für RA-Daten.
- Keine API-Auth.
