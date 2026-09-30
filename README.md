# PDF Tool

Quellcode von **PDF Tool 2.7.0** – einer Windows-App mit Werkzeugen für PDF-Dateien.
Entwickler und Inhaber: Jerico. Bis Version 2.2 hieß die App „Übersichten-Ersteller“.

Das Repository enthält:

- die Windows-App für Windows 10 (ab 1809) und 11 unter `windows-app/app/` – Oberfläche **PySide6 + Qt Quick/QML**
  (seit 2.7.0), Fachlogik in **Python**
- das Inno-Setup-Skript für den Windows-Installer unter `windows-app/installer/PDF-Tool.iss`
- das Build-Skript `windows-app/build.py`
- die Web-/Downloadseite auf Basis von React, TanStack Start und Vite

## Werkzeuge

Nach dem Start zeigt PDF Tool eine Startseite mit allen Werkzeugen. Die Navigation links führt zu
**Start**, den **Tools** und den **Einstellungen**. Eine Datei kann direkt in das Fenster gezogen
werden: eine PDF öffnet „PDF reparieren“, eine Excel-Liste „Vertragsübersichten“.

| Werkzeug | Zweck | Code |
| --- | --- | --- |
| **Vertragsübersichten** | Erstellt professionelle Vertragsübersichten aus Excel-Dateien – einzeln oder als Stapel, mit Excel-Fettschrift, Vorlagen, formatierten Kopf- und Fußzeilen, Textbausteinen, Zyklus-Regeln, Live-Vorschau, optionaler Kundenakte mit Wiedererkennung bekannter Kunden und Vertragsvergleich mit dem letzten Stand | Fachlogik: `app/tools/contract_overview/` (`overview.py`, `customers/` für die Kundenakte, `batch/` für den Stapel, `history/` für den Vertragsvergleich), `app/engine.py`, `app/excelstyle.py`, `app/richtext.py`, `app/pdffonts.py` · Controller: `app/qtapp/contracts/` · Seiten: `app/qml/PdfTool/Pages/` |
| **PDF reparieren** | Analysiert beschädigte PDF-Dateien und versucht, lesbare Inhalte in eine neue PDF zu übertragen – bis zur Rekonstruktion der Dokumentstruktur aus den noch vorhandenen Objekten | Fachlogik: `app/tools/pdf_repair/` (`recovery/` für die erweiterte Wiederherstellung) · Controller: `app/qtapp/repair.py` · Seite: `app/qml/PdfTool/Pages/RepairPage.qml` |

Die Werkzeuge sind voneinander getrennt: Jedes hat eigene Seiten, eigene Einstellungen und eigene
Logik; gemeinsam sind nur Fenster, Navigation, Design und Dialoge (`app/qtapp/app.py`,
`app/qml/PdfTool/Shell/`, `app/qml/PdfTool/Controls/`). Neue Werkzeuge bekommen ein eigenes Paket
unter `app/tools/` (Fachlogik ohne Oberfläche), einen Controller unter `app/qtapp/`, eine Seite
unter `app/qml/PdfTool/Pages/` und einen Eintrag in `app/tools/registry.py` – siehe
[`windows-app/ARCHITECTURE.md`](windows-app/ARCHITECTURE.md).

### Vertragsübersichten: Kundenakte und Kundenwiedererkennung

Das Werkzeug hat die Ansichten **Übersicht erstellen**, **Stapel**, **Darstellung**, **Vorschau**
und – mit eingeschalteter Kundenakte – **Kunden**. Die Kundenakte gehört ausschließlich zu
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

### Vertragsübersichten: Stapelverarbeitung

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

### Vertragsübersichten: Vertragsänderungen

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

### Vertragsübersichten: Live-Vorschau

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

### Technik: Oberfläche und Architektur (seit 2.7.0)

- **UI:** PySide6 6.11.2 (Qt 6, Qt Quick/QML), eigene Windows-11-nahe Steuerelemente auf Basis von
  Qt Quick Templates (`app/qml/PdfTool/Controls/`), Design-Tokens für Farben, Abstände, Radien,
  Schrift (Segoe UI Variable) und Animationsdauern (`app/qml/PdfTool/Style/`).
- **Backend:** Python – die Fachlogik ist dieselbe wie bis 2.6.1 und enthält keinen Oberflächencode.
- **Qt-Brücke:** `QObject`-Controller je Bereich (`app/qtapp/`: `App`, `Settings`, `Contracts`,
  `Customers`, `Preview`, `Batch`, `Comparison`, `Repair`) sind die einzige Verbindung zwischen QML
  und Fachlogik; Listen (Stapel, Kunden, Vertragsänderungen, Vorlagen …) sind
  `QAbstractListModel`s mit gezielten Änderungen (`insertRows`/`removeRows`/`moveRows`/`dataChanged`)
  statt Neuaufbau.
- **Hintergrundarbeit:** Excel-Prüfung, PDF, Vorschau und Stapel laufen in Threads, „PDF reparieren“
  in einem eigenen Prozess; Ergebnisse kommen über Qt-Signale in den GUI-Thread – Hintergrund-Threads
  berühren nie QML.
- **Start:** Konfiguration → Qt-Anwendung → Design → Controller → QML-Engine → verborgenes Fenster
  (DWM-Cloaking) → Startseite; das Fenster erscheint mit dem ersten fertig gezeichneten Bild, weitere
  Seiten laden danach im Hintergrund. Die QML-Oberfläche kommt im Setup aus einer eingebauten
  Qt-Ressource (`qrc:/qml`, unabhängig vom Arbeitsverzeichnis).
- **Animationen:** Profil „Vollständig“, „Reduziert“ oder „Aus“ (Einstellungen → Verhalten →
  Animationen); ist in
  Windows „Animationseffekte“ aus, gilt mindestens „Reduziert“. Seitenwechsel (Aus-/Einblenden mit
  leichter Bewegung), Navigationsindikator, Menüs, Tooltips, Aufklappbereiche, InfoBars, Dialoge,
  Schaltflächen, Schalter und Statuswechsel sind animiert; alle Dauern stehen zentral in
  `Style/Motion.qml` und gelten sofort ohne Neustart.
- **Anzeige:** Hell/Dunkel/„Wie Windows“ und Windows-Akzentfarbe live, Mica (nur wenn Windows es
  zuverlässig unterstützt), Skalierung 100–200 % (Qt High-DPI), Layout mit einer oder zwei Spalten
  je nach Breite.

Details für Mitwirkende: [`windows-app/ARCHITECTURE.md`](windows-app/ARCHITECTURE.md) und
[`windows-app/QML_STYLE.md`](windows-app/QML_STYLE.md).

### PDF reparieren

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
  SHA-256-Prüfsumme verglichen. Die Ausgabe heißt `<Name>_repariert.pdf` (bei Bedarf `_2`, `_3` …)
  und entsteht neben dem Original oder in einem gewählten Ordner. Bei einem Fehler bleibt keine
  Ausgabe zurück.
- **Verschlüsselte PDFs** lassen sich mit dem richtigen Passwort reparieren; die Kopie bleibt
  verschlüsselt. Das Passwort wird nie gespeichert oder protokolliert, Passwortschutz wird nicht
  umgangen.
- **Arbeitsprozess:** Analyse und Reparatur laufen in einem eigenen Prozess mit niedriger Priorität.
  Die Oberfläche bleibt bedienbar, „Abbrechen“ beendet den Prozess wirklich und entfernt alle
  Zwischendateien. Schutz vor Ressourcenbomben: Der Arbeitsspeicher des Arbeitsprozesses ist
  begrenzt (Windows-Job-Objekt), Bildgröße und Zahl der untersuchten Objekte je Seite haben
  Obergrenzen; stürzt eine Engine an einer manipulierten Datei ab, endet nur der Arbeitsprozess.

### Erweiterte PDF-Reparatur

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

## Installation

Das Setup `PDF-Tool-Setup-<Version>.exe` enthält Python, qpdf (über pikepdf), PDFium (über
pypdfium2) und alle weiteren Pakete – es muss nichts zusätzlich installiert werden. Benutzerhinweise
(Installation, Update, stille Installation, Deinstallation, Bedienung) stehen in
[`windows-app/README.txt`](windows-app/README.txt).

- Programmdateien: `%LOCALAPPDATA%\PDF-Tool` (Installation ohne Administratorrechte)
- Benutzerdaten: `%APPDATA%\PDF-Tool` – bleiben bei Updates erhalten
- **Update vom Übersichten-Ersteller (bis 2.2):** Das Setup verwendet dieselbe AppId – unter
  „Installierte Apps“ entsteht kein zweiter Eintrag. Die Programmdateien ziehen von
  `%LOCALAPPDATA%\Uebersichten-Ersteller` nach `%LOCALAPPDATA%\PDF-Tool` um, alte Verknüpfungen
  werden durch „PDF Tool“ ersetzt. Beim ersten Start übernimmt die App die Daten aus
  `%APPDATA%\Uebersichten-Ersteller` einmalig: zuerst eine Sicherung
  (`migration-backup-<Version>.zip`), dann Kopie mit Prüfung jeder Datei (Größe und SHA-256).
  Der alte Datenordner bleibt unverändert erhalten; schlägt die Übernahme fehl, arbeitet die App mit
  ihm weiter.
- **Update von 2.6.1 (Tk-Oberfläche) auf 2.7.0:** Das Setup ersetzt die Programmdateien vollständig –
  die frühere Tk-Oberfläche und Tcl/Tk bleiben nicht zurück. Einstellungen, Kundenakten,
  Zuordnungen, Vorlagen, Regeln, Textbausteine, Kopf- und Fußzeilen, Stapel- und
  Reparatur-Einstellungen und Vertragsstände werden unverändert weiterverwendet – **keine manuelle
  Migration**. Die Fensterlage der alten Oberfläche wird nur gelesen (neue Lage: `fenster_qt`), die
  frühere Einstellung „Animationen“ wird zum Animationsprofil.
- **Update von 2.6.0:** Das Setup ersetzt nur Programmdateien. Die Kundenakte ist danach zunächst
  aus (Opt-in); Kundenakten, Zuordnungen und Vertragsstände bleiben unverändert erhalten und stehen
  nach dem Einschalten sofort wieder bereit. Alle übrigen Einstellungen bleiben unverändert.
- **Update von 2.5:** Das Setup ersetzt nur Programmdateien; Einstellungen, Kundenakten, Vorlagen,
  Textbausteine, Rich-Text-Kopf- und Fußzeilen, Zyklus-Regeln, der gespeicherte Stapel mit seinen
  Einstellungen und die Einstellungen von „PDF reparieren“ bleiben unverändert. Vertragsstände
  (`contract-history`) sind Benutzerdaten: Ein Update löscht sie nie; bei der Deinstallation
  werden sie nur mit den übrigen Benutzerdaten und nur auf Nachfrage entfernt.
- **Update von 2.4:** Das Setup ersetzt nur Programmdateien; Einstellungen, Kundenakten, Vorlagen,
  Rich-Text-Kopf- und Fußzeilen und die Einstellungen von „PDF reparieren“ bleiben unverändert.
- **Update von 2.3:** Das Setup ersetzt nur Programmdateien. Der Kundenverlauf bleibt unverändert
  erhalten; sobald die Kundenakte eingeschaltet wird, übernimmt die App ihn als Kundenakten (siehe
  oben, mit Sicherung). Einstellungen, Vorlagen, Textbausteine, Regeln sowie Kopf- und Fußzeile
  bleiben unverändert.
- Die Version steht zentral in `windows-app/VERSION`.

## Datenschutz

Alle Dateien werden vollständig lokal auf dem PC verarbeitet; es wird nichts hochgeladen und keine
Verbindung zu einem Dienst aufgebaut. PDF Tool schreibt Einstellungen, die Kundenakten
(`kundenakten.json`), die Vertragsstände (`contract-history\`), den aktuellen Stapel (`stapel.json`)
und die technischen Protokolle `pdf-repair.log` und `stapel.log` in den Datenordner. Auch die
Stapelverarbeitung, der Vertragsvergleich und die erweiterte PDF-Wiederherstellung arbeiten
vollständig lokal – keine Cloud, keine Uploads.

**Vertragsstände** enthalten nur, was ohnehin in der erstellten Übersicht steht, und bleiben auf
diesem PC. Protokolle enthalten weder Vertragsdaten noch Verläufe von Kunden; Fehler beim Speichern
eines Stands werden ohne Vertragsinhalte protokolliert. Wer die Benutzerdaten sichert, sichert den
Ordner `%APPDATA%\PDF-Tool` vollständig – `contract-history` gehört dazu.

**Die Kundenakte ist optional** (Standard: aus). Ist sie ausgeschaltet, werden keine Kundendaten
automatisch gespeichert oder abgeglichen, und `kundenakten.json` wird nicht gelesen; vorhandene
Kundendaten bleiben unverändert erhalten.

**Kundenakten und E-Mail-Zuordnungen** sind ausschließlich lokal gespeicherte Nutzerdaten: keine
Cloud, keine Telemetrie, keine Synchronisierung, keine E-Mail-Abfrage, keine Internetsuche und
keine Domain-Auflösung. Gespeichert werden nur Angaben, die der Benutzer bewusst speichert, sowie
Pfade der zuletzt verwendeten Excel- und PDF-Datei – keine Kopien der Dateien. Löschen entfernt
die Kundenakte und ihre Zuordnungen, nie PDF- oder Excel-Dateien. Das Protokoll enthält Dateinamen, Größen und technische
Befunde, aber keine PDF-Inhalte, keine vollständigen Pfade und keine Passwörter. Zwischendateien
entstehen nur im temporären Ordner von Windows und werden nach jedem Vorgang gelöscht.

## Entwicklung

### Setup bauen

Voraussetzungen unter Windows 10/11 (64 Bit):

- Python 3.13 (64 Bit) mit pip, Pillow und PySide6-Essentials in derselben Version wie das Setup
  (`py -3.13 -m pip install pillow PySide6-Essentials==6.11.2` – liefert `rcc` für die QML-Ressource)
- [Inno Setup 6.6 oder neuer](https://jrsoftware.org/isdl.php)
- Internetzugang (eingebettete Python-Laufzeit von python.org, Pakete aus
  `windows-app/runtime-requirements.txt`, jeweils mit SHA-256-Prüfsumme)

```powershell
py -3.13 windows-app\build.py
```

Ergebnis: `windows-app\dist\PDF-Tool-Setup-<Version>.exe` und die zugehörige `.sha256`-Datei.
Das Build-Skript bündelt die QML-Oberfläche als Qt-Ressource (`windows-app/qmlres.py`), übernimmt
von PySide6 nur die benötigten Module, Plugins und QML-Module (`windows-app/qtruntime.py`, anhand
der Importtabellen der DLLs), entfernt tkinter/Tcl/Tk aus der Laufzeit und prüft, dass alle Module,
die nativen Bibliotheken von qpdf und PDFium sowie Qt Quick enthalten sind – und keine Reste der
früheren Tk-Oberfläche.

Die GitHub-Action [`windows-setup.yml`](.github/workflows/windows-setup.yml) baut das Setup auf
`windows-latest`, führt alle Tests aus, prüft die eingebettete Laufzeit (Module, Vertragsübersicht,
PDF-Reparatur im Arbeitsprozess, Kundenakte, Vorschau, Stapel, Programmstart) und das installierte
Setup: stille Installation, Programmstart, stille Deinstallation, das Update vom Übersichten-Ersteller
2.2.0 (ein Eintrag unter „Installierte Apps“, Ordner, Verknüpfungen, Datenübernahme), das Update
von PDF Tool 2.3.0 mit Beispieldaten (der Kundenverlauf bleibt bei ausgeschalteter Kundenakte
unverändert und wird nach dem Einschalten mit Sicherung zu Kundenakten; Formatierung,
Standard-Fußzeile und Vorlagen bleiben), das Update von PDF Tool 2.4.0 mit Beispieldaten
(Kundenakten, Vorlagen, Rich Text und Reparatur-Einstellungen bleiben erhalten), das Update von
PDF Tool 2.5.0 (zusätzlich Stapel-Einstellungen und Vertragsstände) und das Update von PDF Tool
2.6.0 (Kundenakte zunächst aus, Kundenakten und Vertragsstände unverändert und lesbar) sowie das
Update von PDF Tool 2.6.1 mit der früheren Tk-Oberfläche (keine Reste von Tk, alle Benutzerdaten
und Einstellungen erhalten).
Der Runtime-Smoke-Test prüft außerdem pypdf, die Rohrekonstruktion einer beschädigten PDF und das
Speichern und Vergleichen eines Vertragsstands. Manuell gestartet mit
`release: true` veröffentlicht sie danach das Release `v<Version>` („PDF Tool <Version>“) mit Setup
und Prüfsumme – nur wenn alle Prüfungen bestanden sind.

### Tests

```powershell
py -3.13 -m pip install pytest pandas openpyxl reportlab pillow xlrd pypdf xlwt pikepdf==10.15.0 pypdfium2==5.13.0 PySide6-Essentials==6.11.2
$env:QT_QPA_PLATFORM = "offscreen"   # Oberflächentests ohne Bildschirm (so läuft auch die CI)
py -3.13 -m pytest windows-app\tests
```

Die Tests erzeugen ihre Test-PDFs selbst (`windows-app/tests/pdfsamples.py`): gültige Dateien,
falsche Querverweise, fehlender Trailer, abgeschnittene Dateien, beschädigte Datenströme, nicht
reparierbare Dateien, verschlüsselte PDFs, Formulare, Anhänge, Signaturen und große PDFs – für die
erweiterte Wiederherstellung zusätzlich klassische PDF 1.4 ohne xref, Trailer, `%%EOF` oder
Seitenbaum, falsche `/Parent`-Verweise, geerbte Ressourcen, Binärdaten mit scheinbaren
Objektköpfen, inkrementelle Updates, Objektströme und eine Nachbildung einer realen, nach den Seiten
abgeschnittenen Datei. Echte Kundendateien liegen nie im Repository; eine lokale Beispieldatei lässt
sich mit `PDF_TOOL_REAL_SAMPLE=<Pfad>` zusätzlich prüfen.

Die Oberflächentests (`test_qt_*.py`) starten die App wie beim echten Start – Controller, QML und
Fenster (`tests/qtutil.py`) – und schlagen fehl, sobald die QML-Engine eine Warnung meldet
(Bindungsschleifen, fehlende Properties …). Sie prüfen alle Abläufe von 2.6.1 an den Controllern
(Excel-Prüfung, PDF, Rich Text mit Rückgängig/Wiederholen, Vorlagen, Kundenakte, Vorschau, Stapel
mit 100 Dateien, Kundenliste mit Hunderten Einträgen, Vertragsvergleich, PDF reparieren) sowie
Qt-Spezifisches: Listenmodelle ändern nur betroffene Zeilen, alle Seiten entstehen genau einmal,
Animationsprofile, Hell/Dunkel, Fenstergrößen, das Laden der Oberfläche aus der eingebauten
Ressource und dass kein Code mehr tkinter verwendet.

**Manuelle Prüfung vor einem Release (Windows 10/11):**

1. Skalierung 100 %, 125 %, 150 %, 175 % und 200 % (Einstellungen → Anzeige): Start ohne weißes
   oder halbfertiges Fenster, keine abgeschnittenen Texte, Navigation breit/kompakt, Einstellungen
   vollständig lesbar. Zum Nachbilden eignet sich `QT_SCALE_FACTOR=1.5`.
2. Hell/Dunkel mehrfach wechseln (auch „Wie Windows“ und über die Windows-Einstellung): Wechsel in
   einem Schritt, Titelleiste und Mica passend.
3. „Animationseffekte“ in Windows aus: Seitenwechsel, Navigation und Bereiche ohne Bewegung.
4. Fenstergröße langsam und schnell ziehen, maximieren, wiederherstellen, Navigation ein- und
   ausklappen: keine springenden Karten, kein Flackern.
5. Schnell zwischen „Übersicht erstellen“, „Darstellung“, „Vorschau“, „Stapel“ und (mit Kundenakte)
   „Kunden“ wechseln: keine leeren oder halb aufgebauten Seiten.
6. Kundenakte aus → ein → aus → ein: Daten bleiben, keine doppelten Einträge; Stapel und PDF ohne
   Kundenakte.
7. Animationsprofil „Vollständig“ → „Reduziert“ → „Aus“: wirkt sofort, ohne Neustart.

Das App-Symbol entsteht mit `python windows-app/scripts/make_icons.py` (Windows-Symbol, Favicons
und Logo der Downloadseite).

## Lizenzen

PDF Tool nutzt ausschließlich Bibliotheken mit freien Lizenzen, darunter PySide6/Qt (LGPL-3.0,
dynamisch geladen und ersetzbar), pikepdf (MPL-2.0) mit qpdf (Apache-2.0), pypdfium2
(Apache-2.0/BSD-3-Clause) mit PDFium (BSD-3-Clause) und pypdf (BSD-3-Clause); die Symbole der
Oberfläche stammen aus Fluent UI System Icons (MIT). Die vollständige
Übersicht steht in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md); die Lizenztexte liegen im
Setup bei den jeweiligen Paketen (`runtime\Lib\site-packages\*.dist-info`).

## Sicherheit

Lokale Build-Artefakte, Download-Caches, Workspace-Metadaten, Screenshots, Caches und
vorkompilierte EXE-/ZIP-Dateien werden nicht versioniert. Das Setup ist ohne Zertifikat
unsigniert; eine Signatur lässt sich über die Umgebungsvariable `SIGN_COMMAND` (z. B. `signtool`)
im Build ergänzen. OAuth-Secrets gehören ausschließlich in Umgebungsvariablen und sind nicht im
Repository enthalten.
