"""Werkzeug »Vertragsübersichten«: aus einer Excel-Vertragsliste eine PDF-Übersicht erstellen.

* ``controller``  – Ablauf des Werkzeugs (Excel laden, Analyse, PDF erzeugen, Vorlagen, Verlauf)
* ``customer_flow`` – Kundenakte 2.0: Wiedererkennung, Übernahme, Arbeitskopie, bewusstes Speichern
* ``customers/`` – Datenmodell, E-Mail-Abgleich, lokaler Speicher und Übernahme der alten Historie
* ``preview``  – Live-Vorschau (Erzeugung im Hintergrund, Revisionsschutz)
* ``page_create`` – Ansicht »Übersicht erstellen«
* ``page_layout`` – Ansicht »Darstellung« (Vorlagen, Layout, Kopf- und Fußzeile)
* ``page_preview`` – Ansicht »Vorschau« (Seiten, Zoom)
* ``page_customers`` – Ansicht »Kunden« (Kundenakten suchen, bearbeiten, zusammenführen)

Die fachliche Logik liegt unverändert in den Modulen ``engine`` (Excel-Auswertung,
Zyklus-Regeln, PDF-Aufbau), ``excelstyle``, ``richtext``, ``pdffonts`` und ``appstate``.
"""
