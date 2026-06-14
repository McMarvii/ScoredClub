# ScoredClub — Roadmap v2

Stand: v1 + großer Teil von v2 sind in `main` (Scoring, Trending, A/B-Testing, Backend-API
mit Auth/async, Postgres/Alembic, Dashboard mit Listen-/Karten-/Trending-Ansicht,
CI/Pages/Monthly-Automatisierung, ausführliche Doku, 238 Tests). Dieses Dokument hält die
Richtung fest. Es ist ein lebendes Planungsdokument, kein Vertrag — Reihenfolge und Umfang
werden iterativ angepasst. P3 (unten) ergänzt eine Wettbewerbs-/Domänen-Recherche.

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

### 7. Multi-City-Generalisierung — ❌ offen
Eine `scene`/`city`-Dimension, pro Szene eigene Seeds/Configs — „ScoredClub für
Hamburg/London/NYC".

### 8. Lernkomponente (optional) — ❌ offen
Ein leichtes Ranking-Modell auf einem kleinen, menschlich gelabelten Relevanz-Set — als
Ergänzung zum erklärbaren Regel-Score, der die Baseline bleibt.

### 9. Event- & DJ-Graph — ❌ offen
Über Entitäten hinaus: **DJ/Artist als eigene Entitäten** und ein **Venue↔Artist↔Kollektiv-
Booking-/Kollaborations-Graph** (die `networking`-Dimension als echter Graph). Plus echte
**NLP-Sentiment-Analyse** auf Reddit/Presse statt manuellem Hint. Details/Begründung: P3.

---

## P3 — Erweiterte Fähigkeiten (Recherche vergleichbarer Tools)

Abgeleitet aus einer Wettbewerbs-/Domänen-Recherche: **Musik-/Artist-Analytics**
(Chartmetric, Soundcharts, Viberate, Songstats), **Event-/Venue-Aggregatoren** (Resident
Advisor, Bandsintown, Songkick, Dice, Shotgun), **Nightlife-/Reputations-Apps** sowie
**Kulturpolitik-Monitoring** (Clubcommission, UNESCO-ICH). Ziel: was ein solches Tool über
das heutige Org-Entity-Scoring hinaus können sollte.

> **Datenzugang/rechtliche Leitplanke:** Resident Advisor hat **keine offizielle öffentliche
> API** (nur undokumentiertes GraphQL/Scraper → ToS-/Rechtsrisiko). **Bandsintown** und
> **Songkick** sind die sanktionierten, dokumentierten APIs und sollten der primäre Event-
> Datenpfad sein. Community-/Personendaten brauchen eine GDPR-/Retention-Linie und
> robots.txt-/ToS-konforme Erhebung.

### Datenquellen
- **Event-/Lineup-Ingestion (Bandsintown + Songkick) → ✅ umgesetzt.** Der
  `BandsintownCollector` (no-op ohne `BANDSINTOWN_APP_ID`/ohne Artists) holt über die
  *sanktionierte* Bandsintown-API die Events einer Artist-Entität und speist Event-Zahlen
  (3/6 Monate, Dimension A), `last_event_date` und die bespielten Venues. Der
  `SongkickCollector` ergänzt dieselben Signale aus der **Songkick-API** (Suche → Gigography,
  `SONGKICK_API_KEY`). Beide mit gemocktem Client getestet. Siehe
  [Datenerhebung](data-collection.md). **Offen:** RA (vorsichtig), Org-Entitäten (nicht nur Artists).
- **DJ/Artist-Entitäten → 🟡 erster Schritt ausgeliefert.** `artist` ist ein First-Class
  `EntityType` (Schema, Report, Dashboard-Filter). Artists werden über `ingest`/Research
  eingespielt (nicht über Seeds, damit der kanonische Lauf stabil bleibt). **Offen:**
  Artist-spezifische Scoring-Rubrik, Discovery von Artists.
- **Event-Nachfragesignale:** → ✅ als `demand`-Objekt modelliert (`going_count`, `sold_out`,
  `waitlist`); fließt als Bonus „Hohe Event-Nachfrage" ins Scoring ein, wenn vorhanden.
  Live-Erhebung (RA „going"/Dice/Shotgun) braucht noch einen authentifizierten Collector.
- **Cross-Plattform-Follower-Zeitreihen** → ✅ als `follower_history` (Plattform → datierte
  Punkte) modelliert; `scoredclub.followers` berechnet Wachstum/Steigung je Plattform,
  ausgewiesen in `GET /entities/{id}` (`follower_growth`). Streaming-Quellen offen.

### Analytics / Intelligence
- **Booking-/Kollaborations-Graph** (Venue↔Artist↔Kollektiv) → ✅ Aggregation/Abfrage
  umgesetzt. `scoredclub.graph` baut aus `networking` (`booked_djs`/`collaborations`/
  `cross_promotions`) einen Graphen mit Namensauflösung auf bestehende Entitäten, plus
  Metriken (Top-Venues/-DJs, geteilte Bookings, Degree, Komponenten). CLI `graph`, API
  `GET /graph`. Siehe [Graph](graph.md). **Offen:** visueller Graph-View im Dashboard.
- **Breakout-/Anomalie-Erkennung** auf dem Score-Momentum → ✅ umgesetzt. Slope-Buckets
  Growth/Strong/Explosive mit **dynamischer Baseline** (Volatilität der Entität) statt fixer
  Schwellen. `scoredclub.analytics`, CLI `analytics`, API `GET /analytics`. Siehe [Analytics](analytics.md).
- **NLP-Sentiment-Analyse** auf Reddit/Notizen → ✅ umgesetzt (deterministische
  Lexikon-Analyse, DE+EN, Negation/Verstärker; `SentimentCollector`, off by default, füllt
  nur unbekannte Hints). Eine ML-/Transformer-Variante bliebe optionaler Ausbau. Siehe
  [Sentiment](sentiment.md).
- **Perzentil-/Karrierephasen-Klassifikation** (Developing → Elite) → ✅ umgesetzt
  (Perzentilrang der Kohorte → Phase). Siehe [Analytics](analytics.md).
- **Kurzfrist-Forecast** der Score-Trajektorie für „steigt bald"-Flags → ✅ umgesetzt
  (Kleinste-Quadrate-Steigung + `rising_soon`). Siehe [Analytics](analytics.md).

### Produkt / UX
- **Digests/Alerts über Webhooks hinaus:** → ✅ umgesetzt — RSS-Feed (`GET /feed.xml`,
  `scoredclub.feeds`) plus **Slack-** und **E-Mail-Digest-Sender** (`deliver_slack`/
  `deliver_email`, beide off by default, fehlertolerant, mit gemocktem Client/SMTP getestet).
  **Offen:** gestufte Wochen-Digests (sofort-kritisch vs. wöchentlich).
- **Watchlists + gespeicherte Filter** (nach Bezirk/Typ/Tier) als beobachtete Ansichten.
- **Event-Kalender + Lineup-Ansicht** im Dashboard; pro Entität eine Gigography-Historie.
- **CSV-/BI-Export** → ✅ umgesetzt (`scoredclub export`, `GET /export.csv`: Summary +
  Dimensionspunkte je Entität). **Offen:** einbettbare Score-/Trend-Widgets für Partner.

### Ops / Trust
- **Per-Feld-Provenance** (Quelle + Konfidenz je Feld) → ✅ als optionale `provenance`-Map
  im Schema umgesetzt (Merge: neuere Quelle gewinnt je Feldpfad). **GDPR-Retention** → ✅
  `scoredclub.retention` + CLI `retention` (redigiert veraltete Community-/Personendaten).
  **ToS-/robots-Konformität** → ✅ Matrix je Collector dokumentiert. Siehe
  [Compliance](compliance.md).

### Differenzierter Niche: Kulturökosystem-Monitoring (Berlin-spezifisch, weitgehend greenfield)
- **Clubsterben-Register:** → ✅ umgesetzt. `lifecycle_events` (opening/closure/reopening/
  relocation/threatened) mit Ursachen-Taxonomie (rent/noise/redevelopment/insolvency/…) +
  `displacement_signals` im Schema; `scoredclub.clubsterben` aggregiert Eröffnungen/
  Schließungen, Ursachen, Jahresverlauf und gefährdete Venues. CLI `clubsterben`, API
  `GET /clubsterben`. Siehe [Clubsterben-Register](clubsterben.md).
- **Gentrifizierungs-/Verdrängungssignale** → ✅ als `displacement_signals` modelliert
  (rent_increase/property_sale/rezoning/noise_complaint/construction) und in der „at_risk"-
  Watchlist berücksichtigt.
- **Förder-/Subventions- und Policy-Feed** (Clubcommission/Senat, UNESCO-ICH-Status) mit
  Eignungs-/Deadline-Hinweisen; braucht deutschsprachige Quellen. **Offen** (externer Feed).

### Quellen (Auswahl)
- Chartmetric Artist Analytics — https://chartmetric.com/features/artist-analytics
- Soundcharts / Viberate — https://soundcharts.com/en/ar-research-and-business-facing-music-discovery · https://www.viberate.com/soundcharts-alternative/
- Bandsintown API · Songkick Developer — https://help.artists.bandsintown.com/en/articles/7053475-what-is-the-bandsintown-api · https://www.songkick.com/developer
- RA Events Scraper (ToS-Hinweis) — https://github.com/djb-gt/resident-advisor-events-scraper
- Chartmetric „Predict"/Emerging — https://resources.onestowatch.com/chartmetric-data-accuracy-predictions/
- Clubcommission „Clubsterben" · RA News · UNESCO-ICH — https://www.clubcommission.de/pressemitteilung-clubsterben-ist-wieder-an-der-tagesordnung/ · https://ra.co/news/76507 · https://www.timeout.com/news/why-has-berlin-techno-been-added-to-unescos-list-of-intangible-cultural-heritage-031524
- Anomalie-Erkennung · Sentiment · Scraping-Recht/GDPR — https://www.kissmetrics.io/blog/ai-analytics-anomaly-detection-guide · https://use-apify.com/blog/web-scraping-legal-guide · https://www.octoparse.com/blog/gdpr-compliance-in-web-scraping

---

## Daten-Qualität & Ops (querschnittlich)

- Dedup-Review-UI / Human-in-the-Loop für mehrdeutige Merges.
- Datenfrische prominent ausweisen (Alter aus `last_verification`).
- Alerting über Webhooks hinaus: Digest-Mails, RSS der Movers (siehe P3).
- Watchlists / gespeicherte Filter als beobachtete Ansichten (siehe P3).
- Anomalie-/Breakout-Erkennung statt fixer Alert-Schwellen (siehe P3).
- Per-Feld-Provenance + GDPR-/Retention-Policy für Community-Daten → ✅ (siehe [Compliance](compliance.md)).
- Observability: strukturiertes Logging, Run-Metriken, Error-Tracking.
- Collector-Tests gegen aufgezeichnete Fixtures (VCR-Stil), damit Layout-Änderungen
  externer Seiten im CI auffallen.

## Bewusst *nicht* in v2

- Den erklärbaren, regelbasierten Score **nicht** durch eine Blackbox ersetzen —
  Nachvollziehbarkeit ist hier ein Feature.
- Keine Infrastruktur-Überfrachtung, bevor der agentische Collector den Datenengpass löst.

## Empfohlene Reihenfolge

1. **P0** Agentischer Collector + Confidence/Provenance (löst Datenengpass und
   Vertrauensproblem in einem). ✅ weitgehend erledigt
2. **P1** Postgres/Alembic + Auth-API/Jobs. ✅ erledigt
3. **P1** Frontend-Ausbau (Trending-, Compare-, Karten-Ansicht). ✅ erledigt
4. **P3** Event-/Lineup-Ingestion (Bandsintown/Songkick) + DJ/Artist-Entitäten + Booking-Graph
   — der nächste hohe Hebel: bringt echte Event-/Beziehungsdaten in alle Dimensionen.
   🟡 erster Schritt erledigt (artist-Typ + Bandsintown-Collector + Venue-Kanten); offen:
   Songkick, Artist-Scoring, Graph-Aggregation/-View.
5. **P3** Kulturökosystem-Monitoring (Clubsterben-Register, Förder-/Policy-Feed) — am stärksten
   differenziert, weitgehend greenfield.
6. **P2** Multi-City, Lernkomponente.

## Bezug zu v1-Komponenten

| v2-Vorhaben | baut auf v1 auf |
|-------------|------------------|
| Agentischer Collector | `EntityProfile`-Schema, `collectors/base.py`, Dedup/Merge |
| Confidence-aware Scoring | `scoring/rubric.py`, `engine.py`, `last_verification` |
| Auth-API + Jobs | `api/app.py`, `pipeline/run.py` |
| Frontend-Ansichten | `frontend/`, Trending-/Compare-Endpunkte, `trend`-Export |
| Postgres/Alembic | `db/models.py`, `db/session.py` (bereits Postgres-kompatibel) |
| Multi-City | `config.py` (Settings), Seeds, Scoring-Config |
