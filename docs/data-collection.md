# Datenerhebung & Research-Workflow

ScoredClub nutzt einen **hybriden** Ansatz: ein maßgeblicher LLM-Research-Pfad plus
best-effort Netzwerk-Collector. Alle Collector sind **fehlertolerant** — Netzwerk- oder
Parse-Fehler werden zu Warnungen, ein Lauf wird nie abgebrochen.

## Überblick

```
LLM-Research (research.json)  ──┐
Clubcommission-Collector        ├─► Dedup/Merge ─► DB ─► Scoring ─► Reports
Resident-Advisor-Collector      │
Reddit-Collector (Enrichment) ──┘
```

Zwei Kategorien (siehe `src/scoredclub/collectors/__init__.py`):

- **Discovery-Collector** dürfen neue Entitäten anlegen: `ClubcommissionCollector`, `ResidentAdvisorCollector`.
- **Enrichment-Collector** reichern nur bestehende Entitäten an (legen keine neuen an): `LLMResearchCollector`, `RedditCollector`.

Die Pipeline führt erst Discovery, dann Enrichment aus.

## 0. Agentischer LLM-Collector (optional, automatisiert Schritt 1)

Statt die Research-Datei von Hand zu erzeugen, kann der `LLMResearchCollector` die
Recherche automatisieren: pro Entität ruft er die Claude-API (offizielles `anthropic`-SDK)
mit dem serverseitigen **web_search**-Tool auf, extrahiert per **Structured Outputs** ein
`EntityProfile` und merged es in die bestehende Entität (Enrichment, legt nichts Neues an).

- **Standardmäßig aus.** Aktivieren über `llm.enabled` in der [Konfiguration](configuration.md).
- **Optionale Abhängigkeit:** `pip install -e ".[llm]"` plus `ANTHROPIC_API_KEY` im Environment.
  Fehlt eines davon, degradiert der Collector zu einer Warnung — nie ein Fehler.
- **Kostenkontrolle:** `llm.max_entities` begrenzt die Anzahl pro Run; bevorzugt werden die
  am längsten nicht verifizierten Entitäten (`last_verification`). `llm.model` (Default
  `claude-opus-4-8`) und `llm.effort` sind konfigurierbar.
- Fehlertolerant: bricht nach wiederholten API-Fehlern sauber ab und reicht Teilresultate durch.

> Dies ist der erste Baustein des in der [Roadmap v2](roadmap-v2.md) beschriebenen
> agentischen Collectors. Da die Claude-API in Sandbox/CI nicht erreichbar ist, wird die
> Logik mit einem gemockten Client getestet; der reale Lauf passiert in deiner Umgebung.

## 1. LLM-Research per Hand (immer verfügbar)

Alternativ (oder ergänzend) füllt ein Research-Agent (z. B. Claude mit Websuche) pro Entität
ein Profil gemäß [Datenschema](schema.md) und schreibt es nach
`data/research/berlin_research_<DATUM>.json`.

**Empfohlener Ablauf:**

1. Pro Entität recherchieren: Status, Follower (Größenordnung), Event-Zahlen, Presse,
   Reddit-Threads, Awareness-Policies, Label/Podcast, internationale Bookings, Vorfälle, Quellen.
2. Bei Unsicherheit `null` lassen — **keine Zahlen erfinden**.
3. Validieren: `scoredclub ingest <datei> --dry-run`.
4. Einspielen/laufen lassen: `scoredclub run --research <datei>`.

Die Recherche-Themen pro Entität (als Leitfaden): aktueller Status & letzte Events,
Instagram/RA-Follower, Events der letzten 3/6 Monate, Presse (RA/Mixmag/Groove/DJ Mag
vs. lokal: taz/tip/exberliner), Community (Reddit), Safety/Awareness/queer/FLINTA,
eigenes Label/Podcast, internationale Bookings, dokumentierte Vorfälle, Clubcommission/
UNESCO/Kulturförderung.

## 2. Clubcommission-Collector (Discovery)

Quelle: Members-Bereich der Clubcommission-Startseite (`sources.clubcommission_url`).
Parst Member-Links der Form `/members/<slug>/` und leitet daraus Namen ab. Setzt das
Flag `cultural_recognition.clubcommission_member = true` (speist den Bonus, wenn die
Entität in eine bestehende gemerged wird).

- Robust gegen Layout-Änderungen: leeres Parse-Ergebnis → Warnung, kein Abbruch.
- Die öffentliche Startseite zeigt nur ~10 ausgewählte Member (kein vollständiges
  Verzeichnis) — das ist die Grenze der Quelle.

## 3. Resident-Advisor-Collector (Discovery, best effort)

Versucht eine Abfrage gegen die öffentliche GraphQL-Schnittstelle (`sources.ra_graphql_url`).
RA ist JavaScript-lastig und bot-geschützt; bei 403/Cloudflare degradiert der Collector
zu einer Warnung. **Es wird kein Headless-Browser verwendet** — der LLM-Research-Pfad ist
die maßgebliche Quelle für RA-Daten. Liefert opportunistisch `ra_profile_url`/`ra_followers`.

## 4. Reddit-Collector (Enrichment) — mit OAuth

Sucht pro Entität auf Reddit, filtert auf szene-relevante Subreddits (`r/berlin`,
`r/Berghain_Community`, `r/techno`, `r/aves`, …) und merged die Permalinks in
`community.reddit_threads` — das speist **Dimension D**. Zwei Modi, automatisch gewählt:

- **OAuth (bevorzugt, zuverlässig):** Sind `REDDIT_CLIENT_ID` und `REDDIT_CLIENT_SECRET`
  im Environment gesetzt, holt der Collector ein App-Only-Token (Client-Credentials-Grant)
  und fragt den authentifizierten `oauth.reddit.com`-Endpunkt ab — mit echten Rate-Limits,
  nicht geblockt. **Das ist der Pfad, der Dimension D in Produktion verlässlich füllt.**
- **Public-Fallback:** Ohne Credentials wird die öffentliche `search.json`-API genutzt —
  best effort, außerhalb eines Browsers oft geblockt/rate-limited.

**Setup:** Reddit-„script"-App unter <https://www.reddit.com/prefs/apps> anlegen → Client-ID
und Secret. Zusätzlich einen aussagekräftigen `REDDIT_USER_AGENT` setzen (Reddit verlangt
einen eindeutigen UA).

```bash
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
export REDDIT_USER_AGENT="scoredclub/0.1 by /u/deinname"
scoredclub run        # Reddit-Collector nutzt automatisch OAuth
```

- Konfigurierbar: `sources.reddit_enabled`, `sources.reddit_max_threads`, Endpunkt-URLs.
- Fehlertolerant: OAuth-Fehler → Public-Fallback; wiederholte Suchfehler → sauberer Abbruch
  mit Teilresultaten. In Sandbox/CI ohne Credentials bleibt D mangels Zugang oft 0.

> Erster Teil von **P0.2** der [Roadmap v2](roadmap-v2.md). RA-Follower/Events und Ticketing
> brauchen einen authentifizierten Zugang bzw. einen Scraping-Dienst und bleiben vorerst
> best effort (siehe Roadmap).

## Dedup & Merge

Vor dem Einspielen werden Entitäten zusammengeführt (`src/scoredclub/normalize.py`):

- **Normalisierung:** Kleinschreibung, Diakritika entfernen (`ÆDEN` → `aeden`),
  Sonderzeichen entfernen (`://about blank` → `about blank`), Füllwörter strippen
  (`Club der Visionaere` → `visionaere`).
- **Alias-Tabelle** für die Seeds (z. B. `rso` → `rso-berlin`).
- **Matching-Reihenfolge:** exakte `entity_id` → Alias → normalisierter Name →
  konservatives Fuzzy-Matching (Ähnlichkeit ≥ 0.92 **und** Korroboration über
  Bezirk/Website/Instagram).
- **Merge-Politik:** neuere `last_verification` gewinnt pro Feld; Listen (Quellen,
  Vorfälle, Bookings, Presse) werden vereinigt; der Name einer Seed-Entität wird nie
  herabgestuft; `"unknown"`-Werte überschreiben keine echten Werte.

## Collectors konfigurieren oder abschalten

In der [Konfiguration](configuration.md) unter `sources`. Beim Lauf lassen sich alle
Netzwerk-Collector mit `--skip-collectors` überspringen (z. B. für reproduzierbare
Reports nur auf Basis der Research-Datei).
