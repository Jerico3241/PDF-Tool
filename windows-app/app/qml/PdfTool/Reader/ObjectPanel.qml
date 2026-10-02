import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Eigenschaften der Auswahl im Modus »Objekt bearbeiten«: Text (Schrift, Größe, Farbe, Position,
// Drehung, Zeichenabstand), Bild (Größe, Position, Ersetzen, Drehen) oder mehrere Objekte (Ausrichten,
// gemeinsame Formatierung). Angeboten wird nur, was sich zuverlässig ändern lässt – Schrift und
// Drehung eines Textes sind nur zu sehen. Positionen in Millimetern ab der linken oberen Ecke der Seite.
// Kopf (Titel, Schließen) und Breite kommen von der rechten Seitenleiste (RightPanel).
ColumnLayout {
    id: root
    objectName: "readerObjectPanel"
    property var doc: null
    readonly property var chosen: doc ? doc.objectSelection : []
    readonly property var first: chosen.length ? chosen[0] : null
    readonly property bool texts: chosen.length > 0 && chosen.every(function(item) { return item.kind !== "image" })
    readonly property bool editable: texts && chosen.every(function(item) { return item.native })
    readonly property bool image: chosen.length === 1 && chosen[0].kind === "image"
    // Genau ein Objekt – aus ``first`` abgeleitet, damit Prüfung und Wert in jeder Bindung zusammenpassen
    readonly property var one: first !== null && chosen.length === 1 ? first : null
    readonly property bool oneImage: one !== null && one.kind === "image"
    readonly property real mm: 25.4 / 72
    // Art der Auswahl: wechselt sie (Text → Bild → mehrere), blendet der Inhalt kurz ein statt hart zu
    // wechseln; neue Werte derselben Art (anderes Wort, verschoben) erscheinen sofort
    readonly property string kind: chosen.length === 0 ? "" : (chosen.length > 1 ? "multi" : (image ? "image" : "text"))
    onKindChanged: if (kind !== "" && Motion.enabled) reveal.restart()
    spacing: 0

    ParallelAnimation {
        id: reveal
        NumberAnimation { target: details; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
        NumberAnimation { target: detailsShift; property: "y"; from: Motion.paneShift; to: 0; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    function number(text) {
        var value = parseFloat(String(text).replace(",", "."))
        return isNaN(value) ? null : value
    }
    function shown(value, digits) {
        return Number(value).toLocaleString(Qt.locale("de_DE"), "f", digits === undefined ? 1 : digits)
    }

    // Nichts gewählt
    PEmptyState {
        objectName: "readerObjectPanelEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.chosen.length === 0
        iconName: "select_object"
        title: root.doc && root.doc.tool === "objects" ? "Kein Objekt ausgewählt" : "Eigenschaften einzelner Objekte"
        text: root.doc && root.doc.tool === "objects"
            ? "Text oder Bild auf der Seite anklicken. Ein weiterer Klick wählt ein einzelnes Wort, Strg+Klick oder ein Rahmen mehrere Objekte."
            : "Im Werkzeug »Objekt bearbeiten« zeigt diese Leiste Schrift, Größe, Farbe und Position der Auswahl."
    }

    Flickable {
        id: details
        objectName: "readerObjectDetails"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.chosen.length > 0
        transform: Translate { id: detailsShift }
        contentHeight: body.implicitHeight + 24
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}

        ColumnLayout {
            id: body
            x: 16
            y: 12
            width: parent.width - 32
            spacing: 10

            PText {
                textStyle: "caption"
                tone: "secondary"
                text: root.chosen.length > 1 ? root.chosen.length + " Objekte ausgewählt" : (root.image ? "Bild" : (root.first && root.first.kind === "word" ? "Wort" : "Text"))
            }
            PText {
                Layout.fillWidth: true
                visible: root.chosen.length === 1 && !root.image
                text: root.first && !root.image ? "»" + root.first.text + "«" : ""
                elide: Text.ElideRight
                textStyle: "bodyStrong"
            }

            // Text: Schrift, Drehung (nur Anzeige), Größe, Zeichenabstand, Farbe; Text und Bild: Position
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 12
                rowSpacing: 8
                readonly property bool single: root.chosen.length === 1
                readonly property bool oneText: single && root.texts
                PText { visible: parent.oneText; text: "Schrift"; tone: "secondary" }
                PText { visible: parent.oneText; Layout.fillWidth: true; text: root.one && root.texts ? root.one.font : ""; elide: Text.ElideRight }
                PText { visible: parent.oneText; text: "Drehung"; tone: "secondary" }
                PText { visible: parent.oneText; text: root.one && root.texts ? root.shown(root.one.angle || 0, 0) + "°" : "" }
                PText { visible: root.texts; text: "Größe (pt)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectSize"
                    visible: root.texts
                    label: "Größe (pt)"
                    preferredWidth: 90
                    enabled: root.editable
                    text: root.first && root.texts ? root.shown(root.first.size) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && value >= 1 && value <= 400) root.doc.styleObjects("size", value) }
                }
                PText { visible: parent.oneText; text: "Zeichenabstand (pt)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectSpacing"
                    visible: parent.oneText
                    label: "Zeichenabstand (pt)"
                    preferredWidth: 90
                    enabled: root.editable
                    text: root.one && root.texts ? root.shown(root.one.spacing || 0, 2) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && value > -5 && value < 50) root.doc.styleObjects("spacing", value) }
                }
                PText { visible: root.texts; text: "Farbe"; tone: "secondary" }
                PSwatch {
                    id: colorButton
                    objectName: "readerObjectColor"
                    visible: root.texts
                    size: 28
                    swatchColor: root.first && root.texts ? root.first.color : "#000000"
                    tip: root.editable ? "Farbe ändern" : "Die Farbe dieses Textes lässt sich nicht direkt ändern"
                    enabled: root.editable
                    onClicked: colors.open()
                    ColorChooser {
                        id: colors
                        y: colorButton.height + 4
                        current: root.first && root.texts ? root.first.color : ""
                        onPicked: (value) => { root.doc.styleObjects("color", value); colors.close() }
                    }
                }
                PText { visible: parent.single; text: "Links (mm)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectX"
                    visible: parent.single
                    label: "Links (mm)"
                    preferredWidth: 90
                    enabled: root.oneImage ? root.one.editable === true : root.editable
                    text: root.one ? root.shown(root.one.view[0] * root.mm) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && root.one) root.doc.moveObjects(value / root.mm - root.one.view[0], 0) }
                }
                PText { visible: parent.single; text: "Oben (mm)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectY"
                    visible: parent.single
                    label: "Oben (mm)"
                    preferredWidth: 90
                    enabled: root.oneImage ? root.one.editable === true : root.editable
                    text: root.one ? root.shown(root.one.view[1] * root.mm) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && root.one) root.doc.moveObjects(0, value / root.mm - root.one.view[1]) }
                }
                PText { visible: root.image; text: "Größe"; tone: "secondary" }
                PText {
                    visible: root.image
                    Layout.fillWidth: true
                    wrap: true
                    text: root.oneImage ? root.shown((root.one.view[2] - root.one.view[0]) * root.mm) + " × " + root.shown((root.one.view[3] - root.one.view[1]) * root.mm) + " mm" + (root.one.pixels && root.one.pixels[0] ? " · " + root.one.pixels[0] + " × " + root.one.pixels[1] + " Pixel" : "") : ""
                }
            }

            // --- Mehrere: Ausrichten -----------------------------------------------------------------------------
            PText { visible: root.chosen.length > 1 && root.texts; text: "Ausrichten"; tone: "secondary" }
            Flow {
                Layout.fillWidth: true
                visible: root.chosen.length > 1 && root.texts
                spacing: 6
                PButton { text: "Links"; enabled: root.editable; onClicked: root.doc.alignObjects("left") }
                PButton { text: "Rechts"; enabled: root.editable; onClicked: root.doc.alignObjects("right") }
                PButton { text: "Oben"; enabled: root.editable; onClicked: root.doc.alignObjects("top") }
                PButton { text: "Unten"; enabled: root.editable; onClicked: root.doc.alignObjects("bottom") }
            }

            // --- Aktionen ----------------------------------------------------------------------------------------
            Flow {
                Layout.fillWidth: true
                spacing: 6
                PButton { visible: root.texts && root.chosen.length === 1; text: "Duplizieren"; iconName: "document_copy"; onClicked: root.doc.duplicateObject() }
                PButton { visible: root.texts; text: "Kopieren"; iconName: "copy"; onClicked: root.doc.copyObjects() }
                PButton { visible: root.image; text: "Ersetzen …"; iconName: "image"; enabled: root.oneImage && root.one.editable === true; onClicked: root.doc.replaceImage(root.one.page, root.one.index) }
                PButton { visible: root.image; text: "Drehen"; iconName: "arrow_rotate_clockwise"; enabled: root.oneImage && root.one.editable === true; onClicked: root.doc.rotateImage(root.one.page, root.one.index, true) }
                PButton { objectName: "readerObjectDelete"; text: "Löschen"; iconName: "delete"; kind: "danger"; onClicked: root.doc.deleteObjects() }
            }

            // Wie geändert wird – ehrlich benannt
            PText {
                Layout.fillWidth: true
                wrap: true
                textStyle: "caption"
                tone: root.texts && !root.editable ? "warning" : "secondary"
                text: !root.texts ? "" : (root.editable
                    ? "Änderungen betreffen nur die Auswahl und erfolgen direkt im PDF. Fehlen der Originalschrift Zeichen, wird der Text neu gesetzt."
                    : "Nicht direkt änderbar: " + (root.chosen.find(function(item) { return !item.native }) || {}).reason + " Text ändern und Löschen sind nur als Überlagerung möglich (der Originaltext bleibt in der Datei).")
            }
        }
    }
}
