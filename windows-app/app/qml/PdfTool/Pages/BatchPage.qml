import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Stapel«: mehrere Excel-Listen prüfen und gesammelt als PDF erstellen.
// Oben »Stapel« (Zusammenfassung, Fortschritt, Erstellen) neben »Ausgabe und Standards«, darunter
// Filter, Massenaktionen und die virtualisierte Liste. Ein Eintrag öffnet sich zum Bearbeiten.
Item {
    id: root
    objectName: "batchPage"
    readonly property bool detail: Batch.detailId !== ""

    // Liste ---------------------------------------------------------------------------------------
    PListPage {
        id: listPage
        anchors.fill: parent
        opacity: root.detail ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr(Batch.texts.subtitle, I18n.revision)
        model: Batch.listModel
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Stapel", I18n.revision)
        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
        Keys.onSpacePressed: if (currentIndex >= 0) Batch.toggleSelected(model.get(currentIndex).id)
        Keys.onReturnPressed: if (currentIndex >= 0) Batch.showDetail(model.get(currentIndex).id)
        Keys.onEnterPressed: if (currentIndex >= 0) Batch.showDetail(model.get(currentIndex).id)

        headerContent: ColumnLayout {
            spacing: 0
            ContractViews {}
            Flow {
                Layout.fillWidth: true
                visible: Batch.hasItems
                spacing: 8
                PButton { iconName: "add"; text: I18n.tr("Excel-Dateien hinzufügen", I18n.revision); tip: I18n.tr("Mehrere Excel-Dateien wählen" + Shortcuts.hints["app.open"], I18n.revision); onClicked: Batch.pickFiles() }
                PButton { iconName: "folder_open"; text: I18n.tr("Ordner hinzufügen", I18n.revision); tip: I18n.tr("Alle Excel-Dateien eines Ordners hinzufügen (ohne Unterordner)", I18n.revision); onClicked: Batch.pickFolder() }
                PButton { kind: "subtle"; iconName: "arrow_clockwise"; text: I18n.tr("Neuer Stapel", I18n.revision); visible: Batch.newVisible; tip: I18n.tr("Liste leeren – Dateien, Kundenakten, Vorlagen und Einstellungen bleiben", I18n.revision); onClicked: Batch.newBatch() }
            }
            PInfoBar { id: batchInfo; Layout.fillWidth: true; notice: Notices.area("batch_info"); topMargin: Batch.hasItems ? 8 : 0 }
            // Abstand zu den Karten nur unter Schaltflächen bzw. Hinweis – ohne sie stehen die Karten so
            // dicht unter den Ansichten wie auf allen anderen Ansichten von »Vertragsübersichten«
            Item {
                Layout.fillWidth: true
                implicitHeight: Batch.hasItems || batchInfo.shown ? 12 : 0
                Behavior on implicitHeight { enabled: Motion.moves; NumberAnimation { duration: Motion.infoBar; easing.type: Motion.decelerate } }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: listPage.columns
                columnSpacing: 12
                rowSpacing: 12

                // Leer: Dateien hinzufügen
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    visible: !Batch.hasItems
                    implicitHeight: emptyColumn.implicitHeight + 56
                    radius: Metrics.radiusCard
                    color: Theme.surface
                    border.color: Theme.border
                    ColumnLayout {
                        id: emptyColumn
                        x: 24
                        y: 28
                        width: parent.width - 48
                        spacing: 4
                        PIcon { name: "stack"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                        PText { text: I18n.tr(Batch.texts.emptyTitle, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 6 }
                        PText { text: I18n.tr(Batch.texts.emptyText, I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                        Flow {
                            Layout.fillWidth: true
                            Layout.topMargin: 10
                            spacing: 8
                            PButton { kind: "accent"; iconName: "add"; text: I18n.tr("Dateien hinzufügen", I18n.revision); onClicked: Batch.pickFiles() }
                            PButton { iconName: "folder_open"; text: I18n.tr("Ordner hinzufügen", I18n.revision); onClicked: Batch.pickFolder() }
                        }
                        PText { text: I18n.tr(Batch.customerParts ? Batch.texts.emptyHint : Batch.texts.emptyHintPlain, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8 }
                    }
                }

                // Stapel: Zusammenfassung, Fortschritt, Ergebnis, Erstellen
                PCard {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    visible: Batch.hasItems
                    title: I18n.tr("Stapel", I18n.revision)
                    iconName: "stack"
                    PStatusLine {
                        Layout.fillWidth: true
                        objectName: "batchSummary"
                        visible: !Batch.result.shown
                        kind: Batch.summaryKind
                        text: I18n.tr(Batch.summaryText, I18n.revision)
                    }
                    PCollapse {
                        Layout.fillWidth: true
                        expanded: Batch.running
                        ColumnLayout {
                            width: parent.width
                            spacing: 2
                            PProgressBar {
                                Layout.fillWidth: true
                                Layout.topMargin: 10
                                value: Batch.progress
                                color: Batch.progressError ? Theme.warning : Theme.accent
                            }
                            PText { text: I18n.tr(Batch.progressText, I18n.revision); Layout.fillWidth: true; Layout.topMargin: 4 }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                PProgressRing { size: 16; running: Batch.running }
                                PCrossfadeText { text: I18n.tr(Batch.currentText, I18n.revision); font: Typography.caption; color: Theme.textSecondary; Layout.fillWidth: true; Layout.preferredHeight: 20 }
                            }
                        }
                    }
                    PCollapse {
                        Layout.fillWidth: true
                        expanded: Batch.result.shown === true
                        Rectangle {
                            width: parent.width
                            implicitHeight: resultColumn.implicitHeight + 20
                            height: implicitHeight
                            radius: Metrics.radiusControl
                            color: Theme.surfaceSecondary
                            border.color: Theme.border
                            ColumnLayout {
                                id: resultColumn
                                x: 14
                                y: 10
                                width: parent.width - 28
                                spacing: 6
                                RowLayout {
                                    spacing: 10
                                    PIcon { name: Theme.toneIcon(Batch.result.severity || "success"); color: Theme.toneIconColor(Batch.result.severity || "success") }
                                    PText { text: I18n.tr(Batch.result.title || "", I18n.revision); textStyle: "bodyStrong" }
                                }
                                PText { text: I18n.tr(Batch.result.message || "", I18n.revision); wrap: true; Layout.fillWidth: true; leftPadding: 26 }
                                Flow {
                                    Layout.fillWidth: true
                                    leftPadding: 26
                                    spacing: 8
                                    PButton { visible: Batch.result.hasOutput === true; iconName: "folder_open"; text: I18n.tr("Ausgabeordner öffnen", I18n.revision); onClicked: Batch.openOutput() }
                                    PButton { visible: Batch.result.hasErrors === true; iconName: "warning"; text: I18n.tr("Fehler anzeigen", I18n.revision); onClicked: Batch.showErrors() }
                                    PButton { iconName: "arrow_clockwise"; text: I18n.tr("Neuer Stapel", I18n.revision); onClicked: Batch.newBatch() }
                                }
                            }
                        }
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 12
                        spacing: 8
                        PButton {
                            objectName: "batchRun"
                            kind: "accent"
                            large: true
                            iconName: "document_pdf"
                            text: I18n.tr(Batch.texts.run, I18n.revision)
                            enabled: Batch.canRun
                            busy: Batch.running
                            busyText: I18n.tr("Wird erstellt …", I18n.revision)
                            tip: I18n.tr("Alle bereiten Einträge nacheinander erstellen" + Shortcuts.hints["app.primary"], I18n.revision)
                            onClicked: Batch.run()
                        }
                        PButton { visible: Batch.running; large: true; iconName: "stop"; text: I18n.tr("Stapel abbrechen", I18n.revision); enabled: Batch.canCancel; tip: I18n.tr("Nach der laufenden PDF anhalten – fertige PDFs bleiben erhalten", I18n.revision); onClicked: Batch.cancel() }
                        PButton { visible: Batch.canRetry; large: true; iconName: "arrow_clockwise"; text: I18n.tr("Fehlgeschlagene erneut versuchen", I18n.revision); tip: I18n.tr("Nur fehlgeschlagene Einträge erneut prüfen und erstellen", I18n.revision); onClicked: Batch.retryFailed() }
                    }
                }

                // Ausgabe und Standards
                PCard {
                    id: settingsCard
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    title: I18n.tr("Ausgabe und Standards", I18n.revision)
                    iconName: "settings"
                    subtitle: I18n.tr(Batch.customerParts ? Batch.texts.settingsText : Batch.texts.settingsTextPlain, I18n.revision)
                    property bool more: false
                    PFileRow {
                        Layout.fillWidth: true
                        iconName: "folder"
                        label: I18n.tr("Zielordner", I18n.revision)
                        value: Batch.targetText
                        fullPath: Batch.targetPath
                        PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Gemeinsamen Zielordner wählen", I18n.revision); onClicked: Batch.pickTarget() }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 12
                        rowSpacing: 6
                        PText { text: I18n.tr("Vorlage des Stapels", I18n.revision) }
                        PComboBox {
                            Layout.fillWidth: true
                            preferredWidth: 220
                            label: I18n.tr("Vorlage des Stapels", I18n.revision)
                            tip: I18n.tr("Vorlage für Einträge ohne eigene Vorlage und ohne Vorlage der Kundenakte – sonst gilt die Standardvorlage", I18n.revision)
                            model: Batch.templateChoices
                            currentIndex: Batch.templateChoices.indexOf(Batch.templateValue)
                            onActivated: (index) => Batch.setDefaultTemplate(Batch.templateChoices[index])
                        }
                        PText { text: I18n.tr("Vorhandene PDF", I18n.revision) }
                        PComboBox {
                            Layout.fillWidth: true
                            preferredWidth: 220
                            label: I18n.tr("Vorhandene PDF", I18n.revision)
                            tip: I18n.tr("Was geschieht, wenn es die PDF schon gibt (Standard: automatisch nummerieren)", I18n.revision)
                            model: Batch.conflictChoices
                            textRole: "label"
                            valueRole: "value"
                            currentIndex: {
                                for (var i = 0; i < Batch.conflictChoices.length; ++i)
                                    if (Batch.conflictChoices[i].value === Batch.conflictValue) return i
                                return 0
                            }
                            onActivated: (index) => Batch.setConflict(Batch.conflictChoices[index].value)
                        }
                    }
                    PButton {
                        kind: "subtle"
                        Layout.topMargin: 8
                        iconName: settingsCard.more ? "chevron_up" : "chevron_down"
                        text: I18n.tr(settingsCard.more ? "Weniger Einstellungen" : "Weitere Einstellungen", I18n.revision)
                        tip: I18n.tr("Standardlogo, Unterordner je Kunde, Zielordner der Kundenakte", I18n.revision)
                        onClicked: settingsCard.more = !settingsCard.more
                    }
                    PCollapse {
                        Layout.fillWidth: true
                        expanded: settingsCard.more
                        ColumnLayout {
                            width: parent.width
                            spacing: 4
                            PFileRow {
                                Layout.fillWidth: true
                                Layout.topMargin: 6
                                iconName: "image"
                                label: I18n.tr("Standardlogo", I18n.revision)
                                value: Batch.logoText
                                fullPath: Batch.logoPath
                                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Logo für Einträge ohne eigenes Logo", I18n.revision); onClicked: Batch.pickLogo() }
                                PIconButton { iconName: "arrow_reset"; tip: I18n.tr("Installiertes Standardlogo verwenden", I18n.revision); onClicked: Batch.resetLogo() }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: 6
                                spacing: 8
                                PToggle { showState: false; label: I18n.tr("Unterordner je Kunde", I18n.revision); checked: Batch.subfolders; onToggled: Batch.setSubfolders(checked) }
                                PText { text: I18n.tr("Unterordner je Kunde (»123456 Beispiel GmbH«)", I18n.revision); wrap: true; Layout.fillWidth: true }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: Batch.customerParts
                                spacing: 8
                                PToggle { showState: false; label: I18n.tr("Zielordner der Kundenakte verwenden", I18n.revision); checked: Batch.customerTarget; onToggled: Batch.setCustomerTarget(checked) }
                                PText { text: I18n.tr("Zielordner der Kundenakte verwenden", I18n.revision); wrap: true; Layout.fillWidth: true }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                        PText { text: I18n.tr(Batch.texts.privacy, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    }
                }
            }

            // Filter und Massenaktionen
            ColumnLayout {
                Layout.fillWidth: true
                visible: Batch.hasItems
                spacing: 0
                PSelectorBar {
                    Layout.topMargin: 16
                    current: Batch.filter
                    items: Batch.filters
                    onSelected: (key) => Batch.setFilter(key)
                    Accessible.name: I18n.tr("Filter", I18n.revision)
                }
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 8
                    PCheckBox {
                        text: I18n.tr("Alle auswählen", I18n.revision)
                        tristate: true
                        wrap: false
                        enabled: Batch.visibleCount > 0
                        checkState: Batch.checkAll === 2 ? Qt.Checked : (Batch.checkAll === 1 ? Qt.PartiallyChecked : Qt.Unchecked)
                        nextCheckState: function() { return checkState }
                        onClicked: Batch.toggleAll()
                    }
                    PText { text: I18n.tr(Batch.selectedText, I18n.revision); textStyle: "caption"; tone: "secondary"; height: 32; visible: text !== "" }
                    PButton { iconName: "document"; text: I18n.tr("Vorlage anwenden …", I18n.revision); enabled: Batch.selection > 0 && !Batch.running; tip: I18n.tr("Dieselbe Vorlage für alle ausgewählten Einträge setzen", I18n.revision); onClicked: Batch.applyTemplateToSelection() }
                    PButton { iconName: "delete"; text: I18n.tr("Auswahl entfernen", I18n.revision); enabled: Batch.selection > 0 && !Batch.running; tip: I18n.tr("Ausgewählte Einträge aus dem Stapel nehmen (die Dateien bleiben)", I18n.revision); onClicked: Batch.removeSelected() }
                }
                PText { text: I18n.tr(Batch.filterEmpty, I18n.revision); tone: "secondary"; visible: text !== ""; Layout.topMargin: 12 }
                Item { implicitHeight: 8 }
            }
        }

        // Karte hinter den Zeilen
        Rectangle {
            parent: listPage.contentItem
            z: -1
            x: listPage.columnX
            y: -6  // die erste Zeile beginnt bei 0, der Kopfbereich liegt darüber
            width: listPage.columnWidth
            height: listPage.count * 64 + 12
            visible: listPage.count > 0
            radius: Metrics.radiusCard
            color: Theme.surface
            border.color: Theme.border
        }

        delegate: Item {
            id: row
            required property int index
            required property string id
            required property string name
            required property string facts
            required property string detail
            required property string detailTone
            required property string status
            required property string statusTone
            required property string statusKey
            required property bool selected
            width: listPage.width
            height: 64
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(name + ", " + status + (detail !== "" ? ", " + detail : ""), I18n.revision)

            PListItem {
                x: listPage.columnX + 6
                y: 2
                width: listPage.columnWidth - 12
                height: row.height - 4
                hovered: mouse.containsMouse
                pressed: mouse.pressed
                selected: row.selected
                focused: listPage.activeFocus && listPage.currentIndex === row.index
            }
            Rectangle {
                visible: row.index > 0
                x: listPage.columnX + 14
                width: listPage.columnWidth - 28
                height: 1
                color: Theme.divider
            }
            RowLayout {
                x: listPage.columnX + 14
                width: listPage.columnWidth - 34
                height: row.height
                spacing: 12
                PCheckBox {
                    checked: row.selected
                    text: ""
                    Accessible.name: I18n.tr(row.name + " auswählen", I18n.revision)
                    onClicked: Batch.select(row.id, checked)
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { text: I18n.tr(row.name, I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: I18n.tr(row.facts, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                    PText { text: I18n.tr(row.detail, I18n.revision); textStyle: "caption"; tone: row.detailTone === "muted" ? "secondary" : row.detailTone; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                }
                PBadge { text: I18n.tr(row.status, I18n.revision); tone: row.statusTone === "critical" ? "error" : row.statusTone }
                PIcon { name: "chevron_right"; size: 12; color: Theme.textSecondary }
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                anchors.leftMargin: listPage.columnX + 50
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.PointingHandCursor
                onClicked: (mouseEvent) => {
                    listPage.currentIndex = row.index
                    if (mouseEvent.button === Qt.RightButton) menu.popup()
                    else Batch.showDetail(row.id)
                }
            }
            PMenu {
                id: menu
                PMenuItem { text: I18n.tr("Eintrag öffnen", I18n.revision); iconName: "open"; onTriggered: Batch.showDetail(row.id) }
                PMenuItem { text: I18n.tr("PDF öffnen", I18n.revision); iconName: "document_pdf"; enabled: row.statusKey === "success" || row.statusKey === "warning"; onTriggered: Batch.openItemPdf(row.id) }
                PMenuItem { text: I18n.tr("Pfad kopieren", I18n.revision); iconName: "copy"; onTriggered: Batch.copyItemPath(row.id) }
                PMenuItem { text: I18n.tr("Aus Stapel entfernen", I18n.revision); iconName: "delete"; enabled: !Batch.running; onTriggered: Batch.removeItem(row.id) }
            }
        }
    }

    // Detail eines Eintrags -----------------------------------------------------------------------------
    PPage {
        id: detailPage
        anchors.fill: parent
        opacity: root.detail ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr(Batch.texts.subtitle, I18n.revision)
        onVisibleChanged: if (visible) scrollToTop()

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: I18n.tr("Alle Einträge", I18n.revision); tip: I18n.tr("Zurück zur Liste", I18n.revision); onClicked: Batch.showList() }
            Item { Layout.fillWidth: true }
            PIconButton { iconName: "chevron_left"; tip: I18n.tr("Vorheriger Eintrag", I18n.revision); enabled: Batch.canPrev; onClicked: Batch.step(-1) }
            PText { text: I18n.tr(Batch.position, I18n.revision); textStyle: "caption"; tone: "secondary" }
            PIconButton { iconName: "chevron_right"; tip: I18n.tr("Nächster Eintrag", I18n.revision); enabled: Batch.canNext; onClicked: Batch.step(1) }
        }
        PText { text: I18n.tr(Batch.detailTitle, I18n.revision); textStyle: "subtitle"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
        PText { text: I18n.tr(Batch.detailFolder, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2 }
        PStatusLine { Layout.fillWidth: true; Layout.topMargin: 10; kind: Batch.detailKind; text: I18n.tr(Batch.detailText, I18n.revision) }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_detail_info") }

        GridLayout {
            Layout.fillWidth: true
            Layout.topMargin: 12
            columns: detailPage.columns
            columnSpacing: 12
            rowSpacing: 12

            PCard {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                title: I18n.tr("Excel-Prüfung", I18n.revision)
                iconName: "document_table"
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_excel"); closable: false; topMargin: 0 }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 12
                    PText { text: I18n.tr("Rechnungsempfänger", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150 }
                    PText { text: I18n.tr(Batch.mailValue, I18n.revision); Layout.fillWidth: true }
                    PComboBox {
                        visible: Batch.mailChoices.length > 1
                        preferredWidth: 210
                        label: I18n.tr("Rechnungsempfänger", I18n.revision)
                        tip: I18n.tr("Rechnungsempfänger für diese Übersicht", I18n.revision)
                        placeholder: I18n.tr("Empfänger wählen", I18n.revision)
                        model: Batch.mailChoices
                        currentIndex: Batch.mailChoices.indexOf(Batch.mailChoice)
                        onActivated: (index) => Batch.pickMail(Batch.mailChoices[index])
                    }
                    PTextField {
                        visible: Batch.mailField
                        preferredWidth: 210
                        label: I18n.tr("Rechnungsempfänger", I18n.revision)
                        placeholderText: I18n.tr("E-Mail-Adresse (optional)", I18n.revision)
                        text: Batch.email
                        onTextEdited: Batch.email = text
                        onActiveFocusChanged: Batch.setFieldFocus("email", activeFocus)
                    }
                }
                PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: Batch.excelFacts }
            }

            PCard {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                title: I18n.tr("Kunde", I18n.revision)
                iconName: "contact_card"
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: Batch.customerParts
                    spacing: 2
                    PText { text: I18n.tr(Batch.customerTitle, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                    PText { text: I18n.tr(Batch.customerNote, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; visible: text !== "" }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        spacing: 6
                        PButton { iconName: "people"; text: I18n.tr("Kunden auswählen …", I18n.revision); enabled: !Batch.itemRunning; tip: I18n.tr("Bekannten Kunden für diesen Eintrag wählen", I18n.revision); onClicked: Batch.chooseCustomer() }
                        PButton { kind: "subtle"; text: I18n.tr("Ohne Kundenakte", I18n.revision); visible: Batch.customerMode !== "none"; enabled: !Batch.itemRunning; tip: I18n.tr("Diesen Eintrag ohne Kundenakte erstellen – Angaben selbst eintragen", I18n.revision); onClicked: Batch.setCustomerMode("none") }
                        PButton { kind: "subtle"; text: I18n.tr("Automatisch erkennen", I18n.revision); visible: Batch.customerMode !== "auto"; enabled: !Batch.itemRunning; tip: I18n.tr("Kunden wieder über die Rechnungsempfänger erkennen", I18n.revision); onClicked: Batch.setCustomerMode("auto") }
                    }
                }
                PFieldLabel { text: I18n.tr("Firmenname", I18n.revision); first: !Batch.customerParts }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Firmenname", I18n.revision); placeholderText: I18n.tr("z. B. Muster GmbH", I18n.revision); text: Batch.company; invalid: Batch.companyError; onTextEdited: Batch.company = text; onActiveFocusChanged: Batch.setFieldFocus("company", activeFocus) }
                PFieldLabel { text: I18n.tr("Kundennummer", I18n.revision) }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Kundennummer", I18n.revision); placeholderText: I18n.tr("z. B. 10042", I18n.revision); text: Batch.number; invalid: Batch.numberError; onTextEdited: Batch.number = text; onActiveFocusChanged: Batch.setFieldFocus("number", activeFocus) }
                PText { text: I18n.tr(Batch.valueSource, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4; visible: text !== "" }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_mail_info"); visible: Batch.customerParts && (shown || animating) }
            }
        }

        // Vertragsänderungen (dieselbe Anzeige wie im Einzelmodus)
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            visible: Batch.customerParts
            title: I18n.tr("Vertragsänderungen", I18n.revision)
            iconName: "history"
            ComparisonHead { Layout.fillWidth: true; view: Batch.comparison }
            Column {
                Layout.fillWidth: true
                Layout.topMargin: 6
                visible: Batch.comparison.mode === "comparison" && Batch.comparison.rowCount > 0
                Repeater {
                    model: Batch.comparison.mode === "comparison" ? Batch.comparison.changeModel : null
                    ChangeRow { view: Batch.comparison; width: parent ? parent.width : 400 }
                }
            }
            ComparisonFoot { Layout.fillWidth: true; Layout.topMargin: 8; view: Batch.comparison; visible: Batch.comparison.mode === "comparison" }
        }

        // Darstellung und Ausgabe
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: I18n.tr("Darstellung und Ausgabe", I18n.revision)
            iconName: "document"
            subtitle: I18n.tr(Batch.customerParts ? Batch.texts.outputText : Batch.texts.outputTextPlain, I18n.revision)
            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 12
                rowSpacing: 6
                PText { text: I18n.tr("Vorlage", I18n.revision) }
                PComboBox {
                    preferredWidth: 240
                    label: I18n.tr("Vorlage", I18n.revision)
                    tip: I18n.tr("»Automatisch«: Vorlage der Kundenakte, sonst die Vorlage des Stapels, sonst die Standardvorlage", I18n.revision)
                    model: Batch.itemTemplateChoices
                    currentIndex: Batch.itemTemplateChoices.indexOf(Batch.itemTemplate)
                    onActivated: (index) => Batch.setItemTemplate(Batch.itemTemplateChoices[index])
                }
                Item { Layout.fillWidth: true }
                PText { text: I18n.tr("Regelwerk", I18n.revision) }
                PComboBox {
                    objectName: "itemRuleSet"
                    preferredWidth: 240
                    label: I18n.tr("Regelwerk", I18n.revision)
                    tip: I18n.tr("»Automatisch«: Regelwerk der Vorlage, sonst das der »Darstellung«", I18n.revision)
                    model: Batch.itemRuleSetChoices
                    currentIndex: Batch.itemRuleSetChoices.indexOf(Batch.itemRuleSet)
                    onActivated: (index) => Batch.setItemRuleSet(Batch.itemRuleSetChoices[index])
                }
                Item { Layout.fillWidth: true }
            }
            PText { text: I18n.tr(Batch.templateNote, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "image"
                label: I18n.tr("Logo", I18n.revision)
                value: Batch.itemLogoText
                fullPath: Batch.itemLogoPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; onClicked: Batch.pickItemLogo() }
                PIconButton { iconName: "arrow_undo"; tip: I18n.tr("Zurücksetzen (Kundenakte bzw. Stapel)", I18n.revision); enabled: Batch.itemLogoReset; onClicked: Batch.resetItemLogo() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: I18n.tr("Zielordner", I18n.revision)
                value: Batch.itemTargetText
                fullPath: Batch.itemTargetPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; onClicked: Batch.pickItemTarget() }
                PIconButton { iconName: "arrow_undo"; tip: I18n.tr("Zurücksetzen (Kundenakte bzw. Stapel)", I18n.revision); enabled: Batch.itemTargetReset; onClicked: Batch.resetItemTarget() }
            }
            PText { text: I18n.tr(Batch.outputText, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8; visible: text !== "" }
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 16
            spacing: 8
            PButton { kind: "accent"; iconName: "eye"; text: I18n.tr("Vorschau", I18n.revision); enabled: Batch.canPreview; tip: I18n.tr("Diesen Eintrag in der Vorschau ansehen – dieselbe Vorschau wie im Einzelmodus", I18n.revision); onClicked: Batch.preview() }
            PButton { iconName: "edit"; text: I18n.tr("Einzeln bearbeiten", I18n.revision); tip: I18n.tr("Eintrag in »Übersicht erstellen« übernehmen", I18n.revision); onClicked: Batch.editSingle() }
            PButton { visible: Batch.hasOutput; iconName: "open"; text: I18n.tr("PDF öffnen", I18n.revision); onClicked: Batch.openPdf() }
            PButton { visible: Batch.hasOutput; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); onClicked: Batch.openFolder() }
            PButton { objectName: "batchMailPdf"; visible: Batch.hasOutput; iconName: "mail"; text: I18n.tr("Per E-Mail senden", I18n.revision); tip: I18n.tr("Neue E-Mail mit dieser PDF als Anhang – an den Rechnungsempfänger des Eintrags, falls bekannt", I18n.revision); onClicked: Batch.mailPdf() }
            PButton { iconName: "delete"; text: I18n.tr("Aus Stapel entfernen", I18n.revision); tip: I18n.tr("Eintrag aus dem Stapel nehmen – die Datei bleibt", I18n.revision); onClicked: Batch.removeCurrent() }
        }
    }
}
