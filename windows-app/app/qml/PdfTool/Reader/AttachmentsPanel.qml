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
        title: "Keine Anhänge"
        text: "Dieses PDF enthält keine angehängten Dateien. Über »Datei anhängen« lässt sich eine Datei hinzufügen."
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
        Accessible.name: "Anhänge"

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
            Accessible.name: name + (sizeText !== "" ? ", " + sizeText : "")

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
                    PText { text: row.name; Layout.fillWidth: true; elide: Text.ElideMiddle }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "open"; tip: row.openable ? "Öffnen" : "Dieser Dateityp wird nicht geöffnet – nur speichern"; enabled: row.openable; onClicked: root.doc.openAttachment(row.key) }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "save"; tip: "Speichern unter …"; onClicked: root.doc.saveAttachment(row.key) }
                    PIconButton {
                        implicitWidth: 28
                        implicitHeight: 28
                        iconName: "delete"
                        tip: "Anhang entfernen"
                        visible: row.page < 0 && root.canEdit
                        onClicked: root.doc.removeAttachment(row.key)
                    }
                }
                PText {
                    Layout.fillWidth: true
                    visible: row.description !== ""
                    text: row.description
                    wrap: true
                    maximumLineCount: 3
                    elide: Text.ElideRight
                    tone: "secondary"
                }
                PText {
                    Layout.fillWidth: true
                    text: [row.sizeText, row.modified, row.page >= 0 ? "auf Seite " + (row.page + 1) : ""].filter(function(v) { return v !== "" }).join(" · ")
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
        text: "Datei anhängen …"
        onClicked: root.doc.addAttachment()
    }
}
