import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Leiste oben über der Seite (wie die Hinweise): Einstellungen und Befehle des gewählten
// Werkzeugs (Farbe, Strichstärke, Schriftgröße; Bild einfügen, drehen, ersetzen, Reihenfolge, löschen) – ohne
// Bedienhinweise und ohne »Fertig« (seit 4.0; Esc oder ein Klick auf das Werkzeug beendet es). Sie schiebt die Seiten nicht nach unten, blendet weich
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
    readonly property bool coloredTool: ["addText", "highlight", "underline", "strikeout", "note", "ink", "rect", "ellipse", "line", "arrow", "textbox"].indexOf(tool) >= 0 || (tool === "stamp" && doc !== null && doc.stampPreset === "custom")
    readonly property bool stampSelected: annotationSelected && annotation !== null && annotation.subtype === "/Stamp"  // Stempel/Unterschrift: Farbe fest
    readonly property bool strokeTool: ["ink", "rect", "ellipse", "line", "arrow"].indexOf(tool) >= 0
    readonly property bool sizeTool: tool === "addText" || tool === "textbox"
    readonly property string toolColor: doc ? (tool === "highlight" ? doc.markColor : doc.toolColor) : "#000000"

    // Seit 4.0 keine Bedienhinweise mehr (das gewählte Werkzeug zeigt der Strich in den
    // Schnellwerkzeugen, die Erklärung steht im Tooltip). Übrig bleiben Hinweise mit Inhalt: warum ein Bild
    // nicht änderbar ist, ein PDF ohne Felder, der Weg der letzten Textänderung.
    readonly property string hint: {
        switch (tool) {
        case "editText": case "objects": return root.doc && root.doc.lastMode !== "" ? "Zuletzt: " + root.doc.lastMode : ""
        case "image": return root.imageSelected && !selected.editable ? (selected.reason || "Dieses Bild lässt sich nicht ändern.") : ""
        case "form": return root.doc && Object.keys(root.doc.fieldPages).length > 0 ? "" : "Dieses PDF enthält keine ausfüllbaren Felder."
        default: return ""
        }
    }
    // Werkzeuge, deren Leiste Befehle trägt, die man zum Arbeiten braucht (Schwärzen anwenden, Unterschrift
    // wählen, Bild einfügen, Feldart): Leiste immer. Reine Einstellungen (Farbe, Stärke, Größe, Stempelart)
    // erst nach erneutem Klick auf das Werkzeug (``settingsOpen``); ein gewählter Kommentar zeigt seine immer.
    property bool settingsOpen: false
    readonly property bool commandTool: ["redact", "signature", "image", "formDesign"].indexOf(tool) >= 0
    readonly property bool settingsTool: coloredTool || strokeTool || sizeTool || tool === "stamp"
    readonly property bool hasControls: commandTool || annotationSelected || (settingsTool && settingsOpen)
    readonly property bool shown: doc !== null && (hasControls || hint !== "")

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
        implicitWidth: row.implicitWidth + 12
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
            anchors.leftMargin: 6  // gleicher Rand links und rechts: Symbole stehen mittig in der Leiste
            anchors.rightMargin: 6
            spacing: 4

            // Farbe
            PIconButton {
                id: colorButton
                visible: root.coloredTool || (root.annotationSelected && !root.stampSelected)
                iconName: "color"
                tip: I18n.tr("Farbe", I18n.revision)
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
                label: I18n.tr("Strichstärke", I18n.revision)
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
                label: I18n.tr("Schriftgröße", I18n.revision)
                model: [{ "label": "8 pt", "value": 8 }, { "label": "10 pt", "value": 10 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }, { "label": "18 pt", "value": 18 }, { "label": "24 pt", "value": 24 }, { "label": "36 pt", "value": 36 }]
                textRole: "label"
                valueRole: "value"
                currentIndex: root.doc ? Math.max(0, indexOfValue(root.doc.fontSize)) : 2
                onActivated: (index) => root.doc.fontSize = model[index].value
            }
            // Kommentar ausgewählt: Eigenschaften (nur bei Kommentaren aus Novadesk – ihr Bild wird neu erzeugt)
            PComboBox {
                objectName: "readerAnnotationWidth"
                visible: root.ownAnnotation && root.annotation.width >= 0
                preferredWidth: 96
                label: I18n.tr("Linienstärke", I18n.revision)
                model: [{ "label": "1 pt", "value": 1 }, { "label": "2 pt", "value": 2 }, { "label": "3 pt", "value": 3 }, { "label": "5 pt", "value": 5 }, { "label": "8 pt", "value": 8 }]
                textRole: "label"
                valueRole: "value"
                displayText: I18n.tr(root.annotation && root.annotation.width >= 0 ? (Math.round(root.annotation.width * 10) / 10) + " pt" : currentText, I18n.revision)
                currentIndex: root.annotation ? Math.max(0, indexOfValue(Math.round(root.annotation.width))) : 1
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "width", model[index].value)
            }
            PIconButton {
                id: fillButton
                objectName: "readerAnnotationFill"
                visible: root.ownAnnotation && ["/Square", "/Circle", "/FreeText"].indexOf(root.annotation.subtype) >= 0
                iconName: "square"
                tip: I18n.tr(root.annotation && root.annotation.fill !== "" ? "Füllung ändern" : "Füllen", I18n.revision)
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
                tip: I18n.tr("Ohne Füllung", I18n.revision)
                onClicked: root.doc.styleAnnotation(root.selected.key, "fill", "")
            }
            PComboBox {
                objectName: "readerAnnotationOpacity"
                visible: root.ownAnnotation
                preferredWidth: 96
                label: I18n.tr("Deckkraft", I18n.revision)
                model: [{ "label": "100 %", "value": 1 }, { "label": "75 %", "value": 0.75 }, { "label": "50 %", "value": 0.5 }, { "label": "25 %", "value": 0.25 }]
                textRole: "label"
                valueRole: "value"
                displayText: I18n.tr(root.annotation ? Math.round(root.annotation.opacity * 100) + " %" : currentText, I18n.revision)
                currentIndex: root.annotation ? Math.max(0, indexOfValue(root.annotation.opacity)) : 0
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "opacity", model[index].value)
            }
            PComboBox {
                objectName: "readerAnnotationFontSize"
                visible: root.ownAnnotation && root.annotation.fontSize > 0
                preferredWidth: 96
                label: I18n.tr("Schriftgröße", I18n.revision)
                model: [{ "label": "8 pt", "value": 8 }, { "label": "10 pt", "value": 10 }, { "label": "12 pt", "value": 12 }, { "label": "14 pt", "value": 14 }, { "label": "18 pt", "value": 18 }, { "label": "24 pt", "value": 24 }, { "label": "36 pt", "value": 36 }]
                textRole: "label"
                valueRole: "value"
                displayText: I18n.tr(root.annotation && root.annotation.fontSize > 0 ? (Math.round(root.annotation.fontSize * 10) / 10) + " pt" : currentText, I18n.revision)
                currentIndex: root.annotation ? Math.max(0, indexOfValue(Math.round(root.annotation.fontSize))) : 2
                onActivated: (index) => root.doc.styleAnnotation(root.selected.key, "fontSize", model[index].value)
            }
            PButton { visible: root.annotationSelected; iconName: "delete"; text: I18n.tr(root.stampSelected ? (root.annotation.label === "Unterschrift" ? "Unterschrift löschen" : "Stempel löschen") : "Kommentar löschen", I18n.revision); onClicked: root.doc.deleteAnnotation(root.selected.key) }

            // Schwärzen: Bereich oder Text markieren, Suchen, Markierungen verwerfen, anwenden
            PIconButton { objectName: "readerRedactArea"; visible: root.tool === "redact"; toggle: true; checked: root.doc !== null && root.doc.redactMode === "area"; iconName: "square"; tip: I18n.tr("Bereiche aufziehen", I18n.revision); onClicked: root.doc.setRedactMode("area") }
            PIconButton { objectName: "readerRedactText"; visible: root.tool === "redact"; toggle: true; checked: root.doc !== null && root.doc.redactMode === "text"; iconName: "text_edit_style"; tip: I18n.tr("Text markieren", I18n.revision); onClicked: root.doc.setRedactMode("text") }
            PButton { objectName: "readerRedactSearch"; visible: root.tool === "redact"; kind: "subtle"; iconName: "document_search"; text: I18n.tr("Suchen …", I18n.revision); onClicked: root.doc.searchRedact() }
            PIconButton { objectName: "readerRedactClear"; visible: root.tool === "redact" && root.doc.redactCount > 0; iconName: "dismiss_circle"; tip: I18n.tr("Alle Markierungen verwerfen", I18n.revision); onClicked: root.doc.clearRedactMarks() }
            PButton {
                objectName: "readerRedactApply"
                visible: root.tool === "redact"
                kind: "danger"
                iconName: "eye_off"
                enabled: root.doc !== null && root.doc.redactCount > 0
                text: I18n.tr(root.doc && root.doc.redactCount > 0 ? "Schwärzen anwenden (" + root.doc.redactCount + ")" : "Schwärzen anwenden", I18n.revision)
                onClicked: root.doc.applyRedaction()
            }

            // Stempel: Vorgabe oder eigener Text, zweite Zeile
            PComboBox {
                objectName: "readerStampPreset"
                visible: root.tool === "stamp"
                preferredWidth: 170
                label: I18n.tr("Stempel", I18n.revision)
                model: root.doc ? root.doc.stampPresets.concat([{ "key": "custom", "label": root.doc.stampText !== "" ? root.doc.stampText + " (eigener)" : "Eigener Text …" }]) : []
                textRole: "label"
                valueRole: "key"
                currentIndex: root.doc ? Math.max(0, indexOfValue(root.doc.stampPreset)) : 0
                onActivated: (index) => root.doc.setStampPreset(model[index].key)
            }
            PComboBox {
                objectName: "readerStampSubtitle"
                visible: root.tool === "stamp"
                preferredWidth: 170
                label: I18n.tr("Zweite Zeile", I18n.revision)
                readonly property var options: [{ "key": "", "label": "Ohne zweite Zeile" }, { "key": "{datum}", "label": "Datum" }, { "key": "{datum} {zeit}", "label": "Datum und Uhrzeit" }]
                readonly property bool customLine: root.doc !== null && root.doc.stampSubtitle !== "" && root.doc.stampSubtitle !== "{datum}" && root.doc.stampSubtitle !== "{datum} {zeit}"
                model: options.concat([{ "key": "custom", "label": customLine ? root.doc.stampSubtitle : "Eigener Text …" }])
                textRole: "label"
                valueRole: "key"
                currentIndex: !root.doc ? 0 : (customLine ? 3 : Math.max(0, indexOfValue(root.doc.stampSubtitle)))
                onActivated: (index) => root.doc.setStampSubtitle(model[index].key)
            }

            // Unterschrift: gespeicherte (und die dieser Sitzung) zur Auswahl, neue anlegen, löschen
            Repeater {
                model: root.tool === "signature" && root.doc ? root.doc.signatures : []
                PButton {
                    id: signatureChoice
                    required property var modelData
                    objectName: "readerSignatureChoice"
                    kind: "subtle"
                    toggle: true
                    checked: root.doc.signatureChoice === modelData.id
                    implicitWidth: Math.min(150, Math.max(64, 30 * modelData.aspect)) + 12
                    tip: I18n.tr(modelData.label + (modelData.stored ? "" : " (nicht gespeichert)"), I18n.revision)
                    onClicked: root.doc.chooseSignature(modelData.id)
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        radius: 3
                        color: Theme.paper
                        border.width: signatureChoice.checked ? 2 : 1
                        border.color: signatureChoice.checked ? Theme.accent : Theme.border
                        Image { anchors.fill: parent; anchors.margins: 3; source: signatureChoice.modelData.preview; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true }
                    }
                }
            }
            PButton { objectName: "readerSignatureNew"; visible: root.tool === "signature"; kind: "subtle"; iconName: "add"; text: I18n.tr(root.doc && root.doc.signatures.length > 0 ? "Neu …" : "Unterschrift erstellen …", I18n.revision); onClicked: root.doc.newSignature() }
            PIconButton { objectName: "readerSignatureDelete"; visible: root.tool === "signature" && root.doc && root.doc.signatureChoice !== ""; iconName: "delete"; tip: I18n.tr("Gewählte Unterschrift löschen", I18n.revision); onClicked: root.doc.deleteSignature(root.doc.signatureChoice) }
            // Bilder
            PButton {
                objectName: "readerInsertImage"
                visible: root.tool === "image"
                iconName: "image_add"
                text: I18n.tr("Bild einfügen", I18n.revision)
                onClicked: root.doc.insertImage(root.doc.currentPage, [])
            }
            Rectangle { visible: root.imageSelected; Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.divider }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_rotate_counterclockwise"; tip: I18n.tr("Nach links drehen", I18n.revision); onClicked: root.doc.rotateImage(root.selected.page, root.selected.index, false) }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_rotate_clockwise"; tip: I18n.tr("Nach rechts drehen", I18n.revision); onClicked: root.doc.rotateImage(root.selected.page, root.selected.index, true) }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "arrow_swap"; tip: I18n.tr("Bild ersetzen", I18n.revision); onClicked: root.doc.replaceImage(root.selected.page, root.selected.index) }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "chevron_up"; tip: I18n.tr("In den Vordergrund", I18n.revision); onClicked: root.doc.arrangeImage(root.selected.page, root.selected.index, true) }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "chevron_down"; tip: I18n.tr("In den Hintergrund", I18n.revision); onClicked: root.doc.arrangeImage(root.selected.page, root.selected.index, false) }
            PIconButton { visible: root.imageSelected && root.selected.editable; iconName: "delete"; tip: I18n.tr("Bild löschen (Entf)", I18n.revision); onClicked: root.doc.deleteImage(root.selected.page, root.selected.index) }

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
                    tip: I18n.tr(modelData.tip, I18n.revision)
                    toggle: true
                    checked: root.formKind === modelData.kind
                    // erneuter Klick auf die gewählte Feldart: zurück zum Auswählen der Felder
                    onClicked: root.doc.setFormKind(root.formKind === modelData.kind ? "" : modelData.kind)
                }
            }
            Rectangle { visible: root.designTool && root.fieldChosen; Layout.preferredWidth: 1; Layout.preferredHeight: 20; color: Theme.divider }
            PIconButton { objectName: "readerFieldProperties"; visible: root.designTool && root.fieldChosen; iconName: "text_box_settings"; tip: I18n.tr("Eigenschaften … (Doppelklick, Eingabetaste)", I18n.revision); onClicked: root.doc.editFieldProperties("") }
            PIconButton { objectName: "readerFieldAddOption"; visible: root.designTool && root.chosenField.kind === "radio"; iconName: "add"; tip: I18n.tr("Option hinzufügen", I18n.revision); onClicked: root.doc.addFieldOption("") }
            PIconButton { objectName: "readerFieldDuplicate"; visible: root.designTool && root.fieldChosen && root.chosenField.kind !== "signature" && root.chosenField.kind !== "button"; iconName: "document_copy"; tip: I18n.tr("Duplizieren (Strg+D)", I18n.revision); onClicked: root.doc.duplicateField("") }
            PIconButton { objectName: "readerFieldDelete"; visible: root.designTool && root.fieldChosen; iconName: "delete"; tip: I18n.tr("Löschen (Entf)", I18n.revision); onClicked: root.doc.deleteField("") }

            PText {
                objectName: "readerToolHint"
                Layout.fillWidth: true
                Layout.leftMargin: root.hasControls ? 8 : 0
                Layout.rightMargin: root.hasControls ? 0 : 6
                visible: text !== ""
                text: I18n.tr(root.hint, I18n.revision)
                textStyle: "caption"
                tone: root.imageSelected && !root.selected.editable ? "warning" : "secondary"
                elide: Text.ElideRight
            }
        }
    }
}
