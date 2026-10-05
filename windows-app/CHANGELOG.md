# Changelog

Ausführliche Hinweise je Version: [`release-notes/`](release-notes/).

# PDF Tool 3.0.0-beta.2

Beta zum Testen (Kanal „Beta“). Behebt den Fehler beim Speichern von PDFs mit XMP-Metadaten aus
3.0.0-beta.1 und bringt das Werkzeug „Objekt bearbeiten“ sowie einen aufgeräumten Reader.

## Neu

- PDF Editor: Werkzeug „Objekt bearbeiten“. Es wählt Text und Bilder einzeln statt ganzer
  Textblöcke.
  - Auswahl: eine Zeile einer Adresse, eine Tabellenzelle oder ein Wort; ein Klick wählt die Zeile,
    ein weiterer Klick das Wort, ein Doppelklick bearbeitet genau dieses Stück.
  - Aktionen: ändern, verschieben (Ziehen oder Pfeiltasten), löschen, Größe, Farbe und
    Zeichenabstand ändern, duplizieren, ausrichten.
  - Mehrfachauswahl mit Strg+Klick oder Rahmen; Kontextmenü und Eigenschaften in der rechten
    Seitenleiste.
  - Änderungen geschehen direkt im PDF und in der Originalschrift. Fehlen der Schrift Zeichen, wird
    der Text neu gesetzt. Nur wo beides nicht sicher geht, wird überlagert, und der Hinweis sagt das.
  - Alles andere auf der Seite bleibt an seinem Platz.
  - Seiten ohne Text melden „Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt.“

## Geändert

- PDF Reader: Seitenleisten neu geordnet.
  - Die Umschalter sitzen im Kopf der jeweiligen Leiste: links Seiten, Lesezeichen und Suchen,
    rechts Kommentare und Eigenschaften. Die Befehlsleiste enthält keine Seitenleisten-Umschalter
    mehr.
  - Eine geschlossene Leiste bleibt als schmaler Streifen mit ihren Symbolen und öffnet sich
    darüber wieder.
  - Beide Leisten haben eine feste Breite: Wechsel zwischen Seiten, Lesezeichen und Suchen ändern
    die Breite nicht mehr.
  - Alle Köpfe sind gleich aufgebaut, und leere Leisten (keine Lesezeichen, keine Kommentare, kein
    Objekt gewählt) zeigen einen ruhigen Hinweis.
  - Beim Öffnen und Schließen gleitet die Leiste kurz herein bzw. hinaus („Reduziert“: Überblenden,
    „Aus“: sofort). Die Seiten werden dabei nur einmal neu angeordnet, und eine ganz oben stehende
    Ansicht bleibt oben.
- PDF Reader: Bewegung nach dem Animationsprofil der App („Vollständig“, „Reduziert“, „Aus“).
  - Dokument-Tabs blenden ein und aus, die übrigen rücken nach, die Markierung des aktiven Tabs gleitet.
  - Ungespeichert zeigt ein Punkt, der weich ein- und ausblendet, statt „*“ im Namen.
  - Werkzeugmarkierung, Auswahl im Kopf der Seitenleisten und Kontextmenüs (Einblenden mit leichtem
    Wachsen) bewegen sich weich.
  - Seitenbilder, Miniaturen und Änderungen auf der Seite blenden kurz ein.
  - Zoom über Schaltflächen und Tastatur gleitet kurz.
  - Suchtreffer blenden ein, der aktuelle Treffer wird beim Wechsel kurz hervorgehoben.
  - Beim Ziehen in „Seiten organisieren“ zeigen Platzhalter die neue Stelle, eine Vorschau folgt dem
    Zeiger, die übrigen Seiten rücken weich nach. Gelöschte und eingefügte Seiten blenden aus bzw. ein.
  - Eine über die Ansicht gezogene PDF zeigt eine Ablagefläche, die weich ein- und ausblendet.
  - Die Fokusmarkierung von Formularfeldern blendet weich ein und aus.
  - Scrollen und Strg+Mausrad bleiben direkt.
- Seiten organisieren: Nach dem Verschieben bleiben die verschobenen Seiten an ihrer neuen Stelle gewählt.
- App-Navigation: Bei geöffnetem Dokument ist sie im Reader eingeklappt. Die Menüschaltfläche klappt
  sie vorübergehend aus, bis zum nächsten Dokument. Der eingeklappte Zustand zeigt zentrierte Symbole
  und den gewählten Bereich mit dezenter Akzentfläche.
- PDF Reader: Eine Textauswahl blendet keine eigene Aktionsleiste mehr ein. Kopieren, Markieren,
  Unterstreichen, Durchstreichen und Notiz stehen im Kontextmenü (Rechtsklick), Strg+C kopiert.
- „Ganze Seite“ passt beim Blättern in der seitenweisen Ansicht jede Seite neu ein. In der
  fortlaufenden Ansicht bleibt der Zoom beim Scrollen gleich.

## Behoben

- PDF Editor: Speichern schlug bei PDFs mit XMP-Metadaten (die meisten PDFs aus Office-Programmen,
  Acrobat oder Scannern) mit „Das Dokument konnte nicht geschrieben werden.“ fehl. Ursache: Beim
  Schreiben wollte pikepdf die PDF-Version in den XMP-Metadaten nachtragen und brauchte dafür lxml,
  das nicht zum Programm gehört. Die XMP-Metadaten bleiben jetzt beim Speichern unverändert. Davon
  betroffen waren auch die Sitzungssicherung für ungespeicherte Änderungen und „Eigenschaften“
  (meldete fälschlich beschädigte XMP-Metadaten) – beides funktioniert wieder, Titel, Autor, Thema
  und Stichwörter werden in Info und XMP gemeinsam geändert
- Speichern meldet Fehler verständlich und bietet „Speichern unter …“ direkt an: Datei
  schreibgeschützt, keine Schreibberechtigung am Speicherort, Datei in einem anderen Programm
  geöffnet (genau geprüft statt vermutet), Datenträger voll; technische Angaben stehen ohne Pfad
  und ohne Inhalte im Protokoll
- die gespeicherte Datei wird nach dem Ersetzen wie beim Öffnen nachgeprüft; erst dann gilt das
  Dokument als gespeichert (der Punkt für „ungespeichert“ verschwindet), bei einem Fehler bleibt es
  ungespeichert und Rückgängig bleibt möglich
- je Dokument läuft höchstens ein Speichervorgang: mehrfaches Strg+S schreibt die Datei einmal,
  „Speichern“ beim Schließen während eines laufenden Speicherns wartet darauf
- Speichern wartet nicht mehr auf eine laufende Suche (die Suche läuft danach weiter); Ansicht,
  Seite, Zoom, Seitenleisten und Tabs bleiben beim Speichern unverändert
- Werkzeugleiste: „Speichern …“ während des Speicherns, danach kurz „Gespeichert“ – ohne Dialog
- PDF Reader: „Ganze Seite“ konnte bei unterschiedlich großen Seiten (z. B. Hoch- und Querformat)
  beim Scrollen zwischen den Seiten hin- und herspringen.
- „Notiz hier hinzufügen“ aus dem Kontextmenü: Die Eingabe hatte bei eingeschalteten Animationen
  nicht sofort den Tastaturfokus.
- PDF Reader: Miniaturen zeigten beim schnellen Scrollen und beim Wechsel zwischen Dokumenten kurz
  das Bild einer anderen Seite bzw. des anderen Dokuments, bis das richtige Bild fertig war; in
  „Seiten organisieren“ beim schnellen Scrollen ebenso. Bis dahin steht jetzt das leere Blatt.
- Formular ausfüllen: Nach der Eingabetaste oder Escape blieb die Tastatur im ausgeblendeten
  Eingabefeld. Tastendrücke landeten dort, und die Markierung des Felds blieb stehen. Jetzt geht die
  Tastatur wie nach dem Textbearbeiten zurück an die Seite.

# PDF Tool 3.0.0-beta.1

Beta zum Testen (Kanal „Beta“). Neues Werkzeug „PDF Reader & Editor“.

## PDF Reader

- PDFs öffnen über „Öffnen“ (Strg+O), Ziehen in das Fenster, „Zuletzt geöffnet“ (leerbar) und
  „Öffnen mit“ im Explorer (läuft PDF Tool schon, öffnet sich die Datei dort als neuer Tab; PDF Tool
  wird dabei nicht zur Standard-App)
- Tabs mit „*“ bei ungespeicherten Änderungen; Schließen mit „Speichern“ / „Nicht speichern“ /
  „Abbrechen“; Strg+Tab, Strg+W
- scharfe Darstellung bei jeder Windows-Skalierung; Ansichten Einzelseite, fortlaufend, zwei Seiten,
  fortlaufend zweiseitig; Zoom 25–400 % in Stufen, frei mit Strg+Mausrad (um den Mauszeiger),
  Seitenbreite, ganze Seite, Originalgröße
- Miniaturen, Lesezeichen, Seitennavigation, Textauswahl und Kopieren, Suche (Strg+F, F3) mit
  Groß-/Kleinschreibung und ganzem Wort
- Drucken über den Druckdialog von Windows (Bereich, Kopien, Ausrichtung, Anpassung) und
  Druckvorschau; Seiten als PNG/JPEG exportieren; Eigenschaften und Metadaten
- große Dokumente (1000+ Seiten): nur sichtbare Seiten werden aufgebaut und gezeichnet,
  begrenzter Zwischenspeicher

## PDF Editor

- Text ändern mit ehrlich benanntem Weg: „Direkt im PDF geändert (Originalschrift)“, „Neu gesetzt
  (Originaltext entfernt)“ oder „Kompatibilitätsmodus“ (Überlagerung – keine Schwärzung); jede
  Änderung wird geprüft, sonst zurückgenommen; Text hinzufügen mit Schrift, Größe, Farbe
- Bilder auswählen, verschieben, Größe ändern, drehen, ersetzen, löschen, PNG/JPEG einfügen
- Seiten organisieren: Raster mit Mehrfachauswahl und Ziehen, drehen, löschen, duplizieren, leere
  Seite, aus PDF einfügen, PDFs anhängen, extrahieren, teilen
- Kommentare: markieren, unterstreichen, durchstreichen, Notiz, Freihand (auch als sichtbare
  Unterschrift), Rechteck, Ellipse, Linie, Pfeil, Textfeld; vorhandene Kommentare bleiben erhalten
- Formulare (AcroForm) ausfüllen; PDF-JavaScript wird nie ausgeführt
- Rückgängig/Wiederholen je Dokument (Strg+Z, Strg+Y)

## Sicher speichern

- Strg+S / Strg+Umschalt+S: Prüfung der neuen Datei vor dem Ersetzen, atomares Ersetzen, Sicherung
  des vorherigen Stands; bei einem Fehler bleibt das Original unverändert
- von außen geänderte Dateien werden nicht still überschrieben
- verschlüsselte PDFs: Passwort nur im Arbeitsspeicher, Berechtigungen werden beachtet;
  digital signierte PDFs: Warnung vor der ersten Änderung
- beschädigte PDFs: „PDF reparieren“ wird angeboten (nie automatisch)
- ungespeicherte Änderungen werden lokal gesichert und nach einem Absturz zum Wiederherstellen
  angeboten

## Weitere Änderungen

- Startseite: Werkzeug „PDF Reader & Editor“ (Strg+5); eine auf die Startseite gezogene PDF öffnet
  sich im Reader („PDF reparieren“ nimmt PDFs auf seiner eigenen Seite an)
- Diagnose nennt die Engines des Editors (pikepdf/qpdf, PDFium, fontTools)
- Laufzeit: fontTools 4.66.1 (MIT) für Schrift-Teilmengen, Qt Print Support für den Druck

# PDF Tool 2.8.0

Freigegebene Version – getestet als Beta 2.8.0-beta.1, Funktionsumfang unverändert.

## Vorlagen 2.0

- je Vorlage eine eigene Datei mit fester ID und Schema-Version (`vorlagen\`); Vorlagen bis 2.7
  werden beim ersten Start einmalig übernommen, die bisherige Liste bleibt unverändert
- neue Ansicht „Vorlagen“: suchen, ansehen, anwenden, laden und bearbeiten, umbenennen,
  duplizieren, Beschreibung, Standardvorlage, löschen (Verweise in Kundenakten, Stapel und
  Standardvorlage werden dabei kontrolliert gelöst)
- „Darstellung“: geladene Vorlage mit „Vorlage geändert“, „Vorlage aktualisieren“, „Als neue
  Vorlage speichern“ und „Änderungen verwerfen“; die Vorlage hält auch das Regelwerk fest
- Standardvorlage für jede neue Übersicht (rückgängig machbar) und als vierte Stufe im Stapel:
  Eintrag → Kundenakte → Vorlage des Stapels → Standardvorlage → Darstellung

## Regelwerk 2.0

- Regelwerke mit Regeln „WENN … DANN …“: Bedingungen für Text, Zahl (Netto) und Datum (Beginn),
  „alle“ oder „mindestens eine“; Aktionen setzen, ersetzen, voranstellen, anhängen, leeren für Art,
  Beschreibung, Abrechnungszyklus und Zahlungsart – keine Skripte, kein Code
- neue Ansicht „Regeln“: Regelkarten, visueller Editor, Reihenfolge, duplizieren, entfernen mit
  „Rückgängig“, ein- und ausschalten; automatisch gespeichert
- Testmodus („Trifft auf 7 von 18 Verträgen zu“) und Vorschau vorher → nachher mit Konflikten,
  im Hintergrund berechnet; „Übersicht erstellen“ nennt, was das Regelwerk ändert
- wirkt auf PDF, Vorschau, Stapel und Vertragsstand (gespeichert werden die exportierten Werte),
  nie auf die Excel-Datei; Stapel: Regelwerk je Eintrag

## Sicherung & Wiederherstellung

- Sicherung als `.pdtbackup` (ZIP mit Manifest und SHA-256 je Datei), atomar erstellt und geprüft
- „Jetzt sichern …“ in einen Ordner Ihrer Wahl; automatisch einmal täglich bei Änderungen und vor
  jedem Update; die letzten 10 automatischen bleiben, manuelle werden nie automatisch gelöscht
- Wiederherstellen: vollständige Prüfung, Zusammenfassung, Auswahl der Bereiche, Sicherung des
  aktuellen Stands, Ausführung beim Neustart – atomar mit Rückabwicklung; Sicherungen einer
  neueren Version werden nie eingespielt

## Diagnose

- Systeminformationen (Version, Kanal, Python, Qt, Windows, Pfade, Module, Reparatur-Engines)
- Datenprüfung ohne Änderungen (Einstellungen, Kundenakten, Vorlagen, Regelwerke, Vertragsstände,
  Sicherungsordner, temporärer Ordner, freier Speicher)
- Support-Paket (ZIP) mit Bericht und bereinigten Protokollen – ohne Kunden- oder Dokumentdaten
- Protokoll `pdf-tool.log` mit Rotation; eigene temporäre Dateien früherer Sitzungen werden
  aufgeräumt

## Weitere Änderungen

- Ansichtsleiste von „Vertragsübersichten“ verschiebbar, wenn die Breite nicht reicht
- Stapel: „Standardvorlage“ heißt jetzt „Vorlage des Stapels“ (die Standardvorlage gilt für alle)
- Speichern wiederholt kurz gesperrte Dateien (z. B. durch Virenscanner) statt abzubrechen
- Oberfläche: Schutz vor einem Absturz der QML-Engine (Qt 6.11) beim Laden der Ansichten im
  Hintergrund
- Release-Workflow: ein stabiles Release setzt eine veröffentlichte Beta derselben Version voraus

# PDF Tool 2.8.0-beta.1

Beta zum Testen (Kanal „Beta“) mit dem Umfang von 2.8.0 (siehe oben).

# PDF Tool 2.7.2

## In-App Updates

- PDF Tool kann jetzt direkt in der Anwendung nach Updates suchen
- Updates können direkt heruntergeladen werden
- Downloads werden per SHA-256 überprüft
- Installation erfolgt weiterhin sicher über das PDF-Tool-Setup

## Stable- und Beta-Kanal

- Stable bleibt der Standard
- Beta kann optional aktiviert werden
- Beta-Nutzer erhalten Vorabversionen zum Testen
- Stable-Nutzer erhalten ausschließlich freigegebene Releases

## Hintergrundprüfung

- automatische Updateprüfung
- blockiert den Programmstart nicht
- Offline-Betrieb bleibt vollständig möglich

## Korrekturen

- Eine Rückfrage direkt nach einem Dialog mit Inhalt (z. B. nach den Update-Details) übernahm
  dessen Höhe und zeigte eine große leere Fläche; sie ist jetzt so hoch wie ihr Text.

# PDF Tool 2.7.1

## PDF reparieren: mehrere PDFs

- mehrere PDFs gleichzeitig reparieren
- Multi-File Drag & Drop
- Batch-Reparatur
- individuelle Ausgabedateinamen
- optionales "_repariert" im Dateinamen
- sichere automatische Konfliktauflösung
- Fortschritt und Ergebnis pro PDF
- Batch-Ergebnisübersicht

Im Einzelnen: Mehrfachauswahl im Dialog, mehrere Dateien zugleich ablegen, später weitere
hinzufügen; dieselbe Datei nur einmal, andere Dateien mit Hinweis. Jede PDF wird für sich
analysiert (höchstens zwei Arbeitsprozesse) und nacheinander mit der unveränderten Engine aus
2.7.0 repariert – keine eigene Batch-Engine. Zustand je Datei, Gesamtstand („8 PDFs · 6
reparierbar · 1 verschlüsselt · 1 nicht wiederherstellbar“), „Alle reparieren“, „Nur diese Datei
reparieren“, „Abbrechen“ (fertige Dateien bleiben), „Fehlgeschlagene erneut versuchen“,
Zusammenfassung mit „Ausgabeordner öffnen“. Passwörter gelten nur für ihre Datei; signierte
Dateien lassen sich auf Rückfrage überspringen; der Rettungsmodus gilt nur für eine Datei und nur
nach Bestätigung. Mit einer PDF bleibt der Ablauf wie in 2.7.0.

Dateinamen: Schalter „„repariert“ an Dateinamen anhängen“ (Standard ein, auch nach dem Update)
mit änderbarem Zusatz; eigener Name je Datei mit sofortiger Prüfung auf unter Windows ungültige
Namen. Ein Name, den es schon gibt – ohne Rücksicht auf Groß-/Kleinschreibung, das Original selbst
oder schon für eine andere Datei der Liste geplant –, wird nummeriert: `Rechnung_repariert (1).pdf`
statt bisher `Rechnung_repariert_2.pdf`. Die Namen werden beim Start reserviert; eine vorhandene
Datei wird nie überschrieben, das Original nie verändert, umbenannt oder gelöscht.

## Korrekturen

- Listen-Seiten (PDF reparieren, Stapel, Kunden, Vertragsvergleich) bleiben oben, wenn sich der
  Kopfbereich ändert (Hinweis, aufklappender Bereich, erste Datei) – der Seitentitel rutschte
  vorher aus dem Bild. Wer zu den Zeilen gescrollt hat, behält sie im Blick.

## Tests

- `tests/test_pdf_repair_batch.py`: Liste, Zustände, Namensregel, Windows-Namen, Konflikte,
  Nummerierung, Reservierung.
- `tests/test_qt_repair.py`: alle Abläufe aus 2.7.0 mit einer PDF sowie 10 gemischte PDFs,
  Abbrechen bei Datei 4 von 10, Passwort nur je Datei, Signaturen überspringen, kein stiller
  Rettungsmodus, Fehlgeschlagene erneut, globaler Schreibfehler, 100 PDFs, Animationsprofile,
  Schalter aus/an, eigener Name, gleiche Namen aus verschiedenen Ordnern, Neustart.
- Datenmigration: Einstellungen von 2.7.0 (`config_v270.json`).

# PDF Tool 2.7.0

## Neue Oberfläche

PDF Tool wurde vollständig auf PySide6 und Qt Quick/QML umgestellt. Die Fachlogik ist unverändert;
QObject-Controller je Bereich verbinden sie mit der QML-Oberfläche. Die produktive App enthält kein
Tkinter mehr, die Laufzeit kein Tcl/Tk.

## Modernes Design

Komplett überarbeitete Windows-11-orientierte Oberfläche mit zentralem Design-System (Farben,
Abstände, Radien, Schrift, Animationsdauern); Hell/Dunkel/„Wie Windows“ und Akzentfarbe wirken
sofort.

## Animationen

Neue Animationen für:

- Navigation
- Menüs
- Dialoge
- Accordions
- InfoBars
- Buttons
- Toggle Switches
- Statuswechsel

Einstellbar: Vollständig, Reduziert, Aus (Windows „Animationseffekte aus“ → mindestens Reduziert).

## Performance

Neue Model/View-Architektur und effizienteres Rendering: Listen melden nur geänderte Zeilen,
virtualisierte Listen für Stapel, Kunden und Vertragsänderungen, Seiten entstehen einmal,
Hintergrundarbeit ohne blockierte Oberfläche.

## High DPI

Verbesserte Darstellung auf hochauflösenden Displays (100–200 %), Symbole als Vektorgrafik.

## Bestehende Funktionen

Alle Funktionen aus 2.6.1 wurden übernommen. Keine manuelle Migration: Einstellungen, Kunden,
Vorlagen, Regeln und Vertragsstände werden weiterverwendet.

## Korrekturen und Qualitätssicherung

- RichText-Kopf-/Fußzeilenintegration für Qt/QML korrigiert
  – gespeicherte Kopf- und Fußzeilen erscheinen wieder vollständig im Editor (das Textfeld blieb
  eine Zeile hoch und zeigte nichts an), Klicken, Markieren mit der Maus und Scrollen funktionieren
  in jeder Zeile, Umschalt+Eingabe beginnt wieder einen Absatz; der Inhalt wird nach jeder Änderung
  sofort ins Python-Modell übernommen (gespeichert wird weiterhin verzögert), »Kopfzeile speichern«
  und »Fußzeile speichern« aktualisieren die Vorschau. Dasselbe gilt für das Notizfeld der Kundenakte.
- Einfügemarke in Kopf- und Fußzeile an Schrift und Grundlinie ausgerichtet
  – so hoch wie die Schrift am Cursor (Ober- plus Unterlänge, geprüft mit 8 bis 24 pt), auf der Grundlinie der
  Zeile, in ganzen Gerätepixeln (100 bis 200 % gleich schmal und scharf); im leeren Feld nicht mehr
  10 px hoch oben links, sondern dort, wo der Text entsteht – auch zentriert. Der Platzhalter steht in
  derselben Schrift und Ausrichtung wie der spätere Text. Sichtbar nur mit Textfokus; die
  Formatleiste zeigt in einer Leerzeile deren eigenes Format.
- Startseite visuell symmetrisch überarbeitet
  – beide Werkzeugkarten exakt gleich breit und hoch, gleicher Innenaufbau, »Öffnen« und
  Tastenkürzel auf einer Linie, Gruppe mittig mit gleichem Abstand links und rechts, Titel und
  Datenschutzhinweis an der Kante der Karten, unter 736 px Gruppenbreite eine Spalte.
- Installer-/Upgrade-Tests deutlich effizienter gestaltet
  – ältere Einstellungen (2.2.0 bis 2.6.1) prüfen schnelle Migrationstests mit Fixtures statt
  alter Setups; die vollständige historische Prüfung gibt es nur noch als manuellen Workflow
  »Deep Compatibility Test«.
- normaler Upgrade-Test beschränkt sich auf vorherige stabile Version → aktuelle Version
  – für 2.7.0: Clean Install 2.7.0 und Update 2.6.1 → 2.7.0; die Vorversion wird nach SemVer
  aus den veröffentlichten Releases bestimmt und ihr Setup zwischengespeichert, nie neu gebaut.

# PDF Tool 2.6.1

Qualitäts-Update: flüssigere Oberfläche, optimiertes Rendering, optionale Kundenakte (Standard aus).
Siehe [`release-notes/2.6.1.md`](release-notes/2.6.1.md).

# PDF Tool 2.6.0

Vertragsvergleich mit gespeicherten Vertragsständen, erweiterte PDF-Wiederherstellung.
Siehe [`release-notes/2.6.0.md`](release-notes/2.6.0.md).

# PDF Tool 2.5.0

Stapelverarbeitung, kompakte Excel-Karte. Siehe [`release-notes/2.5.0.md`](release-notes/2.5.0.md).

# PDF Tool 2.4.0

Kundenakte mit Wiedererkennung, Ansicht „Kunden“, Live-Vorschau.
Siehe [`release-notes/2.4.0.md`](release-notes/2.4.0.md).

# PDF Tool 2.3.0

Neuer Name „PDF Tool“, Werkzeug „PDF reparieren“. Siehe [`release-notes/2.3.0.md`](release-notes/2.3.0.md).

# Übersichten-Ersteller 2.2.0

Excel-Fettschrift, formatierte Kopf- und Fußzeilen. Siehe [`release-notes/2.2.0.md`](release-notes/2.2.0.md).
