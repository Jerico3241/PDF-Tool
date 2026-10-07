# Architektur von PDF Tool (seit 2.7.0)

PDF Tool trennt **Fachlogik**, **Qt-Brücke** und **Oberfläche** strikt. Seit 2.7.0 ist die
Oberfläche eine Qt-Quick-Anwendung (PySide6 + QML); die Fachlogik ist dieselbe wie bis 2.6.1.
Ziel: Neue Funktionen sollen nie wieder Oberfläche und Geschäftslogik vermischen.

```
┌──────────────────────────────┐   Properties, Signale, Slots,     ┌─────────────────────────────┐
│ QML-Oberfläche               │ ◄──────────────────────────────── │ Qt-Brücke (app/qtapp)       │
│ app/qml/PdfTool/…            │ ────────────────────────────────► │ QObject-Controller, Modelle │
│ Seiten, Steuerelemente,      │   Aufrufe (Slots), Eingaben        │ Hintergrundarbeit           │
│ Design-Tokens, Animationen   │                                    └──────────────┬──────────────┘
└──────────────────────────────┘                                                   │ Python-Aufrufe
                                                                                   ▼
                                                                   ┌─────────────────────────────┐
                                                                   │ Python-Kern (Fachlogik)     │
                                                                   │ engine.py, appstate.py,     │
                                                                   │ richtext.py, tools/…        │
                                                                   └─────────────────────────────┘
```

## Python-Kern (Fachlogik)

`app/engine.py`, `app/appstate.py`, `app/richtext.py`, `app/excelstyle.py`, `app/pdffonts.py`
und `app/tools/` (ohne Oberflächencode):

- `tools/contract_overview/overview.py` – Excel-Prüfung, Bereitschaft, PDF-Felder (Einzel- und
  Stapelmodus), `preview.py` – Vorschau-PDF und Seitenbilder (PDFium),
  `customers/` – Kundenakte (Modelle, Abgleich, Speicher, Übernahme aus 2.3),
  `batch/` – Stapel (Analyse, Auflösung, Verarbeitung), `history/` – Vertragsstände und Vergleich,
  `templates/` – Vorlagen 2.0 (Modell mit ID und Schema-Version, Ablage je Datei, Übernahme aus
  2.7, Vorrang `priority.py`), `rules/` – Regelwerk 2.0 (`models.py` Felder, Vergleiche, Aktionen;
  `evaluate.py` Auswertung mit Spur und Vorschau; `repository.py` Ablage).
- `storage.py` – gemeinsame Ablage: atomar schreiben (temporäre Datei, `fsync`, `os.replace` mit
  kurzen Wiederholungen), sicher lesen, Schema-Versionen (`NewerSchema`), `JsonFolderStore` (je
  Datensatz eine Datei; beschädigte oder neuere Dateien werden übersprungen und gemeldet).
- `backup/` – Sicherung (`archive.py`), Wiederherstellung beim Start mit Journal und Rückabwicklung
  (`restore.py`), automatische Sicherung und Aufbewahrung (`policy.py`).
- `diagnostics/` – Systeminformationen, Datenprüfung, Bereinigung, Support-Paket, Protokoll
  `pdf-tool.log` (`applog.py`), Aufräumen eigener temporärer Dateien.
- `tools/pdf_repair/` – Analyse und Reparatur (`engine.py`), Arbeitsprozess (`process.py`, auch
  `deliver`: exklusives Speichern unter dem reservierten Namen), Dateiliste für eine oder mehrere
  PDFs (`batch.py`: Zustände `ItemState`, Namensregel `NameMode` AUTO/MANUAL, Windows-Namensprüfung,
  Konflikte und Nummerierung, Reservierung beim Start – keine eigene Engine, nur Reihenfolge und
  Namen), Texte und Angaben für die Anzeige (`presentation.py`), erweiterte Wiederherstellung
  (`recovery/`).
- `tools/pdf_editor/` (seit 3.0.0) – PDF Reader & Editor ohne Oberfläche: Dokument (pikepdf als
  Quelle der Wahrheit, PDFium für Darstellung und Text), Text bearbeiten (`textedit.py`: direkt, neu
  gesetzt, Überlagerung – mit Prüfung), Bilder, Seiten, Anmerkungen, Formulare, Metadaten, Export,
  Rückgängig (`commands.py`), sicheres Speichern (`save.py`), Sitzungssicherung (`recovery.py`).
  Details: [`docs/PDF-EDITOR.md`](../docs/PDF-EDITOR.md).
- `tools/registry.py` – welche Werkzeuge es gibt und welche Seiten zu ihnen gehören.

Regeln: kein `import PySide6` und keine Oberfläche im Kern; Texte, die die Oberfläche zeigt,
entstehen aus Zustandsklassen (z. B. `Condition`, `RepairStatus`), nie umgekehrt.

## Qt-Brücke (`app/qtapp`)

Je Bereich ein `QObject`-Controller – kein „Gott-Controller“. QML sieht sie als Singletons im
Modul `PdfTool.Backend`:

| QML-Name | Klasse | Aufgabe |
| --- | --- | --- |
| `App` | `app.AppController` | Navigation und Werkzeug-Tabs (`openTabs`, `closeTab`), Statuszeile, Hinweise, Tastenkürzel, Drag & Drop, Speichern, Beenden |
| `ThemeBackend` | `theme.ThemeController` | Hell/Dunkel, Akzentfarbe, Mica, Animationsprofil, Design-Tokens |
| `Settings` | `settings.SettingsController` | Seite „Einstellungen“ (inkl. Kundenakte an/aus) |
| `Dialogs` / `Notices` | `dialogs.DialogService` / `notices.NoticeCenter` | Dialoge in QML, InfoBars je Bereich |
| `Contracts` | `contracts.overview.ContractOverviewController` | Übersicht erstellen, Darstellung (geladene Vorlage, »Vorlage geändert«, Regelwerk), Rich Text |
| `Templates` | `contracts.templates.TemplatesController` | Ansicht „Vorlagen“ (Liste ↔ Detail) |
| `Rules` | `contracts.rules.RulesController` | Ansicht „Regeln“: Regelwerke, Regelkarten, Editor, Testmodus und Vorschau (im Hintergrund) |
| `Customers` | `contracts.customers.CustomerController` | Kundenakte (nur geladen, wenn eingeschaltet) |
| `Preview` | `contracts.preview.PreviewController` | Vorschau (Seitenbilder über `image://preview/…`) |
| `Batch` | `contracts.batch.BatchController` | Stapel |
| `Comparison` | `contracts.comparison.ComparisonController` | Vertragsvergleich |
| `Repair` | `repair.RepairController` | PDF reparieren |
| `Reader` | `reader.controller.ReaderController` | PDF Reader & Editor: Tabs, Öffnen, »Zuletzt geöffnet«, Seitenleisten; `Reader.current` ist der `DocumentController` des aktiven Tabs (Seitenbilder über `image://pdfpage/…`) |
| `Updates` | `updates.UpdatesController` | Updates (vor der Installation: Sicherung) |
| `Backup` | `backups.BackupController` | Einstellungen → Sicherung & Wiederherstellung |
| `Diagnose` | `diagnose.DiagnoseController` | Einstellungen → Diagnose |

- **Properties** entstehen mit `base.prop()` (Wert + Änderungssignal, nur echte Änderungen
  melden); Python-Code kann mit `observe()` darauf hören.
- **Werkzeuge** melden sich mit `ToolHooks` beim `AppController` an (Strg+Enter, Strg+O, Strg+F,
  F1, Drag & Drop, Speichern, Beenden, laufende Verarbeitung vor einem Update) –
  `qtapp/contracts/tool.py`, `qtapp/repair.py`.
- **Singletons je Engine:** `application.register_backend()` registriert jeden Namen einmal;
  jede QML-Engine erhält die Controller ihrer eigenen Laufzeit (Tests starten viele nacheinander).
  Die Controller gehören der Laufzeit (`Runtime`) und leben länger als die Engine.

## Modelle

Listen sind `models.KeyedListModel` (`QAbstractListModel`) mit eindeutigem Schlüssel.
`set_items()` gleicht die neue Liste mit der angezeigten ab und meldet nur Unterschiede
(`removeRows`, `insertRows`, `moveRows`, `dataChanged` für geänderte Rollen); `update_item()`
ändert eine Zeile. Ein Neuaufbau (`resets`) passiert nur bei sehr vielen Verschiebungen
(z. B. neue Sortierung einer langen Liste). QML-Listen (`ListView`, `reuseItems: true`) sind
virtualisiert – auch 500 Kunden oder 100 Stapel-Einträge bleiben flüssig.

## Kopf- und Fußzeile (Rich Text)

Es gibt genau ein Datenmodell: `richtext.RichText` (Formatierung je Zeichen, Ausrichtung je Absatz),
unverändert seit 2.2. QML erhält kein eigenes Format.

| Schritt | Ort | Was passiert |
| --- | --- | --- |
| Speicher → Modell | `appstate.header_rich_from` / `footer_rich_from` / `baustein_rich` | reiner Text (`kopfzeile`, `fusszeile`, Baustein `text`) plus Formatierung (`kopfzeile_format`, `fusszeile_format`, Baustein `format`). Fehlt die Formatierung oder passt sie nicht zum Text: Standardformat. Ohne bewusst gespeicherte Fußzeile: Standard-Fußzeile. |
| Modell → Editor | `qtapp/contracts/richtext.py`: `RichTextDocument.attach` → `load_document` | je Absatz ein Block mit Ausrichtung (`QTextBlockFormat`), je Abschnitt ein Zeichenformat (`QTextCharFormat`) im `QTextDocument` des QML-Textfelds |
| Editor → Modell | `RichTextDocument._contents_change` → `document_rich` | nach **jeder** Änderung (Tippen, Formatleiste, Rückgängig) sofort zurück ins Modell; `rich()` liefert immer den aktuellen Stand – der Inhalt existiert nie nur in QML |
| Modell → Speicher | `ContractOverviewController.config()` | verzögert (800 ms nach der letzten Änderung) und bei »Kopfzeile/Fußzeile speichern«, nie bei jedem Tastendruck |
| Modell → PDF | `overview.pdf_fields(header=…, footer=…)` → `engine.erstelle_pdf` | Platzhalter mit `RichText.with_placeholders` (der Wert behält das Format des Platzhalters), ReportLab-Markup mit `richtext.paragraph_markup` – dieselbe Erzeugung für Vorschau, »PDF erstellen« und Stapel |

HTML, Markdown oder die Property `text` des Textfelds werden nie gelesen oder geschrieben;
eingefügt wird nur reiner Text (`pastePlain`). Umschalt+Eingabe beginnt einen Absatz (`newParagraph`).

`load_document` schreibt immer in *einem* Bearbeitungsblock: Einzeln verwirft `setBlockCharFormat`
auf einem leeren Absatz dessen Zeilen-Layout, ohne es neu zu berechnen – das Textfeld setzte die
Einfügemarke dann ersatzweise 10 px hoch oben links. Die Einfügemarke selbst ist `PTextCaret`
(`cursorDelegate` von `PRichTextEditor`): Ihre Maße liefert `RichTextDocument` (`caretFont`,
`caretAscent`, `caretDescent`, `caretBaseline` – Font Metrics der Schrift, die am Cursor entstünde,
auch einer ohne Markierung gewählten, und Grundlinie der Zeile); der Strich liegt in ganzen
Gerätepixeln. Der Platzhalter im leeren Feld verwendet dieselbe Schrift (`caretFont`) und die
Ausrichtung des Absatzes – Platzhalter, Einfügemarke und getippter Text beginnen an derselben Stelle.

## Hintergrundarbeit

- `tasks.Worker.run(func, on_done, on_error)` – Excel-Prüfung, PDF-Erzeugung, Vorschau, Stapel,
  Hashing in Threads. Ergebnisse, Fehler und Zwischenmeldungen kommen über ein Qt-Signal
  (queued) in den GUI-Thread. **Hintergrund-Threads berühren nie QML-Objekte.**
- PDF reparieren läuft in eigenen Arbeitsprozessen (`tools/pdf_repair/process.py`). Ein Prozess
  erledigt mehrere Dateien nacheinander (bis zu 25; nach einem Fehler, einem Absturz oder „Abbrechen“
  folgt ein frischer); gestartet wird er in einem Hilfsthread, beim Öffnen der Seite einer im Voraus.
  Der Controller fragt die Meldungen aller laufenden Aufträge alle 30 ms im GUI-Thread ab – höchstens
  zwei gleichzeitig (Analysen), repariert wird nacheinander. „Abbrechen“ beendet die Prozesse und
  lässt die noch nicht begonnenen Dateien aus. Die Zeilen (`Repair.items`, `KeyedListModel`) melden
  Fortschritt nur für die betroffene Zeile und Rolle.
- PDF Reader & Editor: ein eigener Arbeitsthread (`qtapp/reader/engine.py`) für alle Zugriffe auf
  geöffnete Dokumente, Aufträge mit Priorität (Bearbeiten vor sichtbaren Seiten vor Miniaturen vor
  Suche), Seitenbilder abbrechbar und in einem begrenzten Zwischenspeicher. Die Texterkennung läuft
  als Hintergrundauftrag im App-Arbeitsthread (Tesseract als eigener Prozess, abbrechbar); Änderungen
  am Dokument warten, bis sie fertig ist. Einstellungen des Readers in `gui-config.json`:
  `reader_zoom_beim_oeffnen` (`last`, `width`, `page`, `100`), `reader_leiste_beim_oeffnen` (`last`,
  `thumbs`, `outline`, `none`) – fehlt der Schlüssel oder ist der Wert unbekannt: `last` – und
  `reader_ocr_sprachen` (zuletzt gewählte Sprachen der Texterkennung).
- `timers.Timers` – benannte, abbrechbare Zeitgeber (verzögertes Speichern, Entprellen der Suche).

## QML-Oberfläche (`app/qml`)

| Modul | Inhalt |
| --- | --- |
| `PdfTool.Style` | `Theme` (Farben aus `ThemeBackend`), `Metrics` (Abstände, Radien, Größen), `Typography`, `Motion` (Animationsdauern und -kurven, Profil) |
| `PdfTool.Controls` | Steuerelemente `P…` auf Basis von Qt Quick Templates (Button, TextField, ComboBox, Toggle, InfoBar, Card, Collapse, ListPage …) |
| `PdfTool.Shell` | Fenster: Tab-Leiste oben (`AppTabs`, `AppTab`), Seitenwechsel (`PageHost`), Statuszeile, Dialoge (`DialogHost`) |
| `PdfTool.Pages` | Seiten: Start, Einstellungen, Vertragsübersichten (Erstellen, Darstellung, Vorschau, Stapel, Vergleich, Kunden), PDF reparieren |
| `PdfTool.Dialogs` | Inhalte der Dialoge (Kurzanleitung, Über, Neuerungen, Kunden wählen …) |

**Tab-Leiste (Adobe-Prinzip, seit 3.1.0-beta.4):** `AppTabs` zeigt ≡ Menü, ⌂ Start, die geöffneten
Werkzeuge (`App.openTabs`: Vertragsübersichten, PDF reparieren, Einstellungen – in der Reihenfolge des
Öffnens) und die Dokumente des Readers (`Reader.tabs`). `App.navigate` legt den Tab eines Werkzeugs an,
`App.closeTab` schließt ihn – Eingaben bleiben, war er zu sehen, folgt der Tab rechts daneben (nach den
Werkzeugen das aktive Dokument), sonst der links daneben bzw. Start. Einen Tab für den Reader selbst gibt
es nicht: `App.openTool("reader")` zeigt das aktive Dokument oder fragt nach einer PDF; der Reader
navigiert erst mit dem geöffneten Dokument zu sich (`ReaderController.open_paths`) und nach dem letzten
geschlossenen zur Startseite (`_leave_if_empty`). Die Breiten bei Platzmangel rechnet `AppTabs` aus der
Leistenbreite (keine Bindung über die Inhaltsbreite der Dokument-Tabs – das gäbe eine Schleife). Beim
Beenden (`App.closing`) schließen die PDFs ohne Übergänge, und `finish_incubation` löscht zum Löschen
vorgemerkte QML-Objekte, bevor die Engine endet.

Seiten entstehen je einmal (Loader): die erste – die Startseite, bei »Öffnen mit« der Reader –
synchron beim Laden der Oberfläche (sie steht im ersten Bild), die übrigen danach im Hintergrund.
Sind alle geladen, meldet `PageHost` das über `App.pagesLoaded`; dann lädt der Reader die PDF-Engine
(pikepdf, PDFium) im Arbeitsthread vor – beim Start mit einer PDF schon vor dem ersten Bild. Der
Dokumentbereich des Readers (Tabs, Leisten, Ansicht, Seitenleisten) entsteht ebenfalls im
Hintergrund, wird vorher ein PDF geöffnet, sofort. Ein Seitenwechsel blendet die alte Seite aus und
die fertige neue ein – nichts wird neu aufgebaut. Im Setup kommt die Oberfläche aus der Qt-Ressource `qrc:/qml` (`qml_rc.py`, erzeugt
von `windows-app/qmlres.py`).

**Mausrad:** Qt 6.11 bewegt ein `Flickable` je Mausrad-Raste mit einer eigenen Animation, die bei
jeder Raste an der gerade erreichten Stelle neu beginnt – zügig gedreht kam die Ansicht nur gut halb
so weit. Deshalb liegt in jeder scrollenden Ansicht ein `PWheelScroll` (`Controls/PWheelScroll.qml`)
als unterstes Element im Inhalt: Es verschiebt je Raste um `Qt.styleHints.wheelScrollLines` × 24 px
(Windows-Einstellung „Eine Bildschirmseite“: um die Höhe der Ansicht ohne zwei Zeilen),
schnell folgende Rasten verlängern das Ziel der laufenden Bewegung (160 ms; „Reduziert“ und „Aus“:
sofort), Touchpads mit Pixelangaben folgen direkt. Was im Inhalt selbst scrollt, bekommt das Rad
zuerst, an seinem Ende geht es an die Ansicht weiter; mit Strg oder Umschalt bleibt es bei den
Handlern der Ansicht (Zoom, waagerecht). `tune_wheel` (`qtapp/application.py`) rechnet die Zeilen aus
den Windows-Einstellungen beim Start auf rund 32 px je Zeile um, wie Edge und Chrome.

**Qt 6.11 und das Laden im Hintergrund:** Mit der schrittweisen Speicherbereinigung der QML-Engine
können Objekte, die beim Laden der Seiten im Hintergrund entstehen, ihre QML-Funktionen verlieren;
ein `Connections` mit Funktionen stürzt dann beim Fertigstellen ab (Windows und Linux, im Stresstest
mit sehr kleinen Ladeschritten reproduziert). Deshalb setzt `create_engine` vor dem Anlegen der
Engine `QV4_GC_TIMELIMIT=0` (Bereinigung in einem Zug), und Steuerelemente, die in vielen
Schaltflächen und Seiten stecken (`PProgressRing`, `PInfoBar`), reagieren über eigene
Signal-Handler statt über `Connections`.

## Start

`app/start.py` → `qtapp.application.main()`:
Protokoll (`pdf-tool.log`) → vorbereitete Wiederherstellung ausführen (`prepare_data`, vor dem
Lesen jeder Datei) → Konfiguration → Qt-Anwendung → Design (`ThemeController`) → Controller
(`Runtime`) → QML-Engine → Fenster verdeckt (DWM-Cloaking) mit Lage und Titelleiste → Startseite →
aufdecken mit dem ersten fertigen Bild → weitere Seiten laden. Nach dem Start im Hintergrund:
Update-Prüfung, automatische Sicherung (nach 15 s), Aufräumen alter temporärer Dateien (nach 30 s).
Fordert eine Wiederherstellung den Neustart an, startet `main` die App neu – erst nachdem diese
Instanz alles gespeichert hat.

## Sicherung, Wiederherstellung und Diagnose (seit 2.8)

- **Bereiche** (`backup/archive.py`, `AREAS`): Einstellungen (`gui-config.json`, `stapel.json`),
  Kundenakten (`kundenakten.json`, `.bak`, `contract-history\`), Vorlagen (`vorlagen\`),
  Regelwerke (`regelwerke\`). Nie: Protokolle, `sicherung.json`, andere Sicherungen, Dokumente.
- **Erstellen:** ZIP in eine temporäre Datei im Zielordner, `fsync`, vollständige Nachprüfung, dann
  `os.replace` – keine halbe Sicherung. Manifest mit Format-/App-Version, Art, Bereichen,
  Schema-Versionen und SHA-256 je Datei.
- **Prüfen:** Format- und Schema-Versionen (neuere → `BackupError(newer=True)`), nur Pfade in
  Bereichen (kein `..`, kein Laufwerk), Mitglieder = Manifest, Größe und SHA-256 je Datei.
- **Wiederherstellen:** `stage_restore` entpackt die gewählten Bereiche nach
  `.wiederherstellung\` (jede Datei gegen ihre SHA-256 geprüft, sichtbar erst nach vollständigem
  Entpacken); `apply_pending` läuft beim nächsten Start vor dem Laden der Daten und tauscht je
  Bereich per Umbenennen aus (`.wiederherstellung-alt\`). Jeder Schritt steht vorher im Journal;
  bei Fehlern oder nach einem Abbruch werden die Schritte rückwärts zurückgenommen; gelingt das nicht
  vollständig, bleibt der alte Stand als `.wiederherstellung-nicht-zurueckgenommen-<Zeitpunkt>\`
  erhalten (nie automatisch gelöscht, die Datenprüfung nennt ihn). Nach dem Erfolg
  wird der alte Stand nur umbenannt (`.wiederherstellung-alt-<Kennung>\`) und von einem
  Hintergrund-Thread gelöscht – der Start wartet nicht auf tausende Dateien. Ergebnis:
  `wiederherstellung-ergebnis.json`.
- **Automatisch** (`backup/policy.py`): höchstens alle 24 h und nur bei geändertem Datenstand
  (Pfade, Größen, Änderungszeiten); Aufbewahrung 10/5/5 (automatisch/vor Update/vor
  Wiederherstellung), manuelle nie; Status in `sicherung.json` (nicht Teil der Sicherung).
- **Laufende Arbeit:** Sicherung, Wiederherstellung und Diagnose-Export melden sich über
  `AppController.register_work` – „Jetzt installieren“ wartet darauf, und vor jeder Installation
  entsteht eine Sicherung (`BackupController.backup_before_update`).
- **Diagnose:** `diagnostics/checks.py` liest nur; das Support-Paket bereinigt Texte
  (`sanitize.py`: Programm- und Datenordner als Platzhalter, sonstige Pfade als `<Pfad>.<Endung>`,
  Benutzerordner, Benutzer- und Computername, E-Mail-Adressen, bekannte Firmen und Kundennummern
  aus den eigenen Daten) und anonymisiert die Einstellungen (nur Schalter, Zahlen, Anzahlen).

## Updater (`app/updater`, seit 2.7.2)

Der Updater ist kein Werkzeug, sondern eine eigene Schicht: Logik in `app/updater/`, Anzeige im
Controller `app/qtapp/updates.py` (QML: `Updates`), Oberfläche in `Shell/UpdateBanner.qml`,
`Pages/SettingsPage.qml` (Abschnitt „Updates“) und `Dialogs/UpdateContent.qml`. QML ruft nie
GitHub auf, lädt nichts, berechnet keine Prüfsumme und vergleicht keine Versionen.

| Modul | Aufgabe |
| --- | --- |
| `semver.py` | Versionen nach SemVer 2.0.0 (Vorabversionen, nie Textvergleich) |
| `models.py` | `Channel` (STABLE/BETA), `UpdateState`, `ErrorKind`, `Release`, `Asset` |
| `github.py` | Release-Liste lesen; Kanal filtern; Assets nach fester Namenskonvention; höchste neuere Version |
| `policy.py` | erlaubte Adressen: nur HTTPS, nur `api.github.com`, `github.com`, `*.githubusercontent.com`; höchstens 5 Weiterleitungen |
| `transport.py` | Qt Network (Windows: Schannel, System-Proxy): Zeitlimits, Größenlimits, geprüfte Weiterleitungen, Abbruch, gedrosselter Fortschritt |
| `verifier.py` | Prüfsummendatei lesen, SHA-256 berechnen und vergleichen |
| `state.py` | Zustandsautomat; `READY` nur nach `VERIFYING` |
| `schedule.py` | 24-Stunden-Regel ab der letzten *erfolgreichen* Prüfung |
| `store.py` | `%LOCALAPPDATA%\PDF-Tool-Updates`: `.part`, verifiziertes Setup, `.sha256`, `releases.json`; Aufräumen nur eigener Dateien |
| `notes.py` | Release Notes (Markdown) als maskierte Blöcke – nur `<b>`, `<i>`, `<code>`, `<br>`, `https`-Links |
| `service.py` | Ablauf prüfen → herunterladen → verifizieren → bereit → Installation vorbereiten (asynchron, Hashing im Hintergrund-Thread) |
| `installer.py`, `launch.py` | Hilfsprozess: wartet auf das Ende der App, prüft das Setup erneut, startet es (ShellExecute) |

**Quelle:** `https://api.github.com/repositories/1382108244/releases` – die feste ID von
`Jerico3241/PDF-Tool`. Eine Umbenennung des Repositories ändert nichts, ein anderes Repository mit
demselben Namen wird nie gelesen. Downloads kommen von der Download-Adresse des jeweiligen Releases
(`github.com/<Repository>/releases/download/<Tag>/…`), die aus dessen Seite abgeleitet und geprüft
wird. Eine Prüfung ist genau eine API-Anfrage (das Anfragelimit von 60 pro Stunde reicht weit).

**Kein zusätzliches Manifest:** Version (Tag), Kanal (Vorabversion), Dateiname, Größe und
Download-Adresse liefert die Release-API, die Prüfsumme die `.sha256`-Datei; GitHub nennt
zusätzlich einen eigenen SHA-256-Wert der Datei, der – wenn vorhanden – gegengeprüft wird. Ein
`update.json` hätte dieselben Angaben ein zweites Mal enthalten (und hätte auseinanderlaufen können),
ohne die Prüfung sicherer zu machen.

**Ablauf:** Automatische Prüfungen laufen unsichtbar (kein `CHECKING`, Fehler still), manuelle
sichtbar. Das Ergebnis der letzten Prüfung liegt in `releases.json`; so bleibt ein Angebot nach einem
Neustart sichtbar, und ein Kanalwechsel wirkt sofort ohne neue Anfrage. Download: zuerst die
Prüfsumme, dann das Setup als `.part`; erst nach bestandener SHA-256-Prüfung wird daraus das Setup.
Ein bereits verifiziertes Setup wird nicht erneut geladen, aber vor der Verwendung erneut geprüft.

**Installation:** „Jetzt installieren“ prüft laufende Arbeiten (`ToolHooks.running_work`), prüft
Datei und Prüfsumme im Hintergrund, startet `pythonw -I launch.py --setup … --sha256 … --wait <PID>`
(vom App-Prozess gelöst) und schließt das Fenster wie über das Schließen-Kreuz. Lehnt ein Werkzeug
das Beenden ab, wird der Hilfsprozess beendet und das Update bleibt bereit. Das Inno-Setup ersetzt
die Programmdateien (gleiche AppId) und bietet am Ende „PDF Tool starten“ an. Die App ersetzt nie
eigene Dateien. Einstellungen: `update_kanal`, `update_automatisch`, `update_letzte_pruefung`,
`update_beta_bestaetigt` in `gui-config.json` (fehlt etwas: Stable, automatisch ein).

**Tests:** `test_updater.py` (ohne Netzwerk), `test_updater_flow.py` (lokaler Testserver
`tests/updateserver.py`), `test_qt_updates.py` (Oberfläche), `smoke_updater.py` (Windows, eingebettete
Laufzeit, Inno-Setup-Attrappe). Tests erreichen nie das echte GitHub – außer dem lesenden Teil von
`smoke_updater.py --live` in der CI.

## Ein neues Werkzeug hinzufügen

1. Fachlogik als Paket unter `app/tools/<werkzeug>/` – ohne Oberfläche, mit eigenen Tests.
2. Eintrag in `app/tools/registry.py` (Titel, Beschreibung, Symbol, Seiten, Tastenkürzel).
3. Controller unter `app/qtapp/` (`Observable` + `prop()`), `ToolHooks` beim `AppController`
   anmelden, in `qtapp/tools.py` als QML-Singleton eintragen.
4. Seite `app/qml/PdfTool/Pages/<Name>Page.qml` (in `qmldir` eintragen) und in `Main.qml`
   registrieren – Stilregeln: [`QML_STYLE.md`](QML_STYLE.md).
5. Tests: Kern (pytest ohne Qt) und Oberfläche (`tests/test_qt_*.py` mit `ui_app`).

## Tests

- Kern: `tests/test_core.py`, `test_excel_bold.py`, `test_richtext.py`, `test_customers.py`,
  `test_batch.py`, `test_history.py`, `test_pdf_repair.py`, `test_pdf_recovery.py`, `test_migration.py`,
  `test_templates.py`, `test_rules.py`, `test_rules_pipeline.py`, `test_backup.py`, `test_diagnostics.py`.
- Qt-Brücke und Oberfläche: `tests/test_qt_*.py` mit `tests/qtutil.py` (`Harness`: App wie beim
  Start, ohne Bildschirm mit `QT_QPA_PLATFORM=offscreen`). Jede Meldung der QML-Engine lässt einen
  Test scheitern.
- Einfügemarke: `tests/test_qt_caret.py` (Bild bei 100 %, Geometrie in Gerätepixeln bei 125 … 200 %
  über `tests/caret_geometry.py` – je Skalierung ein eigener Prozess).
- PDF reparieren: `tests/test_pdf_repair_batch.py` (Liste, Zustände, Namen, Konflikte ohne Qt),
  `tests/test_qt_repair.py` (eine PDF wie bis 2.7.0, mehrere PDFs, Namen; bis zu 100 PDFs).
- PDF Reader & Editor: `tests/test_editor_*.py` (Engine) und `tests/test_qt_reader.py`,
  `test_qt_reader_v31.py`, `test_qt_objects*.py`, `test_qt_pages_v31.py`, `test_qt_edit_v31.py`,
  `test_qt_forms_v31.py`, `test_qt_ocr.py` (Oberfläche mit Maus und Tastatur); Messung:
  `tests/bench_editor.py`.
- Datenmigration: `tests/test_config_migration.py` lädt Einstellungen älterer Versionen
  (`tests/fixtures/config_v22.json` … `config_v272.json`, dazu Kundenakten und ein Vertragsstand)
  in die aktuelle Version und prüft das gespeicherte Ergebnis – schnell, ohne alte Setups.
- Laufzeit und Setup: `tests/smoke_runtime.py` (`--part runtime` bzw. `--part ui`),
  `tests/smoke_installer.ps1` (in der CI).

## CI

- **Windows-Setup** (`.github/workflows/windows-setup.yml`, bei Pull Request, Push auf `main` und manuell):
  Tests (die Qt-Tests in sechs gleichzeitig laufenden Jobs auf eigenen Rechnern) → Setup bauen →
  Clean Install der neuen Version → Upgrade von der unmittelbar vorherigen veröffentlichten Version
  (für eine Beta auch eine Beta; `windows-app/releases.py` bestimmt sie nach SemVer aus den veröffentlichten Releases; das
  veröffentlichte Setup wird geladen, per SHA-256 geprüft und zwischengespeichert) → Runtime-Smoke-Test
  → QML-Smoke-Test → Updater-E2E-Test → auf `main` nach allen Jobs: Release Candidate
  `PDF-Tool-Release-Candidate-<Commit-SHA>` (Setup, Prüfsumme, Manifest; `windows-app/release_candidate.py`).
- **Release** (`.github/workflows/release.yml`, nur manuell auf `main`): veröffentlicht den Release
  Candidate des erfolgreichen main-Laufs für genau den Release-Commit – ohne neuen Build und ohne
  erneute Tests; unveränderlich (vorhandene Releases und Tags werden nie überschrieben); ein stabiles
  Release setzt eine veröffentlichte Beta derselben Version voraus, siehe
  [`docs/RELEASE.md`](../docs/RELEASE.md).
- **Deep Compatibility Test** (`.github/workflows/deep-compatibility.yml`, nur manuell): Upgrade von
  allen bzw. ausgewählten älteren stabilen Versionen (ab 2.2.0), je Version ein frischer Windows-Rechner.
- **Update-Test** (`.github/workflows/update-test.yml`, nur manuell nach dem Veröffentlichen einer
  Beta oder einer stabilen Version): Vorversion installieren, Kanal „Stable“ oder „Beta“; deren
  Updater findet die neue Version bei GitHub, lädt und prüft sie (Stable nie eine Beta); das
  freigegebene Setup läuft still; danach Version, ein App-Eintrag, Programmstart, Kanal,
  Einstellungen und Vorlagen (`tests/smoke_update.py`).
