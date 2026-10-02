import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Tabs der geöffneten Dokumente: Name, »*« bei ungespeicherten Änderungen, Schließen (×, mittlere
// Maustaste, Strg+W). Strg+Tab / Strg+Umschalt+Tab wechseln. »+« öffnet weitere PDFs.
Rectangle {
    id: root
    objectName: "readerTabs"
    implicitHeight: Metrics.readerTabHeight + 4
    color: Theme.layer

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.topMargin: 4
        spacing: 2
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.preferredWidth: contentWidth
            Layout.maximumWidth: contentWidth
            Layout.fillHeight: true
            orientation: ListView.Horizontal
            model: Reader.tabs
            spacing: 2
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Accessible.role: Accessible.PageTabList
            Accessible.name: "Geöffnete Dokumente"
            // aktiver Tab bleibt im Blick (auch bei vielen Tabs)
            readonly property string activeKey: Reader.currentKey
            function revealActive() {
                var index = Reader.tabs.indexOf(activeKey)
                if (index >= 0) positionViewAtIndex(index, ListView.Contain)
            }
            onActiveKeyChanged: Qt.callLater(revealActive)
            onCountChanged: Qt.callLater(revealActive)

            delegate: Item {
                id: tab
                required property string key
                required property string name
                required property bool dirty
                required property string tip
                required property int index
                readonly property bool active: Reader.currentKey === key
                width: Math.min(Metrics.readerTabMaxWidth, row.implicitWidth + 20)
                height: list.height
                objectName: "readerTab_" + index
                Accessible.role: Accessible.PageTab
                Accessible.name: name + (dirty ? " (ungespeichert)" : "")
                Accessible.selected: active

                Rectangle {
                    anchors.fill: parent
                    anchors.bottomMargin: -Metrics.radiusControl
                    radius: Metrics.radiusControl
                    color: tab.active ? Theme.surface : (hover.hovered ? Theme.subtleHover : "transparent")
                    border.width: tab.active ? 1 : 0
                    border.color: Theme.border
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                }
                Rectangle {
                    visible: tab.active
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: Metrics.radiusControl
                    anchors.rightMargin: Metrics.radiusControl
                    height: 2
                    color: Theme.accent
                }
                HoverHandler { id: hover }
                TapHandler {
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    onTapped: (point, button) => {
                        if (button === Qt.MiddleButton) Reader.closeTab(tab.key)
                        else Reader.activate(tab.key)
                    }
                }
                RowLayout {
                    id: row
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 4
                    spacing: 6
                    PIcon { name: "document_pdf"; color: tab.active ? Theme.accent : Theme.textSecondary }
                    PText {
                        Layout.fillWidth: true
                        Layout.maximumWidth: Metrics.readerTabMaxWidth - 76
                        text: tab.name + (tab.dirty ? " *" : "")
                        font: tab.active ? Typography.bodyStrong : Typography.body
                        elide: Text.ElideMiddle
                    }
                    PIconButton {
                        objectName: "readerTabClose"
                        implicitWidth: 24
                        implicitHeight: 24
                        iconName: "dismiss"
                        tip: "Schließen (Strg+W)"
                        onClicked: Reader.closeTab(tab.key)
                    }
                }
                PToolTip { text: tab.tip; visible: hover.hovered }
            }
        }
        PIconButton {
            objectName: "readerTabAdd"
            iconName: "add"
            tip: "PDF öffnen (Strg+O)"
            onClicked: Reader.openDialog()
        }
        Item { Layout.fillWidth: true }
    }
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider; z: -1 }
}
