# Local Track

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

**Speichert die Standorte ausgewählter `person.*`- und `device_tracker.*`-Entitäten
dauerhaft in einer eigenen SQLite-Datei und gibt sie über zwei
WebSocket-Kommandos ans Dashboard.**

## Wofür das gut ist

Der Recorder von Home Assistant speichert Standorte zwar, löscht sie aber nach
`purge_keep_days` — und diese Einstellung ist **global**. Entweder man hebt
*alles* jahrelang auf oder nichts.

Local Track schreibt genau die Entitäten, um die es geht, in eine eigene Datei,
die der Recorder nie anfasst. Punkte werden beim Schreiben entdoppelt und nach
einer Weile ausgedünnt, damit die Datei nicht unbegrenzt wächst.

Wer das Ganze **sehen** will, braucht zusätzlich die Karte
**`busch-timeline-card`** aus dem Repo
[ha-busch-cards](https://github.com/luukkii123/ha-busch-cards) — Karten und
Integrationen lassen sich in HACS nicht im selben Repository ausliefern.

## Installation über HACS

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/luukkii123/ha-localtrack-integrations`,
   Kategorie: **Integration**
3. **Local Track** herunterladen, Home Assistant neu starten
4. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → „Local Track"

Manuell geht auch: den Ordner `custom_components/localtrack` nach
`<config>/custom_components/localtrack` kopieren und neu starten.

Voraussetzungen: Home Assistant **2024.11.0** oder neuer. Die Abhängigkeit
`aiosqlite` installiert Home Assistant beim ersten Start selbst.

## Einrichtung

Beim Hinzufügen fragt die Integration zwei Dinge:

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| Aufzuzeichnende Entitäten | — | eine oder mehrere `person.*` / `device_tracker.*`; Pflichtfeld |
| Verlauf aufbewahren | 400 d | nach so vielen Tagen wird ein Punkt gelöscht (1–3650) |

Über **Konfigurieren** kommen danach die Feinheiten dazu — und die Entitäten
lassen sich dort auch wieder ändern:

| Option | Standard | Grenzen | Wirkung |
| --- | --- | --- | --- |
| Mindestabstand | 20 m | 0–5000 | wie weit ein Punkt vom letzten entfernt sein muss … |
| Mindestabstand in der Zeit | 30 s | 1–86400 | … **oder** wie viel Zeit seither vergangen sein muss |
| Ausdünnen ab Alter | 30 d | 1–3650 | ab welchem Alter alte Punkte ausgedünnt werden |
| Intervall nach dem Ausdünnen | 300 s | 10–86400 | wie dicht sie danach höchstens noch liegen |

Die beiden Dedupe-Werte sind mit **oder** verknüpft: gespeichert wird, sobald
*eine* der beiden Bedingungen erfüllt ist. Der Abstand filtert GPS-Zittern im
Stand, das Zeitintervall sorgt dafür, dass auch ein langer Aufenthalt Punkte hat.

Eine Änderung der Optionen lädt die Integration neu.

**Es ist nur ein Eintrag möglich.** Es gibt eine Datenbank und ein
WebSocket-Kommando; ein zweiter Eintrag würde mit dem ersten um beides streiten.

## Was danach passiert

**Die Integration legt keine Entitäten an** — keine Sensoren, keine Geräte. Sie
hört am Zustandsbus mit, schreibt in ihre Datei und beantwortet Anfragen des
Frontends. Sichtbar wird sie erst durch eine Karte.

Ein Punkt wird geschrieben, wenn die Entität eine Zustandsänderung mit
`latitude`/`longitude` meldet und die Dedupe-Prüfung ihn durchlässt.
Attributänderungen ohne Koordinaten werden verworfen, bevor die Datenbank
überhaupt angefasst wird. `gps_accuracy` wird mitgespeichert, wenn vorhanden.

Einmal täglich läuft die Pflege: alles jenseits der Aufbewahrungsfrist wird
gelöscht, alles jenseits der Ausdünn-Grenze auf einen Punkt je Intervall
reduziert, danach gibt die Datei freie Seiten ans Dateisystem zurück.

## Wo die Daten liegen

`<config>/.storage/localtrack.db` — eine eigene SQLite-Datei, unabhängig von
`home-assistant_v2.db`. Ein `recorder.purge` löscht dort nichts. Ein Entfernen
der Integration löscht die Datei ebenfalls nicht.

```sql
CREATE TABLE points (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_id TEXT NOT NULL,
  ts REAL NOT NULL,          -- Unix-Epoch
  lat REAL NOT NULL,
  lon REAL NOT NULL,
  accuracy REAL
);
```

Zur Größenordnung: rund ein Punkt je Minute und Person sind etwa 0,5 Mio. Zeilen
im Jahr — vor dem Ausdünnen. Wie viele Megabyte das werden, hängt an der
Punktdichte und ist hier nicht gemessen.

## WebSocket-API

Die Karte liest ausschließlich hierüber. Kein REST-Endpunkt, kein Token im
Frontend.

```js
await hass.callWS({
  type: "localtrack/history",
  entity_id: "person.beispiel",
  start: "2026-08-24T00:00:00+02:00",
  end: "2026-08-24T23:59:59+02:00",
  max_points: 2000,           // optional, 2–50000, Standard 2000
});
// → { entity_id, points: [{ts, lat, lon, accuracy}], total, simplified }
```

Zeitangaben **ohne** Zeitzone gelten als lokale Zeit des HA-Hosts — sonst kippen
Aufenthalte um Mitternacht in den falschen Tag. Liegt `end` vor `start`, werden
beide getauscht.

Sind mehr Punkte vorhanden als `max_points`, reduziert der Server sie mit
**Douglas-Peucker**: Geraden kosten zwei Punkte, Kurven behalten ihre Form.
Stumpf jeden N-ten zu nehmen würde genau die Ecken wegwerfen, die die Route
ausmachen. Erster und letzter Punkt bleiben immer erhalten. `total` nennt die
Zahl vor der Reduktion, `simplified` sagt, ob reduziert wurde.

```js
await hass.callWS({ type: "localtrack/stats" });
// → { entities: [{entity_id, points, first_ts, last_ts}],
//     points, db_bytes, tracked }
```

`entities` zählt, was **in der Datei** steht (auch von Entitäten, die inzwischen
nicht mehr aufgezeichnet werden), `tracked` nennt, was **gerade** aufgezeichnet
wird. Ist die Integration nicht geladen, antworten beide Kommandos mit
`not_found`.

## Grenzen

- **Noch nicht in einem laufenden Home Assistant getestet.** Die Kernlogik ist
  gegengeprüft, das Zusammenspiel mit einer echten Installation nicht.
- **Die Routenqualität hängt an der Quelle, nicht am Code.** Die Companion-App
  meldet im Standardmodus nur bei deutlicher Bewegung oder Zonenwechsel — dann
  sind die Linien zwischen den Punkten gerade. „Hohe Genauigkeit" in der App
  (kostet Akku) oder ein eigener Tracker liefert dichtere Spuren.
- **Keine Entitäten**, siehe oben. Wer einen Zahlenwert im Dashboard will,
  braucht eine Karte oder ein Template.
- **Kein Import.** Was vor der Einrichtung passiert ist, steht nicht in der
  Datei; aus dem Recorder wird nichts übernommen.
- **Ein Eintrag**, nicht mehr.
- Die Ausdünnung behält den **ersten** Punkt jedes Zeitfensters, nicht den
  aussagekräftigsten.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
