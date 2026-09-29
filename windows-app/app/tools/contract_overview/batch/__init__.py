"""Stapelverarbeitung in »Vertragsübersichten«: mehrere Excel-Listen prüfen und gesammelt als PDF erstellen.

* ``models``   – Datenmodell: Eintrag (``BatchItem``), Status, eigene Angaben, Einstellungen
* ``analyzer`` – Voranalyse im Hintergrund mit Sitzungs-Cache (dieselbe Excel-Prüfung wie einzeln)
* ``resolver`` – welche Werte gelten (Eintrag → Kundenakte → Stapel → Standard) und was fehlt
* ``processor`` – Verarbeitung nacheinander mit derselben PDF-Engine, Abbruch, Protokoll
* ``flow``     – Ablauf im Hauptfenster (Baustein der App)
* ``page``/``widgets`` – Ansicht »Stapel«

Nichts davon hat eine eigene Fachlogik für Excel, Kundenerkennung, Rich Text oder PDF: Der
Stapel verwendet ``overview``, ``customers`` und ``engine`` wie der Einzelmodus.
"""
