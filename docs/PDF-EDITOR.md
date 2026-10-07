# PDF Reader & Editor – technische Beschreibung

Werkzeug »PDF Reader & Editor« (seit 3.0.0): PDFs lesen, bearbeiten, organisieren und
kommentieren – vollständig lokal. Kurzfassung für Anwender: [README](../README.md) und
[Release Notes](../windows-app/release-notes/).

## Aufbau

| Teil | Aufgabe | Code |
| --- | --- | --- |
| Engine (ohne Oberfläche) | Dokument, Darstellung, Textschicht, Suche, Gliederung, Text bearbeiten, Bilder, Seiten, Anmerkungen, Formulare, Metadaten, Bildexport, Texterkennung, Rückgängig, Speichern, Sitzungssicherung | `windows-app/app/tools/pdf_editor/` |
| Arbeitsthread | ein Thread für alle Zugriffe auf geöffnete Dokumente; Aufträge mit Priorität (Bearbeiten/Öffnen/Speichern vor sichtbaren Seiten vor Miniaturen vor Suche), Seitenbilder abbrechbar; die Suche gibt dringenden Aufträgen zwischendurch Vorrang | `app/qtapp/reader/engine.py` |
| Controller | Tabs, Öffnen (Dialog, Ziehen, »Zuletzt geöffnet«, »Öffnen mit«), Ansicht, Werkzeuge, Dialoge | `app/qtapp/reader/controller.py`, `document.py`, `session.py`, `printing.py` |
| Oberfläche | Seitenansicht (virtualisiert), Tabs, Befehls- und Werkzeugleiste, Miniaturen, Lesezeichen, Suche, Kommentare, »Seiten organisieren« | `app/qml/PdfTool/Reader/` |
| »Öffnen mit« | zweiter Start reicht PDF-Pfade an die laufende App weiter (lokale Verbindung, nur für diesen Benutzer) | `app/qtapp/instance.py`, `installer/PDF-Tool.iss` (`[Registry]`) |

**Quelle der Wahrheit ist pikepdf (qpdf):** Jede Änderung geschieht in der Objektstruktur des
Dokuments. **PDFium** (pypdfium2) zeichnet die Seiten, liefert Zeichen, Positionen und Glyphen und
prüft Änderungen. Beide greifen nur unter einer gemeinsamen Sperre (`pdfium_lock.PDFIUM_LOCK`) und
nur aus dem Arbeitsthread auf ein Dokument zu.

## Fensteraufbau: Tabs, Seitenleisten, Dokument

Drei getrennte Ebenen:

1. **Tab-Leiste oben** (seit 3.1.0-beta.4, nach dem Vorbild von Adobe Acrobat – `Shell/AppTabs.qml`):
   - ≡ Menü, ⌂ Start, je ein Tab für geöffnete Werkzeuge und **für jedes geöffnete PDF**, »+« öffnet
     weitere PDFs; rechts Kurzanleitung und Einstellungen. Eine Seitenleiste der App gibt es nicht –
     das Dokument hat die ganze Fensterbreite.
   - Der aktive Tab hat die Farbe der Fläche darunter und geht in sie über; die Akzentmarkierung
     gleitet zum aktiven Tab.
   - Ein Klick auf ein PDF führt von überall in den Reader mit diesem Dokument (`Reader.showTab`).
     Der Reader erscheint erst mit dem geöffneten Dokument; nach dem letzten geschlossenen PDF geht es
     zur Startseite. Lässt sich eine Datei nicht öffnen, bleibt die Seite, auf der man war, und zeigt
     den Hinweis.
   - PDF-Tabs zeigen den Namen ohne „.pdf“ (vollständiger Pfad im Tooltip).
   - Bei vielen Tabs werden die Werkzeug-Tabs schmaler, sobald die PDF-Tabs weniger als 200 px hätten;
     die PDF-Tabs werden wie in Edge schmaler (bis 144 px). Haben auch dann nicht alle Platz, zeigt die
     Leiste nur ganze Tabs und ‹ › zum Blättern; Pfeile und Mausrad bewegen um genau einen Tab.
     Der aktive bleibt ganz zu sehen.
   - Seit 3.2: Ziehen ordnet einen PDF-Tab um (`Reader.moveTab`; die Nachbarn weichen weich aus, am Rand
     blättert die Leiste weiter), ebenso Strg+Umschalt+←/→ im fokussierten Tab. Rechtsklick, die
     Kontextmenü-Taste oder Umschalt+F10 öffnen das Menü des Tabs: Schließen, Andere Tabs schließen, Tabs
     rechts schließen (je ungespeichertem Dokument die übliche Rückfrage), Pfad kopieren, Im Ordner
     anzeigen, Geschlossenen Tab wieder öffnen.
   - »Geschlossenen Tab wieder öffnen« (Strg+Umschalt+T, `Reader.reopenClosed`): die zehn zuletzt
     geschlossenen Dokumente mit Pfad, jeweils auf der zuletzt gezeigten Seite.
   - Letzte Sitzung (Einstellung »PDFs der letzten Sitzung beim Start wieder öffnen«, Standard aus): Das
     Beenden merkt sich Pfade, Seiten und das aktive Dokument (`reader_sitzung` in `gui-config.json`); der
     nächste Start öffnet sie nach der Frage zur Absturz-Wiederherstellung im Hintergrund – ohne
     Rückfragen. Fehlende, geschützte oder beschädigte Dateien werden übergangen und in der Statuszeile
     gezählt. Ausschalten entfernt die Liste.
2. **Seitenleisten** links (Seiten, Lesezeichen, Suchen) und rechts (Kommentare, Eigenschaften):
   - Feste Breiten, gleich, welcher Inhalt gezeigt wird: links 256 px, rechts 280 px
     (`Metrics.readerLeftPanelWidth`, `readerRightPanelWidth`).
   - Der Kopf ist in allen Leisten gleich aufgebaut (`PanelHeader`, 44 px hoch): Titel links,
     daneben bei Kommentaren die Anzahl, rechts die Umschalter dieser Leiste (`PanelTabs`, die
     Markierung gleitet zum gewählten Inhalt) und Schließen.
   - Geschlossen bleibt ein schmaler Streifen (44 px, `PanelRail`) mit den Symbolen dieser Leiste;
     ein Klick öffnet sie gleich mit diesem Inhalt. Die Befehlsleiste enthält keine Umschalter für
     Seitenleisten mehr.
   - Leere Inhalte zeigen einen ruhigen Hinweis mit Symbol, Titel und Erklärung
     (`Controls/PEmptyState.qml`).
   - In schmalen Fenstern (unter 820 px) liegen geöffnete Seitenleisten über der Seite.
3. **Dokumentfläche** in der Mitte:
   - Öffnet oder schließt eine Seitenleiste, nimmt die Fläche ihre neue Breite einmal an und wird
     nicht in jedem Bild der Animation neu angeordnet.
   - Die Leiste gleitet in 200 ms über ihren Streifen („Reduziert“: Überblenden, „Aus“: sofort).
   - Steht die Ansicht ganz oben (z. B. gleich nach dem Öffnen), bleibt sie oben. Sonst bleibt die
     Stelle in der Mitte stehen.
   - Dokument bewegen (seit 3.1.0-beta.3): Werkzeug „Verschieben“ (Hand) – Ziehen mit der linken
     Maustaste bewegt das Dokument, herausgezoomt wie vergrößert. In jedem Werkzeug zieht die linke
     Maustaste auf der freien Fläche neben den Seiten und die mittlere Maustaste überall; Umschalt +
     Mausrad verschiebt waagerecht. Wo das geht, zeigt der Zeiger eine offene Hand
     (`Reader/DocumentView.qml`).
   - Ein Klick auf das gewählte Werkzeug schaltet zurück zu „Auswählen“; ebenso schaltet ein Klick
     auf die gewählte Feldart beim Gestalten von Formularen sie ab.

## Bewegung (Animationsprofile)

Der Reader nutzt dasselbe Animationssystem wie die übrige App (Einstellungen → Animationen:
„Vollständig“, „Reduziert“, „Aus“; `Style/Motion.qml`). Alle Dauern und Kurven kommen von dort:

- Farbe und Deckkraft: `fast` (83 ms), `fade` (150/110 ms), `renderFade` (120/90 ms)
- Bewegungen, nur „Vollständig“: `pane` (200 ms), `expand` (200 ms), `indicator` (260 ms),
  `normal` (167 ms)
- Versatz und Größe: `paneShift` (8 px), `menuScale` (95 %)
- Kurven: `decelerate`, `accelerate`, `standard`

Was sich bewegt („Vollständig“):

- **Tab-Leiste:** Die Akzentmarkierung gleitet zum aktiven Tab – auch zwischen ⌂, Werkzeugen und PDFs –
  und bleibt darunter, wenn Tabs hinzukommen oder wegfallen. Neue Tabs blenden ein und heben sich leicht,
  geschlossene blenden aus, die übrigen rücken weich nach.
- **Seitenleisten:**
  - Sie gleiten über ihren Streifen herein bzw. hinaus. Die Dokumentfläche nimmt ihre Breite einmal
    an, ohne Neuaufbau in jedem Bild.
  - Der Inhalt überblendet mit leichtem Versatz, die Auswahl im Kopf gleitet zum neuen Reiter.
  - Die Eigenschaften blenden kurz ein, wenn die Art der Auswahl wechselt (Text, Bild, mehrere).
- **Dokument-Tabs** (in der Tab-Leiste oben):
  - Neue Tabs blenden ein, geschlossene blenden aus, die übrigen rücken weich nach.
  - Die Markierung des aktiven Tabs gleitet.
  - Der Punkt für „ungespeichert“ blendet ein und aus; sein Platz ist reserviert, der Tab springt nicht.
- **Werkzeuge:** Die Akzentmarkierung unter dem gewählten Werkzeug gleitet zum neuen Werkzeug.
- **Kontextmenüs** blenden ein und wachsen dabei von 95 auf 100 % (140 ms).
- **Seitenbilder und Miniaturen:**
  - Ein neues Bild blendet kurz über dem weißen Blatt ein, nur über die Deckkraft.
  - Nach einer Änderung (Text, Kommentar, Rückgängig) blendet das alte Bild über dem neuen aus.
  - Zeigt ein Platz eine andere Seite (Scrollen, wiederverwendete Zeile, anderes Dokument), ist das
    alte Bild im selben Moment weg, und bis zum neuen steht das weiße Blatt. Ausblenden ist dabei nie
    animiert, nur das Einblenden (`Reader/PageImage.qml`).
  - Die Markierung der aktuellen Miniatur wechselt weich.
- **Zoom:** Über Schaltflächen, Menü und Tastatur gleitet die Darstellung kurz vom alten zum neuen
  Maßstab (167 ms). Aufbau und Lage gelten dabei sofort, nur die fertigen Inhalte werden skaliert.
- **Mausrad:** Jede Raste verschiebt um dieselbe Strecke (Zeilen aus den Windows-Einstellungen, rund
  32 px je Zeile; „Eine Bildschirmseite“: eine Seite), weich in 160 ms; schnell gedrehte Rasten addieren sich (`Controls/PWheelScroll.qml`,
  in der Ansicht, den Seitenleisten und „Seiten organisieren“).
- **Suche:**
  - Die Treffer einer Seite blenden einmal ein.
  - Der Rahmen des aktuellen Treffers zieht sich beim Wechsel kurz auf den Treffer zusammen.
- **Seiten organisieren:**
  - Beim Ziehen werden die gewählten Seiten zu Platzhaltern an der neuen Stelle, und eine Vorschau mit
    Schatten folgt dem Zeiger.
  - Die übrigen Seiten rücken weich in die neue Reihenfolge, nach dem Ablegen rasten die Seiten ein.
  - Gelöschte Seiten blenden aus, eingefügte ein, die übrigen rücken nach.
  - Jede Zelle wechselt erst an ihre neue Stelle, wenn ihr neues Bild da ist. So steht nie eine falsche
    Seite an einer Stelle.
- **Formularfelder:** Die Fokusmarkierung (kräftigerer Rahmen) blendet kurz ein und aus, ohne Glühen.
  Fläche und Eingabe wechseln sofort, sonst schiene der Wert aus dem PDF kurz durch. Nach der
  Eingabetaste oder Escape hat wieder die Seite die Tastatur.
- **Hinweise und Ablegen:**
  - InfoBars gleiten ein und aus.
  - Eine über die Ansicht gezogene PDF zeigt eine Ablagefläche, die weich ein- und ausblendet.
  - Beim Speichern wechselt „Speichern …“ → „Gespeichert“ mit Überblendung.

„Reduziert“: nur kurze Überblendungen und Farbwechsel – nichts gleitet, wächst oder rückt nach; beim
Organisieren zeigt die Einfügemarke die Stelle. „Aus“: jeder Zustand gilt sofort, keine Komponente
erzwingt eine Animation.

Bewusst ohne Bewegung:

- Strg+Mausrad zoomt direkt, ohne Gleiten. Touchpad, Bildlaufleiste und Ziehen folgen direkt; das
  Mausrad scrollt bei „Reduziert“ und „Aus“ sofort.
- Seiten gleiten beim Scrollen nicht ein.
- Textauswahl, Einfügemarke und Anfasser beim Ziehen folgen direkt; neue Anfasser blenden nur ein.
- Animiert werden nur Deckkraft, Verschiebung und Skalierung einzelner Elemente. Lange Listen werden
  nicht Element für Element animiert, und es gibt keine Unschärfe oder Shader.

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

### Nachtmodus (seit 3.2)

Ansicht-Menü oder Einstellungen → PDF Reader: Die Seitenbilder werden umgekehrt und abgemildert (Papier
`#1E1E1E`, Schrift höchstens `#E0E0E0`; `engine.night_image`). Die Bildadresse trägt dann `~n` hinter der
Dokumentkennung, der Zwischenspeicher führt die Bilder getrennt. Nur die Anzeige: Datei, Drucken und Export
rendern ohne diesen Weg. Die Einstellung gilt für alle Tabs und bleibt nach einem Neustart
(`reader_nachtmodus`).

### Schnellwerkzeuge der Startseite (seit 3.2)

In der Karte »Werkzeuge« der Startseite: PDF verkleinern, Schwärzen, Kennwortschutz, Wasserzeichen,
Seitenzahlen, Dokument bereinigen, Unterschreiben, Zusammenführen (`Reader.quickTools`). Ein Klick wählt eine
PDF; sie öffnet sich im Reader, und sobald das Dokument aktiv ist, startet das Werkzeug
(`open_paths(…, then=…)`, `DocumentController.runAction`). Wird der Tab vorher geschlossen oder gewechselt,
startet nichts.

### Per E-Mail senden (seit 3.2)

»Weitere Befehle« → »Per E-Mail senden …« (`Reader.sendByMail`, `app/qtapp/mail.py`): Das E-Mail-Programm
öffnet eine neue Nachricht mit der PDF als Anhang – gesendet wird nur dort, nie von PDF Tool. Ungespeicherte
Änderungen: vorher speichern oder den gespeicherten Stand senden; ein nie gespeichertes Dokument wird zuerst
gespeichert.

- Windows: Simple MAPI (`MAPISendMailW`, sonst `MAPISendMail`) mit `MAPI_DIALOG` – nur, wenn unter
  `Software\Clients\Mail` ein E-Mail-Programm eingetragen ist. Ohne MAPI oder nach einem Fehler (nicht nach
  einem Abbruch im E-Mail-Programm): `mailto:` mit Empfänger und Betreff, die Datei im Explorer markiert.
- Im Hintergrund (MAPI wartet, bis die Nachricht gesendet oder verworfen ist), höchstens eine Nachricht
  zugleich. Protokolliert werden nur Fehlercodes – nie Pfade, Adressen oder Inhalte.
- Dieselbe Funktion haben »Übersicht erstellen« (nach »PDF erstellen«, an den Rechnungsempfänger wie in der
  PDF) und der Stapel (Detail eines Eintrags).

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

## Objekt bearbeiten – einzelne Zeilen, Segmente, Wörter und Bilder

Eigenes Werkzeug neben »Text bearbeiten« (`tools/pdf_editor/objects.py`). »Text bearbeiten« ändert
einen logischen Absatz mit Cursor und Umbruch. »Objekt bearbeiten« wählt die kleinsten sinnvollen
Einheiten, wie sie im PDF stehen: eine Zeile einer Adresse, eine Tabellenzelle, ein Wort oder ein
Bild. Jede Einheit lässt sich einzeln ändern, verschieben, formatieren und löschen. Alles andere auf
der Seite bleibt, wo es ist.

**Segmentierung (nur ein Modell – die Datei ändert sich erst mit einer Aktion).** PDFium liefert je
Zeichen Box, Ursprung auf der Grundlinie, Schrift, Größe, Farbe, Richtung und das Textobjekt (einen
Textoperator `Tj`/`TJ`/`'`/`"`). Gruppiert wird nach Geometrie, nicht nach Operatoren. Eine
sichtbare Zeile besteht oft aus mehreren Operatoren, ein Operator enthält manchmal mehrere Zeilen
oder Spalten:

1. **Zeilen:** Zeichen gleicher Richtung auf derselben Grundlinie (Abstand ≤ 35 % der
   Schriftgröße), in Schreibrichtung fortlaufend.
2. **Segmente:** innerhalb einer Zeile Trennung an großen Lücken (≥ 0,9 Geviert – Tabellenspalten,
   abgesetzte Werte) und an Wechseln von Schrift, Größe (> 15 %), Farbe oder Darstellungsart.
3. **Wörter:** innerhalb eines Segments an Leerzeichen *oder* an geometrischen Lücken ≥ 0,15 Geviert.
   Viele PDFs setzen Wortabstände als TJ-Verschiebung ohne Leerzeichen.

Alle Toleranzen sind relativ zur Schriftgröße in Seitenkoordinaten, also unabhängig von Zoom und
DPI. Unsichtbarer Text (Darstellungsart 3, etwa die Texterkennung über einem Scan) ist kein Objekt.
Auf Seiten ohne Text steht »Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt.«. Bilder
bleiben dort trotzdem wählbar. Gescannte Seiten macht die [Texterkennung](#texterkennung-ocr)
durchsuchbar; ihr Text bleibt unsichtbar und ist ebenfalls kein Objekt.

**Zuordnung zum Inhaltsstrom.** Die Textobjekte von PDFium werden den Textoperatoren zugeordnet
(gleiche Reihenfolge, gleicher Text). Danach werden je Operator die Codes einzeln den Zeichen
zugeordnet. Das gilt nur, wenn die Anzahl übereinstimmt und die Schrift sich sicher kodieren lässt
(einfache Schriften, CID mit Identity-H). Ein so zugeordnetes Segment ist **direkt änderbar**. Für
alle anderen nennt das Modell den Grund, zum Beispiel »Der Text liegt in einem eingebetteten
Formular-Objekt.«.

**Änderungen im Inhaltsstrom (nativ, `NATIVE`).** Betroffene Operatoren werden an Code-Grenzen in
Teile zerlegt. Das ist rein syntaktisch, die Darstellung bleibt identisch. Danach werden nur die
Zielteile geändert:

| Aktion | Wie |
| --- | --- |
| Text ändern | neuer Text in der Originalschrift (Kodierung und Glyphen geprüft). Wird ein Wort mitten im Segment länger oder kürzer, rückt nur der Rest *dieses* Segments nach. |
| Löschen | der Teil wird zu einer reinen Verschiebung gleicher Breite; ein gelöschtes Wort nimmt seinen Wortabstand mit. |
| Verschieben | eigene Textmatrix (`Tm`) für den Teil; danach gelten Text- und Zeilenmatrix wie vorher. |
| Größe, Farbe, Zeichenabstand | Zustand nur für den Teil, danach wiederhergestellt; immer genau eine Eigenschaft je Schritt. |
| Duplizieren | dieselben Codes mit derselben Schrift, Größe, Farbe und Transformation versetzt daneben. |
| Ausrichten | mehrere Segmente links, rechts, oben oder unten bündig (ein Schritt für Rückgängig). |

**Neu gesetzt (`RECONSTRUCTED`)**, wenn der Originalschrift Zeichen fehlen (z. B. »Č« in einer
WinAnsi-Schrift): Die Originalzeichen werden nativ entfernt, der neue Text wird an derselben
Grundlinie in einer passenden Schrift gesetzt (wie bei »Text bearbeiten«).

**Überlagerung (`OVERLAY`)** nur als letzter Ausweg, wenn der Text keinem Operator sicher zugeordnet
ist (Formular-XObjects, unklare Struktur). Das Rechteck hat die gemessene Hintergrundfarbe. Es ist
nie pauschal weiß, aber einfarbig: Auf Bildern und Verläufen bleibt es sichtbar. Der Originaltext
bleibt in der Datei, die Überlagerung ist **keine Schwärzung**. Verschieben und Formatieren gibt es
nur nativ.

Jede Änderung wird wie bei »Text bearbeiten« geprüft:
- Die Darstellung hat sich nur im betroffenen Bereich geändert.
- Der neue Text ist lesbar, der alte entfernt.
- Beim Verschieben und Formatieren sind die Zeichen der Seite dieselben.

Scheitert die Prüfung, wird die Änderung vollständig zurückgenommen. Jede Aktion ist ein Schritt
für Rückgängig/Wiederholen. Gespeichert wird über denselben sicheren Weg wie jede andere Änderung.
Eine Analyse eines älteren Seitenstands ändert nie etwas (Revisionsprüfung).

**Bedienung.**
- **Maus:**
  - Zeigen hebt nur das Objekt unter dem Zeiger dezent hervor.
  - Klick wählt eine Zeile bzw. ein Segment, ein weiterer Klick darauf ein Wort.
  - Doppelklick bearbeitet genau dieses Segment, mit dem Cursor an der Klickstelle.
  - Strg+Klick fügt Objekte hinzu oder entfernt sie; ein Rahmen auf freier Fläche wählt alle
    Objekte, die überwiegend darin liegen.
  - Ziehen verschiebt die Auswahl 1:1 mit dem Zeiger.
- **Tastatur:**
  - Pfeiltasten verschieben um 1 pt, mit Umschalt um 10 pt; das ergibt einen Schritt.
  - Entf löscht, Eingabe oder F2 bearbeitet.
  - Strg+C, Strg+X und Strg+D kopieren, schneiden aus und duplizieren.
  - Tab wählt das nächste Objekt der Seite, Esc hebt die Auswahl auf.
- **Kontextmenü:** Bearbeiten, Text bearbeiten (ganzer Absatz), Kopieren, Ausschneiden,
  Duplizieren, Löschen und Eigenschaften; für Bilder Ersetzen, Drehen und Löschen.
- **Eigenschaften (rechte Seitenleiste):**
  - Text: Schrift und Drehung (nur Anzeige), Größe, Zeichenabstand, Farbe, Position.
  - Bild: Position, Größe, Ersetzen, Drehen.
  - Mehrere Objekte: Ausrichten, gemeinsame Größe und Farbe.
  - Die Seitenleiste öffnet sich mit dem Modus und schließt sich beim Verlassen wieder.

Verlassen des Modus hebt die Auswahl auf. Bilder sind im Objektmodus wie im Bildwerkzeug
verschiebbar, skalierbar (Ecken), drehbar, ersetzbar und löschbar.

**Treffer und Leistung.** Die Oberfläche bekommt je Seite alle Objekte in Anzeige-Punkten
(Seitendrehung, CropBox und MediaBox sind eingerechnet). Die Treffer prüft sie selbst, ohne bei
jeder Mausbewegung nachzufragen:
- Ein Bandindex (24 pt hohe Streifen) begrenzt die Prüfung auf die Objekte unter dem Zeiger.
- Bei Überlappung gewinnt das kleinste Objekt.
- Die Toleranz beträgt 1 pt.

Analysiert werden nur die aktuelle Seite und ihre Nachbarn, im Arbeitsthread. Das Ergebnis gilt je
Seitenstand (Revision), sonst wird neu analysiert.

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
- **Formulare gestalten** (Werkzeug »Formular gestalten«, Pfeil neben »Formular«; Engine
  `formdesign.py`): Textfeld, Kontrollkästchen, Optionsfeld (Gruppe; weitere Optionen über »Option
  hinzufügen«), Dropdown und Liste anlegen – Feldart wählen und einen Rahmen aufziehen, klicken
  (Standardgröße) oder per Rechtsklick »… hier«. Felder ziehen verschiebt sie, die Ecken ändern die
  Größe (frei, mit Umschalt im Seitenverhältnis), Pfeiltasten verschieben (1 pt, mit Umschalt 10 pt;
  gesammelt als ein Schritt), Strg+D dupliziert (bei Optionsfeldern: neue Option derselben Gruppe), Entf
  löscht. Doppelklick, Eingabetaste oder »Eigenschaften …« öffnet den Dialog »Feldeigenschaften«:
  Name, Kurzinfo, Pflichtfeld, schreibgeschützt, mehrzeilig, Zeichenzahl, Schriftgröße, Ausrichtung,
  Optionen, Exportwert, Rahmen und Hintergrund. Neue Felder sind gewöhnliche AcroForm-Felder mit
  gezeichneten Erscheinungsbildern für jeden Zustand (ohne Schrift für Haken und Punkt) und
  Standardschriften in den Formularressourcen – sie lassen sich in jedem Programm ausfüllen. Jede
  Änderung ist ein Schritt für Rückgängig; Arrays und Dictionaries werden nie in place verändert.
  Fremde Kästchen behalten ihr Aussehen, solange Rahmen und Hintergrund nicht geändert werden;
  Signaturfelder und Schaltflächen lassen sich verschieben, skalieren und löschen, aber nicht
  duplizieren. XFA-Formulare werden nicht umgestaltet (ein XFA-Programm zeigte neue Felder nicht).

## Schützen und Weitergeben (seit 3.2)

Befehle in der Werkzeugleiste unter **Schützen** (Schild) und **Seiten gestalten**; Engine je Aufgabe ein
Modul in `tools/pdf_editor/`. Jede Änderung ist ein Schritt für Rückgängig und wird beim Speichern wie jede
andere geprüft (die Datei wird erst ersetzt, wenn die neue fehlerfrei geöffnet und gezeichnet wurde).

- **Schwärzen** (`redact.py`, Werkzeug »Schwärzen«): Bereiche aufziehen oder Text markieren – vorgemerkte
  Stellen sind rot umrandet, entfernt wird erst mit »Schwärzen anwenden« (Rückfrage). Im Bereich werden
  Textzeichen aus dem Inhaltsstrom entfernt (TJ mit Abständen, der übrige Text bleibt an seiner Stelle),
  Vektorpfade ganz im Bereich gelöscht, Bilder neu kodiert mit schwarzen Flächen (auch ihre weiche Maske),
  Formular-XObjects als eigene Kopie bearbeitet (bis Tiefe 8), Kommentare, Links und Formularfelder im
  Bereich entfernt, Vorschaubilder der Seite gelöscht, alternative Texte (`/ActualText`, `/Alt`, `/E`) und
  passende Einträge des Strukturbaums geleert. Inline-Bilder, Masken, JBIG2 und unbekannte Schriften lassen
  sich nicht sicher teilweise bearbeiten: Dann wird die ganze Seite mit 200 dpi als Bild geschwärzt (der
  Hinweis nennt die Seite). Danach prüft PDFium jede Seite: Steht im Bereich noch ein Zeichen, wird die Seite
  als Bild geschwärzt; bleibt auch dann etwas, wird alles zurückgenommen (Fehler statt halber Schwärzung).
  **Suchen und schwärzen:** IBAN (mit Prüfziffer nach ISO 13616), E-Mail-Adressen, Telefonnummern (7–15
  Ziffern), Datumsangaben und eigene Begriffe; Fundstellen werden nur vorgemerkt. Seitenänderungen
  (drehen, löschen, verschieben, zuschneiden) verwerfen noch nicht angewendete Bereiche.
- **Dokument bereinigen** (`sanitize.py`): zählt zuerst, was es gibt, und entfernt dann die gewählten Arten
  – Metadaten (Info-Wörterbuch, XMP), Skripte und unsichere Aktionen (JavaScript, Launch, SubmitForm,
  ImportData, Rendition, RichMediaExecute; auch an Feldern, Kommentaren, Lesezeichen und Seiten), Anhänge
  (eingebettete Dateien, Dateianhang-Kommentare), versteckte Daten (Vorschaubilder, PieceInfo, unsichtbare
  Kommentare) und auf Wunsch alle Kommentare. Ein Schritt für Rückgängig.
- **Reduzieren** (`flatten.py`): Erscheinungsbilder von Formularfeldern und Kommentaren werden als
  Formular-XObject in die Seite gezeichnet (Lage aus BBox, Matrix und Rect, Deckkraft über ExtGState),
  danach werden die Anmerkungen und leere Formularstrukturen entfernt. Felder mit `NeedAppearances` bekommen
  vorher frische Erscheinungsbilder; Signaturfelder und Anmerkungen ohne Erscheinungsbild bleiben.
- **Kennwortschutz** (`protect.py`): Kennwort zum Öffnen und/oder Einschränkungen (Drucken, Kopieren,
  Ändern, Kommentieren, Formulare, Seiten) mit eigenem Berechtigungskennwort – oder Schutz entfernen.
  Gespeichert wird mit AES-256 (Revision 6); geprüft wird die neue Datei mit dem neuen Kennwort. Den Schutz
  ändern darf nur, wer das Dokument uneingeschränkt geöffnet hat; »Einschränkungen aufheben …« fragt dazu
  nach dem Berechtigungskennwort und prüft es an der Originaldatei (nichts wird geraten oder umgangen).
- **PDF verkleinern** (`optimize.py`): immer als Kopie. Bilder, die mindestens 1,3-mal feiner sind als die
  Stufe (110, 150 oder 220 dpi bezogen auf ihre größte Darstellung), werden als JPEG neu berechnet, wenn das
  höchstens 90 % der bisherigen Größe ergibt; Ungenutztes wird entfernt, Objektströme werden komprimiert.
  Kennwortschutz bleibt; die Kopie wird vor dem Schreiben geprüft. Gewinnt die Kopie nichts, entspricht sie
  dem aktuellen Stand.
- **Kopf- und Fußzeile, Seitenzahlen, Bates-Nummern, Wasserzeichen** (`pagemarks.py`): Texte in sechs
  Positionen mit den Platzhaltern `{seite}`, `{seiten}`, `{datum}`, `{datei}`, `{bates}`; Wasserzeichen mit
  Farbe, Deckkraft, Winkel und Größe über oder hinter dem Inhalt. Jeweils ein eigener, markierter
  Inhaltsstrom je Seite (`/PDFToolMark`, als Artefakt gekennzeichnet) mit eigenen Schrift- und
  Grafikzustand-Ressourcen – aufrecht auch auf gedrehten Seiten, ersetzbar und wieder entfernbar, ohne den
  übrigen Inhalt anzufassen. Standardschriften mit WinAnsi; nicht darstellbare Zeichen werden durch »?«
  ersetzt (der Hinweis nennt sie).
- **Stempel und Unterschrift** (`stamps.py`): Anmerkung `/Stamp` mit eigenem Erscheinungsbild im eigenen
  Raum (BBox = Größe in der Anzeige) und einer Matrix gegen die Seitendrehung – aufrecht auf jeder Seite.
  Verschieben und Größe ändern ändern nur `/Rect` (jedes Programm bildet das Bild darauf ab; das
  Seitenverhältnis bleibt, Umschalt: frei). Stempel: GENEHMIGT, GEPRÜFT, ERLEDIGT, BEZAHLT, EINGEGANGEN,
  ENTWURF, KOPIE, VERTRAULICH, ABGELEHNT oder eigener Text, zweite Zeile mit `{datum}`/`{zeit}`.
  Unterschrift: gezeichnet (Striche als Bézier-Kurven mit runden Enden) oder aus einem Bild (Papier wird
  durchsichtig, die Tinte behält ihre Farbe; als Bild mit weicher Maske). Gespeicherte Unterschriften liegen
  nur auf Wunsch in `%APPDATA%\PDF-Tool\unterschriften.json` (höchstens sechs, atomar geschrieben, löschbar);
  sie gehören zu keinem Sicherungsbereich und nicht ins Support-Paket. Keine digitale Signatur.
- **Links** (`links.py`): Links werden beim Zeigen mit »Auswählen« erkannt (Zeiger und Ziel als Hinweis);
  ein Klick ohne Ziehen springt zur Zielseite, eine Webadresse öffnet erst nach Rückfrage. Andere Aktionen
  (Programme, Dateien, Skripte) führt PDF Tool nie aus. Werkzeug »Links«: Bereich aufziehen und Ziel wählen
  (Seite oder http/https/mailto), vorhandene Links ändern oder entfernen. Benannte Ziele werden aufgelöst.
- **Lesezeichen bearbeiten** (`outline.py`): hinzufügen (zur angezeigten Seite, dahinter oder als
  Unterpunkt), umbenennen (F2), auf die angezeigte Seite setzen, verschieben, ein- und ausrücken, löschen
  (Entf; mit Unterpunkten nach Rückfrage). Jede Änderung schreibt einen neuen Lesezeichenbaum; Ziele und
  Aktionen werden als Verweise übernommen, der alte Baum dient Rückgängig.
- **Seiten zuschneiden** (`crop.py`): Ränder in Millimetern, wie man die Seite sieht (auch gedreht), oder an
  den Inhalt angepasst (Ränder aus einem Seitenbild mit 500 px Breite); mindestens 36 pt bleiben sichtbar.
  Zugeschnitten wird die CropBox – der Inhalt außerhalb bleibt in der Datei (zum Entfernen: Schwärzen);
  »Zuschnitt zurücksetzen« zeigt wieder die ganze Seite.

## KI-Assistent (optional, seit 3.2)

Rechte Seitenleiste `assistant` (`Reader/AssistantPanel.qml`), nur wenn der Assistent in den Einstellungen
eingeschaltet ist; Streifen und Kopf zeigen dann ein drittes Symbol. Ausschalten schließt die Seitenleiste in
allen Tabs (`ReaderController.close_right_panel`).

- **Text:** `DocumentController.assistant_texts` liest die Seitentexte im Arbeitsthread (`Session.page_texts`,
  höchstens 2 Mio. Zeichen) einmal je Dokumentstand; `assistant/text.py` teilt sie in Abschnitte je Seite und
  sucht mit BM25 die passenden für eine Frage.
- **Antwort:** `AssistantController` startet den KI-Prozess bei Bedarf (`assistant/runtime.py`), schickt
  Auszüge mit Seitenzahl und streamt die Antwort in die Zeile des Gesprächs (`KeyedListModel`, höchstens etwa
  zwölfmal pro Sekunde). Seitenangaben werden zu Verweisen `page:N` (nur vorhandene Seiten), alles andere
  bleibt maskierter Text (`StyledText`).
- **Gespräche** gehören zum Dokument-Tab, nur im Arbeitsspeicher; geschlossene Tabs verwerfen ihres, eine
  laufende Antwort ihres Tabs wird abgebrochen.
- **Ohne Text** (Scan): Hinweis auf »Text erkennen (OCR)«, kein KI-Prozess.

## Texterkennung (OCR)

`tools/pdf_editor/ocr.py` legt über gescannte Seiten eine unsichtbare Textebene – vollständig lokal
mit Tesseract. Die Seite sieht danach aus wie vorher; Suche, Auswahl und Kopieren finden den Text.

- **Engine:** gebündelt unter `<Installationsordner>\ocr\` (Tesseract 5.5.3, Windows-Build der UB
  Mannheim: nur `tesseract.exe` und die DLLs aus seinen Importtabellen; Sprachdaten Deutsch, Englisch
  und Lageerkennung aus `tessdata_fast`; `build.py`, geprüft von `release_check.check_ocr`). Sonst
  `PDFTOOL_TESSERACT` (Pfad zur ausführbaren Datei) oder `tesseract` im PATH.
- **Ablauf:** `render_page_image` zeichnet im Arbeitsthread die sichtbare Seite (CropBox, Drehung)
  mit 300 dpi. `recognize` startet Tesseract in einem beliebigen Thread als eigenen Prozess; Bild und
  Ergebnis liegen in einem privaten Temp-Ordner, der immer gelöscht wird, Abbrechen beendet den
  Prozess. `apply_text_layers` übernimmt im Arbeitsthread die Text-only-PDF als Formular-XObject
  `/PTOCRn`, platziert über `PageGeometry.to_page`, ersetzt eine vorhandene Ebene – ein Schritt für
  Rückgängig, geprüft wie beim Bearbeiten (Darstellung unverändert, Text lesbar).
- **Datenschutz:** Nichts verlässt den Rechner, erkannte Texte werden nicht protokolliert.

## Rückgängig und Wiederholen

Je Dokument eine Befehlsliste (`tools/pdf_editor/commands.py`). Gespeichert werden nur die vor der
Änderung betroffenen Objekte (Memento je Objekt, nicht das ganze Dokument); die Liste hält
höchstens 100 Schritte – älteste Schritte entfallen zuerst.

## Speichern – sicher oder gar nicht

`tools/pdf_editor/save.py`, Strg+S bzw. Strg+Umschalt+S:

1. Wurde die Datei seit dem Öffnen von einem anderen Programm verändert, wird sie nicht
   überschrieben – PDF Tool fragt (»Überschreiben« / »Speichern unter …« / »Abbrechen«).
2. Vorab: Zielordner vorhanden, Datei nicht schreibgeschützt; die temporäre Datei wird zuerst im
   Zielordner angelegt (gleiches Dateisystem – fehlt die Schreibberechtigung, zeigt sich das sofort).
3. Der Stand wird serialisiert (qpdf, komprimiert, keine Vergrößerung durch Altlasten:
   nicht mehr benutzte eigene Schriften werden entfernt). Eine vorhandene Verschlüsselung bleibt
   samt Berechtigungen erhalten. XMP-Metadaten bleiben unverändert (`fix_metadata_version=False`):
   sonst bräuchte pikepdf lxml, das nicht zur Laufzeit gehört – daran scheiterte in 3.0.0-beta.1
   das Speichern jedes PDFs mit XMP-Metadaten. »Eigenschaften« gleicht XMP mit der
   Standardbibliothek an (`xmp.py`).
4. **Prüfung vor dem Ersetzen:** mit pikepdf und PDFium neu öffnen, Seitenzahl, Darstellbarkeit der
   Seiten und Erhalt der Struktur (Lesezeichen, Links, Anmerkungen, Formularfelder, Anhänge,
   Metadaten, Ebenen, Sprungziele) mit dem Stand im Speicher vergleichen.
5. Temporäre Datei schreiben, auf den Datenträger zwingen, zurücklesen, vergleichen.
6. Vor dem Überschreiben des Originals eine Sicherung des vorherigen Stands anlegen
   (`%LOCALAPPDATA%\PDF-Tool-Editor\Sicherungen`, je Datei die letzten 3, höchstens 7 Tage).
7. Atomar ersetzen (`os.replace` = `MoveFileEx` im selben Ordner; kurze Wiederholungen, falls ein
   Virenscanner die Datei gerade prüft).
8. **Nachprüfung:** die gespeicherte Datei wie beim Öffnen lesen (dieselben Bytes wie geprüft,
   pikepdf und PDFium, gleiche Seitenzahl). Erst dann gilt das Dokument als gespeichert.

Schlägt ein Schritt fehl, bleibt das Original unverändert, die temporäre Datei wird entfernt, das
Dokument bleibt ungespeichert (»*«) und Rückgängig bleibt möglich. Jeder Fehler hat eine Art
(`SaveFailed.kind`) mit verständlichem Text; wo es hilft, bietet die Meldung »Speichern unter …« an:

| Art | Meldung (gekürzt) |
| --- | --- |
| `TARGET_READ_ONLY` | Die Datei ist schreibgeschützt. Verwenden Sie »Speichern unter« … |
| `DIRECTORY_NOT_WRITABLE` | PDF Tool hat keine Schreibberechtigung für diesen Speicherort. |
| `FILE_LOCKED` | Die Datei wird möglicherweise von einem anderen Programm verwendet. |
| `TEMP_WRITE_FAILED` | Datei nicht geschrieben (z. B. Datenträger voll) – Original unverändert |
| `VALIDATION_FAILED` | Prüfung vor dem Schreiben fehlgeschlagen – Original unverändert |
| `REPLACE_FAILED` | Originaldatei nicht ersetzt (sonstiger Grund) – unverändert |
| `REOPEN_FAILED` | gespeicherte Datei ließ sich nicht wieder öffnen – nennt die Sicherung |
| `SERIALIZE_FAILED`, `BACKUP_FAILED`, `DIRECTORY_MISSING` | Stand nicht als PDF schreibbar, Sicherung nicht möglich, Ordner fehlt |

»Gesperrt« wird nie vermutet: Scheitert das Ersetzen mit »Zugriff verweigert«, prüft PDF Tool mit
einem kurzen Öffnen mit Löschrecht, ob ein anderes Programm die Datei offen hält oder die
Berechtigung fehlt. Eigene offene Handles gibt es nicht – das Dokument liegt nach dem Öffnen
vollständig im Speicher (pikepdf und PDFium arbeiten auf Bytes, auch Darstellung, Miniaturen und
Suche). Das Protokoll (`pdf-tool.log`) nennt Art, Schritt, Komponente, Fehlertyp, errno/WinError –
statt des Pfads nur die Endung und eine Kurzkennung, nie Inhalte oder Passwörter.

Je Dokument läuft höchstens ein Speichervorgang; weitere Anfragen (mehrfaches Strg+S, »Speichern«
beim Schließen) werden zusammengefasst und danach ausgeführt – ohne Änderungen gibt es nichts zu
schreiben. Eine laufende Suche gibt dem Speichern Vorrang und läuft danach weiter. Die Ansicht
(Seite, Zoom, Modus, Seitenleisten, Tabs) und der Verlauf für Rückgängig bleiben beim Speichern
erhalten; die Werkzeugleiste zeigt »Speichern …« und danach kurz »Gespeichert« – ohne Dialog.

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
- Neue Kennwörter (Kennwortschutz) und gespeicherte Unterschriften werden nie protokolliert; Unterschriften
  bleiben nur auf diesem PC und nur, wenn sie ausdrücklich gespeichert werden.
- Links öffnen Webadressen nur nach Rückfrage; Skripte, Programme und Dateien aus Links werden nie gestartet.
- Die letzte Sitzung (nur mit der Einstellung) enthält nur Pfade und Seiten, lokal in den Einstellungen; das
  Support-Paket nennt davon nur die Anzahl. »Per E-Mail senden« verschickt nichts selbst.
- KI-Assistent (nur eingeschaltet): Texte, Fragen und Antworten bleiben im Arbeitsspeicher und gehen nur an den
  lokalen KI-Prozess (127.0.0.1, zufälliger Schlüssel); protokolliert werden nur Fehlerarten.

## Tests

- Engine: `tests/test_editor_*.py` (Kern, Text, Seiten, Bilder, Anmerkungen, Formulare ausfüllen und
  gestalten, Eigenschaften) mit künstlichen PDFs aus `tests/editorsamples.py`.
- Formulare gestalten: `tests/test_editor_formdesign.py` (alle Feldarten anlegen, ausfüllen, speichern,
  neu öffnen; verschieben, Größe, duplizieren, löschen, Eigenschaften, Rückgängig, XFA, Berechtigungen)
  und `tests/test_qt_forms_v31.py` (Werkzeugleiste, Rahmen aufziehen, Klick, Kontextmenü, Ziehen,
  Ecken, Strg+D, Entf, Pfeiltasten, Dialog, danach ausfüllen und speichern).
- Oberfläche: `tests/test_qt_reader.py` – Maus und Tastatur wie von Hand (Auswahl, Zoom mit
  Strg+Mausrad, Text ändern, Zeichnen, Bilder, Formulare, Seiten organisieren, Speichern, Passwort,
  beschädigte und signierte PDFs, »Öffnen mit«, Sitzungssicherung, Datenschutz).
- Objekt bearbeiten:
  - `tests/test_editor_objects.py` (Engine):
    - Fälle A–L: Zeile, mehrere Zeilen in einem Textobjekt, Wort aus mehreren Runs,
      unterschiedliche Schriften, Tabelle (auch in einem einzigen TJ), Adresse, farbiger
      Hintergrund, Text auf Bild, gedrehte Seiten mit CropBox, Teilschrift, CID-Schrift,
      gleiche Wörter
    - Regression »Hottgenroth Software GmbH«, Tabelle, Speichern → Schließen → Öffnen
  - `tests/test_qt_objects.py` (Oberfläche):
    - Zeigen, Klick, Wort, Doppelklick, Strg+Klick, Rahmen, Ziehen, Tastatur
    - Kontextmenü, Eigenschaften, Bilder
    - Zoom 50–400 %, gedrehte Seiten, Tabs, Animationsprofile
- Bewegung: `tests/test_qt_reader_motion.py` (je Test „Vollständig“, „Reduziert“, „Aus“)
  - Seitenleisten: gleiten, blenden oder schalten sofort; nach schnellem Umschalten gilt der letzte
    Zustand
  - Auswahl im Kopf, Dokument-Tabs (Markierung, Punkt für „ungespeichert“), Kontextmenü, Werkzeug
  - Miniaturen: Beim schnellen Scrollen und beim Wechsel des Dokuments zeigt keine Zeile ein fremdes
    Bild, am Ende sind alle sichtbar; Einblenden außer bei „Aus“
  - Formularfelder: Die Fokusmarkierung blendet außer bei „Aus“; nach Escape hat die Seite die Tastatur
  - Seiten organisieren: Vorschau beim Ziehen, Einrasten, Löschen
  - Zoom gleitet nur über Schaltflächen; Strg+Mausrad bleibt direkt, Seiten folgen dem Scrollen sofort
  - Suchtreffer, Ablagefläche
- Fensteraufbau: `tests/test_qt_reader_layout.py`
  - feste Breiten der Seitenleisten, Umschalter im Kopf, Streifen zum Wiederöffnen
  - einheitliche Köpfe (kein Titel gekürzt), leere Zustände, Befehlsleiste ohne Umschalter
  - PDFs als Tabs neben ⌂ Start, Wechsel zur Startseite und zurück, nach dem letzten PDF die Startseite
  - Öffnen von der Startseite: der Reader erscheint erst mit dem Dokument, Fehler bleiben auf der Startseite
  - viele Tabs im schmalen Fenster: nur ganze Tabs mit ‹ ›, Pfeile und Mausrad blättern um einen Tab, der aktive
    bleibt zu sehen
  - Beenden mit Werkzeug-Tabs und vielen PDFs ohne QML-Meldungen beim Abbau
  - kein Neuanordnen in jedem Bild (Animationsprofile „Vollständig“ und „Aus“)
- Schützen und Weitergeben: `tests/test_editor_redact.py` (Text, TJ mit Abständen, CID-Schrift,
  Formular-XObject, Scan mit Texterkennung, gedrehte Seite, Anmerkungen, Muster, Rückfall »Seite als Bild«;
  geprüft mit PDFium, an den Rohdaten und an den Bildpunkten), `test_editor_cleanup.py` (Bereinigen,
  Reduzieren), `test_editor_protect.py`, `test_editor_optimize.py`, `test_editor_pagemarks.py`,
  `test_editor_stamps.py` (Stempel aufrecht auf gedrehten Seiten, Unterschrift aus Strichen und aus einem
  Scan, gespeicherte Unterschriften), `test_editor_navigation.py` (Lesezeichen, Links, Zuschneiden) und
  `tests/test_qt_protect.py` (Werkzeugleiste, Schwärzen mit der Maus und per Suche, Bereinigen,
  Kennwortschutz, Reduzieren, Verkleinern, Kopf-/Fußzeile, Wasserzeichen, Zuschneiden, Stempel, Unterschrift,
  Links, Lesezeichen, jeder neue Dialog ohne QML-Meldungen).
- Komfort: `tests/test_qt_comfort.py` (Kontextmenü der Tabs, Schließen mit Rückfragen, Umordnen mit der Maus,
  Strg+Umschalt+T, letzte Sitzung samt fehlender Dateien, »Öffnen mit« beim Start und dem aktiven Tab vor den
  Rückfragen beim Beenden, Nachtmodus, Schnellwerkzeuge, Per E-Mail senden in Reader, Übersicht und Stapel) und
  `tests/test_mail.py` (`mailto:`, Empfängerprüfung, Ergebnisse von `send_file`, Aufbau der MAPI-Strukturen
  für 64-Bit-Windows – ohne echtes E-Mail-Programm).
- Texterkennung: `tests/test_editor_ocr.py` – Scans aus `editorsamples.scanned` (aufrecht, `/Rotate`,
  CropBox, gemischt), Lage der Treffer, Darstellung, Rückgängig, Ersetzen, Speichern, Abbruch, fehlende
  Sprache. Tests mit Tesseract laufen nur, wenn eine Engine gefunden wird; die Textebene prüfen die
  übrigen auch ohne.
- KI-Assistent: `tests/test_assistant.py` (Katalog, Ablage, Abschnitte, Suche, Seitenangaben, Maskierung,
  Anweisungen, KI-Prozess und Anfragen mit der Attrappe `fixtures/fake_llama_server.py`) und
  `tests/test_qt_assistant.py` (Einrichten, Download über einen lokalen Testserver mit Weiterleitung und
  `Range`, Prüfsumme, Fragen mit Seitenverweisen, Zusammenfassen in Teilen, Abbrechen, Tabs, Ausschalten).
- Laufzeit und Setup: `tests/smoke_runtime.py` (Text direkt ändern, Schrift-Teilmenge einbetten,
  speichern, Texterkennung mit der gebündelten Engine, gebündelter llama-server mit einem Testmodell) und
  `tests/smoke_installer.ps1` (»Öffnen mit«, zweiter Start reicht die PDF weiter, Standard-App für PDF
  unverändert, KI-Laufzeit vorhanden, Deinstallation entfernt die Einträge und geladene Sprachmodelle).

## Bekannte Einschränkungen (3.2.0-beta.2)

- KI-Assistent: rechnet auf dem Prozessor; liest nur Text (keine Bilder); Fragen erhalten die passenden
  Abschnitte bis etwa 9.000 Zeichen, Zusammenfassungen höchstens etwa 60.000 Zeichen.

- Textauswahl innerhalb einer Seite (nicht über Seitengrenzen hinweg).
- Per E-Mail senden: Den Anhang setzt nur ein E-Mail-Programm mit Simple MAPI (z. B. Outlook, Thunderbird);
  sonst neue Nachricht ohne Anhang und die Datei im Explorer.
- Schwärzen: Seiten mit Inline-Bildern, Masken, JBIG2-Bildern oder unbekannten Schriften im Bereich werden
  ganz als Bild geschwärzt (dort ist danach kein Text mehr auswählbar). Text, der nur in Metadaten,
  Anhängen oder Lesezeichen steht, entfernt »Dokument bereinigen«, nicht das Schwärzen.
- Digitale Signaturen werden erkannt, aber noch nicht erstellt oder geprüft; Stempel und Unterschrift
  sind sichtbare Anmerkungen.
- XFA-Formulare: nur der AcroForm-Teil lässt sich ausfüllen, nicht gestalten; PDF-JavaScript
  (Berechnungen, Prüfungen) läuft nie.
- Texterkennung: gebündelt sind nur Deutsch und Englisch; Seiten, die schon Text haben (auch die
  Textebene eines anderen Programms), werden nicht erkannt – ersetzt oder entfernt werden nur
  Textebenen von PDF Tool.
- Text in Type3-Schriften und mit anderen CMaps als Identity-H/V wird nicht direkt geändert (neu
  gesetzt oder überlagert – der Hinweis nennt den Weg).
- Objekt bearbeiten:
  - **Direkt änderbar** ist nur Text, dessen Codes sich eindeutig den Zeichen zuordnen lassen.
    Das sind einfache Schriften und CID-Schriften mit Identity-H.
  - **Nur überlagert** werden Text in Formular-XObjects, senkrechter Text (Identity-V),
    Type3-Schriften und Seiten mit unklarer Struktur. Diese Texte lassen sich weder verschieben
    noch formatieren.
  - **Drehen** in 90°-Schritten (Schaltflächen, Kontextmenü); beliebige Winkel nicht.
  - **Noch nicht enthalten:** Einrasten beim Ziehen und manuelles Gruppieren.
  - **Bilder** wie im Bildwerkzeug: Bilder in Formular-XObjects und Inline-Bilder werden nur
    geändert, wo das sicher möglich ist.
