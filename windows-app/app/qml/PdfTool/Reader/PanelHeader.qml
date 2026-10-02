import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// Kopf einer Reader-Seitenleiste – in allen Leisten gleich aufgebaut: Titel links (wechselt weich),
// Zusätze wie eine Anzahl daneben, rechts die Umschalter dieser Leiste (PanelTabs) und Schließen;
// feste Höhe, gleiche Innenabstände, Trennlinie darunter.
Item {
    id: root
    property string title: ""
    property var tabs: []           // [{key, icon, tip, name}] – Inhalte dieser Seitenleiste
    property string current: ""
    default property alias extra: trailing.data
    signal tabSelected(string key)
    signal closeRequested()

    implicitHeight: Metrics.readerPanelHeaderHeight
    Layout.fillWidth: true
    Layout.preferredHeight: implicitHeight

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Metrics.s16
        anchors.rightMargin: Metrics.s8
        spacing: Metrics.s4
        PCrossfadeText {
            objectName: "readerPanelTitle"
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: root.title
            font: Typography.bodyStrong
        }
        RowLayout { id: trailing; spacing: Metrics.s4 }
        PanelTabs {
            Layout.leftMargin: Metrics.s4
            visible: root.tabs.length > 1
            tabs: root.tabs
            current: root.current
            onSelected: (key) => root.tabSelected(key)
        }
        PIconButton {
            objectName: "readerPanelClose"
            Layout.leftMargin: Metrics.s2
            implicitWidth: Metrics.readerPanelTab
            implicitHeight: Metrics.readerPanelTab
            iconName: "dismiss"
            tip: "Seitenleiste schließen"
            onClicked: root.closeRequested()
        }
    }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }
}
