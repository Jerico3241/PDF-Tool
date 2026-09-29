# PDF Tool

Quellcode von **PDF Tool 2.4.0** – einer Windows-App mit Werkzeugen für PDF-Dateien.
Entwickler und Inhaber: Jerico. Bis Version 2.2 hieß die App „Übersichten-Ersteller“.

Das Repository enthält:

- die Windows-App (Python/Tkinter, Fluent-Oberfläche für Windows 10 und 11) unter `windows-app/app/`
- das Inno-Setup-Skript für den Windows-Installer unter `windows-app/installer/PDF-Tool.iss`
- das Build-Skript `windows-app/build.py`
- die Web-/Downloadseite auf Basis von React, TanStack Start und Vite

## Werkzeuge

Nach dem Start zeigt PDF Tool eine Startseite mit allen Werkzeugen. Die Navigation links führt zu
**Start**, den **Tools** und den **Einstellungen**. Eine Datei kann direkt in das Fenster gezogen
werden: eine PDF öffnet „PDF reparieren“, eine Excel-Liste „Vertragsübersichten“.

| Werkzeug | Zweck | Code |
| --- | --- | --- |
| **Vertragsübersichten** | Erstellt professionelle Vertragsübersichten aus Excel-Dateien – mit Excel-Fettschrift, Vorlagen, formatierten Kopf- und Fußzeilen, Textbausteinen, Zyklus-Regeln, Live-Vorschau und Kundenakte mit Wiedererkennung bekannter Kunden | `app/tools/contract_overview/` (Ablauf, Seiten, `customers/` für die Kundenakte), `app/engine.py`, `app/excelstyle.py`, `app/richtext.py`, `app/pdffonts.py` |
| **PDF reparieren** | Analysiert beschädigte PDF-Dateien und versucht, lesbare Inhalte in eine neue PDF zu übertragen | `app/tools/pdf_repair/` |

Die Werkzeuge sind voneinander getrennt: Jedes hat eigene Seiten, eigene Einstellungen und eigene
Logik; gemeinsam sind nur Fenster, Navigation, Design und Dialoge (`app/vertragdesk.py`, `app/ui/`).
Neue Werkzeuge bekommen ein eigenes Paket unter `app/tools/` und einen Eintrag in
`app/tools/registry.py`.

### Vertragsübersichten: Kundenakte und Kundenwiedererkennung

Das Werkzeug hat vier Ansichten: **Übersicht erstellen**, **Darstellung**, **Vorschau** und
**Kunden**. Die Kundenakte gehört ausschließlich zu „Vertragsübersichten“; „PDF reparieren“ bleibt
davon unberührt.

- **Kundenakte 2.0:** stabile ID (UUID), Firmenname, Kundennummer, mehrere
  Rechnungsempfänger-E-Mails (die erste ist primär), optionale Notiz, bevorzugtes Logo, bevorzugter
  Zielordner, bevorzugte Vorlage („Vorlage automatisch verwenden“), eigene Kopf- und Fußzeile mit
  Formatierung sowie die letzte Aktivität (letzte Excel, letzte PDF, zuletzt verwendet). Es werden
  nur Pfade gespeichert – PDF- und Excel-Dateien werden nie kopiert.
- **Wiedererkennung nach der Excel-Prüfung:** Die Rechnungsempfänger der Excel werden mit den
  gespeicherten Zuordnungen verglichen – normalisiert wird nur zurückhaltend (Leerzeichen am Rand,
  Groß-/Kleinschreibung; `+Tags`, Punkte und Domains bleiben unverändert). Ergebnis
  (`customers/matching.py`): kein Treffer, genau ein Kunde (auch mit mehreren seiner Adressen),
  mehrdeutige Zuordnung oder Adressen verschiedener Kunden. Bei genau einem Kunden erscheint der
  Hinweis „Bekannter Kunde gefunden“ mit **Übernehmen**, **Kundenakte** und **Ignorieren**; bei
  verschiedenen Kunden entscheidet der Benutzer. Ein unbekannter Kunde ist normal und kein Fehler;
  die Wiedererkennung blockiert nie die PDF-Erstellung.
- **Nichts wird geraten:** Firmenname und Kundennummer stammen nur aus der Kundenakte oder aus
  Spalten der Excel-Datei – nie aus einer E-Mail-Adresse oder Domain. Es gibt keine
  Internetsuche, keine Domain-Auflösung und keine externe Datenbank.
- **Automatisch übernehmen** (Einstellung in „Kunden“, Standard: aus): nur bei genau einem
  bekannten Kunden, ohne aktive Kundenakte und ohne abweichende eingetragene Kundendaten –
  rückgängig machbar.
- **Arbeitskopie statt stiller Änderung:** Übernehmen füllt das Formular (Firma, Kundennummer,
  Logo und Zielordner, falls vorhanden – sonst bleibt der aktuelle Wert mit Hinweis, Vorlage nach
  Regel, Kopf- und Fußzeile nur, solange sie in dieser Übersicht nicht geändert wurden). Änderungen
  im Formular ändern die Kundenakte nie; „Kundenakte aktualisieren“ zeigt die Abweichungen und
  speichert nur die gewählten. Automatisch fortgeschrieben werden nur „zuletzt verwendet“, letzte
  Excel und letzte PDF. Eine leere Fußzeile ersetzt nie die gültige; die Standard-Fußzeile bleibt.
- **Lernen nur bewusst:** Neue Kundenakten entstehen nur über „Als Kundenakte speichern“ (mit
  „Zuordnung merken“); neue Adressen eines bekannten Kunden werden angeboten („Diese E-Mail
  künftig diesem Kunden zuordnen?“). Gehört eine Adresse schon einem anderen Kunden, fragt die App:
  „Bestehende Zuordnung verwenden“, „Zuordnung verschieben“ oder „Abbrechen“ – eine Adresse ist nie
  still zwei Kunden zugeordnet.
- **Ansicht „Kunden“:** Liste mit Suche (Firma, Kundennummer, E-Mail), Sortierung (zuletzt
  verwendet, Firma A–Z, Kundennummer), Detailansicht zum Bearbeiten, E-Mail-Adressen hinzufügen
  und entfernen, Hinweis auf mögliche Doppelungen, Zusammenführen nur auf Wunsch und Löschen mit
  Rückfrage (entfernt nur Kundenakte und Zuordnungen, nie Dateien). Die Liste zeichnet auch
  hunderte Kundenakten flüssig (Canvas statt vieler Widgets); Tastatur: Pfeiltasten, Eingabe,
  Strg+F.
- **Speicher:** `%APPDATA%\PDF-Tool\kundenakten.json` mit `schema_version: 2`, atomar geschrieben
  (temporäre Datei, dann Ersetzen) mit `.bak` als vorigem Stand; eine unlesbare Datei wird
  beiseitegelegt statt überschrieben. Bewusst ohne Datenbank, Server oder Konto.
- **Übernahme aus 2.3:** Beim ersten Start mit 2.4 wird der bisherige Kundenverlauf
  (`kunden` in `gui-config.json`) einmalig zu Kundenakten – vorher sichert die App die
  Konfiguration byte-genau nach `sicherungen\gui-config-vor-kundenakte-<Zeit>.json`. Schlägt die
  Übernahme fehl, bleibt der alte Verlauf unverändert und die App versucht es beim nächsten Start
  erneut. Code: `app/tools/contract_overview/customers/migration.py`.

### Vertragsübersichten: Live-Vorschau

Die Ansicht **Vorschau** erzeugt die PDF genau wie „PDF erstellen“, nur in einen privaten
temporären Ordner, und zeigt sie seitenweise (PDFium) – mit Seitennavigation (Bild ↑/↓), Zoom
(+/−, „An Breite anpassen“) und Verschieben breiter Seiten. Jede Änderung (auch das Übernehmen
eines Kunden) markiert die Vorschau als veraltet; neu erzeugt wird entprellt im Hintergrund und nur,
solange die Ansicht sichtbar ist. Eine Signatur aller Eingaben verhindert, dass ein veraltetes
Ergebnis angezeigt wird (schneller Wechsel Kunde A → B). Code: `app/tools/contract_overview/preview.py`.

### PDF reparieren

- **Analyse vor der Reparatur:** Größe, Seiten, PDF-Version, Verschlüsselung, Querverweistabelle,
  Objekte, Trailer, Seitenbaum, Metadaten, Datenströme, Formulare, Anhänge und digitale Signaturen.
  Ergebnis: „Keine Fehler gefunden“, „Reparierbare Probleme erkannt“, „Schwer beschädigt“ oder
  „Keine Reparatur möglich“.
- **Mehrstufig:** (1) Prüfen und Neuaufbau mit qpdf (pikepdf), (2) Übertragen der lesbaren Seiten in
  ein neues Dokument, (3) zweite Engine PDFium (pypdfium2). Die geprüfte Ausgabe mit den meisten
  vollständigen Seiten wird verwendet. Seiten werden nicht standardmäßig in Bilder umgewandelt; der
  Rettungsmodus „Lesbare Seiten als neue PDF retten“ tut das nur nach Bestätigung.
- **Ehrliche Ergebnisse:** repariert, teilweise wiederhergestellt („12 von 15 Seiten …“) oder
  nicht reparierbar – ohne Garantieversprechen. Nicht übernommene Bestandteile (z. B. Lesezeichen,
  Anhänge, gültige Signaturen) werden genannt.
- **Original bleibt unverändert:** Es wird nur gelesen; vor und nach der Verarbeitung wird die
  SHA-256-Prüfsumme verglichen. Die Ausgabe heißt `<Name>_repariert.pdf` (bei Bedarf `_2`, `_3` …)
  und entsteht neben dem Original oder in einem gewählten Ordner. Bei einem Fehler bleibt keine
  Ausgabe zurück.
- **Verschlüsselte PDFs** lassen sich mit dem richtigen Passwort reparieren; die Kopie bleibt
  verschlüsselt. Das Passwort wird nie gespeichert oder protokolliert, Passwortschutz wird nicht
  umgangen.
- **Arbeitsprozess:** Analyse und Reparatur laufen in einem eigenen Prozess mit niedriger Priorität.
  Die Oberfläche bleibt bedienbar, „Abbrechen“ beendet den Prozess wirklich und entfernt alle
  Zwischendateien. Schutz vor Ressourcenbomben: Der Arbeitsspeicher des Arbeitsprozesses ist
  begrenzt (Windows-Job-Objekt), Bildgröße und Zahl der untersuchten Objekte je Seite haben
  Obergrenzen; stürzt eine Engine an einer manipulierten Datei ab, endet nur der Arbeitsprozess.

## Installation

Das Setup `PDF-Tool-Setup-<Version>.exe` enthält Python, qpdf (über pikepdf), PDFium (über
pypdfium2) und alle weiteren Pakete – es muss nichts zusätzlich installiert werden. Benutzerhinweise
(Installation, Update, stille Installation, Deinstallation, Bedienung) stehen in
[`windows-app/README.txt`](windows-app/README.txt).

- Programmdateien: `%LOCALAPPDATA%\PDF-Tool` (Installation ohne Administratorrechte)
- Benutzerdaten: `%APPDATA%\PDF-Tool` – bleiben bei Updates erhalten
- **Update vom Übersichten-Ersteller (bis 2.2):** Das Setup verwendet dieselbe AppId – unter
  „Installierte Apps“ entsteht kein zweiter Eintrag. Die Programmdateien ziehen von
  `%LOCALAPPDATA%\Uebersichten-Ersteller` nach `%LOCALAPPDATA%\PDF-Tool` um, alte Verknüpfungen
  werden durch „PDF Tool“ ersetzt. Beim ersten Start übernimmt die App die Daten aus
  `%APPDATA%\Uebersichten-Ersteller` einmalig: zuerst eine Sicherung
  (`migration-backup-<Version>.zip`), dann Kopie mit Prüfung jeder Datei (Größe und SHA-256).
  Der alte Datenordner bleibt unverändert erhalten; schlägt die Übernahme fehl, arbeitet die App mit
  ihm weiter.
- **Update von 2.3:** Das Setup ersetzt nur Programmdateien. Beim ersten Start übernimmt die App den
  Kundenverlauf als Kundenakten (siehe oben, mit Sicherung); Einstellungen, Vorlagen,
  Textbausteine, Regeln sowie Kopf- und Fußzeile bleiben unverändert.
- Die Version steht zentral in `windows-app/VERSION`.

## Datenschutz

Alle Dateien werden vollständig lokal auf dem PC verarbeitet; es wird nichts hochgeladen und keine
Verbindung zu einem Dienst aufgebaut. PDF Tool schreibt Einstellungen, die Kundenakten
(`kundenakten.json`) und das technische Protokoll `pdf-repair.log` in den Datenordner.

**Kundenakten und E-Mail-Zuordnungen** sind ausschließlich lokal gespeicherte Nutzerdaten: keine
Cloud, keine Telemetrie, keine Synchronisierung, keine E-Mail-Abfrage, keine Internetsuche und
keine Domain-Auflösung. Gespeichert werden nur Angaben, die der Benutzer bewusst speichert, sowie
Pfade der zuletzt verwendeten Excel- und PDF-Datei – keine Kopien der Dateien. Löschen entfernt
die Kundenakte und ihre Zuordnungen, nie PDF- oder Excel-Dateien. Das Protokoll enthält Dateinamen, Größen und technische
Befunde, aber keine PDF-Inhalte, keine vollständigen Pfade und keine Passwörter. Zwischendateien
entstehen nur im temporären Ordner von Windows und werden nach jedem Vorgang gelöscht.

## Entwicklung

### Setup bauen

Voraussetzungen unter Windows 10/11 (64 Bit):

- Python 3.13 (64 Bit) mit pip und Pillow (`py -3.13 -m pip install pillow`)
- [Inno Setup 6.6 oder neuer](https://jrsoftware.org/isdl.php)
- Internetzugang (eingebettete Python-Laufzeit von python.org, Pakete aus
  `windows-app/runtime-requirements.txt`, jeweils mit SHA-256-Prüfsumme)

```powershell
py -3.13 windows-app\build.py
```

Ergebnis: `windows-app\dist\PDF-Tool-Setup-<Version>.exe` und die zugehörige `.sha256`-Datei.
Das Build-Skript prüft, dass die Laufzeit alle Module und die nativen Bibliotheken von qpdf und
PDFium enthält.

Die GitHub-Action [`windows-setup.yml`](.github/workflows/windows-setup.yml) baut das Setup auf
`windows-latest`, führt alle Tests aus, prüft die eingebettete Laufzeit (Module, Vertragsübersicht,
PDF-Reparatur im Arbeitsprozess, Kundenakte, Vorschau, Programmstart) und das installierte Setup:
stille Installation, Programmstart, stille Deinstallation, das Update vom Übersichten-Ersteller
2.2.0 (ein Eintrag unter „Installierte Apps“, Ordner, Verknüpfungen, Datenübernahme) und das Update
von PDF Tool 2.3.0 mit Beispieldaten (Kundenverlauf wird mit Sicherung zu Kundenakten,
Formatierung, Standard-Fußzeile und Vorlagen bleiben). Manuell gestartet mit
`release: true` veröffentlicht sie danach das Release `v<Version>` („PDF Tool <Version>“) mit Setup
und Prüfsumme – nur wenn alle Prüfungen bestanden sind.

### Tests

```powershell
py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0
py -3.13 -m pytest windows-app\tests
```

Die Tests erzeugen ihre Test-PDFs selbst (`windows-app/tests/pdfsamples.py`): gültige Dateien,
falsche Querverweise, fehlender Trailer, abgeschnittene Dateien, beschädigte Datenströme, nicht
reparierbare Dateien, verschlüsselte PDFs, Formulare, Anhänge, Signaturen und große PDFs.

Das App-Symbol entsteht mit `python windows-app/scripts/make_icons.py` (Windows-Symbol, Favicons
und Logo der Downloadseite).

## Lizenzen

PDF Tool nutzt ausschließlich Bibliotheken mit freien Lizenzen, darunter pikepdf (MPL-2.0) mit
qpdf (Apache-2.0) und pypdfium2 (Apache-2.0/BSD-3-Clause) mit PDFium (BSD-3-Clause). Die vollständige
Übersicht steht in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md); die Lizenztexte liegen im
Setup bei den jeweiligen Paketen (`runtime\Lib\site-packages\*.dist-info`).

## Sicherheit

Lokale Build-Artefakte, Download-Caches, Workspace-Metadaten, Screenshots, Caches und
vorkompilierte EXE-/ZIP-Dateien werden nicht versioniert. Das Setup ist ohne Zertifikat
unsigniert; eine Signatur lässt sich über die Umgebungsvariable `SIGN_COMMAND` (z. B. `signtool`)
im Build ergänzen. OAuth-Secrets gehören ausschließlich in Umgebungsvariablen und sind nicht im
Repository enthalten.
