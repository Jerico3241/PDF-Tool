"""Updates in der App: prüfen, herunterladen, verifizieren und das Setup starten.

Quelle sind ausschließlich die Releases des offiziellen Repositories (GitHub, über die feste
Repository-ID – unabhängig von einer späteren Umbenennung). Die Oberfläche (``qtapp.updates``,
QML) zeigt nur Zustand, Texte und Fortschritt; alle Entscheidungen fallen hier:

* ``semver`` – Versionen nach Semantic Versioning 2.0.0, nie als Text verglichen
* ``models`` – Kanal (Stable/Beta), Zustand, Fehlerarten, Release und Assets
* ``github`` – Releases einlesen, Kanal filtern (keine Entwürfe, Stable nie Vorabversionen),
  Assets nach fester Namenskonvention wählen, neuestes Update bestimmen (nie ein Downgrade)
* ``policy`` – erlaubte Adressen: nur HTTPS, nur GitHub; Weiterleitungen nur dorthin
* ``verifier`` – Prüfsummendatei lesen, SHA-256 berechnen und vergleichen
* ``state`` – Zustandsautomat (IDLE … READY, INSTALLING, CANCELLED, ERROR)
* ``schedule`` – automatische Prüfung höchstens alle 24 Stunden
* ``store`` – Download-Ordner, Zwischenspeicher, Aufräumen (nur eigene Dateien)
* ``notes`` – Release Notes (Markdown) sicher als einfache Blöcke aufbereiten
* ``transport`` – HTTPS-Abrufe mit Zeitlimits, Größenlimits und geprüften Weiterleitungen (Qt)
* ``service`` – Ablauf: prüfen → herunterladen → verifizieren → bereit (Qt, asynchron)
* ``installer`` und ``launch`` – Setup erst nach dem Beenden der App starten: ein kleiner
  Hilfsprozess wartet auf das Ende der App, prüft die Datei erneut und startet das Setup

Installiert wird ausschließlich über das Inno-Setup – die App ersetzt nie eigene Dateien.
"""
