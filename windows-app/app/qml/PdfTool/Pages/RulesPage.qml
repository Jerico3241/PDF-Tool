import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Regeln«: Regelwerke verwalten und Regeln visuell bearbeiten.
// Liste ↔ Detail wie in »Kunden«. Im Detail ist jede Regel eine Karte »WENN … DANN …«; geöffnet
// wird immer nur eine Regel (Bedingungen und Aktionen als eigene Listen – Eingaben behalten ihren
// Fokus). Testmodus und Vorschau rechnen mit der geprüften Excel aus »Übersicht erstellen«.
Item {
    id: root
    objectName: "rulesPage"
    readonly property bool detail: Rules.detailId !== ""

    Connections {
        target: Rules
        function onFocusRequested(field) {
            if (field === "search") {
                listPage.positionViewAtBeginning()
                Qt.callLater(function() { if (listPage.headerContentItem) listPage.headerContentItem.focusSearch() })
            }
        }
        function onRevealRule(ruleId) {
            Qt.callLater(function() {
                var row = Rules.rulesModel.indexOf(ruleId)
                if (row >= 0) rulesPage.positionViewAtIndex(row, ListView.Contain)
            })
        }
    }

    // Liste der Regelwerke ----------------------------------------------------------------------------
    PListPage {
        id: listPage
        anchors.fill: parent
        opacity: root.detail ? 0 : 1
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr("Regeln: Werte der Übersicht nach festen Regeln anpassen – ohne die Excel zu verändern.", I18n.revision)
        model: Rules.listModel
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Regelwerke", I18n.revision)
        Keys.onReturnPressed: if (currentIndex >= 0) Rules.showDetail(model.get(currentIndex).id)
        Keys.onEnterPressed: if (currentIndex >= 0) Rules.showDetail(model.get(currentIndex).id)
        Keys.onSpacePressed: if (currentIndex >= 0) Rules.showDetail(model.get(currentIndex).id)
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
                        objectName: "ruleSetSearch"
                        preferredWidth: 300
                        label: I18n.tr("Regelwerke durchsuchen", I18n.revision)
                        placeholderText: I18n.tr("Name oder Beschreibung suchen", I18n.revision)
                        text: Rules.search
                        onTextEdited: Rules.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Rules.showDetail(Rules.listModel.get(0).id)
                    }
                }
                PButton { objectName: "newRuleSet"; iconName: "add"; text: I18n.tr("Neues Regelwerk …", I18n.revision); onClicked: Rules.newRuleSet() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: I18n.tr("Regeln wirken nur auf die Werte der PDF und den gespeicherten Vertragsstand. Excel-Dateien werden nie verändert. Es gibt keine Skripte – nur feste Felder, Vergleiche und Aktionen.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_verwaltung") }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: text !== ""
                text: I18n.tr(Rules.problemsText, I18n.revision)
                textStyle: "caption"
                tone: "warning"
                wrap: true
            }
            // Noch kein Regelwerk
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Rules.total === 0
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
                    PIcon { name: "filter"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                    PText { text: I18n.tr(Rules.texts.emptyTitle, I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: I18n.tr(Rules.texts.emptyText, I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PButton { kind: "accent"; iconName: "add"; text: I18n.tr("Erstes Regelwerk anlegen …", I18n.revision); Layout.topMargin: 10; onClicked: Rules.newRuleSet() }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Rules.total > 0
                text: I18n.tr(Rules.countText, I18n.revision)
                tone: "secondary"
                wrap: true
            }
            Item { implicitHeight: listPage.count > 0 ? 12 : 0 }
        }

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
            id: setRow
            required property int index
            required property string id
            required property string name
            required property string description
            required property string rules
            required property bool active
            required property bool used
            width: listPage.width
            height: 60
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(name + ", " + rules + (used ? ", in der Darstellung gewählt" : "") + (active ? "" : ", ausgeschaltet"), I18n.revision)
            PListItem {
                x: listPage.columnX + 6
                y: 2
                width: listPage.columnWidth - 12
                height: setRow.height - 4
                hovered: setMouse.containsMouse
                pressed: setMouse.pressed
                selected: setRow.used
                focused: listPage.activeFocus && listPage.currentIndex === setRow.index
            }
            Rectangle {
                visible: setRow.index > 0
                x: listPage.columnX + 14
                width: listPage.columnWidth - 28
                height: 1
                color: Theme.divider
            }
            MouseArea {
                id: setMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { listPage.currentIndex = setRow.index; Rules.showDetail(setRow.id) }
            }
            RowLayout {
                x: listPage.columnX + 20
                width: listPage.columnWidth - 40
                height: setRow.height
                spacing: 12
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    PText { text: I18n.tr(setRow.name, I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: I18n.tr(setRow.description, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                }
                PBadge { text: I18n.tr(setRow.used ? "in Verwendung" : "", I18n.revision); tone: "accent" }
                PBadge { text: I18n.tr(setRow.active ? "" : "ausgeschaltet", I18n.revision) }
                PText { text: I18n.tr(setRow.rules, I18n.revision); textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 520 }
                PIcon { name: "chevron_right"; size: 12; color: Theme.textSecondary }
            }
        }

        footerContent: ColumnLayout {
            spacing: 0
            Item { implicitHeight: 4 }
        }
    }

    // Detail: Regelwerk mit seinen Regeln ---------------------------------------------------------------
    PListPage {
        id: rulesPage
        objectName: "ruleCards"
        anchors.fill: parent
        opacity: root.detail ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
        title: I18n.tr("Vertragsübersichten", I18n.revision)
        subtitle: I18n.tr("Regeln: Werte der Übersicht nach festen Regeln anpassen – ohne die Excel zu verändern.", I18n.revision)
        model: Rules.rulesModel
        keyNavigationEnabled: false
        spacing: 0
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Regeln von " + Rules.detailName, I18n.revision)

        headerContent: ColumnLayout {
            spacing: 0
            ContractViews {}
            RowLayout {
                Layout.fillWidth: true
                PButton { kind: "subtle"; iconName: "arrow_left"; text: I18n.tr("Alle Regelwerke", I18n.revision); tip: I18n.tr("Zurück zur Liste der Regelwerke", I18n.revision); onClicked: Rules.showList() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PText { objectName: "ruleSetName"; text: I18n.tr(Rules.detailName, I18n.revision); textStyle: "subtitle"; elide: Text.ElideRight; Layout.fillWidth: true }
                PBadge { text: I18n.tr(Rules.detailUsed ? "in Verwendung" : "", I18n.revision); tone: "accent" }
                PBadge { text: I18n.tr(Rules.detailActive ? "" : "ausgeschaltet", I18n.revision); tone: "caution" }
            }
            PText { text: I18n.tr(Rules.detailCaption, I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_verwaltung") }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PButton { objectName: "useRuleSet"; visible: !Rules.detailUsed; kind: "accent"; iconName: "checkmark"; text: I18n.tr("Für die Übersicht verwenden", I18n.revision); tip: I18n.tr("Dieses Regelwerk in der »Darstellung« wählen", I18n.revision); onClicked: Rules.useInOverview() }
                PButton { visible: Rules.detailUsed; iconName: "dismiss"; text: I18n.tr("Nicht mehr verwenden", I18n.revision); tip: I18n.tr("In der »Darstellung« kein Regelwerk wählen", I18n.revision); onClicked: Rules.stopUsing() }
                PButton { iconName: "text_font"; text: I18n.tr("Umbenennen …", I18n.revision); onClicked: Rules.rename() }
                PButton { iconName: "copy"; text: I18n.tr("Duplizieren", I18n.revision); onClicked: Rules.duplicate() }
                PButton { iconName: "delete"; text: I18n.tr("Löschen", I18n.revision); tip: I18n.tr("Regelwerk löschen – Vorlagen und »Darstellung« verwenden es danach nicht mehr", I18n.revision); onClicked: Rules.remove() }
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                columns: rulesPage.columns
                columnSpacing: 12
                rowSpacing: 12

                PCard {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    title: I18n.tr("Regelwerk", I18n.revision)
                    iconName: "filter"
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        PText { text: I18n.tr("Regelwerk eingeschaltet", I18n.revision); Layout.fillWidth: true }
                        PToggle {
                            objectName: "ruleSetActive"
                            label: I18n.tr("Regelwerk eingeschaltet", I18n.revision)
                            checked: Rules.detailActive
                            onToggled: Rules.setActive(checked)
                        }
                    }
                    PText { text: I18n.tr("Ausgeschaltet ändert das Regelwerk nichts – auch nicht im Stapel. Der Testmodus zeigt trotzdem, was es täte.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PFieldLabel { text: I18n.tr("Beschreibung (optional)", I18n.revision) }
                    PTextArea {
                        id: descriptionArea
                        objectName: "ruleSetDescription"
                        Layout.fillWidth: true
                        label: I18n.tr("Beschreibung des Regelwerks", I18n.revision)
                        placeholderText: I18n.tr("Wofür ist dieses Regelwerk?", I18n.revision)
                        minLines: 2
                        Connections {
                            target: Rules
                            function onDetailDescriptionChanged() { if (!descriptionArea.area.activeFocus && descriptionArea.text !== Rules.detailDescription) descriptionArea.text = Rules.detailDescription }
                            function onDetailIdChanged() { descriptionArea.text = Rules.detailDescription }
                        }
                        Component.onCompleted: text = Rules.detailDescription
                        onEdited: Rules.setDescription(text)
                    }
                    Repeater {
                        model: Rules.detailUses
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.topMargin: 8
                            spacing: 8
                            PIcon { name: "link"; size: 12; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4 }
                            PText { text: I18n.tr(modelData, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                        }
                    }
                }

                // Testmodus: mit der geprüften Excel
                PCard {
                    objectName: "ruleTest"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    title: I18n.tr("Testmodus", I18n.revision)
                    iconName: "eye"
                    subtitle: I18n.tr(Rules.testReady ? Rules.testSource : "Mit der Excel aus »Übersicht erstellen« – nur gelesen, nie verändert.", I18n.revision)
                    headerRight: [
                        PProgressRing { size: 16; visible: Rules.testBusy; running: visible }
                    ]
                    PText { objectName: "ruleTestTitle"; text: I18n.tr(Rules.testTitle, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; visible: text !== "" }
                    PText { text: I18n.tr(Rules.testText, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PButton { visible: Rules.testReady && Rules.changesModel.count > 0; iconName: "document_search"; text: I18n.tr("Vorher → nachher ansehen", I18n.revision); onClicked: rulesPage.positionViewAtEnd() }
                        PButton { visible: !Rules.testReady; iconName: "document_table"; text: I18n.tr("Excel wählen", I18n.revision); tip: I18n.tr("Zu »Übersicht erstellen«", I18n.revision); onClicked: App.navigate("create") }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 20
                spacing: 8
                PText { text: I18n.tr("Regeln", I18n.revision); textStyle: "bodyStrong"; Accessible.role: Accessible.Heading }
                PText { text: I18n.tr(Rules.ruleCount > 0 ? "(" + Rules.ruleCount + ")" : "", I18n.revision); tone: "secondary" }
                Item { Layout.fillWidth: true }
                PButton { iconName: "add"; text: I18n.tr("Regel hinzufügen", I18n.revision); onClicked: Rules.addRule() }
            }
            PText { text: I18n.tr(Rules.texts.orderHint, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; Layout.bottomMargin: 10 }
            PText {
                visible: Rules.ruleCount === 0
                text: I18n.tr("Noch keine Regel. »Regel hinzufügen« legt eine an.", I18n.revision)
                tone: "secondary"
                Layout.fillWidth: true
                Layout.bottomMargin: 10
            }
        }

        delegate: Item {
            id: row
            required property int index
            required property string id
            required property int number
            required property string name
            required property bool active
            required property string whenText
            required property string thenText
            required property string problems
            required property string hits
            required property bool first
            required property bool last
            readonly property bool editing: Rules.editingRule === id
            width: rulesPage.width
            height: card.height + 8
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(name + ": wenn " + whenText + ", dann " + thenText, I18n.revision)

            Rectangle {
                id: card
                x: rulesPage.columnX
                width: rulesPage.columnWidth
                height: cardColumn.implicitHeight + 28
                radius: Metrics.radiusCard
                color: Theme.surface
                border.width: row.editing ? 2 : 1
                border.color: row.editing ? Theme.accent : Theme.border
                Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }

                ColumnLayout {
                    id: cardColumn
                    x: 16
                    y: 14
                    width: parent.width - 32
                    spacing: 6

                    // Kopf: Nummer, Name, Zustand, Reihenfolge, Aktionen
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Rectangle {
                            implicitWidth: 26
                            implicitHeight: 26
                            radius: 13
                            color: row.active ? Theme.accent : Theme.surfaceSecondary
                            border.width: row.active ? 0 : 1
                            border.color: Theme.border
                            Text { anchors.centerIn: parent; text: I18n.tr(row.number, I18n.revision); font: Typography.caption; color: row.active ? Theme.textOnAccent : Theme.textSecondary }
                        }
                        PText { text: I18n.tr(row.name, I18n.revision); textStyle: "bodyStrong"; tone: row.active ? "" : "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.leftMargin: 4 }
                        PBadge { text: I18n.tr(row.problems !== "" ? "unvollständig" : "", I18n.revision); tone: "caution" }
                        PBadge { text: I18n.tr(row.active ? "" : "ausgeschaltet", I18n.revision) }
                        PToggle { showState: false; label: I18n.tr("Regel " + row.number + " einschalten", I18n.revision); tip: I18n.tr(row.active ? "Regel ausschalten" : "Regel einschalten", I18n.revision); checked: row.active; onToggled: Rules.setRuleActive(row.id, checked) }
                        PIconButton { iconName: "chevron_up"; tip: I18n.tr("Nach oben (früher ausführen)", I18n.revision); enabled: !row.first; onClicked: Rules.moveRule(row.id, -1) }
                        PIconButton { iconName: "chevron_down"; tip: I18n.tr("Nach unten (später ausführen – gilt dann zuletzt)", I18n.revision); enabled: !row.last; onClicked: Rules.moveRule(row.id, 1) }
                        PIconButton { iconName: "copy"; tip: I18n.tr("Regel duplizieren", I18n.revision); onClicked: Rules.duplicateRule(row.id) }
                        PIconButton { iconName: "delete"; tip: I18n.tr("Regel entfernen", I18n.revision); onClicked: Rules.removeRule(row.id) }
                        PButton { objectName: "editRule"; minimumWidth: 124; kind: row.editing ? "accent" : "standard"; iconName: row.editing ? "checkmark" : "edit"; text: I18n.tr(row.editing ? "Fertig" : "Bearbeiten", I18n.revision); onClicked: Rules.editRule(row.id) }
                    }

                    // Lesbare Zusammenfassung: WENN … DANN …
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: I18n.tr("WENN", I18n.revision); font: Typography.caption; color: Theme.accentText; Layout.preferredWidth: 40; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: I18n.tr(row.whenText, I18n.revision); wrap: true; Layout.fillWidth: true; tone: row.active ? "" : "secondary" }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: I18n.tr("DANN", I18n.revision); font: Typography.caption; color: Theme.accentText; Layout.preferredWidth: 40; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: I18n.tr(row.thenText, I18n.revision); wrap: true; Layout.fillWidth: true; tone: row.active ? "" : "secondary" }
                    }
                    PText { text: I18n.tr(row.hits, I18n.revision); visible: text !== ""; textStyle: "caption"; tone: "accent"; wrap: true; Layout.fillWidth: true }
                    PText { text: I18n.tr(row.problems, I18n.revision); visible: text !== ""; textStyle: "caption"; tone: "warning"; wrap: true; Layout.fillWidth: true }

                    // Bearbeiten (nur die geöffnete Regel)
                    Loader {
                        Layout.fillWidth: true
                        active: row.editing
                        visible: active
                        sourceComponent: ruleEditor
                    }
                }
            }
        }

        footerContent: ColumnLayout {
            spacing: 0
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 4
                visible: Rules.ruleCount > 0
                PButton { iconName: "add"; text: I18n.tr("Regel hinzufügen", I18n.revision); onClicked: Rules.addRule() }
            }
            // Vorschau: vorher → nachher
            PCard {
                objectName: "rulePreview"
                Layout.fillWidth: true
                Layout.topMargin: 16
                title: I18n.tr("Vorschau: vorher → nachher", I18n.revision)
                iconName: "document_search"
                subtitle: I18n.tr(Rules.testReady ? Rules.testSource + " – nur Verträge, die sich ändern." : Rules.texts.noExcel, I18n.revision)
                PText { text: I18n.tr(Rules.testTitle, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; visible: Rules.testReady }
                PText { visible: Rules.testReady && Rules.changesModel.count === 0; text: I18n.tr("Keine Änderungen.", I18n.revision); tone: "secondary"; Layout.fillWidth: true }
                Repeater {
                    model: Rules.changesModel
                    ColumnLayout {
                        required property int index
                        required property string title
                        required property var lines
                        Layout.fillWidth: true
                        Layout.topMargin: index === 0 ? 8 : 12
                        spacing: 2
                        PText { text: I18n.tr(title, I18n.revision); textStyle: "bodyStrong"; Layout.fillWidth: true; elide: Text.ElideRight }
                        Repeater {
                            model: lines
                            GridLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                columns: rulesPage.columnWidth > 640 ? 4 : 2
                                columnSpacing: 10
                                rowSpacing: 0
                                PText { text: I18n.tr(modelData.label, I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 130 }
                                PText { text: I18n.tr(modelData.before, I18n.revision); tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                PText { text: I18n.tr("→ " + modelData.after, I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                PText {
                                    text: I18n.tr((modelData.conflict ? "Konflikt – " : "") + modelData.rules, I18n.revision)
                                    textStyle: "caption"
                                    tone: modelData.conflict ? "warning" : "secondary"
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 1
                                }
                            }
                        }
                    }
                }
                PText { text: I18n.tr(Rules.previewMore, I18n.revision); visible: text !== ""; tone: "secondary"; Layout.topMargin: 10; Layout.fillWidth: true }
            }
            Item { implicitHeight: 8 }
        }
    }

    // Editor der geöffneten Regel ------------------------------------------------------------------------
    Component {
        id: ruleEditor
        ColumnLayout {
            id: editor
            spacing: 0
            readonly property bool wide: rulesPage.columnWidth >= 720
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 6; Layout.bottomMargin: 6; height: 1; color: Theme.divider }
            PFieldLabel { text: I18n.tr("Name der Regel (optional)", I18n.revision); first: true }
            PTextField {
                objectName: "ruleName"
                Layout.fillWidth: true
                label: I18n.tr("Name der Regel", I18n.revision)
                placeholderText: I18n.tr("z. B. Energieverträge kennzeichnen", I18n.revision)
                text: Rules.editName
                onTextEdited: Rules.setRuleName(text)
            }

            // WENN
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 16
                spacing: 10
                PText { text: I18n.tr("WENN", I18n.revision); textStyle: "bodyStrong" }
                PComboBox {
                    objectName: "ruleMatch"
                    preferredWidth: 300
                    label: I18n.tr("Verknüpfung der Bedingungen", I18n.revision)
                    model: Rules.matchChoices
                    textRole: "label"
                    currentIndex: Rules.editMatch === "any" ? 1 : 0
                    onActivated: (index) => Rules.setMatch(Rules.matchChoices[index].key)
                }
                Item { Layout.fillWidth: true }
            }
            PText {
                visible: Rules.conditionsModel.count === 0
                text: I18n.tr("Ohne Bedingung gilt die Regel für alle Verträge.", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                Layout.topMargin: 8
            }
            Repeater {
                model: Rules.conditionsModel
                GridLayout {
                    id: conditionRow
                    required property int index
                    required property string key
                    required property string field
                    required property string operator
                    required property string value
                    required property bool needsValue
                    required property var operators
                    required property string placeholder
                    required property string problem
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    columns: editor.wide ? 8 : 2  // breit: alles in einer Zeile
                    columnSpacing: 8
                    rowSpacing: 6
                    PComboBox {
                        preferredWidth: 180
                        Layout.fillWidth: !editor.wide
                        label: I18n.tr("Feld der Bedingung " + (conditionRow.index + 1), I18n.revision)
                        model: Rules.fieldChoices
                        textRole: "label"
                        currentIndex: {
                            for (var i = 0; i < Rules.fieldChoices.length; ++i)
                                if (Rules.fieldChoices[i].key === conditionRow.field) return i
                            return -1
                        }
                        onActivated: (i) => Rules.setConditionField(conditionRow.key, Rules.fieldChoices[i].key)
                    }
                    PComboBox {
                        preferredWidth: 190
                        Layout.fillWidth: !editor.wide
                        label: I18n.tr("Vergleich der Bedingung " + (conditionRow.index + 1), I18n.revision)
                        model: conditionRow.operators
                        textRole: "label"
                        currentIndex: {
                            for (var i = 0; i < conditionRow.operators.length; ++i)
                                if (conditionRow.operators[i].key === conditionRow.operator) return i
                            return -1
                        }
                        onActivated: (i) => Rules.setConditionOperator(conditionRow.key, conditionRow.operators[i].key)
                    }
                    PTextField {
                        objectName: "conditionValue"
                        Layout.fillWidth: true
                        visible: conditionRow.needsValue
                        label: I18n.tr("Wert der Bedingung " + (conditionRow.index + 1), I18n.revision)
                        placeholderText: I18n.tr(conditionRow.placeholder, I18n.revision)
                        text: conditionRow.value
                        invalid: conditionRow.value.trim() !== "" && conditionRow.problem !== ""
                        onTextEdited: Rules.setConditionValue(conditionRow.key, text)
                    }
                    Item { Layout.fillWidth: true; visible: !conditionRow.needsValue; implicitHeight: 1 }
                    PIconButton { iconName: "delete"; tip: I18n.tr("Bedingung " + (conditionRow.index + 1) + " entfernen", I18n.revision); onClicked: Rules.removeCondition(conditionRow.key) }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                PButton { kind: "subtle"; iconName: "add"; text: I18n.tr("Bedingung hinzufügen", I18n.revision); onClicked: Rules.addCondition() }
            }

            // DANN
            PText { text: I18n.tr("DANN", I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 14 }
            Repeater {
                model: Rules.actionsModel
                GridLayout {
                    id: actionRow
                    required property int index
                    required property string key
                    required property string kind
                    required property string field
                    required property string value
                    required property string find
                    required property bool needsValue
                    required property bool needsFind
                    required property string placeholder
                    required property string problem
                    Layout.fillWidth: true
                    Layout.topMargin: 8
                    columns: editor.wide ? 8 : 2
                    columnSpacing: 8
                    rowSpacing: 6
                    PComboBox {
                        preferredWidth: 180
                        Layout.fillWidth: !editor.wide
                        label: I18n.tr("Feld der Aktion " + (actionRow.index + 1), I18n.revision)
                        model: Rules.targetChoices
                        textRole: "label"
                        currentIndex: {
                            for (var i = 0; i < Rules.targetChoices.length; ++i)
                                if (Rules.targetChoices[i].key === actionRow.field) return i
                            return -1
                        }
                        onActivated: (i) => Rules.setActionField(actionRow.key, Rules.targetChoices[i].key)
                    }
                    PComboBox {
                        preferredWidth: 190
                        Layout.fillWidth: !editor.wide
                        label: I18n.tr("Aktion " + (actionRow.index + 1), I18n.revision)
                        model: Rules.actionChoices
                        textRole: "label"
                        currentIndex: {
                            for (var i = 0; i < Rules.actionChoices.length; ++i)
                                if (Rules.actionChoices[i].key === actionRow.kind) return i
                            return -1
                        }
                        onActivated: (i) => Rules.setActionKind(actionRow.key, Rules.actionChoices[i].key)
                    }
                    PTextField {
                        Layout.fillWidth: true
                        visible: actionRow.needsFind
                        label: I18n.tr("Zu ersetzender Text der Aktion " + (actionRow.index + 1), I18n.revision)
                        placeholderText: I18n.tr("zu ersetzender Text", I18n.revision)
                        text: actionRow.find
                        onTextEdited: Rules.setActionFind(actionRow.key, text)
                    }
                    PTextField {
                        objectName: "actionValue"
                        Layout.fillWidth: true
                        visible: actionRow.needsValue
                        label: I18n.tr("Wert der Aktion " + (actionRow.index + 1), I18n.revision)
                        placeholderText: I18n.tr(actionRow.placeholder, I18n.revision)
                        text: actionRow.value
                        onTextEdited: Rules.setActionValue(actionRow.key, text)
                    }
                    Item { Layout.fillWidth: true; visible: !actionRow.needsValue && !actionRow.needsFind; implicitHeight: 1 }
                    PIconButton { iconName: "delete"; tip: I18n.tr("Aktion " + (actionRow.index + 1) + " entfernen", I18n.revision); onClicked: Rules.removeAction(actionRow.key) }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                PButton { kind: "subtle"; iconName: "add"; text: I18n.tr("Aktion hinzufügen", I18n.revision); onClicked: Rules.addAction() }
            }
            PText {
                text: I18n.tr("Änderbar sind Art, Beschreibung, Abrechnungszyklus und Zahlungsart. Vertragsnummer, Beginn und Netto bleiben immer so, wie sie in der Excel stehen.", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                wrap: true
                Layout.fillWidth: true
                Layout.topMargin: 10
            }
        }
    }
}
