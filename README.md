# Übersichten-Ersteller

Quellcode für den **Übersichten-Ersteller 2.2.0**. Entwickler und Inhaber: Jerico.

Das Repository enthält:

- die Windows-App (Python/Tkinter, Fluent-Oberfläche für Windows 10 und 11) unter `windows-app/app/`
- das Inno-Setup-Skript für den Windows-Installer unter `windows-app/installer/`
- das Build-Skript `windows-app/build.py`
- die Web-/Downloadseite auf Basis von React, TanStack Start und Vite

## Windows-App

Die Anwendung erstellt Vertragsübersichten aus Excel-Daten und exportiert diese als PDF.
Benutzerhinweise (Installation, Update, stille Installation, Deinstallation) stehen in
[`windows-app/README.txt`](windows-app/README.txt).

Neu in 2.2.0:

- **Excel-Fettschrift in der PDF:** fett formatierte Zellen erscheinen zellgenau fett
  (`excelstyle.py`: openpyxl bzw. xlrd mit `formatting_info`; jede Datenzeile behält ihre
  Excel-Zeile in `_source_excel_row`, auch nach Filtern und Sortieren)
- **Rich-Text-Kopf- und -Fußzeilen:** Schriftart, Größe, fett, kursiv, unterstrichen,
  durchgestrichen, Farbe und Ausrichtung je Absatz (`richtext.py` als JSON-Datenmodell,
  `ui/richtext.py` als Editor, `pdffonts.py` für PDF- und Windows-Schriften)
- **Verbesserte Excel-Prüfung** und Anzeige **„Bereit zum Erstellen“**
- **Neuer PDF-Abschluss:** Öffnen, Ordner öffnen, Pfad kopieren, Neue Übersicht
- automatisches Speichern aller Eingaben (verzögert, atomar)

Das Setup enthält Python und alle Pakete – eine eigene Python-Installation ist nicht nötig.

- Programmdateien: `%LOCALAPPDATA%\Uebersichten-Ersteller` (Installation ohne Administratorrechte)
- Benutzerdaten: `%APPDATA%\Uebersichten-Ersteller` – bleiben bei Updates erhalten
- Die Version steht zentral in `windows-app/VERSION`.

## Setup bauen

Voraussetzungen unter Windows 10/11 (64 Bit):

- Python 3.13 (64 Bit) mit pip und Pillow (`py -3.13 -m pip install pillow`)
- [Inno Setup 6.6 oder neuer](https://jrsoftware.org/isdl.php)
- Internetzugang (eingebettete Python-Laufzeit von python.org, Pakete aus
  `windows-app/runtime-requirements.txt`, jeweils mit SHA-256-Prüfsumme)

```powershell
py -3.13 windows-app\build.py
```

Ergebnis: `windows-app\dist\Uebersichten-Ersteller-Setup-<Version>.exe` und die zugehörige
`.sha256`-Datei. Go wird nicht mehr benötigt.

Die GitHub-Action [`windows-setup.yml`](.github/workflows/windows-setup.yml) baut das Setup auf
`windows-latest`, führt alle Tests aus, prüft die eingebettete Laufzeit und das installierte Setup
(stille Installation, Programmstart, stille Deinstallation) und stellt Setup und `.sha256` als
Build-Artefakt bereit. Manuell gestartet mit `release: true` veröffentlicht sie danach das Release
`v<Version>` („Version <Version>“) mit beiden Dateien – nur wenn alle Prüfungen bestanden sind.

Tests der Windows-App:

```powershell
py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt
py -3.13 -m pytest windows-app\tests
```

## Sicherheit

Lokale Build-Artefakte, Download-Caches, Workspace-Metadaten, Screenshots, Caches und
vorkompilierte EXE-/ZIP-Dateien werden nicht versioniert. Das Setup ist ohne Zertifikat
unsigniert; eine Signatur lässt sich über die Umgebungsvariable `SIGN_COMMAND` (z. B. `signtool`)
im Build ergänzen. OAuth-Secrets gehören ausschließlich in Umgebungsvariablen und sind nicht im
Repository enthalten.
