PDF Tool für Windows
Entwickler und Inhaber: Jerico
=============================

Version 2.7.2

Werkzeuge für PDF-Dateien:
- Vertragsübersichten: erstellt professionelle Vertragsübersichten aus
  Excel-Listen und speichert sie als PDF – einzeln oder als Stapel aus
  vielen Excel-Dateien, mit Live-Vorschau, optionalen Kundenakten, die
  bekannte Kunden an der Rechnungsempfänger-E-Mail wiedererkennen, und
  einem Vergleich mit dem letzten Vertragsstand des Kunden.
- PDF reparieren: analysiert beschädigte PDF-Dateien – eine oder mehrere auf
  einmal – und versucht, lesbare Inhalte in neue PDFs zu übertragen; bei
  Bedarf baut es die Dokumentstruktur aus den noch vorhandenen Objekten neu
  auf.

Bis Version 2.2 hieß die App „Übersichten-Ersteller“.


Was Sie herunterladen
---------------------
PDF-Tool-Setup-2.7.2.exe

Die Datei enthält die komplette App einschließlich Python und aller Pakete
(Qt 6 mit PySide6, pandas, openpyxl, xlrd, ReportLab, Pillow, pikepdf mit
qpdf, pypdfium2 mit PDFium, pypdf). Eine eigene Python-Installation, qpdf, Ghostscript oder
andere Zusatzprogramme sind nicht nötig.


Neu in Version 2.7.2 – In-App Updates
-------------------------------------
PDF Tool findet neue Versionen jetzt selbst und installiert sie auf Wunsch.
- Einstellungen → Updates: aktuelle Version, Update-Kanal (Stable oder
  Beta), automatische Prüfung (ein/aus), letzte Prüfung und „Nach Updates
  suchen“.
- Die automatische Prüfung läuft höchstens einmal täglich im Hintergrund –
  der Start wartet nie darauf, ohne Internet passiert nichts.
- Ist eine neue Version da, erscheint oben ein Hinweis: „Details“ zeigt die
  Neuerungen, „Herunterladen“ lädt das Setup mit Fortschrittsanzeige.
- Jedes heruntergeladene Setup wird per SHA-256 mit der veröffentlichten
  Prüfsumme verglichen. Stimmt sie nicht, wird nichts installiert.
- „Jetzt installieren“ beendet PDF Tool und startet das Setup. Während einer
  laufenden Verarbeitung (z. B. PDF-Reparatur, Stapel) wartet PDF Tool damit.

Neu in Version 2.7.1 – PDF Repair Batch
---------------------------------------
„PDF reparieren“ verarbeitet jetzt mehrere PDFs auf einmal.
- Mehrere PDFs auswählen (Mehrfachauswahl) oder zusammen in das Fenster
  ziehen; weitere lassen sich jederzeit hinzufügen. Dieselbe Datei wird
  nur einmal aufgenommen, andere Dateien werden mit Hinweis übergangen.
- Jede PDF wird für sich geprüft. Die Liste zeigt je Datei den Zustand
  (z. B. „Beschädigt · Reparatur möglich“, „Passwort erforderlich“),
  den geplanten Ausgabenamen und den Fortschritt; darüber steht der
  Gesamtstand, z. B. „8 PDFs · 6 reparierbar · 1 verschlüsselt · 1 nicht
  wiederherstellbar“.
- „Alle reparieren“ repariert die beschädigten PDFs nacheinander –
  Fortschritt gesamt („3 / 8 Dateien“) und je Datei (Analyse, Reparatur,
  Validierung, Fertig). „Abbrechen“ beendet die laufende Reparatur sauber;
  fertige Dateien bleiben. Ein Fehler betrifft nur seine Datei.
- Danach eine Zusammenfassung, z. B. „5 erfolgreich repariert · 1 teilweise
  wiederhergestellt · 1 fehlgeschlagen“, mit „Ausgabeordner öffnen“ und
  „Fehlgeschlagene erneut versuchen“.
- Dateinamen: Der Schalter „„repariert“ an Dateinamen anhängen“ (Standard:
  ein) ergibt wie bisher Rechnung_repariert.pdf, ausgeschaltet Rechnung.pdf;
  der Zusatz ist änderbar (z. B. „_gefixt“). Jeder Name lässt sich einzeln
  ändern, die Endung .pdf ergänzt PDF Tool selbst.
- Die Originaldatei wird nie überschrieben: Gibt es den Namen schon, wird
  nummeriert – „Rechnung (1).pdf“, „Rechnung_repariert (1).pdf“ (bisher
  „…_repariert_2.pdf“).
- Mit einer einzelnen PDF bleibt alles so einfach wie bisher.

Neu in Version 2.7 – Next Generation UI
---------------------------------------
PDF Tool hat eine vollständig neue Oberfläche auf Basis von Qt 6.
- Neues, modernes Design im Stil von Windows 11; Hell, Dunkel, „Wie
  Windows“ und die Akzentfarbe wirken sofort.
- Flüssigere Navigation mit sanften Seitenübergängen; echte Animationen
  für Menüs, Dialoge, aufklappende Bereiche, Hinweise, Schaltflächen und
  Schalter. Einstellungen → Animationen: Vollständig, Reduziert oder Aus.
  Ist in Windows „Animationseffekte“ aus, gilt mindestens „Reduziert“.
- Scharfe Darstellung auf hochauflösenden Bildschirmen (100–200 %).
- Effizientere Listen im Stapel, in der Kundenliste und im Vertrags-
  vergleich – auch mit Hunderten Einträgen flüssig.
- Vorschau mit Seiten blättern, Zoom, „An Breite anpassen“ und „Ganze
  Seite“; „PDF reparieren“ mit neuer, übersichtlicher Oberfläche.
- Alle Funktionen aus 2.6.1 bleiben erhalten.
- Keine manuelle Migration: Einstellungen, Kunden, Vorlagen, Regeln und
  Vertragsstände werden weiterverwendet.

Neu in Version 2.6.1
--------------------
Ein Qualitäts-Update: Geschwindigkeit, ruhige Darstellung und Bedienkomfort.
- Die Kundenakte ist jetzt optional: Einstellungen → Vertragsübersichten →
  „Kundenakte verwenden“. Bei neuen Installationen – und auch nach dem
  Update – ist sie zunächst aus. Gespeicherte Kundendaten bleiben dabei
  immer erhalten; nach dem Einschalten stehen sie sofort wieder bereit.
- Ausgeschaltet werden keine Kundendaten gespeichert oder abgeglichen und
  die Kunden-Elemente sind ausgeblendet. Firmenname, Kundennummer und
  Rechnungsempfänger tragen Sie selbst ein (oder sie stammen aus der
  Excel); Vorschau, Stapel und PDF-Erstellung funktionieren unverändert.
- Flüssigere Oberfläche: Ansichten werden verdeckt vorbereitet und
  erscheinen fertig, der Start ist schneller, das Ändern der Fenstergröße
  ruhiger; Animationen sind kurz und einheitlich.
- Die Vorschau wird beim erneuten Öffnen nicht neu erzeugt, der
  Vertragsvergleich nur bei echten Änderungen neu berechnet.
- Ist in Windows „Animationseffekte“ ausgeschaltet, wechseln Seiten ohne
  Bewegung.

Neu in Version 2.6
------------------
- Vertragsvergleich in „Übersicht erstellen“: Nach der Excel-Prüfung zeigt
  die Karte „Vertragsänderungen“, welche Verträge seit dem letzten Stand
  des Kunden neu, entfernt oder geändert sind – z. B. „Seit 12.08.2026 ·
  2 neu · 1 entfernt · 1 geändert · 4 unverändert“.
- Ein Vertragsstand wird nur nach einer erfolgreich erstellten PDF
  gespeichert – je Kundenakte, nie für die Vorschau, einen Abbruch oder
  einen Fehler. Alte PDF- oder Excel-Dateien werden dafür nicht gebraucht.
- Im Stapel stehen die Änderungen kompakt in der Liste („+2 neu ·
  ~1 geändert“), die Einzelheiten in der Detailansicht.
- „PDF reparieren“ rettet deutlich mehr: Öffnet keine PDF-Engine die Datei,
  heißt es „Erweiterte Wiederherstellung möglich“, und „PDF-Struktur
  rekonstruieren“ baut Querverweise, Trailer und Seitenbaum aus den noch
  vorhandenen Objekten neu auf.
- Neue dritte, tolerante PDF-Engine (pypdf). Jede reparierte Datei wird
  normalisiert und streng geprüft; teilweise gerettete Dateien sind
  deutlich gekennzeichnet.

Neu in Version 2.5
------------------
- Neue Stapelverarbeitung in „Vertragsübersichten“ (Ansicht „Stapel“):
  mehrere Excel-Dateien oder einen ganzen Ordner hinzufügen und daraus in
  einem Durchlauf Vertragsübersichten erstellen.
- Jede Datei wird sofort geprüft; bekannte Kunden werden über die
  gespeicherten E-Mail-Zuordnungen erkannt – genau wie im Einzelmodus.
- Status je Datei („Bereit“, „Angaben erforderlich“, „Fehler“, „Erstellt“),
  Filter, Massenaktionen (z. B. Vorlage für mehrere Einträge setzen) und
  Fortschritt mit „Stapel abbrechen“.
- Nur bereite Dateien werden verarbeitet; ein Fehler bei einer Datei
  unterbricht den Stapel nicht. „Fehlgeschlagene erneut versuchen“
  verarbeitet nur die fehlgeschlagenen erneut.
- Vorhandene PDFs werden nie unbeabsichtigt überschrieben (Standard:
  automatisch nummerieren, z. B. …_2.pdf).
- Kompaktere Excel-Karte in „Übersicht erstellen“: Die Vertragszahlen
  stehen nur noch in der Statuszeile („Excel geprüft · 5 aktive Verträge ·
  3 inaktiv ausgeblendet“), darunter nur zusätzliche Angaben wie der
  Rechnungsempfänger – bei mehreren „3 erkannt“ mit Auswahl.

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
- Windows 10 (Version 1809 oder neuer) oder Windows 11 (64 Bit) – die
  Oberfläche (Qt 6) setzt Windows 10 Version 1809 voraus
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
                  (Einstellungen, Kundenakten kundenakten.json,
                  Vertragsstände im Ordner contract-history, Vorlagen,
                  Textbausteine, Kopf- und Fußzeile, Zyklus-Regeln, Design,
                  Akzentfarbe, aktueller Stapel stapel.json, Protokolle
                  pdf-repair.log und stapel.log)

Die App erscheint im Startmenü unter „PDF Tool“ und unter
Einstellungen → Apps → Installierte Apps.


Aktualisieren
-------------
Ab Version 2.7.2 meldet PDF Tool neue Versionen selbst: Einstellungen →
Updates → „Nach Updates suchen“, oder der Hinweis nach der automatischen
Prüfung. „Herunterladen“ und danach „Jetzt installieren“ – PDF Tool beendet
sich, das Setup startet und aktualisiert die vorhandene Installation. Am
Ende kann PDF Tool direkt wieder gestartet werden.

Update-Kanal: „Stable“ (Standard) erhält nur freigegebene Versionen. „Beta“
erhält zusätzlich Vorabversionen zum Testen – Beta-Versionen können Fehler
enthalten und sind nicht vollständig freigegeben. Ein Wechsel von Beta zurück
zu Stable installiert nie eine ältere Version; er wirkt, sobald eine neuere
stabile Version erscheint.

Alternativ wie bisher: das neue Setup von GitHub herunterladen und ausführen.
Die vorhandene Installation wird ersetzt, es entsteht keine zweite
Installation. Ihre Daten bleiben erhalten.

Update von PDF Tool 2.7.1 auf 2.7.2: Das Setup ersetzt nur die
Programmdateien. Alle Einstellungen und Daten bleiben unverändert. Der
Update-Kanal ist danach „Stable“, die automatische Prüfung eingeschaltet.

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

Update von PDF Tool 2.7.0 auf 2.7.1: Das Setup ersetzt nur die
Programmdateien. Alle Einstellungen und Daten bleiben unverändert. Der neue
Schalter „„repariert“ an Dateinamen anhängen“ ist eingeschaltet – reparierte
Dateien heißen wie bisher <Name>_repariert.pdf.

Update von PDF Tool 2.6.1 auf 2.7.0: Das Setup ersetzt die
Programmdateien vollständig durch die neue Oberfläche – die frühere
Oberfläche bleibt nicht zurück. Einstellungen, Kundenakten, E-Mail-
Zuordnungen, Vorlagen, Textbausteine, formatierte Kopf- und Fußzeilen,
Zyklus-Regeln, Stapel- und Reparatur-Einstellungen und Vertragsstände
werden unverändert weiterverwendet; die Kundenakte bleibt so eingestellt,
wie sie war. Eine manuelle Migration ist nicht nötig.

Update von PDF Tool 2.6.0: Das Setup ersetzt nur die Programmdateien.
Die Kundenakte ist jetzt optional und zunächst aus – Ihre Kundenakten,
E-Mail-Zuordnungen und Vertragsstände bleiben unverändert erhalten. Ein
einmaliger Hinweis nennt die neue Einstellung; nach dem Einschalten
(Einstellungen → Vertragsübersichten → „Kundenakte verwenden“) ist alles
sofort wieder da. Einstellungen, Vorlagen, Textbausteine, formatierte
Kopf- und Fußzeilen, Zyklus-Regeln, Stapel- und Reparatur-Einstellungen,
Design und Akzentfarbe bleiben unverändert.

Update von PDF Tool 2.3: Das Setup ersetzt nur die Programmdateien. Der
bisherige Kundenverlauf bleibt unverändert erhalten. Sobald Sie die
Kundenakte einschalten, wird er einmalig zu Kundenakten. Vorher sichert die
App die Einstellungen byte-genau nach
%APPDATA%\PDF-Tool\sicherungen\gui-config-vor-kundenakte-<Zeit>.json.
Schlägt die Übernahme fehl, bleibt der alte Verlauf unverändert erhalten
und sie wird beim nächsten Start erneut versucht. Vorlagen, Textbausteine,
Regeln sowie Kopf- und Fußzeile (auch die Standard-Fußzeile) bleiben wie
sie sind.

Update von PDF Tool 2.5: Das Setup ersetzt nur die Programmdateien.
Einstellungen, Kundenakten, Vorlagen, Textbausteine, formatierte Kopf- und
Fußzeilen, Zyklus-Regeln, der gespeicherte Stapel mit seinen Einstellungen
und die Einstellungen von „PDF reparieren“ bleiben unverändert. Frühere
Vertragsstände gibt es noch nicht – es werden keine künstlich angelegt.
Der erste Export mit Kundenakte meldet „Erster Vertragsstand gespeichert“,
ab dem nächsten Excel-Import erscheint der Vergleich.

Update von PDF Tool 2.4: Das Setup ersetzt nur die Programmdateien.
Einstellungen, Kundenakten, Vorlagen, Textbausteine, formatierte Kopf- und
Fußzeilen, Zyklus-Regeln und die Einstellungen von „PDF reparieren“
bleiben unverändert.

Update von 2.0.5 oder älter: Das Setup übernimmt die gespeicherten
Einstellungen (gui-config.json) und entfernt die alten Programmdateien,
Verknüpfungen und den alten Eintrag in „Installierte Apps“.

Läuft die App (auch der alte Übersichten-Ersteller) während des Updates,
meldet das Setup dies und wartet, bis sie geschlossen ist. Dasselbe Setup
erneut ausführen repariert die Installation.


Stille Installation (Skripte, Softwareverteilung)
-------------------------------------------------
   PDF-Tool-Setup-2.7.1.exe /VERYSILENT /SUPPRESSMSGBOXES
   PDF-Tool-Setup-2.7.1.exe /SILENT          (mit Fortschritt)

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
Startseite: Jedes Werkzeug hat eine Karte mit „Öffnen“. Dateien können
auch direkt in das Fenster gezogen werden: PDFs (eine oder mehrere) öffnen
„PDF reparieren“, eine Excel-Liste „Vertragsübersichten“.

Tastatur: Strg+1 Start · Strg+2 Vertragsübersichten · Strg+3 PDF reparieren ·
Strg+4 Einstellungen · Strg+O Datei wählen · Strg+Enter Hauptaktion des
Werkzeugs · Strg+F bekannten Kunden suchen (Vertragsübersichten, mit
Kundenakte) ·
F1 Kurzanleitung · Tab/Umschalt+Tab zwischen Feldern wechseln ·
Leertaste/Eingabe löst Schaltflächen aus · Escape schließt Dialoge und Listen.


Werkzeug „Vertragsübersichten“
------------------------------
Oben wechselt die Umschaltleiste zwischen den Ansichten „Übersicht
erstellen“, „Stapel“, „Darstellung“, „Vorschau“ und – mit eingeschalteter
Kundenakte – „Kunden“.

1. „Übersicht erstellen“: Excel-Liste wählen (Strg+O) oder die Datei in das
   Fenster ziehen. Die Statuszeile nennt das Ergebnis, z. B. „Excel geprüft ·
   5 aktive Verträge · 3 inaktiv ausgeblendet“. Darunter stehen nur
   zusätzliche Angaben: der Rechnungsempfänger (bei mehreren „3 erkannt“
   mit Auswahl daneben) und Hinweise. Kundennummer und Firmenname aus der
   Datei werden übernommen, sofern sie darin stehen.
2. Firmenname und Kundennummer eintragen, sofern sie nicht aus der Excel
   stammen. Mit eingeschalteter Kundenakte: Ist ein Rechnungsempfänger als
   Kunde bekannt, erscheint „Bekannter Kunde gefunden“: „Übernehmen“ füllt
   die Kundendaten, „Kundenakte“ öffnet sie, „Ignorieren“ blendet den
   Hinweis für diese Excel aus; oder „Bekannten Kunden auswählen“ (Strg+F).
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


Stapelverarbeitung (Vertragsübersichten → „Stapel“)
---------------------------------------------------
Mit „Stapel“ entstehen viele Vertragsübersichten in einem Durchlauf – der
Einzelmodus „Übersicht erstellen“ bleibt unverändert.

1. „Excel-Dateien hinzufügen“ (Mehrfachauswahl, Strg+O), „Ordner
   hinzufügen“ (alle Excel-Dateien des Ordners, ohne Unterordner) oder
   mehrere Dateien in das Fenster ziehen. Dieselbe Datei wird nie doppelt
   aufgenommen; andere Dateien werden mit Hinweis übergangen.
2. Jede Datei wird sofort im Hintergrund geprüft – mit derselben Prüfung
   wie im Einzelmodus. Die Liste zeigt je Datei den Status, kurz die
   Vertragszahlen und den Rechnungsempfänger sowie den erkannten Kunden.
3. Stehen Firmenname und Kundennummer in der Excel, ist der Eintrag
   „Bereit“; sonst „Angaben erforderlich“: Firmenname und Kundennummer
   eintragen. Mit eingeschalteter Kundenakte werden bekannte Kunden
   zusätzlich über die gespeicherten E-Mail-Zuordnungen erkannt („Kunden
   auswählen …“); gehören die Empfänger verschiedenen Kunden, entscheiden
   Sie selbst. Ohne Kundenakte gibt es keinen Abgleich, keine Zuordnung
   und keinen Vertragsvergleich – die Angaben stehen direkt am Eintrag.
4. Ein Klick auf einen Eintrag öffnet ihn: Kunde, Firmenname, Kundennummer,
   Rechnungsempfänger, Vorlage, Logo und Zielordner lassen sich hier nur
   für diesen Eintrag setzen („Zurücksetzen“ übernimmt wieder Kundenakte
   bzw. Stapel). „Vorschau“ zeigt genau diesen Eintrag, „Einzeln
   bearbeiten“ übernimmt ihn in „Übersicht erstellen“. Wird einem Eintrag
   bewusst ein Kunde zugeordnet, bietet PDF Tool „Zuordnung merken“ für
   neue E-Mail-Adressen an – nie automatisch.
5. „Bereite Übersichten erstellen“ (Strg+Enter) verarbeitet nacheinander
   nur die bereiten Einträge; die Anzeige nennt den Fortschritt und die
   Datei, die gerade entsteht. Einträge mit fehlenden Angaben werden
   übersprungen, ein Fehler bei einer Datei hält die übrigen nicht auf.
   „Stapel abbrechen“ beendet die laufende PDF sauber; fertige PDFs
   bleiben, halbe Dateien entstehen nie.
6. Danach: „Ausgabeordner öffnen“, „Fehler anzeigen“,
   „Fehlgeschlagene erneut versuchen“ oder „Neuer Stapel“ (leert nur die
   Liste – Kundenakten, Vorlagen und Einstellungen bleiben).

Welche Angaben gelten (von oben nach unten, die erste vorhandene zählt):
- Vorlage: im Eintrag gewählt → bevorzugte Vorlage der Kundenakte →
  Standardvorlage des Stapels → keine (aktuelle „Darstellung“).
- Logo: im Eintrag gewählt → Logo der Kundenakte → Standardlogo des
  Stapels → installiertes Standardlogo.
- Zielordner: im Eintrag gewählt → Zielordner der Kundenakte (abschaltbar)
  → Zielordner des Stapels (auf Wunsch mit Unterordner je Kunde, z. B.
  „123456 Beispiel GmbH“).
- Kopf- und Fußzeile: aus einer im Eintrag gewählten Vorlage, sonst die
  eigenen Texte der Kundenakte, sonst Vorlage bzw. „Darstellung“. Eine
  leere Fußzeile ersetzt nie die gültige.
Gibt es die PDF schon, wird standardmäßig nummeriert (…_2.pdf); alternativ
„Überspringen“ oder „Überschreiben“ (nie eine im selben Stapel erstellte
Datei). Nach dem Erstellen werden in der Kundenakte nur „zuletzt
verwendet“, letzte Excel und letzte PDF fortgeschrieben.
Der aktuelle Stapel wird lokal gesichert (stapel.json: nur Pfade,
Zuordnungen und eigene Angaben – keine Kopien der Excel-Dateien); nach
einem Neustart ist er wieder da. Technische Fehler stehen in stapel.log
(ohne Inhalte der Excel-Dateien und ohne vollständige Pfade).


Vertragsänderungen (Vertragsübersichten → „Übersicht erstellen“)
-----------------------------------------------------------------
Ist eine Kundenakte aktiv, vergleicht PDF Tool nach der Excel-Prüfung die
Verträge mit dem zuletzt gespeicherten Stand dieses Kunden. Der Vergleich
braucht eine sichere Kundenidentität: Ist die Kundenakte ausgeschaltet,
bleibt die Karte verborgen, es wird nichts geraten (weder über Firmenname
noch über E-Mail-Adresse) – und gespeicherte Stände bleiben unverändert. Die Karte
„Vertragsänderungen“ zeigt z. B. „Seit 12.08.2026“ und „2 neu · 1 entfernt
· 1 geändert · 4 unverändert“ in Farben (neu grün, entfernt rot, geändert
gelb, unverändert grau). Aufgeführt werden nur die Änderungen:
- Neu: z. B. „10006 Cloud-Speicher – 19,00 €“
- Entfernt: „nicht mehr in der Excel“
- Geändert: ein Klick klappt die geänderten Felder auf, z. B.
  „Netto: 250,00 € → 270,00 €“.
„4 unveränderte anzeigen“ blendet die übrigen Verträge ein. „Vergleichen
mit“ wählt einen früheren Stand (Standard: „Letzter Stand“), „Änderungen
kopieren“ legt den Vergleich als Text in die Zwischenablage. Darunter
stehen Datum und Uhrzeit des Stands sowie die damalige Excel- und PDF-Datei
(„nicht mehr vorhanden“, wenn sie gelöscht wurde – für den Vergleich wird
sie nicht gebraucht).

Wann wird ein Stand gespeichert?
- Nur nach einer erfolgreich erstellten PDF und nur mit Kundenakte – nie
  für die Vorschau, die Excel-Prüfung, einen Abbruch oder einen Fehler.
- Gespeichert werden die Verträge so, wie sie in der PDF stehen
  (Vertragsnummer, Art, Beschreibung, Beginn, Abrechnungszyklus, Netto,
  Zahlungsart) – keine Kopie der PDF oder der Excel.
- Ist der Stand unverändert, entsteht kein zweiter Eintrag; es wird nur
  mitgezählt („2× erstellt, zuletzt …“).
- Der Vergleich gehört immer zur Kundenakte, nie zu einem ähnlichen
  Firmennamen. Eine geänderte Vertragsnummer zählt als „entfernt“ und
  „neu“. Formatierung (z. B. Fettschrift) zählt nicht als Änderung.
- Der Vergleich ändert die PDF nicht und wird nicht in die Übersicht
  gedruckt.

Im Stapel speichert jeder erfolgreich erstellte Eintrag mit Kundenakte
seinen eigenen Stand (übersprungene und fehlgeschlagene nicht). Die Liste
zeigt kurz „+2 neu · ~1 geändert“, die Detailansicht den ganzen Vergleich.

Ablage: %APPDATA%\PDF-Tool\contract-history\<Kunden-ID>\ – je Stand eine
kleine Datei. Je Kunde bleiben die letzten 50 unterschiedlichen Stände
erhalten; ältere werden beim Speichern eines neuen Stands entfernt. Beim
Zusammenführen von Kundenakten gehören beide Verläufe zum Ziel. Die
Vertragsstände bleiben bei Updates erhalten und liegen nur auf diesem PC.
Wer seine Daten sichert, sichert den ganzen Ordner %APPDATA%\PDF-Tool.


Kundenakten (Vertragsübersichten → „Kunden“)
--------------------------------------------
Die Kundenakte ist optional: Einstellungen → Vertragsübersichten →
„Kundenakte verwenden“ (Standard: aus). Ist sie aus, werden keine
Kundendaten automatisch gespeichert oder abgeglichen – nicht einmal im
Hintergrund –, die Ansicht „Kunden“ und alle Kunden-Elemente sind
ausgeblendet, und vorhandene Kundenakten bleiben unverändert auf diesem PC
liegen. Einschalten wirkt sofort, ohne Neustart; alle gespeicherten
Kundenakten stehen dann wieder zur Verfügung.

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
1. Eine oder mehrere PDFs wählen („PDFs auswählen“, Strg+O, Mehrfach-
   auswahl) oder in das Fenster ziehen; „PDFs hinzufügen“ nimmt weitere
   auf. Jede Datei wird sofort für sich analysiert (höchstens zwei
   gleichzeitig). Dieselbe Datei steht nur einmal in der Liste; das Kreuz
   an einem Eintrag nimmt ihn heraus, „Alle entfernen“ leert die Liste –
   die Dateien selbst bleiben unverändert.
2. Die Analyse zeigt Größe, Seiten, PDF-Version, Verschlüsselung und den
   Zustand (mit mehreren PDFs kurz am Eintrag, ausführlich unter „Details
   anzeigen“):
   - „Keine Fehler gefunden“ – die PDF scheint strukturell in Ordnung zu
     sein. Ein Neuaufbau ist trotzdem möglich („Trotzdem neu aufbauen“).
   - „Reparierbare Probleme erkannt“ – beschädigte Strukturen, die
     möglicherweise repariert werden können.
   - „Schwer beschädigt“ – Teile der PDF können nicht gelesen werden;
     PDF Tool versucht, so viele Seiten und Inhalte wie möglich zu retten.
   - „Erweiterte Wiederherstellung möglich“ – keine PDF-Engine öffnet die
     Datei, es wurden aber noch PDF-Objekte (und Datenströme) gefunden.
     „PDF-Struktur rekonstruieren“ versucht, die noch vorhandenen Inhalte
     wiederherzustellen.
   - „Keine Reparatur möglich“ – die Datei lässt sich mit keiner der
     eingebauten Engines lesen, und es ist keine verwertbare Struktur mehr
     vorhanden.
   „Technische Details anzeigen“ listet Querverweistabelle, Objekte,
   Trailer, Seitenbaum, Metadaten, Datenströme und alle Befunde – bei
   beschädigten Dateien auch die Rohanalyse (Objektkandidaten, Katalog,
   Seitenobjekte, Seitenbaum-Knoten, xref, Trailer, startxref, %%EOF).
3. Verschlüsselte PDF: Passwort am Eintrag eingeben und „Entsperren“
   wählen. Das Passwort gilt nur für diese Datei, wird nie für andere PDFs
   verwendet und nirgends gespeichert. Die reparierte Kopie bleibt mit
   demselben Passwort geschützt.
4. Ausgabe festlegen: „Neben der Original-PDF“ (Standard) oder
   „Gemeinsamer Ausgabeordner“, dazu der Schalter „„repariert“ an
   Dateinamen anhängen“ und – eingeschaltet – der Zusatz (Standard
   „_repariert“). Jeder Eintrag zeigt seinen Ausgabenamen und lässt ihn
   ändern; ».pdf« wird ergänzt, ungültige Namen (z. B. mit : oder ?)
   werden sofort angezeigt. Ein eigener Name bleibt, auch wenn Sie den
   Schalter umstellen – bis „Automatischen Namen wiederherstellen“.
   Die Einstellungen werden gemerkt.
5. „PDF reparieren“ (eine PDF) bzw. „Alle reparieren“ (alle beschädigten)
   klicken oder Strg+Enter drücken; „Nur diese Datei reparieren“ repariert
   einen einzelnen Eintrag. Repariert wird nacheinander; der Fortschritt
   nennt die Datei und den Schritt (Analyse, Reparatur, Validierung,
   Fertig). „Abbrechen“ beendet die laufende Reparatur sofort – es bleibt
   keine unvollständige Datei zurück – und lässt die noch nicht begonnenen
   aus; fertige Dateien bleiben. Gesunde PDFs repariert „Alle reparieren“
   nicht; „Trotzdem neu aufbauen“ geht einzeln.
6. Ergebnis je Datei: Ausgabedatei, Größe und Seiten vorher/nachher und
   Hinweise – mit „Öffnen“, „Ordner öffnen“ und „Pfad kopieren“. Dazu die
   Zusammenfassung des Durchlaufs, „Ausgabeordner öffnen“,
   „Fehlgeschlagene erneut versuchen“ und „Weitere PDFs reparieren“.

Ergebnisse:
- „PDF wurde repariert“ – alle Seiten wurden vollständig übernommen und die
  neue Datei wurde geprüft.
- „PDF teilweise wiederhergestellt“ – z. B. „12 von 15 Seiten konnten
  vollständig rekonstruiert werden“. Fehlende Bestandteile werden genannt.
- „PDF konnte nicht repariert werden“ – es wird keine Datei gespeichert.
Nicht jede beschädigte Datei lässt sich vollständig wiederherstellen.

Die Originaldatei wird nie verändert, umbenannt oder überschrieben. Die neue
Datei heißt <Name>_repariert.pdf (Schalter aus: <Name>.pdf). Gibt es den
Namen im Zielordner schon – auch anders geschrieben, z. B. „rechnung.PDF“ –,
ist es das Original oder bekommt ihn bereits eine andere Datei der Liste,
wird nummeriert: <Name>_repariert (1).pdf, (2) usw. Die Namen werden beim
Start festgelegt; eine vorhandene Datei wird nie überschrieben.

Erweiterte Wiederherstellung: PDF Tool versucht nacheinander qpdf, die
Übertragung einzelner Seiten, PDFium und die tolerante Engine pypdf. Reicht
das nicht, sucht es die noch vorhandenen PDF-Objekte direkt in der Datei,
schreibt eine neue Querverweistabelle, einen neuen Trailer und das
Dateiende und baut bei Bedarf den Seitenbaum neu auf – mit Seitengröße,
Schriften und Bildern, die die Seiten vorher über den Seitenbaum geerbt
haben. Fehlt eine Schrift ganz, wird sie durch eine Standardschrift
ersetzt; das Ergebnis heißt dann ehrlich „teilweise wiederhergestellt“.
Jede reparierte Datei wird vor dem Speichern mit zwei Engines geprüft.
Verschlüsselte Dateien ohne Verschlüsselungsangaben werden nicht
rekonstruiert – ein Passwortschutz wird nie umgangen.

Digitale Signaturen: Eine Reparatur kann die Gültigkeit von Signaturen
aufheben. Die App fragt deshalb vorher nach – mit mehreren PDFs einmal für
alle signierten („Alle reparieren“ oder „Signierte überspringen“).

Rettungsmodus „Lesbare Seiten als neue PDF retten“: Nur wenn nichts anderes
hilft, nur für die einzelne Datei („Weitere Rettungsoption verfügbar“) und
nur nach Bestätigung – „Alle reparieren“ verwendet ihn nie. Die lesbaren Seiten werden als Bilder in
eine neue PDF übertragen – Text ist dann nicht mehr durchsuchbar oder
kopierbar, Links, Formulare und Lesezeichen fehlen.

Datenschutz: Die Verarbeitung erfolgt vollständig lokal auf diesem PC; es
wird nichts hochgeladen. (Die einzige Internetverbindung von PDF Tool ist
die Update-Prüfung bei GitHub – ohne Dateien oder persönliche Daten.)
Zwischendateien entstehen nur im temporären Ordner von Windows und werden
danach gelöscht. Das Protokoll pdf-repair.log im
Datenordner enthält technische Befunde, aber keine PDF-Inhalte, keine
vollständigen Pfade und keine Passwörter.


Einstellungen
-------------
Seite „Einstellungen“: App-Design (Wie Windows, Hell, Dunkel), Akzentfarbe
(Windows-Akzentfarbe oder eine eigene Farbe), Mica-Material, Animationen
(Vollständig, Reduziert, Aus), Kundenakte und Informationen zur App.
Einstellungen der Werkzeuge stehen im jeweiligen Werkzeug.


Windows-11-Design
-----------------
Die Oberfläche (Qt 6, Qt Quick) folgt dem Fluent Design von Windows 11:
Navigation links, Karten mit runden Ecken, Segoe-UI-Variable-Schrift und
Fluent-Symbole. Unter Windows 11 erhalten Titelleiste und Navigation das
Mica-Material, unter Windows 10 eine passende einfarbige Fläche.
Animationen richten sich nach der Windows-Einstellung „Animationseffekte“
(dann mindestens „Reduziert“) und lassen sich in der App auf „Reduziert“
oder „Aus“ stellen.


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
gehören Kundenakten, Vertragsstände, der gespeicherte Stapel und die bei
der Übernahme erhaltenen Daten des Übersichten-Erstellers. Erstellte und
reparierte PDF-Dateien und Ihre Excel-Listen bleiben in jedem Fall
erhalten.


Lizenzen
--------
PDF Tool nutzt freie Bibliotheken, u. a. Python (PSF), pikepdf (MPL-2.0)
mit qpdf (Apache-2.0), pypdfium2 (Apache-2.0/BSD-3-Clause) mit PDFium
(BSD-3-Clause), pypdf (BSD-3-Clause), ReportLab (BSD), pandas, NumPy,
openpyxl, xlrd und Pillow.
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

Tests: py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0 PySide6-Essentials==6.11.2
       py -3.13 -m pytest windows-app\tests

GitHub Actions baut das Setup bei jedem Push auf windows-latest
(.github/workflows/windows-setup.yml), prüft es (Clean Install, Update von
der vorherigen stabilen Version, Updater-Test) und stellt es als Artefakt
bereit. Releases (Stable und Beta) veröffentlicht derselbe Workflow – siehe
docs/RELEASE.md im Repository.
