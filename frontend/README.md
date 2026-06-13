# ScoredClub Dashboard (statisches Frontend)

Ein abhängigkeitsfreies Single-Page-Dashboard (reines HTML/CSS/JS, kein Build-Schritt),
das die Score-Daten aus `data/entities.json` visualisiert: Tier-/Typ-Filter, Suche,
Sortierung, pro Entität ein Detail-Dialog mit Score-Breakdown (A–G), Bonus/Malus,
Presse-Highlights und Quellen.

## Lokal ansehen

```bash
python scripts/refresh_frontend_data.py   # neueste output/-Daten -> frontend/data/entities.json
cd frontend && python -m http.server 8000 # http://localhost:8000
```

(`file://` funktioniert nicht, weil `fetch` denselben Origin braucht — daher ein
einfacher Static-Server.)

## Dauerhaftes Hosting

- **GitHub Pages:** `.github/workflows/pages.yml` regeneriert die Daten aus der jüngsten
  Research-Datei und deployt `frontend/`. Einmalig in *Settings → Pages → Source:
  „GitHub Actions"* aktivieren (Private Repos brauchen einen Pages-fähigen Plan).
- **Beliebiger Static-Host** (Netlify, Cloudflare Pages, S3 …): einfach den Ordner
  `frontend/` ausliefern.

## Sicherheit

Alle Daten werden als nicht vertrauenswürdig behandelt: Rendering ausschließlich über
`createElement`/`textContent` (kein `innerHTML` mit Daten), und jede ausgehende URL wird
auf `http(s)` geprüft, bevor sie als Link gesetzt wird. Damit ist Stored-XSS über die
Datendatei ausgeschlossen.
