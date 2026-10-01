"""Diagnose von PDF Tool – lokal, ohne Netzwerk, ohne Inhalte von Dokumenten.

* ``info``: Systeminformationen (Version, Kanal, Python, Qt, Windows, Pfade, Module, Engines).
* ``checks``: Datenprüfung (Einstellungen, Kundenakten, Vorlagen, Regelwerke, Vertragsstände,
  Sicherungsordner, temporärer Ordner, freier Speicher).
* ``sanitize``: Texte für das Support-Paket entschärfen (Benutzerordner, Benutzer- und
  Computername, Pfade zu Dokumenten, E-Mail-Adressen).
* ``support``: Support-Paket (ZIP) mit Bericht, Versionen, anonymisierten Einstellungen und
  bereinigten Protokollen. Nie: Kundendaten, Vertragsinhalte, Passwörter, PDF- oder
  Excel-Inhalte, Logos oder andere Dokumentdaten.
* ``applog``: Protokoll der App (INFO, WARNING, ERROR) mit Rotation.
* ``cleanup``: eigene temporäre Dateien früherer Sitzungen entfernen – nie fremde.
"""
