# Design-Audit vom 08.10.2026 — ha-localtrack

Kanonische Quelle: `/mnt/user/Data/Claude Projekte/DESIGN_GUIDELINES.md`.
Umfang: Agent-Einstieg, fachliche Benennung und statische Quellenprüfung. Keine App-Codeänderung, kein Deploy und kein Upload.

## Plattform und Nachweise

Home-Assistant-Integration; sichtbare Config-/Options-/Reauth-Formulare rendert HA. Keine eigenständige PWA.

Lesereihenfolge: gemeinsame `AGENTS.md` und `CLAUDE.md`, zentrale Richtlinien, Audit-/Glossarvorlage und Todo-Regel; lokale `AGENTS.md`/`CLAUDE.md`; lokale AGENTS.md → HACS AGENTS/CLAUDE und docs/ui-regeln.md; gezielte README-/Flow-/Übersetzungsquellen.

Tatsächlich: `git status`, Dateibestand mit `rg --files`, gezielte `rg -n`-/Quelltextprüfung, Todoabruf/-Übernahme und Dokumentenprüfung. Kein Browser gestartet, keine echten Viewports (360/390 px, Tablet, Desktop) geprüft, keine echte Keyboard-/Escape-/Back-/Forward-Prüfung, keine PWA-Installation oder Offline-Geräteprobe, kein Screenreader, keine Kontrast-/Zoom-/Touchmessung, keine Web-Vitals-Feldmessung. Vorhandene Tests/ältere Abnahmen sind Quellenhinweise und wurden hier nicht erneut ausgeführt. `teilweise` meint belegte Teilstruktur; es bedeutet keine bestandene Laufzeitabnahme.

### Quellen

- **E01**: `custom_components/localtrack/config_flow.py`: ConfigFlow, OptionsFlow, Fehler-/Formzweige und Unique ID.
- **E02**: `custom_components/localtrack/strings.json`, `translations/de.json`, `translations/en.json`: Feldlabel/-erklärung und Fehler; `manifest.json`/`quality_scale.yaml`.
- **E03**: `custom_components/localtrack/` und README.md: Integrationsbestand; eigene Browseroberfläche nicht implementiert, Formrendering gehört zu Home Assistant.
- **E04**: `../scripts/ui-regeln-pruefen.py`: tatsächlich von HACS-Wurzel ausgeführt, dieses Unterrepo 0 statische Verstöße, Exit 0; deckt die globale Laufzeitmatrix nicht ab.

## Alle 26 Regeln

| Regel | Status | Beleg, Anwendbarkeit und nächste Prüfung |
| --- | --- | --- |
| R01 · Konsistenz | teilweise | E01/E02: ein Config-/OptionsFlow, deutsche und englische Übersetzung; Labels fachlich vergleichen. |
| R02 · Mehrfachauswahl | nicht anwendbar | Keine eigene Liste mit fachlicher Sammelaktion; HA-Entitäts-/Konfigurationsverwaltung gehört zum Host. Bei zukünftiger eigener Liste erneut prüfen. |
| R03 · Keyboard | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R04 · Modale Dialoge | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R05 · Navigation | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R06 · Responsive Mobile | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R07 · PWA | nicht anwendbar | Integration hat keine eigene Webapp/PWA; Installation/Manifest/Offline gehören zu Home Assistant. Integration muss eigene Datenverfügbarkeit ehrlich melden. |
| R08 · Wiederverwendung | teilweise | E01: zentrale Flows/Validierung und Hostformular; Reconfigure/Reauth/Optionspfade fachlich vergleichen. |
| R09 · Designsystem | teilweise | E02/E03: Hostschema statt eigenem Designsystem; keine neue Markenoberfläche. Host-Rendering nicht aktuell geprüft. |
| R10 · Formulare | teilweise | E01/E02/E04: Schema/Fehler und alle geprüften Feldbeschreibungen; Datenerhalt/Keyboard real prüfen. |
| R11 · Feedback | teilweise | E01: asynchrone Verbindungsprüfung und Fehlerzweige; echter langsamer Host-/Dienstfall ungeprüft. |
| R12 · Fehlerbehebung | teilweise | E01/E02: Fehlerkeys und lokalisierte Meldungen; reale Auth-/Timeout-/Datenfehler mit nächster Aktion prüfen. |
| R13 · Destruktive Aktionen | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R14 · Große Datenmengen | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R15 · Drag&Drop | nicht anwendbar | Kein eigener Drag&Drop-Pfad im Integrationsbestand E03. |
| R16 · Accessibility | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R17 · Interaktionszustände | teilweise | E01/E02: Formularfehler/Hostzustände statisch vorhanden; Disabled/Busy/Fokus nicht real geprüft. |
| R18 · Ansichtszustände | teilweise | E01/E03: API-/Coordinator-Datenverfügbarkeit und Hostfehler; reale offline/forbidden/partial-Fälle ungeprüft. |
| R19 · Berechtigungen | nicht anwendbar | Keine Browser-Kamera-/Mikrofon-/Push-/Standortberechtigung in E01–E03; konfigurierte Datenquellen/Tracker sind keine browserseitige Geolocation-Anfrage. |
| R20 · Performance | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R21 · UI-Präferenzen | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R22 · Auffindbarkeit | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R23 · Responsive Komponenten | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R24 · Ausnahmen | teilweise | R07/R15/R19 fachlich begrenzte Nichtanwendbarkeit oben; Risiko falscher HA-Hostdelegation, Ersatz: reale Config-/Options-/Reauth- und Verfügbarkeitsprüfung. Kein pauschales Backend-Bestehen. |
| R25 · Menüs/Settings | ungeprüft | E01/E02/E03: Home-Assistant-Formoberfläche und fachliche Wirkung dieser Integration real prüfen; Quellstruktur allein genügt nicht. |
| R26 · Sprache/Fachvokabular | teilweise | E02/E04: deutsche Texte und englische Variante vorhanden; Fachbegriffe in design-glossar.md. Komplette Laufzeitanzeige ungeprüft. |

## Ausnahmen und Folgearbeit

Kein Integrationstest, keine HA-Hostprüfung und kein Schaltversuch ausgeführt. R03/R04/R05/R06/R16 bleiben für Hostdialoge ungeprüft, auch wenn Code an HA delegiert. Die historische Bronze-/Liveabnahme wird hier nicht als aktuelle Designabnahme verwendet. Weiterarbeit über HACS-Audit #139.


## Runtime-Nachtrag #139 am 08.10.2026

Der initiale Quellaudit oben bleibt historischer Befund. Die folgende Matrix
ersetzt dessen ungeprüfte Runtimeeinordnung nur im tatsächlich belegten Umfang.
Vollständige Methoden/Artefakte/Grenzen: gemeinsamer
[Runtimebericht](../../docs/runtime-design-audit-2026-10-08.md).

I1: frische echte HA2026.9.2-Suite6/6 (Root); nativer Optionsflow6 Felder,12 Layouts,Tab/Shift Tab/Inert,Entwurf321nach Escapeerhalten;1eigener Flowerstellt/abgebrochen.

| Regel | Status | Tatsächlicher Beleg und Grenze |
| --- | --- | --- |
| R01 · Konsistenz | teilweise | Zentrale Config-/Options Flow-Schemata, de/en-Labels; Feldvertrag und Hostdarstellung mit den unten genannten Nachweisen. |
| R02 · Mehrfachauswahl | nicht anwendbar | Keine eigene Liste mit fachlicher Sammelaktion; Host-Entitätsauswahl nicht als eigenes Bulk-System bewerten. |
| R03 · Keyboard | teilweise | Native Form-/Tastaturprüfung soweit Hostpfad verfügbar; Einzelheiten und Grenzen unten, keine Screenreader-Abnahme. |
| R04 · Modale Dialoge | teilweise | Keine eigenen Produktdialoge. Native Optionsprüfung schützt lokalen Zahlenentwurf vor Escape; volle Clean-Scrim-/Back-/Reauth-Abnahme nicht behauptet. |
| R05 · Navigation | teilweise | URL blieb bei lokalem Escape unverändert; komplette HA-Deep-Link-/Forward-/Refresh-/mobile-Gestenprüfung fehlt. |
| R06 · Responsive Mobile | teilweise | Native ha-form bei 320/360/390/480/768/960, Hell/Dunkel, ohne Formular-/Dokumentüberlauf soweit unten verfügbar; keine physische Touchprobe. |
| R07 · PWA | nicht anwendbar | Integration ohne eigenständige Webapp/Manifest. HA/Companion-PWA-Installation und Offline-Synchronisierung nicht Bestandteil. |
| R08 · Wiederverwendung | teilweise | Gemeinsame Flow-/Validierungspfade im Repo und native HA-Formkomponenten; Backend-/HA-Tests, keine zusätzliche Formularimplementierung. |
| R09 · Designsystem | teilweise | Native HA-Schema/Tokens, Hell/Dunkel-Rendering; keine vollständige numerische Kontrastprüfung aller Hostflächen. |
| R10 · Formulare | teilweise | Label/Helper statisch und Schema-/Fehlerzweige im HA-Test; nativer lokaler Entwurf erhalten soweit prüfbar. Kein produktives Optionsspeichern. |
| R11 · Feedback | teilweise | Asynchrone Backend-/Fehlerzweige getestet; keine Verzögerung des realen Dienstes oder doppelte produktive Aktion provoziert. |
| R12 · Fehlerbehebung | teilweise | Lokalisierte Fehlerpfade durch Tests/Quellvertrag belegt; reale Auth-/Dienststörungen nicht injiziert. |
| R13 · Destruktive Aktionen | teilweise | Aufbewahrung und Recorderimport verändern gespeicherte Historie; vorhandene Daten-/Importtests sind funktionale Belege. Kein echter Datenbestand gelöscht oder Optionswert gespeichert. |
| R14 · Große Datenmengen | teilweise | Schema-/Backend-Datensätze aus Tests; keine repräsentative große reale HA-Registry-/Optionslisten-Messung. |
| R15 · Drag&Drop | nicht anwendbar | Kein eigener Drag&Drop-Pfad im Integrationsbestand. |
| R16 · Accessibility | teilweise | Native Semantik/Fokus und Reflow-Proxies soweit prüfbar; kein Screenreader, keine tatsächliche 200/400%-Browserzoom-/Gesamtkontrastabnahme. |
| R17 · Interaktionszustände | teilweise | Form-/Fehler-/Loadingzustände in HA-Tests, native Fokus-/lokale Dirtyzustände soweit verfügbar; nicht alle Hostzustände geprüft. |
| R18 · Ansichtszustände | teilweise | Backendfehler/Verfügbarkeit aus Tests; native kurze Offline-Injektion erhält Formular, bildet keinen realen Dienst-/SSH-/OAuth-Ausfall ab. |
| R19 · Berechtigungen | nicht anwendbar | Keine eigene Kamera-/Mikrofon-/Push-/Geolocation-Browserpermission angefordert. |
| R20 · Performance | ungeprüft | Keine p75-Web-Vitals-Feldstichprobe: keine Telemetrie erhoben, Backend kein eigener Browserrouter. Funktionale Tests sind keine Feldperformance. |
| R21 · UI-Präferenzen | teilweise | Konfiguration ist HA-persistent; produktive Speicherung/Rückkehr bewusst nicht verändert. Keine neue UI-Präferenz. |
| R22 · Auffindbarkeit | teilweise | Vorhandene sichtbare native Konfigurieren-/Feldpfade untersucht; keine Essentialfunktion neu hinter Shortcut/Geste versteckt. |
| R23 · Responsive Komponenten | teilweise | Derselbe native fachliche Formvertrag bei den tatsächlich geprüften Breiten; keine gesonderte Mobile-Geschäftslogik. |
| R24 · Ausnahmen | teilweise | Nichtanwendbarkeit/Grenzen hier explizit; Hostdelegation bedeutet kein automatisches Bestehen. |
| R25 · Menüs/Settings | teilweise | Themenbezogene native Optionsschemas, kein neues Optionsmenü; reale lange Options-/Registry-Suche nicht umfassend geprüft. |
| R26 · Sprache/Fachvokabular | teilweise | Deutsche de/en-Labels, Helper und Fehler mit Repo-Glossar abgeglichen; keine privaten Titel/Werte publiziert. |
