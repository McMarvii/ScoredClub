# HTTP-API

Read-only FastAPI (`src/scoredclub/api/app.py`). Sie liefert dieselben Daten wie die
Reports in strukturierter Form — gedacht für lokale Tools, Dashboards oder Integrationen.

> **Sicherheit:** Die API hat in V1 **keine Authentifizierung** und ist für den lokalen/
> Docker-Betrieb gedacht. Wird sie über localhost hinaus exponiert, gehört eine Auth-Schicht
> davor (Reverse-Proxy mit Basic-Auth/OAuth o. Ä.).

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
Vollständiges Profil + letzter Breakdown + Score-Historie.

```bash
curl http://127.0.0.1:8000/entities/berghain
```
```json
{ "entity_id": "berghain", "name": "Berghain", "...": "...",
  "profile": { "...": "vollständiges EntityProfile" },
  "latest_breakdown": { "total": 86.1, "tier": "TOP-TIER", "...": "..." },
  "score_history": [ { "run_id": 1, "score": 86.1, "tier": "TOP-TIER" } ] }
```
`404`, wenn die Entität nicht existiert.

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
