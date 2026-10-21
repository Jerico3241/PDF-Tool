import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Kunden« (nur mit Kundenakte): Kundenakten suchen, ansehen, bearbeiten,
// zusammenführen. Die Liste ist virtualisiert; Liste und Detail blenden ineinander über.
Item {
    id: root
    objectName: "customersPage"
    readonly property bool detail: Customers.detailId !== ""

    Connections {
        target: Customers
        function onFocusRequested(field) {
            if (field === "search") {
                listPage.positionViewAtBeginning()
                Qt.callLater(function() { if (listPage.headerContentItem) listPage.headerContentItem.focusSearch() })
            } else if (field === "company") {
                detailPage.scrollToTop()
                Qt.callLater(function() { fieldCompany.forceActiveFocus(Qt.OtherFocusReason) })
            }
        }
    }

    // Liste ------------------------------------------------------------------------------------------
    PListPage {
        id: listPage
        anchors.fill: parent
        opacity: root.detail ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr("Kundenakten: bekannte Kunden verwalten und in Übersichten wiederverwenden.", I18n.revision)
        model: Customers.listModel
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Kundenakten", I18n.revision)
        Keys.onReturnPressed: if (currentIndex >= 0) Customers.showDetail(model.get(currentIndex).id)
        Keys.onEnterPressed: if (currentIndex >= 0) Customers.showDetail(model.get(currentIndex).id)
        Keys.onSpacePressed: if (currentIndex >= 0) Customers.showDetail(model.get(currentIndex).id)
        onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0

        headerContent: ColumnLayout {
            spacing: 0
            function focusSearch() { searchField.forceActiveFocus(Qt.OtherFocusReason) }
            ContractViews {}
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Row {
                    spacing: 8
                    PIcon { name: "search"; color: Theme.textSecondary; anchors.verticalCenter: parent.verticalCenter }
                    PTextField {
                        id: searchField
                        objectName: "customerSearch"
                        preferredWidth: 300
                        label: I18n.tr("Kundenakten durchsuchen", I18n.revision)
                        placeholderText: I18n.tr("Firma, Kundennummer oder E-Mail suchen", I18n.revision)
                        text: Customers.search
                        onTextEdited: Customers.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Customers.showDetail(Customers.listModel.get(0).id)
                    }
                }
                Row {
                    spacing: 8
                    PText { text: I18n.tr("Sortierung", I18n.revision); height: 32; leftPadding: 8 }
                    PComboBox {
                        preferredWidth: 180
                        label: I18n.tr("Sortierung", I18n.revision)
                        tip: I18n.tr("Reihenfolge der Kundenliste", I18n.revision)
                        model: Customers.orders
                        textRole: "label"
                        valueRole: "value"
                        currentIndex: {
                            for (var i = 0; i < Customers.orders.length; ++i)
                                if (Customers.orders[i].value === Customers.order) return i
                            return 0
                        }
                        onActivated: (index) => Customers.setOrder(Customers.orders[index].value)
                    }
                }
                PButton { iconName: "person_add"; text: I18n.tr("Neue Kundenakte", I18n.revision); tip: I18n.tr("Kundenakte manuell anlegen", I18n.revision); onClicked: Customers.newCustomer() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: I18n.tr(Customers.texts.privacy, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunden_info") }
            // Noch keine Kundenakten
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Customers.total === 0
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
                    PIcon { name: "people"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                    PText { text: I18n.tr(Customers.texts.emptyTitle, I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: I18n.tr(Customers.texts.emptyText, I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PButton { kind: "accent"; iconName: "document"; text: I18n.tr("Zur Vertragsübersicht", I18n.revision); Layout.topMargin: 10; onClicked: App.navigate("create") }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Customers.total > 0 && !Customers.listShown
                text: I18n.tr(Customers.countText, I18n.revision)
                tone: "secondary"
                wrap: true
            }
            Item { implicitHeight: Customers.listShown ? 12 : 0 }
        }

        // Karte hinter den Zeilen
        Rectangle {
            parent: listPage.contentItem
            z: -1
            x: listPage.columnX
            y: -8  // die erste Zeile beginnt bei 0, der Kopfbereich liegt darüber
            width: listPage.columnWidth
            height: listPage.count * 60 + 16
            visible: listPage.count > 0
            radius: Metrics.radiusCard
            color: Theme.surface
            border.color: Theme.border
        }

        delegate: Item {
            id: row
            required property int index
            required property string id
            required property string company
            required property string subtitle
            required property string when
            required property bool active
            width: listPage.width
            height: 60
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(company + ", " + subtitle, I18n.revision)
            PListItem {
                x: listPage.columnX + 6
                y: 2
                width: listPage.columnWidth - 12
                height: row.height - 4
                hovered: mouse.containsMouse
                pressed: mouse.pressed
                selected: row.active
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
                x: listPage.columnX + 20
                width: listPage.columnWidth - 40
                height: row.height
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { text: I18n.tr(row.company, I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: I18n.tr(row.subtitle, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                }
                PBadge { text: I18n.tr(row.active ? "aktiv" : "", I18n.revision); tone: "accent" }
                PText { text: I18n.tr(row.when, I18n.revision); textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 420 && text !== "" }
                PIcon { name: "chevron_right"; size: 12; color: Theme.textSecondary }
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { listPage.currentIndex = row.index; Customers.showDetail(row.id) }
            }
        }

        footerContent: ColumnLayout {
            spacing: 0
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 14
                visible: Customers.listShown
                text: I18n.tr(Customers.countText, I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                wrap: true
            }
            PSettingsCard {
                Layout.fillWidth: true
                Layout.topMargin: 16
                iconName: "arrow_sync"
                title: I18n.tr("Bekannte Kunden automatisch übernehmen", I18n.revision)
                description: I18n.tr("Erkennt Novadesk nach der Excel-Prüfung genau einen bekannten Kunden und sind noch keine Kundendaten eingetragen, werden sie ohne Nachfrage übernommen (rückgängig machbar). Standard: aus.", I18n.revision)
                PToggle {
                    label: I18n.tr("Bekannte Kunden automatisch übernehmen", I18n.revision)
                    checked: Customers.autoApply
                    onToggled: Customers.autoApply = checked
                }
            }
        }
    }

    // Detail -------------------------------------------------------------------------------------------
    PPage {
        id: detailPage
        anchors.fill: parent
        opacity: root.detail ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr("Kundenakten: bekannte Kunden verwalten und in Übersichten wiederverwenden.", I18n.revision)

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: I18n.tr("Alle Kunden", I18n.revision); tip: I18n.tr("Zurück zur Kundenliste", I18n.revision); onClicked: Customers.showList() }
        }
        PText { text: I18n.tr(Customers.detailTitle, I18n.revision); textStyle: "subtitle"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
        PText { text: I18n.tr(Customers.detailCaption, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2 }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunde_detail_info") }

        GridLayout {
            Layout.fillWidth: true
            Layout.topMargin: 12
            columns: detailPage.columns
            columnSpacing: 12
            rowSpacing: 12

            // Stammdaten
            PCard {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                title: I18n.tr("Stammdaten", I18n.revision)
                iconName: "contact_card"
                PFieldLabel { text: I18n.tr("Firmenname", I18n.revision); first: true }
                PTextField {
                    id: fieldCompany
                    Layout.fillWidth: true
                    label: I18n.tr("Firmenname", I18n.revision)
                    placeholderText: I18n.tr("z. B. Muster GmbH", I18n.revision)
                    text: Customers.company
                    invalid: Customers.companyError
                    onTextEdited: Customers.company = text
                }
                PFieldLabel { text: I18n.tr("Kundennummer", I18n.revision) }
                PTextField {
                    Layout.fillWidth: true
                    label: I18n.tr("Kundennummer", I18n.revision)
                    placeholderText: I18n.tr("z. B. 10042", I18n.revision)
                    text: Customers.number
                    onTextEdited: Customers.number = text
                }
                PFieldLabel { text: I18n.tr("Notiz (optional)", I18n.revision) }
                PTextArea {
                    id: noteArea
                    Layout.fillWidth: true
                    label: I18n.tr("Notiz", I18n.revision)
                    minLines: 3
                    Connections {
                        target: Customers
                        function onNoteChanged() { if (!noteArea.area.activeFocus && noteArea.text !== Customers.note) noteArea.text = Customers.note }
                    }
                    Component.onCompleted: text = Customers.note
                    onEdited: Customers.note = text
                }
            }

            // Rechnungsempfänger
            PCard {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                title: I18n.tr("Rechnungsempfänger", I18n.revision)
                iconName: "mail"
                subtitle: I18n.tr("Adressen, an denen Novadesk diesen Kunden in einer Excel-Liste wiedererkennt.", I18n.revision)
                PText {
                    Layout.fillWidth: true
                    visible: Customers.emailModel.count === 0
                    text: I18n.tr("Keine E-Mail zugeordnet. Die Kundenakte kann weiterhin manuell ausgewählt werden.", I18n.revision)
                    tone: "secondary"
                    wrap: true
                }
                Repeater {
                    model: Customers.emailModel
                    Rectangle {
                        required property int index
                        required property string email
                        required property bool primary
                        required property bool ambiguous
                        Layout.fillWidth: true
                        Layout.topMargin: index === 0 ? 0 : 4
                        implicitHeight: 40
                        radius: Metrics.radiusControl
                        color: Theme.surfaceSecondary
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 4
                            spacing: 10
                            PText { text: I18n.tr(email, I18n.revision); elide: Text.ElideMiddle; Layout.fillWidth: true }
                            PBadge { text: I18n.tr(primary ? "primär" : "", I18n.revision); tone: "accent" }
                            PText { text: I18n.tr(ambiguous ? "auch anderen Kundenakten zugeordnet" : "", I18n.revision); textStyle: "caption"; tone: "warning"; visible: ambiguous }
                            PIconButton { iconName: "chevron_up"; tip: I18n.tr("Als primäre Adresse festlegen", I18n.revision); visible: !primary; onClicked: Customers.makePrimary(email) }
                            PIconButton { iconName: "delete"; tip: I18n.tr(email + " entfernen", I18n.revision); onClicked: Customers.removeEmail(email) }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 10
                    spacing: 8
                    PTextField {
                        Layout.fillWidth: true
                        preferredWidth: 220
                        label: I18n.tr("Weitere E-Mail-Adresse", I18n.revision)
                        placeholderText: I18n.tr("weitere E-Mail-Adresse", I18n.revision)
                        text: Customers.newEmail
                        invalid: Customers.emailError
                        onTextEdited: Customers.newEmail = text
                        onSubmitted: Customers.addEmail()
                    }
                    PButton { iconName: "add"; text: I18n.tr("E-Mail hinzufügen", I18n.revision); onClicked: Customers.addEmail() }
                }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunde_mail_info") }
            }
        }

        // Einstellungen
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: I18n.tr("Einstellungen für Vertragsübersichten", I18n.revision)
            iconName: "settings"
            subtitle: I18n.tr("Werden beim Übernehmen des Kunden verwendet – fehlt eine Datei, bleibt der aktuelle Wert.", I18n.revision)
            PFileRow {
                Layout.fillWidth: true
                iconName: "image"
                label: I18n.tr("Bevorzugtes Logo", I18n.revision)
                value: Customers.logoText
                fullPath: Customers.logoPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; onClicked: Customers.pickLogo() }
                PIconButton { iconName: "dismiss"; tip: I18n.tr("Kein bevorzugtes Logo", I18n.revision); onClicked: Customers.clearLogo() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: I18n.tr("Bevorzugter Zielordner", I18n.revision)
                value: Customers.targetText
                fullPath: Customers.targetPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; onClicked: Customers.pickTarget() }
                PIconButton { iconName: "dismiss"; tip: I18n.tr("Kein bevorzugter Zielordner", I18n.revision); onClicked: Customers.clearTarget() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFieldLabel { text: I18n.tr("Bevorzugte Vorlage", I18n.revision); first: true }
            Flow {
                Layout.fillWidth: true
                spacing: 16
                PComboBox {
                    preferredWidth: 240
                    label: I18n.tr("Bevorzugte Vorlage", I18n.revision)
                    tip: I18n.tr("Vorlage aus »Darstellung«", I18n.revision)
                    model: Customers.templateChoices
                    currentIndex: Customers.templateChoices.indexOf(Customers.templateValue)
                    onActivated: (index) => Customers.setTemplate(Customers.templateChoices[index])
                }
                Row {
                    spacing: 8
                    height: 32
                    PToggle {
                        anchors.verticalCenter: parent.verticalCenter
                        showState: false
                        label: I18n.tr("Vorlage automatisch verwenden", I18n.revision)
                        checked: Customers.templateAuto
                        onToggled: Customers.setTemplateAuto(checked)
                    }
                    PText { text: I18n.tr("Vorlage automatisch verwenden", I18n.revision); anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }

        // Dokumentdarstellung
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: I18n.tr("Dokumentdarstellung", I18n.revision)
            iconName: "document"
            subtitle: I18n.tr("Eigene Kopf- und Fußzeile dieses Kunden (mit Formatierung). Ohne eigene Fußzeile bleibt die gültige – nie eine leere.", I18n.revision)
            PFactList { Layout.fillWidth: true; labelWidth: 110; facts: Customers.textFacts }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 10
                spacing: 8
                PButton { iconName: "save"; text: I18n.tr("Aktuelle Kopf- und Fußzeile übernehmen", I18n.revision); tip: I18n.tr("Kopf- und Fußzeile aus »Darstellung« in dieser Kundenakte speichern", I18n.revision); onClicked: Customers.takeTexts() }
                PButton { iconName: "dismiss"; text: I18n.tr("Eigene entfernen", I18n.revision); onClicked: Customers.clearTexts() }
            }
        }

        // Letzte Aktivität
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: I18n.tr("Letzte Aktivität", I18n.revision)
            iconName: "history"
            PFileRow {
                Layout.fillWidth: true
                iconName: "document_table"
                label: I18n.tr("Letzte Excel-Liste", I18n.revision)
                value: Customers.excelText
                fullPath: Customers.excelPath
                PButton { visible: Customers.excelAvailable; text: I18n.tr("Als Quelle verwenden", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Kunden übernehmen und diese Excel neu prüfen", I18n.revision); onClicked: Customers.useLastExcel() }
                PIconButton { visible: Customers.excelAvailable; iconName: "open"; tip: I18n.tr("Excel öffnen", I18n.revision); onClicked: Customers.openLastExcel() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "document_pdf"
                label: I18n.tr("Zuletzt erstellte Übersicht", I18n.revision)
                value: Customers.pdfText
                fullPath: Customers.pdfPath
                PButton { visible: Customers.pdfAvailable; text: I18n.tr("Ordner öffnen", I18n.revision); iconName: "folder_open"; onClicked: Customers.openLastPdfFolder() }
                PIconButton { visible: Customers.pdfAvailable; iconName: "open"; tip: I18n.tr("PDF öffnen", I18n.revision); onClicked: Customers.openLastPdf() }
            }
            PFactList { Layout.fillWidth: true; Layout.topMargin: 12; facts: Customers.activity }
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 16
            spacing: 8
            PButton { kind: "accent"; iconName: "checkmark"; text: I18n.tr("In Vertragsübersicht übernehmen", I18n.revision); tip: I18n.tr("Kundendaten in »Übersicht erstellen« übernehmen", I18n.revision); onClicked: Customers.applyDetail() }
            PButton { iconName: "merge"; text: I18n.tr("Zusammenführen …", I18n.revision); tip: I18n.tr("Eine doppelte Kundenakte in diese übernehmen", I18n.revision); onClicked: Customers.merge() }
            PButton { iconName: "delete"; text: I18n.tr("Kundenakte löschen", I18n.revision); tip: I18n.tr("Löscht nur die Kundenakte – keine PDF- oder Excel-Dateien", I18n.revision); onClicked: Customers.deleteRecord() }
        }
    }
}
