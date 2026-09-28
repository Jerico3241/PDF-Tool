Übersichten-Ersteller für Windows
Entwickler und Inhaber: Jerico
=================================

Version 2.2.0

Erstellt Vertragsübersichten aus Excel-Listen und speichert sie als PDF.


Was Sie herunterladen
---------------------
Uebersichten-Ersteller-Setup-2.2.0.exe

Die Datei enthält die komplette App einschließlich Python und aller Pakete
(pandas, openpyxl, xlrd, ReportLab, Pillow). Eine eigene Python-Installation
oder zusätzliche Pakete sind nicht nötig.


Neu in Version 2.2
------------------
- Fettschrift aus der Excel-Liste wird zellgenau in die PDF übernommen –
  auch nach dem Sortieren nach Vertragsbeginn und dem Ausblenden inaktiver
  Verträge.
- Kopf- und Fußzeile lassen sich formatieren: Schriftart, Schriftgröße,
  fett, kursiv, unterstrichen, durchgestrichen, Schriftfarbe und Ausrichtung
  je Absatz. Platzhalter wie {kd} behalten ihre Formatierung.
- Übersichtlichere Excel-Prüfung: aktive und ausgeblendete Verträge,
  Rechnungsempfänger, fehlende Spalten und – nur wenn in der Datei vorhanden –
  Kundennummer und Firmenname.
- »Bereit zum Erstellen« zeigt schon vor dem Klick, was noch fehlt.
- Nach dem Erstellen: Öffnen, Ordner öffnen, Pfad kopieren, Neue Übersicht.
- Eingaben werden automatisch gespeichert; Dateiauswahl startet im zuletzt
  verwendeten Ordner; Excel-Dateien werden beim Hineinziehen hervorgehoben.


Voraussetzungen
---------------
- Windows 10 oder Windows 11 (64 Bit)
- keine Administratorrechte
- rund 250 MB freier Speicher


Installation
------------
1. Die Setup-Datei doppelklicken.
2. Falls Windows SmartScreen erscheint:
   „Weitere Informationen“ → „Trotzdem ausführen“.
3. Dem Assistenten folgen: Zielordner bestätigen, optional
   „Verknüpfung auf dem Desktop erstellen“ an- oder abwählen.
4. Am Ende „Übersichten-Ersteller starten“ angehakt lassen und
   „Fertigstellen“ wählen.

Programmdateien:  %LOCALAPPDATA%\Uebersichten-Ersteller
Ihre Daten:       %APPDATA%\Uebersichten-Ersteller
                  (Einstellungen, Kundenverlauf, Vorlagen, Textbausteine,
                  Kopf- und Fußzeile, Zyklus-Regeln, Design, Akzentfarbe)

Die App erscheint im Startmenü unter „Übersichten-Ersteller“ und unter
Einstellungen → Apps → Installierte Apps.


Aktualisieren
-------------
Einfach das neue Setup ausführen. Die vorhandene Installation wird ersetzt,
es entsteht keine zweite Installation. Ihre Daten bleiben erhalten.

Update von 2.0.5 oder älter: Das Setup erkennt die alte Installation,
übernimmt deren Ordner und die gespeicherten Einstellungen
(gui-config.json wandert in den Datenordner), entfernt die alten Programm-
dateien, Verknüpfungen und den alten Eintrag in „Installierte Apps“.

Läuft die App während des Updates, meldet das Setup dies und wartet, bis
sie geschlossen ist. Dasselbe Setup erneut ausführen repariert die
Installation.


Stille Installation (Skripte, Softwareverteilung)
-------------------------------------------------
   Uebersichten-Ersteller-Setup-2.2.0.exe /VERYSILENT /SUPPRESSMSGBOXES
   Uebersichten-Ersteller-Setup-2.2.0.exe /SILENT          (mit Fortschritt)

Weitere Parameter:
   /LOG="C:\Pfad\setup.log"      Protokoll an diesen Ort schreiben
   /DIR="C:\Pfad\Ordner"         anderer Zielordner
   /TASKS=""                     keine Desktop-Verknüpfung
   /MERGETASKS="!desktopicon"    dito, übrige Aufgaben unverändert

Stille Deinstallation:
   "%LOCALAPPDATA%\Uebersichten-Ersteller\unins000.exe" /VERYSILENT
   (Ihre Daten bleiben dabei erhalten.)


Verwendung
----------
1. Seite „Erstellen“: Firmenname und Kundennummer eintragen oder unter
   „Zuletzt verwendet“ einen Kunden wählen.
2. Excel-Liste wählen (Strg+O) oder die Datei in das Fenster ziehen.
   Die Prüfung zeigt aktive und ausgeblendete Verträge, den oder die
   Rechnungsempfänger, fehlende Spalten sowie Kundennummer und Firmenname,
   sofern sie in der Datei stehen. Bei mehreren Empfängern einen auswählen.
3. Optional Logo und Zielordner ändern.
4. Sobald „Bereit zum Erstellen“ erscheint: „PDF erstellen“ klicken oder
   Strg+Enter drücken. Fehlt etwas, nennt die Anzeige den Grund; ein Klick
   darauf führt zum passenden Feld.
5. Nach dem Erstellen: „Öffnen“, „Ordner öffnen“, „Pfad kopieren“ oder
   „Neue Übersicht“ (leert Firma, Kundennummer, Empfänger und Excel-Datei;
   Logo, Zielordner, Darstellung, Vorlage, Kopf-/Fußzeile und Regeln bleiben).

Fettschrift: In der Excel-Liste fett formatierte Zellen erscheinen in der PDF
fett – zellgenau für Vertrag-Nr., Beschreibung (auch „Art“), Beginn,
Abrechnungszyklus, Netto und Zahlungsart. Andere Excel-Formate (Farben,
Schriftgrößen, Rahmen) werden bewusst nicht übernommen.

Seite „Darstellung“: Vorlagen, Titel, Dateiname, Logo-Breite, Hoch- oder
Querformat, Kopfzeile, Fußzeile mit Textbausteinen und Zyklus-Regeln.
Kopf- und Fußzeile haben eine Formatierungsleiste: Schriftart (Helvetica,
Times, Courier sowie – falls installiert – Arial, Calibri, Segoe UI und
Times New Roman), Größe 6–18 pt, fett (Strg+B), kursiv (Strg+I),
unterstrichen (Strg+U), durchgestrichen, Schriftfarbe und Ausrichtung
(Strg+L/E/R). Ohne Markierung gilt die Formatierung für neu getippten Text.
Strg+Z/Strg+Y machen Text- und Formatänderungen rückgängig bzw. wieder.
Die Fußzeile ist mit einem Standardtext vorbelegt; „Standard wiederherstellen“
setzt Text und Formatierung zurück. Kopf- und Fußzeile, Vorlagen,
Textbausteine und die Kundenakte speichern die Formatierung mit.

Seite „Einstellungen“: App-Design (Wie Windows, Hell, Dunkel), Akzentfarbe
(Windows-Akzentfarbe oder eine eigene Farbe), Mica-Material, Animationen,
Verhalten nach dem Erstellen und Informationen zur App.

Tastatur: Strg+Enter PDF erstellen · Strg+O Excel öffnen · F1 Kurzanleitung ·
Strg+1/2/3 Seiten wechseln · Tab/Umschalt+Tab zwischen Feldern wechseln ·
Leertaste/Eingabe löst Schaltflächen aus · Escape schließt Dialoge und Listen.


Windows-11-Design
-----------------
Die Oberfläche folgt dem Fluent Design von Windows 11: Navigation links,
Karten mit runden Ecken, Segoe-UI-Variable-Schrift und Fluent-Symbole.
Unter Windows 11 erhalten Titelleiste und Navigation das Mica-Material,
unter Windows 10 eine passende einfarbige Fläche. Animationen richten sich
nach der Windows-Einstellung „Animationseffekte“ und lassen sich in der App
abschalten.


Wenn etwas nicht klappt
-----------------------
Falls die App nicht startet, erscheint ein Fehlerfenster. Die Datei
fehler.log liegt im Datenordner %APPDATA%\Uebersichten-Ersteller.
Das Setup schreibt ein Protokoll nach %TEMP% („Setup Log <Datum>.txt“)
oder an den mit /LOG angegebenen Ort.


Deinstallation
--------------
Einstellungen → Apps → Installierte Apps → „Übersichten-Ersteller“ →
Deinstallieren.

Entfernt werden Programmdateien, Verknüpfungen und der Eintrag in den
Windows-Einstellungen. Anschließend fragt die Deinstallation, ob auch Ihre
gespeicherten Einstellungen gelöscht werden sollen (Standard: Nein).
Erstellte PDF-Dateien bleiben in jedem Fall erhalten.


Für Entwickler: Setup bauen
---------------------------
Voraussetzungen (Windows 10/11, 64 Bit):
- Python 3.13 (64 Bit) von python.org mit pip und Pillow
  (py -3.13 -m pip install pillow)
- Inno Setup 6.6 oder neuer: https://jrsoftware.org/isdl.php
- Internetzugang (lädt die eingebettete Python-Laufzeit von python.org und
  die Pakete aus runtime-requirements.txt, jeweils mit Prüfsummen)

Bauen (im Repository-Ordner):
   py -3.13 windows-app\build.py

Ergebnis:
   windows-app\dist\Uebersichten-Ersteller-Setup-<Version>.exe
   windows-app\dist\Uebersichten-Ersteller-Setup-<Version>.exe.sha256

Die Version steht nur in windows-app\VERSION. App, Setup und Dateiname
übernehmen sie von dort. ISCC.exe wird automatisch gesucht (PATH,
Umgebungsvariable ISCC, Standard-Installationsordner von Inno Setup 6).

Signieren: Sobald ein Code-Signing-Zertifikat vorhanden ist, die
Umgebungsvariable SIGN_COMMAND setzen, z. B.
   signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a "{file}"
Ohne Zertifikat bleibt das Setup unsigniert (SmartScreen-Hinweis beim ersten
Start ist dann normal).

Tests: py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt
       py -3.13 -m pytest windows-app\tests

GitHub Actions baut das Setup bei jedem Push auf windows-latest
(.github/workflows/windows-setup.yml) und stellt es als Artefakt bereit;
bei einem veröffentlichten Release wird es zusätzlich angehängt.
