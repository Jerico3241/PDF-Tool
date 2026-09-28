"""Werkzeug »PDF reparieren«: beschädigte PDF-Dateien analysieren und lesbare Inhalte in eine neue PDF übertragen.

* ``models``  – Statusklassen, Analyse- und Ergebnismodell (ohne Abhängigkeiten)
* ``engine``  – Analyse und Reparatur mit qpdf (pikepdf) und PDFium (pypdfium2)
* ``process`` – Ausführung in einem eigenen Prozess (abbrechbar), Übernahme der Ausgabe
* ``page``    – Oberfläche und Ablauf des Werkzeugs
"""
