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
        title: "Vertragsübersichten"
        subtitle: Batch.texts.subtitle
        model: Batch.listModel
        Accessible.role: Accessible.List
        Accessible.name: "Stapel"
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
                PButton { iconName: "add"; text: "Excel-Dateien hinzufügen"; tip: "Mehrere Excel-Dateien wählen (Strg+O)"; onClicked: Batch.pickFiles() }
                PButton { iconName: "folder_open"; text: "Ordner hinzufügen"; tip: "Alle Excel-Dateien eines Ordners hinzufügen (ohne Unterordner)"; onClicked: Batch.pickFolder() }
                PButton { kind: "subtle"; iconName: "arrow_clockwise"; text: "Neuer Stapel"; visible: Batch.newVisible; tip: "Liste leeren – Dateien, Kundenakten, Vorlagen und Einstellungen bleiben"; onClicked: Batch.newBatch() }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_info"); topMargin: Batch.hasItems ? 8 : 0 }

            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
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
                        PText { text: Batch.texts.emptyTitle; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 6 }
                        PText { text: Batch.texts.emptyText; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                        Flow {
                            Layout.fillWidth: true
                            Layout.topMargin: 10
                            spacing: 8
                            PButton { kind: "accent"; iconName: "add"; text: "Dateien hinzufügen"; onClicked: Batch.pickFiles() }
                            PButton { iconName: "folder_open"; text: "Ordner hinzufügen"; onClicked: Batch.pickFolder() }
                        }
                        PText { text: Batch.customerParts ? Batch.texts.emptyHint : Batch.texts.emptyHintPlain; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8 }
                    }
                }

                // Stapel: Zusammenfassung, Fortschritt, Ergebnis, Erstellen
                PCard {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    visible: Batch.hasItems
                    title: "Stapel"
                    iconName: "stack"
                    PStatusLine {
                        Layout.fillWidth: true
                        objectName: "batchSummary"
                        visible: !Batch.result.shown
                        kind: Batch.summaryKind
                        text: Batch.summaryText
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
                            PText { text: Batch.progressText; Layout.fillWidth: true; Layout.topMargin: 4 }
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8
                                PProgressRing { size: 16; running: Batch.running }
                                PCrossfadeText { text: Batch.currentText; font: Typography.caption; color: Theme.textSecondary; Layout.fillWidth: true; Layout.preferredHeight: 20 }
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
                                    PText { text: Batch.result.title || ""; textStyle: "bodyStrong" }
                                }
                                PText { text: Batch.result.message || ""; wrap: true; Layout.fillWidth: true; leftPadding: 26 }
                                Flow {
                                    Layout.fillWidth: true
                                    leftPadding: 26
                                    spacing: 8
                                    PButton { visible: Batch.result.hasOutput === true; iconName: "folder_open"; text: "Ausgabeordner öffnen"; onClicked: Batch.openOutput() }
                                    PButton { visible: Batch.result.hasErrors === true; iconName: "warning"; text: "Fehler anzeigen"; onClicked: Batch.showErrors() }
                                    PButton { iconName: "arrow_clockwise"; text: "Neuer Stapel"; onClicked: Batch.newBatch() }
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
                            text: Batch.texts.run
                            enabled: Batch.canRun
                            busy: Batch.running
                            busyText: "Wird erstellt …"
                            tip: "Alle bereiten Einträge nacheinander erstellen (Strg+Enter)"
                            onClicked: Batch.run()
                        }
                        PButton { visible: Batch.running; large: true; iconName: "stop"; text: "Stapel abbrechen"; enabled: Batch.canCancel; tip: "Nach der laufenden PDF anhalten – fertige PDFs bleiben erhalten"; onClicked: Batch.cancel() }
                        PButton { visible: Batch.canRetry; large: true; iconName: "arrow_clockwise"; text: "Fehlgeschlagene erneut versuchen"; tip: "Nur fehlgeschlagene Einträge erneut prüfen und erstellen"; onClicked: Batch.retryFailed() }
                    }
                }

                // Ausgabe und Standards
                PCard {
                    id: settingsCard
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    title: "Ausgabe und Standards"
                    iconName: "settings"
                    subtitle: Batch.customerParts ? Batch.texts.settingsText : Batch.texts.settingsTextPlain
                    property bool more: false
                    PFileRow {
                        Layout.fillWidth: true
                        iconName: "folder"
                        label: "Zielordner"
                        value: Batch.targetText
                        fullPath: Batch.targetPath
                        PButton { text: "Durchsuchen"; iconName: "folder_open"; tip: "Gemeinsamen Zielordner wählen"; onClicked: Batch.pickTarget() }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 12
                        rowSpacing: 6
                        PText { text: "Vorlage des Stapels" }
                        PComboBox {
                            Layout.fillWidth: true
                            preferredWidth: 220
                            label: "Vorlage des Stapels"
                            tip: "Vorlage für Einträge ohne eigene Vorlage und ohne Vorlage der Kundenakte – sonst gilt die Standardvorlage"
                            model: Batch.templateChoices
                            currentIndex: Batch.templateChoices.indexOf(Batch.templateValue)
                            onActivated: (index) => Batch.setDefaultTemplate(Batch.templateChoices[index])
                        }
                        PText { text: "Vorhandene PDF" }
                        PComboBox {
                            Layout.fillWidth: true
                            preferredWidth: 220
                            label: "Vorhandene PDF"
                            tip: "Was geschieht, wenn es die PDF schon gibt (Standard: automatisch nummerieren)"
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
                        text: settingsCard.more ? "Weniger Einstellungen" : "Weitere Einstellungen"
                        tip: "Standardlogo, Unterordner je Kunde, Zielordner der Kundenakte"
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
                                label: "Standardlogo"
                                value: Batch.logoText
                                fullPath: Batch.logoPath
                                PButton { text: "Durchsuchen"; iconName: "folder_open"; tip: "Logo für Einträge ohne eigenes Logo"; onClicked: Batch.pickLogo() }
                                PIconButton { iconName: "arrow_reset"; tip: "Installiertes Standardlogo verwenden"; onClicked: Batch.resetLogo() }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Layout.topMargin: 6
                                spacing: 8
                                PToggle { showState: false; label: "Unterordner je Kunde"; checked: Batch.subfolders; onToggled: Batch.setSubfolders(checked) }
                                PText { text: "Unterordner je Kunde (»123456 Beispiel GmbH«)"; wrap: true; Layout.fillWidth: true }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: Batch.customerParts
                                spacing: 8
                                PToggle { showState: false; label: "Zielordner der Kundenakte verwenden"; checked: Batch.customerTarget; onToggled: Batch.setCustomerTarget(checked) }
                                PText { text: "Zielordner der Kundenakte verwenden"; wrap: true; Layout.fillWidth: true }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                        PText { text: Batch.texts.privacy; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
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
                    Accessible.name: "Filter"
                }
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 8
                    PCheckBox {
                        text: "Alle auswählen"
                        tristate: true
                        wrap: false
                        enabled: Batch.visibleCount > 0
                        checkState: Batch.checkAll === 2 ? Qt.Checked : (Batch.checkAll === 1 ? Qt.PartiallyChecked : Qt.Unchecked)
                        nextCheckState: function() { return checkState }
                        onClicked: Batch.toggleAll()
                    }
                    PText { text: Batch.selectedText; textStyle: "caption"; tone: "secondary"; height: 32; visible: text !== "" }
                    PButton { iconName: "document"; text: "Vorlage anwenden …"; enabled: Batch.selection > 0 && !Batch.running; tip: "Dieselbe Vorlage für alle ausgewählten Einträge setzen"; onClicked: Batch.applyTemplateToSelection() }
                    PButton { iconName: "delete"; text: "Auswahl entfernen"; enabled: Batch.selection > 0 && !Batch.running; tip: "Ausgewählte Einträge aus dem Stapel nehmen (die Dateien bleiben)"; onClicked: Batch.removeSelected() }
                }
                PText { text: Batch.filterEmpty; tone: "secondary"; visible: text !== ""; Layout.topMargin: 12 }
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
            Accessible.name: name + ", " + status + (detail !== "" ? ", " + detail : "")

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
                    Accessible.name: row.name + " auswählen"
                    onClicked: Batch.select(row.id, checked)
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { text: row.name; textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: row.facts; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                    PText { text: row.detail; textStyle: "caption"; tone: row.detailTone === "muted" ? "secondary" : row.detailTone; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                }
                PBadge { text: row.status; tone: row.statusTone === "critical" ? "error" : row.statusTone }
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
                PMenuItem { text: "Eintrag öffnen"; iconName: "open"; onTriggered: Batch.showDetail(row.id) }
                PMenuItem { text: "PDF öffnen"; iconName: "document_pdf"; enabled: row.statusKey === "success" || row.statusKey === "warning"; onTriggered: Batch.openItemPdf(row.id) }
                PMenuItem { text: "Pfad kopieren"; iconName: "copy"; onTriggered: Batch.copyItemPath(row.id) }
                PMenuItem { text: "Aus Stapel entfernen"; iconName: "delete"; enabled: !Batch.running; onTriggered: Batch.removeItem(row.id) }
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
        title: "Vertragsübersichten"
        subtitle: Batch.texts.subtitle
        onVisibleChanged: if (visible) scrollToTop()

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: "Alle Einträge"; tip: "Zurück zur Liste"; onClicked: Batch.showList() }
            Item { Layout.fillWidth: true }
            PIconButton { iconName: "chevron_left"; tip: "Vorheriger Eintrag"; enabled: Batch.canPrev; onClicked: Batch.step(-1) }
            PText { text: Batch.position; textStyle: "caption"; tone: "secondary" }
            PIconButton { iconName: "chevron_right"; tip: "Nächster Eintrag"; enabled: Batch.canNext; onClicked: Batch.step(1) }
        }
        PText { text: Batch.detailTitle; textStyle: "subtitle"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
        PText { text: Batch.detailFolder; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2 }
        PStatusLine { Layout.fillWidth: true; Layout.topMargin: 10; kind: Batch.detailKind; text: Batch.detailText }
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
                title: "Excel-Prüfung"
                iconName: "document_table"
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_excel"); closable: false; topMargin: 0 }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    spacing: 12
                    PText { text: "Rechnungsempfänger"; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150 }
                    PText { text: Batch.mailValue; Layout.fillWidth: true }
                    PComboBox {
                        visible: Batch.mailChoices.length > 1
                        preferredWidth: 210
                        label: "Rechnungsempfänger"
                        tip: "Rechnungsempfänger für diese Übersicht"
                        placeholder: "Empfänger wählen"
                        model: Batch.mailChoices
                        currentIndex: Batch.mailChoices.indexOf(Batch.mailChoice)
                        onActivated: (index) => Batch.pickMail(Batch.mailChoices[index])
                    }
                    PTextField {
                        visible: Batch.mailField
                        preferredWidth: 210
                        label: "Rechnungsempfänger"
                        placeholderText: "E-Mail-Adresse (optional)"
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
                title: "Kunde"
                iconName: "contact_card"
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: Batch.customerParts
                    spacing: 2
                    PText { text: Batch.customerTitle; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                    PText { text: Batch.customerNote; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; visible: text !== "" }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        spacing: 6
                        PButton { iconName: "people"; text: "Kunden auswählen …"; enabled: !Batch.itemRunning; tip: "Bekannten Kunden für diesen Eintrag wählen"; onClicked: Batch.chooseCustomer() }
                        PButton { kind: "subtle"; text: "Ohne Kundenakte"; visible: Batch.customerMode !== "none"; enabled: !Batch.itemRunning; tip: "Diesen Eintrag ohne Kundenakte erstellen – Angaben selbst eintragen"; onClicked: Batch.setCustomerMode("none") }
                        PButton { kind: "subtle"; text: "Automatisch erkennen"; visible: Batch.customerMode !== "auto"; enabled: !Batch.itemRunning; tip: "Kunden wieder über die Rechnungsempfänger erkennen"; onClicked: Batch.setCustomerMode("auto") }
                    }
                }
                PFieldLabel { text: "Firmenname"; first: !Batch.customerParts }
                PTextField { Layout.fillWidth: true; label: "Firmenname"; placeholderText: "z. B. Muster GmbH"; text: Batch.company; invalid: Batch.companyError; onTextEdited: Batch.company = text; onActiveFocusChanged: Batch.setFieldFocus("company", activeFocus) }
                PFieldLabel { text: "Kundennummer" }
                PTextField { Layout.fillWidth: true; label: "Kundennummer"; placeholderText: "z. B. 10042"; text: Batch.number; invalid: Batch.numberError; onTextEdited: Batch.number = text; onActiveFocusChanged: Batch.setFieldFocus("number", activeFocus) }
                PText { text: Batch.valueSource; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4; visible: text !== "" }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("batch_mail_info"); visible: Batch.customerParts && (shown || animating) }
            }
        }

        // Vertragsänderungen (dieselbe Anzeige wie im Einzelmodus)
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            visible: Batch.customerParts
            title: "Vertragsänderungen"
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
            title: "Darstellung und Ausgabe"
            iconName: "document"
            subtitle: Batch.customerParts ? Batch.texts.outputText : Batch.texts.outputTextPlain
            GridLayout {
                Layout.fillWidth: true
                columns: 3
                columnSpacing: 12
                rowSpacing: 6
                PText { text: "Vorlage" }
                PComboBox {
                    preferredWidth: 240
                    label: "Vorlage"
                    tip: "»Automatisch«: Vorlage der Kundenakte, sonst die Vorlage des Stapels, sonst die Standardvorlage"
                    model: Batch.itemTemplateChoices
                    currentIndex: Batch.itemTemplateChoices.indexOf(Batch.itemTemplate)
                    onActivated: (index) => Batch.setItemTemplate(Batch.itemTemplateChoices[index])
                }
                Item { Layout.fillWidth: true }
                PText { text: "Regelwerk" }
                PComboBox {
                    objectName: "itemRuleSet"
                    preferredWidth: 240
                    label: "Regelwerk"
                    tip: "»Automatisch«: Regelwerk der Vorlage, sonst das der »Darstellung«"
                    model: Batch.itemRuleSetChoices
                    currentIndex: Batch.itemRuleSetChoices.indexOf(Batch.itemRuleSet)
                    onActivated: (index) => Batch.setItemRuleSet(Batch.itemRuleSetChoices[index])
                }
                Item { Layout.fillWidth: true }
            }
            PText { text: Batch.templateNote; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "image"
                label: "Logo"
                value: Batch.itemLogoText
                fullPath: Batch.itemLogoPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; onClicked: Batch.pickItemLogo() }
                PIconButton { iconName: "arrow_undo"; tip: "Zurücksetzen (Kundenakte bzw. Stapel)"; enabled: Batch.itemLogoReset; onClicked: Batch.resetItemLogo() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 8; Layout.bottomMargin: 8; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: "Zielordner"
                value: Batch.itemTargetText
                fullPath: Batch.itemTargetPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; onClicked: Batch.pickItemTarget() }
                PIconButton { iconName: "arrow_undo"; tip: "Zurücksetzen (Kundenakte bzw. Stapel)"; enabled: Batch.itemTargetReset; onClicked: Batch.resetItemTarget() }
            }
            PText { text: Batch.outputText; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8; visible: text !== "" }
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 16
            spacing: 8
            PButton { kind: "accent"; iconName: "eye"; text: "Vorschau"; enabled: Batch.canPreview; tip: "Diesen Eintrag in der Vorschau ansehen – dieselbe Vorschau wie im Einzelmodus"; onClicked: Batch.preview() }
            PButton { iconName: "edit"; text: "Einzeln bearbeiten"; tip: "Eintrag in »Übersicht erstellen« übernehmen"; onClicked: Batch.editSingle() }
            PButton { visible: Batch.hasOutput; iconName: "open"; text: "PDF öffnen"; onClicked: Batch.openPdf() }
            PButton { visible: Batch.hasOutput; iconName: "folder_open"; text: "Ordner öffnen"; onClicked: Batch.openFolder() }
            PButton { iconName: "delete"; text: "Aus Stapel entfernen"; tip: "Eintrag aus dem Stapel nehmen – die Datei bleibt"; onClicked: Batch.removeCurrent() }
        }
    }
}
