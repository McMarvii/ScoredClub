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

### 2. Echte API-Collectors
- **Reddit-OAuth-App** → bringt Dimension D zuverlässig zum Leben.
- **Resident Advisor** über authentifizierten Zugang oder einen gepflegten
  Scraping-Dienst → echte Follower- und Event-Zahlen.
- **Ticketing** (RA/Dice) → verlässliche Event-Aktivität (Dimension A).

### 3. Provenance & Confidence pro Feld
Jedes Feld bekommt Quelle, Konfidenz und Alter. Das Scoring wird **confidence-aware**:
dünne/veraltete Daten werden als Unsicherheit markiert statt als „niedrige Relevanz".

- Behebt das „fehlende Daten = niedriger Score"-Artefakt.
- Schafft Vertrauen und Nachvollziehbarkeit.
- Score-Decay über `last_verification` (Alter senkt Konfidenz).

---

## P1 — Vom Tool zum Service

### 4. Postgres-first + Alembic-Migrationen
Sauberer Schema-Evolutionspfad (heute nur `create_all`), JSONB-Indizes, getestete
Migrationen.

### 5. Voll-API mit Auth + Background-Jobs
- Token-Auth (API-Key/OAuth), Rate-Limiting.
- Schreib-/Trigger-Endpunkte: Run auslösen, Research einspielen, Entitäten verwalten.
- Asynchrone Läufe (APScheduler/RQ/Celery) statt nur Cron.

### 6. Frontend-Ausbau
- Dedizierte **Trending-Ansicht** (Sparklines, Leaderboard über Zeit).
- Visuelles **A/B-Compare-UI** (zwei Configs wählen, Diff sehen).
- Entity-Detailseiten mit Verlaufs-Charts.
- **Kartenansicht** — das `geo`-Feld endlich nutzen (Bezirke/Adressen geocoden).
- Daten live aus der API statt statischem JSON-Snapshot (Snapshot als Fallback/Cache).
- Auth-geschützter Admin-Bereich (Läufe auslösen, Dedup-Merges prüfen).

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
