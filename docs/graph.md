# Booking-/Kollaborations-Graph

`scoredclub.graph` macht aus der `networking`-Dimension einen echten Graphen
(Venue ↔ Artist ↔ Kollektiv), statt nur Zähler zu bilden — abrufbar über CLI
(`scoredclub graph`) und API (`GET /graph`).

## Kanten

| Quelle (`networking`-Feld) | Relation | Bedeutung |
|----------------------------|----------|-----------|
| `booked_djs` | `books` | Org bucht DJ/Artist (Club/Kollektiv → Artist) |
| `collaborations` (bei `artist`) | `played_at` | Artist hat Venue bespielt |
| `collaborations` (Orgs) | `collaborates` | Zusammenarbeit mit anderer Org |
| `cross_promotions` | `cross_promotes` | gegenseitige Bewerbung |

Referenzierte Namen werden – wo möglich – auf bestehende Entitäten aufgelöst
(über die Normalisierung/Alias-Logik), sonst als leichte **externe Knoten**
(`ext:<normalisiert>`) geführt. So verbinden sich die von [Bandsintown](data-collection.md)
gelieferten Venues eines Artists mit den geseedeten Clubs. Kanten werden dedupliziert,
Selbstbezüge verworfen.

## Metriken

`graph_metrics` leitet aus dem Graphen ab:

- **`top_venues`** — Venues nach Anzahl unterschiedlicher Artists (`played_at`).
- **`top_djs`** — meistgebuchte DJs/Artists nach Anzahl bucherender Orgs (`books`).
- **`top_connected`** — Knoten nach Grad (Degree-Zentralität).
- **`shared_bookings`** — Org-Paare, die **denselben DJ** buchen (geteilte Talent-Links).
- **`components`** — Anzahl zusammenhängender Komponenten (Union-Find, ungerichtet).

## Kollaborations-/Beziehungs-Ranking

„Wer arbeitet/bucht am meisten mit wem." Eine Zusammenarbeit zwischen zwei Knoten wird aus
drei Signalen gewichtet: **direkte Kante** (Gewicht 3, am stärksten), **gleicher gebuchter
DJ** (2) und **gleiches bespieltes Venue** (1).

- **`collaboration_pairs`** — stärkste Paare (wer mit wem), mit Aufschlüsselung
  `direct`/`shared_djs`/`shared_venues` und Gesamtgewicht.
- **`most_collaborative`** — Akteure nach Anzahl Partner (und Gesamtgewicht).
- **`entity_relationships`** — je Entität: `books` / `booked_by` / `collaborates_with` /
  `cross_promotes` / `played_venues` / `played_by` / `shared_booking_partners`.

DJs sind dabei vollwertige Akteure: Eine direkte Booking-Kante (Org → DJ) zählt als
Zusammenarbeit, daher erscheinen vielbuchende Orgs und vielgebuchte DJs als „kollaborativ".

```bash
scoredclub collaborations                 # stärkste Paare + kollaborativste Akteure
scoredclub collaborations berghain        # Beziehungen einer Entität
curl localhost:8000/collaborations
curl localhost:8000/entities/berghain/relationships
```

## Nutzung

```bash
scoredclub graph                       # Top-Venues, -DJs, geteilte Bookings, Kollaborationen
scoredclub graph --export graph.json   # vollständige Knoten/Kanten als JSON
curl localhost:8000/graph              # nur Metriken
curl 'localhost:8000/graph?include_graph=true'   # Metriken + Knoten/Kanten
```

Der Graph wird live aus den aktuellen Entitäten gebaut (keine eigene Tabelle, keine
Migration). Teil von **P3** der [Roadmap v2](roadmap-v2.md) — die nächste Ausbaustufe wäre
eine visuelle Graph-Ansicht im Dashboard.
