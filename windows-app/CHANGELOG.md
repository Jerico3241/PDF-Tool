# Changelog

Ausführliche Hinweise je Version: [`release-notes/`](release-notes/).

# PDF Tool 2.8.0-beta.1

Beta zum Testen (Kanal „Beta“). Die stabile Version 2.8.0 folgt erst nach Test und Freigabe.

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
