# PDF Tool

PDF Tool ist eine Windows-App mit Werkzeugen für PDF-Dateien: Sie öffnet, bearbeitet, organisiert
und kommentiert PDFs, erstellt professionelle Vertragsübersichten aus Excel-Listen und repariert
beschädigte PDF-Dateien. Alle Dateien werden lokal auf dem PC verarbeitet. Entwickler und Inhaber:
Jerico.

## Funktionen

- PDF Reader & Editor: lesen, suchen, Text direkt ändern, Bilder, Seiten organisieren, Kommentare,
  Formulare ausfüllen, drucken – mit Tabs, Rückgängig und sicherem Speichern
- Vertragsübersichten aus Excel erstellen – einzeln oder als Stapel
- Live-PDF-Vorschau
- Vertragsvergleich mit dem letzten Stand
- optionale Kundenakte mit Wiedererkennung bekannter Kunden
- Vorlagen für die Darstellung, mit Standardvorlage für neue Übersichten
- Regelwerk: Werte der Übersicht nach eigenen Regeln anpassen (WENN … DANN …) – die Excel bleibt unverändert
- PDF-Reparatur für eine oder mehrere Dateien, bis zur Rekonstruktion der Dokumentstruktur
- Sicherung und Wiederherstellung aller Daten, lokal
- Diagnose mit Support-Paket ohne Kunden- oder Dokumentdaten
- In-App-Updates mit Stable- und Beta-Kanal

Ausführlich: [docs/FUNKTIONEN.md](docs/FUNKTIONEN.md) · PDF Reader & Editor: [docs/PDF-EDITOR.md](docs/PDF-EDITOR.md).

## Oberfläche

PySide6 mit Qt Quick/QML im modernen Windows-11-Design (hell/dunkel, Akzentfarbe, Mica,
Animationen); die Fachlogik ist in Python geschrieben. Unterstützt werden Windows 10 (ab Version
1809) und Windows 11, 64 Bit.

## Datenschutz

Dateien werden lokal verarbeitet – keine Cloud, keine Uploads. Die einzige Internetverbindung ist
die abschaltbare Update-Prüfung bei GitHub. Einzelheiten: [docs/DATENSCHUTZ.md](docs/DATENSCHUTZ.md).

## Installation

`PDF-Tool-Setup-<Version>.exe` aus den [GitHub Releases](https://github.com/Jerico3241/PDF-Tool/releases)
herunterladen und ausführen. Python und alle Pakete sind enthalten; Administratorrechte sind nicht
nötig. Danach meldet PDF Tool neue Versionen selbst (Einstellungen → Updates).

Stable ist der Standard. Beta ist für Nutzer gedacht, die neue Versionen vor der allgemeinen
Veröffentlichung testen möchten – Beta-Releases können Fehler enthalten und sind nicht vollständig
freigegeben.

## Entwicklung

```powershell
py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0 PySide6-Essentials==6.11.2 fonttools==4.66.1
$env:QT_QPA_PLATFORM = "offscreen"
py -3.13 -m pytest windows-app\tests    # Tests
py -3.13 windows-app\build.py           # Setup bauen (Inno Setup 6.6 oder neuer)
```

Build, Tests und CI: [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md) · Releases (Beta und Stable):
[docs/RELEASE.md](docs/RELEASE.md) · Aufbau des Codes: [windows-app/ARCHITECTURE.md](windows-app/ARCHITECTURE.md).
Das Repository enthält außerdem die Downloadseite (React, TanStack Start, Vite).

## Lizenz

GPL-3.0-or-later – Lizenztext: [LICENSE](LICENSE). Verwendete Bibliotheken und ihre Lizenzen:
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
