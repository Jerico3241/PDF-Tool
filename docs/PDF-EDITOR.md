# PDF Reader & Editor – technische Beschreibung

Werkzeug »PDF Reader & Editor« (seit 3.0.0): PDFs lesen, bearbeiten, organisieren und
kommentieren – vollständig lokal. Kurzfassung für Anwender: [README](../README.md) und
[Release Notes](../windows-app/release-notes/).

## Aufbau

| Teil | Aufgabe | Code |
| --- | --- | --- |
| Engine (ohne Oberfläche) | Dokument, Darstellung, Textschicht, Suche, Gliederung, Text bearbeiten, Bilder, Seiten, Anmerkungen, Formulare, Metadaten, Bildexport, Rückgängig, Speichern, Sitzungssicherung | `windows-app/app/tools/pdf_editor/` |
| Arbeitsthread | ein Thread für alle Zugriffe auf geöffnete Dokumente; Aufträge mit Priorität (Bearbeiten/Öffnen/Speichern vor sichtbaren Seiten vor Miniaturen vor Suche), Seitenbilder abbrechbar | `app/qtapp/reader/engine.py` |
| Controller | Tabs, Öffnen (Dialog, Ziehen, »Zuletzt geöffnet«, »Öffnen mit«), Ansicht, Werkzeuge, Dialoge | `app/qtapp/reader/controller.py`, `document.py`, `session.py`, `printing.py` |
| Oberfläche | Seitenansicht (virtualisiert), Tabs, Befehls- und Werkzeugleiste, Miniaturen, Lesezeichen, Suche, Kommentare, »Seiten organisieren« | `app/qml/PdfTool/Reader/` |
| »Öffnen mit« | zweiter Start reicht PDF-Pfade an die laufende App weiter (lokale Verbindung, nur für diesen Benutzer) | `app/qtapp/instance.py`, `installer/PDF-Tool.iss` (`[Registry]`) |

**Quelle der Wahrheit ist pikepdf (qpdf):** Jede Änderung geschieht in der Objektstruktur des
Dokuments. **PDFium** (pypdfium2) zeichnet die Seiten, liefert Zeichen, Positionen und Glyphen und
prüft Änderungen. Beide greifen nur unter einer gemeinsamen Sperre (`pdfium_lock.PDFIUM_LOCK`) und
nur aus dem Arbeitsthread auf ein Dokument zu.

## Ansicht und Leistung

- Nur sichtbare Seiten (plus eine halbe Bildschirmhöhe Vorlauf) existieren als Elemente; sie werden
  wiederverwendet. Die Lage jeder Seite ergibt sich exakt aus den Seitengrößen – auch bei 1000+
  Seiten mit unterschiedlichen Formaten.
- Seitenbilder kommen asynchron über `image://pdfpage/…` in Gerätepixeln (scharf bei jeder
  Windows-Skalierung). Das vorige Bild bleibt stehen, bis das neue fertig ist (kein Flackern beim
  Zoomen oder nach Änderungen). Ein ganzes Seitenbild hat höchstens 16 Mio. Pixel; darüber wird
  zusätzlich der sichtbare Ausschnitt in voller Schärfe gezeichnet.
- Zwischenspeicher der Seitenbilder: höchstens 320 MB, zuletzt benutzte bleiben.
- Aufträge, deren Seite aus dem Bild gescrollt ist, werden abgebrochen; die Suche läuft Seite für
  Seite im Hintergrund und zeigt Treffer sofort.

Messwerte vom 02.10.2026 (Linux-Testrechner, 4 Kerne, Python 3.13.15; künstliche Dokumente mit
Text und Fläche je Seite aus `tests/editorsamples.py`; Median aus drei Läufen). Unter Windows auf
einem Arbeitsplatzrechner sind andere Werte zu erwarten – die Größenordnung zeigt, dass die
Dauer von Darstellung und Bearbeitung kaum von der Seitenzahl abhängt.

Engine (`windows-app/tests/bench_editor.py`):

| Seiten | Öffnen | 1. Seite (1190 px) | Miniatur (je) | Zeichentabelle | Suche (alle Seiten) | Text ändern | Speichern + Prüfung | Datei vorher → nachher |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0 ms | 10 ms | 0,4 ms | 0,5 ms | 0 ms | 26 ms | 2 ms | 1 → 1 KB |
| 10 | 1 ms | 10 ms | 0,3 ms | 0,5 ms | 1 ms | 27 ms | 4 ms | 4 → 4 KB |
| 100 | 2 ms | 11 ms | 0,2 ms | 0,5 ms | 8 ms | 30 ms | 16 ms | 34 → 34 KB |
| 500 | 11 ms | 14 ms | 0,3 ms | 0,7 ms | 42 ms | 43 ms | 64 ms | 172 → 172 KB |
| 1000 | 21 ms | 13 ms | 0,3 ms | 0,5 ms | 88 ms | 56 ms | 74 ms | 348 → 348 KB |

Höchster Arbeitsspeicher des Messprozesses (alle fünf Größen nacheinander): 83 MB. Die Datei wird
durch Bearbeiten und Speichern nicht größer (keine angehängten Altstände).

App mit Oberfläche (Qt offscreen, Fenster 1180 × 860, Seitenbreite):

| Seiten | Öffnen bis erste Seite scharf sichtbar | Sprung zur letzten Seite (Bild da) | Seitenbilder im Speicher |
| ---: | ---: | ---: | ---: |
| 1 | 75 ms | 4 ms | 2,7 MB |
| 10 | 58 ms | 26 ms | 11,1 MB |
| 100 | 40 ms | 16 ms | 11,1 MB |
| 500 | 123 ms | 27 ms | 11,1 MB |
| 1000 | 228 ms | 41 ms | 11,1 MB |

## Text bearbeiten – drei ehrlich benannte Wege

Jede Textänderung nennt danach ihren Weg:

| Weg | Anzeige | Was passiert |
| --- | --- | --- |
| `NATIVE` | »Direkt im PDF geändert (Originalschrift)« | Die Textoperatoren im Inhaltsstrom werden ersetzt; die Originalschrift kodiert alle neuen Zeichen. Der alte Text ist entfernt. |
| `RECONSTRUCTED` | »Neu gesetzt (Originaltext entfernt)« | Der alte Text wird aus dem Inhaltsstrom entfernt und mit einer passenden Schrift neu gesetzt (Originalschrift, lokale Schrift oder Ersatzschrift). |
| `OVERLAY` | »Kompatibilitätsmodus: Originaltext überdeckt – er bleibt in der Datei enthalten (keine Schwärzung)« | Nur wenn die anderen Wege nicht sicher möglich sind: ein deckendes Rechteck und der neue Text darüber. **Eine Überlagerung ist keine Schwärzung** – der Originaltext bleibt in der Datei. |

Jede Änderung wird vor der Übernahme geprüft: Darstellung außerhalb des erlaubten Bereichs
unverändert (Vergleich der gerenderten Seite), neuer Text lesbar (Textschicht), alter Text entfernt
(außer bei der Überlagerung). Scheitert die Prüfung, wird die Änderung vollständig zurückgenommen
und der nächste Weg versucht – nie entstehen kaputte Glyphen.

**Schriften:** zuerst die Originalschrift, dann eine passende lokale Schrift, dann eine
Ersatzschrift (Standardschriften Helvetica/Times/Courier). Lokale Schriften werden nur als
Teilmenge eingebettet und nur, wenn ihre Lizenz es erlaubt (OS/2 `fsType`). Schriften werden nie
aus PDFs extrahiert oder weitergegeben. Passt ein längerer Text nicht in den Bereich, fragt PDF Tool:
»Zeilen anfügen« oder »Schrift verkleinern«.

## Bilder, Seiten, Anmerkungen, Formulare

- **Bilder:** auswählen, verschieben, Größe ändern (Seitenverhältnis bleibt, Umschalt: frei),
  drehen, löschen, ersetzen, PNG/JPEG mit Transparenz einfügen, Reihenfolge (Vorder-/Hintergrund)
  für neu eingefügte Bilder. Bilder in Formular-XObjects und Inline-Bilder werden angezeigt, aber nur
  geändert, wo das sicher möglich ist (sonst mit Begründung).
- **Seiten:** Raster »Seiten organisieren« mit Mehrfachauswahl und Ziehen; drehen, löschen,
  duplizieren, leere Seite, Seiten aus einer anderen PDF einfügen, PDFs anhängen, als neue PDF
  speichern (extrahieren), teilen (alle n Seiten oder Bereiche), als PNG/JPEG exportieren.
  Lesezeichen, Links, Sprungziele und Formularfelder gelöschter Seiten werden mit aufgeräumt.
- **Anmerkungen:** markieren, unterstreichen, durchstreichen, Notiz, Freihand (auch als sichtbare
  Unterschrift), Rechteck, Ellipse, Linie, Pfeil, Textfeld; Farbe und Strichstärke; verschieben,
  Text und Farbe ändern, löschen. Vorhandene Anmerkungen anderer Programme bleiben unverändert,
  solange sie nicht ausdrücklich geändert werden.
- **Formulare (AcroForm):** Text-, Kontroll-, Options-, Auswahl- und Listenfelder ausfüllen; das
  Erscheinungsbild wird neu erzeugt, damit der Wert in jedem Programm gleich aussieht.
  Schreibgeschützte, Passwort- und Signaturfelder werden nicht geändert; bei XFA wird nur der
  AcroForm-Teil bearbeitet. **PDF-JavaScript wird nie ausgeführt** (auch keine Berechnungen).

## Rückgängig und Wiederholen

Je Dokument eine Befehlsliste (`tools/pdf_editor/commands.py`). Gespeichert werden nur die vor der
Änderung betroffenen Objekte (Memento je Objekt, nicht das ganze Dokument); die Liste hält
höchstens 100 Schritte – älteste Schritte entfallen zuerst.

## Speichern – sicher oder gar nicht

`tools/pdf_editor/save.py`, Strg+S bzw. Strg+Umschalt+S:

1. Wurde die Datei seit dem Öffnen von einem anderen Programm verändert, wird sie nicht
   überschrieben – PDF Tool fragt (»Überschreiben« / »Speichern unter …« / »Abbrechen«).
2. Der Stand wird serialisiert (qpdf, komprimiert, keine Vergrößerung durch Altlasten:
   nicht mehr benutzte eigene Schriften werden entfernt). Eine vorhandene Verschlüsselung bleibt
   samt Berechtigungen erhalten.
3. **Prüfung vor dem Ersetzen:** mit pikepdf und PDFium neu öffnen, Seitenzahl, Darstellbarkeit der
   Seiten und Erhalt der Struktur (Lesezeichen, Links, Anmerkungen, Formularfelder, Anhänge,
   Metadaten, Ebenen, Sprungziele) mit dem Stand im Speicher vergleichen.
4. Temporäre Datei im Zielordner schreiben, auf den Datenträger zwingen, zurücklesen, vergleichen.
5. Vor dem Überschreiben des Originals eine Sicherung des vorherigen Stands anlegen
   (`%LOCALAPPDATA%\PDF-Tool-Editor\Sicherungen`, je Datei die letzten 3, höchstens 7 Tage).
6. Atomar ersetzen. Schlägt ein Schritt fehl, bleibt das Original unverändert.

## Sitzungssicherung (Absturz)

Solange ein Dokument ungespeicherte Änderungen hat, sichert PDF Tool den Stand wenige Sekunden
nach jeder Änderung lokal (`%LOCALAPPDATA%\PDF-Tool-Editor\Sitzungen`). Jede Sitzung hält eine Sperrdatei; nach einem
Absturz erkennt der nächste Start verwaiste Sitzungen und fragt: »Eine nicht gespeicherte Bearbeitung
wurde gefunden.« – **Wiederherstellen** / **Verwerfen** / **Später**. Wiederhergestellt wird ein
ungespeicherter Stand; die Originaldatei bleibt unverändert, bis gespeichert wird. Verschlüsselte
PDFs bleiben auch in der Sicherung verschlüsselt (das Passwort wird nie gespeichert).

## Sicherheit und Datenschutz

- Alles lokal: keine Uploads, keine Telemetrie, keine Cloud.
- Passwörter verschlüsselter PDFs nur im Arbeitsspeicher – nie in Einstellungen, Protokoll,
  Sitzungssicherung oder Support-Paket. Berechtigungen des PDFs (Bearbeiten, Kommentieren,
  Ausfüllen, Zusammenstellen, Drucken, Kopieren) werden beachtet; nichts wird umgangen.
- Digital signierte PDFs werden erkannt; vor der ersten Änderung fragt PDF Tool, weil jede
  Änderung die Signatur ungültig macht.
- Beschädigte PDFs: PDF Tool bietet »PDF reparieren« an; die reparierte Datei lässt sich danach im
  Reader öffnen. Repariert wird nie automatisch, das Original bleibt unverändert.
- Protokolle enthalten keine Texte aus PDFs; »Zuletzt geöffnet« enthält nur Pfade und lässt sich
  leeren.

## Tests

- Engine: `tests/test_editor_*.py` (Kern, Text, Seiten, Bilder, Anmerkungen, Formulare,
  Eigenschaften) mit künstlichen PDFs aus `tests/editorsamples.py`.
- Oberfläche: `tests/test_qt_reader.py` – Maus und Tastatur wie von Hand (Auswahl, Zoom mit
  Strg+Mausrad, Text ändern, Zeichnen, Bilder, Formulare, Seiten organisieren, Speichern, Passwort,
  beschädigte und signierte PDFs, »Öffnen mit«, Sitzungssicherung, Datenschutz).
- Laufzeit und Setup: `tests/smoke_runtime.py` (Text direkt ändern, Schrift-Teilmenge einbetten,
  speichern) und `tests/smoke_installer.ps1` (»Öffnen mit«, zweiter Start reicht die PDF weiter,
  Standard-App für PDF unverändert, Deinstallation entfernt die Einträge).

## Bekannte Einschränkungen (3.0.0-beta.1)

- Textauswahl innerhalb einer Seite (nicht über Seitengrenzen hinweg).
- Keine Schwärzung: Eine echte Schwärzung (Entfernen von Text, Bildern und Vektoren eines
  Bereichs) ist nicht enthalten. Die Überlagerung ist ausdrücklich keine Schwärzung.
- Digitale Signaturen werden erkannt, aber nicht erstellt; eine sichtbare Unterschrift entsteht
  mit dem Freihand-Werkzeug.
- XFA-Formulare: nur der AcroForm-Teil; PDF-JavaScript (Berechnungen, Prüfungen) läuft nie.
- Text in Type3-Schriften und mit anderen CMaps als Identity-H/V wird nicht direkt geändert (neu
  gesetzt oder überlagert – der Hinweis nennt den Weg).
