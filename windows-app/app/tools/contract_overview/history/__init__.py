"""Vertragsvergleich: gespeicherte Vertragsstände je Kundenakte und ihr Vergleich.

* ``models`` – Vertrag (roh und wie in der PDF), Vertragsstand, Vergleichsergebnis, Normalisierung
* ``compare`` – neu, entfernt, geändert, unverändert mit den geänderten Feldern
* ``repository`` – Ablage je Kunde als JSON (atomar, versioniert, ohne doppelte Stände)
* ``report`` – Texte für Anzeige und »Änderungen kopieren«

Verglichen werden ausschließlich strukturierte Daten, die PDF Tool beim Erstellen
einer Übersicht gespeichert hat – nie Inhalte erzeugter PDF-Dateien.
"""
