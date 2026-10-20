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
    title: I18n.tr("Stapel-Aktionen", I18n.revision)
    subtitle: I18n.tr("Dieselben Schritte auf viele PDFs anwenden – jede wird als neue Datei gespeichert.", I18n.revision)

    PInfoBar { Layout.fillWidth: true; notice: Notices.area("actions_info"); topMargin: 0 }

    // Dateien
    PDropZone {
        objectName: "actionsDropZone"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Actions.count === 0
        highlighted: Actions.dropHighlight
        iconName: "stack"
        title: I18n.tr("PDFs hierher ziehen", I18n.revision)
        text: I18n.tr("oder auswählen – auch viele auf einmal.", I18n.revision)
        actions: [
            PButton { objectName: "actionsPick"; kind: "accent"; iconName: "folder_open"; text: I18n.tr("PDFs wählen", I18n.revision); tip: I18n.tr(Shortcuts.labels["app.open"], I18n.revision); onClicked: Actions.pick() }
        ]
    }
    PCard {
        objectName: "actionsFiles"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Actions.count > 0
        title: I18n.tr(Actions.count === 1 ? "1 PDF" : Actions.count + " PDFs", I18n.revision)
        iconName: "document_multiple"
        headerRight: [
            PButton { objectName: "actionsAdd"; kind: "subtle"; iconName: "add"; text: I18n.tr("Hinzufügen", I18n.revision); enabled: !Actions.running; onClicked: Actions.pick() },
            PButton { objectName: "actionsClear"; kind: "subtle"; iconName: "delete"; text: I18n.tr("Alle entfernen", I18n.revision); enabled: !Actions.running; onClicked: Actions.removeAll() }
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
                    PText { Layout.fillWidth: true; text: I18n.tr(modelData.name, I18n.revision); elide: Text.ElideMiddle }
                    PText {
                        Layout.fillWidth: true
                        text: I18n.tr(modelData.message !== "" ? modelData.message : (modelData.outputName !== "" ? "→ " + modelData.outputName : modelData.sizeText + " · " + modelData.folder), I18n.revision)
                        textStyle: "caption"
                        tone: modelData.state === "error" ? "critical" : "secondary"
                        elide: Text.ElideMiddle
                    }
                }
                PBadge { text: I18n.tr(modelData.stateText, I18n.revision); tone: modelData.tone; visible: modelData.state !== "waiting" }
                PIconButton { iconName: "open"; tip: I18n.tr("Ergebnis im Reader öffnen", I18n.revision); visible: modelData.hasOutput; onClicked: Actions.openOutput(modelData.key) }
                PIconButton { iconName: "folder_open"; tip: I18n.tr("Ordner öffnen", I18n.revision); onClicked: Actions.openFolder(modelData.key) }
                PIconButton { iconName: "dismiss"; tip: I18n.tr("Aus der Liste nehmen", I18n.revision); enabled: !Actions.running; onClicked: Actions.remove(modelData.key) }
            }
        }
    }

    // Aktionen
    PCard {
        objectName: "actionsSteps"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Aktionen", I18n.revision)
        subtitle: I18n.tr(Actions.summary !== "" ? Actions.summary : "Mindestens eine Aktion ankreuzen", I18n.revision)
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
                    text: I18n.tr(modelData.label, I18n.revision)
                    checked: modelData.checked
                    enabled: !Actions.running
                    onClicked: Actions.setStep(modelData.key, checked)
                }
                PText { Layout.fillWidth: true; Layout.leftMargin: 28; text: I18n.tr(modelData.description, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true }
                // Einstellungen des Schritts, nur wenn er gewählt ist
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.watermark
                    PTextField { objectName: "actionsWatermarkText"; label: I18n.tr("Text des Wasserzeichens", I18n.revision); text: Actions.watermarkText; invalid: text.trim() === ""; onTextEdited: Actions.setWatermarkText(text) }
                }
                RowLayout {
                    Layout.leftMargin: 28
                    Layout.topMargin: 4
                    Layout.bottomMargin: 4
                    spacing: 8
                    visible: modelData.checked && modelData.key === Actions.texts.numbers
                    PComboBox {
                        objectName: "actionsNumberFormat"
                        label: I18n.tr("Format der Seitenzahl", I18n.revision)
                        model: Actions.numberFormats()
                        textRole: "label"
                        valueRole: "key"
                        Component.onCompleted: currentIndex = Math.max(0, indexOfValue(Actions.numberFormat))
                        onActivated: (index) => Actions.setNumberFormat(model[index].key)
                    }
                    PComboBox {
                        objectName: "actionsNumberPosition"
                        label: I18n.tr("Position der Seitenzahl", I18n.revision)
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
                        label: I18n.tr("Qualität", I18n.revision)
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
                        label: I18n.tr("Kennwort zum Öffnen", I18n.revision)
                        placeholderText: I18n.tr("Kennwort (mind. 4 Zeichen)", I18n.revision)
                        echoMode: TextInput.Password
                        onTextEdited: Actions.setPassword(text)
                    }
                    PText { text: I18n.tr("Wird nicht gespeichert.", I18n.revision); textStyle: "caption"; tone: "secondary" }
                }
            }
        }
    }

    // Ausgabe
    PCard {
        objectName: "actionsOutput"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Ausgabe", I18n.revision)
        iconName: "folder"
        Flow {
            Layout.fillWidth: true
            spacing: 16
            PRadioButton { objectName: "actionsOutOriginal"; text: I18n.tr("Neben den Originalen", I18n.revision); checked: Actions.outMode === Actions.texts.outOriginal; enabled: !Actions.running; onClicked: Actions.setOutMode(Actions.texts.outOriginal) }
            PRadioButton { objectName: "actionsOutFolder"; text: I18n.tr("Gemeinsamer Ordner", I18n.revision); checked: Actions.outMode === Actions.texts.outFolder; enabled: !Actions.running; onClicked: Actions.setOutMode(Actions.texts.outFolder) }
        }
        PFileRow {
            Layout.fillWidth: true
            visible: Actions.outMode === Actions.texts.outFolder
            iconName: "folder"
            label: I18n.tr("Ausgabeordner", I18n.revision)
            value: Actions.outPath !== "" ? Actions.outPath : "Noch kein Ordner gewählt"
            fullPath: Actions.outPath
            PButton { iconName: "folder_open"; text: I18n.tr("Durchsuchen", I18n.revision); enabled: !Actions.running; onClicked: Actions.pickOutDir() }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PText { text: I18n.tr("Zusatz am Dateinamen", I18n.revision); tone: "secondary" }
            PTextField { objectName: "actionsSuffix"; preferredWidth: 160; label: I18n.tr("Zusatz am Dateinamen", I18n.revision); text: Actions.suffix; enabled: !Actions.running; onTextEdited: Actions.setSuffix(text) }
            PText { Layout.fillWidth: true; text: I18n.tr("Brief.pdf → Brief" + Actions.suffix + ".pdf", I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
        }
    }

    // Start, Fortschritt, Ergebnis
    PText { objectName: "actionsProblem"; Layout.fillWidth: true; Layout.topMargin: 12; visible: text !== "" && Actions.count > 0; text: I18n.tr(Actions.problem, I18n.revision); tone: "critical"; wrap: true }
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
            text: I18n.tr(Actions.count > 1 ? "Alle bearbeiten" : "Bearbeiten", I18n.revision)
            tip: I18n.tr(Shortcuts.labels["app.primary"], I18n.revision)
            enabled: Actions.canStart
            onClicked: Actions.start()
        }
        PButton { objectName: "actionsCancel"; large: true; iconName: "dismiss"; text: I18n.tr("Abbrechen", I18n.revision); tip: I18n.tr("Nach der laufenden Datei anhalten – fertige Dateien bleiben", I18n.revision); enabled: Actions.running; onClicked: Actions.cancel() }
        PButton { objectName: "actionsOpenFolder"; large: true; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); visible: Actions.resultText !== "" && !Actions.running; onClicked: Actions.openOutputFolder() }
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
            PText { text: I18n.tr(Actions.progressText, I18n.revision); textStyle: "bodyStrong" }
            PText { Layout.fillWidth: true; text: I18n.tr(Actions.currentText, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
        }
    }
    PText { objectName: "actionsResult"; Layout.fillWidth: true; Layout.topMargin: 8; visible: text !== "" && !Actions.running; text: I18n.tr(Actions.resultText, I18n.revision); tone: Actions.resultTone === "success" ? "success" : (Actions.resultTone === "critical" ? "critical" : "warning"); wrap: true }
    Item { implicitHeight: 24 }
}
