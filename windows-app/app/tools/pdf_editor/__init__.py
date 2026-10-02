"""PDF Reader & Editor (ab 3.0): PDFs öffnen, lesen, durchsuchen, bearbeiten und speichern.

Aufbau (Einzelheiten: ``docs/PDF-EDITOR.md``):

* ``document`` – ein geöffnetes PDF. **pikepdf (qpdf) hält den Stand der Bearbeitung**: Was
  nicht bearbeitet wird, bleibt beim Speichern unverändert erhalten (Lesezeichen, Links,
  Anmerkungen, Formulare, Metadaten, Anhänge, Ebenen …). **PDFium** zeigt den jeweiligen Stand an
  und liefert Geometrie, Text und Schriften; nach einer Änderung wird es aus dem pikepdf-Stand neu
  geladen.
* ``render``, ``textlayer``, ``search``, ``outline`` – Lesen: Seitenbilder, Text mit Zeichen-
  positionen, Auswahl, Suche, Gliederung.
* ``commands`` – Rückgängig/Wiederholen: Jede Änderung merkt sich die Einträge der betroffenen
  Seiten bzw. des Dokuments vor und nach der Änderung (Verweise, keine Kopien großer Daten).
  Bestehende Inhaltsströme werden nie verändert, sondern ersetzt.
* ``content``, ``fonts``, ``textedit`` – Text bearbeiten: **nativ** (Textoperator im Inhalts-
  strom mit der Originalschrift geändert), **rekonstruiert** (Originaltext entfernt, neu gesetzt –
  etwa mit Ersatzschrift) oder **Überlagerung** (Original bleibt verdeckt in der Datei). Die
  Engine wählt den sicheren Weg und meldet ihn ehrlich; eine Überlagerung ist nie eine Schwärzung.
* ``images``, ``pages``, ``annotations``, ``forms``, ``metadata`` – weitere Bearbeitung.
* ``save`` – atomar speichern: temporäre Datei → prüfen → ersetzen; bei einem Fehler bleibt das
  Original unverändert. ``recovery`` – Sitzungssicherung für den Fall eines Absturzes.

Kein Code hier kennt die Oberfläche (Qt/QML); die Controller stehen in ``qtapp/reader``.
"""
