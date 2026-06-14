# HTTP-API

FastAPI (`src/scoredclub/api/app.py`). Liefert dieselben Daten wie die Reports in
strukturierter Form — gedacht für lokale Tools, Dashboards oder Integrationen.

> **Sicherheit:** **Lese-Endpunkte** sind offen (für lokalen/Docker-Betrieb; ein
> Reverse-Proxy schützt sie bei öffentlicher Exposition). **Schreib-/Trigger-Endpunkte**
> (`POST /ingest`, `POST /runs`) sind per **API-Key** geschützt: `SCOREDCLUB_API_KEY` im
> Environment setzen, dann den Header `X-API-Key: <key>` mitsenden. Ohne gesetzten Key sind
> die Schreib-Endpunkte deaktiviert (503). Der Key-Vergleich ist konstant-zeitig.

## Starten

```bash
scoredclub serve --host 127.0.0.1 --port 8000
# oder direkt:
uvicorn scoredclub.api.app:app --host 0.0.0.0 --port 8000
```

Die API liest dieselbe `DATABASE_URL` wie die CLI. Interaktive Doku (Swagger UI) unter
`/docs`, OpenAPI-Schema unter `/openapi.json` (von FastAPI automatisch bereitgestellt).

## Endpunkte

### `GET /health`
```json
{ "status": "ok", "version": "0.1.0" }
```

## Schreib-/Trigger-Endpunkte (API-Key erforderlich)

Alle benötigen `X-API-Key: <SCOREDCLUB_API_KEY>`. Ohne konfigurierten Key → `503`;
falscher/fehlender Header → `401`.

### `POST /ingest`
Validiert und upsertet Research-Entitäten (JSON-Array oder `{"entities": [...]}`) —
derselbe Pfad wie `scoredclub ingest`, nur über HTTP.

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H "X-API-Key: $SCOREDCLUB_API_KEY" -H "Content-Type: application/json" \
  -d '[{"name":"Neuer Club","type":"club","status":"active"}]'
```
```json
{ "ok": true, "ingested": ["neuer-club"], "new_entities": ["neuer-club"],
  "merged_entities": [], "errors": [] }
```

### `POST /runs`
Löst einen Pipeline-Lauf aus (synchron). Optionaler Body:

```json
{ "skip_collectors": true, "date": "2026-07-13", "research": [ /* optionale Entitäten */ ] }
```
Wird `research` mitgegeben, wird es vorher eingespielt. Antwort:

```json
{ "run_id": 2, "entities_tracked": 25, "new_entities": 1, "alerts": 0,
  "report_md": "output/berlin_techno_check_2026-07-13.md", "warnings": [] }
```

> `skip_collectors` ist standardmäßig `true`, damit API-Läufe schnell und deterministisch
> sind. Für einen Lauf mit Netzwerk-Collectorn `false` setzen.

**Asynchron (Background-Job):** Mit `"async": true` blockiert der Request nicht — der Lauf
läuft in einem Hintergrund-Thread, der Endpunkt antwortet sofort mit `202` und einer
`job_id`:

```json
{ "job_id": "a1b2c3…", "status": "queued" }
```

### `POST /compare`
A/B-Vergleich zweier Scoring-Konfigurationen über die aktuellen Entitäten (read-only, aber
API-Key erforderlich). Body: `config_b` (Pflicht, der `scoring`-Block der Variante),
optional `config_a` (Basis; null = aktive Konfiguration), `date`, `label_a`, `label_b`.

```bash
curl -X POST http://127.0.0.1:8000/compare \
  -H "X-API-Key: $SCOREDCLUB_API_KEY" -H "Content-Type: application/json" \
  -d '{"config_b": {"weights": {"online_reach": 0.4, "event_activity": 0.2, "press": 0.1,
       "community": 0.1, "networking": 0.05, "continuity": 0.1, "safety": 0.05}},
       "label_a": "aktiv", "label_b": "reach"}'
```
Antwort = dasselbe Format wie `scoredclub compare` (`rank_correlation`, `mean_abs_delta`,
`tier_change_count`, `entities[]` mit Score-/Rang-Deltas). Siehe [A/B-Testing](ab-testing.md).

### `GET /jobs/{job_id}`
Status eines Background-Jobs (offen, die `job_id` wirkt als Capability-Token). `404` bei
unbekannter ID.

```json
{ "job_id": "a1b2c3…", "status": "done",
  "result": { "run_id": 3, "entities_tracked": 25, "new_entities": 1, "alerts": 0,
              "report_md": "output/…", "warnings": [] } }
```
`status` ∈ `queued | running | done | error` (bei `error` zusätzlich ein `error`-Feld).

> Der Job-Runner ist in-process (kein externer Broker); Job-Status geht bei einem
> Server-Neustart verloren. Für persistente/verteilte Jobs siehe [Roadmap v2](roadmap-v2.md).

## Lese-Endpunkte

### `GET /entities`
Liste der Entitäten (Kurzform), absteigend nach Score.

**Query-Parameter:** `type`, `tier`, `status`, `min_score` (alle optional).

```bash
curl "http://127.0.0.1:8000/entities?type=club&min_score=50"
```
```json
[
  { "entity_id": "tresor", "name": "Tresor", "type": "club", "status": "active",
    "district": "Mitte", "tier": "TOP-TIER", "current_score": 87.8,
    "last_event_date": "2026-06-12" }
]
```

### `GET /entities/{entity_id}`
Vollständiges Profil + letzter Breakdown + Score-Historie + Follower-Wachstum je Plattform
(aus `follower_history`, leer wenn keine Zeitreihe vorliegt).

```bash
curl http://127.0.0.1:8000/entities/berghain
```
```json
{ "entity_id": "berghain", "name": "Berghain", "...": "...",
  "profile": { "...": "vollständiges EntityProfile" },
  "latest_breakdown": { "total": 86.1, "tier": "TOP-TIER", "...": "..." },
  "score_history": [ { "run_id": 1, "score": 86.1, "tier": "TOP-TIER" } ],
  "follower_growth": { "instagram": { "start": 1000, "end": 1400, "delta": 400, "pct": 40.0, "slope": 200.0, "points": 2 } } }
```
`404`, wenn die Entität nicht existiert.

### `GET /trending`
Trend-Leaderboard des letzten Laufs: pro Entität Richtung, Score-/Rang-Delta und Rang.
Siehe [Trending](trending.md).

```json
{ "run_id": 2, "entities": [
  { "entity_id": "tresor", "name": "Tresor", "run_id": 2, "score": 87.8, "rank": 1,
    "score_delta": 0.0, "rank_delta": 0, "momentum": 0.0, "direction": "stable" } ] }
```

### `GET /trending/movers`
Top-Auf- und -Absteiger des letzten Laufs (nach Score-Delta). **Query:** `limit` (1–50, Standard 5).

```json
{ "run_id": 2,
  "risers": [ { "entity_id": "oxi", "name": "OXI", "score": 55.1, "score_delta": 31.9,
                "rank": 10, "rank_delta": 14, "direction": "rising", "...": "..." } ],
  "fallers": [ { "entity_id": "kitkat-club", "name": "KitKat Club", "score_delta": -8.4, "...": "..." } ] }
```

### `GET /entities/{entity_id}/trend`
Vollständige Trend-Historie einer Entität (Sparkline über alle Läufe). `404` bei unbekannter Entität.

```json
{ "entity_id": "oxi", "name": "OXI", "sparkline": [23.2, 55.1],
  "history": [ { "run_id": 1, "score": 23.2, "rank": 24, "direction": "new", "...": "..." } ],
  "latest": { "run_id": 2, "score": 55.1, "direction": "rising", "...": "..." } }
```

### `GET /analytics`
Breakout-/Anomalie-Erkennung (dynamische Baseline), Karrierephase (Perzentil) und
Kurzfrist-Forecast pro Entität, berechnet aus der Score-Historie. Siehe [Analytics](analytics.md).

```json
{ "runs_considered": 3,
  "entities": [
    { "entity_id": "oxi", "name": "OXI", "current_score": 60.0, "percentile": 100.0,
      "career_phase": "elite",
      "breakout": { "bucket": "explosive", "slope": 10.0, "z_score": 10.0 },
      "forecast": { "projected_score": 70.0, "slope": 10.0, "rising_soon": true } } ],
  "breakouts": [ { "entity_id": "oxi", "...": "..." } ] }
```

### `GET /clubsterben`
Kulturökosystem-Register: Eröffnungen/Schließungen, Ursachen, Jahresverlauf und gefährdete
Venues aus den `lifecycle_events`/`displacement_signals`. Siehe [Clubsterben-Register](clubsterben.md).

```json
{ "openings": 3, "closures": 5, "net_change": -2,
  "closures_by_cause": { "rent": 3, "redevelopment": 2 },
  "by_year": { "2024": { "openings": 2, "closures": 1 } },
  "at_risk": [ { "entity_id": "x", "name": "X", "status": "inactive",
                 "displacement_signals": ["rent_increase"] } ],
  "recent_events": [ { "entity_id": "x", "date": "2025-03-01", "event_type": "closure", "cause": "rent" } ] }
```

### `GET /export.csv`
Alle Entitäten als CSV (`text/csv`): Summary-Felder + gewichtete Punkte je Scoring-Dimension
aus dem letzten Snapshot. Spaltenreihenfolge stabil, Dimensionsspalten alphabetisch angehängt.

### `GET /feed.xml`
RSS-2.0-Feed der jüngsten Alerts (`application/rss+xml`). **Query:** `limit` (1–200, Standard 50).
Ein Push-Kanal über Webhooks hinaus — in jedem RSS-Reader abonnierbar.

### `GET /graph`
Booking-/Kollaborations-Graph-Metriken (Top-Venues, -DJs, geteilte Bookings, Komponenten).
**Query:** `include_graph` (vollständige Knoten/Kanten anhängen), `top` (1–50, Standard 10).
Siehe [Graph](graph.md).

```json
{ "metrics": {
    "node_count": 40, "edge_count": 60, "entity_nodes": 26, "external_nodes": 14,
    "components": 3,
    "top_venues": [ { "id": "berghain", "label": "Berghain", "artist_count": 5 } ],
    "top_djs": [ { "id": "dettmann", "label": "Marcel Dettmann", "booker_count": 3 } ],
    "shared_bookings": [ { "a": "berghain", "b": "tresor", "shared_djs": 2, "...": "..." } ] } }
```

### `GET /runs`
Liste aller Läufe (neueste zuerst).

### `GET /runs/{id}`
Details eines Laufs inkl. Scores pro Entität. `404` bei unbekanntem Lauf.

### `GET /runs/latest/report`
Liefert den neuesten Markdown-Report als `text/markdown`. `404`, wenn noch kein Report
existiert.

### `GET /alerts`
Alerts, neueste zuerst. **Query-Parameter:** `run_id` (optional).

```json
[ { "id": 2, "run_id": 2, "entity_id": "berghain", "alert_type": "score_change",
    "message": "Berghain: Score 10.0 -> 88.23 (Δ +78.2)",
    "old_value": "10.0", "new_value": "88.23", "delta": 78.2, "webhook_delivered": false } ]
```

## Beispiel-Integration

```bash
# Alle Top-Tier-Clubs als Namen:
curl -s "http://127.0.0.1:8000/entities?tier=TOP-TIER&type=club" | jq -r '.[].name'
```

## Hinweise

- Alle Endpunkte sind idempotent und seiteneffektfrei (reines Lesen).
- Die API erzeugt keine Läufe — dafür ist die CLI (`scoredclub run`) zuständig.
- `GET /runs/latest/report` liest die Markdown-Datei vom Pfad, den der Lauf gespeichert
  hat; existiert die Datei nicht mehr, kommt `404`.
