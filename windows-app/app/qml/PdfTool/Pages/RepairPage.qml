import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF reparieren«: PDF wählen oder hineinziehen → Analyse mit Diagnose → Reparatur mit
// Fortschritt und »Abbrechen« → Ergebnis. Analyse und Ergebnis klappen weich auf und rücken
// danach in den sichtbaren Bereich. Die Originaldatei wird nie verändert.
PPage {
    id: page
    objectName: "repairPage"
    title: "PDF reparieren"
    subtitle: "Beschädigte PDF-Dateien analysieren und lesbare Inhalte in eine neue PDF übertragen."

    property bool detailsOpen: false
    property bool resultDetailsOpen: false
    // Fortschritt erst nach kurzer Zeit zeigen: schnelle Analysen blitzen nicht auf
    property bool progressShown: false

    Connections {
        target: Repair
        function onFocusRequested(field) {
            if (field === "password")
                passwordField.forceActiveFocus(Qt.OtherFocusReason)
            else if (field === "pick")
                pickButton.forceActiveFocus(Qt.OtherFocusReason)
        }
        function onRevealRequested(what) {
            revealTimer.item = what === "result" ? resultCard : analysisCard
            revealTimer.restart()
        }
        function onPasswordCleared() { passwordField.clear() }
        function onAnalyzedChanged() {
            if (Repair.analyzed && Motion.enabled)
                factsFlash.restart()
        }
        function onBusyChanged() {
            if (Repair.busy) {
                progressDelay.restart()
            } else {
                progressDelay.stop()
                page.progressShown = false
            }
        }
    }
    Timer {
        id: revealTimer
        property Item item: null
        interval: Motion.expand + 40  // nach dem Aufklappen
        onTriggered: page.reveal(item)
    }
    Timer {
        id: progressDelay
        interval: 150
        onTriggered: page.progressShown = Repair.busy
    }

    // Datenschutz
    RowLayout {
        Layout.fillWidth: true
        Layout.bottomMargin: 12
        spacing: 8
        PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
        PText { text: Repair.texts.privacy; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
    }

    // PDF auswählen ----------------------------------------------------------------------------
    PDropZone {
        id: dropZone
        objectName: "repairDrop"
        Layout.fillWidth: true
        highlighted: Repair.dropHighlight
        iconName: "document_pdf"
        title: "PDF hierher ziehen"
        text: "oder eine Datei auswählen – eine PDF pro Vorgang. Die Originaldatei wird nie verändert."
        actions: [
            PButton {
                id: pickButton
                objectName: "repairPick"
                kind: Repair.hasFile ? "standard" : "accent"
                iconName: "open"
                text: "PDF auswählen"
                tip: "PDF auswählen (Strg+O)"
                enabled: !Repair.busy
                onClicked: Repair.pick()
            }
        ]
    }
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_drop_info") }

    // Analyse ------------------------------------------------------------------------------------
    PCollapse {
        Layout.fillWidth: true
        expanded: Repair.hasFile
        ColumnLayout {
            width: parent.width
            spacing: 0
            Item { implicitHeight: 12 }
            PCard {
                id: analysisCard
                objectName: "repairAnalysis"
                Layout.fillWidth: true
                title: "Analyse"
                iconName: "document_search"
                headerRight: [
                    PIconButton { iconName: "open"; tip: "Andere PDF wählen (Strg+O)"; enabled: !Repair.busy; onClicked: Repair.pick() }
                ]

                PFileRow {
                    Layout.fillWidth: true
                    iconName: "document_pdf"
                    label: "Datei"
                    value: Repair.fileName
                    fullPath: Repair.filePath
                    PIconButton { iconName: "copy"; tip: "Pfad der PDF kopieren"; onClicked: Repair.copyInputPath() }
                }
                PFactList {
                    id: factList
                    objectName: "repairFacts"
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    facts: Repair.facts
                    SequentialAnimation {
                        id: factsFlash
                        NumberAnimation { target: factList; property: "opacity"; to: 0.35; duration: 60 }
                        NumberAnimation { target: factList; property: "opacity"; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                    }
                }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_analysis"); closable: false; topMargin: 4 }

                // Passwort (nur bei verschlüsselten PDFs)
                PCollapse {
                    Layout.fillWidth: true
                    expanded: Repair.needsPassword
                    ColumnLayout {
                        width: parent.width
                        spacing: 0
                        PFieldLabel { text: "Passwort" }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            PTextField {
                                id: passwordField
                                objectName: "repairPassword"
                                preferredWidth: 260
                                label: "Passwort der PDF"
                                placeholderText: "Passwort der PDF"
                                echoMode: TextInput.Password
                                passwordCharacter: "•"
                                inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                                enabled: !Repair.busy
                                onSubmitted: Repair.unlock(text)
                            }
                            PButton {
                                iconName: "lock_closed"
                                text: "Entsperren"
                                tip: "PDF mit diesem Passwort öffnen"
                                enabled: !Repair.busy
                                onClicked: Repair.unlock(passwordField.text)
                            }
                        }
                        PText {
                            text: "Das Passwort wird nur für diesen Vorgang verwendet und nicht gespeichert."
                            textStyle: "caption"
                            tone: "secondary"
                            wrap: true
                            Layout.fillWidth: true
                            Layout.topMargin: 6
                        }
                    }
                }

                // Technische Details (aufklappbar)
                PButton {
                    kind: "subtle"
                    iconName: page.detailsOpen ? "chevron_up" : "info"
                    text: page.detailsOpen ? "Technische Details ausblenden" : "Technische Details anzeigen"
                    enabled: Repair.analyzed
                    Layout.topMargin: 2
                    onClicked: page.detailsOpen = !page.detailsOpen
                }
                PCollapse {
                    Layout.fillWidth: true
                    expanded: page.detailsOpen && Repair.analyzed
                    PFactList {
                        objectName: "repairDetails"
                        width: parent.width
                        labelWidth: 190
                        facts: Repair.details
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4; height: 1; color: Theme.divider }

                // Ausgabe
                PText { text: "Speichern"; textStyle: "bodyStrong" }
                Flow {
                    Layout.fillWidth: true
                    spacing: 16
                    PRadioButton {
                        text: "Neben der Original-PDF"
                        checked: Repair.outMode === Repair.texts.outOriginal
                        onClicked: Repair.setOutMode(Repair.texts.outOriginal)
                    }
                    PRadioButton {
                        text: "Anderer Ordner"
                        checked: Repair.outMode === Repair.texts.outFolder
                        onClicked: Repair.setOutMode(Repair.texts.outFolder)
                    }
                }
                PFileRow {
                    Layout.fillWidth: true
                    iconName: "folder"
                    label: "Ausgabeordner"
                    value: Repair.outLabel
                    valueTone: Repair.outMissing ? "warning" : ""
                    fullPath: Repair.outPath
                    PButton { iconName: "folder_open"; text: "Durchsuchen"; tip: "Ordner für reparierte PDFs wählen"; onClicked: Repair.pickOutDir() }
                }
                PText { objectName: "repairOutName"; text: Repair.outName; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }

                // Aktionen
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    spacing: 8
                    PButton {
                        objectName: "repairStart"
                        kind: "accent"
                        large: true
                        minimumWidth: 180
                        iconName: "wrench"
                        text: Repair.repairText
                        tip: "PDF reparieren (Strg+Enter)"
                        enabled: Repair.canRepair && !Repair.busy
                        onClicked: Repair.startRepair()
                    }
                    PButton {
                        objectName: "repairCancel"
                        large: true
                        iconName: "dismiss"
                        text: "Abbrechen"
                        tip: "Vorgang abbrechen – es bleibt keine unvollständige Datei zurück"
                        enabled: Repair.busy
                        onClicked: Repair.cancel()
                    }
                }
                PCollapse {
                    Layout.fillWidth: true
                    expanded: page.progressShown && Repair.busy
                    ColumnLayout {
                        width: parent.width
                        spacing: 8
                        Item { implicitHeight: 2 }
                        PStatusLine { Layout.fillWidth: true; kind: "busy"; text: Repair.progressText }
                        PProgressBar {
                            Layout.fillWidth: true
                            indeterminate: Repair.progressValue < 0
                            value: Math.max(0, Repair.progressValue)
                            visible: Repair.busy
                        }
                    }
                }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_info"); topMargin: 4 }
            }
        }
    }

    // Ergebnis -----------------------------------------------------------------------------------
    PCollapse {
        Layout.fillWidth: true
        expanded: Repair.hasResult
        ColumnLayout {
            width: parent.width
            spacing: 0
            Item { implicitHeight: 12 }
            PCard {
                id: resultCard
                objectName: "repairResult"
                Layout.fillWidth: true
                title: "Ergebnis"
                iconName: "document_checkmark"

                PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_result"); closable: false; topMargin: 0 }
                PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: Repair.resultFacts }
                Repeater {
                    model: Repair.resultWarnings
                    RowLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        spacing: 8
                        PIcon { name: "warning"; color: Theme.warning; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: modelData; wrap: true; Layout.fillWidth: true }
                    }
                }
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    spacing: 8
                    PButton { objectName: "repairOpen"; kind: "accent"; iconName: "window_new"; text: "Öffnen"; tip: "Reparierte PDF öffnen"; enabled: Repair.hasOutput; onClicked: Repair.openOutput() }
                    PButton { iconName: "folder_open"; text: "Ordner öffnen"; enabled: Repair.hasOutput; onClicked: Repair.openOutputFolder() }
                    PButton { iconName: "copy"; text: "Pfad kopieren"; enabled: Repair.hasOutput; onClicked: Repair.copyOutputPath() }
                    PButton { objectName: "repairAgain"; iconName: "add"; text: "Weitere PDF reparieren"; enabled: !Repair.busy; onClicked: Repair.reset() }
                }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_rescue"); closable: false; topMargin: 4 }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_result_info"); topMargin: 4 }
                PButton {
                    kind: "subtle"
                    iconName: page.resultDetailsOpen ? "chevron_up" : "list"
                    text: page.resultDetailsOpen ? "Details ausblenden" : "Details anzeigen"
                    onClicked: page.resultDetailsOpen = !page.resultDetailsOpen
                }
                PCollapse {
                    Layout.fillWidth: true
                    expanded: page.resultDetailsOpen
                    PFactList {
                        width: parent.width
                        labelWidth: 40
                        facts: Repair.resultActions
                    }
                }
            }
        }
    }
}
