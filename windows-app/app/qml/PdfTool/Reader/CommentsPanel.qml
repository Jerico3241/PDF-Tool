import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Kommentare des Dokuments (alle Seiten): Art, Seite, Text, Verfasser und Datum. Klick springt zur
// Stelle; der Text lässt sich ändern, ein Kommentar löschen oder beantworten (Antworten stehen eingerückt
// darunter – wie in Acrobat, auch dort sichtbar). Vorhandene Kommentare anderer Programme bleiben erhalten,
// solange sie nicht ausdrücklich geändert oder gelöscht werden.
// Kopf (Titel, Anzahl, Schließen) und Breite kommen von der rechten Seitenleiste (RightPanel).
ColumnLayout {
    id: root
    objectName: "readerCommentsPanel"
    property var doc: null
    property string editingKey: ""
    property string replyingKey: ""  // Kommentar, auf den gerade geantwortet wird
    spacing: 0

    PEmptyState {
        objectName: "readerCommentsEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.doc !== null && root.doc.annotationList.count === 0
        iconName: "comment"
        title: I18n.tr("Noch keine Kommentare", I18n.revision)
        text: I18n.tr("Markieren, Notizen und Formen im Menüband unter »Kommentieren«.", I18n.revision)
    }
    ListView {
        id: list
        PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: count > 0
        model: root.doc ? root.doc.annotationList : null
        clip: true
        spacing: 2
        topMargin: 4
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: I18n.tr("Kommentare", I18n.revision)

        delegate: Item {
            id: row
            required property string key
            required property int page
            required property string label
            required property string contents
            required property string author
            required property string modified
            required property string color
            required property string subtype
            required property string replyTo
            required property int depth
            readonly property bool editing: root.editingKey === key
            readonly property bool replying: root.replyingKey === key
            readonly property bool chosen: root.doc !== null && root.doc.selectedObject.key === key
            width: list.width
            height: body.implicitHeight + 16
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(label + ", Seite " + (page + 1), I18n.revision)

            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
                selected: row.chosen
            }
            HoverHandler { id: hover }
            TapHandler {
                enabled: !row.editing
                onTapped: {
                    if (root.doc.tool !== "select") root.doc.setTool("select")  // setzt die Auswahl zurück
                    root.doc.goTo(row.page)
                    root.doc.selectedObject = { "kind": "annotation", "page": row.page, "key": row.key }
                }
            }
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 14 + row.depth * 20  // Antworten eingerückt
                anchors.rightMargin: 8
                anchors.topMargin: 8
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle { Layout.preferredWidth: 10; Layout.preferredHeight: 10; radius: 5; color: row.color !== "" ? row.color : Theme.neutral; border.color: Theme.border }
                    PText { text: I18n.tr(row.depth > 0 ? "Antwort" : row.label + " · Seite " + (row.page + 1), I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.fillWidth: true }
                    PIconButton { objectName: "readerCommentReply"; implicitWidth: 28; implicitHeight: 28; iconName: "comment"; tip: I18n.tr("Antworten", I18n.revision); visible: row.depth === 0 && !row.editing && !row.replying && row.subtype !== "/Link"; onClicked: { root.replyingKey = row.key; replyEditor.text = ""; replyEditor.area.forceActiveFocus() } }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "edit"; tip: I18n.tr("Text ändern", I18n.revision); visible: !row.editing && row.subtype !== "/Link"; onClicked: { root.editingKey = row.key; editor.text = row.contents; editor.area.forceActiveFocus() } }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "delete"; tip: I18n.tr("Kommentar löschen", I18n.revision); visible: !row.editing; onClicked: root.doc.deleteAnnotation(row.key) }
                }
                PText {
                    Layout.fillWidth: true
                    visible: !row.editing && row.contents !== ""
                    text: I18n.tr(row.contents, I18n.revision)
                    wrap: true
                    maximumLineCount: 6
                    elide: Text.ElideRight
                }
                PTextArea {
                    id: editor
                    Layout.fillWidth: true
                    visible: row.editing
                    minLines: 2
                    maxLines: 8
                    label: I18n.tr("Kommentartext", I18n.revision)
                }
                RowLayout {
                    visible: row.editing
                    Layout.alignment: Qt.AlignRight
                    PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: root.editingKey = "" }
                    PButton { kind: "accent"; text: I18n.tr("Speichern", I18n.revision); onClicked: { root.doc.updateAnnotation(row.key, editor.text, ""); root.editingKey = "" } }
                }
                PTextArea {
                    id: replyEditor
                    objectName: "readerCommentReplyText"
                    Layout.fillWidth: true
                    visible: row.replying
                    minLines: 2
                    maxLines: 6
                    label: I18n.tr("Antwort", I18n.revision)
                }
                RowLayout {
                    visible: row.replying
                    Layout.alignment: Qt.AlignRight
                    PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: root.replyingKey = "" }
                    PButton { objectName: "readerCommentReplySend"; kind: "accent"; text: I18n.tr("Antworten", I18n.revision); enabled: replyEditor.text.trim() !== ""; onClicked: { root.doc.replyAnnotation(row.key, replyEditor.text); root.replyingKey = "" } }
                }
                PText {
                    Layout.fillWidth: true
                    visible: row.author !== "" || row.modified !== ""
                    text: I18n.tr([row.author, row.modified].filter(function(v) { return v !== "" }).join(" · "), I18n.revision)
                    textStyle: "caption"
                    tone: "tertiary"
                    elide: Text.ElideRight
                }
            }
        }
    }
}
