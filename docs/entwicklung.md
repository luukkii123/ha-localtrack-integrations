# Entwicklung

Hinweise für alle, die an Local Track mitarbeiten. Nutzer brauchen sie nicht.

## Tests

- `python3 tests/smoke_test.py` — Logikprüfung ohne Home Assistant (nur
  `aiosqlite==0.20.0`): Ausdünnung, SQLite-Schicht, Recorder-Import
  (Trockenlauf, Wiederholbarkeit, Überschreiben, Tagesaufteilung) und die
  Verweildauer-Rechnung. Die Home-Assistant-Module des Imports werden durch
  Attrappen ersetzt. Der Lauf belegt deshalb **nicht**, dass
  `history.get_significant_states` in der jeweiligen HA-Version die erwartete
  Signatur hat; das zeigt erst ein Test in einer echten Installation.
- `tests_ha/` — Config-/Options-Flow mit echten Home-Assistant-Flowmanagern
  und `pytest-homeassistant-custom-component`, ohne HA-Server. Aufruf und
  Docker-Befehl: [`tests_ha/README.md`](../tests_ha/README.md). Die CI prüft
  HA 2026.7.0 (Plugin 0.13.344) und 2026.9.2 (Plugin 0.13.365) mit 100 %
  Zeilen- und Zweigabdeckung des Config-Flows. Das bezieht sich nur auf
  `config_flow.py`, nicht auf die ganze Integration.
- Die Import-Aktion wird schon in `async_setup` registriert und bleibt nach dem
  Entladen erreichbar; ohne geladenen Eintrag oder bei einer nicht
  aufgezeichneten Entität meldet sie einen `ServiceValidationError`.

## Qualitätsstufe

`custom_components/localtrack/quality_scale.yaml` führt die Bronze-Regeln auf.
`dependency-transparency` ist offen (Herkunft des Pakets aus einem öffentlichen
CI-Build nicht belegt), deshalb beansprucht das Manifest keine Stufe.

## Datenbank

Datei `<config>/.storage/localtrack.db`, Tabelle `points`:

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

Es gibt keinen eindeutigen Schlüssel auf `(entity_id, ts)`. Der Import
verhindert Dubletten deshalb gröber: Ein Kalendertag mit vorhandenen Punkten
wird übersprungen, außer bei `overwrite`. Größenordnung: rund ein Punkt je
Minute und Person sind etwa 0,5 Mio. Zeilen im Jahr, vor dem Ausdünnen.

## Aufzeichnung und Pflege

- Geschrieben wird bei einer Zustandsänderung mit `latitude`/`longitude`, die
  die Entdopplung passiert (Mindestabstand **oder** Mindestzeitabstand).
  Änderungen ohne Koordinaten werden verworfen, bevor die Datenbank berührt
  wird.
- Einmal täglich: Löschen jenseits der Aufbewahrung, Ausdünnen jenseits der
  Ausdünn-Grenze (der **erste** Punkt je Intervall bleibt), danach werden freie
  Seiten ans Dateisystem zurückgegeben.
- Automatischer Erstimport kurz nach dem Start: jede aufgezeichnete Entität ohne
  gespeicherten Punkt wird aus dem Recorder nachgefüllt. Es gibt bewusst keinen
  Merker; der Zustand wird aus den Daten abgeleitet, ein geglückter Import
  verhindert den nächsten.
- Der Import fragt den Recorder tageweise (rollierende 24 Stunden ab jetzt,
  nicht Kalendertage), weil eine dichte Quelle Zehntausende Zeilen je Tag
  liefert. Er nutzt dieselbe Entdopplung wie die Live-Aufzeichnung. Bei einem
  Beispiel mit fünf Personen und `min_distance_m: 10` wurden zwischen 0,1 % und
  83 % der Rohzeilen ausgedünnt; der Anteil sagt mehr über die Meldedichte der
  Quelle als über die Einstellung.

## WebSocket: `localtrack/history`

`max_points` (2–50000, Standard 2000). Zeitangaben ohne Zeitzone gelten als
lokale Zeit des HA-Hosts. Liegt `end` vor `start`, werden beide getauscht.
Bei Überschreitung vereinfacht der Server mit Douglas-Peucker; erster und
letzter Punkt bleiben erhalten. Jeden N-ten Punkt zu nehmen würde genau die
Ecken verlieren, die die Route ausmachen.

## WebSocket: `localtrack/zone_time`

Die Rechnung läuft im Server, nicht im Browser. Ein Monat einer dicht meldenden
Person sind rund 92 000 Punkte (etwa 6,6 MB), und `localtrack/history` würde
sie mit Douglas-Peucker vereinfachen. Das erhält die Form der Route, wirft aber
die zeitliche Dichte weg.

- **Koordinaten statt Zonen-ID.** Die Integration weiß nichts über Zonen und ist
  unabhängig von deren Attributnamen.
- Tagesgrenzen sind lokale Mitternacht des HA-Hosts, nicht des Browsers.
- Nur Tage mit Anwesenheit stehen in `days`; Zeitraum höchstens 366 Tage.
- Regeln, jeweils nach dem Grundsatz „lieber zu wenig als erfunden": Der
  Grenzübertritt zählt halb. Eine Lücke größer als `max_gap_s` trennt den
  Aufenthalt. `min_visit_s` greift am ganzen Besuch, vor der Tagesaufteilung,
  sonst verlöre eine Nachtschicht ihren ersten Abend.
- Warum nicht die Zustandshistorie der `person`-Entität: Bei überlappenden
  Zonen zeigt Home Assistant die kleinste, und GPS-Zittern lässt den Zustand im
  Sekundentakt zwischen Zone und `not_home` wechseln. Die geometrische
  Rechnung flackert an der Grenze auch, für eine Tagessumme ist das folgenlos.
- Wahl von `max_gap_s`: Die Companion-App meldet nach Bewegung, nicht nach Uhr.
  An einem Tag unterwegs kamen 4232 Punkte im 30-Sekunden-Takt, an einem Tag zu
  Hause nur 141 mit Lücken über einer Stunde. Derselbe Tag ergab bei 900 s
  12,6 h netto, bei 1800 s 15,8 h und bei 3600 s 18,9 h (brutto 23,8 h). 900 s
  halbiert die Hauptzahl, 3600 s schriebe eine echte einstündige Abwesenheit
  voll gut; 1800 s ist der Kompromiss. Die Zahl der „Besuche" ist ein Hinweis:
  zerfällt ein Tag in zwanzig Aufenthalte, ist der Wert zu niedrig.

## Fehlende Integration

Fehlt der Eintrag, antwortet Home Assistant mit `unknown_command`, nicht mit
`not_found`: Die Kommandos werden erst in `async_setup_entry` registriert.
`not_found` kommt nur vom Kommando selbst, wenn der Eintrag existiert, aber
gerade entladen ist. Karten müssen beide Fälle abfangen.
