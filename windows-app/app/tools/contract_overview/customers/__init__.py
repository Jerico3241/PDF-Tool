"""Kundenakte 2.0 des Werkzeugs »Vertragsübersichten« – ohne Oberfläche.

* ``models``     – Datenmodell (stabile ID, Stammdaten, Rechnungsempfänger, Einstellungen)
* ``matching``   – Normalisierung und Wiedererkennung von Rechnungsempfänger-E-Mails
* ``repository`` – lokaler Speicher (JSON mit Schema-Version, atomar geschrieben)
* ``migration``  – Übernahme der Kundenhistorie bis Version 2.3

Die Zuordnung E-Mail → Kunde entsteht ausschließlich aus Daten, die der Benutzer
selbst gespeichert hat. Aus einer E-Mail-Adresse oder Domain wird nie ein
Firmenname oder eine Kundennummer abgeleitet; es gibt keine externen Abfragen.
"""
