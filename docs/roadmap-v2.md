# ScoredClub — Roadmap v2

Stand: v1 ist vollständig in `main` (Scoring, Trending, A/B-Testing, Backend-API,
Dashboard, CI/Pages/Monthly-Automatisierung, ausführliche Doku, 106 Tests). Dieses
Dokument hält die Richtung für v2 fest. Es ist ein lebendes Planungsdokument, kein
Vertrag — Reihenfolge und Umfang werden iterativ angepasst.

## Ausgangslage: was v1 limitiert

Drei strukturelle Schwächen bremsen v1 — sie definieren die v2-Prioritäten:

1. **Datenbeschaffung ist halb-manuell.** Der maßgebliche Pfad ist eine von Hand bzw.
   per LLM erzeugte `research.json`. Jeder Lauf braucht Vorarbeit.
2. **Datenzugang ist lückenhaft.** Reddit/Resident Advisor sind ohne API-Keys geblockt
   → Dimension D (Community) bleibt faktisch 0; RA-Follower fehlen; Clubcommission
   liefert nur ~10 öffentlich gelistete Member.
3. **Fehlende Daten sehen aus wie geringe Relevanz.** Das Modell unterscheidet
   „unbekannt" nicht von „schlecht" (Berghain landete erst niedrig, weil Followerzahlen
   fehlten).

Alles andere ist solide Basis.

## Leitidee v2

**Von „Batch-Tool mit manueller Recherche" zu „selbst-aktualisierendem Service mit
vertrauenswürdigen Daten."**

---

## P0 — Höchster Hebel (Datenengpass & Vertrauen)

### 1. Agentischer LLM-Collector — ✅ v1 ausgeliefert
Die Webrecherche in die Pipeline holen: ein Collector, der pro Entität über die Claude-API
mit dem serverseitigen web_search-Tool + Structured Outputs das vorhandene Pydantic-Schema
selbst befüllt. Damit entfällt der manuelle `research.json`-Schritt.

- **Status:** Als `LLMResearchCollector` umgesetzt (Enrichment, standardmäßig aus,
  optionale `[llm]`-Abhängigkeit, fehlertolerant, mit gemocktem Client getestet). Siehe
  [Datenerhebung](data-collection.md) → „Agentischer LLM-Collector".
- **Offen für v2-Vollausbau:** pro Feld Quelle/Confidence mitliefern (siehe P0.3),
  Batching/Kostendeckel feiner steuern, Discovery-Modus (neue Entitäten finden), gegen
  echte API evaluieren.

### 2. Echte API-Collectors — 🟡 teilweise ausgeliefert
- **Reddit-OAuth-App → ✅ umgesetzt.** Der Reddit-Collector nutzt automatisch den
  authentifizierten `oauth.reddit.com`-Endpunkt, wenn `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`
  gesetzt sind (Public-Fallback sonst). Bringt Dimension D in Produktion zuverlässig zum
  Leben. Siehe [Datenerhebung](data-collection.md) → Reddit-Collector.
- **Resident Advisor** über authentifizierten Zugang oder einen gepflegten Scraping-Dienst
  → echte Follower-/Event-Zahlen. **Offen** (kein öffentlicher Auth-Endpunkt; braucht
  Zugang/Service-Key).
- **Ticketing** (RA/Dice) → verlässliche Event-Aktivität (Dimension A). **Offen.**

### 3. Provenance & Confidence — ✅ v1 ausgeliefert (confidence-aware Scoring)
Das Scoring ist jetzt **confidence-aware**: pro Entität werden Datenkonfidenz
(Vollständigkeit + Frische aus `last_verification`), Presence pro Dimension und ein
**bereinigter Score** (Relevanz über bekannte Dimensionen) berechnet und überall angezeigt
(Report, CLI, API, Dashboard). Dünne/veraltete Daten werden als „⚠ geringe Datenbasis"
markiert statt als niedrige Relevanz.

- **Status:** `scoring/confidence.py` + additive Felder im `ScoreBreakdown`
  (`total`/`tier` unverändert). Siehe [Scoring-Modell](scoring.md) → Datenkonfidenz.
- **Offen für v2-Vollausbau:** echte **Per-Feld-Provenance** (Quelle + Konfidenz je Feld,
  nicht nur je Entität), Dedup-Review mit Quellenanzeige, gewichtete Imputation statt
  reiner Renormalisierung.

---

## P1 — Vom Tool zum Service

### 4. Postgres-first + Alembic-Migrationen — ✅ v1 ausgeliefert
Alembic ist eingerichtet: `migrations/` mit einer aus den ORM-Modellen generierten
Initial-Migration, `migrations/env.py` liest `DATABASE_URL` (SQLite **oder** Postgres),
CLI `scoredclub migrate`. Getestet (Upgrade/Downgrade-Roundtrip + `alembic check` =
Migration deckt sich mit den Modellen). Siehe [Deployment](deployment.md) → PostgreSQL + Migrationen.

- **Offen für v2-Vollausbau:** Postgres-spezifische JSONB-Spalten/Indizes (statt portablem
  `JSON`), CI-Job, der Migrationen gegen echtes Postgres testet.

### 5. Voll-API mit Auth + Background-Jobs — 🟡 teilweise ausgeliefert
- **API-Key-Auth + Schreib-/Trigger-Endpunkte → ✅ umgesetzt.** `SCOREDCLUB_API_KEY`
  schützt `POST /ingest` (Research einspielen) und `POST /runs` (Lauf auslösen);
  konstant-zeitiger Vergleich, ohne Key deaktiviert (503). Lese-Endpunkte bleiben offen.
  Siehe [API](api.md) → Schreib-/Trigger-Endpunkte.
- **Asynchrone Läufe → ✅ v1 umgesetzt.** `POST /runs` mit `"async": true` startet einen
  In-Process-Background-Job (`202` + `job_id`); Status via `GET /jobs/{id}`. Siehe
  [API](api.md) → `POST /runs` / `GET /jobs/{id}`.
- **Offen:** Rate-Limiting, OAuth/mehrere Keys, **persistente/verteilte Jobs**
  (RQ/Celery + Broker) statt In-Process, Entitäten-Management-Endpunkte.

### 6. Frontend-Ausbau — 🟡 teilweise ausgeliefert
- **Trending im Dashboard → ✅ umgesetzt.** Bewegungen-Panel (Top-Auf-/Absteiger) und
  Score-Verlauf-Sparkline im Detail-Dialog (XSS-sicher per `createElementNS`). Aktiviert
  sich ab ≥ 2 Läufen. Siehe [Dashboard](frontend.md).
- **A/B-Compare über die API → ✅ umgesetzt.** `POST /compare` liefert den Vergleich zweier
  Scoring-Konfigurationen (Grundlage für ein künftiges Compare-UI). Siehe [API](api.md).
- **Kartenansicht → ✅ umgesetzt.** Listen-/Karten-Umschalter im Dashboard; Entitäten werden
  nach Berliner Bezirk geplottet (statische Bezirks-Zentren via `scoredclub.geocode`, kein
  externer Dienst). Das `geo`-Feld wird im Lauf befüllt (`run.geocode_districts`).
- **Offen:** visuelles **A/B-Compare-UI** (Frontend, das `POST /compare` nutzt), präzises
  Per-Adress-Geocoding über einen Dienst, Daten live aus der API statt statischem Snapshot,
  auth-geschützter Admin-Bereich.

---

## P2 — Reichweite & Tiefe

### 7. Multi-City-Generalisierung
Eine `scene`/`city`-Dimension, pro Szene eigene Seeds/Configs — „ScoredClub für
Hamburg/London/NYC".

### 8. Lernkomponente (optional)
Ein leichtes Ranking-Modell auf einem kleinen, menschlich gelabelten Relevanz-Set — als
Ergänzung zum erklärbaren Regel-Score, der die Baseline bleibt.

### 9. Event- & DJ-Graph
Über Entitäten hinaus: Lineups, „wer spielt wo", Netzwerk-Analyse (die `networking`-
Dimension als echter Graph). Sentiment per echtem NLP auf Reddit/Presse statt manuellem
Hint.

---

## Daten-Qualität & Ops (querschnittlich)

- Dedup-Review-UI / Human-in-the-Loop für mehrdeutige Merges.
- Datenfrische prominent ausweisen (Alter aus `last_verification`).
- Alerting über Webhooks hinaus: Digest-Mails, RSS der Movers.
- Observability: strukturiertes Logging, Run-Metriken, Error-Tracking.
- Collector-Tests gegen aufgezeichnete Fixtures (VCR-Stil), damit Layout-Änderungen
  externer Seiten im CI auffallen.

## Bewusst *nicht* in v2

- Den erklärbaren, regelbasierten Score **nicht** durch eine Blackbox ersetzen —
  Nachvollziehbarkeit ist hier ein Feature.
- Keine Infrastruktur-Überfrachtung, bevor der agentische Collector den Datenengpass löst.

## Empfohlene Reihenfolge

1. **P0** Agentischer Collector + Confidence/Provenance (löst Datenengpass und
   Vertrauensproblem in einem).
2. **P1** Postgres/Alembic + Auth-API/Jobs.
3. **P1** Frontend-Ausbau (Trending-, Compare-, Karten-Ansicht).
4. **P2** Multi-City, Lernkomponente, Event/DJ-Graph.

## Bezug zu v1-Komponenten

| v2-Vorhaben | baut auf v1 auf |
|-------------|------------------|
| Agentischer Collector | `EntityProfile`-Schema, `collectors/base.py`, Dedup/Merge |
| Confidence-aware Scoring | `scoring/rubric.py`, `engine.py`, `last_verification` |
| Auth-API + Jobs | `api/app.py`, `pipeline/run.py` |
| Frontend-Ansichten | `frontend/`, Trending-/Compare-Endpunkte, `trend`-Export |
| Postgres/Alembic | `db/models.py`, `db/session.py` (bereits Postgres-kompatibel) |
| Multi-City | `config.py` (Settings), Seeds, Scoring-Config |
