# Local Track

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

**Speichert die Standorte ausgewählter `person.*`- und `device_tracker.*`-Entitäten
dauerhaft in einer eigenen SQLite-Datei und gibt sie über drei
WebSocket-Kommandos ans Dashboard.**

## Wofür das gut ist

Der Recorder von Home Assistant speichert Standorte zwar, löscht sie aber nach
`purge_keep_days` — und diese Einstellung ist **global**. Entweder man hebt
*alles* jahrelang auf oder nichts.

Local Track schreibt genau die Entitäten, um die es geht, in eine eigene Datei,
die der Recorder nie anfasst. Punkte werden beim Schreiben entdoppelt und nach
einer Weile ausgedünnt, damit die Datei nicht unbegrenzt wächst.

Wer das Ganze **sehen** will, braucht zusätzlich die Karten
**`localtrack-timeline-card`** (Tages-Track auf der Landkarte) und
**`localtrack-zone-time-card`** (Verweildauer an einem Ort, Monat als
Tagesliste) aus dem Repo
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

Jedes Feld des Dialogs trägt seinen eigenen Hilfetext (deutsch und englisch,
je nach Spracheinstellung von Home Assistant); die Tabellen unten wiederholen
ihn in Kurzform.

*English:* add this repository to HACS as a **custom repository** of category
**Integration**, download *Local Track*, restart Home Assistant, then go to
Settings → Devices & Services → **Add integration** → *Local Track*. Every
field in the dialog carries its own helper text, so nothing has to be guessed.

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
| Mindestzeitabstand | 30 s | 1–86400 | … **oder** wie viel Zeit seither vergangen sein muss |
| Ausdünnen ab Alter | 30 d | 1–3650 | ab welchem Alter alte Punkte ausgedünnt werden |
| Ausdünn-Intervall | 300 s | 10–86400 | wie dicht sie danach höchstens noch liegen |

Die beiden Dedupe-Werte sind mit **oder** verknüpft: gespeichert wird, sobald
*eine* der beiden Bedingungen erfüllt ist. Der Abstand filtert GPS-Zittern im
Stand, das Zeitintervall sorgt dafür, dass auch ein langer Aufenthalt Punkte hat.

Eine Änderung der Optionen lädt die Integration neu.

**Es ist nur ein Eintrag möglich.** Es gibt eine Datenbank und einen Satz
WebSocket-Kommandos; ein zweiter Eintrag würde mit dem ersten um beides
streiten.

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

### `localtrack/zone_time` — wie lange im Umkreis, Tag für Tag

Beantwortet „wie lange war ich diesen Monat bei der Arbeit". Die Rechnung
läuft hier und nicht im Browser: ein Monat sind bei einer dicht meldenden
Person rund **92 000 Punkte ≈ 6,6 MB**, und `localtrack/history` würde darüber
mit Douglas-Peucker vereinfachen — das erhält die *Form* der Route und wirft
gerade die zeitliche Dichte weg, also genau das, worum es hier geht.

```js
await hass.callWS({
  type: "localtrack/zone_time",
  entity_id: "person.beispiel",
  latitude: 48.2015943, longitude: 16.3566148, radius: 138,
  start: "2026-09-01T00:00:00", end: "2026-09-30T23:59:59",
  min_visit_s: 300,   // optional, Standard 300, 0–6 h
  max_gap_s: 1800,    // optional, Standard 1800, 60 s–24 h
});
// → { entity_id, from, to,
//     days: [{ date, net_s, gross_s, visits, first_ts, last_ts }],
//     total_net_s, total_gross_s, total_visits, days_present }
```

**Koordinaten statt Zonen-ID.** Die Integration weiß damit nichts über Zonen,
bleibt unabhängig von deren Attributnamen, und derselbe Befehl beantwortet
auch „wie lange war ich im Umkreis von 200 m um diesen Punkt".

**Tagesgrenzen sind lokale Mitternacht des HA-Hosts**, nicht des Browsers: ein
Haushalt soll dieselbe Zahl sehen, egal von welchem Gerät. Das weicht bewusst
von `localtrack/history` ab, wo der Aufrufer die Grenzen selbst setzt.

**Nur Tage mit Anwesenheit stehen in `days`.** Das halbiert die Antwort; die
Karte füllt den Monat auf. Der Zeitraum ist auf **366 Tage** begrenzt.

#### netto und brutto — und warum beide

| Feld | Bedeutung |
| --- | --- |
| `net_s` | Summe der Sekunden tatsächlich im Umkreis |
| `gross_s` | letzte Abfahrt minus erste Ankunft **desselben Tages** |

Es gilt immer `gross_s >= net_s`; die Differenz ist die Zeit außerhalb —
Mittagspause, Botengang, oder ein Datenloch.

Drei Regeln, alle dieselbe Haltung — **lieber zu wenig als erfunden**:

- **Der Übertritt zählt halb.** Liegt ein Punkt drin und der nächste draußen,
  lag die Grenze dazwischen; gutgeschrieben wird die halbe Lücke. Bei
  30-Sekunden-Takt sind das ±15 s je Übertritt.
- **Eine Lücke größer als `max_gap_s` trennt den Aufenthalt**, auch wenn beide
  Punkte drin liegen. Ist das Handy zwei Stunden aus, werden 30 Minuten
  gutgeschrieben statt zwei Stunden erfunden — `gross_s` zeigt die Spanne
  trotzdem, und die Differenz macht das Loch sichtbar.

#### Wie `max_gap_s` zu wählen ist

**Die Meldedichte hängt an der Bewegung, nicht am Ort.** An einem Tag
unterwegs kamen 4232 Punkte im 30-Sekunden-Takt, an einem Tag zu Hause nur
**141 mit Lücken über einer Stunde** — dieselbe Person, dasselbe Handy, zwei
Tage auseinander. Wer stillsitzt, meldet selten.

Derselbe Tag zu Hause, verschiedene Werte:

| `max_gap_s` | netto | „Besuche" | Anteil an brutto |
| --- | --- | --- | --- |
| 900 (15 min) | 12,6 h | 28 | 53 % |
| **1800 (30 min, Standard)** | **15,8 h** | **11** | **67 %** |
| 3600 (60 min) | 18,9 h | 6 | 79 % |
| — | brutto 23,8 h | | 100 % |

Der Standard liegt bei 1800 s, weil 900 s die Hauptzahl halbiert und 3600 s
eine echte einstündige Abwesenheit voll gutschreiben würde. **Wer viel
stillsitzt, darf höher gehen** — die Bruttospalte zeigt die Obergrenze
ohnehin, und die Zahl der „Besuche" ist ein guter Hinweis: zerfällt ein Tag
in zwanzig Aufenthalte, ist der Wert zu niedrig.
- **`min_visit_s` greift am ganzen Besuch**, vor der Tagesaufteilung. Sonst
  verlöre eine Nachtschicht ihren ersten Abend, weil der Anteil dort unter der
  Schwelle liegt.

#### Warum nicht die Zustandshistorie der `person`-Entität

Naheliegend wäre, zu zählen, wie lange `person.x` den Zustand `Arbeit` hatte.
**Das flackert.** An einer laufenden Installation gemessen:

```
09:38:02  SCN      →  09:38:05  not_home   (3 s)
11:00:40  Spar     →  11:00:46  not_home   (6 s)
11:20:17  Schule   →  11:20:22  not_home   (5 s)
```

Überlappende Zonen, Home Assistant zeigt die kleinste, GPS-Zittern schiebt den
Punkt im Sekundentakt über die Grenzen. Die geometrische Rechnung auf den
gespeicherten Punkten flackert an der Grenze zwar auch — für eine **Tagessumme**
ist das folgenlos, und `min_visit_s` wirft die Vorbeifahrten ohnehin weg. Das
zählt besonders bei kleinen Zonen: 19 m Radius ist weniger als die übliche
GPS-Streuung.

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

## Entfernen

1. Einstellungen → Geräte & Dienste → **Local Track** → ⋮ → **Löschen**.
   Damit endet der Mitschnitt sofort; der Zustands-Listener, der Timer für die
   Pflege und die WebSocket-Kommandos verschwinden mit dem Eintrag.
2. In HACS **Local Track** → ⋮ → **Entfernen**, danach Home Assistant neu
   starten. Das löscht `custom_components/localtrack`.

**Was zurückbleibt:** die Datenbank `localtrack.db` im Konfigurationsordner.
Sie wird bewusst **nicht** gelöscht — dort liegen Jahre an Standorten, und ein
versehentliches Entfernen der Integration darf sie nicht mitnehmen. Wer sie
wirklich loswerden will, löscht die Datei von Hand (bei gestopptem Home
Assistant; je nach SQLite-Zustand liegen daneben `localtrack.db-wal` und
`localtrack.db-shm`). Entitäten oder Geräte bleiben keine zurück — die
Integration legt keine an.

*English:* delete the entry under Settings → Devices & Services, then remove
*Local Track* in HACS and restart. The database `localtrack.db` in the
configuration folder is deliberately kept; delete it by hand (with Home
Assistant stopped) if you really want the history gone. No entities or devices
are left behind, because none are ever created.

## Lizenz

MIT — siehe [LICENSE](LICENSE).


## Lokale Qualitätsprüfung – 05.10.2026

HA-Bibliothekstests ohne eigenen HA-Server: Home Assistant 2026.7.0 mit
pytest-homeassistant-custom-component 0.13.344 sowie HA 2026.9.2 mit
0.13.365. `tests_ha/test_config_flow.py` prüft den vollständigen Config-Flow,
Optionen und vorhandene Reauth-/Reconfigure-Schritte, Fehler-Recovery und
Dubletten. Gemessene Zeilen- **und** Zweigabdeckung: **100 %**; der
CI-Befehl erzwingt dies mit `--cov-branch --cov-fail-under=100`.
Die HA-Suite umfasst 6 bestandene Tests je Matrixversion.

Local Tracks Importaktion wird bereits in `async_setup` registriert und
bleibt nach dem Entladen erreichbar. Ohne geladenen Eintrag oder bei einer
nicht erfassten Entität erscheint ein `ServiceValidationError`.
Die bestehende Logikprüfung besteht zusätzlich mit 62 Prüfungen.

Die aktuelle Bronze-Checkliste ist in `quality_scale.yaml` vollständig
aufgeführt. `dependency-transparency` bleibt ungeklärt: Lizenz, PyPI und
Release-Tag sind belegt, die Herkunft des konkret geprüften Pakets aus
öffentlichem CI-Build/Publish jedoch nicht. Es wird deshalb keine vollständige
Bronze-Stufe im Manifest beansprucht.

Dies sind lokale Quellcode- und Bibliotheksnachweise; sie ersetzen keine
Live-Abnahme und behaupten weder Veröffentlichung noch HACS-Installation.
Aufruf und Testumgebung: [`tests_ha`](tests_ha/).

## Geprüft: Release 0.4.1 (05.10.2026)

Die Importaktion ist bereits nach Domainsetup verfügbar und bleibt nach Unload
registriert. Die HA-Bibliotheksmatrix 2026.7.0/2026.9.2 besteht mit jeweils sechs
Tests; Config-/Optionsflow erreichen 100 % Zeilen- und Zweigabdeckung. Ein
unabhängiger Test prüft normales Domainsetup, erfolgreiche Serviceantwort,
Unload und erneutes Setup. Die bestehenden 62 Logikprüfungen und statischen
UI-Regeln sind erfolgreich.

Die tatsächlich installierten nativen Localtrack-Karteneditoren wurden auf
HA 2026.9.4 mit Speichern, Visual/YAML, Wiederöffnen und echter Browser-IME-
Komposition geprüft; alle 17 Editoren der gemeinsamen Kartenfamilien bestanden.
Das eigene Testdashboard wurde nach jedem Lauf wiederhergestellt. Diese
Frontendprobe betrifft den bestehenden Kartenvertrag; Release 0.4.1 verändert
keine Formularfelder, Übersetzungen oder Kartenoberfläche. Die Runtimekorrektur
ist zusätzlich mit echten HA-ServiceRegistry-Tests belegt.

Vollständige Bronze wird wegen des ungeklärten Dependency-Herkunftsnachweises
weiterhin nicht im Manifest beansprucht. Produktive Importaktionen mit
Recorderdaten sind kein Teil dieser Abnahme.
