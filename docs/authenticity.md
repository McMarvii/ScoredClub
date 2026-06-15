# Follower-Echtheit (Authentizitäts-Modul)

`scoredclub.authenticity` bewertet, ob die Follower einer Entität (DJs **und** Venues)
organisch wirken — als **separates, informatives Modul**, das das [Scoring](scoring.md)
**nicht beeinflusst** (`scoring/` importiert dieses Modul nie). Das Ergebnis wird in CLI,
API und Dashboard neben dem Score angezeigt. Offline und deterministisch; das Lexikon der
Signale ist nachvollziehbar.

## Signale

| Signal | Bedeutung | Strafe |
|--------|-----------|--------|
| **Spike** | abnormer Follower-Sprung in der Zeitreihe (Kauf-Signal) | −45 |
| **Drop** | starker Follower-Verlust (Bot-Bereinigung/Churn) | −35 |
| **Reichweite ohne Footprint** | viele Follower, kaum reale Aktivität/Resonanz | −35 |
| **Großes, inaktives Konto** | viele Follower, kaum Posts | −25 |

Spikes/Drops werden gegen die **eigene** typische Bewegung der Reihe bewertet (Median der
übrigen Schritte als Baseline, plus absolute/prozentuale Mindestschwelle), brauchen ≥ 3
Punkte. Der „Footprint" ist ein Proxy aus Events, Presse, Community, Bookings und
Anerkennung.

**Verdikt** (Start 100, Strafen abziehen): ≥ 80 `authentic`, 50–79 `questionable` (auffällig),
< 50 `suspicious` (verdächtig). Ein einzelnes Signal → „auffällig", mehrere → „verdächtig".
Ohne Follower-Daten: `inconclusive`.

> Heuristik, kein Beweis. Eine Tiefenprüfung (Engagement-Rate, Konto-Alter der Follower,
> Audience-Geografie) braucht Plattform-APIs und bleibt Ausbau.

## Externe Datensätze — abrufen & verifizieren

Über die internen Vergleiche hinaus zieht der **`FollowerAuditCollector`** einen *externen*
Datensatz heran (Social-Blade-/HypeAuditor-Stil): vermuteter Fake-Follower-Anteil,
Engagement-Rate und historische Follower-Zahlen. Damit wird die Echtheit **verifiziert**,
nicht nur intern verglichen.

- Provider-agnostisch: `FOLLOWER_AUDIT_API_KEY` setzen und `sources.follower_audit_url` auf
  einen Endpunkt (oder dünnen Adapter) richten, der die normalisierte JSON-Form liefert:
  `{ fake_follower_pct, engagement_rate, quality_score, source, checked_at, history:[{date,followers}] }`.
- No-op ohne Key oder ohne Instagram-Handle; fehlertolerant; mit gemocktem Client getestet.
- Das Ergebnis landet als `follower_audit` an der Entität; die gelieferte `history` fließt in
  `follower_history` (echte externe Verlaufsdaten). Siehe [Datenerhebung](data-collection.md).

**In die Bewertung einbezogen** (`assess`):

| Externes Signal | Bedingung | Strafe |
|-----------------|-----------|--------|
| Sehr hoher Fake-Anteil | `fake_follower_pct ≥ 50 %` | −55 |
| Erhöhter Fake-Anteil | `fake_follower_pct ≥ 30 %` | −30 |
| Sehr niedrige Engagement-Rate | `< 0,5 %` bei hoher Reichweite | −20 |

Die Audit-Daten erscheinen auch in `signals.audit` (API/Dashboard).

## Historische Daten — abrufen & auswerten

Das Modul wertet die **historische Follower-Trajektorie** je Plattform aus (`follower_history`):
Spikes, Drops, Wachstum (%/Steigung) und Volatilität — im API-Feld
`follower_authenticity.signals.history` und im Dashboard-Dialog sichtbar.

Damit sich diese Historie **aufbaut**, schreibt ein **optionaler** Pipeline-Schritt bei jedem
Lauf die aktuellen Follower-Zahlen je Plattform (inkl. RA) als datierten Punkt fort —
aktiviert über `authenticity.capture_history` (Standard **aus**, damit der kanonische Lauf
reproduzierbar bleibt). Unveränderte/taggleiche Werte werden nicht dupliziert.

```jsonc
"authenticity": { "capture_history": true }
```

## Nutzung

```bash
scoredclub authenticity                 # Verdikte je Entität (informativ)
scoredclub authenticity --flagged-only  # nur auffällig/verdächtig
curl localhost:8000/authenticity        # Liste der Verdikte
curl localhost:8000/entities/<id>       # follower_authenticity (inkl. signals.history)
```

Im Dashboard erscheint je Entität ein Echtheits-Badge (✓/⚠/✕) und im Detail-Dialog die
Flags samt historischem Follower-Verlauf. Die Anzeige-Logik im `frontend/app.js` spiegelt
die Schwellen dieses Moduls. Teil von **P3** der [Roadmap v2](roadmap-v2.md).
