# Booking-/Kollaborations-Graph

`scoredclub.graph` macht aus der `networking`-Dimension einen echten Graphen
(Venue ↔ Artist ↔ Kollektiv), statt nur Zähler zu bilden — abrufbar über CLI
(`scoredclub graph`) und API (`GET /graph`).

## Kanten

| Quelle | Relation | Bedeutung |
|--------|----------|-----------|
| `networking.booked_djs` | `books` | Org bucht DJ/Artist (Club/Kollektiv → Artist) |
| `networking.collaborations` (bei `artist`) | `played_at` | Artist hat Venue bespielt |
| `networking.collaborations` (Orgs) | `collaborates` | Zusammenarbeit mit anderer Org |
| `networking.cross_promotions` | `cross_promotes` | gegenseitige Bewerbung |
| `parties` (Gigography, ≥ N Auftritte) | `resident` | Artist ist Resident einer Venue |

Referenzierte Namen werden – wo möglich – auf bestehende Entitäten aufgelöst
(über die Normalisierung/Alias-Logik), sonst als leichte **externe Knoten**
(`ext:<normalisiert>`) geführt. So verbinden sich die von [Bandsintown](data-collection.md)
gelieferten Venues eines Artists mit den geseedeten Clubs. Kanten werden dedupliziert,
Selbstbezüge verworfen.

## Residency-Erkennung

Eine **Residency** wird automatisch aus der Gigography (`parties`) abgeleitet: Erscheint ein
`artist` mindestens `analytics.residency_min_appearances` Mal (Default: **3**) an derselben
Venue, erhält das Paar eine `resident`-Kante im Graph. Die Erkennung ist deterministisch und
läuft im kanonischen Lauf ohne externe Quellen — je mehr Gigography-Daten vorhanden sind
(über [SoundCloud](data-collection.md#6-musik-collectors-soundcloud--mixcloud-enrichment),
[Bandsintown](data-collection.md#5-bandsintown-collector-enrichment----für-djartist-entitäten)/
Songkick oder `ingest`), desto besser die Auflösung.

Die Residency-Kante ist eigenständig gegenüber `played_at` (die aus `networking.collaborations`
kommt): Beide können für dasselbe Artist↔Venue-Paar gleichzeitig im Graphen erscheinen.

```bash
scoredclub collaborations berghain   # zeigt "residents" für Berghain
scoredclub graph                     # zeigt "top_residencies" in den Metriken
```

Schwellwert tunen: In der [Konfiguration](configuration.md) unter
`analytics.residency_min_appearances`.

## Metriken

`graph_metrics` leitet aus dem Graphen ab:

- **`top_venues`** — Venues nach Anzahl unterschiedlicher Artists (`played_at`).
- **`top_djs`** — meistgebuchte DJs/Artists nach Anzahl bucherender Orgs (`books`).
- **`top_connected`** — Knoten nach Grad (Degree-Zentralität).
- **`shared_bookings`** — Org-Paare, die **denselben DJ** buchen (geteilte Talent-Links).
- **`top_residencies`** — Venues nach Anzahl Resident-Artists (`resident`-Kanten).
- **`components`** — Anzahl zusammenhängender Komponenten (Union-Find, ungerichtet).

## Kollaborations-/Beziehungs-Ranking

„Wer arbeitet/bucht am meisten mit wem." Eine Zusammenarbeit zwischen zwei Knoten wird aus
drei Signalen gewichtet: **direkte Kante** (Gewicht 3, am stärksten), **gleicher gebuchter
DJ** (2) und **gleiches bespieltes Venue** (1).

- **`collaboration_pairs`** — stärkste Paare (wer mit wem), mit Aufschlüsselung
  `direct`/`shared_djs`/`shared_venues` und Gesamtgewicht.
- **`most_collaborative`** — Akteure nach Anzahl Partner (und Gesamtgewicht).
- **`entity_relationships`** — je Entität: `books` / `booked_by` / `collaborates_with` /
  `cross_promotes` / `played_venues` / `played_by` / **`residencies`** (Artist → Venues als
  Resident) / **`residents`** (Venue → resident Artists) / `shared_booking_partners`.

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
