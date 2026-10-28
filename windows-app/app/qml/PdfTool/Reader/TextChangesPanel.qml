import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Nachverfolgte Änderungen eines Textes (seit 5.0 Beta 5): oben Nachverfolgen ein/aus und »Alle annehmen« bzw.
// »Alle ablehnen«, darunter jede Änderung mit Art (eingefügt grün, gelöscht rot, formatiert blau), Verfasser, Datum
// und dem betroffenen Text. Klick springt zur Stelle; Häkchen nimmt an, Kreuz lehnt ab.
ColumnLayout {
    id: root
    objectName: "textChangesPanel"
    property var doc: null
    readonly property var entries: doc ? doc.changes : []
    spacing: 0

    function toneOf(type) {
        if (type === "Insert" || type === "TableRowInsert" || type === "TableCellInsert") return "success"
        if (type === "Delete" || type === "TableRowDelete" || type === "TableCellDelete") return "error"
        return "info"
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        Layout.topMargin: 12
        Layout.bottomMargin: 8
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PText { Layout.fillWidth: true; text: I18n.tr("Änderungen nachverfolgen", I18n.revision); wrap: true }
            PToggle {
                objectName: "textChangesTrack"
                label: I18n.tr("Änderungen nachverfolgen", I18n.revision)
                checked: root.doc !== null && root.doc.trackChanges
                enabled: root.doc !== null && root.doc.ready
                onToggled: {
                    root.doc.toggle("trackChanges")
                    checked = Qt.binding(function() { return root.doc !== null && root.doc.trackChanges })
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PButton { objectName: "textChangesAcceptAll"; Layout.fillWidth: true; iconName: "checkmark"; text: I18n.tr("Alle annehmen", I18n.revision); enabled: root.entries.length > 0; onClicked: root.doc.acceptAllChanges() }
            PButton { objectName: "textChangesRejectAll"; Layout.fillWidth: true; iconName: "dismiss"; text: I18n.tr("Alle ablehnen", I18n.revision); enabled: root.entries.length > 0; onClicked: root.doc.rejectAllChanges() }
        }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.divider }

    PEmptyState {
        objectName: "textChangesEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.entries.length === 0
        iconName: "document_edit"
        title: I18n.tr("Keine Änderungen", I18n.revision)
        text: I18n.tr(root.doc && root.doc.trackChanges ? "Was Sie jetzt schreiben oder löschen, erscheint hier zum Annehmen oder Ablehnen." : "Mit »Änderungen nachverfolgen« wird jede Änderung markiert, statt sie gleich zu übernehmen.", I18n.revision)
    }
    ListView {
        id: list
        objectName: "textChangesList"
        PWheelScroll { flickable: list }
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: count > 0
        model: root.entries
        clip: true
        spacing: 2
        topMargin: 4
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Änderungen", I18n.revision)

        delegate: Item {
            id: row
            required property var modelData
            width: list.width
            height: body.implicitHeight + 16
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(modelData.kind + ": " + modelData.text, I18n.revision)

            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
            }
            HoverHandler { id: hover }
            TapHandler { onTapped: root.doc.goToChange(row.modelData.index) }
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                anchors.topMargin: 8
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    PBadge { text: I18n.tr(row.modelData.kind, I18n.revision); tone: root.toneOf(row.modelData.type) }
                    PText { Layout.fillWidth: true; text: I18n.tr(row.modelData.author, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight }
                    PIconButton { objectName: "textChangeAccept"; implicitWidth: 28; implicitHeight: 28; iconName: "checkmark"; tip: I18n.tr("Annehmen", I18n.revision); onClicked: root.doc.acceptChange(row.modelData.index) }
                    PIconButton { objectName: "textChangeReject"; implicitWidth: 28; implicitHeight: 28; iconName: "dismiss"; tip: I18n.tr("Ablehnen", I18n.revision); onClicked: root.doc.rejectChange(row.modelData.index) }
                }
                PText {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: I18n.tr(row.modelData.text, I18n.revision)
                    wrap: true
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    font.strikeout: row.modelData.type === "Delete"
                }
                PText { Layout.fillWidth: true; visible: text !== ""; text: I18n.tr(row.modelData.date, I18n.revision); textStyle: "caption"; tone: "tertiary" }
            }
        }
    }
}
