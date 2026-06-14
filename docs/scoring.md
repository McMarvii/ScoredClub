# Scoring-Modell

Jede Entität erhält einen **Relevanz-Score von 0–100**. Er setzt sich aus sieben
Dimensionen (A–G), Bonus- und Malus-Punkten zusammen. Die Implementierung steht in
`src/scoredclub/scoring/rubric.py` (reine Funktionen pro Dimension) und
`src/scoredclub/scoring/engine.py` (Kombination + Tier).

## Formel

Jede Dimensionsrubrik liefert einen **normalisierten Subscore 0–100**. Der Basis-Score
ist die gewichtete Summe; die im Report gezeigten **Punkte** sind `Gewicht × Subscore`,
sodass die Maxima der ursprünglichen Spezifikation entsprechen.

```
punkteᵢ = gewichtᵢ × subscoreᵢ
basis   = Σ punkteᵢ
total   = clamp(basis + Bonus − Malus, 0, 100)
```

> **Warum so?** Die ursprüngliche Spezifikation multiplizierte bereits unterschiedlich
> skalierte Punktwerte (die zusammen 100 ergeben) ein zweites Mal mit Gewichten. Diese
> Doppelgewichtung wird hier sauber aufgelöst: Rubriken liefern 0–100, Gewichte sind
> unabhängig justierbar, und die sichtbaren Punkt-Maxima bleiben wie spezifiziert.

## Dimensionen, Standardgewichte und Maxima

| Kürzel | Dimension | Gewicht | Max. Punkte |
|--------|-----------|--------:|------------:|
| **A** | Event-Aktivität | 0.20 | 20 |
| **B** | Online-Reichweite | 0.20 | 20 |
| **C** | Presse-Präsenz | 0.15 | 15 |
| **D** | Community-Resonanz | 0.15 | 15 |
| **E** | Szene-Vernetzung | 0.10 | 10 |
| **F** | Kontinuität | 0.10 | 10 |
| **G** | Safety & Inclusivity | 0.10 | 10 |

Die Gewichte stehen in `config/...json` unter `scoring.weights` und müssen zu 1.0
summieren, damit `total` im Bereich 0–100 bleibt.

## Die Rubriken im Detail

### A — Event-Aktivität
Basis ist die Monatsrate der letzten 3 Monate (`events.events_last_3_months / 3`):

| Rate | Subscore |
|------|---------:|
| ≥ 4 / Monat | 100 |
| ≥ 2 / Monat | 75 |
| ≥ 1 / Monat | 50 |
| > 0 | 30 |
| 0 in 3 Mon., aber > 0 in 6 Mon. (`events_last_6_months`) | 15 |
| sonst | 0 |

**Stale-Guard:** −20 (Boden 0), wenn trotz Zählern das `last_event_date` älter als
90 Tage ist.

### B — Online-Reichweite
`0.7 × Follower-Band + 0.3 × Plattform-Breite`.

Follower-Band aus der höchsten Followerzahl über alle Plattformen (inkl. `ra_followers`):

| Follower | Band |
|----------|-----:|
| ≥ 100k | 100 |
| ≥ 50k | 85 |
| ≥ 20k | 70 |
| ≥ 10k | 55 |
| ≥ 5k | 40 |
| ≥ 1k | 25 |
| > 0 | 10 |
| unbekannt | 0 |

Plattform-Breite = `min(aktive Plattformen, 6) / 6 × 100`. Eine Plattform zählt als
aktiv, wenn sie eine `url` oder `handle` hat und `activity_hint` nicht `"inactive"` ist.

### C — Presse-Präsenz
- 40 Punkte je Eintrag in `press.major_features` (gedeckelt bei 80)
- +5 je Eintrag in `press.local_press_mentions` (gedeckelt bei 10)
- +5, wenn `press.international_mentions` vorhanden
- +5, wenn `press.cultural_funding_mentions` vorhanden
- Deckel 100. Welche Outlets „major" sind, entscheidet die Recherche (Datenfrage, kein Code).

### D — Community-Resonanz
Reddit-Thread-Band aus `community.reddit_threads`:

| Threads | Punkte |
|---------|-------:|
| ≥ 10 | 60 |
| ≥ 5 | 45 |
| ≥ 1 | 25 |
| 0 | 0 |

+10, wenn `community.twitter_handles` vorhanden. Dann Multiplikator nach
`community_sentiment_hint`: positive ×1.3, mixed ×1.0, negative ×0.6, unknown ×0.9.
Deckel 100.

> **Hinweis:** Ohne Reddit-Daten bleibt D = 0. Der [Reddit-Collector](data-collection.md)
> kann `reddit_threads` automatisch füllen, sofern Reddit erreichbar ist.

### E — Szene-Vernetzung
- 8 Punkte je `networking.booked_djs` (Deckel 56)
- 10 Punkte je `networking.collaborations` (Deckel 30)
- 7 Punkte je `networking.cross_promotions` (Deckel 14)
- Deckel 100.

### F — Kontinuität
Aus `active_since` (Jahr):

| Jahre aktiv | Subscore |
|-------------|---------:|
| ≥ 20 | 100 |
| ≥ 10 | 80 |
| ≥ 5 | 60 |
| ≥ 2 | 40 |
| ≥ 1 | 25 |
| < 1 oder unbekannt | 10 |

Status `closed` → 0.

### G — Safety & Inclusivity
Aus den Tri-State-Flags in `policy_safety` (yes/no/unklar):

- `safer_spaces_communicated` → +40
- `queer_friendly` → +40
- `flinta_focus` → +20

Nur ausdrückliche „yes"-Werte zählen; `null`/unklar zählt 0.

## Bonus (+5 je Kriterium, max. +15)

1. **Kulturelle Anerkennung** — `cultural_recognition.clubcommission_member` oder
   `unesco_mention` oder `cultural_funding`, oder `press.cultural_funding_mentions`.
2. **Eigenes Label / Podcast** — `labels_podcasts.own_label` oder `podcast_series`.
3. **Internationales Booking** — `networking.international_booking` oder
   `press.international_mentions`.
4. **Hohe Event-Nachfrage** — `demand.sold_out`/`demand.waitlist` oder
   `demand.going_count` ≥ 500 (Proxys aus RA „going"/Dice/Shotgun).

## Malus (−5 je Eintrag, Standard-Deckel −15)

- −5 je Eintrag in `incidents` (dokumentierte Vorfälle/Kontroversen).
- −5, wenn `status` = `inactive`.

Deckel und Punktwerte sind konfigurierbar (`scoring.malus_per_incident`,
`scoring.malus_cap`, `scoring.bonus_per_item`, `scoring.bonus_cap`).

## Tier-Einstufung

Reihenfolge der Prüfung (`engine.classify_tier`):

1. `status` ∈ {inactive, closed} → **INAKTIV/GESCHLOSSEN**
2. `last_event_date` älter als `inactive_after_days` (Standard 180) → **INAKTIV/GESCHLOSSEN**
3. `total ≥ 75` → **TOP-TIER**
4. `total ≥ 50` → **MID-TIER**
5. `total ≥ 25` → **EMERGING**
6. sonst → **INAKTIV/GESCHLOSSEN**

Die Schwellen stehen unter `scoring.tier_thresholds` ({top, mid, emerging}).

## Rechenbeispiel (Tresor, Lauf 2026-06-13)

```
A 20.0 | B 16.0 | C 13.5 | D 0.0 | E 9.3 | F 10.0 | G 4.0  → Basis 72.8
Bonus +15 (Label, internationales Booking, kulturelle Anerkennung)
Malus −0
Total = clamp(72.8 + 15 − 0, 0, 100) = 87.8  → TOP-TIER
```

D = 0, weil in diesem Lauf keine Reddit-Threads recherchiert werden konnten — eine
Datenfrage, kein Fehler im Modell.

## Datenkonfidenz (confidence-aware)

Der Score behandelt fehlende Daten als 0 — ein noch nicht recherchierter Club sieht damit
aus wie ein wirklich kleiner. Damit man „niedrig, weil klein" von „niedrig, weil dünne
Datenlage" unterscheiden kann, berechnet das System zusätzlich eine **Konfidenz** (0–100,
`src/scoredclub/scoring/confidence.py`):

- **Dimension-Presence** (A–G): Anteil der vorhandenen Eingangssignale je Dimension.
- **Vollständigkeit:** gewichteter Mittelwert der Presence über alle Dimensionen.
- **Frische:** aus `last_verification` (frisch = 100, verfällt mit dem Alter bis zu einem
  Boden; fehlt sie ganz → niedriger Standardwert).
- **Konfidenz** = Blend aus Vollständigkeit und Frische. Unter
  `confidence.low_confidence_threshold` (Default 50) wird die Entität als
  **⚠ geringe Datenbasis** markiert.

Zusätzlich liefert der Breakdown einen **bereinigten Score**
(`confidence_adjusted_total`): die Relevanz nur über die Dimensionen, für die tatsächlich
Daten vorliegen (die Gewichte werden über die bekannten Dimensionen renormalisiert). So
zieht ein fehlendes Feld den Score nicht fälschlich nach unten.

> **Wichtig:** `total` und `tier` bleiben unverändert — Konfidenz ist rein additiv und dient
> der Interpretation. Reports, CLI (`score`), API (`/entities/{id}` → `latest_breakdown`) und
> Dashboard zeigen die Konfidenz an. Konfigurierbar unter `scoring.confidence`.

## Gewichte/Schwellen anpassen

Alles ist über die [Konfiguration](configuration.md) justierbar, z. B. um Online-Reichweite
stärker zu gewichten:

```json
{ "scoring": { "weights": { "online_reach": 0.30, "event_activity": 0.10, "...": "..." } } }
```

Anschließend `scoredclub score` oder `scoredclub run` erneut ausführen.
