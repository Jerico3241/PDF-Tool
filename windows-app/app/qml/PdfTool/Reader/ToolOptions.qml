import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Leiste unter der Befehlsleiste: Einstellungen und Befehle des gewählten Werkzeugs (Farbe,
// Strichstärke, Schriftgröße; Bild einfügen, drehen, ersetzen, Reihenfolge, löschen) und ein
// kurzer Hinweis, was ein Klick in die Seite tut. Nur sichtbar, wenn es etwas zu sagen gibt.
Rectangle {
    id: root
    objectName: "readerToolOptions"
    property var doc: null
    readonly property string tool: doc ? doc.tool : "select"
    readonly property var selected: doc ? doc.selectedObject : ({})
    readonly property bool imageSelected: tool === "image" && selected.kind === "image"
    readonly property bool annotationSelected: tool === "select" && selected.kind === "annotation"
    readonly property bool textSelected: doc !== null && doc.selectionPage >= 0
    readonly property bool coloredTool: ["addText", "highlight", "underline", "strikeout", "note", "ink", "rect", "ellipse", "line", "arrow", "textbox"].indexOf(tool) >= 0
    readonly property bool strokeTool: ["ink", "rect", "ellipse", "line", "arrow"].indexOf(tool) >= 0
    readonly property bool sizeTool: tool === "addText" || tool === "textbox"
    readonly property string toolColor: doc ? (tool === "highlight" ? doc.markColor : doc.toolColor) : "#000000"
    readonly property bool shown: doc !== null && (tool !== "select" || annotationSelected || textSelected)

    readonly property string hint: {
        switch (tool) {
        case "editText": return "Einen Textblock anklicken, um ihn zu ändern. Blau gestrichelt: direkt im PDF änderbar · orange: wird neu gesetzt oder überlagert."
        case "addText": return "In die Seite klicken und schreiben."
        case "image": return root.imageSelected ? (selected.editable ? "Ziehen verschiebt, die Ecken ändern die Größe (Umschalt: frei)." : (selected.reason || "Dieses Bild lässt sich nicht ändern.")) : "Bild anklicken – oder einen Rahmen aufziehen und ein Bild einfügen."
        case "highlight": return "Text markieren: mit der Maus über den Text ziehen."
        case "underline": return "Text unterstreichen: mit der Maus über den Text ziehen."
        case "strikeout": return "Text durchstreichen: mit der Maus über den Text ziehen."
        case "note": return "In die Seite klicken, um eine Notiz anzuheften."
        case "textbox": return "Rahmen aufziehen (oder klicken) und Text schreiben."
        case "ink": return "Mit gedrückter Maustaste zeichnen – auch für eine sichtbare Unterschrift (keine digitale Signatur)."
        case "rect": case "ellipse": return "Rahmen aufziehen."
        case "line": case "arrow": return "Von Anfang zu Ende ziehen."
        case "form": return root.doc && Object.keys(root.doc.fieldPages).length > 0 ? "Felder anklicken und ausfüllen. Skripte im PDF werden nicht ausgeführt." : "Dieses PDF enthält keine ausfüllbaren Felder."
        default: return ""
        }
    }

    implicitHeight: shown ? Metrics.controlHeight + 12 : 0
    visible: implicitHeight > 0
    clip: true
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 4

        // Farbe
        PIconButton {
            id: colorButton
            visible: root.coloredTool || root.annotationSelected
            iconName: "color"
            tip: "Farbe"
            onClicked: colors.open()
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 4
                width: 16
                height: 3
                color: root.annotationSelected ? (root.doc.toolColor) : root.toolColor
            }
            ColorChooser {
                id: colors
                y: colorButton.height + 4
                current: root.toolColor
                onPicked: (value) => {
                    if (root.annotationSelected) root.doc.setAnnotationColor(root.selected.key, value)
                    else if (root.tool === "highlight") root.doc.markColor = value
                    else root.doc.toolColor = value
                }
            }
        }
        // Strichstärke
        PComboBox {
            visible: root.strokeTool
            preferredWidth: 96
            label: "Strichstärke"
            model: [{ "label": "1 pt", "value": 1 }, { "label": "2 pt", "value": 2 }, { "label": "3 pt", "value": 3 }, { "label": "5 pt", "value": 5 }, { "label": "8 pt", "value": 8 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: root.doc ? Math.max(0, indexOfValue(root.doc.strokeWidth)) : 1
            onActivated: (index) => root.doc.strokeWidth = model[index].value
        }
        // Schriftgröße (neuer Text, Textfeld)
        PComboBox {
            visible: root.sizeTool
            preferredWidth: 96
            label: "Schriftgröße"
            model: [{ "label": "8 pt", "value": 8 }, { "label": "10 pt", "value": 10 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }, { "label": "18 pt", "value": 18 }, { "label": "24 pt", "value": 24 }, { "label": "36 pt", "value": 36 }]
            textRole: "label"
            valueRole: "value"
            currentIndex: root.doc ? Math.max(0, indexOfValue(root.doc.fontSize)) : 2
            onActivated: (index) => root.doc.fontSize = model[index].value
        }
        // Text ausgewählt (Werkzeug »Auswählen«)
        PButton { visible: root.textSelected && root.tool === "select"; iconName: "copy"; text: "Kopieren"; onClicked: root.doc.copySelection() }
        PButton { visible: root.textSelected && root.tool === "select"; iconName: "highlight"; text: "Markieren"; onClicked: root.doc.markSelection("highlight") }
        PIconButton { visible: root.textSelected && root.tool === "select"; iconName: "text_underline"; tip: "Unterstreichen"; onClicked: root.doc.markSelection("underline") }
        PIconButton { visible: root.textSelected && root.tool === "select"; iconName: "text_strikethrough"; tip: "Durchstreichen"; onClicked: root.doc.markSelection("strikeout") }
        // Kommentar ausgewählt
        PButton { visible: root.annotationSelected; iconName: "delete"; text: "Kommentar löschen"; onClicked: root.doc.deleteAnnotation(root.selected.key) }
        // Bilder
        PButton {
            objectName: "readerInsertImage"
            visible: root.tool === "image"
            iconName: "image_add"
            text: "Bild einfügen"
            onClicked: root.doc.insertImage(root.doc.currentPage, [])
        }
        Rectangle { visible: root.imageSelected; Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.divider }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_rotate_counterclockwise"; tip: "Nach links drehen"; onClicked: root.doc.rotateImage(root.selected.page, root.selected.index, false) }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_rotate_clockwise"; tip: "Nach rechts drehen"; onClicked: root.doc.rotateImage(root.selected.page, root.selected.index, true) }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_swap"; tip: "Bild ersetzen"; onClicked: root.doc.replaceImage(root.selected.page, root.selected.index) }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "chevron_up"; tip: "In den Vordergrund"; onClicked: root.doc.arrangeImage(root.selected.page, root.selected.index, true) }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "chevron_down"; tip: "In den Hintergrund"; onClicked: root.doc.arrangeImage(root.selected.page, root.selected.index, false) }
        PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "delete"; tip: "Bild löschen (Entf)"; onClicked: root.doc.deleteImage(root.selected.page, root.selected.index) }

        PText {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            text: root.tool === "editText" && root.doc && root.doc.lastMode !== "" ? root.hint + "   Zuletzt: " + root.doc.lastMode : root.hint
            textStyle: "caption"
            tone: root.imageSelected && !root.selected.editable ? "warning" : "secondary"
            elide: Text.ElideRight
        }
        PButton {
            visible: root.tool !== "select"
            kind: "subtle"
            iconName: "dismiss"
            text: "Fertig"
            tip: "Zurück zu »Auswählen« (Esc)"
            onClicked: root.doc.setTool("select")
        }
    }
}
