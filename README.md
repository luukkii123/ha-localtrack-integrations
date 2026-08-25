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
**`localtrack-timeline-card`** aus dem Repo
[ha-localtrack-cards](https://github.com/luukkii123/ha-localtrack-cards) —
Karten und Integrationen lassen sich in HACS nicht im selben Repository
ausliefern, deshalb zwei.

> Bis August 2026 lag die Karte als `busch-timeline-card` in
> [ha-busch-cards](https://github.com/luukkii123/ha-busch-cards). Wer sie von
> dort kennt: `type:` auf `custom:localtrack-timeline-card` ändern, die Optionen
> sind unverändert.

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

## Verlauf aus dem Recorder nachholen

Local Track sieht erst ab dem Moment etwas, in dem sein Eintrag existiert. Der
Recorder hat aber die ganze Zeit `latitude`/`longitude` in die Attribute jeder
`person`- und `device_tracker`-Entität geschrieben. Diese Überschneidung lässt
sich einmal einsammeln.

**Automatisch:** Kurz nach dem Start prüft die Integration jede aufgezeichnete
Entität. Wer **keinen einzigen** gespeicherten Punkt hat, wird aus dem Recorder
nachgefüllt. Das ist bewusst nicht in einem Merker festgehalten, sondern aus den
Daten abgeleitet: Eine Entität mit Punkten ist versorgt, eine ohne nicht. Der
Lauf begrenzt sich damit selbst — ein geglückter Import verhindert den nächsten —
und tut das Richtige, wenn später eine weitere Person dazukommt oder die Datei
absichtlich gelöscht wird.

**Von Hand:** Entwicklerwerkzeuge → Aktionen → **Local Track: Verlauf
importieren** (`localtrack.import_history`).

| Feld | Standard | Bedeutung |
| --- | --- | --- |
| Entitäten | alle | leer heißt: alles, was dieser Eintrag aufzeichnet |
| Tage zurück | 30 | wie weit der Recorder gefragt wird (1–400) |
| Überschreiben | aus | einen bereits gefüllten Tag vorher löschen und neu holen |
| Trockenlauf | aus | nur zählen, nichts schreiben |

```yaml
action: localtrack.import_history
data:
  entity_id: person.beispiel
  days: 14
  dry_run: true
```

Die Aktion liefert eine Antwort mit `scanned`, `stored` und je Entität den
Listen `days_written`, `days_skipped` und `days_without_data`.

**Drei Dinge, die das ausdrücklich nicht kann:**

- **Weiter zurück als der Recorder reicht es nicht.** Was `purge_keep_days`
  bereits gelöscht hat, ist weg. Auf der Entwicklungsinstallation waren es rund
  **acht Tage** — nachgemessen, nicht geschätzt: `oldest_recorder_run` stand auf
  dem 17.08.2026, Stichproben am 15./16./17.08. lieferten null Zeilen, ab dem
  18.08. welche.
- **Es entdoppelt nicht Zeile für Zeile.** `points` hat keinen eindeutigen
  Schlüssel auf `(entity_id, ts)`, ein zweiter Lauf würde also stillschweigend
  verdoppeln. Deshalb die gröbere, ehrlichere Sperre: Ein Kalendertag, für den
  schon Punkte vorliegen, wird übersprungen — außer bei **Überschreiben**.
- **Es ändert die Ausdünnung nicht.** Der Import benutzt dieselbe Regel wie der
  Live-Mitschnitt (Mindestabstand **oder** Mindestzeit), damit ein nachgeholter
  Tag genauso dicht ist wie ein mitgeschriebener.

Gefragt wird **tageweise**: eine dichte Quelle liefert Zehntausende Zeilen pro
Tag, und ein ganzer Monat am Stück läge ohne Gewinn gleichzeitig im Speicher.

**„Tag" heißt hier: rollierende 24 Stunden ab jetzt**, nicht Kalendertag ab
lokaler Mitternacht. Ein um 23:15 gestarteter Lauf schneidet die Fenster bei
23:15, und `days_written` nennt nur das lokale Datum des Fensteranfangs. Für
einen einmaligen Nachtrag ist das folgenlos. Wer denselben Bereich später zu
anderer Tageszeit erneut importiert, trifft auf verschobene Fenster — und damit
auf eine andere Entscheidung, welcher „Tag" schon voll ist.

### Was der Import in der Praxis liefert

Gemessen am 25.08.2026 an einer laufenden Installation (HA core-2026.8.3,
Recorder auf MariaDB, fünf Personen, `min_distance_m: 10`):

| Person | Rohzeilen | gespeichert | ausgedünnt |
| --- | --- | --- | --- |
| A (viel unterwegs) | 146 438 | 24 445 | 83 % |
| B | 9 112 | 5 471 | 40 % |
| C | 3 048 | 2 227 | 27 % |
| D | 1 963 | 1 961 | 0,1 % |
| E | 620 | 603 | 3 % |

Zusammen 34 708 Punkte in 2,5 MiB, Spanne knapp acht Tage — genau so weit, wie
der Recorder zurückreichte. **Der Ausdünnungsanteil sagt mehr über die Quelle
als über die Einstellung:** Wer viel steht und dabei dicht meldet, verliert den
größten Teil (GPS-Zittern); wer sich kaum bewegt und selten meldet, verliert
fast nichts.

Ein Lauf über zehn Tage und 146 000 Zeilen dauerte auf einem Raspberry Pi 4
rund **zwei Minuten**. Wer den Dienst über eine API mit Zeitablauf aufruft,
bekommt die Antwort möglicherweise nicht mehr — das Ergebnis steht dann im
Protokoll, sofern `custom_components.localtrack` auf `info` steht.

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
wird.

**Fehlt der Eintrag, ist die Antwort `unknown_command`, nicht `not_found`.**
Das ist kein Haarspalten, sondern der häufigste Fall: Registriert werden die
Kommandos in `async_setup_entry`, also existieren sie gar nicht, solange die
Integration zwar über HACS installiert, aber nie unter *Geräte & Dienste*
hinzugefügt wurde. `not_found` kommt nur vom Kommando selbst — dann, wenn der
Eintrag existiert, aber gerade entladen ist. Wer nur `not_found` abfängt,
verschweigt die häufigere Ursache; genau das ist der Karte am 25.08.2026
passiert.

## Grenzen

- **Seit 25.08.2026 in einem laufenden Home Assistant erprobt** (core-2026.8.3,
  Recorder auf MariaDB, Raspberry Pi 4): Einrichtung, Live-Mitschnitt, Import
  und die WebSocket-Abfrage der Karte. Zusätzlich läuft
  `python3 tests/smoke_test.py` ohne Home Assistant und deckt Ausdünnung,
  SQLite-Schicht und Import ab (Trockenlauf, Wiederholbarkeit, Überschreiben,
  Tagesaufteilung).

  **Nicht erprobt:** SQLite als Recorder-Datenbank (hier lief MariaDB), sehr
  große Zeiträume, und der automatische Erstimport im Erfolgsfall — bei diesem
  Test hatten alle Entitäten bereits Punkte, er übersprang also korrekt alle.
- **Die Routenqualität hängt an der Quelle, nicht am Code.** Die Companion-App
  meldet im Standardmodus nur bei deutlicher Bewegung oder Zonenwechsel — dann
  sind die Linien zwischen den Punkten gerade. „Hohe Genauigkeit" in der App
  (kostet Akku) oder ein eigener Tracker liefert dichtere Spuren.
- **Keine Entitäten**, siehe oben. Wer einen Zahlenwert im Dashboard will,
  braucht eine Karte oder ein Template.
- **Der Import reicht nur so weit wie der Recorder.** Seit `0.2.0` wird
  vorhandener Verlauf nachgeholt (siehe oben) — aber nur der, den
  `purge_keep_days` noch nicht gelöscht hat. Alles davor ist endgültig weg.
- **Ein Eintrag**, nicht mehr.
- Die Ausdünnung behält den **ersten** Punkt jedes Zeitfensters, nicht den
  aussagekräftigsten.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
