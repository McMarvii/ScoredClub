# Sentiment-Analyse (Lexikon, deterministisch)

`scoredclub.sentiment` leitet den `community_sentiment_hint` automatisch aus dem
verfügbaren Community-/Freitext einer Entität ab (Reddit-Thread-Titel + Notizen) und
ersetzt so den manuell gesetzten Hint. Bewusst **kein** Black-Box-Transformer: Lexikon-,
Negations- und Verstärker-Regeln sind nachvollziehbar (Erklärbarkeit ist hier ein Feature)
und laufen vollständig **offline** — kein Netz, kein Modell-Download, CI-tauglich.

## Verfahren

- **Folding:** Text wird wie in `normalize` auf ASCII gefaltet (ü→u, ß→ss …), das Lexikon
  ist in gefalteter Form notiert und matcht deutschen wie englischen Text.
- **Lexikon:** szene-relevante Positiv-/Negativ-Begriffe mit Gewichten (z. B. `legendary`,
  `safe`, `geil`, `beste` vs. `racist`, `unsafe`, `überteuert`, `gefährlich`).
- **Negation:** ein Negationswort (`not`, `kein`, `nicht`, …) im Fenster davor dreht die
  Polarität (`not bad` zählt nicht negativ).
- **Verstärker:** `very`, `sehr`, `mega`, … skalieren das Gewicht.
- **Aggregation:** `polarity = (pos − neg) / (pos + neg)`. Bei Signal auf beiden Seiten und
  nahezu neutraler Polarität → `mixed`, sonst `positive`/`negative`; kein Signal → `unknown`.

## Collector & Scoring

Der `SentimentCollector` (Enrichment, **standardmäßig aus** via `sources.sentiment_enabled`)
füllt nur **unbekannte** Hints — eine recherchierte Wertung wird nie überschrieben — und
läuft nach dem Reddit-Collector (sieht also frisch angehängte Threads). Der Hint speist über
den Sentiment-Multiplikator **Dimension D** (Community) im [Scoring](scoring.md).

```bash
scoredclub sentiment            # Analyse je Entität (kein Schreiben)
scoredclub sentiment berghain
# In der Konfiguration aktivieren:  sources.sentiment_enabled = true
```

Off by default, damit der kanonische Lauf unverändert bleibt. Teil von **P3** der
[Roadmap v2](roadmap-v2.md); eine echte ML-/Transformer-Variante bliebe ein optionaler
Ausbau analog zum LLM-Collector.
