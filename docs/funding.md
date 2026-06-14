# Förder-/Policy-Feed

`scoredclub.funding` ist ein leichter, einspielbarer Feed von **Förderprogrammen** der
Berliner Club-/Musikkultur und relevanten **Policy-/Status-Items** (Clubcommission/Senat,
UNESCO-ICH) — mit Deadline-Hinweisen. Gelesen aus einer JSON-Datei
(`sources.funding_feed_path`, Standard `data/funding/berlin_funding.json`), demselben
offline-/dateibasierten Muster wie der Research-Ingest. Kein DB-Tabelle, kein Live-Scraper.

## Datenmodell

```jsonc
{
  "programs": [
    { "name": "Clubkulturförderung", "provider": "Musicboard Berlin",
      "url": "https://...", "deadline": "2026-09-30", "eligibility": "Berliner Clubs/Kollektive",
      "amount": null, "status": "rolling", "notes": "Fristen je Runde prüfen" }
  ],
  "policies": [
    { "title": "Techno als UNESCO-ICH", "source": "UNESCO", "url": "https://...",
      "date": "2024-03-13", "summary": "..." }
  ]
}
```

## Nutzung

```bash
scoredclub funding --within 90      # Programme, anstehende Deadlines, Policy-Items
curl localhost:8000/funding         # {programs, policies, upcoming_deadlines}
```

`upcoming_deadlines` liefert Programme mit Frist von heute bis `within_days` voraus
(früheste zuerst); Programme ohne Frist werden hier ausgelassen.

Die mitgelieferte Seed-Datei enthält reale Berliner Programme (Musicboard, Clubkultur-/
Festivalförderung) und Policy-Items (UNESCO-ICH, Clubsterben) — **Deadlines bewusst `null`,
wo nicht gesichert**; bitte an der Quelle prüfen. Eine **Live-Erhebung deutschsprachiger
Quellen** (Senat/Musicboard/Clubcommission) bleibt offener Ausbau und kann später dieselbe
Datei schreiben. Teil von **P3** der [Roadmap v2](roadmap-v2.md).
