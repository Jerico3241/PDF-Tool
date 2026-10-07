# Changelog

Ausführliche Hinweise je Version: [`release-notes/`](release-notes/).

# PDF Tool 3.2.0-beta.2

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Optionaler KI-Assistent: Fragen zum geöffneten PDF und
Zusammenfassungen mit Seitenangaben, vollständig lokal mit llama.cpp; das Sprachmodell (Qwen3.5 4B oder 2B) wird nur
auf ausdrücklichen Wunsch geladen und lässt sich jederzeit entfernen. Standardmäßig aus. Details in den
[Release Notes](release-notes/3.2.0-beta.2.md).

## KI-Assistent (`app/assistant/`, `qtapp/assistant.py`)

- `catalog.py`: zwei Modelle (GGUF Q4_K_M von unsloth, Apache-2.0) mit festem Commit bei Hugging Face, Größe und
  SHA-256; `recommended(ram)` (»Genau« ab 12 GB Arbeitsspeicher, sonst »Kompakt«).
- `store.py`: `%LOCALAPPDATA%\PDF-Tool-KI\modelle` (Tests: `PDFTOOL_AI_DIR`), eingerichtet erst mit Größe und
  Vermerk der geprüften Prüfsumme (`.sha256`), Teildownload `.part`, `remove`, Platzbedarf mit 512 MB Reserve.
- `text.py`: Seitentexte bereinigt (Silbentrennung), Abschnitte bis 1.000 Zeichen nie über Seitengrenzen,
  BM25-Index mit ausgeschriebenen Umlauten, Füllwörtern und Wortanfängen langer Wörter; `cited_pages` und `rich`
  (Antwort maskiert, nur fett, Überschriften, Stichpunkte und Verweise `page:N` – Qt `StyledText`).
- `prompts.py`: Antworten nur aus den Auszügen mit Seitenangabe; Fragen mit bis zu 9.000 Zeichen passender
  Auszüge; Zusammenfassung in einem Schritt oder in bis zu fünf Teilen à 12.000 Zeichen mit Zusammenführung.
- `runtime.py`: `llama-server` (gebündelt `ai\llama-server.exe`, Tests `PDFTOOL_LLAMA_SERVER`) mit `--host
  127.0.0.1`, freiem Port, `--ctx-size 8192`, `--parallel 1`, `--no-webui`, `--log-disable`; Schlüssel über
  `LLAMA_API_KEY`; `CREATE_NO_WINDOW`, `BELOW_NORMAL_PRIORITY_CLASS`, Job-Objekt mit
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; verständliche Fehler (fehlende DLL, Prozessor, Speicher).
- `client.py`: `/v1/chat/completions` gestreamt (SSE), Qwen3.5 ohne »Nachdenken«
  (`chat_template_kwargs.enable_thinking=false`), Temperatur 0,2; `cancel()` aus jedem Thread.
- `AssistantController` (QML `Assistant`): Zustände off/setup/download/verify/ready, Konfiguration
  `ki_assistent`/`ki_modell`, Einrichten-Dialog `assistant_setup`, Download über den Updater-Transport mit
  `UrlPolicy` nur für huggingface.co und `*.hf.co`, SHA-256 im Arbeitsthread, Entfernen nach Rückfrage; Gespräch je
  Dokument (`KeyedListModel`, beim Streamen ändert sich nur die Zeile der Antwort), Auszüge je Dokumentstand
  zwischengespeichert, KI-Prozess erst bei Bedarf und nach zehn Minuten ohne Frage beendet.
- Reader: rechte Seitenleiste `assistant` (`AssistantPanel.qml`, Streifen und Kopf nur eingeschaltet);
  Ausschalten schließt sie in allen Tabs (`ReaderController.close_right_panel`). `PTextArea.submitOnEnter`.
- Einstellungen: Karte „KI-Assistent (optional)“ mit Status, Fortschritt, Einrichten, Fortsetzen, Anhalten,
  Anderes Modell, Modell entfernen und Hinweis zum Datenschutz.

## Updater-Transport

- `download(..., offset, keep_partial)`: Fortsetzen mit `Range` (206 mit passendem `Content-Range`, sonst von
  vorn), Teildatei bleibt nach Abbruch, Zeitüberschreitung oder Verbindungsverlust; der Updater selbst nutzt das
  nicht.

## Setup, Prüfungen, Tests

- `build.py`: llama.cpp b11476 (`llama-b11476-bin-win-cpu-x64.zip`, SHA-256) → `ai\`: `llama-server.exe`, DLLs
  laut Importtabellen, `ggml-cpu-*.dll`, `LICENSES.txt` (von `llama.exe licenses`). Fehler des Builds in der CI
  zusätzlich als Fehlermeldung am Lauf.
- `release_check.check_ai`; Runtime-Smoke-Test mit dem gebündelten llama-server und einem Testmodell (1,2 MB),
  Abbruch des Elternprozesses beendet den KI-Prozess; Installer ersetzt bzw. entfernt `ai\` und entfernt geladene
  Modelle bei der Deinstallation (nur die eigenen Dateien).
- `test_assistant.py` (ohne Oberfläche, Attrappe `fixtures/fake_llama_server.py`), `test_qt_assistant.py`
  (lokaler Testserver statt Hugging Face: Weiterleitung, `Range`, Anhalten und Fortsetzen, falsche Prüfsumme,
  fremde Weiterleitung, Speicherplatz, Entfernen, Fragen mit Seitenverweisen, Zusammenfassen in Teilen, Abbrechen,
  Scans, Gespräche je Tab, Leerlauf, keine Inhalte in Protokollen).

# PDF Tool 3.2.0-beta.1

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Schützen und Weitergeben: Schwärzen, Bereinigen,
Kennwortschutz, Reduzieren, Verkleinern, Kopf-/Fußzeile, Seitenzahlen und Wasserzeichen, Stempel und Unterschrift;
dazu Links, Lesezeichen bearbeiten und Seiten zuschneiden. Mehr Komfort: Tabs mit Kontextmenü, Umordnen und
„Geschlossenen Tab wieder öffnen“, letzte Sitzung beim Start, Nachtmodus, Schnellwerkzeuge auf der Startseite und
„Per E-Mail senden“. Details in den [Release Notes](release-notes/3.2.0-beta.1.md).

## Schützen und Weitergeben (Reader, Schaltfläche „Schützen“)

- Schwärzen (`tools/pdf_editor/redact.py`, Werkzeug `redact`): Bereiche aufziehen oder Text markieren
  (`redactMarks`, `addRedactArea`, `redactSelection`), „Schwärzen anwenden“ nach Rückfrage. Entfernt Glyphen aus
  dem Inhaltsstrom (TJ mit Abständen), Pfade ganz im Bereich, Bildpunkte (Bild und weiche Maske neu kodiert),
  Inhalte kopierter Formular-XObjects, Kommentare, Links und Formularfelder im Bereich, Vorschaubilder,
  `/ActualText`/`/Alt`/`/E` und passende Strukturelemente. Nicht sicher teilbare Inhalte (Inline-Bilder, Masken,
  JBIG2, unbekannte Schriften) und Reste nach der PDFium-Prüfung: Seite mit 200 dpi als Bild; bleibt dann noch
  Text, wird alles zurückgenommen. „Suchen und schwärzen“: IBAN mit Prüfziffer, E-Mail, Telefon, Datum, eigene
  Begriffe – nur vormerken. Seitenänderungen verwerfen offene Bereiche.
- Dokument bereinigen (`sanitize.py`): zählen, dann Metadaten, Skripte und unsichere Aktionen, Anhänge,
  versteckte Daten und auf Wunsch Kommentare entfernen (Dialog `checklist`).
- Reduzieren (`flatten.py`): Erscheinungsbilder von Feldern und Kommentaren als Formular-XObject in die Seite.
- Kennwortschutz (`protect.py`, Dialog `protect`): Kennwort zum Öffnen, Einschränkungen mit eigenem
  Berechtigungskennwort, AES-256 (R6), ändern oder entfernen; gilt ab dem nächsten Speichern, geprüft mit dem
  neuen Kennwort. „Einschränkungen aufheben …“ prüft das Berechtigungskennwort an der Originaldatei.
- PDF verkleinern (`optimize.py`, Dialog `optimize`): Kopie mit Bildern auf 110/150/220 dpi (JPEG, nur mit
  Gewinn), Ungenutztes entfernt, Objektströme; Original unverändert, Kennwortschutz bleibt.

## Seiten gestalten (Reader, Schaltfläche „Seiten gestalten“)

- Kopf- und Fußzeile, Seitenzahlen, Bates-Nummern und Wasserzeichen (`pagemarks.py`, Dialoge `header_footer`,
  `watermark` mit Vorschau): eigener markierter Inhaltsstrom je Seite, aufrecht auch auf gedrehten Seiten,
  ersetzbar (ein Schritt) und entfernbar; Platzhalter `{seite}`, `{seiten}`, `{datum}`, `{datei}`, `{bates}`.
- Seiten zuschneiden (`crop.py`, Dialog `crop`): Ränder in Millimetern oder an den Inhalt angepasst, CropBox,
  zurücksetzbar.
- Lesezeichen bearbeiten (`outline.py`): hinzufügen, umbenennen (F2), Ziel auf die angezeigte Seite, verschieben,
  ein-/ausrücken, löschen (Entf) – Seitenleiste „Lesezeichen“ (Schaltfläche unten, Kontextmenü, leerer Zustand).

## Unterschreiben und Stempeln

- `stamps.py`: Anmerkung `/Stamp` mit eigenem Erscheinungsbild (BBox in Anzeigegröße, Matrix gegen die
  Seitendrehung); verschieben und Größe ändern ändern nur `/Rect` (`annotations.RESIZABLE` um `/Stamp` ergänzt,
  Seitenverhältnis bleibt). Stempel-Vorgaben und eigener Text mit zweiter Zeile (`{datum}`, `{zeit}`).
- Unterschrift zeichnen (Bézier-Kurven) oder aus einem Bild (Papier durchsichtig, Tintenfarbe, weiche Maske);
  Dialog `signature`. Gespeicherte Unterschriften (`SignatureStore`, `unterschriften.json` im Datenordner,
  höchstens sechs, atomar, löschbar) nur auf Wunsch – nicht in Sicherung oder Support-Paket.
- Nach dem Setzen ist „Auswählen“ aktiv und der neue Stempel bzw. die Unterschrift ausgewählt.

## Links

- Links aller Seiten (`links.py`, `linkPages`) werden nach jeder Änderung neu gelesen. „Auswählen“: Zeiger und
  Ziel beim Zeigen, Klick ohne Ziehen folgt (Seite sofort, Webadresse nach Rückfrage über `files.open_url`);
  andere Aktionen nie. Werkzeug `link`: Bereich aufziehen, Ziel Seite oder http/https/mailto (Dialog `link`);
  ändern, Ziel öffnen, entfernen über Klick bzw. Kontextmenü.

## Reader-Komfort

- Dokument-Tabs (`AppTabs.qml`, `ReaderController`): Kontextmenü (Schließen, Andere Tabs schließen, Tabs rechts
  schließen, Pfad kopieren, Im Ordner anzeigen, Geschlossenen Tab wieder öffnen; Kontextmenü-Taste bzw.
  Umschalt+F10), Umordnen per Ziehen (`moveTab`, gleitende Nachbarn, am Rand blättert die Leiste weiter) und mit
  Strg+Umschalt+←/→. Die Liste blättert nur noch mit Mausrad und ‹ ›.
- „Geschlossenen Tab wieder öffnen“ (Strg+Umschalt+T, `reopenClosed`): die zehn zuletzt geschlossenen Dokumente
  mit Pfad, auf der zuletzt gezeigten Seite.
- Einstellung „PDFs der letzten Sitzung beim Start wieder öffnen“ (`reader_sitzung_wiederherstellen`, Standard
  aus): Beim Beenden merkt sich der Reader Pfade, Seiten und das aktive Dokument (`reader_sitzung`); der nächste
  Start öffnet sie im Hintergrund nach der Absturz-Wiederherstellung – ohne Rückfragen, fehlende oder geschützte
  Dateien werden übergangen und gezählt. Ausschalten entfernt die Liste.
- Nachtmodus (`reader_nachtmodus`, Ansicht-Menü und Einstellungen): Seitenbilder umgekehrt und abgemildert
  (`night_image`, Bildkennung `~n`, eigener Eintrag im Zwischenspeicher). Datei, Drucken und Export unverändert.
- Schnellwerkzeuge auf der Startseite (`Reader.quickTools`, `quickTool`): PDF verkleinern, Schwärzen,
  Kennwortschutz, Wasserzeichen, Seitenzahlen, Dokument bereinigen, Unterschreiben, Zusammenführen – PDF wählen,
  sie öffnet sich im Reader, das Werkzeug startet (`open_paths(…, then=…)`, `runAction`).

## Per E-Mail senden

- `qtapp/mail.py`: neue Nachricht im E-Mail-Programm mit der PDF als Anhang – Simple MAPI (`MAPISendMailW`, sonst
  `MAPISendMail`) mit `MAPI_DIALOG` nur, wenn ein E-Mail-Programm eingetragen ist; sonst bzw. nach einem Fehler
  `mailto:` mit Empfänger und Betreff und die Datei im Explorer markiert. Gesendet wird nie von PDF Tool; im
  Hintergrund, höchstens eine Nachricht zugleich; protokolliert werden nur Fehlercodes.
- Reader („Weitere Befehle“ → „Per E-Mail senden …“, mit Rückfrage bei ungespeicherten Änderungen),
  „Übersicht erstellen“ (nach dem Erstellen, an den Rechnungsempfänger wie in der PDF) und Stapel (Detail eines
  Eintrags, an dessen Rechnungsempfänger).

## Oberfläche

- Werkzeugleiste: Werkzeug „Links“, Gruppe „Unterschreiben“ (Unterschrift, Stempel), Menüs „Schützen“ (markiert,
  solange „Schwärzen“ aktiv ist) und „Seiten gestalten“; schwebende Leiste mit den Einstellungen der neuen
  Werkzeuge. Neue Dialoginhalte (`Dialogs/`): `ChecklistContent`, `ProtectContent`, `OptimizeContent`,
  `HeaderFooterContent`, `WatermarkContent`, `RedactSearchContent`, `SignatureContent`, `LinkContent`,
  `CropContent`. Neue Symbole aus den Fluent UI System Icons: crop, weather_moon, document_header_footer,
  document_page_number, bookmark_add, eye_off, link_edit, arrow_minimize.
- Startseite: Name und Beschreibung eines Werkzeugs brechen nur zwischen Wörtern um. Passt das längste Wort
  nicht in die Spalte (breite Schrift, schmales Fenster), stehen die Werkzeuge untereinander; `test_qt_shell`
  prüft jedes Wort in allen Fenstergrößen.
- Tests: `test_editor_redact.py`, `test_editor_cleanup.py`, `test_editor_protect.py`, `test_editor_optimize.py`,
  `test_editor_pagemarks.py`, `test_editor_stamps.py`, `test_editor_navigation.py`, `test_qt_protect.py`,
  `test_qt_comfort.py`, `test_mail.py`.

# PDF Tool 3.1.0

Freigegebene Version – getestet als Betas 3.0.0-beta.1 bis 3.1.0-beta.4, Funktionsumfang wie 3.1.0-beta.4.
Für Anwender von 2.8 neu: das Werkzeug „PDF Reader & Editor“, die Tab-Leiste statt der Seitenleiste und die neue
Startseite – im Einzelnen in den Abschnitten der Betas unten und in den [Release Notes](release-notes/3.1.0.md).

- Version 3.1.0; README.txt, Neuerungen und Release Notes beschreiben 3.1 als freigegebene Version für Anwender
  von 2.8. Der Programmcode ist gegenüber 3.1.0-beta.4 unverändert.

# PDF Tool 3.1.0-beta.4

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Neuer App-Rahmen nach dem Vorbild von Adobe Acrobat: Tabs
oben statt Seitenleiste links, neue Startseite; Details in den [Release Notes](release-notes/3.1.0-beta.4.md).

## Tab-Leiste

- Die Seitenleiste der App (Start, Tools, Einstellungen; breit/kompakt) entfällt. Oben steht eine Tab-Leiste
  (`Shell/AppTabs.qml`, `AppTab.qml`): ≡ Menü (PDF öffnen, Start, Einstellungen, Kurzanleitung, Neuerungen,
  Über), ⌂ Start, je ein Tab für geöffnete Werkzeuge (`App.openTabs`: Vertragsübersichten, PDF reparieren,
  Einstellungen) und für jedes geöffnete PDF (bisher eine eigene Leiste im Reader), „+“ öffnet PDFs; rechts
  Kurzanleitung und Einstellungen.
- Werkzeug-Tabs schließen mit ×, mittlerer Maustaste oder Strg+W (`App.closeTab`); Eingaben und laufende Arbeit
  bleiben. War der Tab zu sehen, folgt der rechts daneben (nach den Werkzeugen das aktive PDF), sonst der links
  daneben bzw. Start.
- Der aktive Tab geht in die Inhaltsebene über; die Akzentmarkierung gleitet zwischen ⌂, Werkzeugen und PDFs und
  bleibt unter ihrem Tab, wenn Tabs hinzukommen oder wegfallen. Neue Tabs blenden ein und heben sich leicht.
- PDF-Tabs zeigen den Namen ohne „.pdf“, der vollständige Pfad steht im Tooltip; höchstens 240 px breit.
- Viele Tabs: Werkzeug-Tabs werden schmaler, sobald die PDF-Tabs weniger als 200 px hätten; PDF-Tabs werden bis
  144 px schmal (Name in der Mitte gekürzt). Haben auch dann nicht alle Platz, zeigt die Leiste nur ganze, gleich
  breite Tabs und ‹ › zum Blättern; Pfeile, Mausrad (`PWheelScroll.sideways`, `notch`) und Ziehen bewegen um genau
  einen Tab. Der aktive bleibt ganz zu sehen.
- Der Reader erscheint erst mit dem geöffneten Dokument (kein leerer Reader); nach dem letzten geschlossenen
  PDF geht es zur Startseite. Schlägt das Öffnen fehl, bleibt die Seite, auf der man war, mit dem Hinweis.
  Strg+5 und „PDF Reader & Editor“ öffnen ohne Dokument die Dateiauswahl; Strg+O öffnet auf Start und in den
  Einstellungen eine PDF.
- Beim Beenden laufen keine Übergänge der Tab-Leiste mehr (`App.closing`), und zum Löschen vorgemerkte
  QML-Objekte enden vor der Engine (`finish_incubation`) – kein Abbau halb gelöschter Tabs.
- Die gespeicherte Einstellung `nav_kompakt` älterer Versionen bleibt erhalten, wird aber nicht mehr gelesen.

## Startseite

- Werkzeuge in einer Karte (Symbol, Name, Beschreibung, „Öffnen ›“, Tastenkürzel), daneben die Ablagefläche
  „PDF hierher ziehen“ mit „Datei öffnen“; schmal untereinander. Drei Werkzeuge nebeneinander nur, wenn jedes
  seine Fußzeile ganz zeigen kann (Schrift und Skalierung bestimmen die Breite) – sonst untereinander.
- „Zuletzt verwendet“ (bisher „Zuletzt geöffnet“ im leeren Reader): Name, Ordner, wann geöffnet („Heute, 14:05“,
  „Gestern, 09:12“, Datum), Größe wie im Explorer; Klick öffnet, „Im Ordner zeigen“, Entfernen, „Liste leeren“.
  Gespeichert werden nur Pfad und Zeitpunkt (`reader_zuletzt_zeit`), Einträge älterer Versionen zunächst ohne
  Zeitpunkt. Die Zeitangaben werden beim Zeigen der Startseite neu gebildet.
- Datenschutzhinweis unter der Liste, ergänzt um das sichere Speichern (Prüfung der neuen Datei vor dem Ersetzen).

# PDF Tool 3.1.0-beta.3

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Feinschliff: optische und technische Fehler der
ganzen App behoben, fehlende Bewegungen ergänzt; Details in den [Release Notes](release-notes/3.1.0-beta.3.md).

## Scrollen

- Jede Mausrad-Raste verschiebt um dieselbe Strecke, schnell gedrehte Rasten addieren sich (Qts eigene
  Bewegung begann bei jeder Raste neu und verlor beim zügigen Drehen bis zu gut der Hälfte der Strecke).
  Strecke je Raste wie in Edge und Chrome: rund 32 px je Zeile der Windows-Einstellung (Standard 96 statt
  72 px; „Eine Bildschirmseite“: die Höhe der Ansicht ohne zwei Zeilen). Gilt für Seiten, Listen, PDF-Ansicht, Seitenleisten, „Seiten organisieren“, Vorschau und Dialoge
  (`PWheelScroll`); an seinem Ende gibt ein Bereich das Mausrad an den umgebenden weiter.
- Die Bildlaufleiste erscheint auch beim Scrollen mit Mausrad und Tastatur kurz.

## PDF Reader & Editor

- Werkzeuge lassen sich abwählen: Ein Klick auf das gewählte Werkzeug kehrt zu „Auswählen“ zurück (bisher
  änderte sich nur die Schaltfläche). Ebenso die Feldarten beim Gestalten von Formularen.
- Umschalter zeigen immer den wirklichen Zustand (Werkzeuge, „Seiten organisieren“, „Seitenbreite“,
  „Ganze Seite“, Fett/Kursiv/Unterstrichen/Durchgestrichen/Ausrichtung im Texteditor): Sie schalten sich
  nicht mehr selbst um und verlieren so nie die Bindung an den Zustand.
- Neues Werkzeug „Verschieben“ (Hand): Dokument mit gedrückter linker Maustaste ziehen. In jedem Werkzeug
  zieht die linke Maustaste auf der freien Fläche neben den Seiten, die mittlere überall; Umschalt +
  Mausrad verschiebt waagerecht.
- Seiten organisieren: Die Befehlsleiste wächst beim Umbrechen mit („Text erkennen …“ lag über der ersten
  Seitenreihe); „1 Seite“ statt „1 Seiten“.
- Der Texteditor blendet beim Öffnen ein.

## Oberfläche

- Navigation eingeklappt: Die Überschrift „Tools“ wird zur schmalen Trennlinie (bisher blieb sie
  unsichtbar 32 px hoch – zwischen „Start“ und den Tools lagen 40 statt 4 px). Sie schrumpft mit der
  Breite; die Markierung des gewählten Eintrags bleibt dabei auf ihrem Eintrag.
- Vertragsübersichten und Stapel-Filter: Die Markierung der gewählten Ansicht wurde nie gezeichnet (der
  Repeater meldete seine Einträge, bevor es sie gab); jetzt gleitet sie zur gewählten Ansicht. Die
  Einträge springen beim Wechsel nicht mehr (Breite für die fette Schrift reserviert).
- Kartenköpfe ohne Untertitel: Schaltflächen rechts mittig zur Titelzeile.
- Stapel: Abstand unter den Ansichten wie überall (bisher 12 px mehr); „Fügen Sie …“ statt „Füge …“;
  Überschriften leerer Listen ohne Punkt (auch „Kunden“).
- PDF reparieren: „PDFs auswählen“ mit Ordnersymbol.
- Statuszeile: Das Symbol blendet mit der Meldung um.
- „1 Seite“/„2 Seiten“ statt „Seite(n)“ beim Öffnen, Drucken, in der Texterkennung, beim Export, in den
  Hinweisen von „PDF reparieren“ und in der Kundenakte.

# PDF Tool 3.1.0-beta.2

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Nur Leistung – keine neuen Funktionen;
Messwerte in den [Release Notes](release-notes/3.1.0-beta.2.md).

## Schneller

- Start: Die Startseite steht im ersten Bild (bisher erschien das Fenster mit leerer Fläche, die
  Startseite folgte einige Bilder später). Die PDF-Bibliotheken (pikepdf, PDFium) und die Module des
  Editors lädt PDF Tool erst nach dem Start im Arbeitsthread, wenn alle Seiten fertig sind.
- PDF per Doppelklick bzw. „Öffnen mit“: Start direkt im Reader statt über die Startseite; die
  PDF-Bibliotheken laden bereits, während das Fenster entsteht.
- Reader: Die Seite ist sofort da – ihr Dokumentbereich (Tabs, Leisten, Ansicht, Seitenleisten)
  entsteht im Hintergrund, wird vorher ein PDF geöffnet, sofort.
- PDF reparieren: Ein Arbeitsprozess erledigt mehrere Dateien nacheinander (höchstens 25; nach einem
  Fehler, einem Absturz oder „Abbrechen“ übernimmt ein frischer). Er startet in einem Hilfsthread –
  die Oberfläche wartet nie auf den Prozessstart (unter Windows bis zu einer halben Sekunde je Datei) –,
  beim Öffnen der Seite wird einer im Voraus vorbereitet; Meldungen werden alle 30 statt 80 ms
  abgeholt.

## Behoben

- Seitenbilder, die beim Schließen eines PDFs gerade entstanden, blieben im Zwischenspeicher.
- Miniaturen: Nach einem Tabwechsel wurden kurz Bilder für Seiten angefragt, die es im neuen Dokument
  nicht gibt („Seite nicht vorhanden“ im Protokoll).

## Entwicklung

- `tests/bench_app.py`: Messung der App mit Oberfläche (Start, Start mit PDF, Öffnen, Tab- und
  Seitenwechsel, Zoom, Suche, Speichern, „PDF reparieren“ mit vielen Dateien, Arbeitsspeicher), auch
  für einen anderen Stand (`--app`).
- Oberflächentests warten auf die geladenen Seiten über `App.pagesLoaded` statt den Elementbaum
  alle 10 ms zu durchsuchen (das hielt den GIL und verlangsamte das Laden): Der Start der App je
  Test dauert lokal rund 2 statt 13–19 Sekunden.

# PDF Tool 3.1.0-beta.1

Beta zum Testen (Schalter „Beta-Versionen erhalten“). Bringt Formulare gestalten, die lokale
Texterkennung (OCR), Vektorobjekte und die Zwischenablage in „Objekt bearbeiten“, Seiten über Tabs
hinweg und einen erweiterten Reader.

## Neu

- Formulare gestalten: Textfeld, Kontrollkästchen, Optionsfeld (Gruppe, „Option hinzufügen“),
  Dropdown und Liste anlegen (Rahmen aufziehen, Klick, Rechtsklick „… hier“); verschieben (Ziehen,
  Pfeiltasten), Größe an den Ecken, duplizieren (Strg+D), löschen (Entf); Dialog „Feldeigenschaften“
  (Name, Kurzinfo, Pflichtfeld, schreibgeschützt, mehrzeilig, Zeichenzahl, Schriftgröße, Ausrichtung,
  Optionen, Exportwert, Rahmen, Hintergrund). Erscheinungsbilder für jeden Zustand, Rückgängig je
  Schritt; XFA-Formulare werden nicht umgestaltet.
- Texterkennung (OCR) mit Tesseract 5.5.3 im Setup (Deutsch, Englisch, Lageerkennung): Hinweis bei
  gescannten Seiten, Dialog (alle, aktuelle, ausgewählte Seiten; Sprachen; erneut erkennen),
  Erkennung im Hintergrund mit Fortschritt und Abbrechen, unsichtbare Textebene, ein Schritt für
  Rückgängig, „Erkannten Text entfernen“.
- Objekt bearbeiten: Vektorobjekte (Linien, Rahmen, Pfade) mit Kontur, Füllung und Linienstärke;
  gemischte Auswahl aus Text, Bildern und Grafiken; Drehen, Ausrichten und Verteilen, Vorder- und
  Hintergrund, Deckkraft; Ausschneiden, Kopieren, Einfügen und „Hier einfügen“ – auch über Tabs und aus
  anderen Programmen.
- Seiten: Rahmenauswahl in „Seiten organisieren“, Seiten kopieren, ausschneiden und einfügen (auch in
  einen anderen Tab), nur ausgewählte Seiten aus einer PDF einfügen, Kontextmenü der Miniaturen,
  gewählte Seiten drucken.
- Kommentare: Linienstärke, Füllung, Deckkraft und Schriftgröße nachträglich, Größe an den Ecken,
  Antworten in der Seitenleiste.
- Text: Schriftart, unterstrichen, durchgestrichen, Ausrichtung, eigene Farben (Hex-Wert).
- Reader: Vollbild (F11), Seitenleiste „Anhänge“, Seitenleisten, Suche und Lage je Tab, erste/letzte
  Seite, „Gehe zu Seite“ (Strg+G), freie Zoomeingabe, Strg+A für den Text der Seite, Drucken mit
  Bereichen, Auswahl und Kopien; Einstellungen → PDF Reader: Ansicht neu geöffneter PDFs.
- PDF reparieren: fremde Daten vor bzw. nach dem PDF-Inhalt werden zuerst entfernt; beschädigte
  Datenströme so weit wie möglich gerettet.
- Einstellungen → Updates: Schalter „Beta-Versionen erhalten“ (Standard aus); Fenstertitel einer Beta
  „PDF Tool 3.1.0 Beta“ und Hinweis in „Über“.

## Geändert

- Updater: Angeboten werden nur Tags vX.Y.Z (Stable) und als Vorabversion markierte vX.Y.Z-beta.N
  (Beta); Entwicklerstände und andere Kennungen nie.
- Werkzeughinweise schweben über der Seite und blenden weich ein und aus wie die übrigen Meldungen.
- Startseite: drei gleich breite Werkzeugkarten, symmetrisch.
- Vertragsübersichten: Die Statusleiste nennt nur das Ergebnis der Excel-Prüfung.
- Linke Seitenleiste 300 px breit (Platz für vier Umschalter).
- Protokoll mit festen Bereichen (pdf, save, render, repair, ocr, ui, update, installer), ohne Inhalte.
- Setup: Texterkennung im Unterordner „ocr“, Lizenztext LICENSE (GPL-3.0) im Programmordner.

## Behoben

- „Zuletzt verwendet“ (Ansicht beim Öffnen) stellte die zuletzt benutzte Ansicht nicht wieder her.
- Die Leiste des Texteditors ragte in schmalen Fenstern über den Rand.
- Beim Beenden ging ein in PDF Tool kopierter Text in der Zwischenablage verloren.

## Intern

- Workflow „Release-Prüfung“: von Hand angelegte oder geänderte Releases werden geprüft.
- Upgrade- und Update-Test von der unmittelbar vorherigen veröffentlichten Version (bei einer Beta auch
  einer Beta).
- Dependabot bündelt Updates; die Qt-Tests laufen in sechs Jobs, jede Testdatei läuft in der CI.

# PDF Tool 3.0.0-beta.2

Beta zum Testen (Kanal „Beta“). Behebt den Fehler beim Speichern von PDFs mit XMP-Metadaten aus
3.0.0-beta.1 und bringt das Werkzeug „Objekt bearbeiten“ sowie einen aufgeräumten Reader.

## Neu

- PDF Editor: Werkzeug „Objekt bearbeiten“. Es wählt Text und Bilder einzeln statt ganzer
  Textblöcke.
  - Auswahl: eine Zeile einer Adresse, eine Tabellenzelle oder ein Wort; ein Klick wählt die Zeile,
    ein weiterer Klick das Wort, ein Doppelklick bearbeitet genau dieses Stück.
  - Aktionen: ändern, verschieben (Ziehen oder Pfeiltasten), löschen, Größe, Farbe und
    Zeichenabstand ändern, duplizieren, ausrichten.
  - Mehrfachauswahl mit Strg+Klick oder Rahmen; Kontextmenü und Eigenschaften in der rechten
    Seitenleiste.
  - Änderungen geschehen direkt im PDF und in der Originalschrift. Fehlen der Schrift Zeichen, wird
    der Text neu gesetzt. Nur wo beides nicht sicher geht, wird überlagert, und der Hinweis sagt das.
  - Alles andere auf der Seite bleibt an seinem Platz.
  - Seiten ohne Text melden „Auf dieser Seite wurde kein bearbeitbarer PDF-Text erkannt.“

## Geändert

- PDF Reader: Seitenleisten neu geordnet.
  - Die Umschalter sitzen im Kopf der jeweiligen Leiste: links Seiten, Lesezeichen und Suchen,
    rechts Kommentare und Eigenschaften. Die Befehlsleiste enthält keine Seitenleisten-Umschalter
    mehr.
  - Eine geschlossene Leiste bleibt als schmaler Streifen mit ihren Symbolen und öffnet sich
    darüber wieder.
  - Beide Leisten haben eine feste Breite: Wechsel zwischen Seiten, Lesezeichen und Suchen ändern
    die Breite nicht mehr.
  - Alle Köpfe sind gleich aufgebaut, und leere Leisten (keine Lesezeichen, keine Kommentare, kein
    Objekt gewählt) zeigen einen ruhigen Hinweis.
  - Beim Öffnen und Schließen gleitet die Leiste kurz herein bzw. hinaus („Reduziert“: Überblenden,
    „Aus“: sofort). Die Seiten werden dabei nur einmal neu angeordnet, und eine ganz oben stehende
    Ansicht bleibt oben.
- PDF Reader: Bewegung nach dem Animationsprofil der App („Vollständig“, „Reduziert“, „Aus“).
  - Dokument-Tabs blenden ein und aus, die übrigen rücken nach, die Markierung des aktiven Tabs gleitet.
  - Ungespeichert zeigt ein Punkt, der weich ein- und ausblendet, statt „*“ im Namen.
  - Werkzeugmarkierung, Auswahl im Kopf der Seitenleisten und Kontextmenüs (Einblenden mit leichtem
    Wachsen) bewegen sich weich.
  - Seitenbilder, Miniaturen und Änderungen auf der Seite blenden kurz ein.
  - Zoom über Schaltflächen und Tastatur gleitet kurz.
  - Suchtreffer blenden ein, der aktuelle Treffer wird beim Wechsel kurz hervorgehoben.
  - Beim Ziehen in „Seiten organisieren“ zeigen Platzhalter die neue Stelle, eine Vorschau folgt dem
    Zeiger, die übrigen Seiten rücken weich nach. Gelöschte und eingefügte Seiten blenden aus bzw. ein.
  - Eine über die Ansicht gezogene PDF zeigt eine Ablagefläche, die weich ein- und ausblendet.
  - Die Fokusmarkierung von Formularfeldern blendet weich ein und aus.
  - Scrollen und Strg+Mausrad bleiben direkt.
- Seiten organisieren: Nach dem Verschieben bleiben die verschobenen Seiten an ihrer neuen Stelle gewählt.
- App-Navigation: Bei geöffnetem Dokument ist sie im Reader eingeklappt. Die Menüschaltfläche klappt
  sie vorübergehend aus, bis zum nächsten Dokument. Der eingeklappte Zustand zeigt zentrierte Symbole
  und den gewählten Bereich mit dezenter Akzentfläche.
- PDF Reader: Eine Textauswahl blendet keine eigene Aktionsleiste mehr ein. Kopieren, Markieren,
  Unterstreichen, Durchstreichen und Notiz stehen im Kontextmenü (Rechtsklick), Strg+C kopiert.
- „Ganze Seite“ passt beim Blättern in der seitenweisen Ansicht jede Seite neu ein. In der
  fortlaufenden Ansicht bleibt der Zoom beim Scrollen gleich.

## Behoben

- PDF Editor: Speichern schlug bei PDFs mit XMP-Metadaten (die meisten PDFs aus Office-Programmen,
  Acrobat oder Scannern) mit „Das Dokument konnte nicht geschrieben werden.“ fehl. Ursache: Beim
  Schreiben wollte pikepdf die PDF-Version in den XMP-Metadaten nachtragen und brauchte dafür lxml,
  das nicht zum Programm gehört. Die XMP-Metadaten bleiben jetzt beim Speichern unverändert. Davon
  betroffen waren auch die Sitzungssicherung für ungespeicherte Änderungen und „Eigenschaften“
  (meldete fälschlich beschädigte XMP-Metadaten) – beides funktioniert wieder, Titel, Autor, Thema
  und Stichwörter werden in Info und XMP gemeinsam geändert
- Speichern meldet Fehler verständlich und bietet „Speichern unter …“ direkt an: Datei
  schreibgeschützt, keine Schreibberechtigung am Speicherort, Datei in einem anderen Programm
  geöffnet (genau geprüft statt vermutet), Datenträger voll; technische Angaben stehen ohne Pfad
  und ohne Inhalte im Protokoll
- die gespeicherte Datei wird nach dem Ersetzen wie beim Öffnen nachgeprüft; erst dann gilt das
  Dokument als gespeichert (der Punkt für „ungespeichert“ verschwindet), bei einem Fehler bleibt es
  ungespeichert und Rückgängig bleibt möglich
- je Dokument läuft höchstens ein Speichervorgang: mehrfaches Strg+S schreibt die Datei einmal,
  „Speichern“ beim Schließen während eines laufenden Speicherns wartet darauf
- Speichern wartet nicht mehr auf eine laufende Suche (die Suche läuft danach weiter); Ansicht,
  Seite, Zoom, Seitenleisten und Tabs bleiben beim Speichern unverändert
- Werkzeugleiste: „Speichern …“ während des Speicherns, danach kurz „Gespeichert“ – ohne Dialog
- PDF Reader: „Ganze Seite“ konnte bei unterschiedlich großen Seiten (z. B. Hoch- und Querformat)
  beim Scrollen zwischen den Seiten hin- und herspringen.
- „Notiz hier hinzufügen“ aus dem Kontextmenü: Die Eingabe hatte bei eingeschalteten Animationen
  nicht sofort den Tastaturfokus.
- PDF Reader: Miniaturen zeigten beim schnellen Scrollen und beim Wechsel zwischen Dokumenten kurz
  das Bild einer anderen Seite bzw. des anderen Dokuments, bis das richtige Bild fertig war; in
  „Seiten organisieren“ beim schnellen Scrollen ebenso. Bis dahin steht jetzt das leere Blatt.
- Formular ausfüllen: Nach der Eingabetaste oder Escape blieb die Tastatur im ausgeblendeten
  Eingabefeld. Tastendrücke landeten dort, und die Markierung des Felds blieb stehen. Jetzt geht die
  Tastatur wie nach dem Textbearbeiten zurück an die Seite.

# PDF Tool 3.0.0-beta.1

Beta zum Testen (Kanal „Beta“). Neues Werkzeug „PDF Reader & Editor“.

## PDF Reader

- PDFs öffnen über „Öffnen“ (Strg+O), Ziehen in das Fenster, „Zuletzt geöffnet“ (leerbar) und
  „Öffnen mit“ im Explorer (läuft PDF Tool schon, öffnet sich die Datei dort als neuer Tab; PDF Tool
  wird dabei nicht zur Standard-App)
- Tabs mit „*“ bei ungespeicherten Änderungen; Schließen mit „Speichern“ / „Nicht speichern“ /
  „Abbrechen“; Strg+Tab, Strg+W
- scharfe Darstellung bei jeder Windows-Skalierung; Ansichten Einzelseite, fortlaufend, zwei Seiten,
  fortlaufend zweiseitig; Zoom 25–400 % in Stufen, frei mit Strg+Mausrad (um den Mauszeiger),
  Seitenbreite, ganze Seite, Originalgröße
- Miniaturen, Lesezeichen, Seitennavigation, Textauswahl und Kopieren, Suche (Strg+F, F3) mit
  Groß-/Kleinschreibung und ganzem Wort
- Drucken über den Druckdialog von Windows (Bereich, Kopien, Ausrichtung, Anpassung) und
  Druckvorschau; Seiten als PNG/JPEG exportieren; Eigenschaften und Metadaten
- große Dokumente (1000+ Seiten): nur sichtbare Seiten werden aufgebaut und gezeichnet,
  begrenzter Zwischenspeicher

## PDF Editor

- Text ändern mit ehrlich benanntem Weg: „Direkt im PDF geändert (Originalschrift)“, „Neu gesetzt
  (Originaltext entfernt)“ oder „Kompatibilitätsmodus“ (Überlagerung – keine Schwärzung); jede
  Änderung wird geprüft, sonst zurückgenommen; Text hinzufügen mit Schrift, Größe, Farbe
- Bilder auswählen, verschieben, Größe ändern, drehen, ersetzen, löschen, PNG/JPEG einfügen
- Seiten organisieren: Raster mit Mehrfachauswahl und Ziehen, drehen, löschen, duplizieren, leere
  Seite, aus PDF einfügen, PDFs anhängen, extrahieren, teilen
- Kommentare: markieren, unterstreichen, durchstreichen, Notiz, Freihand (auch als sichtbare
  Unterschrift), Rechteck, Ellipse, Linie, Pfeil, Textfeld; vorhandene Kommentare bleiben erhalten
- Formulare (AcroForm) ausfüllen; PDF-JavaScript wird nie ausgeführt
- Rückgängig/Wiederholen je Dokument (Strg+Z, Strg+Y)

## Sicher speichern

- Strg+S / Strg+Umschalt+S: Prüfung der neuen Datei vor dem Ersetzen, atomares Ersetzen, Sicherung
  des vorherigen Stands; bei einem Fehler bleibt das Original unverändert
- von außen geänderte Dateien werden nicht still überschrieben
- verschlüsselte PDFs: Passwort nur im Arbeitsspeicher, Berechtigungen werden beachtet;
  digital signierte PDFs: Warnung vor der ersten Änderung
- beschädigte PDFs: „PDF reparieren“ wird angeboten (nie automatisch)
- ungespeicherte Änderungen werden lokal gesichert und nach einem Absturz zum Wiederherstellen
  angeboten

## Weitere Änderungen

- Startseite: Werkzeug „PDF Reader & Editor“ (Strg+5); eine auf die Startseite gezogene PDF öffnet
  sich im Reader („PDF reparieren“ nimmt PDFs auf seiner eigenen Seite an)
- Diagnose nennt die Engines des Editors (pikepdf/qpdf, PDFium, fontTools)
- Laufzeit: fontTools 4.66.1 (MIT) für Schrift-Teilmengen, Qt Print Support für den Druck

# PDF Tool 2.8.0

Freigegebene Version – getestet als Beta 2.8.0-beta.1, Funktionsumfang unverändert.

## Vorlagen 2.0

- je Vorlage eine eigene Datei mit fester ID und Schema-Version (`vorlagen\`); Vorlagen bis 2.7
  werden beim ersten Start einmalig übernommen, die bisherige Liste bleibt unverändert
- neue Ansicht „Vorlagen“: suchen, ansehen, anwenden, laden und bearbeiten, umbenennen,
  duplizieren, Beschreibung, Standardvorlage, löschen (Verweise in Kundenakten, Stapel und
  Standardvorlage werden dabei kontrolliert gelöst)
- „Darstellung“: geladene Vorlage mit „Vorlage geändert“, „Vorlage aktualisieren“, „Als neue
  Vorlage speichern“ und „Änderungen verwerfen“; die Vorlage hält auch das Regelwerk fest
- Standardvorlage für jede neue Übersicht (rückgängig machbar) und als vierte Stufe im Stapel:
  Eintrag → Kundenakte → Vorlage des Stapels → Standardvorlage → Darstellung

## Regelwerk 2.0

- Regelwerke mit Regeln „WENN … DANN …“: Bedingungen für Text, Zahl (Netto) und Datum (Beginn),
  „alle“ oder „mindestens eine“; Aktionen setzen, ersetzen, voranstellen, anhängen, leeren für Art,
  Beschreibung, Abrechnungszyklus und Zahlungsart – keine Skripte, kein Code
- neue Ansicht „Regeln“: Regelkarten, visueller Editor, Reihenfolge, duplizieren, entfernen mit
  „Rückgängig“, ein- und ausschalten; automatisch gespeichert
- Testmodus („Trifft auf 7 von 18 Verträgen zu“) und Vorschau vorher → nachher mit Konflikten,
  im Hintergrund berechnet; „Übersicht erstellen“ nennt, was das Regelwerk ändert
- wirkt auf PDF, Vorschau, Stapel und Vertragsstand (gespeichert werden die exportierten Werte),
  nie auf die Excel-Datei; Stapel: Regelwerk je Eintrag

## Sicherung & Wiederherstellung

- Sicherung als `.pdtbackup` (ZIP mit Manifest und SHA-256 je Datei), atomar erstellt und geprüft
- „Jetzt sichern …“ in einen Ordner Ihrer Wahl; automatisch einmal täglich bei Änderungen und vor
  jedem Update; die letzten 10 automatischen bleiben, manuelle werden nie automatisch gelöscht
- Wiederherstellen: vollständige Prüfung, Zusammenfassung, Auswahl der Bereiche, Sicherung des
  aktuellen Stands, Ausführung beim Neustart – atomar mit Rückabwicklung; Sicherungen einer
  neueren Version werden nie eingespielt

## Diagnose

- Systeminformationen (Version, Kanal, Python, Qt, Windows, Pfade, Module, Reparatur-Engines)
- Datenprüfung ohne Änderungen (Einstellungen, Kundenakten, Vorlagen, Regelwerke, Vertragsstände,
  Sicherungsordner, temporärer Ordner, freier Speicher)
- Support-Paket (ZIP) mit Bericht und bereinigten Protokollen – ohne Kunden- oder Dokumentdaten
- Protokoll `pdf-tool.log` mit Rotation; eigene temporäre Dateien früherer Sitzungen werden
  aufgeräumt

## Weitere Änderungen

- Ansichtsleiste von „Vertragsübersichten“ verschiebbar, wenn die Breite nicht reicht
- Stapel: „Standardvorlage“ heißt jetzt „Vorlage des Stapels“ (die Standardvorlage gilt für alle)
- Speichern wiederholt kurz gesperrte Dateien (z. B. durch Virenscanner) statt abzubrechen
- Oberfläche: Schutz vor einem Absturz der QML-Engine (Qt 6.11) beim Laden der Ansichten im
  Hintergrund
- Release-Workflow: ein stabiles Release setzt eine veröffentlichte Beta derselben Version voraus

# PDF Tool 2.8.0-beta.1

Beta zum Testen (Kanal „Beta“) mit dem Umfang von 2.8.0 (siehe oben).

# PDF Tool 2.7.2

## In-App Updates

- PDF Tool kann jetzt direkt in der Anwendung nach Updates suchen
- Updates können direkt heruntergeladen werden
- Downloads werden per SHA-256 überprüft
- Installation erfolgt weiterhin sicher über das PDF-Tool-Setup

## Stable- und Beta-Kanal

- Stable bleibt der Standard
- Beta kann optional aktiviert werden
- Beta-Nutzer erhalten Vorabversionen zum Testen
- Stable-Nutzer erhalten ausschließlich freigegebene Releases

## Hintergrundprüfung

- automatische Updateprüfung
- blockiert den Programmstart nicht
- Offline-Betrieb bleibt vollständig möglich

## Korrekturen

- Eine Rückfrage direkt nach einem Dialog mit Inhalt (z. B. nach den Update-Details) übernahm
  dessen Höhe und zeigte eine große leere Fläche; sie ist jetzt so hoch wie ihr Text.

# PDF Tool 2.7.1

## PDF reparieren: mehrere PDFs

- mehrere PDFs gleichzeitig reparieren
- Multi-File Drag & Drop
- Batch-Reparatur
- individuelle Ausgabedateinamen
- optionales "_repariert" im Dateinamen
- sichere automatische Konfliktauflösung
- Fortschritt und Ergebnis pro PDF
- Batch-Ergebnisübersicht

Im Einzelnen: Mehrfachauswahl im Dialog, mehrere Dateien zugleich ablegen, später weitere
hinzufügen; dieselbe Datei nur einmal, andere Dateien mit Hinweis. Jede PDF wird für sich
analysiert (höchstens zwei Arbeitsprozesse) und nacheinander mit der unveränderten Engine aus
2.7.0 repariert – keine eigene Batch-Engine. Zustand je Datei, Gesamtstand („8 PDFs · 6
reparierbar · 1 verschlüsselt · 1 nicht wiederherstellbar“), „Alle reparieren“, „Nur diese Datei
reparieren“, „Abbrechen“ (fertige Dateien bleiben), „Fehlgeschlagene erneut versuchen“,
Zusammenfassung mit „Ausgabeordner öffnen“. Passwörter gelten nur für ihre Datei; signierte
Dateien lassen sich auf Rückfrage überspringen; der Rettungsmodus gilt nur für eine Datei und nur
nach Bestätigung. Mit einer PDF bleibt der Ablauf wie in 2.7.0.

Dateinamen: Schalter „„repariert“ an Dateinamen anhängen“ (Standard ein, auch nach dem Update)
mit änderbarem Zusatz; eigener Name je Datei mit sofortiger Prüfung auf unter Windows ungültige
Namen. Ein Name, den es schon gibt – ohne Rücksicht auf Groß-/Kleinschreibung, das Original selbst
oder schon für eine andere Datei der Liste geplant –, wird nummeriert: `Rechnung_repariert (1).pdf`
statt bisher `Rechnung_repariert_2.pdf`. Die Namen werden beim Start reserviert; eine vorhandene
Datei wird nie überschrieben, das Original nie verändert, umbenannt oder gelöscht.

## Korrekturen

- Listen-Seiten (PDF reparieren, Stapel, Kunden, Vertragsvergleich) bleiben oben, wenn sich der
  Kopfbereich ändert (Hinweis, aufklappender Bereich, erste Datei) – der Seitentitel rutschte
  vorher aus dem Bild. Wer zu den Zeilen gescrollt hat, behält sie im Blick.

## Tests

- `tests/test_pdf_repair_batch.py`: Liste, Zustände, Namensregel, Windows-Namen, Konflikte,
  Nummerierung, Reservierung.
- `tests/test_qt_repair.py`: alle Abläufe aus 2.7.0 mit einer PDF sowie 10 gemischte PDFs,
  Abbrechen bei Datei 4 von 10, Passwort nur je Datei, Signaturen überspringen, kein stiller
  Rettungsmodus, Fehlgeschlagene erneut, globaler Schreibfehler, 100 PDFs, Animationsprofile,
  Schalter aus/an, eigener Name, gleiche Namen aus verschiedenen Ordnern, Neustart.
- Datenmigration: Einstellungen von 2.7.0 (`config_v270.json`).

# PDF Tool 2.7.0

## Neue Oberfläche

PDF Tool wurde vollständig auf PySide6 und Qt Quick/QML umgestellt. Die Fachlogik ist unverändert;
QObject-Controller je Bereich verbinden sie mit der QML-Oberfläche. Die produktive App enthält kein
Tkinter mehr, die Laufzeit kein Tcl/Tk.

## Modernes Design

Komplett überarbeitete Windows-11-orientierte Oberfläche mit zentralem Design-System (Farben,
Abstände, Radien, Schrift, Animationsdauern); Hell/Dunkel/„Wie Windows“ und Akzentfarbe wirken
sofort.

## Animationen

Neue Animationen für:

- Navigation
- Menüs
- Dialoge
- Accordions
- InfoBars
- Buttons
- Toggle Switches
- Statuswechsel

Einstellbar: Vollständig, Reduziert, Aus (Windows „Animationseffekte aus“ → mindestens Reduziert).

## Performance

Neue Model/View-Architektur und effizienteres Rendering: Listen melden nur geänderte Zeilen,
virtualisierte Listen für Stapel, Kunden und Vertragsänderungen, Seiten entstehen einmal,
Hintergrundarbeit ohne blockierte Oberfläche.

## High DPI

Verbesserte Darstellung auf hochauflösenden Displays (100–200 %), Symbole als Vektorgrafik.

## Bestehende Funktionen

Alle Funktionen aus 2.6.1 wurden übernommen. Keine manuelle Migration: Einstellungen, Kunden,
Vorlagen, Regeln und Vertragsstände werden weiterverwendet.

## Korrekturen und Qualitätssicherung

- RichText-Kopf-/Fußzeilenintegration für Qt/QML korrigiert
  – gespeicherte Kopf- und Fußzeilen erscheinen wieder vollständig im Editor (das Textfeld blieb
  eine Zeile hoch und zeigte nichts an), Klicken, Markieren mit der Maus und Scrollen funktionieren
  in jeder Zeile, Umschalt+Eingabe beginnt wieder einen Absatz; der Inhalt wird nach jeder Änderung
  sofort ins Python-Modell übernommen (gespeichert wird weiterhin verzögert), »Kopfzeile speichern«
  und »Fußzeile speichern« aktualisieren die Vorschau. Dasselbe gilt für das Notizfeld der Kundenakte.
- Einfügemarke in Kopf- und Fußzeile an Schrift und Grundlinie ausgerichtet
  – so hoch wie die Schrift am Cursor (Ober- plus Unterlänge, geprüft mit 8 bis 24 pt), auf der Grundlinie der
  Zeile, in ganzen Gerätepixeln (100 bis 200 % gleich schmal und scharf); im leeren Feld nicht mehr
  10 px hoch oben links, sondern dort, wo der Text entsteht – auch zentriert. Der Platzhalter steht in
  derselben Schrift und Ausrichtung wie der spätere Text. Sichtbar nur mit Textfokus; die
  Formatleiste zeigt in einer Leerzeile deren eigenes Format.
- Startseite visuell symmetrisch überarbeitet
  – beide Werkzeugkarten exakt gleich breit und hoch, gleicher Innenaufbau, »Öffnen« und
  Tastenkürzel auf einer Linie, Gruppe mittig mit gleichem Abstand links und rechts, Titel und
  Datenschutzhinweis an der Kante der Karten, unter 736 px Gruppenbreite eine Spalte.
- Installer-/Upgrade-Tests deutlich effizienter gestaltet
  – ältere Einstellungen (2.2.0 bis 2.6.1) prüfen schnelle Migrationstests mit Fixtures statt
  alter Setups; die vollständige historische Prüfung gibt es nur noch als manuellen Workflow
  »Deep Compatibility Test«.
- normaler Upgrade-Test beschränkt sich auf vorherige stabile Version → aktuelle Version
  – für 2.7.0: Clean Install 2.7.0 und Update 2.6.1 → 2.7.0; die Vorversion wird nach SemVer
  aus den veröffentlichten Releases bestimmt und ihr Setup zwischengespeichert, nie neu gebaut.

# PDF Tool 2.6.1

Qualitäts-Update: flüssigere Oberfläche, optimiertes Rendering, optionale Kundenakte (Standard aus).
Siehe [`release-notes/2.6.1.md`](release-notes/2.6.1.md).

# PDF Tool 2.6.0

Vertragsvergleich mit gespeicherten Vertragsständen, erweiterte PDF-Wiederherstellung.
Siehe [`release-notes/2.6.0.md`](release-notes/2.6.0.md).

# PDF Tool 2.5.0

Stapelverarbeitung, kompakte Excel-Karte. Siehe [`release-notes/2.5.0.md`](release-notes/2.5.0.md).

# PDF Tool 2.4.0

Kundenakte mit Wiedererkennung, Ansicht „Kunden“, Live-Vorschau.
Siehe [`release-notes/2.4.0.md`](release-notes/2.4.0.md).

# PDF Tool 2.3.0

Neuer Name „PDF Tool“, Werkzeug „PDF reparieren“. Siehe [`release-notes/2.3.0.md`](release-notes/2.3.0.md).

# Übersichten-Ersteller 2.2.0

Excel-Fettschrift, formatierte Kopf- und Fußzeilen. Siehe [`release-notes/2.2.0.md`](release-notes/2.2.0.md).
