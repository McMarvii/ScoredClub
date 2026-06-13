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
- **Enrichment-Collector** reichern nur bestehende Entitäten an (legen keine neuen an): `RedditCollector`.

Die Pipeline führt erst Discovery, dann Enrichment aus.

## 1. LLM-Research (maßgeblicher Pfad)

Ein Research-Agent (z. B. Claude mit Websuche) füllt pro Entität ein Profil gemäß
[Datenschema](schema.md) und schreibt es nach `data/research/berlin_research_<DATUM>.json`.

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

## 4. Reddit-Collector (Enrichment)

Fragt pro Entität die öffentliche `search.json`-API (`sources.reddit_search_url`) ab,
filtert auf szene-relevante Subreddits (`r/berlin`, `r/Berghain_Community`, `r/techno`,
`r/aves`, …) und merged die Permalinks in `community.reddit_threads` — das speist
**Dimension D**.

- Konfigurierbar: `sources.reddit_enabled`, `sources.reddit_max_threads`.
- Fehlertolerant: bricht nach wiederholten Fehlern (z. B. wenn Reddit geblockt ist)
  sauber ab und liefert Teilresultate.
- In Sandbox-/Offline-Umgebungen ist Reddit oft nicht erreichbar → D bleibt 0. In echter
  Deployment-Umgebung greift die Anreicherung automatisch.

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
