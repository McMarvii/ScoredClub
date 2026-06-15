# Datenschema (`EntityProfile`)

Dies ist das kanonische Format für Research-Dateien und die gespeicherten Profile.
Definition: `src/scoredclub/schemas.py` (Pydantic v2). Unbekannte Felder werden
ignoriert (`extra="ignore"`), fehlende Werte sind erlaubt und werden von den
Scoring-Rubriken toleriert.

## Top-Level-Felder

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `entity_id` | string | Stabiler Slug. Wird aus `name` abgeleitet, wenn leer (z. B. „://about blank" → `about-blank`). |
| `name` | string | **Pflicht.** Anzeigename. |
| `aliases` | string[] | Alternative Namen (für Dedup). |
| `type` | enum | **Pflicht.** `club | collective | label | series | artist` |
| `provenance` | map | Optional. Feldpfad → `{source, confidence?, accessed_at?, note?}`. Siehe [Compliance](compliance.md). |
| `demand` | object\|null | Optional. `{going_count?, sold_out?, waitlist?, source?}` — Event-Nachfrage-Proxys (RA „going", Dice/Shotgun). |
| `follower_history` | map | Optional. Plattform → `[{date?, followers}]` (Follower-Zeitreihe). |
| `follower_audit` | object\|null | Optional. `{fake_follower_pct?, engagement_rate?, quality_score?, source?, checked_at?}` aus externem Audit. Siehe [Follower-Echtheit](authenticity.md). |
| `top_tracks` | list | Optional. `{title, artist?, label?, url?, plays?, released?, rank?, source?}` (Top-Songs). Siehe [Steckbrief](dossier.md). |
| `top_sets` | list | Optional. `{title, venue?, date?, url?, plays?, duration_min?, source?}` (Top-Sets). Siehe [Steckbrief](dossier.md). |
| `parties` | list | Optional. `{name, venue?, date?, role?, url?, source?}` (gespielte Partys). Siehe [Steckbrief](dossier.md). |
| `lifecycle_events` | list | Optional. `{date?, event_type, cause?, description?, source?}` (Clubsterben). Siehe [Clubsterben](clubsterben.md). |
| `displacement_signals` | list | Optional. `{signal_type, description?, date?, source?}` (Verdrängung). Siehe [Clubsterben](clubsterben.md). |
| `status` | enum | **Pflicht.** `active | emerging | inactive | closed | unknown` |
| `address` | string\|null | Adresse / Hauptort. |
| `district` | string\|null | Berliner Bezirk. |
| `geo` | Geo | `{ lat, lon }` (optional, kein Geocoding in V1). |
| `active_since` | string\|null | „YYYY" oder „YYYY-MM". Ganzzahlen werden akzeptiert. |
| `last_event_date` | date\|null | ISO-Datum des letzten bekannten Events. |
| `online` | OnlinePresence | Social-/Web-Präsenz (siehe unten). |
| `events` | EventsInfo | Event- und RA-Daten. |
| `press` | PressInfo | Presse-Erwähnungen. |
| `community` | CommunityInfo | Reddit/Twitter/Sentiment. |
| `networking` | NetworkingInfo | Bookings, Kollaborationen. |
| `policy_safety` | PolicySafety | Awareness-/Safer-Space-Flags. |
| `labels_podcasts` | LabelsPodcasts | Eigenes Label / Podcast. |
| `cultural_recognition` | CulturalRecognition | Clubcommission/UNESCO/Förderung. |
| `incidents` | Incident[] | Dokumentierte Vorfälle (Malus). |
| `sources` | SourceRef[] | Belege (URLs). |
| `notes` | string\|null | Freitext-Zusammenfassung. |
| `last_verification` | datetime\|null | Zeitpunkt der letzten Prüfung (steuert Merge-Vorrang). |
| `score` | ScoreBreakdown | **Nur in der Ausgabe**, nicht Teil der Eingabe. |

## Verschachtelte Strukturen

### OnlinePresence
Acht Plattformen, jede vom Typ `SocialPresence`:
`website, instagram, facebook, soundcloud, mixcloud, bandcamp, youtube, tiktok`.

**SocialPresence:**
```json
{ "url": "string|null", "handle": "string|null", "followers": 0,
  "posts_per_month": 0.0, "last_activity": "date|null", "activity_hint": "string|null" }
```
`activity_hint = "inactive"` schließt die Plattform aus der Reichweiten-Breite aus.

### EventsInfo
```json
{ "ra_profile_url": "string|null", "ra_followers": 0,
  "events_last_3_months": 0, "events_last_6_months": 0,
  "ticketing_platforms": ["RA", "Dice", "..."] }
```

### PressInfo
```json
{ "major_features": ["RA Feature 2025", "Mixmag ..."],
  "local_press_mentions": ["taz", "tip Berlin"],
  "international_mentions": ["The Guardian"],
  "cultural_funding_mentions": ["Clubkultur-Förderung 2024"] }
```

### CommunityInfo
```json
{ "reddit_threads": ["https://reddit.com/r/berlin/comments/..."],
  "twitter_handles": ["@..."],
  "community_sentiment_hint": "positive" }
```
`community_sentiment_hint` ∈ `positive | mixed | negative | unknown` (**ein Wort**).

### NetworkingInfo
```json
{ "booked_djs": ["Ben Klock", "..."], "cross_promotions": ["..."],
  "collaborations": ["..."], "international_booking": true }
```

### PolicySafety (Tri-State)
```json
{ "safer_spaces_communicated": "yes", "queer_friendly": "yes", "flinta_focus": "unclear" }
```
Akzeptiert `yes/ja/true`, `no/nein/false`, `unclear/unknown` (→ `null`) sowie echte
Booleans.

### LabelsPodcasts
```json
{ "own_label": "yes", "podcast_series": "no", "details": ["Ostgut Ton"] }
```

### CulturalRecognition
```json
{ "clubcommission_member": true, "unesco_mention": true, "cultural_funding": false }
```

### Incident
```json
{ "date": "2026-05-18", "description": "Brandanschlag, kein Personenschaden", "source": "https://..." }
```
`date` muss ein **vollständiges** ISO-Datum sein (`YYYY-MM-DD`) oder weggelassen werden.

### SourceRef
```json
{ "url": "https://...", "accessed_at": "2026-06-13", "note": "optional" }
```

## ScoreBreakdown (nur Ausgabe)

```json
{ "subscores": { "A_event_activity": 100.0, "...": "..." },
  "points":    { "A_event_activity": 20.0, "...": "..." },
  "bonus_items": ["Eigenes Label oder Podcast-Reihe"],
  "malus_items": ["Vorfall: ..."],
  "bonus": 15.0, "malus": 0.0, "base": 72.8, "total": 87.8, "tier": "TOP-TIER" }
```

## Minimal gültiges Profil

```json
{ "name": "Neues Kollektiv", "type": "collective", "status": "emerging",
  "sources": [{ "url": "https://instagram.com/neueskollektiv" }],
  "last_verification": "2026-06-13T00:00:00Z" }
```

## Häufige Validierungsfehler

| Meldung | Ursache | Lösung |
|---------|---------|--------|
| `community_sentiment_hint: Input should be 'positive'...` | ganzer Satz statt Enum | auf ein Wort kürzen |
| `incidents.0.date: ... should have zero time` | Jahr-only oder Datetime | volles `YYYY-MM-DD` oder Feld weglassen |
| `cultural_funding: Input should be a valid boolean` | Freitext statt yes/no | `true`/`false` setzen, Prosa in `cultural_funding_mentions` |
| `type: Input should be 'club'...` | unbekannter Typ | auf erlaubtes Enum mappen |

Validieren mit `scoredclub ingest <datei> --dry-run`.
