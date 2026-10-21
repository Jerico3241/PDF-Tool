import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »PDF reparieren« (eine oder mehrere PDFs): PDFs wählen oder hineinziehen → jede
// wird für sich analysiert → Liste mit Zustand, Diagnose und geplantem Ausgabenamen → »PDF
// reparieren« bzw. »Alle reparieren« (nacheinander) mit Fortschritt je Datei und gesamt →
// Ergebnis je Datei und Zusammenfassung. Die Zeilen sind virtualisiert (auch 100 PDFs bleiben
// flüssig); neue und entfernte Dateien blenden weich ein und aus (Animationsprofil beachtet).
// Eine PDF: Reihenfolge wie bis 2.7.0 (Datei → Ausgabe → Reparieren → Ergebnis); mehrere PDFs:
// Ausgabe, »Alle reparieren« und Ergebnis über der Liste. Die Originaldateien werden nie verändert.
Item {
    id: root
    objectName: "repairPage"

    // Aufgeklappte Details (bleiben beim Scrollen erhalten, obwohl Zeilen wiederverwendet werden)
    property var openKeys: ({})
    function setOpen(key, open) {
        const next = Object.assign({}, openKeys)
        if (open)
            next[key] = true
        else
            delete next[key]
        openKeys = next
    }

    Connections {
        target: Repair
        function onFocusRequested(field) {
            const header = listPage.headerContentItem
            if (field !== "pick" || !header)
                return
            const button = Repair.hasFile ? header.addButton : header.pickButton
            if (button)
                button.forceActiveFocus(Qt.OtherFocusReason)
        }
        function onRevealRequested(what) {
            if (what === "result")
                revealTimer.restart()
        }
        function onHasFileChanged() {
            if (!Repair.hasFile)
                root.openKeys = ({})
        }
    }
    Timer {
        id: revealTimer
        interval: Motion.expand + 40  // nach dem Aufklappen
        // Eine PDF: Ergebnis unter der Datei; mehrere: Zusammenfassung über der Liste
        onTriggered: Repair.single ? listPage.positionViewAtEnd() : listPage.positionViewAtBeginning()
    }

    // Ausgabe, Reparieren/Abbrechen, Gesamtfortschritt, Ergebnis
    Component {
        id: controls
        ColumnLayout {
            spacing: 0

            PCard {
                objectName: "repairOutput"
                Layout.fillWidth: true
                Layout.topMargin: Repair.single ? 4 : 12
                title: I18n.tr("Ausgabe", I18n.revision)
                iconName: "folder"
                Flow {
                    Layout.fillWidth: true
                    spacing: 16
                    PRadioButton {
                        objectName: "repairOutOriginal"
                        text: I18n.tr("Neben der Original-PDF", I18n.revision)
                        checked: Repair.outMode === Repair.texts.outOriginal
                        enabled: !Repair.running
                        onClicked: Repair.setOutMode(Repair.texts.outOriginal)
                    }
                    PRadioButton {
                        objectName: "repairOutFolder"
                        text: I18n.tr("Gemeinsamer Ausgabeordner", I18n.revision)
                        checked: Repair.outMode === Repair.texts.outFolder
                        enabled: !Repair.running
                        onClicked: Repair.setOutMode(Repair.texts.outFolder)
                    }
                }
                PFileRow {
                    Layout.fillWidth: true
                    iconName: "folder"
                    label: I18n.tr("Ausgabeordner", I18n.revision)
                    value: Repair.outLabel
                    valueTone: Repair.outMissing ? "warning" : ""
                    fullPath: Repair.outPath
                    PButton { iconName: "folder_open"; text: I18n.tr("Durchsuchen", I18n.revision); tip: I18n.tr("Ordner für reparierte PDFs wählen", I18n.revision); enabled: !Repair.running; onClicked: Repair.pickOutDir() }
                }
                Rectangle { Layout.fillWidth: true; Layout.topMargin: 4; Layout.bottomMargin: 4; height: 1; color: Theme.divider }
                // Namensregel: »_repariert« anhängen (Standard: ein) und Zusatz
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PText { text: I18n.tr("„repariert“ an Dateinamen anhängen", I18n.revision); wrap: true; Layout.fillWidth: true }
                        PText { objectName: "repairNamingExample"; text: I18n.tr(Repair.namingExample, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                        TapHandler { enabled: !Repair.running; onTapped: Repair.setAppendSuffix(!Repair.appendSuffix) }
                    }
                    PToggle {
                        objectName: "repairAppendSuffix"
                        label: I18n.tr("„repariert“ an Dateinamen anhängen", I18n.revision)
                        checked: Repair.appendSuffix
                        enabled: !Repair.running
                        onToggled: Repair.setAppendSuffix(checked)
                    }
                }
                PCollapse {
                    Layout.fillWidth: true
                    expanded: Repair.appendSuffix
                    ColumnLayout {
                        width: parent.width
                        spacing: 2
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: 4
                            spacing: 8
                            PText { text: I18n.tr("Zusatz", I18n.revision); tone: "secondary" }
                            PTextField {
                                objectName: "repairSuffix"
                                preferredWidth: 160
                                label: I18n.tr("Zusatz am Dateinamen", I18n.revision)
                                text: Repair.suffix
                                invalid: Repair.suffixError !== ""
                                enabled: Repair.appendSuffix && !Repair.running
                                onTextEdited: Repair.setSuffix(text)
                            }
                            PButton {
                                kind: "subtle"
                                visible: Repair.suffix !== Repair.texts.defaultSuffix || Repair.suffixError !== ""
                                iconName: "arrow_reset"
                                text: I18n.tr("Standard", I18n.revision)
                                tip: I18n.tr("Zusatz »" + Repair.texts.defaultSuffix + "« verwenden", I18n.revision)
                                enabled: !Repair.running
                                onClicked: Repair.setSuffix(Repair.texts.defaultSuffix)
                            }
                            Item { Layout.fillWidth: true }
                        }
                        PText { objectName: "repairSuffixError"; visible: text !== ""; text: I18n.tr(Repair.suffixError, I18n.revision); tone: "critical"; textStyle: "caption"; wrap: true; Layout.fillWidth: true }
                    }
                }
                PText { objectName: "repairOutName"; Layout.topMargin: 4; text: I18n.tr(Repair.single ? Repair.outName : Repair.texts.namingHint, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }

            // Reparieren, Abbrechen, Gesamtfortschritt
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PButton {
                    objectName: "repairStart"
                    kind: "accent"
                    large: true
                    minimumWidth: 180
                    iconName: "wrench"
                    text: I18n.tr(Repair.primaryText, I18n.revision)
                    tip: I18n.tr((Repair.single ? "PDF reparieren" : "Alle beschädigten PDFs nacheinander reparieren") + Shortcuts.hints["app.primary"], I18n.revision)
                    enabled: Repair.canStart
                    onClicked: Repair.startRepair()
                }
                PButton {
                    objectName: "repairCancel"
                    large: true
                    iconName: "dismiss"
                    text: I18n.tr("Abbrechen", I18n.revision)
                    tip: I18n.tr(Repair.single ? "Vorgang abbrechen – es bleibt keine unvollständige Datei zurück" : "Laufende Reparatur sauber beenden und noch nicht gestartete Dateien auslassen – fertige Dateien bleiben", I18n.revision)
                    enabled: Repair.busy
                    onClicked: Repair.cancel()
                }
                PButton {
                    objectName: "repairRetry"
                    visible: Repair.canRetry && !Repair.hasResult
                    large: true
                    iconName: "arrow_clockwise"
                    text: I18n.tr("Fehlgeschlagene erneut versuchen", I18n.revision)
                    onClicked: Repair.retryFailed()
                }
            }
            PCollapse {
                Layout.fillWidth: true
                expanded: Repair.running
                ColumnLayout {
                    width: parent.width
                    spacing: 4
                    Item { implicitHeight: 6 }
                    PProgressBar { objectName: "repairProgress"; Layout.fillWidth: true; indeterminate: Repair.progressValue < 0; value: Math.max(0, Repair.progressValue) }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        PText { objectName: "repairProgressText"; text: I18n.tr(Repair.progressText, I18n.revision); textStyle: "bodyStrong" }
                        PCrossfadeText { objectName: "repairCurrent"; text: I18n.tr(Repair.currentText, I18n.revision); font: Typography.caption; color: Theme.textSecondary; Layout.fillWidth: true; Layout.preferredHeight: 20 }
                    }
                }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_info"); topMargin: 8 }

            // Ergebnis des Durchlaufs
            PCollapse {
                Layout.fillWidth: true
                expanded: Repair.hasResult
                ColumnLayout {
                    width: parent.width
                    spacing: 0
                    Item { implicitHeight: 12 }
                    PCard {
                        objectName: "repairResult"
                        Layout.fillWidth: true
                        title: I18n.tr("Ergebnis", I18n.revision)
                        iconName: "document_checkmark"
                        PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_result"); closable: false; topMargin: 0 }
                        Flow {
                            Layout.fillWidth: true
                            Layout.topMargin: 4
                            spacing: 8
                            readonly property bool alone: Repair.summary.single === true
                            readonly property bool saved: Repair.summary.hasOutput === true
                            // Eine Datei: wie bis 2.7.0
                            PButton { objectName: "repairOpen"; visible: parent.alone; kind: "accent"; iconName: "window_new"; text: I18n.tr("Öffnen", I18n.revision); tip: I18n.tr("Reparierte PDF öffnen", I18n.revision); enabled: parent.saved; onClicked: Repair.openResultFile() }
                            PButton { visible: parent.alone; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); enabled: parent.saved; onClicked: Repair.openResultFolder() }
                            PButton { visible: parent.alone; iconName: "copy"; text: I18n.tr("Pfad kopieren", I18n.revision); enabled: parent.saved; onClicked: Repair.copyResultPath() }
                            // Mehrere PDFs
                            PButton { objectName: "repairOpenFolder"; visible: !parent.alone; kind: "accent"; iconName: "folder_open"; text: I18n.tr("Ausgabeordner öffnen", I18n.revision); enabled: parent.saved; onClicked: Repair.openResultFolder() }
                            PButton { objectName: "repairResultRetry"; visible: Repair.canRetry; iconName: "arrow_clockwise"; text: I18n.tr("Fehlgeschlagene erneut versuchen", I18n.revision); onClicked: Repair.retryFailed() }
                            PButton { objectName: "repairAgain"; iconName: "add"; text: I18n.tr("Weitere PDFs reparieren", I18n.revision); tip: I18n.tr("Liste leeren und neue PDFs wählen", I18n.revision); enabled: !Repair.busy; onClicked: Repair.reset() }
                        }
                        PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_result_info"); topMargin: 4 }
                    }
                }
            }
        }
    }

    PListPage {
        id: listPage
        objectName: "repairList"
        anchors.fill: parent
        title: I18n.tr("PDF reparieren", I18n.revision)
        subtitle: I18n.tr("Beschädigte PDF-Dateien analysieren und lesbare Inhalte in neue PDFs übertragen – eine oder mehrere auf einmal.", I18n.revision)
        model: Repair.items
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("PDF-Dateien", I18n.revision)

        // Neue Dateien blenden ein, entfernte aus; die übrigen rücken weich nach
        add: Transition {
            enabled: Motion.enabled
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.normal; easing.type: Motion.decelerate }
            NumberAnimation { property: "scale"; from: Motion.moves ? 0.98 : 1; to: 1; duration: Motion.normal; easing.type: Motion.decelerate }
        }
        remove: Transition {
            enabled: Motion.enabled
            NumberAnimation { property: "opacity"; to: 0; duration: Motion.fade; easing.type: Motion.accelerate }
        }
        displaced: Transition {
            enabled: Motion.moves
            NumberAnimation { properties: "y"; duration: Motion.normal; easing.type: Motion.standard }
        }

        headerContent: ColumnLayout {
            property alias pickButton: pickButton
            property alias addButton: addButton
            spacing: 0

            // Datenschutz
            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 12
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: I18n.tr(Repair.texts.privacy, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }

            // Leer: große Ablagefläche
            PDropZone {
                objectName: "repairDrop"
                Layout.fillWidth: true
                visible: !Repair.hasFile
                highlighted: Repair.dropHighlight
                iconName: "document_pdf"
                title: I18n.tr(Repair.texts.emptyTitle, I18n.revision)
                text: I18n.tr(Repair.texts.emptyText, I18n.revision)
                actions: [
                    PButton {
                        id: pickButton
                        objectName: "repairPick"
                        kind: "accent"
                        iconName: "folder_open"
                        text: I18n.tr("PDFs auswählen", I18n.revision)
                        tip: I18n.tr("Eine oder mehrere PDFs auswählen" + Shortcuts.hints["app.open"], I18n.revision)
                        onClicked: Repair.pick()
                    }
                ]
            }

            // Mehrere PDFs: Gesamtstand; Liste bearbeiten
            PStatusLine { objectName: "repairOverview"; Layout.fillWidth: true; Layout.bottomMargin: 8; visible: Repair.hasFile && !Repair.single; kind: Repair.overviewKind; text: I18n.tr(Repair.overview, I18n.revision) }
            Flow {
                Layout.fillWidth: true
                visible: Repair.hasFile
                spacing: 8
                PButton {
                    id: addButton
                    objectName: "repairAdd"
                    iconName: "add"
                    text: I18n.tr("PDFs hinzufügen", I18n.revision)
                    tip: I18n.tr("Weitere PDFs zur Liste hinzufügen" + Shortcuts.hints["app.open"] + " – auch per Ziehen und Ablegen", I18n.revision)
                    onClicked: Repair.pick()
                }
                PButton {
                    objectName: "repairRemoveAll"
                    visible: Repair.count > 1
                    kind: "subtle"
                    iconName: "delete"
                    text: I18n.tr("Alle entfernen", I18n.revision)
                    tip: I18n.tr("Liste leeren – die Dateien bleiben unverändert", I18n.revision)
                    enabled: !Repair.running
                    onClicked: Repair.removeAll()
                }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("repair_drop_info"); topMargin: 8 }

            // Ein abgeschalteter Loader behält seine Höhe – deshalb zusätzlich ausblenden. »count« ändert
            // sich in einem Schritt (mit »hasFile« und »single« entstünde kurz ein Zwischenzustand).
            Loader {
                Layout.fillWidth: true
                active: Repair.count > 1
                visible: active
                sourceComponent: controls
            }
            Item { implicitHeight: Repair.hasFile ? 12 : 0 }
        }

        // Eine PDF: Ausgabe, Reparieren und Ergebnis unter der Datei
        footerContent: Item {
            implicitHeight: footerControls.active && footerControls.item ? footerControls.item.implicitHeight : 0
            Loader {
                id: footerControls
                width: parent.width
                active: Repair.count === 1
                sourceComponent: controls
            }
        }

        delegate: RepairItem {
            id: entry
            width: listPage.width
            columnX: listPage.columnX
            columnWidth: listPage.columnWidth
            detailsOpen: root.openKeys[entry.key] === true
            onToggleDetails: root.setOpen(entry.key, !entry.detailsOpen)
        }
    }
}
