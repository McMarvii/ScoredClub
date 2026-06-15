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
    "webhook_url": null,
    "slack_webhook_url": null,
    "email": {
      "enabled": false,
      "smtp_host": "localhost",
      "smtp_port": 587,
      "use_tls": true,
      "username": null,
      "from_addr": "scoredclub@localhost",
      "to_addrs": [],
      "subject_prefix": "[ScoredClub]"
    }
  },
  "sources": {
    "clubcommission_url": "https://www.clubcommission.de/",
    "ra_graphql_url": "https://ra.co/graphql",
    "reddit_search_url": "https://www.reddit.com/search.json",
    "reddit_enabled": true,
    "reddit_max_threads": 5,
    "bandsintown_url": "https://rest.bandsintown.com/artists",
    "bandsintown_max_artists": 25,
    "songkick_url": "https://api.songkick.com/api/3.0",
    "songkick_max_artists": 25,
    "soundcloud_url": "https://api.soundcloud.com",
    "soundcloud_max_entities": 25,
    "soundcloud_max_tracks": 10,
    "mixcloud_enabled": false,
    "mixcloud_url": "https://api.mixcloud.com",
    "mixcloud_max_entities": 25,
    "mixcloud_max_sets": 10,
    "sentiment_enabled": false,
    "funding_feed_path": "data/funding/berlin_funding.json",
    "follower_audit_url": "https://api.follower-audit.example/v1/audit",
    "follower_audit_max_entities": 25,
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
  },
  "retention": {
    "enabled": false,
    "community_days": 365
  },
  "authenticity": {
    "capture_history": false
  },
  "analytics": {
    "history_window": 12,
    "breakout_baseline_floor": 1.0,
    "growth_z": 1.0,
    "strong_z": 2.0,
    "explosive_z": 3.0,
    "forecast_epsilon": 0.5,
    "elite_percentile": 90.0,
    "established_percentile": 70.0,
    "emerging_percentile": 40.0
  },
  "llm": {
    "enabled": false,
    "model": "claude-opus-4-8",
    "max_entities": 8,
    "effort": "medium",
    "research_max_continuations": 4
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
| `confidence.low_confidence_threshold` | Konfidenz, unter der „⚠ geringe Datenbasis" markiert wird (Default 50). |
| `confidence.freshness_full_days` | Verifiziert innerhalb dieser Tage → volle Frische. |
| `confidence.freshness_floor` | Untergrenze der Frische bei alten Daten. |
| `confidence.unknown_verification_confidence` | Frische ohne `last_verification`. |
| `confidence.completeness_weight` / `freshness_weight` | Blend Vollständigkeit ↔ Frische. |

Details der Wirkung: [Scoring-Modell](scoring.md) (inkl. Datenkonfidenz).

### `alerts`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `score_change_threshold` | Δ-Score, ab dem ein Alert ausgelöst wird (Standard 10). |
| `webhook_url` | Ziel-URL für Alert-Webhooks (oder `null`). |
| `slack_webhook_url` | Slack-Incoming-Webhook für eine Digest-Nachricht pro Lauf (oder `null`). |
| `email` | SMTP-Digest-Mails (`enabled`, `smtp_host`/`smtp_port`, `use_tls`, `username`, `from_addr`, `to_addrs`, `subject_prefix`). Passwort via `SCOREDCLUB_SMTP_PASSWORD`. |

### `sources`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `clubcommission_url` | Startseite mit Members-Bereich. |
| `ra_graphql_url` | Resident-Advisor-GraphQL-Endpunkt. |
| `reddit_search_url` | Öffentliche Reddit-Such-API (Public-Fallback). |
| `reddit_oauth_token_url` / `reddit_oauth_search_url` | Reddit-OAuth-Endpunkte (genutzt, wenn `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` gesetzt sind). |
| `reddit_enabled` | Reddit-Collector an/aus. |
| `reddit_max_threads` | Max. Threads pro Entität. |
| `bandsintown_url` | Basis-URL der Bandsintown-Artists-API (Enrichment für `artist`-Entitäten). |
| `bandsintown_max_artists` | Max. Artists pro Lauf, die über Bandsintown angereichert werden. |
| `songkick_url` / `songkick_max_artists` | Songkick-API (zweite sanktionierte Event-Quelle für Artists). |
| `soundcloud_url` / `soundcloud_max_entities` / `soundcloud_max_tracks` | SoundCloud-API: füllt `top_tracks` + Follower (no-op ohne `SOUNDCLOUD_CLIENT_ID` / ohne Handle). |
| `mixcloud_enabled` / `mixcloud_url` / `mixcloud_max_entities` / `mixcloud_max_sets` | Mixcloud-API: füllt `top_sets` + Follower (off by default; braucht ein Mixcloud-Handle). |
| `sentiment_enabled` | Offline-Sentiment-Collector an/aus (füllt nur unbekannte Hints). |
| `funding_feed_path` | JSON-Datei des Förder-/Policy-Feeds (siehe [Förder-Feed](funding.md)). |
| `follower_audit_url` / `follower_audit_max_entities` | Externer Follower-Audit-Provider (siehe [Follower-Echtheit](authenticity.md)). |
| `extra_sources` | Reserviert für zusätzliche Quellen. |

### `run`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `next_run_interval_days` | Abstand bis zum nächsten geplanten Lauf (in `next_run.json`). |
| `output_dir` | Zielordner für Reports. |
| `geocode_districts` | `geo` aus dem Bezirk befüllen (statische Zentren) für die Kartenansicht. |

### `trending`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `momentum_window` | Anzahl der letzten Läufe für Momentum/Sparkline. |
| `stable_epsilon` | Schwelle für steigend/fallend vs. stabil. |
| `movers_limit` | Anzahl gelisteter Auf-/Absteiger. |

Details: [Trending](trending.md).

### `analytics`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `history_window` | Läufe für Breakout/Forecast (0 = gesamte Historie). |
| `breakout_baseline_floor` | Untergrenze der dynamischen Baseline (Punkte/Lauf). |
| `growth_z` / `strong_z` / `explosive_z` | z-Schwellen der Breakout-Buckets. |
| `forecast_epsilon` | Mindeststeigung für das „rising soon"-Flag. |
| `elite_percentile` / `established_percentile` / `emerging_percentile` | Perzentil-Grenzen der Karrierephasen. |

Details: [Analytics](analytics.md).

### `retention`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `enabled` | GDPR-Retention aktiv (informativ; angewandt via `scoredclub retention`). |
| `community_days` | Aufbewahrungsfenster für Community-/Personendaten (Tage). |

Details: [Compliance](compliance.md).

### `authenticity`
| Schlüssel | Bedeutung |
|-----------|-----------|
| `capture_history` | Bei jedem Lauf aktuelle Follower-Zahlen in `follower_history` fortschreiben (Standard aus). |

Informatives Modul, **ohne Scoring-Einfluss**. Details: [Follower-Echtheit](authenticity.md).

### `llm`
Agentischer LLM-Research-Collector (optional, standardmäßig aus). Braucht
`pip install -e ".[llm]"` und `ANTHROPIC_API_KEY`.

| Schlüssel | Bedeutung |
|-----------|-----------|
| `enabled` | Collector an/aus (Default `false`). |
| `model` | Claude-Modell (Default `claude-opus-4-8`). |
| `max_entities` | Max. Entitäten pro Run (0 = alle), stalste zuerst. |
| `effort` | `low`/`medium`/`high`/`max`. |
| `research_max_continuations` | Continuation-Cap für die serverseitige web_search-Schleife. |

Details: [Datenerhebung](data-collection.md).

## Umgebungsvariablen

| Variable | Vorrang vor | Beschreibung |
|----------|-------------|--------------|
| `DATABASE_URL` | `sqlite:///data/scoredclub.db` | SQLAlchemy-Verbindung. SQLite oder Postgres (`postgresql+psycopg2://user:pass@host/db`). |
| `SCOREDCLUB_WEBHOOK_URL` | `alerts.webhook_url` | Webhook für Alerts. |
| `SCOREDCLUB_SLACK_WEBHOOK_URL` | `alerts.slack_webhook_url` | Slack-Webhook für den Alert-Digest. |
| `SCOREDCLUB_SMTP_PASSWORD` | — | Passwort für den SMTP-Login der Digest-Mails. |
| `SCOREDCLUB_CONFIG` | Standardpfad | Pfad zur Konfigurationsdatei. |
| `SCOREDCLUB_API_KEY` | — | Aktiviert die Schreib-/Trigger-Endpunkte der API (`X-API-Key`). Ohne Key sind sie deaktiviert. |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | — | Reddit-OAuth-App; aktiviert den authentifizierten Reddit-Collector (Dimension D). |
| `REDDIT_USER_AGENT` | Default-UA | Eindeutiger Reddit-User-Agent (von Reddit verlangt). |
| `BANDSINTOWN_APP_ID` | — | Aktiviert den Bandsintown-Collector (Event-/Booking-Daten für `artist`-Entitäten). |
| `SONGKICK_API_KEY` | — | Aktiviert den Songkick-Collector (zweite Event-Quelle für `artist`-Entitäten). |
| `FOLLOWER_AUDIT_API_KEY` | — | Aktiviert den externen Follower-Audit-Collector (Fake-Anteil/Engagement/Verlauf). |
| `ANTHROPIC_API_KEY` | — | Für den agentischen LLM-Research-Collector (`llm.enabled`). |

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
