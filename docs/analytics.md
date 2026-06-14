# Analytics & Intelligence

Über das Basis-[Trending](trending.md) hinaus leitet `scoredclub.analytics` drei Signale
aus der Score-Historie ab — reine Funktionen, ohne Datenbank-Seiteneffekte, on demand
berechnet von CLI (`scoredclub analytics`) und API (`GET /analytics`).

## 1. Breakout-/Anomalie-Erkennung (dynamische Baseline)

Statt einer festen Score-Delta-Schwelle wird das jüngste Momentum gegen die **eigene
Volatilität** der Entität bewertet:

- **Baseline** = Standardabweichung der Run-zu-Run-Deltas, mit einem Boden
  (`breakout_baseline_floor`, Default 1.0), damit auch ein stetiger Anstieg zählt.
- **Slope** = Kleinste-Quadrate-Steigung (Punkte/Lauf) über das Fenster.
- **z** = `slope / baseline`. Nur positive Steigungen können ausbrechen.

| Bucket | Bedingung |
|--------|-----------|
| `explosive` | z ≥ `explosive_z` (3.0) |
| `strong` | z ≥ `strong_z` (2.0) |
| `growth` | z ≥ `growth_z` (1.0) |
| `none` | z < 1.0 oder fallend |
| `insufficient_data` | < 3 Läufe |

Dasselbe +5/Lauf bedeutet so bei einer ruhigen Entität (niedrige Volatilität → hohes z)
einen Ausbruch, bei einer sprunghaften (hohe Volatilität → niedriges z) nur normales
Rauschen.

## 2. Karrierephasen-Klassifikation (Perzentil)

Der **Perzentilrang** innerhalb der aktuellen Kohorte (Anteil niedriger bewerteter
Entitäten) wird auf eine gröbere, stabilere Phase abgebildet als die Score-Tiers:

| Phase | Perzentil |
|-------|-----------|
| `elite` | ≥ `elite_percentile` (90) |
| `established` | ≥ `established_percentile` (70) |
| `emerging` | ≥ `emerging_percentile` (40) |
| `developing` | sonst |

## 3. Kurzfrist-Forecast

Projektion des nächsten Scores aus der Kleinste-Quadrate-Steigung
(`projected_score = clamp(last + slope, 0, 100)`). `rising_soon` wird gesetzt, wenn die
Steigung `forecast_epsilon` (Default 0.5 Punkte/Lauf) übersteigt — ein „steigt bald"-Flag.

## Nutzung

```bash
scoredclub analytics                 # Breakouts + Intelligence-Tabelle
scoredclub analytics --breakouts-only
curl localhost:8000/analytics        # {runs_considered, entities[], breakouts[]}
```

Tuning unter `analytics` in der [Konfiguration](configuration.md). Braucht ≥ 3 Läufe für
Breakout/Forecast; bei weniger Historie greifen `insufficient_data` bzw. flache Prognosen.
Teil von **P3** der [Roadmap v2](roadmap-v2.md).
