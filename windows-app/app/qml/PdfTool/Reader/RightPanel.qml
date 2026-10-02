import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Rechte Seitenleiste: Kommentare oder Eigenschaften (»Objekt bearbeiten«). Umgeschaltet wird in ihrem
// Kopf (aufgebaut wie links), die geschlossene Leiste öffnet der Streifen am rechten Rand (PanelRail).
// Die Breite ist fest. Beim Schließen bleibt der Inhalt stehen, bis die Leiste weggeglitten ist.
Rectangle {
    id: root
    objectName: "readerRightPanel"
    property var doc: null
    readonly property string panel: Reader.rightPanel
    property string shown: "comments"
    onPanelChanged: if (panel !== "") shown = panel
    Component.onCompleted: if (panel !== "") shown = panel
    readonly property var titles: ({ comments: "Kommentare", properties: "Eigenschaften" })
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider; z: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        PanelHeader {
            title: root.titles[root.shown] || ""
            current: root.shown
            tabs: [
                { key: "comments", icon: "comment", tip: "Kommentare", name: "readerTabComments" },
                { key: "properties", icon: "text_font", tip: "Eigenschaften", name: "readerTabProperties" }
            ]
            onTabSelected: (key) => Reader.showRightPanel(key)
            onCloseRequested: Reader.setRightPanel(root.panel)
            PText {
                objectName: "readerCommentsCount"
                visible: root.shown === "comments" && root.doc !== null && root.doc.annotationList.count > 0
                text: root.doc ? String(root.doc.annotationList.count) : ""
                textStyle: "caption"
                tone: "secondary"
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            PanelContent { shown: root.shown === "comments" && root.visible; sourceComponent: CommentsPanel { doc: root.doc } }
            PanelContent { shown: root.shown === "properties" && root.visible; sourceComponent: ObjectPanel { doc: root.doc } }
        }
    }
}
