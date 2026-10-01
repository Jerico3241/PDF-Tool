import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Eine PDF in »PDF reparieren«: Name und Zustand, Fortschritt (Analyse → Reparatur → Validierung →
// Fertig), Passwort (nur ihre Datei), geplanter Ausgabename (editierbar, ».pdf« wird ergänzt),
// Aktionen und aufklappbare Details.
// Einzelmodus (eine PDF): wie bis 2.7.0 – Diagnose als Hinweis mit Erklärung, Angaben der Analyse
// immer sichtbar; Öffnen, Ordner und Pfad stehen in der Karte »Ergebnis«.
// Mehrere PDFs: kompakt – Zustand als Etikett, eine Zeile Erklärung, alles Weitere in den Details.
Item {
    id: row
    required property int index
    required property string key
    required property string name
    required property string path
    required property string sizeText
    required property string state
    required property string stateText
    required property string tone
    required property string message
    required property bool busy
    required property string phaseText
    required property real progress
    required property string outputBase
    required property string outputName
    required property string outputFolder
    required property bool numbered
    required property bool nameManual
    required property string nameError
    required property bool needsPassword
    required property bool canRepair
    required property string repairText
    required property int signatures
    required property bool rescue
    required property bool hasOutput
    required property var facts
    required property var details
    required property var resultFacts
    required property var warnings
    required property bool inRun
    required property bool canAnalyze
    required property string diagSeverity
    required property string diagTitle
    required property string diagText
    required property string resultSeverity
    required property string resultTitle
    required property string resultText
    required property var resultActions

    property real columnX: 0
    property real columnWidth: width
    property bool detailsOpen: false
    signal toggleDetails()
    // Fortschritt erst nach kurzer Zeit zeigen: schnelle Analysen blitzen nicht auf
    property bool progressShown: false
    readonly property bool single: Repair.single
    readonly property string badgeTone: tone === "critical" ? "error" : (tone === "caution" ? "warning" : (tone === "success" ? "success" : "neutral"))

    objectName: "repairItem_" + key
    implicitHeight: card.implicitHeight + 8
    height: implicitHeight
    Accessible.role: Accessible.ListItem
    Accessible.name: name + ", " + stateText + (message !== "" ? ", " + message : "")

    onBusyChanged: {
        if (busy) {
            progressDelay.restart()
        } else {
            progressDelay.stop()
            progressShown = false
        }
    }
    // Analyse fertig: Angaben kurz aufleuchten lassen (wie bis 2.7.0). Kein Binding an »state«:
    // der vorige Zustand muss im Handler noch erhalten sein.
    property string _lastState: ""
    onStateChanged: {
        if (_lastState === "analyzing" && state !== "analyzing" && single && Motion.enabled)
            factsFlash.restart()
        _lastState = state
    }
    Component.onCompleted: {
        _lastState = state
        if (busy)
            progressDelay.restart()
    }
    ListView.onReused: {  // Zeile wird für eine andere Datei wiederverwendet
        // Die Übergänge »entfernen« und »hinzufügen« animieren Deckkraft und Größe – zurücksetzen
        opacity = 1
        scale = 1
        _lastState = state
        factsFlash.stop()
        factList.opacity = 1
        progressDelay.stop()
        progressShown = busy
    }
    Timer {
        id: progressDelay
        interval: 150
        onTriggered: row.progressShown = row.busy
    }

    Connections {
        target: Repair
        function onPasswordRequested(itemKey) { if (itemKey === row.key) passwordField.forceActiveFocus(Qt.OtherFocusReason) }
        function onPasswordCleared(itemKey) { if (itemKey === row.key) passwordField.clear() }
    }

    Rectangle {
        id: card
        x: row.columnX
        y: 4
        width: row.columnWidth
        implicitHeight: content.implicitHeight + 24
        height: implicitHeight
        radius: Metrics.radiusCard
        color: Theme.surface
        border.color: row.inRun && row.busy ? Theme.accent : Theme.border
        Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }

        ColumnLayout {
            id: content
            x: 16
            y: 12
            width: parent.width - 32
            spacing: 6

            // Kopf: Datei, Zustand, Entfernen
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                PIcon { name: "document_pdf"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText {
                        objectName: "repairItemName"
                        text: row.name
                        textStyle: "bodyStrong"
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                        PToolTip { text: row.path; visible: nameHover.hovered && row.path !== "" }
                        HoverHandler { id: nameHover }
                    }
                    PText { objectName: "repairItemCaption"; text: row.sizeText + (row.signatures > 0 ? " · digital signiert" : ""); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                }
                PBadge { objectName: "repairItemState"; text: row.stateText; tone: row.badgeTone; Layout.alignment: Qt.AlignTop }
                PIconButton {
                    objectName: "repairItemRemove"
                    iconName: "dismiss"
                    tip: "Aus der Liste entfernen (die Datei bleibt unverändert)"
                    enabled: row.state !== "repairing"
                    Layout.alignment: Qt.AlignTop
                    onClicked: Repair.remove(row.key)
                }
            }

            // Fortschritt dieser Datei
            PCollapse {
                Layout.fillWidth: true
                expanded: row.busy && row.progressShown
                ColumnLayout {
                    width: parent.width
                    spacing: 4
                    Item { implicitHeight: 2 }
                    PText { objectName: "repairItemPhase"; text: row.phaseText; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                    PProgressBar { Layout.fillWidth: true; indeterminate: row.progress < 0; value: Math.max(0, row.progress) }
                }
            }

            // Angaben der Analyse bzw. des Ergebnisses (Einzelmodus: immer sichtbar, wie bis 2.7.0 vor der Diagnose)
            PFactList {
                id: factList
                objectName: "repairFacts"
                Layout.fillWidth: true
                Layout.topMargin: 2
                visible: row.single
                facts: row.resultFacts.length > 0 ? row.resultFacts : row.facts
                SequentialAnimation {
                    id: factsFlash
                    NumberAnimation { target: factList; property: "opacity"; to: 0.35; duration: 60 }
                    NumberAnimation { target: factList; property: "opacity"; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                }
            }

            // Diagnose (Einzelmodus: wie bis 2.7.0 mit Erklärung; unlesbar → Rettungsmodus anbieten)
            PInfoBar {
                objectName: "repairDiagnosis"
                Layout.fillWidth: true
                topMargin: 2
                closable: false
                animate: Motion.enabled
                shown: row.single && row.diagTitle !== ""
                severity: row.diagSeverity !== "" ? row.diagSeverity : "info"
                title: row.diagTitle
                message: row.diagText
                actions: row.rescue && row.state === "unreadable" ? [Repair.texts.rescueActionShort] : []
                onActionTriggered: Repair.rescueItem(row.key)
            }

            // Hinweis oder Fehler (mehrere PDFs: auch die Erklärung des Zustands)
            PText {
                objectName: "repairItemMessage"
                text: row.message
                visible: text !== ""
                wrap: true
                tone: row.tone === "critical" ? "critical" : (row.tone === "caution" ? "caution" : "secondary")
                Layout.fillWidth: true
            }

            // Weitere Warnungen des Ergebnisses (z. B. fehlende Seiten, Signaturen)
            Repeater {
                model: row.warnings
                RowLayout {
                    required property string modelData
                    Layout.fillWidth: true
                    spacing: 8
                    PIcon { name: "warning"; color: Theme.warning; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                    PText { text: modelData; wrap: true; Layout.fillWidth: true }
                }
            }

            // Passwort (nur diese Datei)
            PCollapse {
                Layout.fillWidth: true
                expanded: row.needsPassword
                ColumnLayout {
                    width: parent.width
                    spacing: 0
                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        PTextField {
                            id: passwordField
                            objectName: "repairPassword"
                            preferredWidth: 240
                            label: "Passwort von " + row.name
                            placeholderText: "Passwort der PDF"
                            echoMode: TextInput.Password
                            passwordCharacter: "•"
                            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                            enabled: !row.busy
                            onSubmitted: Repair.unlock(row.key, text)
                        }
                        PButton { objectName: "repairUnlock"; iconName: "lock_closed"; text: "Entsperren"; tip: "Diese PDF mit dem Passwort öffnen"; enabled: !row.busy; onClicked: Repair.unlock(row.key, passwordField.text) }
                    }
                    PText { text: "Das Passwort gilt nur für diese Datei und wird nicht gespeichert."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
                }
            }

            // Ausgabename (ohne Endung; ».pdf« wird ergänzt)
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                visible: !row.hasOutput
                PText { text: "Ausgabe"; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 56 }
                PTextField {
                    id: nameField
                    objectName: "repairOutputName"
                    Layout.fillWidth: true
                    Layout.maximumWidth: 480
                    preferredWidth: 320
                    label: "Ausgabename für " + row.name
                    text: row.outputBase
                    invalid: row.nameError !== ""
                    enabled: !row.busy && !row.inRun
                    onTextEdited: Repair.setOutputName(row.key, text)
                }
                PText { text: ".pdf"; tone: "secondary" }
                PIconButton {
                    objectName: "repairOutputReset"
                    visible: row.nameManual || row.nameError !== ""
                    iconName: "arrow_reset"
                    tip: "Automatischen Namen wiederherstellen"
                    enabled: !row.busy && !row.inRun
                    onClicked: Repair.resetOutputName(row.key)
                }
                Item { Layout.fillWidth: true }
            }
            PText {
                objectName: "repairOutputNote"
                visible: !row.hasOutput && text !== ""
                text: row.nameError !== "" ? row.nameError : (row.numbered ? "Gespeichert wird als »" + row.outputName + "« – der Name ist schon vergeben." : "")
                tone: row.nameError !== "" ? "critical" : "secondary"
                textStyle: "caption"
                wrap: true
                Layout.fillWidth: true
                Layout.leftMargin: 62
            }
            PText {
                objectName: "repairOutputSaved"
                visible: row.hasOutput
                text: "Gespeichert als »" + row.outputName + "«"
                textStyle: "caption"
                tone: "secondary"
                elide: Text.ElideMiddle
                Layout.fillWidth: true
            }

            // Rettungsmodus nach einer erfolglosen oder unvollständigen Reparatur (Einzelmodus: mit Erklärung)
            PInfoBar {
                objectName: "repairRescue"
                Layout.fillWidth: true
                topMargin: 2
                closable: false
                animate: Motion.enabled
                shown: row.single && row.rescue && row.resultTitle !== ""
                severity: "info"
                title: Repair.texts.rescueTitle
                message: Repair.texts.rescueText
                actions: [Repair.texts.rescueAction]
                onActionTriggered: Repair.rescueItem(row.key)
            }

            // Aktionen
            Flow {
                Layout.fillWidth: true
                spacing: 8
                PButton {
                    objectName: "repairItemStart"
                    visible: !row.single && row.canRepair
                    iconName: "wrench"
                    text: row.repairText === "PDF reparieren" ? "Nur diese Datei reparieren" : row.repairText
                    tip: "Nur diese PDF reparieren"
                    onClicked: Repair.repairItem(row.key)
                }
                PButton {
                    objectName: "repairItemRescue"
                    visible: !row.single && row.rescue
                    iconName: "image"
                    text: Repair.texts.rescueActionShort
                    tip: "Rettungsmodus nur für diese Datei – lesbare Seiten als Bilder (mit Rückfrage)"
                    onClicked: Repair.rescueItem(row.key)
                }
                PButton { objectName: "repairItemAnalyze"; visible: row.canAnalyze; iconName: "arrow_clockwise"; text: "Erneut prüfen"; onClicked: Repair.analyzeAgain(row.key) }
                PButton { objectName: "repairItemOpen"; visible: !row.single && row.hasOutput; iconName: "window_new"; text: "Öffnen"; tip: "Reparierte PDF öffnen"; onClicked: Repair.openItemOutput(row.key) }
                PButton { visible: !row.single && row.hasOutput; iconName: "folder_open"; text: "Ordner öffnen"; onClicked: Repair.openItemFolder(row.key) }
                PButton { visible: !row.single && row.hasOutput; iconName: "copy"; text: "Pfad kopieren"; tip: "Pfad der reparierten PDF kopieren"; onClicked: Repair.copyItemOutput(row.key) }
                PButton {
                    objectName: "repairItemDetails"
                    kind: "subtle"
                    iconName: row.detailsOpen ? "chevron_up" : "info"
                    text: row.detailsOpen ? (row.single ? "Technische Details ausblenden" : "Details ausblenden") : (row.single ? "Technische Details anzeigen" : "Details anzeigen")
                    onClicked: row.toggleDetails()
                }
            }

            // Details – erst beim Aufklappen erzeugt (lange Listen bleiben leicht)
            PCollapse {
                id: detailsCollapse
                Layout.fillWidth: true
                expanded: row.detailsOpen
                Loader {
                    width: parent.width
                    active: row.detailsOpen || detailsCollapse.animating
                    sourceComponent: detailsComponent
                }
            }
        }
    }

    Component {
        id: detailsComponent
        ColumnLayout {
            objectName: "repairItemDetailsContent"
            spacing: 6
            // Mehrere PDFs: Diagnose und Ergebnis ausführlich, je mit ihren Angaben
            PInfoBar {
                objectName: "repairDetailsDiagnosis"
                Layout.fillWidth: true
                topMargin: 0
                closable: false
                animate: false
                shown: !row.single && row.diagTitle !== ""
                severity: row.diagSeverity !== "" ? row.diagSeverity : "info"
                title: row.diagTitle
                message: row.diagText
            }
            PFactList { Layout.fillWidth: true; visible: !row.single; facts: row.facts }
            PInfoBar {
                objectName: "repairDetailsResult"
                Layout.fillWidth: true
                topMargin: 4
                closable: false
                animate: false
                shown: !row.single && row.resultTitle !== ""
                severity: row.resultSeverity !== "" ? row.resultSeverity : "info"
                title: row.resultTitle
                message: row.resultText
            }
            PFactList { Layout.fillWidth: true; visible: !row.single && row.resultFacts.length > 0; facts: row.resultFacts }
            PText { visible: row.details.length > 0; text: "Befunde der Analyse"; textStyle: "bodyStrong"; Layout.topMargin: 4 }
            PFactList { objectName: "repairDetails"; Layout.fillWidth: true; labelWidth: 190; facts: row.details; visible: row.details.length > 0 }
            PText { visible: row.resultActions.length > 0; text: "Durchgeführte Schritte"; textStyle: "bodyStrong"; Layout.topMargin: 4 }
            PFactList { objectName: "repairSteps"; Layout.fillWidth: true; labelWidth: 40; facts: row.resultActions; visible: row.resultActions.length > 0 }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8
                PText { text: row.path; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                PIconButton { iconName: "copy"; tip: "Pfad der PDF kopieren"; onClicked: Repair.copyItemPath(row.key) }
            }
        }
    }
}
