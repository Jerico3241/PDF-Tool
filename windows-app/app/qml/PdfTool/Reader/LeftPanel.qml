import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Linke Seitenleiste: Miniaturen, Lesezeichen oder Suche (umschaltbar; die Wahl bleibt gespeichert).
Rectangle {
    id: root
    objectName: "readerLeftPanel"
    property var doc: null
    readonly property string panel: Reader.leftPanel
    color: Theme.layer
    Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider }

    component PanelTab: PButton {
        property string panelKey: ""
        kind: "subtle"
        checkable: true
        checked: root.panel === panelKey
        Layout.fillWidth: true
        onClicked: if (root.panel !== panelKey) Reader.setLeftPanel(panelKey)
        Accessible.role: Accessible.PageTab
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.rightMargin: 1
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 4
            Layout.rightMargin: 4
            Layout.topMargin: 4
            spacing: 2
            PanelTab { panelKey: "thumbs"; iconName: "document_one_page_multiple"; tip: "Miniaturen" }
            PanelTab { panelKey: "outline"; iconName: "bookmark"; tip: "Lesezeichen" }
            PanelTab { panelKey: "search"; iconName: "search"; tip: "Suchen (Strg+F)" }
            PIconButton { iconName: "dismiss"; tip: "Seitenleiste schließen"; onClicked: Reader.setLeftPanel(root.panel) }
        }
        PText {
            Layout.fillWidth: true
            Layout.leftMargin: 12
            Layout.topMargin: 4
            text: root.panel === "thumbs" ? "Seiten" : (root.panel === "outline" ? "Lesezeichen" : "Suchen")
            textStyle: "bodyStrong"
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            // Nur die gezeigte Leiste existiert (versteckte Miniaturen würden sonst gerendert)
            Loader { anchors.fill: parent; active: root.panel === "thumbs"; sourceComponent: ThumbnailPanel { doc: root.doc } }
            Loader { anchors.fill: parent; active: root.panel === "outline"; sourceComponent: OutlinePanel { doc: root.doc } }
            Loader { anchors.fill: parent; active: root.panel === "search"; sourceComponent: SearchPanel { doc: root.doc } }
        }
    }
}
