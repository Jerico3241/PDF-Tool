import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Kommentare eines Textes (seit 5.0 Beta 5) – rechts neben der Seite wie die Formatvorlagen. Oben »Neuer Kommentar«
// (zur Auswahl bzw. an der Schreibmarke), darunter die Kommentare in Lesereihenfolge mit Verfasser und Datum, Antworten
// eingerückt. Klick springt zur Stelle im Text; Antworten, als erledigt markieren, Text ändern, löschen. Erledigte
// Kommentare stehen blasser da; der kommentierte Text ist im Dokument gelb hinterlegt.
ColumnLayout {
    id: root
    objectName: "textCommentsPanel"
    property var doc: null
    property string editingId: ""
    property string replyingId: ""
    property bool composing: false
    readonly property var entries: doc ? doc.comments : []
    signal done()
    spacing: 0

    function compose() {
        composing = true
        newField.text = ""
        Qt.callLater(function() { newField.area.forceActiveFocus() })
    }
    Connections {
        target: root.doc
        function onCommentRequested() { root.compose() }
    }

    // Neuer Kommentar -----------------------------------------------------------------------------------------------
    ColumnLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        Layout.topMargin: 12
        Layout.bottomMargin: 8
        spacing: 8
        PButton {
            objectName: "textCommentNew"
            Layout.fillWidth: true
            visible: !root.composing
            iconName: "comment_add"
            text: I18n.tr("Neuer Kommentar", I18n.revision)
            enabled: root.doc !== null && root.doc.ready
            onClicked: root.compose()
        }
        PTextArea {
            id: newField
            objectName: "textCommentNewText"
            Layout.fillWidth: true
            visible: root.composing
            minLines: 3
            maxLines: 8
            label: I18n.tr("Kommentar", I18n.revision)
            placeholderText: I18n.tr("Kommentar zur Auswahl schreiben …", I18n.revision)
        }
        RowLayout {
            visible: root.composing
            Layout.alignment: Qt.AlignRight
            spacing: 8
            PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: { root.composing = false; root.done() } }
            PButton {
                objectName: "textCommentNewSend"
                kind: "accent"
                text: I18n.tr("Hinzufügen", I18n.revision)
                enabled: newField.text.trim() !== ""
                onClicked: { root.doc.addComment(newField.text); root.composing = false; root.done() }
            }
        }
    }
    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.divider }

    PEmptyState {
        objectName: "textCommentsEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.entries.length === 0
        iconName: "comment"
        title: I18n.tr("Noch keine Kommentare", I18n.revision)
        text: I18n.tr("Text markieren und »Neuer Kommentar« wählen – der Kommentar steht dann hier.", I18n.revision)
    }
    ListView {
        id: list
        objectName: "textCommentsList"
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
        Accessible.name: I18n.tr("Kommentare", I18n.revision)

        delegate: Item {
            id: row
            required property var modelData
            required property int index
            readonly property string ident: modelData.id
            readonly property bool editing: root.editingId === ident
            readonly property bool replying: root.replyingId === ident
            width: list.width
            height: body.implicitHeight + 16
            opacity: modelData.resolved ? 0.6 : 1
            Accessible.role: Accessible.ListItem
            Accessible.name: I18n.tr(modelData.author + ": " + modelData.text, I18n.revision)

            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
            }
            HoverHandler { id: hover }
            TapHandler {
                enabled: !row.editing && !row.replying
                onTapped: root.doc.goToComment(row.ident)
            }
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 14 + (row.modelData.reply ? 20 : 0)
                anchors.rightMargin: 8
                anchors.topMargin: 8
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle {
                        Layout.preferredWidth: 24
                        Layout.preferredHeight: 24
                        radius: 12
                        color: Theme.selectedSubtle
                        PText {
                            anchors.centerIn: parent
                            text: I18n.tr(row.modelData.author.trim().charAt(0).toUpperCase(), I18n.revision)
                            textStyle: "caption"
                            font.weight: Font.DemiBold
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PText { Layout.fillWidth: true; text: I18n.tr(row.modelData.author, I18n.revision); font.weight: Font.DemiBold; elide: Text.ElideRight }
                        PText { Layout.fillWidth: true; text: I18n.tr(row.modelData.date, I18n.revision); textStyle: "caption"; tone: "tertiary"; visible: text !== ""; elide: Text.ElideRight }
                    }
                    PBadge { text: I18n.tr("Erledigt", I18n.revision); tone: "success"; visible: row.modelData.resolved && !row.modelData.reply }
                }
                PText {
                    Layout.fillWidth: true
                    visible: !row.editing
                    text: I18n.tr(row.modelData.text, I18n.revision)
                    wrap: true
                    maximumLineCount: 8
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
                    PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: root.editingId = "" }
                    PButton { kind: "accent"; text: I18n.tr("Speichern", I18n.revision); enabled: editor.text.trim() !== ""; onClicked: { root.doc.editComment(row.ident, editor.text); root.editingId = "" } }
                }
                PTextArea {
                    id: replyEditor
                    objectName: "textCommentReplyText"
                    Layout.fillWidth: true
                    visible: row.replying
                    minLines: 2
                    maxLines: 6
                    label: I18n.tr("Antwort", I18n.revision)
                }
                RowLayout {
                    visible: row.replying
                    Layout.alignment: Qt.AlignRight
                    PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: root.replyingId = "" }
                    PButton { objectName: "textCommentReplySend"; kind: "accent"; text: I18n.tr("Antworten", I18n.revision); enabled: replyEditor.text.trim() !== ""; onClicked: { root.doc.replyComment(row.ident, replyEditor.text); root.replyingId = "" } }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: !row.editing && !row.replying
                    spacing: 2
                    Item { Layout.fillWidth: true }
                    PIconButton { objectName: "textCommentReply"; implicitWidth: 28; implicitHeight: 28; iconName: "comment"; tip: I18n.tr("Antworten", I18n.revision); visible: !row.modelData.reply; onClicked: { root.replyingId = row.ident; replyEditor.text = ""; replyEditor.area.forceActiveFocus() } }
                    PIconButton { objectName: "textCommentResolve"; implicitWidth: 28; implicitHeight: 28; iconName: "comment_checkmark"; tip: I18n.tr(row.modelData.resolved ? "Wieder öffnen" : "Als erledigt markieren", I18n.revision); visible: !row.modelData.reply; onClicked: root.doc.resolveComment(row.ident) }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "edit"; tip: I18n.tr("Text ändern", I18n.revision); onClicked: { root.editingId = row.ident; editor.text = row.modelData.text; editor.area.forceActiveFocus() } }
                    PIconButton { objectName: "textCommentDelete"; implicitWidth: 28; implicitHeight: 28; iconName: "delete"; tip: I18n.tr("Kommentar löschen", I18n.revision); onClicked: root.doc.deleteComment(row.ident) }
                }
            }
        }
    }
}
