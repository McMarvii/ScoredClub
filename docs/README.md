# ScoredClub — Dokumentation

**ScoredClub** ist ein Intelligence- und Scoring-System für die Berliner Techno-Szene:
es erfasst Clubs, Kollektive, Labels und Partyreihen, berechnet einen Relevanz-Score
(0–100), hält die Score-Historie über Läufe hinweg fest, erzeugt menschen- und
maschinenlesbare Reports und stellt die Daten über eine API und ein statisches
Dashboard bereit.

Diese Dokumentation ist in Kapitel gegliedert. Wenn du neu bist, lies
**Installation → How-To** und schau dann gezielt in die Referenzkapitel.

## Inhalt

| Kapitel | Inhalt |
|---------|--------|
| [Installation](installation.md) | Voraussetzungen, Installation (lokal & Docker), erster Smoke-Test |
| [**How-To (Schritt für Schritt)**](howto.md) | Der komplette Arbeitsablauf von der Installation bis zum gehosteten Dashboard |
| [Architektur](architecture.md) | Komponenten, Datenfluss, Designentscheidungen |
| [Scoring-Modell](scoring.md) | Dimensionen A–G, Gewichte, Bonus/Malus, Tiers — exakte Regeln |
| [Trending](trending.md) | Trend-Analyse über die Score-Historie (Auf-/Absteiger, Momentum, Ränge) |
| [Datenschema](schema.md) | Alle Felder des `EntityProfile` (Research-JSON-Format) |
| [Datenerhebung & Research](data-collection.md) | Collectors, LLM-Research-Workflow, Dedup/Merge |
| [CLI-Referenz](cli.md) | Alle Befehle und Optionen |
| [HTTP-API](api.md) | Endpunkte der FastAPI-Lese-API |
| [Dashboard (Frontend)](frontend.md) | Statisches Dashboard, lokale Vorschau, Sicherheit |
| [Konfiguration](configuration.md) | `config/*.json` und Umgebungsvariablen |
| [Deployment](deployment.md) | Docker, PostgreSQL, CI, GitHub Pages, Scheduling |
| [Troubleshooting](troubleshooting.md) | Häufige Probleme und Lösungen |

## In einem Satz

```bash
pip install -e ".[dev]"                                   # installieren
scoredclub init-db && scoredclub seed                     # DB anlegen + Seeds laden
scoredclub run --research data/research/latest.json       # Pipeline ausführen
cd frontend && python -m http.server 8000                 # Dashboard ansehen
```

## Glossar

- **Entität** — ein Club, Kollektiv, Label oder eine Partyreihe (`EntityProfile`).
- **Seed** — eine der vordefinierten Start-Entitäten (`data/seeds/berlin_seed_entities.json`).
- **Run** — eine vollständige Pipeline-Ausführung; erzeugt Score-Snapshots, Diffs, Alerts und Reports.
- **Snapshot** — der Score einer Entität zu einem bestimmten Run (Grundlage der Historie).
- **Tier** — Einstufung anhand des Scores: TOP-TIER, MID-TIER, EMERGING, INAKTIV/GESCHLOSSEN.
- **Research-Datei** — von einem LLM/Researcher erzeugtes JSON mit Entitätsprofilen (Haupt-Datenquelle).
- **Collector** — Modul, das Daten aus einer externen Quelle holt (Clubcommission, Resident Advisor, Reddit).
