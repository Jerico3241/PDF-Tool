PDF Tool für Windows
Entwickler und Inhaber: Jerico
=============================

Version 2.4.0

Werkzeuge für PDF-Dateien:
- Vertragsübersichten: erstellt professionelle Vertragsübersichten aus
  Excel-Listen und speichert sie als PDF – mit Live-Vorschau und
  Kundenakten, die bekannte Kunden an der Rechnungsempfänger-E-Mail
  wiedererkennen.
- PDF reparieren: analysiert beschädigte PDF-Dateien und versucht, lesbare
  Inhalte in eine neue PDF zu übertragen.

Bis Version 2.2 hieß die App „Übersichten-Ersteller“.


Was Sie herunterladen
---------------------
PDF-Tool-Setup-2.4.0.exe

Die Datei enthält die komplette App einschließlich Python und aller Pakete
(pandas, openpyxl, xlrd, ReportLab, Pillow, pikepdf mit qpdf, pypdfium2 mit
PDFium). Eine eigene Python-Installation, qpdf, Ghostscript oder andere
Zusatzprogramme sind nicht nötig.


Neu in Version 2.4
------------------
- Kundenakte 2.0 in „Vertragsübersichten“: Firmenname, Kundennummer,
  mehrere Rechnungsempfänger-E-Mails, Notiz, bevorzugtes Logo, Zielordner
  und Vorlage sowie eigene Kopf- und Fußzeile (mit Formatierung).
- Wiedererkennung: Nach der Excel-Prüfung erkennt PDF Tool bekannte Kunden
  an der Rechnungsempfänger-E-Mail und bietet „Übernehmen“, „Kundenakte“
  oder „Ignorieren“ an. Nichts wird geraten – kein Firmenname aus einer
  E-Mail-Adresse, keine Internetabfrage.
- Neue Ansicht „Kunden“: suchen, sortieren, bearbeiten, E-Mail-Adressen
  zuordnen, Doppelungen zusammenführen, Kundenakten löschen.
- Neue Ansicht „Vorschau“: die PDF vor dem Erstellen sehen, mit Seiten und
  Zoom – sie aktualisiert sich bei jeder Änderung.
- Der bisherige Kundenverlauf wird beim ersten Start einmalig als
  Kundenakten übernommen (mit Sicherung).

Neu in Version 2.3
------------------
- Die App heißt jetzt PDF Tool. Nach dem Start zeigt eine Startseite alle
  Werkzeuge; die Navigation links führt zu Start, Tools und Einstellungen.
- „Vertragsübersichten“ ist ein eigenes Werkzeug. Alle Funktionen,
  Vorlagen, Textbausteine, Zyklus-Regeln, Kopf- und Fußzeilen und der
  Kundenverlauf bleiben erhalten.
- Neues Werkzeug „PDF reparieren“: Analyse, mehrstufige Reparatur mit zwei
  Engines (qpdf und PDFium), ehrliche Ergebnisse, Originaldatei bleibt
  unverändert.
- Verschlüsselte PDFs lassen sich mit dem richtigen Passwort reparieren;
  das Passwort wird nicht gespeichert.
- Neues App-Symbol.


Voraussetzungen
---------------
- Windows 10 oder Windows 11 (64 Bit)
- keine Administratorrechte
- rund 300 MB freier Speicher


Installation
------------
1. Die Setup-Datei doppelklicken.
2. Falls Windows SmartScreen erscheint:
   „Weitere Informationen“ → „Trotzdem ausführen“.
3. Dem Assistenten folgen: Zielordner bestätigen, optional
   „Verknüpfung auf dem Desktop erstellen“ an- oder abwählen.
4. Am Ende „PDF Tool starten“ angehakt lassen und „Fertigstellen“ wählen.

Programmdateien:  %LOCALAPPDATA%\PDF-Tool
Ihre Daten:       %APPDATA%\PDF-Tool
                  (Einstellungen, Kundenakten kundenakten.json, Vorlagen,
                  Textbausteine, Kopf- und Fußzeile, Zyklus-Regeln, Design,
                  Akzentfarbe, Protokoll pdf-repair.log)

Die App erscheint im Startmenü unter „PDF Tool“ und unter
Einstellungen → Apps → Installierte Apps.


Aktualisieren
-------------
Einfach das neue Setup ausführen. Die vorhandene Installation wird ersetzt,
es entsteht keine zweite Installation. Ihre Daten bleiben erhalten.

Update vom Übersichten-Ersteller (bis 2.2): Das Setup erkennt die
vorhandene Installation und aktualisiert sie – unter „Installierte Apps“
steht danach nur noch „PDF Tool“.
- Die Programmdateien ziehen von %LOCALAPPDATA%\Uebersichten-Ersteller
  nach %LOCALAPPDATA%\PDF-Tool um; der alte Programmordner wird entfernt
  (nur bekannte Programmdateien). Wurde ein eigener Ordner gewählt, bleibt
  er erhalten.
- Die Verknüpfungen „Übersichten-Ersteller“ im Startmenü und auf dem
  Desktop werden durch „PDF Tool“ ersetzt. Eine an die Taskleiste
  angeheftete alte Verknüpfung bitte lösen und PDF Tool neu anheften.
- Beim ersten Start übernimmt PDF Tool Ihre Daten aus
  %APPDATA%\Uebersichten-Ersteller: zuerst eine Sicherung
  (migration-backup-<Version>.zip im neuen Datenordner), dann eine Kopie,
  bei der jede Datei geprüft wird. Der alte Datenordner bleibt unverändert
  erhalten. Schlägt die Übernahme fehl, arbeitet die App mit dem alten
  Ordner weiter und versucht es beim nächsten Start erneut.

Update von PDF Tool 2.3: Das Setup ersetzt nur die Programmdateien. Beim
ersten Start wird der bisherige Kundenverlauf einmalig zu Kundenakten.
Vorher sichert die App die Einstellungen byte-genau nach
%APPDATA%\PDF-Tool\sicherungen\gui-config-vor-kundenakte-<Zeit>.json.
Schlägt die Übernahme fehl, bleibt der alte Verlauf unverändert erhalten
und sie wird beim nächsten Start erneut versucht. Vorlagen, Textbausteine,
Regeln sowie Kopf- und Fußzeile (auch die Standard-Fußzeile) bleiben wie
sie sind.

Update von 2.0.5 oder älter: Das Setup übernimmt die gespeicherten
Einstellungen (gui-config.json) und entfernt die alten Programmdateien,
Verknüpfungen und den alten Eintrag in „Installierte Apps“.

Läuft die App (auch der alte Übersichten-Ersteller) während des Updates,
meldet das Setup dies und wartet, bis sie geschlossen ist. Dasselbe Setup
erneut ausführen repariert die Installation.


Stille Installation (Skripte, Softwareverteilung)
-------------------------------------------------
   PDF-Tool-Setup-2.4.0.exe /VERYSILENT /SUPPRESSMSGBOXES
   PDF-Tool-Setup-2.4.0.exe /SILENT          (mit Fortschritt)

Weitere Parameter:
   /LOG="C:\Pfad\setup.log"      Protokoll an diesen Ort schreiben
   /DIR="C:\Pfad\Ordner"         anderer Zielordner
   /TASKS=""                     keine Desktop-Verknüpfung
   /MERGETASKS="!desktopicon"    dito, übrige Aufgaben unverändert

Stille Deinstallation:
   "%LOCALAPPDATA%\PDF-Tool\unins000.exe" /VERYSILENT
   (Ihre Daten bleiben dabei erhalten.)


Verwendung
----------
Startseite: Jedes Werkzeug hat eine Karte mit „Öffnen“. Eine Datei kann
auch direkt in das Fenster gezogen werden: Eine PDF öffnet „PDF reparieren“,
eine Excel-Liste „Vertragsübersichten“.

Tastatur: Strg+1 Start · Strg+2 Vertragsübersichten · Strg+3 PDF reparieren ·
Strg+4 Einstellungen · Strg+O Datei wählen · Strg+Enter Hauptaktion des
Werkzeugs · Strg+F bekannten Kunden suchen (Vertragsübersichten) ·
F1 Kurzanleitung · Tab/Umschalt+Tab zwischen Feldern wechseln ·
Leertaste/Eingabe löst Schaltflächen aus · Escape schließt Dialoge und Listen.


Werkzeug „Vertragsübersichten“
------------------------------
Oben wechselt die Umschaltleiste zwischen den Ansichten „Übersicht
erstellen“, „Darstellung“, „Vorschau“ und „Kunden“.

1. „Übersicht erstellen“: Excel-Liste wählen (Strg+O) oder die Datei in das
   Fenster ziehen. Die Prüfung zeigt aktive und ausgeblendete Verträge, den
   oder die Rechnungsempfänger, fehlende Spalten sowie Kundennummer und
   Firmenname, sofern sie in der Datei stehen. Bei mehreren Empfängern
   einen auswählen.
2. Ist ein Rechnungsempfänger als Kunde bekannt, erscheint „Bekannter Kunde
   gefunden“: „Übernehmen“ füllt die Kundendaten, „Kundenakte“ öffnet sie,
   „Ignorieren“ blendet den Hinweis für diese Excel aus. Sonst Firmenname
   und Kundennummer eintragen oder „Bekannten Kunden auswählen“ (Strg+F).
3. Optional Logo und Zielordner ändern; „Vorschau“ zeigt die PDF vorab.
4. Sobald „Bereit zum Erstellen“ erscheint: „PDF erstellen“ klicken oder
   Strg+Enter drücken. Fehlt etwas, nennt die Anzeige den Grund; ein Klick
   darauf führt zum passenden Feld. Der Schalter daneben legt fest, ob die
   PDF nach dem Erstellen geöffnet wird.
5. Nach dem Erstellen: „Öffnen“, „Ordner öffnen“, „Pfad kopieren“ oder
   „Neue Übersicht“ (leert Firma, Kundennummer, Empfänger und Excel-Datei;
   Logo, Zielordner, Darstellung, Vorlage, Kopf-/Fußzeile und Regeln bleiben).

Fettschrift: In der Excel-Liste fett formatierte Zellen erscheinen in der PDF
fett – zellgenau für Vertrag-Nr., Beschreibung (auch „Art“), Beginn,
Abrechnungszyklus, Netto und Zahlungsart. Andere Excel-Formate (Farben,
Schriftgrößen, Rahmen) werden bewusst nicht übernommen.

„Darstellung“: Vorlagen, Titel, Dateiname, Logo-Breite, Hoch- oder
Querformat, Kopfzeile, Fußzeile mit Textbausteinen, Zyklus-Regeln und
„Verlauf löschen“ (Liste der zuletzt erstellten PDFs).
Kopf- und Fußzeile haben eine Formatierungsleiste: Schriftart (Helvetica,
Times, Courier sowie – falls installiert – Arial, Calibri, Segoe UI und
Times New Roman), Größe 6–18 pt, fett (Strg+B), kursiv (Strg+I),
unterstrichen (Strg+U), durchgestrichen, Schriftfarbe und Ausrichtung
(Strg+L/E/R). Ohne Markierung gilt die Formatierung für neu getippten Text.
Strg+Z/Strg+Y machen Text- und Formatänderungen rückgängig bzw. wieder.
Die Fußzeile ist mit einem Standardtext vorbelegt; „Standard wiederherstellen“
setzt Text und Formatierung zurück. Kopf- und Fußzeile, Vorlagen,
Textbausteine und die Kundenakte speichern die Formatierung mit.

„Vorschau“: zeigt die PDF so, wie „PDF erstellen“ sie erzeugt – Seiten mit
den Pfeilen oder Bild ↑/↓ blättern, mit +/− zoomen, „An Breite anpassen“,
breite Seiten mit der Maus verschieben. Die Vorschau aktualisiert sich nach
jeder Änderung von selbst; „Aktualisieren“ erzeugt sie neu (z. B. nachdem
die Excel-Datei geändert wurde). Eine fehlende Kundennummer steht in der
Vorschau als „–“. Vorschau-Dateien landen nie im Zielordner.


Kundenakten (Vertragsübersichten → „Kunden“)
--------------------------------------------
Eine Kundenakte enthält Firmenname, Kundennummer, die E-Mail-Adressen der
Rechnungsempfänger (die erste ist primär), eine Notiz und Einstellungen für
Vertragsübersichten: bevorzugtes Logo, bevorzugter Zielordner, bevorzugte
Vorlage („Vorlage automatisch verwenden“) sowie eigene Kopf- und Fußzeile.
Dazu die letzte Aktivität: zuletzt verwendet, letzte Excel-Liste und
zuletzt erstellte Übersicht (nur als Pfad – Dateien werden nie kopiert).

So entstehen Kundenakten – immer bewusst:
- „Als Kundenakte speichern“ unter den Kundendaten (auch nach dem
  Erstellen einer PDF angeboten). Mit „Zuordnung merken“ wird die
  Rechnungsempfänger-E-Mail künftig diesem Kunden zugeordnet.
- „Neue Kundenakte“ in der Ansicht „Kunden“.
- Ist ein bekannter Kunde aktiv und steht eine neue Adresse in der Excel,
  fragt PDF Tool: „Diese E-Mail künftig diesem Kunden zuordnen?“

Übernehmen füllt nur die aktuelle Übersicht (Arbeitskopie). Wer danach
etwas ändert, ändert nicht die Kundenakte; „Kundenakte aktualisieren“
zeigt die Abweichungen und speichert nur die gewählten. Fehlt das
gespeicherte Logo oder der Zielordner, bleibt der aktuelle Wert
(„Gespeichertes Logo wurde nicht gefunden.“). Kopf- und Fußzeile der
Kundenakte ersetzen nur Texte, die in dieser Übersicht noch nicht geändert
wurden; eine leere Fußzeile ersetzt nie die gültige. „Neue Übersicht“ löst
die Kundenakte wieder.

Gehört eine E-Mail-Adresse schon einem anderen Kunden, entscheiden Sie:
„Bestehende Zuordnung verwenden“, „Zuordnung verschieben“ oder
„Abbrechen“. Enthält eine Excel Adressen verschiedener bekannter Kunden,
wählen Sie den passenden Kunden selbst.

In „Kunden“: Suche nach Firma, Kundennummer oder E-Mail (Strg+F),
Sortierung „Zuletzt verwendet“, „Firma A–Z“ oder „Kundennummer“,
Detailansicht mit Bearbeiten (wird automatisch gespeichert), E-Mail-Adressen
hinzufügen oder entfernen, „Zusammenführen …“ für Doppelungen (nur auf
Wunsch) und „Kundenakte löschen“ (entfernt nur die Kundenakte und ihre
Zuordnungen – erstellte PDF-Dateien und Excel-Listen bleiben erhalten).
„Bekannte Kunden automatisch übernehmen“ (Standard: aus) übernimmt einen
eindeutig erkannten Kunden ohne Nachfrage, solange noch keine anderen
Kundendaten eingetragen sind – rückgängig machbar.

Datenschutz: Kundenakten und E-Mail-Zuordnungen werden ausschließlich lokal
auf diesem PC gespeichert (%APPDATA%\PDF-Tool\kundenakten.json). Es gibt
keine Cloud, keine Synchronisierung, keine Telemetrie, keine E-Mail-Abfrage
und keine Internetsuche; aus einer E-Mail-Adresse wird nie ein Firmenname
abgeleitet.


Werkzeug „PDF reparieren“
-------------------------
1. Eine PDF wählen (Strg+O) oder in das Fenster ziehen – eine PDF pro
   Vorgang. Sie wird sofort analysiert.
2. Die Analyse zeigt Größe, Seiten, PDF-Version, Verschlüsselung und den
   Zustand:
   - „Keine Fehler gefunden“ – die PDF scheint strukturell in Ordnung zu
     sein. Ein Neuaufbau ist trotzdem möglich („Trotzdem neu aufbauen“).
   - „Reparierbare Probleme erkannt“ – beschädigte Strukturen, die
     möglicherweise repariert werden können.
   - „Schwer beschädigt“ – Teile der PDF können nicht gelesen werden;
     PDF Tool versucht, so viele Seiten und Inhalte wie möglich zu retten.
   - „Keine Reparatur möglich“ – die Datei lässt sich mit keiner der
     eingebauten Engines lesen.
   „Technische Details anzeigen“ listet Querverweistabelle, Objekte,
   Trailer, Seitenbaum, Metadaten, Datenströme und alle Befunde.
3. Verschlüsselte PDF: Passwort eingeben und „Entsperren“ wählen. Das
   Passwort wird nur für diesen Vorgang verwendet und nirgends gespeichert.
   Die reparierte Kopie bleibt mit demselben Passwort geschützt.
4. Speicherort wählen: „Neben der Original-PDF“ (Standard) oder „Anderer
   Ordner“. Die Einstellung wird gemerkt.
5. „PDF reparieren“ klicken oder Strg+Enter drücken. Der Fortschritt nennt
   die Arbeitsschritte; „Abbrechen“ beendet den Vorgang sofort, es bleibt
   keine unvollständige Datei zurück.
6. Ergebnis: Ausgabedatei, Größe vorher/nachher, Seiten vorher/nachher und
   Hinweise – mit „Öffnen“, „Ordner öffnen“, „Pfad kopieren“ und
   „Weitere PDF reparieren“.

Ergebnisse:
- „PDF wurde repariert“ – alle Seiten wurden vollständig übernommen und die
  neue Datei wurde geprüft.
- „PDF teilweise wiederhergestellt“ – z. B. „12 von 15 Seiten konnten
  vollständig rekonstruiert werden“. Fehlende Bestandteile werden genannt.
- „PDF konnte nicht repariert werden“ – es wird keine Datei gespeichert.
Nicht jede beschädigte Datei lässt sich vollständig wiederherstellen.

Die Originaldatei wird nie verändert oder überschrieben. Die neue Datei
heißt <Name>_repariert.pdf (bei Bedarf <Name>_repariert_2.pdf usw.).

Digitale Signaturen: Eine Reparatur kann die Gültigkeit von Signaturen
aufheben. Die App fragt deshalb vorher nach.

Rettungsmodus „Lesbare Seiten als neue PDF retten“: Nur wenn nichts anderes
hilft und nur nach Bestätigung. Die lesbaren Seiten werden als Bilder in
eine neue PDF übertragen – Text ist dann nicht mehr durchsuchbar oder
kopierbar, Links, Formulare und Lesezeichen fehlen.

Datenschutz: Die Verarbeitung erfolgt vollständig lokal auf diesem PC; es
wird nichts hochgeladen. Zwischendateien entstehen nur im temporären Ordner
von Windows und werden danach gelöscht. Das Protokoll pdf-repair.log im
Datenordner enthält technische Befunde, aber keine PDF-Inhalte, keine
vollständigen Pfade und keine Passwörter.


Einstellungen
-------------
Seite „Einstellungen“: App-Design (Wie Windows, Hell, Dunkel), Akzentfarbe
(Windows-Akzentfarbe oder eine eigene Farbe), Mica-Material, Animationen und
Informationen zur App. Einstellungen der Werkzeuge stehen im jeweiligen
Werkzeug.


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
fehler.log liegt im Datenordner %APPDATA%\PDF-Tool.
Das Setup schreibt ein Protokoll nach %TEMP% („Setup Log <Datum>.txt“)
oder an den mit /LOG angegebenen Ort.


Deinstallation
--------------
Einstellungen → Apps → Installierte Apps → „PDF Tool“ → Deinstallieren.

Entfernt werden Programmdateien, Verknüpfungen und der Eintrag in den
Windows-Einstellungen. Anschließend fragt die Deinstallation, ob auch Ihre
gespeicherten Einstellungen gelöscht werden sollen (Standard: Nein) – dazu
gehören auch die bei der Übernahme erhaltenen Daten des Übersichten-
Erstellers. Erstellte und reparierte PDF-Dateien bleiben in jedem Fall
erhalten.


Lizenzen
--------
PDF Tool nutzt freie Bibliotheken, u. a. Python (PSF), pikepdf (MPL-2.0)
mit qpdf (Apache-2.0), pypdfium2 (Apache-2.0/BSD-3-Clause) mit PDFium
(BSD-3-Clause), ReportLab (BSD), pandas, NumPy, openpyxl, xlrd und Pillow.
Die Übersicht steht im Programmordner in THIRD_PARTY_LICENSES.md, die
Lizenztexte unter runtime\LICENSE.txt und
runtime\Lib\site-packages\<Paket>.dist-info. Portions of this software are
copyright © The FreeType Project (www.freetype.org). All rights reserved.


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
   windows-app\dist\PDF-Tool-Setup-<Version>.exe
   windows-app\dist\PDF-Tool-Setup-<Version>.exe.sha256

Die Version steht nur in windows-app\VERSION. App, Setup und Dateiname
übernehmen sie von dort. ISCC.exe wird automatisch gesucht (PATH,
Umgebungsvariable ISCC, Standard-Installationsordner von Inno Setup 6).

Signieren: Sobald ein Code-Signing-Zertifikat vorhanden ist, die
Umgebungsvariable SIGN_COMMAND setzen, z. B.
   signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a "{file}"
Ohne Zertifikat bleibt das Setup unsigniert (SmartScreen-Hinweis beim ersten
Start ist dann normal).

Tests: py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0
       py -3.13 -m pytest windows-app\tests

GitHub Actions baut das Setup bei jedem Push auf windows-latest
(.github/workflows/windows-setup.yml), prüft es (auch die Updates vom
Übersichten-Ersteller 2.2.0 und von PDF Tool 2.3.0 mit Beispieldaten) und
stellt es als Artefakt bereit; bei einem veröffentlichten Release wird es
zusätzlich angehängt.
