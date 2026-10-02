import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Kommentare des Dokuments (alle Seiten): Art, Seite, Text, Verfasser und Datum. Klick springt zur
// Stelle; der Text lässt sich ändern, ein Kommentar löschen. Vorhandene Kommentare anderer
// Programme bleiben erhalten, solange sie nicht ausdrücklich geändert oder gelöscht werden.
ColumnLayout {
    id: root
    objectName: "readerCommentsPanel"
    property var doc: null
    property string editingKey: ""
    spacing: 0

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 4
        Layout.preferredHeight: Metrics.controlHeight + 12
        PText { text: "Kommentare"; textStyle: "bodyStrong"; Layout.fillWidth: true }
        PText { text: root.doc ? String(root.doc.annotationList.count) : ""; textStyle: "caption"; tone: "secondary" }
        PIconButton { iconName: "dismiss"; tip: "Seitenleiste schließen"; onClicked: Reader.setRightPanel("comments") }
    }
    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.divider }
    PText {
        Layout.fillWidth: true
        Layout.margins: 16
        visible: root.doc !== null && root.doc.annotationList.count === 0
        text: "Noch keine Kommentare. Markieren, Notizen und Formen über »Kommentieren« und »Zeichnen« in der Befehlsleiste."
        tone: "secondary"
        wrap: true
    }
    ListView {
        id: list
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: root.doc ? root.doc.annotationList : null
        clip: true
        spacing: 2
        topMargin: 4
        bottomMargin: 8
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: "Kommentare"

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
            readonly property bool editing: root.editingKey === key
            readonly property bool chosen: root.doc !== null && root.doc.selectedObject.key === key
            width: list.width
            height: body.implicitHeight + 16
            Accessible.role: Accessible.ListItem
            Accessible.name: label + ", Seite " + (page + 1)

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
                anchors.leftMargin: 14
                anchors.rightMargin: 8
                anchors.topMargin: 8
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Rectangle { Layout.preferredWidth: 10; Layout.preferredHeight: 10; radius: 5; color: row.color !== "" ? row.color : Theme.neutral; border.color: Theme.border }
                    PText { text: row.label + " · Seite " + (row.page + 1); textStyle: "caption"; tone: "secondary"; Layout.fillWidth: true }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "edit"; tip: "Text ändern"; visible: !row.editing && row.subtype !== "/Link"; onClicked: { root.editingKey = row.key; editor.text = row.contents; editor.area.forceActiveFocus() } }
                    PIconButton { implicitWidth: 28; implicitHeight: 28; iconName: "delete"; tip: "Kommentar löschen"; visible: !row.editing; onClicked: root.doc.deleteAnnotation(row.key) }
                }
                PText {
                    Layout.fillWidth: true
                    visible: !row.editing && row.contents !== ""
                    text: row.contents
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
                    label: "Kommentartext"
                }
                RowLayout {
                    visible: row.editing
                    Layout.alignment: Qt.AlignRight
                    PButton { text: "Abbrechen"; onClicked: root.editingKey = "" }
                    PButton { kind: "accent"; text: "Speichern"; onClicked: { root.doc.updateAnnotation(row.key, editor.text, ""); root.editingKey = "" } }
                }
                PText {
                    Layout.fillWidth: true
                    visible: row.author !== "" || row.modified !== ""
                    text: [row.author, row.modified].filter(function(v) { return v !== "" }).join(" · ")
                    textStyle: "caption"
                    tone: "tertiary"
                    elide: Text.ElideRight
                }
            }
        }
    }
}
