import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Vorlagen«: gespeicherte Darstellungen suchen, ansehen, anwenden,
// umbenennen, duplizieren, als Standard festlegen und löschen. Bearbeitet wird eine Vorlage in der
// »Darstellung« (laden → ändern → »Vorlage aktualisieren«). Liste und Detail blenden ineinander über.
Item {
    id: root
    objectName: "templatesPage"
    readonly property bool detail: Templates.detailId !== ""

    Connections {
        target: Templates
        function onFocusRequested(field) {
            if (field === "search") {
                listPage.positionViewAtBeginning()
                Qt.callLater(function() { if (listPage.headerContentItem) listPage.headerContentItem.focusSearch() })
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
        subtitle: I18n.tr("Vorlagen: eine Darstellung einmal einrichten und mit einem Klick wiederverwenden.", I18n.revision)
        model: Templates.listModel
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Vorlagen", I18n.revision)
        Keys.onReturnPressed: if (currentIndex >= 0) Templates.showDetail(model.get(currentIndex).id)
        Keys.onEnterPressed: if (currentIndex >= 0) Templates.showDetail(model.get(currentIndex).id)
        Keys.onSpacePressed: if (currentIndex >= 0) Templates.showDetail(model.get(currentIndex).id)
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
                        objectName: "templateSearch"
                        preferredWidth: 300
                        label: I18n.tr("Vorlagen durchsuchen", I18n.revision)
                        placeholderText: I18n.tr("Name oder Beschreibung suchen", I18n.revision)
                        text: Templates.search
                        onTextEdited: Templates.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Templates.showDetail(Templates.listModel.get(0).id)
                    }
                }
                PButton { iconName: "save"; text: I18n.tr("Aktuelle Darstellung speichern …", I18n.revision); tip: I18n.tr("Die aktuelle Darstellung als neue Vorlage speichern", I18n.revision); onClicked: Templates.createFromCurrent() }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                text: I18n.tr(Templates.texts.editHint, I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                wrap: true
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_verwaltung") }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: text !== ""
                text: I18n.tr(Templates.problemsText, I18n.revision)
                textStyle: "caption"
                tone: "warning"
                wrap: true
            }
            // Noch keine Vorlage
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Templates.total === 0
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
                    PIcon { name: "library"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                    PText { text: I18n.tr(Templates.texts.emptyTitle, I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: I18n.tr(Templates.texts.emptyText, I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PButton { kind: "accent"; iconName: "save"; text: I18n.tr("Aktuelle Darstellung speichern …", I18n.revision); onClicked: Templates.createFromCurrent() }
                        PButton { iconName: "document"; text: I18n.tr("Zur Darstellung", I18n.revision); onClicked: App.navigate("layout") }
                    }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Templates.total > 0
                text: I18n.tr(Templates.countText, I18n.revision)
                tone: "secondary"
                wrap: true
            }
            Item { implicitHeight: listPage.count > 0 ? 12 : 0 }
        }

        // Karte hinter den Zeilen
        Rectangle {
            parent: listPage.contentItem
            z: -1
            x: listPage.columnX
            y: -8
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
            required property string name
            required property string description
            required property bool standard
            required property bool loaded
            required property bool modified
            required property string updated
            width: listPage.width
            height: 60
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(name + (standard ? ", Standardvorlage" : "") + (loaded ? ", geladen" : ""), I18n.revision)
            PListItem {
                x: listPage.columnX + 6
                y: 2
                width: listPage.columnWidth - 12
                height: row.height - 4
                hovered: mouse.containsMouse
                pressed: mouse.pressed
                selected: row.loaded
                focused: listPage.activeFocus && listPage.currentIndex === row.index
            }
            Rectangle {
                visible: row.index > 0
                x: listPage.columnX + 14
                width: listPage.columnWidth - 28
                height: 1
                color: Theme.divider
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { listPage.currentIndex = row.index; Templates.showDetail(row.id) }
            }
            RowLayout {
                x: listPage.columnX + 20
                width: listPage.columnWidth - 32
                height: row.height
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { text: I18n.tr(row.name, I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: I18n.tr(row.description, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                }
                PBadge { text: I18n.tr(row.standard ? "Standard" : "", I18n.revision); tone: "accent" }
                PBadge { text: I18n.tr(row.loaded ? (row.modified ? "geladen · geändert" : "geladen") : "", I18n.revision); tone: row.modified ? "caution" : "success" }
                PText { text: I18n.tr(row.updated, I18n.revision); textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 560 && text !== "" }
                PIconButton { iconName: "checkmark"; tip: I18n.tr("„" + row.name + "“ in die Darstellung laden", I18n.revision); onClicked: Templates.apply(row.id) }
                PIcon { name: "chevron_right"; size: 12; color: Theme.textSecondary }
            }
        }

        footerContent: ColumnLayout {
            spacing: 0
            Item { implicitHeight: 4 }
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
        subtitle: I18n.tr("Vorlagen: eine Darstellung einmal einrichten und mit einem Klick wiederverwenden.", I18n.revision)

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: I18n.tr("Alle Vorlagen", I18n.revision); tip: I18n.tr("Zurück zur Liste der Vorlagen", I18n.revision); onClicked: Templates.showList() }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PText { objectName: "templateDetailName"; text: I18n.tr(Templates.detailName, I18n.revision); textStyle: "subtitle"; elide: Text.ElideRight; Layout.fillWidth: true }
            PBadge { text: I18n.tr(Templates.detailDefault ? "Standard" : "", I18n.revision); tone: "accent" }
            PBadge { text: I18n.tr(Templates.detailLoaded ? (Templates.detailModified ? "geladen · geändert" : "geladen") : "", I18n.revision); tone: Templates.detailModified ? "caution" : "success" }
        }
        PText { text: I18n.tr(Templates.detailCaption, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_verwaltung") }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PButton { objectName: "applyTemplate"; kind: "accent"; iconName: "checkmark"; text: I18n.tr("In die Darstellung laden", I18n.revision); tip: I18n.tr("Logo, Format, Texte und Regeln dieser Vorlage übernehmen", I18n.revision); onClicked: Templates.apply(Templates.detailId) }
            PButton { iconName: "edit"; text: I18n.tr("Laden und bearbeiten", I18n.revision); tip: I18n.tr("Vorlage laden und in der »Darstellung« ändern – danach »Vorlage aktualisieren«", I18n.revision); onClicked: Templates.edit(Templates.detailId) }
            PButton { iconName: "text_font"; text: I18n.tr("Umbenennen …", I18n.revision); onClicked: Templates.rename(Templates.detailId) }
            PButton { iconName: "copy"; text: I18n.tr("Duplizieren", I18n.revision); onClicked: Templates.duplicate(Templates.detailId) }
            PButton { iconName: "delete"; text: I18n.tr("Löschen", I18n.revision); tip: I18n.tr("Vorlage löschen – Kundenakten und Stapel verwenden sie danach nicht mehr", I18n.revision); onClicked: Templates.remove(Templates.detailId) }
        }

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
                title: I18n.tr("Inhalt", I18n.revision)
                iconName: "document"
                subtitle: I18n.tr("Was diese Vorlage beim Laden setzt. Nicht festgelegte Werte bleiben, wie sie sind.", I18n.revision)
                PFactList { Layout.fillWidth: true; labelWidth: 120; facts: Templates.detailFacts }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 12
                PCard {
                    Layout.fillWidth: true
                    title: I18n.tr("Beschreibung", I18n.revision)
                    iconName: "text_align_left"
                    PTextArea {
                        id: descriptionArea
                        objectName: "templateDescription"
                        Layout.fillWidth: true
                        label: I18n.tr("Beschreibung der Vorlage", I18n.revision)
                        placeholderText: I18n.tr("Wofür ist diese Vorlage? (optional)", I18n.revision)
                        minLines: 2
                        Connections {
                            target: Templates
                            function onDetailDescriptionChanged() { if (!descriptionArea.area.activeFocus && descriptionArea.text !== Templates.detailDescription) descriptionArea.text = Templates.detailDescription }
                            function onDetailIdChanged() { descriptionArea.text = Templates.detailDescription }
                        }
                        Component.onCompleted: text = Templates.detailDescription
                        onEdited: Templates.setDescription(Templates.detailId, text)
                    }
                }
                PCard {
                    Layout.fillWidth: true
                    title: I18n.tr("Verwendung", I18n.revision)
                    iconName: "link"
                    PText {
                        visible: Templates.detailUses.length === 0
                        text: I18n.tr("Wird derzeit nirgends verwendet.", I18n.revision)
                        tone: "secondary"
                        wrap: true
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: Templates.detailUses
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 8
                            PIcon { name: "checkmark"; size: 12; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4 }
                            PText { text: I18n.tr(modelData, I18n.revision); wrap: true; Layout.fillWidth: true }
                        }
                    }
                }
                PSettingsCard {
                    Layout.fillWidth: true
                    iconName: "checkmark_circle"
                    title: I18n.tr("Standardvorlage", I18n.revision)
                    description: I18n.tr("Wird für jede neue Übersicht geladen – und im Stapel für Einträge ohne andere Vorlage verwendet.", I18n.revision)
                    PToggle {
                        objectName: "templateDefault"
                        label: I18n.tr("Standardvorlage", I18n.revision)
                        checked: Templates.detailDefault
                        onToggled: Templates.setDefault(Templates.detailId, checked)
                    }
                }
            }
        }
    }
}
