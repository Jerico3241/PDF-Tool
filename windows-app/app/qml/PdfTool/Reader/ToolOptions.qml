import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Leiste oben über der Seite (wie die Hinweise): Einstellungen und Befehle des gewählten
// Werkzeugs (Farbe, Strichstärke, Schriftgröße; Bild einfügen, drehen, ersetzen, Reihenfolge, löschen) und
// ein kurzer Hinweis, was ein Klick in die Seite tut. Sie schiebt die Seiten nicht nach unten, blendet weich
// ein und aus (»Aus«: sofort) und ist nur da, wenn es etwas zu sagen gibt; Hinweise darunter rücken nach.
// Eine Textauswahl blendet hier nichts ein: Kopieren, Markieren, Unterstreichen und Durchstreichen
// stehen im Kontextmenü der Seite (Rechtsklick), Strg+C kopiert.
Item {
    id: root
    objectName: "readerToolOptions"
    property var doc: null
    property bool suppressed: false  // Vollbild: keine Werkzeugleiste
    readonly property string tool: doc ? doc.tool : "select"
    readonly property var selected: doc ? doc.selectedObject : ({})
    readonly property bool imageSelected: tool === "image" && selected.kind === "image"
    readonly property bool annotationSelected: tool === "select" && selected.kind === "annotation"
    // Der gewählte Kommentar mit allen Eigenschaften (Linienstärke, Füllung, Deckkraft, Schriftgröße)
    readonly property var annotation: {
        if (!annotationSelected || !doc) return null
        var items = doc.annotationPages[String(selected.page)] || []
        for (var i = 0; i < items.length; ++i)
            if (items[i].key === selected.key) return items[i]
        return null
    }
    readonly property bool ownAnnotation: annotation !== null && annotation.ours === true
    // Formular gestalten: gewähltes Feld und Art des nächsten Feldes
    readonly property bool designTool: tool === "formDesign"
    readonly property var chosenField: designTool && doc ? doc.fieldSelection : ({})
    readonly property bool fieldChosen: chosenField.key !== undefined
    readonly property string formKind: designTool && doc ? doc.formKind : ""
    function kindName(kind) {
        switch (kind) {
        case "text": return "Textfeld"
        case "checkbox": return "Kontrollkästchen"
        case "radio": return "Optionsfeld"
        case "combo": return "Dropdown"
        case "list": return "Liste"
        default: return "Feld"
        }
    }
    readonly property bool coloredTool: ["addText", "highlight", "underline", "strikeout", "note", "ink", "rect", "ellipse", "line", "arrow", "textbox"].indexOf(tool) >= 0
    readonly property bool strokeTool: ["ink", "rect", "ellipse", "line", "arrow"].indexOf(tool) >= 0
    readonly property bool sizeTool: tool === "addText" || tool === "textbox"
    readonly property string toolColor: doc ? (tool === "highlight" ? doc.markColor : doc.toolColor) : "#000000"
    readonly property bool shown: doc !== null && (tool !== "select" || annotationSelected)

    readonly property string hint: {
        switch (tool) {
        case "editText": return "Einen Textblock anklicken, um ihn zu ändern. Blau gestrichelt: direkt im PDF änderbar · orange: wird neu gesetzt oder überlagert."
        case "objects": return "Text, Bild oder Grafik anklicken, erneut klicken wählt ein Wort. Doppelklick ändert den Text, Ziehen verschiebt; Strg- oder Umschalt+Klick oder ein Rahmen wählt mehrere. Strg+C/V kopiert und fügt ein."
        case "hand": return "Mit gedrückter Maustaste ziehen, um das Dokument zu bewegen. Erneuter Klick auf »Verschieben« kehrt zu »Auswählen« zurück."
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
        case "formDesign":
            if (root.formKind !== "") return root.kindName(root.formKind) + ": Rahmen aufziehen oder klicken."
            if (root.fieldChosen) return "Ziehen verschiebt, die Ecken ändern die Größe; Doppelklick: Eigenschaften. Pfeiltasten, Entf, Strg+D."
            return "Feldart wählen und auf der Seite aufziehen – oder ein Feld anklicken. Rechtsklick legt ein Feld genau dort an."
        case "select": return root.annotationSelected ? (root.ownAnnotation ? "Ziehen verschiebt; die Ecken ändern die Größe." : "Kommentar aus einem anderen Programm – Text und Farbe lassen sich ändern, Ziehen verschiebt.") : ""
        default: return ""
        }
    }

    readonly property bool present: shown && !suppressed
    readonly property bool animating: heightAnim.running || fadeAnim.running
    readonly property int gap: 8  // Abstand zum oberen Rand bzw. zum Hinweis darunter

    implicitHeight: present ? card.height + gap : 0
    implicitWidth: card.implicitWidth
    visible: present || animating
    opacity: present ? 1 : 0
    Behavior on implicitHeight { enabled: Motion.infoBar > 0; NumberAnimation { id: heightAnim; duration: Motion.infoBar; easing.type: Motion.decelerate } }
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate } }

    Rectangle {
        id: card
        objectName: "readerToolOptionsCard"
        y: root.gap + (root.present ? 0 : -Motion.infoBarShift)
        anchors.horizontalCenter: parent.horizontalCenter
        implicitWidth: row.implicitWidth + 18
        width: Math.min(root.width, implicitWidth)
        height: Metrics.controlHeight + 12
        radius: Metrics.radiusOverlay
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        Behavior on y { enabled: Motion.moves; NumberAnimation { duration: Motion.infoBar; easing.type: Motion.decelerate } }
        PShadow { radius: Metrics.radiusOverlay }
        // Klicks und Hover auf der Leiste gehen nicht an die Seite darunter
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; preventStealing: true }

        RowLayout {
            id: row
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 6
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
            // Kommentar ausgewählt: Eigenschaften (nur bei Kommentaren aus PDF Tool – ihr Bild wird neu erzeugt)
            PComboBox {
                objectName: "readerAnnotationWidth"
                visible: root.ownAnnotation && root.annotation.width >= 0
                preferredWidth: 96
                label: "Linienstärke"
                model: [{ "label": "1 pt", "value": 1 }, { "label": "2 pt", "value": 2 }, { "label": "3 pt", "value": 3 }, { "label": "5 pt", "value": 5 }, { "label": "8 pt", "value": 8 }]
                textRole: "label"
                valueRole: "value"
                displayText: root.annotation && root.annotation.width >= 0 ? (Math.round(root.annotation.width * 10) / 10) + " pt" : currentText
                currentIndex: root.annotation ? Math.max(0, indexOfValue(Math.round(root.annotation.width))) : 1
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "width", model[index].value)
            }
            PIconButton {
                id: fillButton
                objectName: "readerAnnotationFill"
                visible: root.ownAnnotation && ["/Square", "/Circle", "/FreeText"].indexOf(root.annotation.subtype) >= 0
                iconName: "square"
                tip: root.annotation && root.annotation.fill !== "" ? "Füllung ändern" : "Füllen"
                onClicked: fills.open()
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    width: 16
                    height: 3
                    color: root.annotation && root.annotation.fill !== "" ? root.annotation.fill : "transparent"
                    border.width: root.annotation && root.annotation.fill !== "" ? 0 : 1
                    border.color: Theme.border
                }
                ColorChooser {
                    id: fills
                    y: fillButton.height + 4
                    current: root.annotation ? root.annotation.fill : ""
                    onPicked: (value) => root.doc.styleAnnotation(root.selected.key, "fill", value)
                }
            }
            PIconButton {
                objectName: "readerAnnotationNoFill"
                visible: root.ownAnnotation && root.annotation.fill !== ""
                iconName: "dismiss_circle"
                tip: "Ohne Füllung"
                onClicked: root.doc.styleAnnotation(root.selected.key, "fill", "")
            }
            PComboBox {
                objectName: "readerAnnotationOpacity"
                visible: root.ownAnnotation
                preferredWidth: 96
                label: "Deckkraft"
                model: [{ "label": "100 %", "value": 1 }, { "label": "75 %", "value": 0.75 }, { "label": "50 %", "value": 0.5 }, { "label": "25 %", "value": 0.25 }]
                textRole: "label"
                valueRole: "value"
                displayText: root.annotation ? Math.round(root.annotation.opacity * 100) + " %" : currentText
                currentIndex: root.annotation ? Math.max(0, indexOfValue(root.annotation.opacity)) : 0
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "opacity", model[index].value)
            }
            PComboBox {
                objectName: "readerAnnotationFontSize"
                visible: root.ownAnnotation && root.annotation.fontSize > 0
                preferredWidth: 96
                label: "Schriftgröße"
                model: [{ "label": "8 pt", "value": 8 }, { "label": "10 pt", "value": 10 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }, { "label": "18 pt", "value": 18 }, { "label": "24 pt", "value": 24 }, { "label": "36 pt", "value": 36 }]
                textRole: "label"
                valueRole: "value"
                displayText: root.annotation && root.annotation.fontSize > 0 ? (Math.round(root.annotation.fontSize * 10) / 10) + " pt" : currentText
                currentIndex: root.annotation ? Math.max(0, indexOfValue(Math.round(root.annotation.fontSize))) : 2
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "fontSize", model[index].value)
            }
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

            // Formular gestalten: Feldart wählen (dann Rahmen aufziehen) bzw. »Auswählen«; Befehle des gewählten Feldes
            Repeater {
                model: root.designTool ? [
                    { "kind": "", "icon": "cursor", "tip": "Felder auswählen, verschieben und in der Größe ändern" },
                    { "kind": "text", "icon": "textbox", "tip": "Textfeld anlegen" },
                    { "kind": "checkbox", "icon": "checkbox_checked", "tip": "Kontrollkästchen anlegen" },
                    { "kind": "radio", "icon": "radio_button", "tip": "Optionsfeld anlegen (eine Gruppe; weitere Optionen über »Option hinzufügen«)" },
                    { "kind": "combo", "icon": "chevron_down", "tip": "Dropdown (Auswahlliste) anlegen" },
                    { "kind": "list", "icon": "list", "tip": "Liste anlegen" }
                ] : []
                PIconButton {
                    required property var modelData
                    objectName: "readerFormKind_" + (modelData.kind !== "" ? modelData.kind : "select")
                    iconName: modelData.icon
                    tip: modelData.tip
                    toggle: true
                    checked: root.formKind === modelData.kind
                    // erneuter Klick auf die gewählte Feldart: zurück zum Auswählen der Felder
                    onClicked: root.doc.setFormKind(root.formKind === modelData.kind ? "" : modelData.kind)
                }
            }
            Rectangle { visible: root.designTool && root.fieldChosen; Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.divider }
            PIconButton { objectName: "readerFieldProperties"; visible: root.designTool && root.fieldChosen; iconName: "text_box_settings"; tip: "Eigenschaften … (Doppelklick, Eingabetaste)"; onClicked: root.doc.editFieldProperties("") }
            PIconButton { objectName: "readerFieldAddOption"; visible: root.designTool && root.chosenField.kind === "radio"; iconName: "add"; tip: "Option hinzufügen"; onClicked: root.doc.addFieldOption("") }
            PIconButton { objectName: "readerFieldDuplicate"; visible: root.designTool && root.fieldChosen && root.chosenField.kind !== "signature" && root.chosenField.kind !== "button"; iconName: "document_copy"; tip: "Duplizieren (Strg+D)"; onClicked: root.doc.duplicateField("") }
            PIconButton { objectName: "readerFieldDelete"; visible: root.designTool && root.fieldChosen; iconName: "delete"; tip: "Löschen (Entf)"; onClicked: root.doc.deleteField("") }

            PText {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                text: (root.tool === "editText" || root.tool === "objects") && root.doc && root.doc.lastMode !== "" ? root.hint + "   Zuletzt: " + root.doc.lastMode : root.hint
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
}
