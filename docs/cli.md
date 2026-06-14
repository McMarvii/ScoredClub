# CLI-Referenz

Einstiegspunkt: `scoredclub` (definiert in `src/scoredclub/cli.py`, Typer-App).
Jeder Befehl akzeptiert `--config PATH`, um eine alternative Konfigurationsdatei zu
nutzen (sonst `config/berlin_techno_agent_config.json` bzw. `SCOREDCLUB_CONFIG`).

```
scoredclub [OPTIONS] COMMAND [ARGS]...
```

## Übersicht

| Befehl | Zweck |
|--------|-------|
| `version` | Version ausgeben |
| `init-db` | Datenbanktabellen anlegen (Schnellpfad, SQLite/Dev) |
| `migrate` | Alembic-Migrationen anwenden (Postgres/Produktion) |
| `seed` | Berliner Seed-Entitäten laden |
| `ingest` | Research-JSON validieren und einspielen |
| `score` | Entitäten (neu) bewerten und Breakdown anzeigen |
| `run` | Komplette Pipeline ausführen |
| `report` | Reports eines bestehenden Laufs neu rendern |
| `list` | Entitäten auflisten |
| `show` | Profil + Score-Historie einer Entität anzeigen |
| `trending` | Auf-/Absteiger und Leaderboard des letzten Laufs |
| `analytics` | Breakout-Erkennung, Karrierephase und Forecast über die Historie |
| `graph` | Booking-/Kollaborations-Graph (Top-Venues, -DJs, geteilte Bookings) |
| `sentiment` | Lexikon-Sentiment über Community-Text einer Entität (kein Schreiben) |
| `export` | Alle Entitäten als CSV exportieren (Summary + Dimensionspunkte) |
| `retention` | Veraltete Community-/Personendaten redigieren (GDPR) |
| `clubsterben` | Kulturökosystem-Register: Eröffnungen/Schließungen, Ursachen, gefährdete Venues |
| `funding` | Förder-/Policy-Feed: Programme, Deadlines, Policy-Items |
| `compare` | Zwei Scoring-Konfigurationen vergleichen (A/B) |
| `serve` | FastAPI-Lese-API starten |

---

## `init-db`
```bash
scoredclub init-db [--config PATH]
```
Legt die Tabellen gemäß `DATABASE_URL` an (Standard `sqlite:///data/scoredclub.db`).
Idempotent.

## `migrate`
```bash
scoredclub migrate [--revision head] [--config PATH]
```
Wendet die Alembic-Migrationen auf die Datenbank aus `DATABASE_URL` an (`upgrade head`).
Der maßgebliche Weg für Postgres/Produktion. Die Migrationen sind ins Paket gebündelt,
daher funktioniert der Befehl auch aus einem installierten Wheel (kein Repo nötig).
Details: [Deployment](deployment.md).

## `seed`
```bash
scoredclub seed [--config PATH]
```
Lädt `data/seeds/berlin_seed_entities.json` (20 Entitäten) und upsertet sie. Erneutes
Ausführen erzeugt keine Duplikate (Dedup über Namensnormalisierung).

## `ingest`
```bash
scoredclub ingest FILE [--dry-run] [--config PATH]
```
Validiert eine Research-Datei (Array oder `{entities: [...]}`) gegen das
[Datenschema](schema.md) und spielt sie ein (Dedup/Merge).

- `--dry-run` — nur validieren, nichts schreiben.
- Bei ungültigen Einträgen werden Index und Grund ausgegeben; gültige Einträge werden
  trotzdem eingespielt (Partial Ingest). Exit-Code 1, wenn mindestens ein Eintrag ungültig war.

## `score`
```bash
scoredclub score [ENTITY_ID] [--config PATH]
```
Bewertet alle Entitäten (oder eine) neu und gibt den Breakdown aus, **ohne** einen Run
anzulegen oder Reports zu schreiben. Aktualisiert `current_score`/`tier` in der DB.

```
berghain   86.1 TOP-TIER   A=20.0 B=16.0 C=13.5 D=0.0 E=7.6 F=10.0 G=4.0 bonus=+15 malus=-0
```

## `run`
```bash
scoredclub run [--research PATH] [--skip-collectors] [--date YYYY-MM-DD] [--config PATH]
```
Komplette Pipeline: (optional Research einspielen) → Collectors → Scoring → Diff zum
Vorlauf → Alerts (+ optionaler Webhook) → Reports + `next_run.json`.

- `--research PATH` — Research-Datei als Eingabe.
- `--skip-collectors` — Netzwerk-Collector überspringen (reproduzierbar/offline).
- `--date YYYY-MM-DD` — Lauf-Datum (steuert Dateinamen und Stale-Logik), Standard heute.

Erzeugt in `output/`: `berlin_techno_check_<DATUM>.md`,
`berlin_techno_entities_<DATUM>.json`, `next_run.json`.

## `report`
```bash
scoredclub report [--run-id N] [--config PATH]
```
Rendert die Reports eines bestehenden Laufs neu (Standard: letzter Lauf). Nützlich, um
nach Template-Änderungen Reports zu regenerieren, ohne neu zu scoren.

## `list`
```bash
scoredclub list [--type TYPE] [--tier TIER] [--status STATUS] [--config PATH]
```
Listet Entitäten mit Score, Tier und Status. Filter:

- `--type` — `club | collective | label | series | artist`
- `--tier` — z. B. `TOP-TIER`, `MID-TIER`, `EMERGING`, `INAKTIV/GESCHLOSSEN`
- `--status` — `active | emerging | inactive | closed | unknown`

## `show`
```bash
scoredclub show ENTITY_ID [--config PATH]
```
Zeigt das vollständige Profil (JSON), den letzten Breakdown und die Score-Historie über
alle Läufe.

## `trending`
```bash
scoredclub trending [--movers N] [--config PATH]
```
Zeigt für den letzten Lauf die stärksten Auf-/Absteiger und ein Leaderboard mit
Richtungspfeilen (▲/▼/→/✦) und Rang-Änderungen. Braucht ≥ 2 Läufe für aussagekräftige
Trends. Details: [Trending](trending.md).

## `analytics`
```bash
scoredclub analytics [--breakouts-only] [--config PATH]
```
Berechnet aus der Score-Historie Breakout-/Anomalie-Buckets (dynamische Baseline),
Karrierephasen (Perzentil) und einen Kurzfrist-Forecast pro Entität. `--breakouts-only`
zeigt nur die als Ausbruch markierten Entitäten. Braucht ≥ 3 Läufe für aussagekräftige
Breakouts. Details: [Analytics](analytics.md).

## `funding`
```bash
scoredclub funding [--within N] [--config PATH]
```
Liest den Förder-/Policy-Feed (`sources.funding_feed_path`) und zeigt Programme, anstehende
Deadlines (≤ N Tage) und Policy-Items. Pendant zur API `GET /funding`. Details:
[Förder-Feed](funding.md).

## `clubsterben`
```bash
scoredclub clubsterben [--config PATH]
```
Aggregiert die `lifecycle_events`/`displacement_signals` der Entitäten zu einem Register
(Eröffnungen/Schließungen, Ursachen, Jahresverlauf, gefährdete Venues). Pendant zur API
`GET /clubsterben`. Details: [Clubsterben-Register](clubsterben.md).

## `retention`
```bash
scoredclub retention [--apply] [--days N] [--config PATH]
```
Redigiert veraltete Community-/Personendaten (Reddit-Threads, Twitter-Handles) anhand des
Aufbewahrungsfensters (`retention.community_days`). Standard ist Dry-run; `--apply` schreibt.
Details: [Compliance](compliance.md).

## `export`
```bash
scoredclub export [--output FILE.csv] [--config PATH]
```
Exportiert alle Entitäten als CSV (Summary-Felder + gewichtete Punkte je Scoring-Dimension
aus dem letzten Snapshot). Ohne `--output` nach stdout. Pendant zur API `GET /export.csv`.

## `sentiment`
```bash
scoredclub sentiment [ENTITY_ID] [--config PATH]
```
Analysiert den Community-Text (Reddit-Thread-Titel + Notizen) per Lexikon und zeigt
Polarität/Hint pro Entität — **ohne** zu schreiben. Den automatischen Hint im Lauf
aktiviert `sources.sentiment_enabled`. Details: [Sentiment](sentiment.md).

## `graph`
```bash
scoredclub graph [--export FILE.json] [--top N] [--config PATH]
```
Baut aus der `networking`-Dimension den Booking-/Kollaborations-Graphen und zeigt
Top-Venues (nach Artists), meistgebuchte DJs und geteilte Bookings (Orgs mit gemeinsamen
DJs). `--export` schreibt den vollständigen Graphen (Knoten/Kanten) als JSON. Details:
[Graph](graph.md).

## `compare`
```bash
scoredclub compare --config-b VARIANT.json [--config-a BASIS.json] [--date YYYY-MM-DD] [--no-write]
```
A/B-Vergleich: scort die aktuellen Entitäten unter zwei Scoring-Konfigurationen und zeigt
Score-/Rang-Unterschiede, Tier-Wechsel und die Spearman-Rang-Korrelation. `--config-a`
ist standardmäßig die aktive Konfiguration. Schreibt mit `--write` (Standard) einen
Vergleichs-Report in den Output-Ordner. Details: [A/B-Testing](ab-testing.md).

## `serve`
```bash
scoredclub serve [--host 127.0.0.1] [--port 8000]
```
Startet die [HTTP-API](api.md) per uvicorn. Read-only, ohne Auth (für lokalen/Docker-Betrieb).

---

## Umgebungsvariablen (für alle Befehle)

| Variable | Wirkung |
|----------|---------|
| `DATABASE_URL` | DB-Verbindung (Standard SQLite). |
| `SCOREDCLUB_CONFIG` | Pfad zur Konfigurationsdatei (von `--config` überschrieben). |
| `SCOREDCLUB_WEBHOOK_URL` | Webhook für Alerts (überschreibt `alerts.webhook_url`). |

Details: [Konfiguration](configuration.md).
