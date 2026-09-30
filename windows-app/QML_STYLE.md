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
- Große Listen immer als `ListView` mit Modell und `reuseItems`, nie als `Repeater` über hunderte
  Einträge.
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
- Neue Komponenten in das `qmldir` ihres Moduls eintragen – sonst fehlen sie in der Ressource des
  Setups (Test: `test_qt_resources.py`).

## Bedienung und Barrierefreiheit

- Jede Aktion ist mit der Tastatur erreichbar (Tab-Reihenfolge, Eingabe/Leertaste, Tastenkürzel über
  `App`); sichtbarer Fokusrahmen `PFocusRing`.
- `Accessible.role`/`Accessible.name` für eigene Steuerelemente und Listenzeilen.
- Tooltips (`tip`) für Symbolschaltflächen.

## Prüfen

`tests/test_qt_*.py` lassen jeden Test scheitern, der eine Meldung der QML-Engine erzeugt
(Warnung, Bindungsschleife, fehlende Property). Für eine schnelle Syntaxprüfung eignet sich
`pyside6-qmllint` mit dem Importpfad `windows-app/app/qml`.
