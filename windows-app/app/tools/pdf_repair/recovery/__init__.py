"""Erweiterte Wiederherstellung für »PDF reparieren«.

Greift, wenn qpdf und PDFium eine Datei nicht (vollständig) öffnen können:

* ``lenient`` – dritte, tolerante Engine (pypdf, ``strict=False``)
* ``scanner`` – Rohanalyse: Objekte, Datenströme, Trailer, Querverweise und Dateiende
  direkt in den Bytes (defensiv, speichersparend über ``mmap``)
* ``rebuild`` – neue Querverweistabelle, Trailer, ``startxref`` und ``%%EOF``; bei Bedarf
  ein neuer Seitenbaum mit übernommenen geerbten Seiteneigenschaften

Jeder Kandidat wird anschließend mit qpdf normalisiert und wie jede Ausgabe hart geprüft.
Verschlüsselte Dateien werden nie ohne gültiges Passwort und vollständige
Verschlüsselungsdaten rekonstruiert.
"""
