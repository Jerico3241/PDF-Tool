"""Sicherung und Wiederherstellung der Benutzerdaten von PDF Tool – vollständig lokal.

Eine Sicherung ist eine ZIP-Datei mit der Endung ``.pdtbackup``:

* ``manifest.json`` – Format und Formatversion, App-Version, Zeitpunkt, Art (manuell,
  automatisch, vor einem Update, vor einer Wiederherstellung), Bereiche und je Datei Pfad,
  Größe und SHA-256.
* ``data/…`` – die Dateien der Bereiche, genau wie im Datenordner.

Gesichert werden nur Daten von PDF Tool (``archive.AREAS``): Einstellungen samt Darstellung,
Textbausteinen und Zyklus-Regeln, der Stapel, Kundenakten mit Vertragsständen, Vorlagen und
Regelwerke. Nie: Excel- oder PDF-Dateien, Logos, Protokolle oder andere Sicherungen.

* ``archive``: Bereiche, Sicherung erstellen (atomar) und prüfen.
* ``restore``: Wiederherstellung vorbereiten und beim nächsten Start ausführen – atomar je
  Bereich, mit Rückabwicklung bei jedem Fehler und nach einem Abbruch.
* ``policy``: automatische Sicherungen (höchstens einmal am Tag, nur bei Änderungen),
  Aufbewahrung (manuelle Sicherungen werden nie gelöscht) und Status.
"""
