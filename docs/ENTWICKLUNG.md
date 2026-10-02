# Entwicklung

Build, Tests und CI der Windows-App. Releases (Stable und Beta): [RELEASE.md](RELEASE.md);
Aufbau des Codes: [`windows-app/ARCHITECTURE.md`](../windows-app/ARCHITECTURE.md).

## Setup bauen

Voraussetzungen unter Windows 10/11 (64 Bit):

- Python 3.13 (64 Bit) mit pip, Pillow und PySide6-Essentials in derselben Version wie das Setup
  (`py -3.13 -m pip install pillow PySide6-Essentials==6.11.2` – liefert `rcc` für die QML-Ressource)
- [Inno Setup 6.6 oder neuer](https://jrsoftware.org/isdl.php)
- Internetzugang (eingebettete Python-Laufzeit von python.org, Pakete aus
  `windows-app/runtime-requirements.txt`, jeweils mit SHA-256-Prüfsumme)

```powershell
py -3.13 windows-app\build.py
```

Ergebnis: `windows-app\dist\PDF-Tool-Setup-<Version>.exe` und die zugehörige `.sha256`-Datei.
Das Build-Skript bündelt die QML-Oberfläche als Qt-Ressource (`windows-app/qmlres.py`), übernimmt
von PySide6 nur die benötigten Module, Plugins und QML-Module (`windows-app/qtruntime.py`, anhand
der Importtabellen der DLLs), entfernt tkinter/Tcl/Tk aus der Laufzeit und prüft, dass alle Module,
die nativen Bibliotheken von qpdf und PDFium sowie Qt Quick enthalten sind – und keine Reste der
früheren Tk-Oberfläche.

Die GitHub-Action [`windows-setup.yml`](../.github/workflows/windows-setup.yml) prüft jeden Pull
Request und jeden Stand von `main` vollständig – auf `windows-latest` in dieser Reihenfolge:

1. **Tests:** Kernlogik, Updater (SemVer, Kanäle, Prüfsummen, Download und Hilfsprozess gegen einen
   lokalen Testserver – nie gegen das echte GitHub), Qt-Oberfläche (ohne Bildschirm; in drei
   gleichzeitig laufenden Jobs) und die **Datenmigration älterer Einstellungen** –
   `tests/test_config_migration.py` lädt Fixtures im Format von 2.2.0 bis 2.7.0 in die aktuelle
   Version. Dafür wird kein altes Setup installiert.
2. **Setup bauen** – `release_check.py` prüft danach Namen, Version, Prüfsumme und Release Notes.
3. **Clean-Install-Test** der neuen Version: stille Installation, Prüfung, Programmstart, stille
   Deinstallation.
4. **Upgrade-Test** nur von der unmittelbar vorherigen stabilen Version (z. B. **2.7.1 → 2.7.2**).
   `windows-app/releases.py` bestimmt sie nach SemVer aus den veröffentlichten Releases (Betas und
   Entwürfe zählen nie); das veröffentlichte Setup wird geladen, per SHA-256 geprüft und
   zwischengespeichert – nie neu gebaut.
5. **Runtime-Smoke-Test** der eingebetteten Laufzeit (Module, Vertragsübersicht, Kundenakte, Vorschau,
   Stapel, Vertragsvergleich, PDF-Reparatur im Arbeitsprozess, Rohrekonstruktion, Updater).
6. **QML-Smoke-Test** (Oberfläche aus der Ressource, Programmstart mit Fenster, Werkzeuge und Ansichten).
7. **Updater-E2E-Test** (`tests/smoke_updater.py`): Mock-Release auf einem lokalen Testserver →
   Download → SHA-256 → bereit → der Hilfsprozess startet eine Inno-Setup-Attrappe erst nach dem
   Ende der „App“; manipulierte Dateien werden abgelehnt. Zusätzlich nur lesend HTTPS zu GitHub
   (Schannel, Weiterleitung zum Download-Speicher, Release-Liste über die Repository-ID).
8. **Release Candidate** (nur auf `main`, nur wenn alle Jobs bestanden sind): genau das geprüfte
   Setup und seine Prüfsumme als Artifact `PDF-Tool-Release-Candidate-<Commit-SHA>` mit Manifest
   (`windows-app/release_candidate.py`), 90 Tage aufbewahrt.

Veröffentlicht wird nur mit dem Workflow [`release.yml`](../.github/workflows/release.yml)
(„Release“, manuell auf `main`): Er lädt den Release Candidate des erfolgreichen main-Laufs für genau
den Release-Commit und veröffentlicht ihn unverändert – ohne neuen Build und ohne erneute Tests.
Einzelheiten und alle Prüfungen: [RELEASE.md](RELEASE.md).

Die vollständige historische Installer-Prüfung (Update vom Übersichten-Ersteller 2.2.0 und von
PDF Tool 2.3.0, 2.4.0, 2.5.0, 2.6.0, 2.6.1, 2.7.0 mit Beispieldaten) läuft nur noch auf ausdrückliche
Anforderung im manuellen Workflow [`deep-compatibility.yml`](../.github/workflows/deep-compatibility.yml)
(„Deep Compatibility Test“, je Vorversion ein frischer Windows-Rechner).

Nach dem Veröffentlichen einer Beta oder einer stabilen Version prüft der manuelle Workflow
[`update-test.yml`](../.github/workflows/update-test.yml) („Update-Test“) das Update aus Sicht der
Anwender: veröffentlichte Vorversion installieren, Update-Kanal wählen; der Updater dieser Vorversion
findet die neue Version bei GitHub, lädt und prüft sie (Stable bietet nie eine Beta an); danach
Version, ein App-Eintrag, Programmstart, Kanal, Einstellungen und Vorlagen (`tests/smoke_update.py`).

## Tests

```powershell
py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0 PySide6-Essentials==6.11.2 fonttools==4.66.1
$env:QT_QPA_PLATFORM = "offscreen"   # Oberflächentests ohne Bildschirm (so läuft auch die CI)
py -3.13 -m pytest windows-app\tests
```

Die Tests erzeugen ihre Test-PDFs selbst (`windows-app/tests/pdfsamples.py`): gültige Dateien,
falsche Querverweise, fehlender Trailer, abgeschnittene Dateien, beschädigte Datenströme, nicht
reparierbare Dateien, verschlüsselte PDFs, Formulare, Anhänge, Signaturen und große PDFs – für die
erweiterte Wiederherstellung zusätzlich klassische PDF 1.4 ohne xref, Trailer, `%%EOF` oder
Seitenbaum, falsche `/Parent`-Verweise, geerbte Ressourcen, Binärdaten mit scheinbaren
Objektköpfen, inkrementelle Updates, Objektströme und eine Nachbildung einer realen, nach den Seiten
abgeschnittenen Datei. Echte Kundendateien liegen nie im Repository; eine lokale Beispieldatei lässt
sich mit `PDF_TOOL_REAL_SAMPLE=<Pfad>` zusätzlich prüfen.

Vorlagen, Regelwerk, Sicherung und Diagnose haben eigene Kerntests ohne Oberfläche:
`test_templates.py` (Modell, Übernahme aus 2.7, Vorrang, beschädigte und neuere Dateien, 100
Vorlagen), `test_rules.py` (alle Vergleiche und Aktionen, Reihenfolge, Konflikte, Vorschau,
Determinismus, 500 Verträge × 100 Regeln), `test_rules_pipeline.py` (PDF, Vertragsstand, Stapel –
die Excel bleibt unverändert), `test_backup.py` (Format, Prüfung, Beschädigung, neuere Versionen,
Wiederherstellung mit Rückabwicklung und Abbruch, Aufbewahrung, großer Datenbestand) und
`test_diagnostics.py` (Datenprüfung, Bereinigung, Support-Paket ohne Kunden- oder Dokumentdaten,
Protokoll-Rotation, Aufräumen nur eigener Dateien).

Der PDF Reader & Editor (seit 3.0.0) hat Kerntests mit künstlichen PDFs (`tests/editorsamples.py`):
`test_editor_core.py`, `test_editor_text.py`, `test_editor_pages.py`, `test_editor_images.py`,
`test_editor_annotations.py`, `test_editor_forms.py`, `test_editor_properties.py`; die Oberfläche prüft
`test_qt_reader.py` mit Maus und Tastatur. Messwerte für 1 bis 1000 Seiten liefert
`python windows-app/tests/bench_editor.py` (Ergebnisse in [PDF-EDITOR.md](PDF-EDITOR.md)).

Die Oberflächentests (`test_qt_*.py`) starten die App wie beim echten Start – Controller, QML und
Fenster (`tests/qtutil.py`) – und schlagen fehl, sobald die QML-Engine eine Warnung meldet
(Bindungsschleifen, fehlende Properties …). Sie prüfen alle Abläufe von 2.6.1 an den Controllern
(Excel-Prüfung, PDF, Rich Text mit Rückgängig/Wiederholen, Vorlagen, Regelwerk, Sicherung und
Wiederherstellung samt Neustart, Diagnose, Kundenakte, Vorschau, Stapel mit 100 Dateien,
Kundenliste mit Hunderten Einträgen, Vertragsvergleich, PDF reparieren) sowie
Qt-Spezifisches: Listenmodelle ändern nur betroffene Zeilen, alle Seiten entstehen genau einmal,
Animationsprofile, Hell/Dunkel, Fenstergrößen, das Laden der Oberfläche aus der eingebauten
Ressource und dass kein Code mehr tkinter verwendet.

**Manuelle Prüfung vor einem Release (Windows 10/11):**

1. Skalierung 100 %, 125 %, 150 %, 175 % und 200 % (Einstellungen → Anzeige): Start ohne weißes
   oder halbfertiges Fenster, keine abgeschnittenen Texte, Navigation breit/kompakt, Einstellungen
   vollständig lesbar. Zum Nachbilden eignet sich `QT_SCALE_FACTOR=1.5`.
2. Hell/Dunkel mehrfach wechseln (auch „Wie Windows“ und über die Windows-Einstellung): Wechsel in
   einem Schritt, Titelleiste und Mica passend.
3. „Animationseffekte“ in Windows aus: Seitenwechsel, Navigation und Bereiche ohne Bewegung.
4. Fenstergröße langsam und schnell ziehen, maximieren, wiederherstellen, Navigation ein- und
   ausklappen: keine springenden Karten, kein Flackern.
5. Schnell zwischen „Übersicht erstellen“, „Darstellung“, „Vorschau“, „Stapel“ und (mit Kundenakte)
   „Kunden“ wechseln: keine leeren oder halb aufgebauten Seiten.
6. Kundenakte aus → ein → aus → ein: Daten bleiben, keine doppelten Einträge; Stapel und PDF ohne
   Kundenakte.
7. Animationsprofil „Vollständig“ → „Reduziert“ → „Aus“: wirkt sofort, ohne Neustart.
8. Sicherung: „Jetzt sichern …“ auf einen USB-Stick, danach eine Vorlage ändern und
   „Wiederherstellen …“ nur für „Vorlagen“: PDF Tool startet neu, die Vorlage ist wieder im alten
   Stand, alle anderen Daten unverändert; auf der Startseite steht das Ergebnis.
9. Diagnose: „Daten prüfen“ und „Support-Paket erstellen …“; das ZIP öffnen und prüfen, dass weder
   Firmennamen noch Pfade zu Dokumenten darin stehen.

Das App-Symbol entsteht mit `python windows-app/scripts/make_icons.py` (Windows-Symbol, Favicons
und Logo der Downloadseite).

## Lizenzen

PDF Tool nutzt ausschließlich Bibliotheken mit freien Lizenzen, darunter PySide6/Qt (LGPL-3.0,
dynamisch geladen und ersetzbar), pikepdf (MPL-2.0) mit qpdf (Apache-2.0), pypdfium2
(Apache-2.0/BSD-3-Clause) mit PDFium (BSD-3-Clause) und pypdf (BSD-3-Clause); die Symbole der
Oberfläche stammen aus Fluent UI System Icons (MIT). Die vollständige
Übersicht steht in [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md); die Lizenztexte liegen im
Setup bei den jeweiligen Paketen (`runtime\Lib\site-packages\*.dist-info`).

## Sicherheit

Lokale Build-Artefakte, Download-Caches, Workspace-Metadaten, Screenshots, Caches und
vorkompilierte EXE-/ZIP-Dateien werden nicht versioniert. Das Setup ist ohne Zertifikat
unsigniert; eine Signatur lässt sich über die Umgebungsvariable `SIGN_COMMAND` (z. B. `signtool`)
im Build ergänzen. OAuth-Secrets gehören ausschließlich in Umgebungsvariablen und sind nicht im
Repository enthalten.
