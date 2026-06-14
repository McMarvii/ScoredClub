# How-To: Von der Installation bis zum gehosteten Dashboard

Diese Anleitung führt durch den kompletten Arbeitsablauf. Jeder Schritt ist
eigenständig ausführbar; die meisten Befehle sind idempotent (mehrfaches Ausführen
schadet nicht).

- [1. Setup](#1-setup)
- [2. Seeds laden](#2-seeds-laden)
- [3. Recherche-Daten erzeugen](#3-recherche-daten-erzeugen-llm-research)
- [4. Validieren und einspielen](#4-validieren-und-einspielen)
- [5. Pipeline ausführen](#5-pipeline-ausführen)
- [6. Ergebnisse ansehen](#6-ergebnisse-ansehen)
- [7. Folgeläufe, Historie & Alerts](#7-folgeläufe-historie--alerts)
- [8. Dashboard ansehen](#8-dashboard-ansehen)
- [9. Dauerhaft hosten](#9-dauerhaft-hosten)
- [10. Automatisieren](#10-automatisieren)

---

## 1. Setup

```bash
pip install -e ".[dev]"
scoredclub init-db          # legt die SQLite-DB an (data/scoredclub.db)
```

`init-db` ist idempotent — vorhandene Tabellen bleiben erhalten.

## 2. Seeds laden

ScoredClub bringt 20 Start-Entitäten mit (15 Clubs, 5 Kollektive/Reihen):

```bash
scoredclub seed
# -> Seeded 20 new entities
```

Erneutes Ausführen legt keine Duplikate an (Dedup über Namensnormalisierung).
Die Seeds liegen in `data/seeds/berlin_seed_entities.json` und können angepasst werden.

## 3. Recherche-Daten erzeugen (LLM-Research)

Der maßgebliche Datenpfad ist eine **Research-Datei**: ein JSON, das Entitätsprofile
gemäß [Datenschema](schema.md) enthält. Sie wird typischerweise von einem LLM
(z. B. Claude mit Websuche) erzeugt, das pro Entität Follower, Event-Zahlen, Presse,
Awareness-Policies etc. recherchiert.

**Format** — entweder ein reines Array oder ein Objekt mit `entities`:

```json
{
  "generated_at": "2026-06-13T00:00:00Z",
  "entities": [
    {
      "entity_id": "berghain",
      "name": "Berghain",
      "type": "club",
      "status": "active",
      "district": "Friedrichshain",
      "active_since": "2004",
      "last_event_date": "2026-06-07",
      "online": { "instagram": { "handle": "berghain_panoramabar", "followers": 293000 } },
      "events": { "events_last_3_months": 13, "events_last_6_months": 26 },
      "press": { "major_features": ["RA Feature 2025"] },
      "policy_safety": { "safer_spaces_communicated": "yes", "queer_friendly": "yes" },
      "sources": [{ "url": "https://www.berghain.berlin", "accessed_at": "2026-06-13" }],
      "last_verification": "2026-06-13T00:00:00Z"
    }
  ]
}
```

**Wichtige Regeln** (sonst schlägt die Validierung fehl):

- Pflichtfelder pro Entität: `name`, `type`, `status`, plus sinnvollerweise `sources` und `last_verification`.
- `type` ∈ `club | collective | label | series | artist`
- `status` ∈ `active | emerging | inactive | closed | unknown`
- `community.community_sentiment_hint` ∈ `positive | mixed | negative | unknown` (ein Wort!)
- Zähler (Follower, Events) sind **ganze Zahlen**, keine Bereiche/Strings.
- Unbekannte Felder weglassen oder `null` — die Scoring-Rubriken tolerieren fehlende Daten.

Eine vollständige Vorlage und alle Felder stehen im [Datenschema](schema.md). Ein
fertiges Beispiel liegt unter `data/research/berlin_research_2026-06-13.json`.

> **Tipp:** Lass das LLM pro Entität ein Objekt füllen und schreibe alles in
> `data/research/berlin_research_<DATUM>.json`. Erfinde keine Zahlen — bei Unsicherheit
> `null` lassen.

## 4. Validieren und einspielen

Vor dem eigentlichen Lauf prüfen, ob die Datei dem Schema entspricht:

```bash
scoredclub ingest data/research/berlin_research_2026-06-13.json --dry-run
# -> 25 entities validated
```

Bei Fehlern wird pro ungültigem Eintrag der Index und der Grund ausgegeben; gültige
Einträge würden trotzdem eingespielt (Partial Ingest). `--dry-run` schreibt nichts.

Ohne `--dry-run` wird eingespielt (validiert, dedupliziert, gemerged):

```bash
scoredclub ingest data/research/berlin_research_2026-06-13.json
```

> Du musst nicht separat einspielen — `run --research <datei>` (nächster Schritt)
> macht das in einem Rutsch. Der separate `ingest` ist v. a. zum Validieren nützlich.

## 5. Pipeline ausführen

Der vollständige Lauf: Research einspielen → Collectors → Scoring → Diff zum Vorlauf
→ Alerts → Reports.

```bash
scoredclub run --research data/research/berlin_research_2026-06-13.json
```

**Nützliche Optionen:**

- `--skip-collectors` — Netzwerk-Collector überspringen (reproduzierbar/offline; nur Research-Daten).
- `--date YYYY-MM-DD` — Lauf-Datum setzen (sonst heute); steuert Dateinamen und Stale-Logik.
- `--config PATH` — alternative Konfigurationsdatei.

```bash
# Sauberer, reproduzierbarer Lauf nur auf Basis der Research-Datei:
scoredclub run --research data/research/berlin_research_2026-06-13.json --skip-collectors --date 2026-06-13
```

Ausgabe (Beispiel):

```
Run #1 finished
  entities tracked: 25
  new entities:     0
  alerts:           0
  report:           output/berlin_techno_check_2026-06-13.md
  entities json:    output/berlin_techno_entities_2026-06-13.json
```

## 6. Ergebnisse ansehen

```bash
scoredclub list                       # alle Entitäten mit Score & Tier
scoredclub list --tier TOP-TIER       # nur Top-Tier
scoredclub list --type collective     # nur Kollektive
scoredclub show berghain              # vollständiges Profil + Score-Historie
scoredclub score berghain            # Score-Breakdown einer Entität (A–G, Bonus, Malus)
```

Die generierten Dateien:

- `output/berlin_techno_check_<DATUM>.md` — Report nach Tiers, mit Score-Details und Zusammenfassung (Top 5 Clubs/Kollektive, neu entdeckte Entitäten, Alerts, Empfehlungen).
- `output/berlin_techno_entities_<DATUM>.json` — alle Profile + Breakdowns (Eingabe fürs Dashboard).
- `output/next_run.json` — nächster geplanter Run, Score-Änderungen, Alerts.

Siehe [Scoring-Modell](scoring.md), um die Zahlen zu interpretieren.

## 7. Folgeläufe, Historie & Alerts

Beim zweiten und jedem weiteren Lauf vergleicht ScoredClub die neuen Scores mit dem
vorherigen Lauf und erzeugt **Alerts**:

- **Score-Änderung** > Schwellwert (Standard ±10)
- **Statuswechsel** (z. B. `active` → `inactive`)
- **Neue Entität** (im aktuellen Lauf erstmals gesehen)

```bash
# Aktualisierte Research-Datei einspielen und erneut laufen lassen:
scoredclub run --research data/research/berlin_research_2026-07-13.json
```

Optional werden Alerts an einen **Webhook** geschickt (Slack/Matrix/Telegram-Bridge):

```bash
export SCOREDCLUB_WEBHOOK_URL="https://hooks.example.com/scoredclub"
scoredclub run --research data/research/latest.json
```

Historie einer Entität:

```bash
scoredclub show berghain        # zeigt u. a. die Score-Historie über alle Runs
```

## 8. Dashboard ansehen

Das Dashboard liest `frontend/data/entities.json`. Diese Datei aus dem neuesten Lauf
erzeugen und lokal servieren:

```bash
python scripts/refresh_frontend_data.py     # kopiert neuesten output/-Export
cd frontend && python -m http.server 8000   # http://localhost:8000
```

> `file://` funktioniert nicht (Browser-`fetch` braucht denselben Origin) — daher ein
> einfacher Static-Server.

Mehr Details: [Dashboard](frontend.md).

## 9. Dauerhaft hosten

Das Dashboard ist eine reine Static-Site und überall hostbar:

- **GitHub Pages** (empfohlen, im Repo enthalten): `.github/workflows/pages.yml` erzeugt
  die Daten frisch und deployt `frontend/`. Einmalig in *Settings → Pages → Source:
  „GitHub Actions"* aktivieren. (Workflow läuft vom **Default-Branch**; Private Repos
  brauchen einen Pages-fähigen Plan.)
- **Jeder Static-Host** (Netlify, Cloudflare Pages, S3, nginx): den Ordner `frontend/`
  ausliefern. Vorher `python scripts/refresh_frontend_data.py` ausführen.

Mehr Details: [Deployment](deployment.md).

## 10. Automatisieren

Für wiederkehrende Läufe gibt es zwei Wege:

- **GitHub Actions** (`.github/workflows/monthly-run.yml`): monatlicher Lauf, committet
  Reports und die State-DB zurück (für Historie), lädt Reports als Artifact hoch.
  Läuft vom Default-Branch.
- **Cron** (eigener Server):

  ```cron
  0 4 1 * * cd /opt/scoredclub && scoredclub run --research data/research/latest.json
  ```

`output/next_run.json` dokumentiert den nächsten geplanten Termin (+30 Tage,
konfigurierbar über `run.next_run_interval_days`).

---

## Komplettbeispiel (Copy-&-Paste)

```bash
# Setup
pip install -e ".[dev]"
scoredclub init-db
scoredclub seed

# Research validieren und Pipeline ausführen
scoredclub ingest data/research/berlin_research_2026-06-13.json --dry-run
scoredclub run --research data/research/berlin_research_2026-06-13.json --skip-collectors

# Ergebnisse ansehen
scoredclub list --tier TOP-TIER
scoredclub show berghain

# Dashboard
python scripts/refresh_frontend_data.py
cd frontend && python -m http.server 8000   # http://localhost:8000

# API (in einem zweiten Terminal)
scoredclub serve                            # http://127.0.0.1:8000/entities
```
