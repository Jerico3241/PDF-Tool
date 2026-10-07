# PDF Tool – Funktionen im Detail

Ausführliche Beschreibung der Werkzeuge mit Verweisen auf den Code. Die kurze Vorstellung steht in der
[README](../README.md), Änderungen je Version im [CHANGELOG](../windows-app/CHANGELOG.md) und in den
[Release Notes](../windows-app/release-notes/).

## Werkzeuge

Nach dem Start zeigt PDF Tool die Startseite: die Werkzeuge, eine Ablagefläche zum Öffnen von PDFs
und „Zuletzt verwendet“ (Name, Ordner, wann geöffnet, Größe). Oben liegt – nach dem Vorbild von
Adobe Acrobat – eine Tab-Leiste (seit 3.1.0-beta.4, `Shell/AppTabs.qml`):

- **≡ Menü:** PDF öffnen, Start, Einstellungen, Kurzanleitung, Neuerungen, Über PDF Tool.
- **⌂ Start** ganz links; jedes geöffnete Werkzeug (Vertragsübersichten, PDF reparieren,
  Einstellungen) und jedes geöffnete PDF ist ein Tab daneben, »+« öffnet weitere PDFs. Ein Werkzeug-Tab
  bleibt, bis man ihn schließt (×, mittlere Maustaste, Strg+W); Eingaben bleiben dabei erhalten.
- Rechts: Kurzanleitung (F1) und Einstellungen. Eine Seitenleiste gibt es nicht – PDFs und Werkzeuge
  haben die ganze Fensterbreite.

Eine Datei kann direkt in das Fenster gezogen werden: Auf der Startseite öffnen PDFs (eine oder
mehrere) den „PDF Reader & Editor“, eine Excel-Liste „Vertragsübersichten“; auf der Seite „PDF
reparieren“ werden PDFs zur Reparatur hinzugefügt. Der Reader erscheint mit dem geöffneten Dokument
(nie leer); nach dem letzten geschlossenen PDF geht es zur Startseite.

| Werkzeug | Zweck | Code |
| --- | --- | --- |
| **PDF Reader & Editor** (seit 3.0.0) | Öffnet PDFs in Tabs zum Lesen (Zoom, Ansichten, Miniaturen, Lesezeichen, Suche, Textauswahl, Links, Drucken) und Bearbeiten: Text direkt im PDF ändern oder hinzufügen, Bilder, Seiten organisieren und zuschneiden, Kommentare, Stempel und Unterschrift, Formulare, Lesezeichen, Links, Eigenschaften; vor dem Weitergeben schwärzen, bereinigen, mit Kennwort schützen, reduzieren, verkleinern, mit Kopf-/Fußzeile, Seitenzahlen oder Wasserzeichen versehen (seit 3.2) – mit Rückgängig, sicherem Speichern und Sitzungssicherung. Details: [PDF-EDITOR.md](PDF-EDITOR.md) | Fachlogik: `app/tools/pdf_editor/` · Controller: `app/qtapp/reader/` · Seiten: `app/qml/PdfTool/Reader/` |
| **Vertragsübersichten** | Erstellt professionelle Vertragsübersichten aus Excel-Dateien – einzeln oder als Stapel, mit Excel-Fettschrift, Vorlagen, Regelwerk, formatierten Kopf- und Fußzeilen, Textbausteinen, Zyklus-Regeln, Live-Vorschau, optionaler Kundenakte mit Wiedererkennung bekannter Kunden und Vertragsvergleich mit dem letzten Stand | Fachlogik: `app/tools/contract_overview/` (`overview.py`, `customers/` für die Kundenakte, `batch/` für den Stapel, `history/` für den Vertragsvergleich, `templates/` für Vorlagen, `rules/` für das Regelwerk), `app/engine.py`, `app/excelstyle.py`, `app/richtext.py`, `app/pdffonts.py` · Controller: `app/qtapp/contracts/` · Seiten: `app/qml/PdfTool/Pages/` |
| **PDF reparieren** | Analysiert beschädigte PDF-Dateien – eine oder mehrere auf einmal – und versucht, lesbare Inhalte in neue PDFs zu übertragen, bis zur Rekonstruktion der Dokumentstruktur aus den noch vorhandenen Objekten; Ausgabenamen je Datei, nie wird eine vorhandene Datei überschrieben | Fachlogik: `app/tools/pdf_repair/` (`batch.py` für Liste, Zustände und Ausgabenamen, `recovery/` für die erweiterte Wiederherstellung) · Controller: `app/qtapp/repair.py` · Seiten: `app/qml/PdfTool/Pages/RepairPage.qml`, `RepairItem.qml` |

Die Werkzeuge sind voneinander getrennt: Jedes hat eigene Seiten, eigene Einstellungen und eigene
Logik; gemeinsam sind nur Fenster, Tab-Leiste, Design und Dialoge (`app/qtapp/app.py`,
`app/qml/PdfTool/Shell/`, `app/qml/PdfTool/Controls/`). Neue Werkzeuge bekommen ein eigenes Paket
unter `app/tools/` (Fachlogik ohne Oberfläche), einen Controller unter `app/qtapp/`, eine Seite
unter `app/qml/PdfTool/Pages/` und einen Eintrag in `app/tools/registry.py` – siehe
[`windows-app/ARCHITECTURE.md`](../windows-app/ARCHITECTURE.md).

## PDF Reader & Editor: Schützen und Weitergeben (seit 3.2)

In der Werkzeugleiste des Readers stehen zwei neue Befehle: **Schützen** (Schild) und **Seiten gestalten**.
Alles läuft lokal; jede Änderung lässt sich rückgängig machen, solange das Dokument offen ist, und wird beim
Speichern geprüft. Technische Einzelheiten: [PDF-EDITOR.md](PDF-EDITOR.md#schützen-und-weitergeben-seit-32).

- **Schwärzen:** Bereiche aufziehen oder Text markieren, rot umrandet vorgemerkt; »Schwärzen anwenden«
  entfernt Text, Bildpunkte, Grafiken, Kommentare und Formularfelder im Bereich wirklich aus der Datei –
  nicht nur abgedeckt. **Suchen und schwärzen** merkt IBANs (mit Prüfziffer), E-Mail-Adressen,
  Telefonnummern, Datumsangaben und eigene Begriffe vor. Rechtsklick entfernt eine Markierung.
- **Dokument bereinigen:** Metadaten, Skripte und Aktionen, Anhänge, versteckte Daten und auf Wunsch
  Kommentare entfernen – vorher wird gezählt, was es gibt.
- **Kennwortschutz:** Kennwort zum Öffnen und/oder Einschränkungen (Drucken, Kopieren, Ändern …) mit einem
  eigenen Berechtigungskennwort; AES-256. Schutz ändern oder entfernen; bei eingeschränkten PDFs hebt das
  Berechtigungskennwort die Einschränkungen auf.
- **Reduzieren:** Formularfelder, Kommentare, Stempel und Unterschriften fest in die Seite übernehmen.
- **PDF verkleinern:** Kopie mit neu berechneten Bildern (Klein, Ausgewogen, Hoch); das Original bleibt.
- **Seiten gestalten:** Kopf- und Fußzeile mit Seitenzahl, Seitenanzahl, Datum, Dateiname und
  Bates-Nummer; Wasserzeichen (Text, Farbe, Deckkraft, Winkel, über oder hinter dem Inhalt); beides
  ersetzbar und wieder entfernbar. **Seiten zuschneiden** (Millimeter oder an den Inhalt angepasst),
  **Lesezeichen** hinzufügen.
- **Unterschreiben und Stempeln** (Werkzeug neben »Formular«): Unterschrift zeichnen oder aus einem Bild
  einlesen, auf Wunsch nur auf diesem PC speichern (höchstens sechs, jederzeit löschbar); Stempel wie
  GENEHMIGT, ENTWURF, VERTRAULICH oder eigener Text, mit Datum. Nach dem Setzen gleich verschieben und in
  der Größe ändern. Eine sichtbare Unterschrift ist keine digitale Signatur.
- **Links:** Mit »Auswählen« anklicken – Seiten springen, Webadressen öffnen nach Rückfrage. Werkzeug
  »Links«: Bereich aufziehen und mit einer Seite oder Webadresse verknüpfen; ändern und entfernen.
- **Lesezeichen bearbeiten:** in der Seitenleiste »Lesezeichen« über »Lesezeichen für Seite …« und das
  Kontextmenü – hinzufügen, umbenennen (F2), auf die angezeigte Seite setzen, verschieben, ein- und
  ausrücken, löschen (Entf).

## PDF Reader: Komfort und »Per E-Mail senden« (seit 3.2)

- **Tabs:** Rechtsklick auf einen Dokument-Tab – Schließen, Andere Tabs schließen, Tabs rechts schließen,
  Pfad kopieren, Im Ordner anzeigen. Tabs mit der Maus an eine andere Stelle ziehen (oder Strg+Umschalt+←/→).
  **Strg+Umschalt+T** öffnet das zuletzt geschlossene PDF wieder, auf der zuletzt gezeigten Seite.
- **Letzte Sitzung:** Einstellungen → PDF Reader → »PDFs der letzten Sitzung beim Start wieder öffnen«
  (standardmäßig aus). Gemerkt werden nur Pfade, Seiten und das aktive Dokument – in den Einstellungen auf
  diesem PC; das Support-Paket enthält davon nur die Anzahl. Fehlende oder geschützte Dateien übergeht der
  Start ohne Rückfrage.
- **Nachtmodus:** Seiten dunkelgrau mit heller Schrift (Ansicht-Menü oder Einstellungen) – nur die Anzeige;
  Datei, Drucken und Export bleiben unverändert.
- **Schnellwerkzeuge auf der Startseite:** PDF verkleinern, Schwärzen, Kennwortschutz, Wasserzeichen,
  Seitenzahlen, Dokument bereinigen, Unterschreiben, Zusammenführen – PDF wählen, sie öffnet sich im Reader,
  und das Werkzeug startet.
- **Per E-Mail senden** (Reader: »Weitere Befehle«; Vertragsübersichten: nach »PDF erstellen«; Stapel: Detail
  eines Eintrags): Das E-Mail-Programm öffnet eine neue Nachricht mit der PDF als Anhang – bei
  Vertragsübersichten an den Rechnungsempfänger, wenn seine Adresse bekannt ist. Gesendet wird nur dort,
  nie von PDF Tool. Ohne eingerichtetes E-Mail-Programm (Simple MAPI): neue Nachricht ohne Anhang über
  `mailto:`, die Datei ist im Explorer markiert. Code: `app/qtapp/mail.py`.

## PDF Reader: KI-Assistent (optional, seit 3.2)

Fragen zum geöffneten PDF beantworten und Dokumente zusammenfassen – vollständig auf diesem PC, mit
Seitenangaben. **Standardmäßig aus**; solange er aus ist, lädt PDF Tool nichts und startet keinen KI-Prozess.

- **Einrichten:** Einstellungen → KI-Assistent einschalten und ein Sprachmodell wählen – »Genau« (Qwen3.5 4B,
  2,6 GB, rund 5 GB Arbeitsspeicher beim Antworten) oder »Kompakt« (Qwen3.5 2B, 1,2 GB, rund 2 GB, etwa doppelt
  so schnell, etwas ungenauer); empfohlen wird das passende Modell für den Arbeitsspeicher des PCs. Geladen wird
  erst nach »Herunterladen«: über HTTPS von Hugging Face (Weiterleitungen nur zu dessen Speicher), feste
  Version, Prüfsumme (SHA-256) vor der ersten Nutzung; anhalten und fortsetzen möglich. Das Modell liegt in
  `%LOCALAPPDATA%\PDF-Tool-KI\modelle` – nicht in Sicherungen oder Support-Paketen; »Modell entfernen …« und die
  Deinstallation löschen es.
- **Im Reader:** rechte Seitenleiste »KI-Assistent« (Streifen am rechten Rand oder Kopf der Seitenleiste). Frage
  eintippen, Eingabetaste – die Antwort erscheint Stück für Stück und nennt die Seiten (»S. 3«); ein Klick springt
  dorthin. »Dokument zusammenfassen«, Vorschläge (Fristen und Termine, Beträge und Kosten, Beteiligte), Antwort
  anhalten, kopieren, »Neues Gespräch«. Jedes PDF-Tab hat sein eigenes Gespräch (nur im Arbeitsspeicher).
- **Wie er liest:** Der Text des PDFs wird in Abschnitte je Seite geteilt; für eine Frage sucht PDF Tool die
  passenden Abschnitte (bis etwa 9.000 Zeichen) und gibt nur diese mit Seitenzahl an das Modell, das nur daraus
  antworten soll. Zusammenfassungen lesen kurze Dokumente ganz, lange in bis zu fünf Teilen; reicht das nicht, nennt
  die Antwort die letzte gelesene Seite. Gescannte Seiten ohne Text: erst »Text erkennen (OCR)«.
- **Datenschutz:** Dokumente, Fragen und Antworten verlassen den PC nicht und werden nie gespeichert oder
  protokolliert. Der KI-Prozess (llama.cpp) lauscht nur auf 127.0.0.1 mit einem zufälligen Schlüssel, startet mit
  der ersten Frage und endet nach zehn Minuten ohne Frage, beim Ausschalten und mit PDF Tool. Antworten werden vor
  der Anzeige maskiert – Inhalte aus dem PDF können keine Bilder oder Verweise einschleusen.
- Antworten können Fehler enthalten – die Seitenangaben helfen beim Prüfen.

Code: `app/assistant/` (Katalog, Ablage, Text und Suche, Anweisungen, KI-Prozess, Anfragen),
`app/qtapp/assistant.py`, `Reader/AssistantPanel.qml`, Einstellungen-Karte »KI-Assistent«.

## Vertragsübersichten: Kundenakte und Kundenwiedererkennung

Das Werkzeug hat die Ansichten **Übersicht erstellen**, **Stapel**, **Darstellung**, **Vorschau**,
**Vorlagen**, **Regeln** und – mit eingeschalteter Kundenakte – **Vergleich** und **Kunden**. Reicht
die Breite nicht für alle Ansichten, lässt sich die Ansichtsleiste verschieben; die gewählte Ansicht
steht immer ganz im Bild. Die Kundenakte gehört ausschließlich zu
„Vertragsübersichten“; „PDF reparieren“ bleibt davon unberührt.

**Die Kundenakte ist optional (seit 2.6.1).** Einstellungen → **Vertragsübersichten** →
**„Kundenakte verwenden“** – Standard **aus**, bei einer neuen Installation und auch nach einem
Update (Opt-in). Die App fragt den Zustand zentral ab (Property `enabled` des Controllers in
`app/qtapp/contracts/customers.py`; gespeichert als `kundenakte_verwenden` in `gui-config.json`).

- **Ausgeschaltet** werden keine Kundendaten automatisch gespeichert oder abgeglichen – auch nicht im
  Hintergrund: `kundenakten.json` wird nicht gelesen, kein E-Mail-Abgleich, keine Übernahme, kein
  Fortschreiben nach der PDF, keine Zuordnungen, kein kundenbezogener Vertragsvergleich. Die Ansicht
  „Kunden“ wird gar nicht erst aufgebaut; „Bekannten Kunden auswählen“, „Bekannter Kunde gefunden“,
  „Als Kundenakte speichern“, „Zuordnung merken“ und die Kunden-Angaben im Stapel sind ausgeblendet.
  Firmenname, Kundennummer und Rechnungsempfänger bleiben normale Eingabefelder; Excel-Prüfung,
  Vorlagen, Kopf- und Fußzeile, Vorschau, Stapel und PDF-Erstellung arbeiten unverändert.
- **Vorhandene Daten bleiben immer erhalten:** Ausschalten löscht nichts – Kundenakten,
  Zuordnungen, Vertragsstände und ein Kundenverlauf aus 2.3 bleiben unverändert auf dem PC.
  Stammen Kopf- und Fußzeile gerade aus einer Kundenakte, bleibt die vorher gültige Fassung gemerkt
  („Neue Übersicht“ stellt sie wieder her) – die Standard-Fußzeile geht nie verloren.
- **Ein- und Ausschalten ohne Neustart:** Beim ersten Einschalten lädt die App die Kundenakten
  (ein Kundenverlauf aus 2.3 wird erst jetzt übernommen) und baut die Ansicht „Kunden“ verdeckt und
  fertig auf (`NavigationView.add_page`); danach wird sie nur noch zugelassen bzw. gesperrt
  (`set_available`) und in den Umschaltleisten ein- bzw. ausgeblendet – keine Navigation wird neu
  aufgebaut, keine Bindung doppelt registriert.
- **Bisherige Nutzer** sehen nach dem Update einmalig: „Die Kundenakte ist jetzt optional und kann
  in den Einstellungen aktiviert werden. Ihre gespeicherten Kundendaten bleiben erhalten.“
- Alle Kundendaten bleiben ausschließlich lokal auf diesem PC.

Mit eingeschalteter Kundenakte gilt:

**Excel-Prüfung ohne Doppelungen:** Die Statuszeile ist die einzige Stelle mit den Vertragszahlen
(„Excel geprüft · 5 aktive Verträge · 3 inaktiv ausgeblendet“, Einzahl „1 aktiver Vertrag“, ohne
„0 inaktiv“). Darunter stehen nur zusätzliche Angaben: der Rechnungsempfänger (bei mehreren
„3 erkannt“ mit Auswahl daneben), „Kunde · Nicht zugeordnet“, wenn das weiterhilft, Fettschrift und
Hinweise. Ein erkannter Kunde erscheint einmal – als Hinweis mit Aktionen in der Dateikarte, nach dem
Übernehmen als aktive Kundenakte in den Kundendaten.

- **Kundenakte 2.0:** stabile ID (UUID), Firmenname, Kundennummer, mehrere
  Rechnungsempfänger-E-Mails (die erste ist primär), optionale Notiz, bevorzugtes Logo, bevorzugter
  Zielordner, bevorzugte Vorlage („Vorlage automatisch verwenden“), eigene Kopf- und Fußzeile mit
  Formatierung sowie die letzte Aktivität (letzte Excel, letzte PDF, zuletzt verwendet). Es werden
  nur Pfade gespeichert – PDF- und Excel-Dateien werden nie kopiert.
- **Wiedererkennung nach der Excel-Prüfung:** Die Rechnungsempfänger der Excel werden mit den
  gespeicherten Zuordnungen verglichen – normalisiert wird nur zurückhaltend (Leerzeichen am Rand,
  Groß-/Kleinschreibung; `+Tags`, Punkte und Domains bleiben unverändert). Ergebnis
  (`customers/matching.py`): kein Treffer, genau ein Kunde (auch mit mehreren seiner Adressen),
  mehrdeutige Zuordnung oder Adressen verschiedener Kunden. Bei genau einem Kunden erscheint der
  Hinweis „Bekannter Kunde gefunden“ mit **Übernehmen**, **Kundenakte** und **Ignorieren**; bei
  verschiedenen Kunden entscheidet der Benutzer. Ein unbekannter Kunde ist normal und kein Fehler;
  die Wiedererkennung blockiert nie die PDF-Erstellung.
- **Nichts wird geraten:** Firmenname und Kundennummer stammen nur aus der Kundenakte oder aus
  Spalten der Excel-Datei – nie aus einer E-Mail-Adresse oder Domain. Es gibt keine
  Internetsuche, keine Domain-Auflösung und keine externe Datenbank.
- **Automatisch übernehmen** (Einstellung in „Kunden“, Standard: aus): nur bei genau einem
  bekannten Kunden, ohne aktive Kundenakte und ohne abweichende eingetragene Kundendaten –
  rückgängig machbar.
- **Arbeitskopie statt stiller Änderung:** Übernehmen füllt das Formular (Firma, Kundennummer,
  Logo und Zielordner, falls vorhanden – sonst bleibt der aktuelle Wert mit Hinweis, Vorlage nach
  Regel, Kopf- und Fußzeile nur, solange sie in dieser Übersicht nicht geändert wurden). Änderungen
  im Formular ändern die Kundenakte nie; „Kundenakte aktualisieren“ zeigt die Abweichungen und
  speichert nur die gewählten. Automatisch fortgeschrieben werden nur „zuletzt verwendet“, letzte
  Excel und letzte PDF. Eine leere Fußzeile ersetzt nie die gültige; die Standard-Fußzeile bleibt.
- **Lernen nur bewusst:** Neue Kundenakten entstehen nur über „Als Kundenakte speichern“ (mit
  „Zuordnung merken“); neue Adressen eines bekannten Kunden werden angeboten („Diese E-Mail
  künftig diesem Kunden zuordnen?“). Gehört eine Adresse schon einem anderen Kunden, fragt die App:
  „Bestehende Zuordnung verwenden“, „Zuordnung verschieben“ oder „Abbrechen“ – eine Adresse ist nie
  still zwei Kunden zugeordnet.
- **Ansicht „Kunden“:** Liste mit Suche (Firma, Kundennummer, E-Mail), Sortierung (zuletzt
  verwendet, Firma A–Z, Kundennummer), Detailansicht zum Bearbeiten, E-Mail-Adressen hinzufügen
  und entfernen, Hinweis auf mögliche Doppelungen, Zusammenführen nur auf Wunsch und Löschen mit
  Rückfrage (entfernt nur Kundenakte und Zuordnungen, nie Dateien). Die Liste bleibt auch mit
  hunderten Kundenakten flüssig (virtualisierte QML-Liste, Suche entprellt); Tastatur: Pfeiltasten,
  Eingabe, Strg+F.
- **Speicher:** `%APPDATA%\PDF-Tool\kundenakten.json` mit `schema_version: 2`, atomar geschrieben
  (temporäre Datei, dann Ersetzen) mit `.bak` als vorigem Stand; eine unlesbare Datei wird
  beiseitegelegt statt überschrieben. Bewusst ohne Datenbank, Server oder Konto.
- **Übernahme aus 2.3:** Beim ersten Start mit 2.4 (oder neuer) wird der bisherige Kundenverlauf
  (`kunden` in `gui-config.json`) einmalig zu Kundenakten – vorher sichert die App die
  Konfiguration byte-genau nach `sicherungen\gui-config-vor-kundenakte-<Zeit>.json`. Schlägt die
  Übernahme fehl, bleibt der alte Verlauf unverändert und die App versucht es beim nächsten Start
  erneut. Code: `app/tools/contract_overview/customers/migration.py`.

## Vertragsübersichten: Stapelverarbeitung

Die Ansicht **Stapel** erstellt viele Vertragsübersichten in einem Durchlauf – als eigene
Arbeitsweise neben dem unveränderten Einzelmodus. Code: `app/tools/contract_overview/batch/`.

- **Mehrere Excel-Dateien:** „Excel-Dateien hinzufügen“ (Mehrfachauswahl), „Ordner hinzufügen“
  (nicht rekursiv) oder mehrere Dateien in das Fenster ziehen (nur auf der Ansicht „Stapel“; im
  Einzelmodus bleibt es bei einer Excel). Doppelte Dateien werden über normalisierte Pfade erkannt.
- **Automatische Analyse** im Hintergrund (`batch/analyzer.py`): dieselbe Prüfung wie im
  Einzelmodus (`engine.pruefe_excel`), nacheinander in genau einem Thread, Ergebnisse gebündelt an
  die Oberfläche. Innerhalb der Sitzung wird eine unveränderte Datei (Größe und Änderungszeit)
  nicht erneut gelesen; eine geänderte wird vor der Verarbeitung neu geprüft – ändert sich dabei,
  was die Kundenzuordnung bestimmt, wird der Eintrag nicht verarbeitet.
- **Kundenerkennung:** dieselbe Zuordnung wie im Einzelmodus (`CustomerStore.match`). Eindeutig
  erkannt → „Bereit“, sofern alles andere vorhanden ist; unbekannt → „Angaben erforderlich“
  (Firmenname und Kundennummer eintragen oder Kunden wählen); Empfänger verschiedener Kunden,
  mehrdeutige Zuordnung oder eine abweichende Kundennummer in der Excel → der Benutzer entscheidet.
  Neue E-Mail-Zuordnungen nur mit „Zuordnung merken“.
- **Datenmodell** (`batch/models.py`): `BatchItem` mit ID, Pfad, Prüfergebnis und Dateistand,
  Kundenzuordnung (automatisch, gewählt, keine), eigenen Angaben (`Overrides`), Status
  (`ItemStatus`: pending, analyzing, ready, needs_input, processing, success, warning, failed,
  skipped), Hinweisen, Ausgabe und Fehler. Die geltenden Werte bestimmt `batch/resolver.py` jedes
  Mal neu – geänderte Kundenakten gelten sofort, eigene Angaben bleiben.
- **Vorrang:** Vorlage: Eintrag → Kundenakte → Standardvorlage des Stapels → „Darstellung“. Logo:
  Eintrag → Kundenakte → Standardlogo des Stapels → installiertes Standardlogo (ein Vorlagenlogo gilt
  auf der Stufe, auf der die Vorlage gewählt wurde). Zielordner: Eintrag → Kundenakte (abschaltbar) →
  Stapel, optional mit Unterordner je Kunde. Kopf-/Fußzeile: im Eintrag gewählte Vorlage → eigene
  Texte der Kundenakte → Vorlage → „Darstellung“; eine leere Fußzeile ersetzt nie die gültige.
- **Verarbeitung** (`batch/processor.py`): nur bereite Einträge, nacheinander (Stabilität vor
  Tempo), mit derselben PDF-Engine wie der Einzelmodus. Die Werte eines Eintrags werden unmittelbar
  vor seiner Verarbeitung bestimmt. Jeder Fehler bleibt beim Eintrag – ein Fehler bei Datei 4 hält
  Datei 5 nicht auf. Fortschritt „7 von 20 Übersichten erstellt“ samt aktuellem Eintrag,
  „Stapel abbrechen“ (die laufende PDF endet am nächsten sicheren Punkt), „Fehlgeschlagene erneut
  versuchen“ (nur fehlgeschlagene; Datei-Probleme werden neu geprüft), Ergebnis „Stapel
  abgeschlossen“ mit „Ausgabeordner öffnen“, „Fehler anzeigen“ und „Neuer Stapel“.
- **Sichere Ausgabe:** Die Engine schreibt jede PDF zuerst als temporäre Datei in den Zielordner und
  bringt sie erst fertig an ihren Platz (auch im Einzelmodus) – ein Abbruch oder Fehler hinterlässt
  nie eine halbe PDF. Dateinamen wie im Einzelmodus (`Vertragsuebersicht_Kd{kd}.pdf`); gibt es die
  Datei schon: automatisch nummerieren (Standard, `…_2.pdf`), überspringen oder überschreiben – nie
  eine im selben Lauf erstellte Datei.
- **Vorschau eines Eintrags:** dieselbe Vorschau-Pipeline wie im Einzelmodus, nur mit dem Auftrag des
  Eintrags; es wird nie für alle Einträge gleichzeitig gerendert.
- **Kundenakte:** Nach einer Erstellung werden nur „zuletzt verwendet“, letzte Excel und letzte PDF
  fortgeschrieben – nie Darstellungswerte des Stapels.
- **Sicherung:** Der Stapel wird in `stapel.json` gesichert (nur Pfade, Zuordnungen, eigene Angaben
  und Ergebnisse – keine Kopien); technische Fehler stehen in `stapel.log` (ohne Excel-Inhalte und
  ohne vollständige Pfade).

Gemeinsame Fachlogik von Einzel- und Stapelmodus liegt in `app/tools/contract_overview/overview.py`
(Excel-Analyse als Datentyp, Statuszeile, Validierung, PDF-Auftrag, Vorlagenwerte) – es gibt keinen
zweiten PDF-Generator und keine zweite Kundenerkennung.

## Vertragsübersichten: Vertragsänderungen

Nach der Excel-Prüfung zeigt die Karte **Vertragsänderungen**, was sich seit dem letzten Stand der
aktiven Kundenakte geändert hat – „Seit 12.08.2026“, darunter „2 neu · 1 entfernt · 1 geändert ·
4 unverändert“ in den Statusfarben (Neu grün, Entfernt rot, Geändert gelb, Unverändert neutral).
Prominent sind nur die Änderungen; „4 unveränderte anzeigen“ blendet den Rest ein, geänderte
Verträge klappen mit den geänderten Feldern auf („Netto: 250,00 € → 270,00 €“). „Vergleichen mit“
wählt einen früheren Stand (Standard: „Letzter Stand“), „Änderungen kopieren“ legt den Vergleich als
Text in die Zwischenablage. Code: `app/tools/contract_overview/history/` (Modelle, Ablage, Vergleich,
Texte), `app/qtapp/contracts/comparison.py` (Ablauf und Anzeige-Modell), `ComparisonPage.qml` und
`ChangeRow.qml` (Anzeige).

- **Stand = strukturierte Daten, keine PDF:** Nach jeder erfolgreich erstellten PDF speichert
  PDF Tool die Verträge genau so, wie sie in der PDF stehen (Vertragsnummer, Art, Beschreibung,
  Beginn, Abrechnungszyklus nach den Zyklus-Regeln, Netto, Zahlungsart) plus die Rohwerte der Excel.
  Alte PDFs werden nie gelesen oder geparst; ein Vergleich funktioniert auch, wenn die alten Excel-
  und PDF-Dateien längst gelöscht sind. Kein Stand entsteht für die Live-Vorschau, die Excel-Prüfung,
  einen Abbruch, einen Fehler oder ohne Kundenakte. Ist die Kundenakte ausgeschaltet, fehlt die
  sichere Kundenidentität: Die Karte bleibt verborgen, nichts wird über Firmenname, Domain oder
  Rechnungsempfänger geraten, und gespeicherte Stände bleiben unverändert erhalten.
- **Identität:** Ein Stand gehört allein zur stabilen ID der Kundenakte – nie zu Firmenname,
  Kundennummer oder E-Mail-Ähnlichkeit. Ein Vertrag ist seine Vertragsnummer als Text (`001234`
  bleibt `001234`); eine neue Nummer ist „entfernt“ plus „neu“, nie eine Umbenennung.
- **Normalisierung:** Datum als ISO-Datum, Beträge als Dezimalzahl mit zwei Nachkommastellen
  (`250`, `250,0` und `250.00 €` sind gleich), Texte ohne Unterschiede bei Zeilenenden und Leerzeichen
  am Rand. Formatierung (z. B. Excel-Fettschrift) ist kein Vertragsinhalt und zählt nicht.
- **Vergleich:** neu, entfernt, geändert (mit Feld, altem und neuem Wert) und unverändert; doppelte
  Vertragsnummern werden in ihrer Reihenfolge zugeordnet.
- **Ablage:** `%APPDATA%\PDF-Tool\contract-history\<Kunden-ID>\<Zeit>-<ID>.json` – je Stand eine
  kleine JSON-Datei mit `schema_version: 1`, atomar geschrieben (temporäre Datei, dann ersetzen).
  Neben den Verträgen stehen Zeitpunkt, Kundenname zur Anzeige, Pfad und SHA-256 der Excel und der
  Pfad der PDF. Bewusst ohne Datenbank.
- **Keine Doppelungen:** Ein deterministischer SHA-256 über die normalisierten Vertragsdaten
  (unabhängig von der Reihenfolge) erkennt einen unveränderten Stand; ein erneuter Export legt dann
  keinen neuen Stand an, sondern zählt nur mit („2× erstellt, zuletzt …“).
- **Aufbewahrung:** Je Kunde bleiben die letzten 50 unterschiedlichen Stände; beim Speichern eines
  neuen Stands wird der älteste darüber entfernt. Beschädigte Dateien oder Dateien einer neueren
  Version werden übersprungen, nie gelöscht. Werden Kundenakten zusammengeführt, gehören beide
  Verläufe zum Ziel; wird eine Kundenakte gelöscht, bleiben ihre Stände erhalten (Rückgängig ist
  möglich) und werden erst mit den übrigen Benutzerdaten bei der Deinstallation entfernt.
- **Einführung ohne Altdaten:** Beim Update entstehen keine künstlichen Stände. Der erste Export
  mit Kundenakte meldet „Erster Vertragsstand gespeichert“, ab dem nächsten Excel-Import gibt es
  einen Vergleich; bis dahin steht dort „Noch kein früherer Vertragsstand vorhanden.“
- **Stapel:** Jeder erfolgreich erstellte Eintrag mit Kundenakte speichert seinen eigenen Stand
  (übersprungene und fehlgeschlagene nie). Die Liste zeigt kompakt „+2 neu · ~1 geändert“, die
  Detailansicht den vollständigen Vergleich mit „Vergleichen mit“ und „Änderungen kopieren“.
- **Reine Anzeige:** Der Vergleich ändert die PDF nicht, druckt nichts in die Übersicht und löst
  keine neue Vorschau aus.

## Vertragsübersichten: Vorlagen (seit 2.8)

Eine **Vorlage** hält die ganze Darstellung fest: Seitenformat, Logo und Logo-Breite, Titel,
Untertitel, Dateiname, Kopf- und Fußzeile mit Formatierung, Zyklus-Regeln und das Regelwerk. Jede
Vorlage ist eine eigene Datei (`vorlagen\<ID>.json`) mit fester ID und Schema-Version; ihre
Verwendung in Kundenakten und im Stapel verweist auf die ID – Umbenennen ändert nichts an diesen
Verweisen. Code: `app/tools/contract_overview/templates/`, `app/qtapp/contracts/templates.py`.

- **Ansicht „Vorlagen“:** Liste mit Suche, Detail mit Inhalt, Beschreibung und Verwendung;
  „In die Darstellung laden“, „Laden und bearbeiten“, „Umbenennen …“, „Duplizieren“, „Löschen“.
  Löschen nennt, wo die Vorlage verwendet wird; Kundenakten verwenden danach keine bevorzugte
  Vorlage, der Stapel „Automatisch“, die Standardvorlage entfällt – nie bleibt ein Verweis ins Leere.
- **„Darstellung“:** Auswahl der geladenen Vorlage. Weicht die Darstellung von ihr ab, erscheint
  „Vorlage geändert“ mit „Vorlage aktualisieren“ (gleiche ID, neuer Inhalt), „Änderungen verwerfen“
  und „Als neue Vorlage speichern“ (Name wird sofort geprüft, auch ohne Rücksicht auf
  Groß-/Kleinschreibung). Bearbeitet wird eine Vorlage immer hier – kein zweiter Editor.
- **Standardvorlage:** Wird für jede neue Übersicht geladen („Neue Übersicht“, rückgängig machbar)
  und gilt im Stapel als vierte Stufe: Vorlage des Eintrags → bevorzugte Vorlage der Kundenakte →
  Vorlage des Stapels → Standardvorlage → aktuelle Darstellung.
- **Übernahme aus 2.7:** Beim ersten Start werden die Vorlagen der Einstellungen einmalig als
  Vorlagen 2.0 übernommen; die bisherige Liste bleibt unverändert stehen. Beschädigte oder neuere
  Vorlagendateien werden übersprungen und gemeldet, nie gelöscht.

## Vertragsübersichten: Regelwerk (seit 2.8)

Ein **Regelwerk** passt Werte der Übersicht nach festen Regeln an – „WENN die Beschreibung
‚Energie‘ enthält, DANN die Art auf ‚Energievertrag‘ setzen“. Code:
`app/tools/contract_overview/rules/` (`models.py`, `evaluate.py`, `repository.py`),
`app/qtapp/contracts/rules.py`.

- **Bedingungen:** auf die Felder der Übersicht – Text (Art, Beschreibung, Abrechnungszyklus,
  Zahlungsart, Vertragsnummer: ist gleich, enthält, beginnt mit, endet mit, ist leer …), Zahl (Netto:
  gleich, größer als, kleiner oder gleich …) und Datum (Beginn: vor, nach, am); verknüpft mit „alle“
  oder „mindestens eine“. Ohne Bedingung gilt eine Regel für alle Verträge.
- **Aktionen:** setzen, Text ersetzen (Groß-/Kleinschreibung egal), voranstellen, anhängen, leeren –
  für Art, Beschreibung, Abrechnungszyklus und Zahlungsart. Vertragsnummer, Beginn und Netto ändert
  kein Regelwerk. Es gibt keine Skripte, keinen Code und keine regulären Ausdrücke.
- **Reihenfolge:** Die Regeln laufen von oben nach unten und prüfen die aktuellen Werte (einschließlich
  der Änderungen früherer Regeln); ändern zwei Regeln dasselbe Feld, gilt die spätere. Gleiche
  Eingaben ergeben immer dasselbe Ergebnis.
- **Ansicht „Regeln“:** Regelwerke anlegen, umbenennen, duplizieren, ein- und ausschalten, löschen;
  je Regel eine Karte mit lesbarer Zusammenfassung, visuellem Editor („WENN … DANN …“), nach oben und
  unten verschieben, duplizieren, entfernen (mit „Rückgängig“), ein- und ausschalten. Gespeichert
  wird automatisch. Unvollständige Regeln bleiben gespeichert, werden aber nie ausgeführt – die
  Karte nennt den Grund.
- **Testmodus und Vorschau:** Mit der geprüften Excel aus „Übersicht erstellen“ zeigt jede Regel, auf
  wie viele Verträge sie zutrifft, die Vorschau vorher → nachher je Vertrag samt Konflikten.
  Gerechnet wird im Hintergrund. Auch ein ausgeschaltetes Regelwerk oder eine ausgeschaltete Regel
  zeigt, was sie täte.
- **Wirkung:** Das Regelwerk der Übersicht wählt man in „Darstellung“ (oder es kommt mit einer
  Vorlage). Es wirkt auf PDF, Vorschau, Stapel und den gespeicherten Vertragsstand – nie auf die
  Excel-Datei. „Übersicht erstellen“ nennt, was es an der Excel ändert. Im Stapel hat jeder Eintrag
  „Automatisch“ (Regelwerk der Vorlage, sonst der Darstellung), „Kein Regelwerk“ oder ein bestimmtes.
  Ein fehlendes Regelwerk wird nie still ersetzt.

## Sicherung und Wiederherstellung (seit 2.8)

Einstellungen → „Sicherung & Wiederherstellung“. Code: `app/backup/`, `app/qtapp/backups.py`.

- **Inhalt:** Einstellungen samt Darstellung, Textbausteinen und Zyklus-Regeln, Stapel, Kundenakten
  mit Vertragsständen, Vorlagen und Regelwerke – in einer Datei `.pdtbackup` (ZIP mit
  `manifest.json`: Format- und App-Version, Zeitpunkt, Art, Bereiche, je Datei Größe und SHA-256).
  Nie enthalten: Excel- oder PDF-Dateien, Logos, Protokolle, andere Sicherungen.
- **Erstellen:** atomar – die Datei entsteht als temporäre Datei, wird vollständig nachgeprüft und
  erst dann sichtbar. „Jetzt sichern …“ legt sie in einem Ordner Ihrer Wahl ab (z. B. USB-Stick).
- **Automatisch** (Standard: an): höchstens einmal am Tag und nur, wenn sich die Daten geändert
  haben, dazu vor jedem Update und vor jeder Wiederherstellung; Ordner wählbar (Standard:
  `%APPDATA%\PDF-Tool\Sicherungen`). Es bleiben die letzten 10 automatischen Sicherungen und je 5
  vor Updates und Wiederherstellungen. Manuelle Sicherungen werden nie automatisch gelöscht.
- **Wiederherstellen:** Sicherung wählen → vollständige Prüfung (Format, Pfade, Größen, SHA-256,
  Schema-Versionen) → Zusammenfassung mit Auswahl der Bereiche → Sicherung des aktuellen Stands →
  Neustart. Die Wiederherstellung läuft vor dem Laden der Daten, je Bereich atomar und mit Journal:
  Scheitert ein Schritt oder bricht der Vorgang ab, wird alles zurückgenommen. Eine Sicherung einer
  neueren Version wird nie eingespielt („Dieses Backup wurde mit einer neueren Version von PDF Tool
  erstellt.“); ältere Datenstände übernimmt PDF Tool beim Laden wie bei einem Update.

## Diagnose (seit 2.8)

Einstellungen → „Diagnose“. Code: `app/diagnostics/`, `app/qtapp/diagnose.py`.

- **Systeminformationen:** Version, Update-Kanal, Python, PySide6/Qt, Windows, Architektur, Daten-
  und Programmordner, Reparatur-Engines, Versionen der Module.
- **Datenprüfung:** liest Einstellungen, Kundenakten, Vorlagen, Regelwerke und Vertragsstände und
  prüft Sicherungsordner, temporären Ordner und freien Speicher – ohne etwas zu verändern.
- **Support-Paket:** ZIP mit Bericht, Versionen, anonymisierten Einstellungen (nur Schalter, Zahlen
  und Anzahlen) und bereinigten Protokollen (Pfade zu Dokumenten, Benutzerordner, Benutzer- und
  Computername, E-Mail-Adressen und bekannte Firmen entfernt). Nie enthalten: Kundendaten,
  Vertragsinhalte, Passwörter, PDF- oder Excel-Inhalte, Logos. Es wird nichts versendet.
- **Protokoll:** `pdf-tool.log` (INFO, WARNING, ERROR) mit Rotation (höchstens 1 MB, drei ältere
  Dateien); eigene temporäre Dateien früherer Sitzungen werden beim Start aufgeräumt – nie fremde.

## Vertragsübersichten: Live-Vorschau

Die Ansicht **Vorschau** erzeugt die PDF genau wie „PDF erstellen“, nur in einen privaten
temporären Ordner, und zeigt sie seitenweise (PDFium) – mit Seitennavigation (Bild ↑/↓), Zoom
(+/−, „An Breite anpassen“) und Verschieben breiter Seiten. Jede Änderung (auch das Übernehmen
eines Kunden) markiert die Vorschau als veraltet; neu erzeugt wird entprellt im Hintergrund und nur,
solange die Ansicht sichtbar ist. Eine Signatur aller Eingaben verhindert, dass ein veraltetes
Ergebnis angezeigt wird (schneller Wechsel Kunde A → B). Code: `app/tools/contract_overview/preview.py`.

Sichtbarkeit ist keine Änderung: Wer ohne Änderung zur Vorschau zurückkehrt, bekommt dieselbe PDF
und dasselbe, bereits dekodierte Seitenbild – nichts wird neu erzeugt oder neu gezeichnet. Zoom und
Blättern rendern nur die jeweilige Seite (Seitenbilder bleiben zwischengespeichert). Für eine noch
entstehende Seite wird der Platz vorab reserviert – beim ersten Öffnen schon, während die PDF noch
entsteht (A4 hoch oder quer laut „Darstellung“) –, damit das Bild ohne Layoutsprung erscheint.
Seitenzahl und Zoomstufe haben eine feste Breite, der Zustand („Vorschau wird erstellt …“,
„Aktuell · …“) eine eigene Zeile: Die Werkzeugleiste bricht nicht je nach Zustand um.

## Technik: Oberfläche und Architektur (seit 2.7.0)

- **UI:** PySide6 6.11.2 (Qt 6, Qt Quick/QML), eigene Windows-11-nahe Steuerelemente auf Basis von
  Qt Quick Templates (`app/qml/PdfTool/Controls/`), Design-Tokens für Farben, Abstände, Radien,
  Schrift (Segoe UI Variable) und Animationsdauern (`app/qml/PdfTool/Style/`).
- **Backend:** Python – die Fachlogik ist dieselbe wie bis 2.6.1 und enthält keinen Oberflächencode.
- **Qt-Brücke:** `QObject`-Controller je Bereich (`app/qtapp/`: `App`, `Settings`, `Contracts`,
  `Customers`, `Preview`, `Batch`, `Comparison`, `Templates`, `Rules`, `Repair`, `Updates`, `Backup`,
  `Diagnose`) sind die einzige Verbindung zwischen QML
  und Fachlogik; Listen (Stapel, Kunden, Vertragsänderungen, Vorlagen …) sind
  `QAbstractListModel`s mit gezielten Änderungen (`insertRows`/`removeRows`/`moveRows`/`dataChanged`)
  statt Neuaufbau.
- **Hintergrundarbeit:** Excel-Prüfung, PDF, Vorschau und Stapel laufen in Threads, „PDF reparieren“
  in eigenen Arbeitsprozessen; Ergebnisse kommen über Qt-Signale in den GUI-Thread – Hintergrund-Threads
  berühren nie QML.
- **Start:** Konfiguration → Qt-Anwendung → Design → Controller → QML-Engine → verborgenes Fenster
  (DWM-Cloaking) → Startseite (bei „Öffnen mit“ der Reader); das Fenster erscheint mit dem ersten fertig
  gezeichneten Bild, in dem diese Seite schon steht. Weitere Seiten laden danach im Hintergrund, danach
  die PDF-Bibliotheken (pikepdf, PDFium) – beim Start mit einer PDF gleich zu Beginn. Die QML-Oberfläche kommt im Setup aus einer eingebauten
  Qt-Ressource (`qrc:/qml`, unabhängig vom Arbeitsverzeichnis).
- **Animationen:** Profil „Vollständig“, „Reduziert“ oder „Aus“ (Einstellungen → Verhalten →
  Animationen); ist in
  Windows „Animationseffekte“ aus, gilt mindestens „Reduziert“. Seitenwechsel (Aus-/Einblenden mit
  leichter Bewegung), Markierung des aktiven Tabs, Menüs, Tooltips, Aufklappbereiche, InfoBars, Dialoge,
  Schaltflächen, Schalter und Statuswechsel sind animiert; alle Dauern stehen zentral in
  `Style/Motion.qml` und gelten sofort ohne Neustart.
- **Anzeige:** Hell/Dunkel/„Wie Windows“ und Windows-Akzentfarbe live, Mica (nur wenn Windows es
  zuverlässig unterstützt), Skalierung 100–200 % (Qt High-DPI), Layout mit einer oder zwei Spalten
  je nach Breite.

Details für Mitwirkende: [`windows-app/ARCHITECTURE.md`](../windows-app/ARCHITECTURE.md) und
[`windows-app/QML_STYLE.md`](../windows-app/QML_STYLE.md).

## PDF reparieren

- **Eine oder mehrere PDFs (seit 2.7.1):** Mehrfachauswahl im Dialog, mehrere Dateien zugleich
  in das Fenster ziehen, später weitere hinzufügen; dieselbe Datei (Pfad ohne Rücksicht auf
  Groß-/Kleinschreibung) wird nur einmal aufgenommen, andere Dateien mit Hinweis übergangen.
  Jede Datei wird für sich analysiert – höchstens zwei Arbeitsprozesse gleichzeitig, repariert
  wird nacheinander. Zustände je Datei: `PENDING`, `ANALYZING`, `READY`, `ENCRYPTED`,
  `UNREADABLE`, `REPAIRING`, `REPAIRED`, `PARTIALLY_RECOVERED`, `FAILED`, `CANCELLED`, `SKIPPED`
  (`app/tools/pdf_repair/batch.py`; Entscheidungen nie anhand von Texten). „Alle reparieren“
  nimmt die beschädigten Dateien, „Nur diese Datei reparieren“ eine einzelne; „Abbrechen“ beendet
  den laufenden Arbeitsprozess (Arbeitsordner wird gelöscht) und lässt die noch nicht begonnenen
  aus – fertige Dateien bleiben. Ein Fehler betrifft nur seine Datei; nur ein globaler Fehler
  (kein Schreibzugriff, Datenträger voll) hält den ganzen Durchlauf an. Fortschritt gesamt
  („3 / 8 Dateien“) und je Datei (Analyse → Reparatur → Validierung → Fertig), Zusammenfassung
  („5 erfolgreich repariert · 1 teilweise wiederhergestellt · 1 fehlgeschlagen“) mit
  „Ausgabeordner öffnen“ und „Fehlgeschlagene erneut versuchen“. Es gibt keine eigene
  „Batch-Engine“: Jede Datei läuft genau wie im Einzelmodus durch `engine.analyze` /
  `engine.repair` in einem eigenen Arbeitsprozess.
- **Ausgabenamen:** Schalter „„repariert“ an Dateinamen anhängen“ (Standard ein,
  `reparatur_anhaengen`; fehlt die Einstellung nach einem Update, gilt ein) mit änderbarem Zusatz
  (`reparatur_zusatz`, Standard `_repariert`). Jeder Eintrag zeigt seinen Ausgabenamen und lässt ihn
  ändern (ohne Endung – `.pdf` wird ergänzt); Windows-Regeln (`< > : " / \ | ? *`, reservierte
  Namen wie `CON`, keine leeren Namen, kein Punkt am Ende) werden sofort geprüft. Eigene Namen
  (`MANUAL`) bleiben, wenn sich die Regel ändert, bis „Automatischen Namen wiederherstellen“.
  Konflikte – vorhandene Datei (ohne Rücksicht auf Groß-/Kleinschreibung), das Original selbst oder
  ein Name, den schon eine andere Datei der Liste bekommt (auch gleich benannte PDFs aus
  verschiedenen Ordnern in einem gemeinsamen Ausgabeordner) – lösen sich durch Nummerierung:
  `Rechnung_repariert (1).pdf`, `(2)` … Beim Start werden die Namen reserviert; gespeichert wird
  exklusiv, eine vorhandene Datei wird nie überschrieben.
- **Analyse vor der Reparatur:** Größe, Seiten, PDF-Version, Verschlüsselung, Querverweistabelle,
  Objekte, Trailer, Seitenbaum, Metadaten, Datenströme, Formulare, Anhänge und digitale Signaturen.
  Ergebnis: „Keine Fehler gefunden“, „Reparierbare Probleme erkannt“, „Schwer beschädigt“,
  „Erweiterte Wiederherstellung möglich“ oder „Keine Reparatur möglich“.
- **Mehrstufig:** (1) Neuaufbau mit qpdf (pikepdf), (2) Übertragen der lesbaren Seiten in ein neues
  Dokument, (3) zweite Engine PDFium (pypdfium2), (4) dritte, tolerante Engine pypdf, (5)
  Rohrekonstruktion der Dokumentstruktur (siehe unten). Die geprüfte Ausgabe mit den meisten
  vollständigen Seiten wird verwendet. Seiten werden nicht standardmäßig in Bilder umgewandelt; der
  Rettungsmodus „Lesbare Seiten als neue PDF retten“ tut das nur nach Bestätigung.
- **Ehrliche Ergebnisse:** repariert, teilweise wiederhergestellt („12 von 15 Seiten …“) oder
  nicht reparierbar – ohne Garantieversprechen. Nicht übernommene Bestandteile (z. B. Lesezeichen,
  Anhänge, gültige Signaturen) werden genannt.
- **Original bleibt unverändert:** Es wird nur gelesen; vor und nach der Verarbeitung wird die
  SHA-256-Prüfsumme verglichen; es wird nie verändert, umbenannt oder gelöscht. Die Ausgabe heißt
  `<Name>_repariert.pdf` (bei Bedarf `<Name>_repariert (1).pdf` …, siehe oben) und entsteht neben dem
  Original oder in einem gemeinsamen Ausgabeordner. Bei einem Fehler bleibt keine Ausgabe zurück.
- **Verschlüsselte PDFs** lassen sich mit dem richtigen Passwort reparieren; die Kopie bleibt
  verschlüsselt. Das Passwort gilt nur für seine Datei (nie für andere PDFs der Liste), wird nie
  gespeichert oder protokolliert, Passwortschutz wird nicht umgangen.
- **Signaturen und Rettungsmodus in der Liste:** Signierte Dateien sind gekennzeichnet; vor der
  Reparatur fragt die App einmal („Alle reparieren“ oder „Signierte überspringen“). Der
  Rettungsmodus (Seiten als Bilder) gilt nur für die einzelne Datei und nur nach Bestätigung –
  „Alle reparieren“ verwendet ihn nie.
- **Arbeitsprozess:** Analyse und Reparatur laufen in einem eigenen Prozess mit niedriger Priorität.
  Die Oberfläche bleibt bedienbar, „Abbrechen“ beendet den Prozess wirklich und entfernt alle
  Zwischendateien. Ein Arbeitsprozess erledigt mehrere Dateien nacheinander (höchstens 25, danach
  folgt ein frischer; nach einem Fehler, einem Absturz oder „Abbrechen“ immer ein frischer), der Start
  mit den PDF-Bibliotheken fällt so nicht je Datei an. Beim Öffnen der Seite wird einer im Hintergrund
  vorbereitet; ohne Auftrag endet er nach einer Minute. Gestartet wird er nie im Thread der Oberfläche. Schutz vor Ressourcenbomben: Der Arbeitsspeicher des Arbeitsprozesses ist
  begrenzt (Windows-Job-Objekt), Bildgröße und Zahl der untersuchten Objekte je Seite haben
  Obergrenzen; stürzt eine Engine an einer manipulierten Datei ab, endet nur der Arbeitsprozess.
  Technische Meldungen des Arbeitsprozesses (Bereich `repair`, ohne Inhalte, Passwörter, Datei-
  oder Ordnernamen) reicht die Pipe an die App weiter; sie stehen in `pdf-tool.log`.

## Erweiterte PDF-Reparatur

„Von keinem Parser lesbar“ heißt nicht „nicht wiederherstellbar“: Viele beschädigte Dateien enthalten
noch alle Objekte und Datenströme, nur Querverweistabelle, Trailer, Dateiende oder Seitenbaum fehlen.
Findet die Analyse das, heißt der Zustand **Erweiterte Wiederherstellung möglich**, und die
Schaltfläche **PDF-Struktur rekonstruieren** startet die Wiederherstellung („PDF Tool versucht, die
noch vorhandenen Inhalte wiederherzustellen.“). Die technischen Befunde – Objektkandidaten,
Katalog, `/Page`-Objekte, `/Pages`-Knoten, xref, Trailer, startxref, `%%EOF` – stehen nur in den
technischen Details. Code: `app/tools/pdf_repair/recovery/`.

- **Ablauf:** qpdf neu schreiben → Seiten einzeln (qpdf) → Seiten über PDFium → pypdf
  (`strict=False`) → Rohanalyse → neue Querverweistabelle, Trailer, startxref und `%%EOF` →
  bei Bedarf neuer Seitenbaum → Normalisierung mit qpdf → Prüfung. Ein vollständiges Ergebnis ohne
  Verluste beendet die Suche; der Rettungsmodus (Bilder) folgt nur nach Bestätigung.
- **Fremde Daten vor bzw. nach der PDF:** Steht `%PDF-` erst hinter Byte 1024 (E-Mail- oder
  HTTP-Kopf, HTML, BOM mit Datenmüll – gesucht wird in den ersten 8 MB) oder folgen auf das letzte
  `%%EOF` mehr als 1 KB ohne PDF-Struktur, durchläuft zuerst eine Kopie nur mit den PDF-Daten alle
  Stufen; ihre Kandidaten werden geprüft und bewertet wie alle anderen, das Original folgt, wenn sie
  kein vollständiges Ergebnis liefert. Analyse, Details („Daten vor dem PDF-Anfang entfernt
  (2.880 Byte)“) und Ergebnis nennen das. Stehen vor der Kennung schon PDF-Objekte oder folgt auf
  `%%EOF` noch PDF-Struktur (z. B. ein abgeschnittenes Update), wird nichts abgeschnitten.
- **Datenströme retten** (`recovery/streams.py`): Flate-Ströme, die sich nicht vollständig
  dekodieren lassen, werden mit `zlib.decompressobj` so weit wie möglich gelesen – bevor qpdf eine
  Ausgabe schreibt (sonst übernähme qpdf sie unverändert oder, mit ASCII85 davor, stillschweigend
  gekürzt) und noch einmal nach der Auswahl, falls die beste Ausgabe sie noch enthält (z. B. von
  PDFium). Inhaltsströme von Seiten und Formularen enden am letzten vollständigen Befehl, offene
  Blöcke (`BT`, `q`, `BDC`) werden geschlossen. Bilder nur, wenn es sicher geht (Flate ohne oder
  mit PNG-Prädiktor, Grau/RGB/CMYK, kein `/Decode`, keine Maske; fehlende Zeilen weiß), sonst
  unverändert und gemeldet. Seiten mit beschädigten Strömen zählen als unvollständig; das Ergebnis
  heißt „teilweise wiederhergestellt“ („1 Datenstrom teilweise gerettet …“), nie „repariert“.
- **Dritte Engine:** pypdf (BSD-3-Clause) liest mit eigenen, toleranteren Regeln; dem Ergebnis wird
  nicht vertraut – es wird mit qpdf normalisiert und wie jede Ausgabe geprüft. PyMuPDF und
  Ghostscript wurden wegen ihrer AGPL-Lizenz nicht verwendet (siehe `THIRD_PARTY_LICENSES.md`).
- **Rohanalyse** (`recovery/scanner.py`): durchsucht die Datei per `mmap` blockweise nach
  Objektköpfen `N G obj`. Ein Kandidat zählt nur mit Trennzeichen davor, gültigem Objektanfang und
  `endobj`; Datenströme werden über `/Length` oder `endstream` übersprungen – zufällige Bytes wie
  „20 0 obj … /Type /Page“ in Bild- oder Schriftdaten werden nie zu Objekten. Bei inkrementellen
  Updates gilt die letzte vollständige Definition; Objektströme werden entpackt, soweit sie nur mit
  Flate komprimiert sind (andere Filter werden nicht geraten).
- **Neuaufbau** (`recovery/rebuild.py`): alle gültigen Objekte unverändert übernehmen, klassische
  Querverweistabelle mit exakten Offsets, neuer Trailer mit `/Size` und `/Root` (`/Info` und `/ID`
  nur, wenn sicher vorhanden), `startxref` und `%%EOF`. Fehlt der Katalog, entsteht ein neuer.
  Ist der Seitenbaum defekt (auch Verweise ins Leere, die qpdf beim Öffnen stillschweigend
  entfernt), entsteht ein neuer `/Pages`-Knoten aus den gefundenen `/Page`-Objekten: Reihenfolge des
  erhaltenen Baums, übrige Seiten nach Objektnummer, `/Parent` gesetzt, Inhalte, Ressourcen,
  MediaBox, CropBox, Rotate und Anmerkungen bleiben; geerbte Eigenschaften werden vorher auf die
  Seiten übertragen. Fehlende Schriften mit Ein-Byte-Text werden durch Helvetica ersetzt und
  gemeldet; Zwei-Byte-Text bekommt nie eine geratene Schrift.
- **Rangfolge und Prüfung:** Kandidaten zählen nach vollständigen Seiten, Seitenzahl, Struktur statt
  Bildern, Verlusten und Methode. Jede Ausgabe muss existieren, eine PDF-Kennung und `%%EOF` haben,
  sich mit qpdf ohne Wiederherstellung öffnen lassen, einen lesbaren Seitenbaum mit plausibler
  Seitenzahl haben und von PDFium geöffnet werden. Fehlen Seiten oder Inhalte oder wurden Schriften
  ersetzt, lautet das Ergebnis „teilweise wiederhergestellt“ – nie „repariert“.
- **Grenzen:** Verschlüsselte Dateien, deren Verschlüsselungsangaben fehlen, werden nicht
  rekonstruiert – ein Passwortschutz wird nie umgangen und `/Encrypt` nie geraten. Querverweis-
  Datenströme werden nicht „repariert“, sondern durch eine neue Tabelle ersetzt. Das Original wird
  nur gelesen; die Ausgabe heißt wie gewohnt `<Name>_repariert.pdf`.
