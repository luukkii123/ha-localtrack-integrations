# Local Track — Standortverlauf für Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Speichert die Standorte ausgewählter `person.*`- und `device_tracker.*`-Entitäten
**dauerhaft** in einer eigenen SQLite-Datei und liefert sie über ein
WebSocket-Kommando ans Dashboard. Gegenstück im Frontend ist die Karte
`busch-timeline-card` aus [ha-busch-cards](https://github.com/luukkii123/ha-busch-cards).

**Warum überhaupt?** Der Recorder speichert Standorte zwar, löscht sie aber nach
`purge_keep_days` — und diese Einstellung ist **global**. Entweder man hebt
*alles* jahrelang auf oder nichts. Local Track schreibt genau die Entitäten, um
die es geht, in eine eigene Datei, die der Recorder nie anfasst.

## Installation über HACS

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/luukkii123/ha-localtrack-integrations`,
   Kategorie: **Integration**
3. **Local Track** herunterladen, Home Assistant neu starten
4. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „Local Track"

Manuell geht auch: den Ordner `custom_components/localtrack` nach
`<config>/custom_components/localtrack` kopieren und neu starten.

## Einrichtung

| Feld | Bedeutung |
| --- | --- |
| Aufzuzeichnende Entitäten | Eine oder mehrere `person.*` / `device_tracker.*` |
| Verlauf aufbewahren | Tage, nach denen ein Punkt gelöscht wird (Standard 400) |

Über **Konfigurieren** kommen danach die Feinheiten dazu:

| Option | Standard | Wirkung |
| --- | --- | --- |
| Mindestabstand | 20 m | Punkt wird verworfen, wenn er näher liegt … |
| Mindestabstand in der Zeit | 30 s | … **und** kürzer her ist als das hier |
| Ausdünnen ab Alter | 30 Tage | ab wann alte Punkte ausgedünnt werden |
| Intervall nach dem Ausdünnen | 300 s | wie dicht sie danach noch liegen |

Die beiden Dedupe-Werte sind mit **oder** verknüpft: gespeichert wird, sobald
*eine* der beiden Bedingungen erfüllt ist. Der Abstand filtert GPS-Zittern im
Stand, das Zeitintervall sorgt dafür, dass auch ein langer Aufenthalt Punkte hat.

## Wo die Daten liegen

`<config>/.storage/localtrack.db` — eine eigene SQLite-Datei, unabhängig von
`home-assistant_v2.db`. Ein `recorder.purge` löscht dort nichts.

```sql
CREATE TABLE points (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id TEXT NOT NULL,
  ts REAL NOT NULL,          -- epoch
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  accuracy REAL
);
```

Größenordnung: rund ein Punkt je Minute und Person sind etwa 0,5 Mio. Zeilen und
~30 MB im Jahr — vor dem Ausdünnen. Danach deutlich weniger.

## WebSocket-API

Die Karte liest ausschließlich hierüber. Kein REST-Endpunkt, kein Token im
Frontend.

```js
await hass.callWS({
  type: "localtrack/history",
  entity_id: "person.beispiel",
  start: "2026-08-24T00:00:00+02:00",
  end: "2026-08-24T23:59:59+02:00",
  max_points: 2000,
});
// → { entity_id, points: [{ts, lat, lon, accuracy}], total, simplified }
```

Zeitangaben ohne Zeitzone gelten als **lokale Zeit des HA-Hosts** — sonst kippen
Aufenthalte um Mitternacht in den falschen Tag.

Sind mehr Punkte vorhanden als `max_points`, reduziert der Server sie mit
**Douglas-Peucker**: Geraden kosten zwei Punkte, Kurven behalten ihre Form.
Stumpf jeden N-ten zu nehmen würde genau die Ecken wegwerfen, die die Route
ausmachen. `total` nennt die Zahl vor der Reduktion.

```js
await hass.callWS({ type: "localtrack/stats" });
// → { entities: [{entity_id, points, first_ts, last_ts}], points, db_bytes, tracked }
```

## Grenzen

- **Die Routenqualität hängt an der Quelle, nicht am Code.** Die Companion-App
  meldet im Standardmodus nur bei deutlicher Bewegung oder Zonenwechsel — dann
  sind die Linien zwischen den Punkten gerade. „Hohe Genauigkeit" in der App
  (kostet Akku) oder ein eigener Tracker liefert dichtere Spuren.
- Es gibt **keine Entitäten**. Die Integration legt bewusst keine Sensoren an;
  sie speichert und liefert nur.
- Ein Eintrag genügt: eine Datenbank, ein WebSocket-Kommando. Ein zweiter würde
  mit dem ersten um beides streiten.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
