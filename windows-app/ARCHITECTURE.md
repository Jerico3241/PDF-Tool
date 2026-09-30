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
  `batch/` – Stapel (Analyse, Auflösung, Verarbeitung), `history/` – Vertragsstände und Vergleich.
- `tools/pdf_repair/` – Analyse und Reparatur (`engine.py`), Arbeitsprozess (`process.py`),
  Texte und Angaben für die Anzeige (`presentation.py`), erweiterte Wiederherstellung (`recovery/`).
- `tools/registry.py` – welche Werkzeuge es gibt und welche Seiten zu ihnen gehören.

Regeln: kein `import PySide6` und keine Oberfläche im Kern; Texte, die die Oberfläche zeigt,
entstehen aus Zustandsklassen (z. B. `Condition`, `RepairStatus`), nie umgekehrt.

## Qt-Brücke (`app/qtapp`)

Je Bereich ein `QObject`-Controller – kein „Gott-Controller“. QML sieht sie als Singletons im
Modul `PdfTool.Backend`:

| QML-Name | Klasse | Aufgabe |
| --- | --- | --- |
| `App` | `app.AppController` | Navigation, Statuszeile, Hinweise, Tastenkürzel, Drag & Drop, Speichern, Beenden |
| `ThemeBackend` | `theme.ThemeController` | Hell/Dunkel, Akzentfarbe, Mica, Animationsprofil, Design-Tokens |
| `Settings` | `settings.SettingsController` | Seite „Einstellungen“ (inkl. Kundenakte an/aus) |
| `Dialogs` / `Notices` | `dialogs.DialogService` / `notices.NoticeCenter` | Dialoge in QML, InfoBars je Bereich |
| `Contracts` | `contracts.overview.ContractOverviewController` | Übersicht erstellen, Darstellung, Vorlagen, Rich Text |
| `Customers` | `contracts.customers.CustomerController` | Kundenakte (nur geladen, wenn eingeschaltet) |
| `Preview` | `contracts.preview.PreviewController` | Vorschau (Seitenbilder über `image://preview/…`) |
| `Batch` | `contracts.batch.BatchController` | Stapel |
| `Comparison` | `contracts.comparison.ComparisonController` | Vertragsvergleich |
| `Repair` | `repair.RepairController` | PDF reparieren |

- **Properties** entstehen mit `base.prop()` (Wert + Änderungssignal, nur echte Änderungen
  melden); Python-Code kann mit `observe()` darauf hören.
- **Werkzeuge** melden sich mit `ToolHooks` beim `AppController` an (Strg+Enter, Strg+O, Strg+F,
  F1, Drag & Drop, Speichern, Beenden) – `qtapp/contracts/tool.py`, `qtapp/repair.py`.
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

## Hintergrundarbeit

- `tasks.Worker.run(func, on_done, on_error)` – Excel-Prüfung, PDF-Erzeugung, Vorschau, Stapel,
  Hashing in Threads. Ergebnisse, Fehler und Zwischenmeldungen kommen über ein Qt-Signal
  (queued) in den GUI-Thread. **Hintergrund-Threads berühren nie QML-Objekte.**
- PDF reparieren läuft in einem eigenen Prozess (`tools/pdf_repair/process.py`); der Controller
  fragt dessen Meldungen alle 80 ms im GUI-Thread ab. „Abbrechen“ beendet den Prozess.
- `timers.Timers` – benannte, abbrechbare Zeitgeber (verzögertes Speichern, Entprellen der Suche).

## QML-Oberfläche (`app/qml`)

| Modul | Inhalt |
| --- | --- |
| `PdfTool.Style` | `Theme` (Farben aus `ThemeBackend`), `Metrics` (Abstände, Radien, Größen), `Typography`, `Motion` (Animationsdauern und -kurven, Profil) |
| `PdfTool.Controls` | Steuerelemente `P…` auf Basis von Qt Quick Templates (Button, TextField, ComboBox, Toggle, InfoBar, Card, Collapse, ListPage …) |
| `PdfTool.Shell` | Fenster: Navigation, Seitenwechsel (`PageHost`), Statuszeile, Dialoge (`DialogHost`) |
| `PdfTool.Pages` | Seiten: Start, Einstellungen, Vertragsübersichten (Erstellen, Darstellung, Vorschau, Stapel, Vergleich, Kunden), PDF reparieren |
| `PdfTool.Dialogs` | Inhalte der Dialoge (Kurzanleitung, Über, Neuerungen, Kunden wählen …) |

Seiten entstehen je einmal (Loader); die Startseite im ersten Bild, die übrigen danach im
Hintergrund. Ein Seitenwechsel blendet die alte Seite aus und die fertige neue ein – nichts wird
neu aufgebaut. Im Setup kommt die Oberfläche aus der Qt-Ressource `qrc:/qml` (`qml_rc.py`, erzeugt
von `windows-app/qmlres.py`).

## Start

`app/start.py` → `qtapp.application.main()`:
Konfiguration → Qt-Anwendung → Design (`ThemeController`) → Controller (`Runtime`) → QML-Engine →
Fenster verdeckt (DWM-Cloaking) mit Lage und Titelleiste → Startseite → aufdecken mit dem ersten
fertigen Bild → weitere Seiten laden.

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
  `test_batch.py`, `test_history.py`, `test_pdf_repair.py`, `test_pdf_recovery.py`, `test_migration.py`.
- Qt-Brücke und Oberfläche: `tests/test_qt_*.py` mit `tests/qtutil.py` (`Harness`: App wie beim
  Start, ohne Bildschirm mit `QT_QPA_PLATFORM=offscreen`). Jede Meldung der QML-Engine lässt einen
  Test scheitern.
- Datenmigration: `tests/test_config_migration.py` lädt Einstellungen älterer Versionen
  (`tests/fixtures/config_v22.json` … `config_v261.json`, dazu Kundenakten und ein Vertragsstand)
  in die aktuelle Version und prüft das gespeicherte Ergebnis – schnell, ohne alte Setups.
- Laufzeit und Setup: `tests/smoke_runtime.py` (`--part runtime` bzw. `--part ui`),
  `tests/smoke_installer.ps1` (in der CI).

## CI

- **Windows-Setup** (`.github/workflows/windows-setup.yml`, bei Push/PR/Release): Tests → Setup bauen →
  Clean Install der neuen Version → Upgrade von der unmittelbar vorherigen stabilen Version
  (`windows-app/releases.py` bestimmt sie nach SemVer aus den veröffentlichten Releases; das
  veröffentlichte Setup wird geladen, per SHA-256 geprüft und zwischengespeichert) → Runtime-Smoke-Test
  → QML-Smoke-Test → Release (nur manuell; `ersetzen` aktualisiert ein vorhandenes Release derselben
  Version).
- **Deep Compatibility Test** (`.github/workflows/deep-compatibility.yml`, nur manuell): Upgrade von
  allen bzw. ausgewählten älteren stabilen Versionen (ab 2.2.0), je Version ein frischer Windows-Rechner.
