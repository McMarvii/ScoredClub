# Datenerhebung & Research-Workflow

ScoredClub nutzt einen **hybriden** Ansatz: ein maßgeblicher LLM-Research-Pfad plus
best-effort Netzwerk-Collector. Alle Collector sind **fehlertolerant** — Netzwerk- oder
Parse-Fehler werden zu Warnungen, ein Lauf wird nie abgebrochen.

## Überblick

```
LLM-Research (research.json)     ──┐
Clubcommission-Collector           ├─► Dedup/Merge ─► DB ─► Scoring ─► Reports
Resident-Advisor-Collector         │
Reddit-Collector (Enrichment)      │
Bandsintown/Songkick (Events)      │
SoundCloud/Mixcloud (Musik/Sets)   │
Sentiment-Collector (offline)      ┘
```

Zwei Kategorien (siehe `src/scoredclub/collectors/__init__.py`):

- **Discovery-Collector** dürfen neue Entitäten anlegen: `ClubcommissionCollector`, `ResidentAdvisorCollector`.
- **Enrichment-Collector** reichern nur bestehende Entitäten an (legen keine neuen an): `LLMResearchCollector`, `RedditCollector`, `BandsintownCollector`, `SongkickCollector`, `SoundCloudCollector`, `MixcloudCollector`, `SentimentCollector`, `FollowerAuditCollector`.

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

## 5. Bandsintown-Collector (Enrichment) — für DJ/Artist-Entitäten

Resident Advisor hat keine sanktionierte öffentliche API (Scraping ist ToS-riskant), daher
kommt das Booking-Signal für DJs/Artists aus der offiziellen **Bandsintown-REST-API**. Für
jede Entität vom Typ `artist` holt der Collector die Events und reichert an:

- Event-Zahlen in den letzten 3/6 Monaten (`events.events_last_3_months/6_months`) → **Dimension A**,
- das jüngste vergangene Event als `last_event_date` (Freshness/Kontinuität),
- die bespielten Venues als `networking.collaborations` — der Keim eines **Booking-Graphen**
  (welche Clubs ein Artist tatsächlich bespielt).

**Setup:** Eine Bandsintown-`app_id` unter
<https://www.artists.bandsintown.com/support/api-installation> registrieren und als
`BANDSINTOWN_APP_ID` ins Environment setzen.

```bash
export BANDSINTOWN_APP_ID=...
scoredclub run        # reichert vorhandene artist-Entitäten an
```

- **No-op ohne `BANDSINTOWN_APP_ID`** oder ohne `artist`-Entitäten — der kanonische Lauf
  enthält keine Artists, der Collector bleibt dort still.
- Konfigurierbar: `sources.bandsintown_url`, `sources.bandsintown_max_artists`.
- Fehlertolerant: wiederholte Abruffehler → sauberer Abbruch mit Teilresultaten. Da die API
  in Sandbox/CI ohne `app_id` nicht erreichbar ist, wird die Logik mit einem gemockten
  Client getestet; der reale Lauf passiert in deiner Umgebung.

> Artists werden über `ingest`/Research (Typ `artist`) eingespielt, nicht über die Seeds —
> so bleibt der kanonische Lauf stabil. Siehe **P3** der [Roadmap v2](roadmap-v2.md).

### Songkick (zweite sanktionierte Quelle)

`SongkickCollector` ist eine zweite offizielle Event-Quelle für `artist`-Entitäten neben
Bandsintown. Pro Artist wird zunächst die Songkick-Artist-ID per Suche aufgelöst, dann die
**Gigography** (vergangene Events) geladen und dasselbe Booking-Signal angereichert
(Event-Zahlen 3/6 Monate, `last_event_date`, bespielte Venues → `networking.collaborations`,
`ticketing_platforms=["Songkick"]`).

**Setup:** API-Key unter <https://www.songkick.com/developer> beantragen und als
`SONGKICK_API_KEY` setzen. No-op ohne Key oder ohne Artists; fehlertolerant; mit gemocktem
Client getestet. Konfigurierbar: `sources.songkick_url`, `sources.songkick_max_artists`.

## 6. Musik-Collectors: SoundCloud & Mixcloud (Enrichment)

Befüllen den [Steckbrief/Dossier](dossier.md) automatisch mit der Musik-Tiefe je Entität —
für jede Entität (DJ, Venue, Kollektiv), die ein passendes Handle in `online.soundcloud`
bzw. `online.mixcloud` trägt. Beide sind reine **Enrichment**-Collector, legen keine neuen
Entitäten an, sind fehlertolerant (Abbruch nach wiederholten Fehlern) und mit gemocktem
Client getestet.

- **SoundCloud-Collector** → **Tracks/Releases**. Löst den User per `resolve`-Endpunkt auf,
  holt dessen Tracks und reichert `top_tracks` an (Titel, Plays, Release-Datum, URL,
  `source="soundcloud"`) sowie die SoundCloud-**Follower** (`online.soundcloud.followers` →
  Online-Reichweite, **Dimension B**). **Setup:** SoundCloud-App unter
  <https://developers.soundcloud.com/> registrieren und die Client-ID als
  `SOUNDCLOUD_CLIENT_ID` setzen. **No-op ohne `SOUNDCLOUD_CLIENT_ID`** oder ohne
  SoundCloud-Handle. Konfigurierbar: `sources.soundcloud_url`,
  `sources.soundcloud_max_entities`, `sources.soundcloud_max_tracks`.
- **Mixcloud-Collector** → **Sets/Mixes**. Holt die Cloudcasts des Users und reichert
  `top_sets` an (Titel, Plays, Datum, Länge, URL, `source="mixcloud"`) plus die Mixcloud-
  **Follower**. Mixclouds öffentliche API braucht **keinen Key**; damit der kanonische Lauf
  reproduzierbar bleibt, ist der Collector daher **standardmäßig aus**
  (`sources.mixcloud_enabled`) und ohne Mixcloud-Handle ein No-op. Konfigurierbar:
  `sources.mixcloud_url`, `sources.mixcloud_max_entities`, `sources.mixcloud_max_sets`.

```bash
export SOUNDCLOUD_CLIENT_ID=...     # SoundCloud-Tracks anreichern
scoredclub run                       # füllt top_tracks + soundcloud.followers
```

> Beim erneuten Lauf werden dieselben Tracks/Sets (gleicher Titel + URL) **in place
> aktualisiert** statt dupliziert — die frischeren Play-Zahlen gewinnen (Merge-Dedup über
> einen natürlichen Schlüssel, siehe unten). Schließt den offenen Punkt „Musik-Collectors"
> aus der [Roadmap v3](roadmap-v2.md) / dem [Steckbrief](dossier.md).

## 7. Sentiment-Collector (Enrichment, offline)

Leitet den `community_sentiment_hint` deterministisch aus Reddit-Thread-Titeln + Notizen
ab (Lexikon-Analyse, kein Netz/Modell) und ersetzt so den manuellen Hint. **Standardmäßig
aus** (`sources.sentiment_enabled`); aktiviert füllt er nur *unbekannte* Hints und läuft
nach dem Reddit-Collector. Details: [Sentiment](sentiment.md).

## 8. Follower-Audit-Collector (Enrichment, extern)

Zieht einen *externen* Datensatz zur **Follower-Echtheit** (vermuteter Fake-Anteil,
Engagement-Rate, historische Follower-Zahlen) und hängt ihn als `follower_audit` an die
Entität; die gelieferte Historie fließt in `follower_history`. **No-op ohne
`FOLLOWER_AUDIT_API_KEY`** oder ohne Instagram-Handle; provider-agnostisch über
`sources.follower_audit_url`. Speist die [Follower-Echtheit](authenticity.md) (nicht das
Scoring). Fehlertolerant, mit gemocktem Client getestet.

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
- **Dossier-Listen** (`top_tracks`/`top_sets`/`parties`) werden über einen natürlichen
  Schlüssel dedupliziert (Titel + URL bzw. Name + Venue + Datum) statt über die volle
  Repräsentation — der frischere Eintrag gewinnt. So aktualisiert ein erneuter Musik-Fetch
  geänderte Play-Zahlen **in place**, statt Near-Duplikate anzuhäufen.

## Collectors konfigurieren oder abschalten

In der [Konfiguration](configuration.md) unter `sources`. Beim Lauf lassen sich alle
Netzwerk-Collector mit `--skip-collectors` überspringen (z. B. für reproduzierbare
Reports nur auf Basis der Research-Datei).
