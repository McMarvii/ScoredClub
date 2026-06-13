# Konfiguration

Die Konfiguration kommt aus `config/berlin_techno_agent_config.json`. Der Pfad ist über
`SCOREDCLUB_CONFIG` oder die Option `--config` überschreibbar. Umgebungsvariablen haben
für Laufzeit-/Geheimwerte Vorrang. Lader: `src/scoredclub/config.py` (pydantic-settings).

## Vollständige Standardkonfiguration

```json
{
  "scoring": {
    "weights": {
      "event_activity": 0.20,
      "online_reach": 0.20,
      "press": 0.15,
      "community": 0.15,
      "networking": 0.10,
      "continuity": 0.10,
      "safety": 0.10
    },
    "bonus_per_item": 5,
    "bonus_cap": 15,
    "malus_per_incident": 5,
    "malus_cap": 15,
    "tier_thresholds": { "top": 75, "mid": 50, "emerging": 25 },
    "inactive_after_days": 180
  },
  "alerts": {
    "score_change_threshold": 10,
    "webhook_url": null
  },
  "sources": {
    "clubcommission_url": "https://www.clubcommission.de/",
    "ra_graphql_url": "https://ra.co/graphql",
    "reddit_search_url": "https://www.reddit.com/search.json",
    "reddit_enabled": true,
    "reddit_max_threads": 5,
    "extra_sources": []
  },
  "run": {
    "next_run_interval_days": 30,
    "output_dir": "output"
  },
  "trending": {
    "momentum_window": 4,
    "stable_epsilon": 1.0,
    "movers_limit": 5
  }
}
```

## Felder

### `scoring`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `weights.*` | Gewichte der Dimensionen A–G. Sollten zu 1.0 summieren. |
| `bonus_per_item` / `bonus_cap` | Punkte je Bonuskriterium / Obergrenze. |
| `malus_per_incident` / `malus_cap` | Punkte je Vorfall / Obergrenze. |
| `tier_thresholds.{top,mid,emerging}` | Score-Schwellen der Tiers. |
| `inactive_after_days` | Tage ohne Event, ab denen eine Entität als inaktiv gilt. |

Details der Wirkung: [Scoring-Modell](scoring.md).

### `alerts`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `score_change_threshold` | Δ-Score, ab dem ein Alert ausgelöst wird (Standard 10). |
| `webhook_url` | Ziel-URL für Alert-Webhooks (oder `null`). |

### `sources`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `clubcommission_url` | Startseite mit Members-Bereich. |
| `ra_graphql_url` | Resident-Advisor-GraphQL-Endpunkt. |
| `reddit_search_url` | Reddit-Such-API für den Enrichment-Collector. |
| `reddit_enabled` | Reddit-Collector an/aus. |
| `reddit_max_threads` | Max. Threads pro Entität. |
| `extra_sources` | Reserviert für zusätzliche Quellen. |

### `run`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `next_run_interval_days` | Abstand bis zum nächsten geplanten Lauf (in `next_run.json`). |
| `output_dir` | Zielordner für Reports. |

### `trending`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `momentum_window` | Anzahl der letzten Läufe für Momentum/Sparkline. |
| `stable_epsilon` | Schwelle für steigend/fallend vs. stabil. |
| `movers_limit` | Anzahl gelisteter Auf-/Absteiger. |

Details: [Trending](trending.md).

## Umgebungsvariablen

| Variable | Vorrang vor | Beschreibung |
|----------|-------------|--------------|
| `DATABASE_URL` | `sqlite:///data/scoredclub.db` | SQLAlchemy-Verbindung. SQLite oder Postgres (`postgresql+psycopg2://user:pass@host/db`). |
| `SCOREDCLUB_WEBHOOK_URL` | `alerts.webhook_url` | Webhook für Alerts. |
| `SCOREDCLUB_CONFIG` | Standardpfad | Pfad zur Konfigurationsdatei. |

> **Sicherheitshinweis:** Geheimnisse (Webhook-URLs, künftige API-Tokens) gehören in
> Umgebungsvariablen bzw. CI-Secrets, nicht in die eingecheckte Config.

## Beispiele

**Online-Reichweite stärker gewichten:**
```json
{ "scoring": { "weights": {
  "event_activity": 0.15, "online_reach": 0.30, "press": 0.15,
  "community": 0.10, "networking": 0.10, "continuity": 0.10, "safety": 0.10 } } }
```

**Striktere Inaktivitäts-Schwelle und sensiblere Alerts:**
```json
{ "scoring": { "inactive_after_days": 90 }, "alerts": { "score_change_threshold": 5 } }
```

**PostgreSQL nutzen:**
```bash
export DATABASE_URL="postgresql+psycopg2://scoredclub:scoredclub@localhost:5432/scoredclub"
scoredclub init-db && scoredclub run --research data/research/latest.json
```
