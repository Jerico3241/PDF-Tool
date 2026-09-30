# Changelog

Ausführliche Hinweise je Version: [`release-notes/`](release-notes/).

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
