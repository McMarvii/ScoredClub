# Troubleshooting

## Installation & Tests

**`ModuleNotFoundError: No module named 'tests'` bei `pytest`**
Das Projekt setzt `pythonpath = ["."]` in `pyproject.toml`. Tritt der Fehler dennoch auf,
führe pytest aus dem Repo-Root aus oder nutze `python -m pytest`.

**`scoredclub: command not found`**
Das Paket ist nicht (im aktiven Environment) installiert. `pip install -e ".[dev]"` im
Repo-Root ausführen; bei venv das Environment aktivieren.

## Datenbank

**`unable to open database file`**
Der SQLite-Pfad ist nicht beschreibbar oder das Verzeichnis fehlt. ScoredClub legt das
Elternverzeichnis automatisch an; bei eigenem `DATABASE_URL` auf Schreibrechte achten.

**PostgreSQL: `ModuleNotFoundError: psycopg2`**
Den Treiber installieren: `pip install ".[postgres]"`.

**Frische DB / Neuanfang**
SQLite einfach löschen: `rm -f data/scoredclub.db`, dann `scoredclub init-db && scoredclub seed`.
(Damit geht die Score-Historie verloren.)

## Research-Ingest

**`N entities validated` mit Fehlern**
Pro ungültigem Eintrag werden Index und Grund ausgegeben. Häufige Fälle und Lösungen
stehen im [Datenschema](schema.md#häufige-validierungsfehler). Kurz:
- `community_sentiment_hint` muss **ein Wort** sein (`positive|mixed|negative|unknown`).
- `incidents[].date` muss `YYYY-MM-DD` sein oder weggelassen werden.
- yes/no-Flags müssen `true`/`false`/`yes`/`no`/`unclear` sein, kein Freitext.

**Eine Entität wird doppelt angelegt statt gemerged**
Der Dedup matcht über `entity_id` → Alias → normalisierten Namen → Fuzzy (mit
Korroboration). Wenn Namen stark abweichen und keine gemeinsame Website/Bezirk/Instagram
vorliegt, wird bewusst **nicht** gemerged (Schutz vor Falsch-Merges). Lösung: in der
Research-Datei dieselbe `entity_id` setzen oder den bekannten Namen als `aliases` ergänzen.

## Läufe & Scoring

**Dimension D (Community) ist überall 0**
Es liegen keine `reddit_threads` vor. Entweder der Reddit-Collector ist geblockt
(Sandbox/Offline) oder die Research-Datei enthält keine Threads. In echter
Deployment-Umgebung füllt der [Reddit-Collector](data-collection.md) das automatisch;
alternativ Threads direkt in der Research-Datei angeben.

**Eine erwartete Top-Entität scored niedrig**
Meist fehlende Daten (z. B. keine Follower → B niedrig). Mit `scoredclub score <id>` den
Breakdown prüfen und die Research-Daten ergänzen. Das [Scoring-Modell](scoring.md) zeigt,
welches Feld welche Dimension speist.

**Eine aktive Entität landet in INAKTIV/GESCHLOSSEN**
Entweder `status` ist `inactive`/`closed` oder das `last_event_date` ist älter als
`inactive_after_days` (Standard 180). Aktuelles `last_event_date` setzen oder die Schwelle
in der Config anpassen.

**Keine Alerts beim ersten Lauf**
Korrekt — Alerts entstehen aus dem Vergleich mit einem Vorlauf. Ab dem zweiten Lauf
greifen sie.

## Collectors

**`reddit: endpoint unreachable, aborting after 3 failures`**
Reddit ist nicht erreichbar (häufig in Sandboxes). Der Lauf läuft trotzdem durch; D bleibt
ohne Threads. Bei dauerhaftem Block `sources.reddit_enabled: false` setzen.

**`clubcommission: no member links parsed`**
Die Seitenstruktur hat sich geändert oder die Seite ist nicht erreichbar. Nicht fatal;
ggf. `sources.clubcommission_url` prüfen.

**Lauf mit Collectors liefert plötzlich viel mehr Entitäten**
Discovery-Collector legen neue Entitäten an (z. B. Clubcommission-Member, RA-Treffer).
Für einen reproduzierbaren, sauberen Report `--skip-collectors` verwenden.

## API & Frontend

**Dashboard zeigt „Daten konnten nicht geladen werden"**
`frontend/data/entities.json` fehlt oder die Seite wird per `file://` geöffnet. Lösung:
`python scripts/refresh_frontend_data.py` und über einen HTTP-Server ausliefern
(`cd frontend && python -m http.server 8000`).

**`GET /runs/latest/report` liefert 404**
Es existiert noch kein Lauf mit Report, oder die Markdown-Datei wurde gelöscht. Einen Lauf
ausführen bzw. `scoredclub report` zum Neu-Rendern nutzen.

## CI / GitHub Actions

**`monthly-run`/`pages` lassen sich nicht auslösen (404)**
`schedule`/`workflow_dispatch` laufen nur für Workflows auf dem **Default-Branch**. Den
Workflow auf den Default-Branch mergen. `ci.yml` (Push) läuft auf jedem Branch.

**GitHub Pages erscheint nicht**
In *Settings → Pages → Source: „GitHub Actions"* aktivieren. Private Repos brauchen einen
Pages-fähigen Plan.
