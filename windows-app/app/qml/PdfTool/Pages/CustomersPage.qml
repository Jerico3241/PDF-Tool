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
        title: "Vertragsübersichten"
        subtitle: "Kundenakten: bekannte Kunden verwalten und in Übersichten wiederverwenden."
        model: Customers.listModel
        Accessible.role: Accessible.List
        Accessible.name: "Kundenakten"
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
                        label: "Kundenakten durchsuchen"
                        placeholderText: "Firma, Kundennummer oder E-Mail suchen"
                        text: Customers.search
                        onTextEdited: Customers.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Customers.showDetail(Customers.listModel.get(0).id)
                    }
                }
                Row {
                    spacing: 8
                    PText { text: "Sortierung"; height: 32; leftPadding: 8 }
                    PComboBox {
                        preferredWidth: 180
                        label: "Sortierung"
                        tip: "Reihenfolge der Kundenliste"
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
                PButton { iconName: "person_add"; text: "Neue Kundenakte"; tip: "Kundenakte manuell anlegen"; onClicked: Customers.newCustomer() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: Customers.texts.privacy; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
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
                    PText { text: Customers.texts.emptyTitle; textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: Customers.texts.emptyText; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PButton { kind: "accent"; iconName: "document"; text: "Zur Vertragsübersicht"; Layout.topMargin: 10; onClicked: App.navigate("create") }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Customers.total > 0 && !Customers.listShown
                text: Customers.countText
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
            Accessible.name: company + ", " + subtitle
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
                    PText { text: row.company; textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: row.subtitle; textStyle: "caption"; tone: "secondary"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                }
                PBadge { text: row.active ? "aktiv" : ""; tone: "accent" }
                PText { text: row.when; textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 420 && text !== "" }
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
                text: Customers.countText
                textStyle: "caption"
                tone: "secondary"
                wrap: true
            }
            PSettingsCard {
                Layout.fillWidth: true
                Layout.topMargin: 16
                iconName: "arrow_sync"
                title: "Bekannte Kunden automatisch übernehmen"
                description: "Erkennt PDF Tool nach der Excel-Prüfung genau einen bekannten Kunden und sind noch keine Kundendaten eingetragen, werden sie ohne Nachfrage übernommen (rückgängig machbar). Standard: aus."
                PToggle {
                    label: "Bekannte Kunden automatisch übernehmen"
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
        title: "Vertragsübersichten"
        subtitle: "Kundenakten: bekannte Kunden verwalten und in Übersichten wiederverwenden."

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: "Alle Kunden"; tip: "Zurück zur Kundenliste"; onClicked: Customers.showList() }
        }
        PText { text: Customers.detailTitle; textStyle: "subtitle"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
        PText { text: Customers.detailCaption; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2 }
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
                title: "Stammdaten"
                iconName: "contact_card"
                PFieldLabel { text: "Firmenname"; first: true }
                PTextField {
                    id: fieldCompany
                    Layout.fillWidth: true
                    label: "Firmenname"
                    placeholderText: "z. B. Muster GmbH"
                    text: Customers.company
                    invalid: Customers.companyError
                    onTextEdited: Customers.company = text
                }
                PFieldLabel { text: "Kundennummer" }
                PTextField {
                    Layout.fillWidth: true
                    label: "Kundennummer"
                    placeholderText: "z. B. 10042"
                    text: Customers.number
                    onTextEdited: Customers.number = text
                }
                PFieldLabel { text: "Notiz (optional)" }
                PTextArea {
                    id: noteArea
                    Layout.fillWidth: true
                    label: "Notiz"
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
                title: "Rechnungsempfänger"
                iconName: "mail"
                subtitle: "Adressen, an denen PDF Tool diesen Kunden in einer Excel-Liste wiedererkennt."
                PText {
                    Layout.fillWidth: true
                    visible: Customers.emailModel.count === 0
                    text: "Keine E-Mail zugeordnet. Die Kundenakte kann weiterhin manuell ausgewählt werden."
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
                            PText { text: email; elide: Text.ElideMiddle; Layout.fillWidth: true }
                            PBadge { text: primary ? "primär" : ""; tone: "accent" }
                            PText { text: ambiguous ? "auch anderen Kundenakten zugeordnet" : ""; textStyle: "caption"; tone: "warning"; visible: ambiguous }
                            PIconButton { iconName: "chevron_up"; tip: "Als primäre Adresse festlegen"; visible: !primary; onClicked: Customers.makePrimary(email) }
                            PIconButton { iconName: "delete"; tip: email + " entfernen"; onClicked: Customers.removeEmail(email) }
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
                        label: "Weitere E-Mail-Adresse"
                        placeholderText: "weitere E-Mail-Adresse"
                        text: Customers.newEmail
                        invalid: Customers.emailError
                        onTextEdited: Customers.newEmail = text
                        onSubmitted: Customers.addEmail()
                    }
                    PButton { iconName: "add"; text: "E-Mail hinzufügen"; onClicked: Customers.addEmail() }
                }
                PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunde_mail_info") }
            }
        }

        // Einstellungen
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: "Einstellungen für Vertragsübersichten"
            iconName: "settings"
            subtitle: "Werden beim Übernehmen des Kunden verwendet – fehlt eine Datei, bleibt der aktuelle Wert."
            PFileRow {
                Layout.fillWidth: true
                iconName: "image"
                label: "Bevorzugtes Logo"
                value: Customers.logoText
                fullPath: Customers.logoPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; onClicked: Customers.pickLogo() }
                PIconButton { iconName: "dismiss"; tip: "Kein bevorzugtes Logo"; onClicked: Customers.clearLogo() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: "Bevorzugter Zielordner"
                value: Customers.targetText
                fullPath: Customers.targetPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; onClicked: Customers.pickTarget() }
                PIconButton { iconName: "dismiss"; tip: "Kein bevorzugter Zielordner"; onClicked: Customers.clearTarget() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFieldLabel { text: "Bevorzugte Vorlage"; first: true }
            Flow {
                Layout.fillWidth: true
                spacing: 16
                PComboBox {
                    preferredWidth: 240
                    label: "Bevorzugte Vorlage"
                    tip: "Vorlage aus »Darstellung«"
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
                        label: "Vorlage automatisch verwenden"
                        checked: Customers.templateAuto
                        onToggled: Customers.setTemplateAuto(checked)
                    }
                    PText { text: "Vorlage automatisch verwenden"; anchors.verticalCenter: parent.verticalCenter }
                }
            }
        }

        // Dokumentdarstellung
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: "Dokumentdarstellung"
            iconName: "document"
            subtitle: "Eigene Kopf- und Fußzeile dieses Kunden (mit Formatierung). Ohne eigene Fußzeile bleibt die gültige – nie eine leere."
            PFactList { Layout.fillWidth: true; labelWidth: 110; facts: Customers.textFacts }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 10
                spacing: 8
                PButton { iconName: "save"; text: "Aktuelle Kopf- und Fußzeile übernehmen"; tip: "Kopf- und Fußzeile aus »Darstellung« in dieser Kundenakte speichern"; onClicked: Customers.takeTexts() }
                PButton { iconName: "dismiss"; text: "Eigene entfernen"; onClicked: Customers.clearTexts() }
            }
        }

        // Letzte Aktivität
        PCard {
            Layout.fillWidth: true
            Layout.topMargin: 12
            title: "Letzte Aktivität"
            iconName: "history"
            PFileRow {
                Layout.fillWidth: true
                iconName: "document_table"
                label: "Letzte Excel-Liste"
                value: Customers.excelText
                fullPath: Customers.excelPath
                PButton { visible: Customers.excelAvailable; text: "Als Quelle verwenden"; iconName: "folder_open"; tip: "Kunden übernehmen und diese Excel neu prüfen"; onClicked: Customers.useLastExcel() }
                PIconButton { visible: Customers.excelAvailable; iconName: "open"; tip: "Excel öffnen"; onClicked: Customers.openLastExcel() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "document_pdf"
                label: "Zuletzt erstellte Übersicht"
                value: Customers.pdfText
                fullPath: Customers.pdfPath
                PButton { visible: Customers.pdfAvailable; text: "Ordner öffnen"; iconName: "folder_open"; onClicked: Customers.openLastPdfFolder() }
                PIconButton { visible: Customers.pdfAvailable; iconName: "open"; tip: "PDF öffnen"; onClicked: Customers.openLastPdf() }
            }
            PFactList { Layout.fillWidth: true; Layout.topMargin: 12; facts: Customers.activity }
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 16
            spacing: 8
            PButton { kind: "accent"; iconName: "checkmark"; text: "In Vertragsübersicht übernehmen"; tip: "Kundendaten in »Übersicht erstellen« übernehmen"; onClicked: Customers.applyDetail() }
            PButton { iconName: "merge"; text: "Zusammenführen …"; tip: "Eine doppelte Kundenakte in diese übernehmen"; onClicked: Customers.merge() }
            PButton { iconName: "delete"; text: "Kundenakte löschen"; tip: "Löscht nur die Kundenakte – keine PDF- oder Excel-Dateien"; onClicked: Customers.deleteRecord() }
        }
    }
}
