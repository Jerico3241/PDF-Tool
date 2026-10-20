import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Anhänge des Dokuments (und Dateianhänge auf Seiten): Name, Größe, Beschreibung. Öffnen nur für
// Dokument-, Bild- und Textformate (Programme aus PDFs werden nie ausgeführt), Speichern unter für alle;
// Anhänge des Dokuments lassen sich entfernen und neue hinzufügen (Rückgängig wie jede Änderung).
// Kopf, Breite und Umschalter kommen von der linken Seitenleiste (LeftPanel).
ColumnLayout {
    id: root
    objectName: "readerAttachmentsPanel"
    property var doc: null
    readonly property bool canEdit: doc !== null && doc.readOnlyReason === "" && (doc.permissions.edit === undefined || doc.permissions.edit)
    spacing: 0

    PEmptyState {
        objectName: "readerAttachmentsEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.doc !== null && root.doc.attachmentCount === 0
        iconName: "attach"
        title: I18n.tr("Keine Anhänge", I18n.revision)
        text: I18n.tr("Dieses PDF enthält keine angehängten Dateien. Über »Datei anhängen« lässt sich eine Datei hinzufügen.", I18n.revision)
    }
    ListView {
        id: list
        PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        objectName: "readerAttachmentList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: count > 0
        model: root.doc ? root.doc.attachmentList : null
        clip: true
        spacing: 2
        topMargin: 4
        bottomMargin: 8
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        activeFocusOnTab: true
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Anhänge", I18n.revision)

        delegate: Item {
            id: row
            required property string key
            required property string name
            required property string description
            required property string sizeText
            required property string modified
            required property int page
            required property bool openable
            required property int index
            width: list.width
            height: body.implicitHeight + 16
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(name + (sizeText !== "" ? ", " + sizeText : ""), I18n.revision)

            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
                focused: list.activeFocus && list.currentIndex === row.index
            }
            HoverHandler { id: hover }
            TapHandler {
                onTapped: list.currentIndex = row.index
                onDoubleTapped: if (row.openable) root.doc.openAttachment(row.key)
            }
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                anchors.topMargin: 8
                spacing: 2
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    PIcon { name: "attach"; color: Theme.textSecondary; size: 16 }
                    PText { text: I18n.tr(row.name, I18n.revision); Layout.fillWidth: true; elide: Text.ElideMiddle }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "open"; tip: I18n.tr(row.openable ? "Öffnen" : "Dieser Dateityp wird nicht geöffnet – nur speichern", I18n.revision); enabled: row.openable; onClicked: root.doc.openAttachment(row.key) }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "save"; tip: I18n.tr("Speichern unter …", I18n.revision); onClicked: root.doc.saveAttachment(row.key) }
                    PIconButton {
                        implicitWidth: 28
                        implicitHeight: 28
                        iconName: "delete"
                        tip: I18n.tr("Anhang entfernen", I18n.revision)
                        visible: row.page < 0 && root.canEdit
                        onClicked: root.doc.removeAttachment(row.key)
                    }
                }
                PText {
                    Layout.fillWidth: true
                    visible: row.description !== ""
                    text: I18n.tr(row.description, I18n.revision)
                    wrap: true
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    tone: "secondary"
                }
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr([row.sizeText, row.modified, row.page >= 0 ? "auf Seite " + (row.page + 1) : ""].filter(function(v) { return v !== "" }).join(" · "), I18n.revision)
                    visible: text !== ""
                    textStyle: "caption"
                    tone: "tertiary"
                    elide: Text.ElideRight
                }
            }
        }
        Keys.onReturnPressed: if (currentItem && currentItem.openable) root.doc.openAttachment(currentItem.key)
    }
    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.divider; visible: root.canEdit }
    PButton {
        objectName: "readerAddAttachment"
        Layout.alignment: Qt.AlignLeft
        Layout.margins: Metrics.s12
        visible: root.canEdit
        iconName: "add"
        text: I18n.tr("Datei anhängen …", I18n.revision)
        onClicked: root.doc.addAttachment()
    }
}
