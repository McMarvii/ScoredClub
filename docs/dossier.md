# Steckbrief / Dossier

`scoredclub.dossier` baut je DJ, Venue oder Kollektiv einen verdichteten **Steckbrief**:
Identität + Kernzahlen, die **Top-10-Songs**, **Top-5-Sets**, die **max. Top-20 gespielten/
gehosteten Partys**, das Follower-Echtheits-Verdikt und die wichtigsten Beziehungen.

## Datenmodell (im [Schema](schema.md), alles optional)

```jsonc
"top_tracks": [ { "title": "...", "label": "Ostgut Ton", "plays": 120000, "rank": 1, "url": "...", "source": "soundcloud" } ],
"top_sets":   [ { "title": "Boiler Room 2024", "venue": "Berghain", "date": "2024-06-01", "plays": 90000, "url": "..." } ],
"parties":    [ { "name": "Klubnacht", "venue": "Berghain", "date": "2026-05-01", "role": "headliner" } ]
```

## Ranking (quellenbasiert, kein Blackbox-Geschmack)

- **Songs:** zuerst nach explizitem `rank` (1 = beste), dann nach `plays` absteigend → Top 10.
- **Sets:** nach `plays` absteigend, dann nach Datum (neueste zuerst) → Top 5.
- **Partys:** nach Datum absteigend (undatiert zuletzt) → Top 20.

Der Steckbrief enthält außerdem `follower_authenticity` (siehe [Follower-Echtheit](authenticity.md))
und `relationships` aus dem [Booking-Graphen](graph.md) (bucht / gebucht von / kollaboriert).

## Nutzung

```bash
scoredclub dossier berghain
curl localhost:8000/entities/berghain/dossier
```

Im Dashboard erscheint der Steckbrief als eigener Abschnitt im Detail-Dialog. Die Inhalte
kommen über `ingest`/Research (Teil des Entitäts-Schemas) oder künftige Musik-Collectors
(SoundCloud/Mixcloud, siehe [Roadmap v3](roadmap-v2.md)) — daher bleibt der kanonische Lauf
stabil (leere Listen werden im Report-JSON weggelassen).
