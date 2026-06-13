# Trending (Trend-Analyse)

Trending wertet die **Score-Historie** über mehrere Läufe aus: wer steigt, wer fällt,
mit welchem Momentum, und wie verändern sich die Ränge. Die Ergebnisse werden in der
Datenbank persistiert (`trend_snapshots`) und über CLI, API und Dashboard bereitgestellt.

> Trends brauchen **mindestens zwei Läufe**. Beim ersten Lauf ist jede Entität `new`
> (kein Verlauf, keine Deltas).

## Kennzahlen

Pro Entität im aktuellen Lauf (`src/scoredclub/trending.py`):

| Feld | Bedeutung |
|------|-----------|
| `rank` | Platzierung nach Score (1 = höchster Score). |
| `score_delta` | Score-Änderung gegenüber dem vorherigen Lauf. |
| `rank_delta` | Rang-Änderung (positiv = nach oben gerückt). |
| `momentum` | Mittel der Score-Deltas über das Fenster der letzten Läufe. |
| `direction` | `rising` · `falling` · `stable` · `new`. |
| `sparkline` | Chronologische Score-Folge über das Fenster. |

**Richtung** ergibt sich aus dem Momentum: `> stable_epsilon` → `rising`,
`< -stable_epsilon` → `falling`, dazwischen → `stable`; ohne Verlauf → `new`.

**Movers** sind die größten Auf- und Absteiger (nach `score_delta`), begrenzt durch
`movers_limit`.

## Konfiguration

Unter `trending` in der [Konfiguration](configuration.md):

```json
{ "trending": { "momentum_window": 4, "stable_epsilon": 1.0, "movers_limit": 5 } }
```

| Schlüssel | Bedeutung |
|-----------|-----------|
| `momentum_window` | Anzahl der letzten Läufe für Momentum/Sparkline. |
| `stable_epsilon` | Schwelle, ab der Momentum als steigend/fallend statt stabil gilt. |
| `movers_limit` | Anzahl der gelisteten Auf-/Absteiger. |

## CLI

```bash
scoredclub trending --movers 5
```

Beispielausgabe:

```
Aufsteiger:
  ▲ OXI                        55.1  (Δ +31.9)
Absteiger:
  ▼ KitKat Club                54.8  (Δ -8.4)

Leaderboard:
   1. → Tresor                     87.8
   2. → Berghain                   86.1
  10. ▲ OXI                        55.1 (+14)
  11. ▼ KitKat Club                54.8 (-5)
```

## API

Siehe [HTTP-API](api.md):

- `GET /trending` — Leaderboard des letzten Laufs mit Richtung, Deltas und Rängen.
- `GET /trending/movers?limit=N` — Top-Auf- und -Absteiger.
- `GET /entities/{id}/trend` — vollständige Trend-Historie (Sparkline über alle Läufe).

## Im Report & Dashboard

- **Markdown-Report:** Die Zusammenfassung enthält den Abschnitt „Stärkste Bewegungen
  seit letztem Run" mit Auf-/Absteigern.
- **Entities-JSON:** Jede Entität trägt ein `trend`-Objekt (direction, score_delta, rank,
  rank_delta, momentum, sparkline).
- **Dashboard:** Auf den Entitäten-Karten erscheint ein Trend-Badge (▲ steigend,
  ▼ fallend, → stabil, ✦ neu) mit dem Score-Delta.

## Persistenz

Jeder Lauf schreibt eine `trend_snapshots`-Zeile pro Entität (run_id, entity_id, score,
rank, score_delta, rank_delta, momentum, direction). Das ist die dauerhafte Datenhaltung
für Trends; die API liest daraus, ohne neu zu rechnen. Quelle der Wahrheit für die
Berechnung bleiben die `score_snapshots`.

> **Hinweis:** Die Tabelle `trend_snapshots` wird per `create_all` angelegt. Bestehende
> Datenbanken aus älteren Versionen erhalten sie beim nächsten `init-db`/`run` automatisch
> (neue Tabelle, keine Migration nötig).
