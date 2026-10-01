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
        title: "Vertragsübersichten"
        subtitle: "Vorlagen: eine Darstellung einmal einrichten und mit einem Klick wiederverwenden."
        model: Templates.listModel
        Accessible.role: Accessible.List
        Accessible.name: "Vorlagen"
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
                        label: "Vorlagen durchsuchen"
                        placeholderText: "Name oder Beschreibung suchen"
                        text: Templates.search
                        onTextEdited: Templates.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Templates.showDetail(Templates.listModel.get(0).id)
                    }
                }
                PButton { iconName: "save"; text: "Aktuelle Darstellung speichern …"; tip: "Die aktuelle Darstellung als neue Vorlage speichern"; onClicked: Templates.createFromCurrent() }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                text: Templates.texts.editHint
                textStyle: "caption"
                tone: "secondary"
                wrap: true
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_verwaltung") }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: text !== ""
                text: Templates.problemsText
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
                    PText { text: Templates.texts.emptyTitle; textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: Templates.texts.emptyText; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PButton { kind: "accent"; iconName: "save"; text: "Aktuelle Darstellung speichern …"; onClicked: Templates.createFromCurrent() }
                        PButton { iconName: "document"; text: "Zur Darstellung"; onClicked: App.navigate("layout") }
                    }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Templates.total > 0
                text: Templates.countText
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
            Accessible.name: name + (standard ? ", Standardvorlage" : "") + (loaded ? ", geladen" : "")
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
                    PText { text: row.name; textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: row.description; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; visible: text !== "" }
                }
                PBadge { text: row.standard ? "Standard" : ""; tone: "accent" }
                PBadge { text: row.loaded ? (row.modified ? "geladen · geändert" : "geladen") : ""; tone: row.modified ? "caution" : "success" }
                PText { text: row.updated; textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 560 && text !== "" }
                PIconButton { iconName: "checkmark"; tip: "„" + row.name + "“ in die Darstellung laden"; onClicked: Templates.apply(row.id) }
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
        title: "Vertragsübersichten"
        subtitle: "Vorlagen: eine Darstellung einmal einrichten und mit einem Klick wiederverwenden."

        ContractViews {}
        RowLayout {
            Layout.fillWidth: true
            PButton { kind: "subtle"; iconName: "arrow_left"; text: "Alle Vorlagen"; tip: "Zurück zur Liste der Vorlagen"; onClicked: Templates.showList() }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PText { objectName: "templateDetailName"; text: Templates.detailName; textStyle: "subtitle"; elide: Text.ElideRight; Layout.fillWidth: true }
            PBadge { text: Templates.detailDefault ? "Standard" : ""; tone: "accent" }
            PBadge { text: Templates.detailLoaded ? (Templates.detailModified ? "geladen · geändert" : "geladen") : ""; tone: Templates.detailModified ? "caution" : "success" }
        }
        PText { text: Templates.detailCaption; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_verwaltung") }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PButton { objectName: "applyTemplate"; kind: "accent"; iconName: "checkmark"; text: "In die Darstellung laden"; tip: "Logo, Format, Texte und Regeln dieser Vorlage übernehmen"; onClicked: Templates.apply(Templates.detailId) }
            PButton { iconName: "edit"; text: "Laden und bearbeiten"; tip: "Vorlage laden und in der »Darstellung« ändern – danach »Vorlage aktualisieren«"; onClicked: Templates.edit(Templates.detailId) }
            PButton { iconName: "text_font"; text: "Umbenennen …"; onClicked: Templates.rename(Templates.detailId) }
            PButton { iconName: "copy"; text: "Duplizieren"; onClicked: Templates.duplicate(Templates.detailId) }
            PButton { iconName: "delete"; text: "Löschen"; tip: "Vorlage löschen – Kundenakten und Stapel verwenden sie danach nicht mehr"; onClicked: Templates.remove(Templates.detailId) }
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
                title: "Inhalt"
                iconName: "document"
                subtitle: "Was diese Vorlage beim Laden setzt. Nicht festgelegte Werte bleiben, wie sie sind."
                PFactList { Layout.fillWidth: true; labelWidth: 120; facts: Templates.detailFacts }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 12
                PCard {
                    Layout.fillWidth: true
                    title: "Beschreibung"
                    iconName: "text_align_left"
                    PTextArea {
                        id: descriptionArea
                        objectName: "templateDescription"
                        Layout.fillWidth: true
                        label: "Beschreibung der Vorlage"
                        placeholderText: "Wofür ist diese Vorlage? (optional)"
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
                    title: "Verwendung"
                    iconName: "link"
                    PText {
                        visible: Templates.detailUses.length === 0
                        text: "Wird derzeit nirgends verwendet."
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
                            PText { text: modelData; wrap: true; Layout.fillWidth: true }
                        }
                    }
                }
                PSettingsCard {
                    Layout.fillWidth: true
                    iconName: "checkmark_circle"
                    title: "Standardvorlage"
                    description: "Wird für jede neue Übersicht geladen – und im Stapel für Einträge ohne andere Vorlage verwendet."
                    PToggle {
                        objectName: "templateDefault"
                        label: "Standardvorlage"
                        checked: Templates.detailDefault
                        onToggled: Templates.setDefault(Templates.detailId, checked)
                    }
                }
            }
        }
    }
}
