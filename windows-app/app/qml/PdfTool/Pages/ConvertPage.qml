import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Umwandeln« (seit 5.0 Beta 7): Dateien jeder Art wählen oder hineinziehen → Aufgabe (Umwandeln, Zusammenfügen,
// Teilen, Drucken, Umbenennen) → Einstellungen und Ausgabe → Starten mit Fortschritt je Datei. Aufbau wie die
// Stapel-Aktionen; die Originale bleiben unverändert (außer beim Umbenennen, mit »Rückgängig«).
PPage {
    id: page
    objectName: "convertPage"
    title: I18n.tr("Umwandeln", I18n.revision)
    subtitle: I18n.tr("Viele Dateien auf einmal umwandeln, zusammenfügen, teilen, drucken oder umbenennen.", I18n.revision)

    PInfoBar { Layout.fillWidth: true; notice: Notices.area("convert_info"); topMargin: 0 }

    PSelectorBar {
        objectName: "convertModes"
        Layout.fillWidth: true
        Layout.maximumWidth: implicitWidth
        Layout.bottomMargin: 8
        current: Convert.mode
        items: Convert.modes()
        enabled: !Convert.running
        onSelected: (key) => Convert.setMode(key)
        Accessible.name: I18n.tr("Aufgabe", I18n.revision)
    }

    // Dateien
    PDropZone {
        objectName: "convertDropZone"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Convert.count === 0
        highlighted: Convert.dropHighlight
        iconName: "arrow_swap"
        title: I18n.tr("Dateien hierher ziehen", I18n.revision)
        text: I18n.tr("PDFs, Texte, Tabellen, Präsentationen und Bilder – auch gemischt und viele auf einmal.", I18n.revision)
        actions: [
            PButton { objectName: "convertPick"; kind: "accent"; iconName: "folder_open"; text: I18n.tr("Dateien wählen", I18n.revision); tip: I18n.tr(Shortcuts.labels["app.open"], I18n.revision); onClicked: Convert.pick() }
        ]
    }
    PCard {
        objectName: "convertFiles"
        Layout.fillWidth: true
        Layout.topMargin: 8
        visible: Convert.count > 0
        title: I18n.tr(Convert.count === 1 ? "1 Datei" : Convert.count + " Dateien", I18n.revision)
        subtitle: I18n.tr(Convert.mode === "merge" ? "In dieser Reihenfolge zusammenfügen – mit den Pfeilen ordnen" : "", I18n.revision)
        iconName: "document_multiple"
        headerRight: [
            PButton { objectName: "convertAdd"; kind: "subtle"; iconName: "add"; text: I18n.tr("Hinzufügen", I18n.revision); enabled: !Convert.running; onClicked: Convert.pick() },
            PButton { objectName: "convertClear"; kind: "subtle"; iconName: "delete"; text: I18n.tr("Alle entfernen", I18n.revision); enabled: !Convert.running; onClicked: Convert.removeAll() }
        ]
        Repeater {
            model: Convert.files
            RowLayout {
                required property var modelData
                required property int index
                objectName: "convertFile_" + index
                Layout.topMargin: index > 0 ? 6 : 0
                Layout.fillWidth: true
                spacing: 8
                Item {
                    implicitWidth: 16
                    implicitHeight: 16
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 4
                    Image { anchors.fill: parent; visible: modelData.symbol !== ""; source: FileKinds.image(modelData.symbol, 16); sourceSize: Qt.size(32, 32) }
                    PIcon { anchors.fill: parent; visible: modelData.symbol === ""; name: "image"; size: 16 }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { Layout.fillWidth: true; text: I18n.tr(modelData.name, I18n.revision); elide: Text.ElideMiddle }
                    PText {
                        Layout.fillWidth: true
                        text: I18n.tr(modelData.message !== "" ? modelData.message : modelData.kind + " · " + modelData.sizeText + " · " + modelData.folder, I18n.revision)
                        textStyle: "caption"
                        tone: modelData.state === "error" ? "critical" : "secondary"
                        elide: Text.ElideMiddle
                    }
                }
                PBadge { text: I18n.tr(modelData.stateText, I18n.revision); tone: modelData.tone; visible: modelData.state !== "waiting" }
                PIconButton { iconName: "chevron_up"; tip: I18n.tr("Nach oben", I18n.revision); visible: Convert.mode === "merge"; enabled: !modelData.first && !Convert.running; onClicked: Convert.move(modelData.key, -1) }
                PIconButton { iconName: "chevron_down"; tip: I18n.tr("Nach unten", I18n.revision); visible: Convert.mode === "merge"; enabled: !modelData.last && !Convert.running; onClicked: Convert.move(modelData.key, 1) }
                PIconButton { iconName: "open"; tip: I18n.tr("Ergebnis öffnen", I18n.revision); visible: modelData.hasOutput && Convert.mode !== "rename"; onClicked: Convert.openOutput(modelData.key) }
                PIconButton { iconName: "folder_open"; tip: I18n.tr("Ordner öffnen", I18n.revision); onClicked: Convert.openFolder(modelData.key) }
                PIconButton { iconName: "dismiss"; tip: I18n.tr("Aus der Liste nehmen", I18n.revision); enabled: !Convert.running; onClicked: Convert.remove(modelData.key) }
            }
        }
    }

    // Einstellungen der Aufgabe
    PCard {
        objectName: "convertTarget"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "convert"
        title: I18n.tr("Umwandeln in", I18n.revision)
        subtitle: I18n.tr("Dateien, die sich nicht in das Ziel umwandeln lassen, werden ausgelassen.", I18n.revision)
        iconName: "arrow_swap"
        PComboBox {
            objectName: "convertTargetBox"
            label: I18n.tr("Ziel", I18n.revision)
            preferredWidth: 300
            model: Convert.targets
            textRole: "label"
            valueRole: "key"
            enabled: !Convert.running
            currentIndex: {
                var list = Convert.targets
                for (var i = 0; i < list.length; ++i)
                    if (list[i].key === Convert.target) return i
                return -1
            }
            onActivated: (index) => Convert.setTarget(model[index].key)
        }
    }
    PCard {
        objectName: "convertMerge"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "merge"
        title: I18n.tr("Zu einer PDF zusammenfügen", I18n.revision)
        subtitle: I18n.tr("Office-Dateien und Bilder werden vorher in PDF umgewandelt. Je Datei entsteht ein Lesezeichen.", I18n.revision)
        iconName: "merge"
        RowLayout {
            spacing: 8
            PTextField { objectName: "convertMergeName"; label: I18n.tr("Name der neuen PDF", I18n.revision); preferredWidth: 280; text: Convert.mergeName; enabled: !Convert.running; onTextEdited: Convert.setMergeName(text) }
            PText { text: I18n.tr(".pdf", I18n.revision); tone: "secondary" }
        }
    }
    PCard {
        objectName: "convertSplit"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "split"
        title: I18n.tr("Teilen in PDFs", I18n.revision)
        subtitle: I18n.tr("Jede Datei wird für sich geteilt; Office-Dateien und Bilder vorher in PDF umgewandelt.", I18n.revision)
        iconName: "arrow_split"
        Flow {
            Layout.fillWidth: true
            spacing: 16
            PRadioButton { objectName: "convertSplitPages"; text: I18n.tr("Jede Seite einzeln", I18n.revision); checked: Convert.splitMode === Convert.texts.splitPages; enabled: !Convert.running; onClicked: Convert.setSplitMode(Convert.texts.splitPages) }
            PRadioButton { objectName: "convertSplitEvery"; text: I18n.tr("Alle n Seiten", I18n.revision); checked: Convert.splitMode === Convert.texts.splitEvery; enabled: !Convert.running; onClicked: Convert.setSplitMode(Convert.texts.splitEvery) }
            PRadioButton { objectName: "convertSplitRanges"; text: I18n.tr("Nach Bereichen", I18n.revision); checked: Convert.splitMode === Convert.texts.splitRanges; enabled: !Convert.running; onClicked: Convert.setSplitMode(Convert.texts.splitRanges) }
        }
        RowLayout {
            spacing: 8
            visible: Convert.splitMode !== Convert.texts.splitPages
            PTextField {
                objectName: "convertSplitValue"
                label: I18n.tr(Convert.splitMode === Convert.texts.splitEvery ? "Seiten je Datei" : "Bereiche", I18n.revision)
                preferredWidth: Convert.splitMode === Convert.texts.splitEvery ? 100 : 220
                text: Convert.splitValue
                enabled: !Convert.running
                onTextEdited: Convert.setSplitValue(text)
            }
            PText { text: I18n.tr(Convert.splitMode === Convert.texts.splitEvery ? "z. B. 2 – je zwei Seiten eine Datei" : "z. B. 1-3, 4-6 – je Bereich eine Datei", I18n.revision); textStyle: "caption"; tone: "secondary" }
        }
    }
    PCard {
        objectName: "convertPrint"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "print"
        title: I18n.tr("Alle Dateien drucken", I18n.revision)
        subtitle: I18n.tr("Drucker und Kopien wählen Sie einmal für alle Dateien. Jede Datei ist ein eigener Druckauftrag.", I18n.revision)
        iconName: "print"
    }
    PCard {
        objectName: "convertRename"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "rename"
        title: I18n.tr("Neue Namen", I18n.revision)
        subtitle: I18n.tr("{name} bisheriger Name · {nr} Nummer · {datum} Änderungsdatum · {ordner} Ordnername. Die Endung bleibt.", I18n.revision)
        iconName: "edit"
        RowLayout {
            spacing: 8
            PTextField { objectName: "convertPattern"; label: I18n.tr("Muster", I18n.revision); preferredWidth: 260; text: Convert.pattern; enabled: !Convert.running; onTextEdited: Convert.setPattern(text) }
            PTextField {
                objectName: "convertStartNumber"
                label: I18n.tr("Erste Nummer", I18n.revision)
                preferredWidth: 90
                text: String(Convert.startNumber)
                enabled: !Convert.running
                validator: IntValidator { bottom: 0; top: 999999 }
                onTextEdited: Convert.setStartNumber(parseInt(text) || 0)
            }
        }
    }

    // Ausgabe
    PCard {
        objectName: "convertOutput"
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Convert.mode === "convert" || Convert.mode === "merge" || Convert.mode === "split"
        title: I18n.tr("Ausgabe", I18n.revision)
        iconName: "folder"
        Flow {
            Layout.fillWidth: true
            spacing: 16
            PRadioButton { objectName: "convertOutOriginal"; text: I18n.tr(Convert.mode === "merge" ? "Neben der ersten Datei" : "Neben den Originalen", I18n.revision); checked: Convert.outMode === Convert.texts.outOriginal; enabled: !Convert.running; onClicked: Convert.setOutMode(Convert.texts.outOriginal) }
            PRadioButton { objectName: "convertOutFolder"; text: I18n.tr("Gemeinsamer Ordner", I18n.revision); checked: Convert.outMode === Convert.texts.outFolder; enabled: !Convert.running; onClicked: Convert.setOutMode(Convert.texts.outFolder) }
        }
        PFileRow {
            Layout.fillWidth: true
            visible: Convert.outMode === Convert.texts.outFolder
            iconName: "folder"
            label: I18n.tr("Ausgabeordner", I18n.revision)
            value: Convert.outPath !== "" ? Convert.outPath : "Noch kein Ordner gewählt"
            fullPath: Convert.outPath
            PButton { iconName: "folder_open"; text: I18n.tr("Durchsuchen", I18n.revision); enabled: !Convert.running; onClicked: Convert.pickOutDir() }
        }
        PText { Layout.fillWidth: true; text: I18n.tr("Gibt es eine Datei mit dem neuen Namen schon, erhält die neue Datei eine Nummer – überschrieben wird nie.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true }
    }

    // Start, Fortschritt, Ergebnis
    PText { objectName: "convertProblem"; Layout.fillWidth: true; Layout.topMargin: 12; visible: text !== "" && Convert.count > 0; text: I18n.tr(Convert.problem, I18n.revision); tone: "critical"; wrap: true }
    Flow {
        Layout.fillWidth: true
        Layout.topMargin: 12
        spacing: 8
        PButton {
            objectName: "convertStart"
            kind: "accent"
            large: true
            minimumWidth: 180
            iconName: Convert.mode === "print" ? "print" : (Convert.mode === "rename" ? "edit" : "play")
            text: I18n.tr(Convert.startText, I18n.revision)
            tip: I18n.tr(Shortcuts.labels["app.primary"], I18n.revision)
            enabled: Convert.canStart
            onClicked: Convert.start()
        }
        PButton { objectName: "convertCancel"; large: true; iconName: "dismiss"; text: I18n.tr("Abbrechen", I18n.revision); tip: I18n.tr("Nach der laufenden Datei anhalten – fertige Dateien bleiben", I18n.revision); visible: Convert.mode !== "rename"; enabled: Convert.running; onClicked: Convert.cancel() }
        PButton { objectName: "convertUndo"; large: true; iconName: "arrow_undo"; text: I18n.tr("Rückgängig", I18n.revision); tip: I18n.tr("Alte Namen wiederherstellen", I18n.revision); visible: Convert.canUndo; onClicked: Convert.undoRename() }
        PButton { objectName: "convertOpenResult"; large: true; iconName: "open"; text: I18n.tr("PDF öffnen", I18n.revision); visible: Convert.resultPath !== "" && !Convert.running; onClicked: Convert.openResult() }
        PButton { objectName: "convertOpenFolder"; large: true; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); visible: Convert.resultText !== "" && !Convert.running && Convert.mode !== "print" && Convert.mode !== "rename"; onClicked: Convert.openOutputFolder() }
    }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.topMargin: 8
        spacing: 4
        visible: Convert.running
        PProgressBar { objectName: "convertProgress"; Layout.fillWidth: true; value: Convert.progressValue }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PText { text: I18n.tr(Convert.progressText, I18n.revision); textStyle: "bodyStrong" }
            PText { Layout.fillWidth: true; text: I18n.tr(Convert.currentText, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle }
        }
    }
    PText { objectName: "convertResult"; Layout.fillWidth: true; Layout.topMargin: 8; visible: text !== "" && !Convert.running; text: I18n.tr(Convert.resultText, I18n.revision); tone: Convert.resultTone === "success" ? "success" : (Convert.resultTone === "critical" ? "critical" : (Convert.resultTone === "neutral" ? "secondary" : "warning")); wrap: true }
    Item { implicitHeight: 24 }
}
