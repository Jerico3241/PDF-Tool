import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Rechte Seitenleiste: Kommentare, Eigenschaften (»Objekt bearbeiten«) oder – eingeschaltet in den Einstellungen –
// der KI-Assistent. Umgeschaltet wird in ihrem Kopf (aufgebaut wie links), die geschlossene Leiste öffnet der Streifen
// am rechten Rand (PanelRail). Die Breite ist fest. Beim Schließen bleibt der Inhalt stehen, bis die Leiste weggeglitten
// ist.
Rectangle {
    id: root
    objectName: "readerRightPanel"
    property var doc: null
    readonly property string panel: Reader.rightPanel
    property string shown: "comments"
    onPanelChanged: if (panel !== "") shown = panel
    Component.onCompleted: if (panel !== "") shown = panel
    readonly property var titles: ({ comments: "Kommentare", properties: "Eigenschaften", assistant: "KI-Assistent" })
    readonly property var tabs: [
        { key: "comments", icon: "comment", tip: "Kommentare", name: "readerTabComments" },
        { key: "properties", icon: "text_font", tip: "Eigenschaften", name: "readerTabProperties" }
    ].concat(Assistant.enabled ? [{ key: "assistant", icon: "sparkle", tip: "KI-Assistent", name: "readerTabAssistant" }] : [])
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider; z: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        PanelHeader {
            title: root.titles[root.shown] || ""
            current: root.shown
            tabs: root.tabs
            onTabSelected: (key) => Reader.showRightPanel(key)
            onCloseRequested: Reader.setRightPanel(root.panel)
            PText {
                objectName: "readerCommentsCount"
                visible: root.shown === "comments" && root.doc !== null && root.doc.annotationList.count > 0
                text: root.doc ? String(root.doc.annotationList.count) : ""
                textStyle: "caption"
                tone: "secondary"
            }
            PIconButton {
                objectName: "readerAssistantClear"
                visible: root.shown === "assistant" && Assistant.state === "ready" && Assistant.conversationModel.count > 0
                implicitWidth: Metrics.readerPanelTab
                implicitHeight: Metrics.readerPanelTab
                iconName: "arrow_reset"
                tip: "Neues Gespräch"
                enabled: !Assistant.busy
                onClicked: Assistant.clear()
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            PanelContent { shown: root.shown === "comments" && root.visible; sourceComponent: CommentsPanel { doc: root.doc } }
            PanelContent { shown: root.shown === "properties" && root.visible; sourceComponent: ObjectPanel { doc: root.doc } }
            PanelContent { shown: root.shown === "assistant" && root.visible && Assistant.enabled; sourceComponent: AssistantPanel { doc: root.doc } }
        }
    }
}
