# Local Track

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

**Speichert die Standorte ausgewählter `person.*`- und `device_tracker.*`-Entitäten
dauerhaft in einer eigenen SQLite-Datei und stellt sie dem Dashboard über
WebSocket-Kommandos bereit.**

Der Recorder von Home Assistant löscht Standorte nach `purge_keep_days`, und
diese Einstellung gilt global. Local Track schreibt nur die Entitäten, um die es
geht, in eine eigene Datei, die der Recorder nie anfasst. Punkte werden beim
Schreiben entdoppelt und nach einer Weile ausgedünnt, damit die Datei nicht
unbegrenzt wächst.

Die Integration legt **keine Entitäten und Geräte** an. Sichtbar wird sie über
die Karten aus
[ha-localtrack-cards](https://github.com/luukkii123/ha-localtrack-cards):
`localtrack-timeline-card` (Tagesweg auf der Landkarte) und
`localtrack-zone-time-card` (Verweildauer an einem Ort, Monat als Tagesliste).

## Voraussetzungen

- Home Assistant **2024.11.0** oder neuer
- Personen oder Device-Tracker, die `latitude`/`longitude` liefern, zum Beispiel
  über die Home-Assistant-Companion-App
- Kein API-Key und kein Token: Local Track braucht keinen externen Dienst. Die
  Bibliothek `aiosqlite` installiert Home Assistant beim ersten Start selbst.

## Installation

Über HACS:

1. HACS → ⋮ → **Benutzerdefinierte Repositories** (Custom repositories)
2. Repository `https://github.com/luukkii123/ha-localtrack-integrations`,
   Kategorie **Integration**
3. **Local Track** herunterladen und Home Assistant neu starten
4. Einstellungen → Geräte & Dienste → **Integration hinzufügen** → *Local Track*

Manuell: den Ordner `custom_components/localtrack` nach
`<config>/custom_components/localtrack` kopieren und neu starten.

*English:* add this repository to HACS as a custom repository of category
Integration, download *Local Track*, restart Home Assistant, then add the
integration under Settings → Devices & services. Every field carries its own
helper text in German and English.

## Einrichtung

Es ist **nur ein Eintrag** möglich. Beim Hinzufügen fragt der Dialog:

| Feld | Vorgabe | Bedeutung |
| --- | --- | --- |
| Aufzuzeichnende Entitäten | — (Pflicht) | eine oder mehrere `person.*` oder `device_tracker.*` |
| Verlauf aufbewahren | 400 Tage | nach so vielen Tagen wird ein Punkt gelöscht (1–3650) |

### Optionen

Über **Konfigurieren** lassen sich die Entitäten ändern und diese Werte
einstellen. Eine Änderung lädt die Integration neu.

| Option | Vorgabe | Grenzen | Bedeutung |
| --- | --- | --- | --- |
| Verlauf aufbewahren | 400 Tage | 1–3650 | wie oben |
| Mindestabstand | 20 m | 0–5000 | so weit muss ein Punkt vom letzten entfernt sein; 0 schaltet die Abstandsprüfung ab |
| Mindestzeitabstand | 30 s | 1–86400 | oder so viel Zeit muss seit dem letzten Punkt vergangen sein |
| Ausdünnen ab Alter | 30 Tage | 1–3650 | ab diesem Alter werden Punkte ausgedünnt |
| Ausdünn-Intervall | 300 s | 10–86400 | danach bleibt höchstens ein Punkt je Intervall |

Mindestabstand und Mindestzeitabstand sind mit **oder** verknüpft: Ein Punkt wird
gespeichert, sobald eine der beiden Bedingungen erfüllt ist. Der Abstand filtert
GPS-Zittern im Stand, das Zeitintervall sorgt dafür, dass auch ein langer
Aufenthalt Punkte hat.

## Was die Integration tut

- Ein Punkt wird geschrieben, wenn eine aufgezeichnete Entität eine
  Zustandsänderung mit `latitude`/`longitude` meldet und die Entdopplung ihn
  durchlässt. `gps_accuracy` wird mitgespeichert, falls vorhanden.
- Einmal täglich werden Punkte jenseits der Aufbewahrungsfrist gelöscht und
  ältere Punkte ausgedünnt.
- Das Dashboard liest über die WebSocket-Kommandos `localtrack/history`,
  `localtrack/stats` und `localtrack/zone_time`.

### Entitäten

Keine. Es entstehen weder Sensoren noch Geräte. Wer einen Zahlenwert im
Dashboard möchte, nutzt eine der Karten.

## Aktionen

### `localtrack.import_history` — Verlauf aus dem Recorder nachholen

Local Track sieht erst ab dem Moment etwas, in dem der Eintrag existiert. Der
Recorder hat aber zuvor `latitude`/`longitude` in die Attribute geschrieben. Die
Aktion holt diesen Verlauf einmal nach. Sie ist unter Entwicklerwerkzeuge →
Aktionen als **Local Track: Verlauf importieren** zu finden.

Zusätzlich läuft kurz nach dem Start automatisch ein Import für jede
aufgezeichnete Entität, die noch keinen einzigen gespeicherten Punkt hat.

| Feld | Vorgabe | Bedeutung |
| --- | --- | --- |
| `entity_id` | alle aufgezeichneten | eine oder mehrere `person.*` / `device_tracker.*`; leer bedeutet alle |
| `days` | 30 | wie viele Tage zurück der Recorder gefragt wird (1–400) |
| `overwrite` | aus | gespeicherte Punkte eines Tages vorher löschen und neu holen |
| `dry_run` | aus | nur zählen, nichts schreiben |

```yaml
action: localtrack.import_history
data:
  entity_id: person.beispiel
  days: 14
  dry_run: true
```

Die Aktion liefert eine Antwort mit `scanned`, `stored` und je Entität den
Listen `days_written`, `days_skipped` und `days_without_data`. Nicht
aufgezeichnete Entitäten und ein fehlender Eintrag führen zu einer Fehlermeldung.

Grenzen:

- Der Import reicht nur so weit zurück wie der Recorder. Was `purge_keep_days`
  bereits gelöscht hat, ist endgültig weg.
- Ein Tag, für den schon Punkte vorliegen, wird übersprungen, außer bei
  `overwrite`. Ein „Tag" sind hier die rollierenden 24 Stunden ab jetzt, nicht
  der Kalendertag.
- Der Import benutzt dieselbe Entdopplung wie die Live-Aufzeichnung.
- Bei langen Läufen kann ein Aufrufer mit Zeitlimit die Antwort verpassen; das
  Ergebnis steht dann im Protokoll, sofern `custom_components.localtrack` auf
  `info` steht.

## WebSocket-API

Die Karten lesen ausschließlich hierüber; es gibt keinen REST-Endpunkt. Die
Kommandos sind nur registriert, solange der Eintrag eingerichtet ist. Sonst
antwortet Home Assistant mit `unknown_command`.

| Kommando | Felder | Antwort |
| --- | --- | --- |
| `localtrack/history` | `entity_id`, `start`, `end`, optional `max_points` (2–50000, Vorgabe 2000) | `entity_id`, `points` (`ts`, `lat`, `lon`, `accuracy`), `total`, `simplified` |
| `localtrack/stats` | — | `entities` (je `entity_id`, `points`, `first_ts`, `last_ts`), `points`, `db_bytes`, `tracked` |
| `localtrack/zone_time` | `entity_id`, `latitude`, `longitude`, `radius` (1–100000 m), `start`, `end`, optional `min_visit_s` (Vorgabe 300, 0–21600), `max_gap_s` (Vorgabe 1800, 60–86400) | `days` (je `date`, `net_s`, `gross_s`, `visits`, `first_ts`, `last_ts`), `total_net_s`, `total_gross_s`, `total_visits`, `days_present` |

- Zeitangaben ohne Zeitzone gelten als lokale Zeit des Home-Assistant-Hosts.
- Bei mehr Punkten als `max_points` vereinfacht der Server die Route; erster und
  letzter Punkt bleiben erhalten.
- `zone_time` rechnet mit Mittelpunkt und Radius statt einer Zonen-ID und
  umfasst höchstens 366 Tage. Tagesgrenzen sind lokale Mitternacht des Hosts.
  `net_s` ist die Zeit tatsächlich im Umkreis, `gross_s` die Spanne von der
  ersten Ankunft bis zur letzten Abfahrt desselben Tages.

```js
await hass.callWS({
  type: "localtrack/history",
  entity_id: "person.beispiel",
  start: "2026-08-24T00:00:00+02:00",
  end: "2026-08-24T23:59:59+02:00",
});
```

## Datenschutz

Alle Standorte bleiben auf dem eigenen Home-Assistant-System in der Datei
`<config>/.storage/localtrack.db`, unabhängig von der Recorder-Datenbank. Die
Integration schickt nichts an Dritte. Die Karten laden Kartenkacheln von
OpenStreetMap (oder einem eigenen Kachelserver); Näheres steht in deren README.
Die Datei enthält Aufenthaltsorte und sollte wie ein Backup mit personenbezogenen
Daten behandelt werden. Wer die Datei sichert oder weitergibt, sollte das beachten.

## Grenzen

- Die Routenqualität hängt an der Quelle. Die Companion-App meldet im
  Standardmodus nur bei deutlicher Bewegung oder Zonenwechsel; „Hohe
  Genauigkeit" in der App (kostet Akku) liefert dichtere Spuren.
- Die Ausdünnung behält den ersten Punkt jedes Zeitfensters, nicht den
  aussagekräftigsten.
- Nur ein Eintrag.

## Entfernen

1. Einstellungen → Geräte & Dienste → **Local Track** → ⋮ → **Löschen**. Der
   Mitschnitt endet sofort.
2. In HACS **Local Track** → ⋮ → **Entfernen**, danach Home Assistant neu
   starten.

Die Datenbank `localtrack.db` bleibt bewusst erhalten, damit ein versehentliches
Entfernen keine Jahre an Standorten löscht. Wer sie loswerden will, löscht sie
bei gestopptem Home Assistant von Hand (daneben können `localtrack.db-wal` und
`localtrack.db-shm` liegen). Entitäten oder Geräte bleiben keine zurück.

## Entwicklung

Tests, Datenbankschema und Hintergründe: [docs/entwicklung.md](docs/entwicklung.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE).
