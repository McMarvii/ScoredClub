# Compliance, Provenance & Datenschutz

Ops-/Trust-Leitplanken für die Datenerhebung (P3). Drei Bausteine: **Per-Feld-Provenance**,
**GDPR-Retention** und eine **ToS-/robots-Konformitätsmatrix** je Collector.

## Per-Feld-Provenance

Jede Entität kann eine optionale `provenance`-Map tragen (im [Datenschema](schema.md)):
Feldpfad → Quelle/Konfidenz/Zugriffsdatum.

```json
"provenance": {
  "events.ra_followers": { "source": "https://ra.co/clubs/123", "confidence": 80, "accessed_at": "2026-06-14" },
  "policy_safety.queer_friendly": { "source": "instagram.com/...", "confidence": 60 }
}
```

- Optional und additiv — Entitäten ohne Provenance tragen eine leere Map (im Report-JSON
  weggelassen, damit der Output schlank bleibt).
- Beim Merge gewinnt die neuere Quelle pro Feldpfad, sonst werden Lücken gefüllt.
- Ergänzt das bestehende entitätsweite Confidence-Scoring um eine **feldgenaue** Herkunft.

## GDPR-Retention

Community-/personennahe Daten (Reddit-Thread-Links, Twitter-Handles) sind die sensibelsten
gespeicherten Felder. `scoredclub.retention` lässt sie nach einem Aufbewahrungsfenster
verfallen (abgeleitet aus `last_verification`), während das **Aggregat** (Sentiment-Hint,
bereits in Scores eingeflossene Zähler) erhalten bleibt.

```bash
scoredclub retention            # Dry-run: zeigt, was redigiert würde
scoredclub retention --apply    # schreibt die Redaktion
scoredclub retention --apply --days 180
```

Konfiguration unter `retention` (`enabled`, `community_days`, Default 365). Ohne
`last_verification` wird nichts angefasst (Staleness nicht beweisbar).

## ToS-/robots-/GDPR-Konformität je Collector

| Collector | Zugang | Status | Hinweis |
|-----------|--------|--------|---------|
| LLM-Research | Claude-API (offiziell) | ✅ konform | Nutzt offizielle API + web_search; keine Direkt-Scrapes. |
| Clubcommission | öffentliche Startseite | ⚠️ best effort | Nur öffentlich gelistete Member; kein Login/Umgehung. |
| Resident Advisor | inoffizielles GraphQL | ⛔ ToS-Risiko | **Keine** offizielle API; degradiert bewusst zu Warnung statt Scrape-Zwang. |
| Reddit | offizielle OAuth-API | ✅ konform | App-Only-Token, Rate-Limits respektiert; UA gesetzt. |
| Bandsintown | offizielle REST-API | ✅ konform | Sanktionierter Event-Pfad (App-ID). |
| Songkick | offizielle API | ✅ konform | Sanktionierter Event-Pfad (API-Key). |
| Sentiment | offline (kein Netz) | ✅ konform | Nur lokale Lexikon-Analyse vorhandener Daten. |

**Grundsätze:** robots.txt/ToS respektieren; keine Personendaten ohne legitimen Zweck; nur
öffentlich zugängliche, szene-relevante Inhalte; Aufbewahrung begrenzen (siehe Retention);
Provenance je Feld dokumentieren. RA bleibt bewusst best effort — der maßgebliche Pfad ist
die LLM-Research bzw. die sanktionierten Event-APIs. Teil von **P3** der [Roadmap v2](roadmap-v2.md).
