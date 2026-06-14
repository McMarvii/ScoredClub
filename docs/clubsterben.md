# Clubsterben-Register

`scoredclub.clubsterben` ist das differenzierende Berlin-Feature: ein Register des
Kulturökosystems statt nur Relevanz-Scoring. Es aggregiert pro Entität erfasste
**Lifecycle-Events** (Eröffnungen/Schließungen/Umzüge mit Ursachen-Taxonomie) und
**Verdrängungssignale** zu einem szeneweiten Bild — abrufbar über CLI (`scoredclub
clubsterben`) und API (`GET /clubsterben`).

## Datenmodell (im [Schema](schema.md), beides optional)

```jsonc
"lifecycle_events": [
  { "date": "2025-03-01", "event_type": "closure", "cause": "rent",
    "description": "Mietvertrag nicht verlängert", "source": "https://..." }
],
"displacement_signals": [
  { "signal_type": "property_sale", "description": "Grundstück verkauft 2025", "date": "2025-02-01" }
]
```

- `event_type`: `opening | closure | reopening | relocation | threatened`
- `cause` (Schließungs-Taxonomie): `rent | noise | redevelopment | insolvency | pandemic |
  licensing | sale | other | unknown`
- `signal_type`: `rent_increase | property_sale | rezoning | noise_complaint | construction | other`

Beide Listen werden beim Merge vereinigt; sind sie leer, werden sie aus dem Report-JSON
weggelassen (Output bleibt schlank/stabil).

## Register

`build_register` liefert:

- **`openings` / `closures` / `net_change`** — Netto-Veränderung der Szene.
- **`closures_by_cause`** — Schließungen nach Ursache (z. B. Miete vs. Umbau).
- **`by_year`** — Eröffnungen/Schließungen je Jahr.
- **`at_risk`** — gefährdete Venues: Status `closed`/`inactive`, vorhandene
  Verdrängungssignale **oder** ein `threatened`-Event.
- **`recent_events`** — jüngste Lifecycle-Events (absteigend nach Datum).

```bash
scoredclub clubsterben          # Register in der Konsole
curl localhost:8000/clubsterben # JSON
```

Daten kommen über `ingest`/Research (die Felder sind Teil des Entitäts-Schemas) — nicht über
die Seeds, daher bleibt der kanonische Lauf stabil. Teil von **P3** der
[Roadmap v2](roadmap-v2.md); ein automatischer Förder-/Policy-Feed bleibt offener Ausbau.
