# Installation

## Voraussetzungen

- **Python ≥ 3.11**
- **pip** (oder uv/pipx)
- Optional: **Docker** + **Docker Compose** für den Container-Betrieb
- Optional: **Git** (das Repo wird üblicherweise per Git geklont)

Es werden keine systemweiten Pakete außer Python benötigt. Alle Abhängigkeiten sind
reine Python-Pakete (siehe `pyproject.toml`).

## Lokale Installation (Entwicklung)

```bash
git clone <repo-url> ScoredClub
cd ScoredClub
python -m venv .venv && source .venv/bin/activate      # empfohlen, aber optional
pip install -e ".[dev]"
```

`-e` (editable) verlinkt den Quellcode, sodass Änderungen sofort wirken.
`[dev]` zieht zusätzlich `pytest` und `pytest-cov` für die Tests.

### Ohne Dev-Abhängigkeiten (reiner Betrieb)

```bash
pip install .
```

### Mit PostgreSQL-Treiber

```bash
pip install ".[postgres]"     # zieht psycopg2-binary zusätzlich
```

## Installation prüfen

```bash
scoredclub version
# -> scoredclub 0.1.0

scoredclub --help
```

## Erster Smoke-Test

Der schnellste Weg, um zu sehen, dass alles funktioniert (nutzt die mitgelieferte
Research-Datei, ohne Netzwerkzugriff):

```bash
scoredclub init-db
scoredclub seed
scoredclub run --research data/research/berlin_research_2026-06-13.json --skip-collectors
```

Danach liegen drei Dateien in `output/`:

- `berlin_techno_check_<DATUM>.md` — lesbarer Report
- `berlin_techno_entities_<DATUM>.json` — alle Profile + Score-Breakdowns
- `next_run.json` — Scheduling-Metadaten, Score-Änderungen, Alerts

Zur Kontrolle:

```bash
scoredclub list --tier TOP-TIER
# Tresor und Berghain sollten erscheinen.
```

## Tests ausführen

```bash
pytest               # 90 Tests
pytest -q            # knappe Ausgabe
pytest tests/test_scoring.py -v   # nur das Scoring
```

> **Hinweis:** Das Projekt setzt `pythonpath = ["."]` in `pyproject.toml`, damit die
> Tests sowohl mit `pytest` als auch mit `python -m pytest` laufen.

## Verzeichnisstruktur nach der Installation

```
ScoredClub/
├── config/berlin_techno_agent_config.json   # Standardkonfiguration
├── data/
│   ├── seeds/berlin_seed_entities.json       # 20 Start-Entitäten
│   ├── research/berlin_research_*.json        # Research-Daten (Eingabe)
│   └── scoredclub.db                          # SQLite-DB (wird angelegt, gitignored)
├── output/                                    # generierte Reports
├── frontend/                                  # statisches Dashboard
├── src/scoredclub/                            # Quellcode
└── tests/                                     # Testsuite
```

Weiter mit dem [How-To](howto.md).
