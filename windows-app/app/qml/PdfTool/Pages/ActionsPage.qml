import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Stapel-Aktionen«: PDFs wählen oder hineinziehen → Aktionen ankreuzen (feste, richtige Reihenfolge) →
// Ausgabe → »Alle bearbeiten« mit Fortschritt je Datei. Jede PDF wird als neue Datei gespeichert; die
// Originale bleiben unverändert.
PPage {
    id: page
    objectName: "actionsPage"
    title: "Stapel-Aktionen"
    subtitle: "Dieselben Schritte auf viele PDFs anwenden – jede wird als neue Datei gespeichert."

    PInfoBar { Layout.fillWidth: true; notice: Notices.area("actions_info"); topMargin: 0 }

    // Dateien
    PDropZone {
        objectName: "actionsDropZone"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Actions.count === 0
        highlighted: Actions.dropHighlight
        iconName: "stack"
        title: "PDFs hierher ziehen"
        text: "oder auswählen – auch viele auf einmal."
        actions: [
            PButton { objectName: "actionsPick"; kind: "accent"; iconName: "folder_open"; text: "PDFs wählen"; tip: Shortcuts.labels["app.open"]; onClicked: Actions.pick() }
        ]
    }
    PCard {
        objectName: "actionsFiles"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Actions.count > 0
        title: Actions.count === 1 ? "1 PDF" : Actions.count + " PDFs"
        iconName: "document_multiple"
        headerRight: [
            PButton { objectName: "actionsAdd"; kind: "subtle"; iconName: "add"; text: "Hinzufügen"; enabled: !Actions.running; onClicked: Actions.pick() },
            PButton { objectName: "actionsClear"; kind: "subtle"; iconName: "delete"; text: "Alle entfernen"; enabled: !Actions.running; onClicked: Actions.removeAll() }
        ]
        Repeater {
            model: Actions.files
            RowLayout {
                required property var modelData
                required property int index
                objectName: "actionsFile_" + index
                Layout.fillWidth: true
                spacing: 8
                PIcon { name: "document_pdf"; size: 16; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { Layout.fillWidth: true; text: modelData.name; elide: Text.ElideMiddle }
                    PText {
                        Layout.fillWidth: true
                        text: modelData.message !== "" ? modelData.message : (modelData.outputName !== "" ? "→ " + modelData.outputName : modelData.sizeText + " · " + modelData.folder)
                        textStyle: "caption"
                        tone: modelData.state === "error" ? "critical" : "secondary"
                        elide: Text.ElideMiddle
                    }
                }
                PBadge { text: modelData.stateText; tone: modelData.tone; visible: modelData.state !== "waiting" }
                PIconButton { iconName: "open"; tip: "Ergebnis im Reader öffnen"; visible: modelData.hasOutput; onClicked: Actions.openOutput(modelData.key) }
                PIconButton { iconName: "folder_open"; tip: "Ordner öffnen"; onClicked: Actions.openFolder(modelData.key) }
                PIconButton { iconName: "dismiss"; tip: "Aus der Liste nehmen"; enabled: !Actions.running; onClicked: Actions.remove(modelData.key) }
            }
        }
    }

    // Aktionen
    PCard {
        objectName: "actionsSteps"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Aktionen"
        subtitle: Actions.summary !== "" ? Actions.summary : "Mindestens eine Aktion ankreuzen"
        iconName: "checkbox_checked"
        Repeater {
            model: Actions.steps
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 0
                PCheckBox {
                    objectName: "actionsStep_" + modelData.key
                    Layout.fillWidth: true
                    text: modelData.label
                    checked: modelData.checked
                    enabled: !Actions.running
                    onClicked: Actions.setStep(modelData.key, checked)
                }
                PText { Layout.fillWidth: true; Layout.leftMargin: 28; text: modelData.description; textStyle: "caption"; tone: "secondary"; wrap: true }
                // Einstellungen des Schritts, nur wenn er gewählt ist
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.watermark
                    PTextField { objectName: "actionsWatermarkText"; label: "Text des Wasserzeichens"; text: Actions.watermarkText; invalid: text.trim() === ""; onTextEdited: Actions.setWatermarkText(text) }
                }
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.numbers
                    PComboBox {
                        objectName: "actionsNumberFormat"
                        label: "Format der Seitenzahl"
                        model: Actions.numberFormats()
                        textRole: "label"
                        valueRole: "key"
                        Component.onCompleted: currentIndex = Math.max(0, indexOfValue(Actions.numberFormat))
                        onActivated: (index) => Actions.setNumberFormat(model[index].key)
                    }
                    PComboBox {
                        objectName: "actionsNumberPosition"
                        label: "Position der Seitenzahl"
                        preferredWidth: 170
                        model: [{ "key": "bc", "label": "Unten mittig" }, { "key": "br", "label": "Unten rechts" }, { "key": "bl", "label": "Unten links" }, { "key": "tc", "label": "Oben mittig" }, { "key": "tr", "label": "Oben rechts" }, { "key": "tl", "label": "Oben links" }]
                        textRole: "label"
                        valueRole: "key"
                        Component.onCompleted: currentIndex = Math.max(0, indexOfValue(Actions.numberPosition))
                        onActivated: (index) => Actions.setNumberPosition(model[index].key)
                    }
                }
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.optimize
                    PComboBox {
                        objectName: "actionsOptimizeLevel"
                        label: "Qualität"
                        preferredWidth: 260
                        model: [{ "key": "klein", "label": "Klein – E-Mail (110 dpi)" }, { "key": "mittel", "label": "Ausgewogen (150 dpi)" }, { "key": "hoch", "label": "Hoch – Druck (220 dpi)" }]
                        textRole: "label"
                        valueRole: "key"
                        Component.onCompleted: currentIndex = Math.max(0, indexOfValue(Actions.optimizeLevel))
                        onActivated: (index) => Actions.setOptimizeLevel(model[index].key)
                    }
                }
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.protect
                    PTextField {
                        objectName: "actionsPassword"
                        label: "Kennwort zum Öffnen"
                        placeholderText: "Kennwort (mind. 4 Zeichen)"
                        echoMode: TextInput.Password
                        onTextEdited: Actions.setPassword(text)
                    }
                    PText { text: "Wird nicht gespeichert."; textStyle: "caption"; tone: "secondary" }
                }
            }
        }
    }

    // Ausgabe
    PCard {
        objectName: "actionsOutput"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Ausgabe"
        iconName: "folder"
        Flow {
            Layout.fillWidth: true
            spacing: 16
            PRadioButton { objectName: "actionsOutOriginal"; text: "Neben den Originalen"; checked: Actions.outMode === Actions.texts.outOriginal; enabled: !Actions.running; onClicked: Actions.setOutMode(Actions.texts.outOriginal) }
            PRadioButton { objectName: "actionsOutFolder"; text: "Gemeinsamer Ordner"; checked: Actions.outMode === Actions.texts.outFolder; enabled: !Actions.running; onClicked: Actions.setOutMode(Actions.texts.outFolder) }
        }
        PFileRow {
            Layout.fillWidth: true
            visible: Actions.outMode === Actions.texts.outFolder
            iconName: "folder"
            label: "Ausgabeordner"
            value: Actions.outPath !== "" ? Actions.outPath : "Noch kein Ordner gewählt"
            fullPath: Actions.outPath
            PButton { iconName: "folder_open"; text: "Durchsuchen"; enabled: !Actions.running; onClicked: Actions.pickOutDir() }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PText { text: "Zusatz am Dateinamen"; tone: "secondary" }
            PTextField { objectName: "actionsSuffix"; preferredWidth: 160; label: "Zusatz am Dateinamen"; text: Actions.suffix; enabled: !Actions.running; onTextEdited: Actions.setSuffix(text) }
            PText { Layout.fillWidth: true; text: "Brief.pdf → Brief" + Actions.suffix + ".pdf"; textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
        }
    }

    // Start, Fortschritt, Ergebnis
    PText { objectName: "actionsProblem"; Layout.fillWidth: true; Layout.topMargin: 12; visible: text !== "" && Actions.count > 0; text: Actions.problem; tone: "critical"; wrap: true }
    Flow {
        Layout.fillWidth: true
        Layout.topMargin: 12
        spacing: 8
        PButton {
            objectName: "actionsStart"
            kind: "accent"
            large: true
            minimumWidth: 180
            iconName: "play"
            text: Actions.count > 1 ? "Alle bearbeiten" : "Bearbeiten"
            tip: Shortcuts.labels["app.primary"]
            enabled: Actions.canStart
            onClicked: Actions.start()
        }
        PButton { objectName: "actionsCancel"; large: true; iconName: "dismiss"; text: "Abbrechen"; tip: "Nach der laufenden Datei anhalten – fertige Dateien bleiben"; enabled: Actions.running; onClicked: Actions.cancel() }
        PButton { objectName: "actionsOpenFolder"; large: true; iconName: "folder_open"; text: "Ordner öffnen"; visible: Actions.resultText !== "" && !Actions.running; onClicked: Actions.openOutputFolder() }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.topMargin: 8
        spacing: 4
        visible: Actions.running
        PProgressBar { objectName: "actionsProgress"; Layout.fillWidth: true; value: Actions.progressValue }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PText { text: Actions.progressText; textStyle: "bodyStrong" }
            PText { Layout.fillWidth: true; text: Actions.currentText; textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
        }
    }
    PText { objectName: "actionsResult"; Layout.fillWidth: true; Layout.topMargin: 8; visible: text !== "" && !Actions.running; text: Actions.resultText; tone: Actions.resultTone === "success" ? "success" : (Actions.resultTone === "critical" ? "critical" : "warning"); wrap: true }
    Item { implicitHeight: 24 }
}
