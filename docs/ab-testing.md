# A/B-Testing (Scoring-Vergleich)

Im Web-Sinn (Traffic-Split) ist A/B-Testing für ein CLI-/Static-Tool nicht relevant.
Die domänen-sinnvolle Form ist der **Vergleich zweier Scoring-Konfigurationen** auf
denselben Daten: „Wie ändern sich Ränge und Tiers, wenn ich die Gewichte anders setze?"

`scoredclub compare` scort alle Entitäten der Datenbank unter zwei Konfigurationen (A und
B) und zeigt Score-/Rang-Unterschiede, Tier-Wechsel und eine **Rang-Korrelation**
(Spearman). Die gespeicherten Daten werden dabei **nicht** verändert — es ist ein reines
Analyse-/Tuning-Werkzeug. Implementierung: `src/scoredclub/compare.py` (reine Funktionen).

## Befehl

```bash
scoredclub compare --config-b config/variants/reach_heavy.json
scoredclub compare --config-a config/variants/reach_heavy.json \
                   --config-b config/variants/community_safety.json
```

- `--config-b PATH` (Pflicht) — die Variante.
- `--config-a PATH` (optional) — die Basis; Standard ist die **aktive** Konfiguration.
- `--date YYYY-MM-DD` — Scoring-Datum (beeinflusst zeitabhängige Dimensionen A/F).
- `--write / --no-write` — Vergleichs-Report in den Output-Ordner schreiben (Standard an).

Voraussetzung: Es müssen Entitäten in der DB sein (`seed`/`run` zuvor). Verglichen werden
ausschließlich die `scoring`-Blöcke der beiden Konfigurationen; die DB-Verbindung kommt
aus der aktiven Konfiguration/`DATABASE_URL`.

## Beispiel-Ausgabe

```
Vergleich: aktiv vs. reach_heavy
  Rang-Korrelation (Spearman): 0.96
  Mittlere abs. Score-Differenz: 5.52
  Tier-Wechsel: 3
    Ritter Butzke: MID-TIER → TOP-TIER
    Club der Visionaere: MID-TIER → TOP-TIER
    OST Berlin: EMERGING → INAKTIV/GESCHLOSSEN
  Größte Rang-Bewegungen:
    ▲ Sisyphos                 Rang 8→5 (Δ score +13.6)
    ▼ Pornceptual              Rang 16→20 (Δ score -8.9)
```

## Kennzahlen

| Kennzahl | Bedeutung |
|----------|-----------|
| **Rang-Korrelation (Spearman)** | 1.0 = identische Reihenfolge, 0 = unkorreliert, −1 = umgekehrt. Misst, wie stark sich das Ranking insgesamt ändert. |
| **Mittlere abs. Score-Differenz** | Durchschnittliche \|Score B − Score A\| über alle Entitäten. |
| **Größte Score-Differenz** | Maximale absolute Score-Änderung. |
| **Tier-Wechsel** | Entitäten, die unter B in ein anderes Tier fallen. |
| **Größte Rang-Bewegungen** | Entitäten mit der stärksten Rang-Änderung. |

## Reports

Mit `--write` (Standard) entstehen im Output-Ordner:

- `scoring_compare_<A>_vs_<B>_<DATUM>.md` — Vergleichstabelle (Entität, Score A/B, Δ,
  Tier-Wechsel, Rang-Δ) plus Kennzahlen.
- `scoring_compare_<A>_vs_<B>_<DATUM>.json` — maschinenlesbar.

## Varianten-Konfigurationen

Eine Varianten-Datei braucht nur einen `scoring`-Block; fehlende Felder erben die
Standardwerte. Zwei Beispiele liegen bei:

- `config/variants/reach_heavy.json` — betont Online-Reichweite und Event-Aktivität.
- `config/variants/community_safety.json` — betont Community, Safety/Inclusivity und Presse.

So lassen sich Gewichtungen **datengetrieben** justieren und die gewählten Gewichte
begründen, bevor man sie in die aktive [Konfiguration](configuration.md) übernimmt.
Siehe auch das [Scoring-Modell](scoring.md).
