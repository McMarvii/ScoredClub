# Dashboard (Frontend)

Ein abhängigkeitsfreies Single-Page-Dashboard unter `frontend/` — reines HTML/CSS/JS,
**kein Build-Schritt**. Es visualisiert die Score-Daten und ist als Static-Site überall
hostbar.

## Funktionen

- Kennzahlen-Karten (Gesamtzahl, TOP-TIER, Clubs, Kollektive).
- **Bewegungen-Panel:** Top-Auf-/Absteiger seit dem letzten Run (aus `trend.score_delta`).
  Erscheint, sobald Trenddaten vorliegen (≥ 2 Läufe); klickbar → Detail-Dialog.
- **Listen-/Kartenansicht-Umschalter:** Die Karte plottet Entitäten nach Berliner Bezirk
  (genähert über statische Bezirks-Zentren, kein externer Geocoding-Dienst), Farbe = Tier,
  Klick → Detail. Filter wirken auch auf die Karte.
- Suche (Name/Bezirk), Filter nach Typ und Tier, Sortierung (Score/Name).
- **Watchlist:** ★-Stern je Entität (Karte + Dialog), persistiert in `localStorage`; Filter
  „Nur Watchlist" blendet auf die beobachteten Entitäten ein.
- **Gespeicherte Filter:** aktuelle Filter-/Sortier-/Watchlist-Auswahl benennen, speichern
  und später wieder laden oder löschen (`localStorage`).
- Entitäten-Karten mit Score, Tier-/Status-/Konfidenz-/Trend-Badges, IG-Followern und
  Mini-Balken der Dimensionen A–G.
- **Follower-Echtheit:** je Entität ein Badge (✓ echt / ⚠ auffällig / ✕ verdächtig) und im
  Detail-Dialog die Flags samt **historischem Follower-Verlauf** — eine Spiegelung des
  Moduls [`authenticity`](authenticity.md); **ohne Einfluss aufs Scoring**.
- **Steckbrief:** Detail-Dialog-Sektion mit Top-Songs, Top-Sets und gespielten Partys
  (sortiert/gekappt wie `scoredclub.dossier`), wenn die Daten vorliegen.
- Detail-Dialog pro Entität: **Score-Verlauf als Sparkline** (aus `trend.sparkline`),
  Score-Breakdown (A–G mit Balken), Bonus/Malus, Datenkonfidenz, **Gigography/Bookings**
  (gespielte Venues bei Artists bzw. gebuchte DJs bei Orgs), Presse-Highlights,
  Quellen-Links, Notizen.

## Dateien

```
frontend/
├── index.html        # Seitengerüst
├── style.css         # Dark-Theme
├── app.js            # Logik (Daten laden, rendern, filtern)
├── data/entities.json # Datenquelle (Kopie des neuesten Exports)
└── README.md
```

## Datenquelle

Das Dashboard lädt `frontend/data/entities.json` — eine Kopie der neuesten
`output/berlin_techno_entities_<DATUM>.json`. Aktualisieren:

```bash
python scripts/refresh_frontend_data.py
```

Das Skript sucht den neuesten Export in `output/`, prüft, dass er gültiges JSON ist, und
kopiert ihn nach `frontend/data/entities.json`.

## Lokale Vorschau

```bash
python scripts/refresh_frontend_data.py
cd frontend && python -m http.server 8000   # http://localhost:8000
```

> `file://` funktioniert nicht: `fetch` braucht denselben HTTP-Origin. Daher ein
> einfacher Static-Server (jeder geht — `python -m http.server`, `npx serve`, nginx …).

## Hosting

Siehe [Deployment](deployment.md). Kurz:

- **GitHub Pages** über `.github/workflows/pages.yml` (regeneriert Daten + deployt `frontend/`).
- **Jeder Static-Host**: `frontend/` ausliefern (vorher Daten refreshen).

## Sicherheit

Das Dashboard behandelt alle Daten als nicht vertrauenswürdig:

- **Kein `innerHTML` mit Daten.** Sämtliches Rendering läuft über `document.createElement`
  + `textContent` (Helper `el()` in `app.js`). Damit ist Stored-XSS über die Datendatei
  ausgeschlossen.
- **URL-Validierung.** Jede ausgehende URL (Quellen, RA-Profil) wird über `safeUrl()`
  geprüft (`new URL(...)`, nur `http:`/`https:`), bevor sie als `href` gesetzt wird —
  das blockt `javascript:`/`data:`-URLs.
- Externe Links erhalten `rel="noopener noreferrer"` und `target="_blank"`.
- `<meta name="referrer" content="no-referrer">` reduziert Referrer-Leaks.

Ein Security-Review des gesamten Branch-Diffs (inkl. Frontend) fand keine Schwachstellen.

## Anpassen

- **Aussehen:** `frontend/style.css` (CSS-Variablen oben für Farben/Theme).
- **Felder/Layout:** `frontend/app.js` — die Funktionen `entityCard()` und `openModal()`
  bestimmen, welche Felder wie angezeigt werden. Beim Hinzufügen von Feldern: weiterhin
  `el()`/`textContent` und für Links `safeLink()` verwenden.
