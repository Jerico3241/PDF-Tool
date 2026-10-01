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
        title: "Vertragsübersichten"
        subtitle: "Regeln: Werte der Übersicht nach festen Regeln anpassen – ohne die Excel zu verändern."
        model: Rules.listModel
        Accessible.role: Accessible.List
        Accessible.name: "Regelwerke"
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
                        label: "Regelwerke durchsuchen"
                        placeholderText: "Name oder Beschreibung suchen"
                        text: Rules.search
                        onTextEdited: Rules.search = text
                        Keys.onDownPressed: { listPage.forceActiveFocus(); listPage.currentIndex = 0 }
                        onSubmitted: if (listPage.count > 0) Rules.showDetail(Rules.listModel.get(0).id)
                    }
                }
                PButton { objectName: "newRuleSet"; iconName: "add"; text: "Neues Regelwerk …"; onClicked: Rules.newRuleSet() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: "Regeln wirken nur auf die Werte der PDF und den gespeicherten Vertragsstand. Excel-Dateien werden nie verändert. Es gibt keine Skripte – nur feste Felder, Vergleiche und Aktionen."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_verwaltung") }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 8
                visible: text !== ""
                text: Rules.problemsText
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
                    PText { text: Rules.texts.emptyTitle; textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: Rules.texts.emptyText; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PButton { kind: "accent"; iconName: "add"; text: "Erstes Regelwerk anlegen …"; Layout.topMargin: 10; onClicked: Rules.newRuleSet() }
                }
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 12
                visible: Rules.total > 0
                text: Rules.countText
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
            Accessible.name: name + ", " + rules + (used ? ", in der Darstellung gewählt" : "") + (active ? "" : ", ausgeschaltet")
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
                    PText { text: setRow.name; textStyle: "bodyStrong"; elide: Text.ElideMiddle; Layout.fillWidth: true }
                    PText { text: setRow.description; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                }
                PBadge { text: setRow.used ? "in Verwendung" : ""; tone: "accent" }
                PBadge { text: setRow.active ? "" : "ausgeschaltet" }
                PText { text: setRow.rules; textStyle: "caption"; tone: "secondary"; visible: listPage.columnWidth > 520 }
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
        title: "Vertragsübersichten"
        subtitle: "Regeln: Werte der Übersicht nach festen Regeln anpassen – ohne die Excel zu verändern."
        model: Rules.rulesModel
        keyNavigationEnabled: false
        spacing: 0
        Accessible.role: Accessible.List
        Accessible.name: "Regeln von " + Rules.detailName

        headerContent: ColumnLayout {
            spacing: 0
            ContractViews {}
            RowLayout {
                Layout.fillWidth: true
                PButton { kind: "subtle"; iconName: "arrow_left"; text: "Alle Regelwerke"; tip: "Zurück zur Liste der Regelwerke"; onClicked: Rules.showList() }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PText { objectName: "ruleSetName"; text: Rules.detailName; textStyle: "subtitle"; elide: Text.ElideRight; Layout.fillWidth: true }
                PBadge { text: Rules.detailUsed ? "in Verwendung" : ""; tone: "accent" }
                PBadge { text: Rules.detailActive ? "" : "ausgeschaltet"; tone: "caution" }
            }
            PText { text: Rules.detailCaption; textStyle: "caption"; tone: "secondary"; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_verwaltung") }

            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PButton { objectName: "useRuleSet"; visible: !Rules.detailUsed; kind: "accent"; iconName: "checkmark"; text: "Für die Übersicht verwenden"; tip: "Dieses Regelwerk in der »Darstellung« wählen"; onClicked: Rules.useInOverview() }
                PButton { visible: Rules.detailUsed; iconName: "dismiss"; text: "Nicht mehr verwenden"; tip: "In der »Darstellung« kein Regelwerk wählen"; onClicked: Rules.stopUsing() }
                PButton { iconName: "text_font"; text: "Umbenennen …"; onClicked: Rules.rename() }
                PButton { iconName: "copy"; text: "Duplizieren"; onClicked: Rules.duplicate() }
                PButton { iconName: "delete"; text: "Löschen"; tip: "Regelwerk löschen – Vorlagen und »Darstellung« verwenden es danach nicht mehr"; onClicked: Rules.remove() }
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
                    title: "Regelwerk"
                    iconName: "filter"
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        PText { text: "Regelwerk eingeschaltet"; Layout.fillWidth: true }
                        PToggle {
                            objectName: "ruleSetActive"
                            label: "Regelwerk eingeschaltet"
                            checked: Rules.detailActive
                            onToggled: Rules.setActive(checked)
                        }
                    }
                    PText { text: "Ausgeschaltet ändert das Regelwerk nichts – auch nicht im Stapel. Der Testmodus zeigt trotzdem, was es täte."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                    PFieldLabel { text: "Beschreibung (optional)" }
                    PTextArea {
                        id: descriptionArea
                        objectName: "ruleSetDescription"
                        Layout.fillWidth: true
                        label: "Beschreibung des Regelwerks"
                        placeholderText: "Wofür ist dieses Regelwerk?"
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
                            PText { text: modelData; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
                        }
                    }
                }

                // Testmodus: mit der geprüften Excel
                PCard {
                    objectName: "ruleTest"
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    title: "Testmodus"
                    iconName: "eye"
                    subtitle: Rules.testReady ? Rules.testSource : "Mit der Excel aus »Übersicht erstellen« – nur gelesen, nie verändert."
                    headerRight: [
                        PProgressRing { size: 16; visible: Rules.testBusy; running: visible }
                    ]
                    PText { objectName: "ruleTestTitle"; text: Rules.testTitle; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; visible: text !== "" }
                    PText { text: Rules.testText; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; visible: text !== "" }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 10
                        spacing: 8
                        PButton { visible: Rules.testReady && Rules.changesModel.count > 0; iconName: "document_search"; text: "Vorher → nachher ansehen"; onClicked: rulesPage.positionViewAtEnd() }
                        PButton { visible: !Rules.testReady; iconName: "document_table"; text: "Excel wählen"; tip: "Zu »Übersicht erstellen«"; onClicked: App.navigate("create") }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 20
                spacing: 8
                PText { text: "Regeln"; textStyle: "bodyStrong"; Accessible.role: Accessible.Heading }
                PText { text: Rules.ruleCount > 0 ? "(" + Rules.ruleCount + ")" : ""; tone: "secondary" }
                Item { Layout.fillWidth: true }
                PButton { iconName: "add"; text: "Regel hinzufügen"; onClicked: Rules.addRule() }
            }
            PText { text: Rules.texts.orderHint; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2; Layout.bottomMargin: 10 }
            PText {
                visible: Rules.ruleCount === 0
                text: "Noch keine Regel. »Regel hinzufügen« legt eine an."
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
            Accessible.name: name + ": wenn " + whenText + ", dann " + thenText

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
                            Text { anchors.centerIn: parent; text: row.number; font: Typography.caption; color: row.active ? Theme.textOnAccent : Theme.textSecondary }
                        }
                        PText { text: row.name; textStyle: "bodyStrong"; tone: row.active ? "" : "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.leftMargin: 4 }
                        PBadge { text: row.problems !== "" ? "unvollständig" : ""; tone: "caution" }
                        PBadge { text: row.active ? "" : "ausgeschaltet" }
                        PToggle { showState: false; label: "Regel " + row.number + " einschalten"; tip: row.active ? "Regel ausschalten" : "Regel einschalten"; checked: row.active; onToggled: Rules.setRuleActive(row.id, checked) }
                        PIconButton { iconName: "chevron_up"; tip: "Nach oben (früher ausführen)"; enabled: !row.first; onClicked: Rules.moveRule(row.id, -1) }
                        PIconButton { iconName: "chevron_down"; tip: "Nach unten (später ausführen – gilt dann zuletzt)"; enabled: !row.last; onClicked: Rules.moveRule(row.id, 1) }
                        PIconButton { iconName: "copy"; tip: "Regel duplizieren"; onClicked: Rules.duplicateRule(row.id) }
                        PIconButton { iconName: "delete"; tip: "Regel entfernen"; onClicked: Rules.removeRule(row.id) }
                        PButton { objectName: "editRule"; minimumWidth: 124; kind: row.editing ? "accent" : "standard"; iconName: row.editing ? "checkmark" : "edit"; text: row.editing ? "Fertig" : "Bearbeiten"; onClicked: Rules.editRule(row.id) }
                    }

                    // Lesbare Zusammenfassung: WENN … DANN …
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "WENN"; font: Typography.caption; color: Theme.accentText; Layout.preferredWidth: 40; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: row.whenText; wrap: true; Layout.fillWidth: true; tone: row.active ? "" : "secondary" }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "DANN"; font: Typography.caption; color: Theme.accentText; Layout.preferredWidth: 40; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: row.thenText; wrap: true; Layout.fillWidth: true; tone: row.active ? "" : "secondary" }
                    }
                    PText { text: row.hits; visible: text !== ""; textStyle: "caption"; tone: "accent"; wrap: true; Layout.fillWidth: true }
                    PText { text: row.problems; visible: text !== ""; textStyle: "caption"; tone: "warning"; wrap: true; Layout.fillWidth: true }

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
                PButton { iconName: "add"; text: "Regel hinzufügen"; onClicked: Rules.addRule() }
            }
            // Vorschau: vorher → nachher
            PCard {
                objectName: "rulePreview"
                Layout.fillWidth: true
                Layout.topMargin: 16
                title: "Vorschau: vorher → nachher"
                iconName: "document_search"
                subtitle: Rules.testReady ? Rules.testSource + " – nur Verträge, die sich ändern." : Rules.texts.noExcel
                PText { text: Rules.testTitle; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true; visible: Rules.testReady }
                PText { visible: Rules.testReady && Rules.changesModel.count === 0; text: "Keine Änderungen."; tone: "secondary"; Layout.fillWidth: true }
                Repeater {
                    model: Rules.changesModel
                    ColumnLayout {
                        required property int index
                        required property string title
                        required property var lines
                        Layout.fillWidth: true
                        Layout.topMargin: index === 0 ? 8 : 12
                        spacing: 2
                        PText { text: title; textStyle: "bodyStrong"; Layout.fillWidth: true; elide: Text.ElideRight }
                        Repeater {
                            model: lines
                            GridLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                columns: rulesPage.columnWidth > 640 ? 4 : 2
                                columnSpacing: 10
                                rowSpacing: 0
                                PText { text: modelData.label; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 130 }
                                PText { text: modelData.before; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                PText { text: "→ " + modelData.after; textStyle: "bodyStrong"; elide: Text.ElideRight; Layout.fillWidth: true; Layout.preferredWidth: 1 }
                                PText {
                                    text: (modelData.conflict ? "Konflikt – " : "") + modelData.rules
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
                PText { text: Rules.previewMore; visible: text !== ""; tone: "secondary"; Layout.topMargin: 10; Layout.fillWidth: true }
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
            PFieldLabel { text: "Name der Regel (optional)"; first: true }
            PTextField {
                objectName: "ruleName"
                Layout.fillWidth: true
                label: "Name der Regel"
                placeholderText: "z. B. Energieverträge kennzeichnen"
                text: Rules.editName
                onTextEdited: Rules.setRuleName(text)
            }

            // WENN
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 16
                spacing: 10
                PText { text: "WENN"; textStyle: "bodyStrong" }
                PComboBox {
                    objectName: "ruleMatch"
                    preferredWidth: 300
                    label: "Verknüpfung der Bedingungen"
                    model: Rules.matchChoices
                    textRole: "label"
                    currentIndex: Rules.editMatch === "any" ? 1 : 0
                    onActivated: (index) => Rules.setMatch(Rules.matchChoices[index].key)
                }
                Item { Layout.fillWidth: true }
            }
            PText {
                visible: Rules.conditionsModel.count === 0
                text: "Ohne Bedingung gilt die Regel für alle Verträge."
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
                        label: "Feld der Bedingung " + (conditionRow.index + 1)
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
                        label: "Vergleich der Bedingung " + (conditionRow.index + 1)
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
                        label: "Wert der Bedingung " + (conditionRow.index + 1)
                        placeholderText: conditionRow.placeholder
                        text: conditionRow.value
                        invalid: conditionRow.value.trim() !== "" && conditionRow.problem !== ""
                        onTextEdited: Rules.setConditionValue(conditionRow.key, text)
                    }
                    Item { Layout.fillWidth: true; visible: !conditionRow.needsValue; implicitHeight: 1 }
                    PIconButton { iconName: "delete"; tip: "Bedingung " + (conditionRow.index + 1) + " entfernen"; onClicked: Rules.removeCondition(conditionRow.key) }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                PButton { kind: "subtle"; iconName: "add"; text: "Bedingung hinzufügen"; onClicked: Rules.addCondition() }
            }

            // DANN
            PText { text: "DANN"; textStyle: "bodyStrong"; Layout.topMargin: 14 }
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
                        label: "Feld der Aktion " + (actionRow.index + 1)
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
                        label: "Aktion " + (actionRow.index + 1)
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
                        label: "Zu ersetzender Text der Aktion " + (actionRow.index + 1)
                        placeholderText: "zu ersetzender Text"
                        text: actionRow.find
                        onTextEdited: Rules.setActionFind(actionRow.key, text)
                    }
                    PTextField {
                        objectName: "actionValue"
                        Layout.fillWidth: true
                        visible: actionRow.needsValue
                        label: "Wert der Aktion " + (actionRow.index + 1)
                        placeholderText: actionRow.placeholder
                        text: actionRow.value
                        onTextEdited: Rules.setActionValue(actionRow.key, text)
                    }
                    Item { Layout.fillWidth: true; visible: !actionRow.needsValue && !actionRow.needsFind; implicitHeight: 1 }
                    PIconButton { iconName: "delete"; tip: "Aktion " + (actionRow.index + 1) + " entfernen"; onClicked: Rules.removeAction(actionRow.key) }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 6
                PButton { kind: "subtle"; iconName: "add"; text: "Aktion hinzufügen"; onClicked: Rules.addAction() }
            }
            PText {
                text: "Änderbar sind Art, Beschreibung, Abrechnungszyklus und Zahlungsart. Vertragsnummer, Beginn und Netto bleiben immer so, wie sie in der Excel stehen."
                textStyle: "caption"
                tone: "secondary"
                wrap: true
                Layout.fillWidth: true
                Layout.topMargin: 10
            }
        }
    }
}
