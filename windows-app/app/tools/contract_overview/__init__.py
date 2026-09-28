"""Werkzeug »Vertragsübersichten«: aus einer Excel-Vertragsliste eine PDF-Übersicht erstellen.

* ``controller``  – Ablauf des Werkzeugs (Excel laden, Analyse, PDF erzeugen, Vorlagen, Verlauf)
* ``page_create`` – Seite »Übersicht erstellen«
* ``page_layout`` – Seite »Darstellung« (Vorlagen, Layout, Kopf- und Fußzeile)

Die fachliche Logik liegt unverändert in den Modulen ``engine`` (Excel-Auswertung,
Zyklus-Regeln, PDF-Aufbau), ``excelstyle``, ``richtext``, ``pdffonts`` und ``appstate``.
"""
