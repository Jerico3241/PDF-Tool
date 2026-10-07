# QML-Stilregeln von PDF Tool

Diese Regeln halten die Oberfläche einheitlich, schnell und frei von Fachlogik. Sie gelten für
alles unter `windows-app/app/qml/`.

## Farben, Maße, Schrift, Bewegung – nur aus `PdfTool.Style`

- **Keine festen Farben.** Farben kommen aus `Theme` (z. B. `Theme.textPrimary`, `Theme.surface`,
  `Theme.accent`, `Theme.border`, `Theme.toneBackground(kind)`); sie folgen Hell/Dunkel und der
  Akzentfarbe live. Ausnahme ist nur das „Papier“, das in jedem Design wie das gedruckte Dokument
  aussieht: das weiße Blatt der Vorschau, die Schreibfläche der Kopf- und Fußzeilen-Editoren und die
  Farbfelder der Textfarbe. Standardwerte in `Theme.qml` gelten nur, bis die Design-Tokens da sind.
- **Zentrale Maße:** Abstände, Radien, Höhen und Breiten aus `Metrics` (`Metrics.radiusCard`,
  `Metrics.controlHeight`, `Metrics.pagePaddingLeft`, `Metrics.twoColumnsFrom` …). Neue Werte zuerst
  in `Metrics.qml` anlegen.
- **Zentrale Schrift:** `Typography` (caption, body, bodyStrong, subtitle, title …) bzw. `PText`
  mit `textStyle` und `tone` – keine eigenen Schriftgrößen (einzige Ausnahme: die Buchstaben der
  Format-Schaltflächen B/I/U/S im Rich-Text-Editor zeigen die Formatierung selbst).
- **Zentrale Animationsdauern:** nur `Motion` (`Motion.fast`, `Motion.normal`, `Motion.fade`,
  `Motion.expand`, `Motion.pageIn` …) und seine Kurven (`Motion.decelerate`, `Motion.accelerate`).
  Bewegungen (Verschieben, Skalieren, Höhenanimation) nur, wenn `Motion.moves`; Überblendungen,
  wenn `Motion.enabled`. So wirken die Profile „Vollständig“, „Reduziert“ und „Aus“ überall sofort.
- **Symbole** nur über `PIcon` (`image://icons/<name>/<Farbe>`, Fluent UI System Icons unter
  `qml/icons/`).

## Keine Fachlogik in QML

- QML zeigt an und ruft Slots der Controller auf (`Contracts.startPdf()`, `Repair.cancel()` …).
  Entscheidungen (Ist die Excel bereit? Welcher Kunde passt? Was steht im Hinweis?) trifft Python.
- Texte, die von Daten abhängen, liefert der Controller als Property; QML setzt sie nicht aus
  Fachdaten zusammen.
- Listen kommen als Modelle aus Python (`KeyedListModel`); QML filtert oder sortiert sie nicht.

## Keine Dateizugriffe aus QML

- Kein `XMLHttpRequest`, kein `Qt.openUrlExternally`, keine `file:`-URLs für Daten, kein Lesen oder
  Schreiben von Dateien in QML. Dateiauswahl, Öffnen, Ordner zeigen und Kopieren von Pfaden laufen
  über Slots der Controller (`App.copyPath`, `Contracts.pickExcel`, …).
- Bilder aus Dateien (Vorschau) kommen über Bildquellen der Controller (`image://preview/…`).

## Aufbau und Leistung

- Seiten: `PPage` (scrollende Seite) bzw. `PListPage` (lange, virtualisierte Liste). Zeilen nutzen
  `columnX`/`columnWidth` der Seite.
- **Mausrad:** Jede eigene scrollende Ansicht (`Flickable`, `ListView`, `GridView`) bekommt
  `PWheelScroll { flickable: … }` – jede Raste verschiebt gleich weit, schnell gedrehte Rasten
  addieren sich, die Bewegung folgt `Motion`. `PPage` und `PListPage` haben es schon. Qts eigene
  Mausrad-Bewegung beginnt bei jeder Raste neu an der erreichten Stelle und verliert beim zügigen
  Drehen bis zur Hälfte der Strecke (Test: `test_qt_shell.py`).
- Große Listen immer als `ListView` mit Modell und `reuseItems`, nie als `Repeater` über hunderte
  Einträge. Wiederverwendete Zeilen (`ListView.onReused`) setzen zurück, was Übergänge oder eigene
  Zustände verändert haben (z. B. `opacity`/`scale` nach `add`/`remove`, aufgeklappte Details – deren
  Zustand gehört der Seite, nicht der Zeile). Inhalte, die erst beim Aufklappen gebraucht werden,
  entstehen per `Loader` (`active: offen || animating`).
- `PListPage` hält eine Liste, die ganz oben stand, oben, wenn sich der Kopfbereich ändert
  (`pinnedTop`) – ListView allein hielte die Zeilen fest und schöbe den Seitentitel hinaus.
- Ein abgeschalteter `Loader` behält seine letzte `implicitHeight`: in Layouts zusätzlich
  `visible: active`, außerhalb die Höhe aus `item` ableiten. Zwischenzustände vermeiden – mehrere
  Bedingungen, die sich nacheinander ändern (`hasFile`, dann `single`), nicht kombinieren, wenn
  eine Größe (`count`) es in einem Schritt sagt.
- Bereiche, die auf- und zuklappen, mit `PCollapse`; Hinweise mit `PInfoBar` und einem
  `Notices.area("…")`; Zustandswechsel mit `PStateStack`/`PCrossfadeText`.
- Laufende Animationen nur, solange sie sichtbar sind (`running: visible && …`).
- Bindungen ohne Schleifen; keine Property-Namen, die mit `on` + Großbuchstabe beginnen (QML hält sie
  für Signal-Handler); Flickable-Properties (`contentX`, `contentWidth`) nicht überschreiben.
- **Größe von Template-Steuerelementen:** Elemente aus `QtQuick.Templates` (`T.Button`,
  `T.TextField`, `T.TextArea` …) berechnen ihre Größe nicht selbst – das tut sonst ein Stil. Jede
  `P…`-Komponente setzt `implicitWidth`/`implicitHeight`. Ein `T.TextArea` bekommt seine Höhe aus dem
  Inhalt (`contentHeight + topPadding + bottomPadding`) und füllt seine Fläche
  (`height: Math.max(implicitHeight, flickable.height)`): Sonst bleibt es eine Zeile hoch, Qt zeichnet
  nur, was im Feld liegt, und Klicks darunter gehen verloren (`PRichTextEditor`, `PTextArea`;
  geprüft in `test_qt_richtext.py` mit echten Klicks und dem gezeichneten Bild).
- **Einfügemarke in Textfeldern mit Formatierung:** `PTextCaret` als `cursorDelegate` statt der
  Qt-Marke (die ist 1 logisches Pixel breit – bei 125 … 175 % über mehrere Gerätepixel verwischt –
  und so hoch wie die ganze Zeile). Höhe aus den Font Metrics der Schrift am Cursor, Lage auf der
  Grundlinie, Breite/Höhe/Kanten in ganzen Gerätepixeln; sichtbar nur mit Textfokus
  (`cursorVisible`), Blinken nach `Qt.styleHints.cursorFlashTime`. Der Platzhalter verwendet
  dieselbe Schrift und Ausrichtung wie der Text, der beim Tippen entsteht (Test:
  `test_qt_caret.py`).
- Neue Komponenten in das `qmldir` ihres Moduls eintragen – sonst fehlen sie in der Ressource des
  Setups (Test: `test_qt_resources.py`).

## Bedienung und Barrierefreiheit

- Jede Aktion ist mit der Tastatur erreichbar (Tab-Reihenfolge, Eingabe/Leertaste, Tastenkürzel über
  `App`); sichtbarer Fokusrahmen `PFocusRing`.
- `Accessible.role`/`Accessible.name` für eigene Steuerelemente und Listenzeilen.
- Tooltips (`tip`) für Symbolschaltflächen.
- **Schaltflächen mit Zustand** (Werkzeug, Fett, Ausrichtung, „Seiten organisieren“ …): `toggle: true`,
  `checked` an den Zustand im Controller gebunden, `onClicked` ändert nur diesen Zustand. Nicht
  `checkable: true` – dann schaltet der Klick die Schaltfläche selbst um, löst die Bindung und zeigt
  danach einen Zustand, den es nicht gibt. Ein erneuter Klick auf ein gewähltes Werkzeug kehrt zu
  „Auswählen“ zurück.

## Prüfen

`tests/test_qt_*.py` lassen jeden Test scheitern, der eine Meldung der QML-Engine erzeugt
(Warnung, Bindungsschleife, fehlende Property). Für eine schnelle Syntaxprüfung eignet sich
`pyside6-qmllint` mit dem Importpfad `windows-app/app/qml`.
