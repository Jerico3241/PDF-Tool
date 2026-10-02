import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Tabs der geöffneten Dokumente: Name, Punkt bei ungespeicherten Änderungen, Schließen (×, mittlere
// Maustaste, Strg+W). Strg+Tab / Strg+Umschalt+Tab wechseln. »+« öffnet weitere PDFs.
// Bewegung: ein neuer Tab blendet ein und hebt sich leicht, ein geschlossener blendet aus, die übrigen
// rücken weich nach; die Markierung des aktiven Tabs gleitet zum neuen Tab. Der Punkt für »ungespeichert«
// blendet weich ein und aus (sein Platz ist immer reserviert – der Tab wird dabei nicht breiter).
// »Reduziert«: nur Überblenden, »Aus«: alles sofort.
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
            // aktiver Tab bleibt im Blick (auch bei vielen Tabs); seine Markierung folgt ihm (highlight)
            readonly property string activeKey: Reader.currentKey
            function revealActive() {
                var index = Reader.tabs.indexOf(activeKey)
                currentIndex = index
                if (index >= 0) positionViewAtIndex(index, ListView.Contain)
            }
            onActiveKeyChanged: Qt.callLater(revealActive)
            onCountChanged: Qt.callLater(revealActive)
            Component.onCompleted: revealActive()
            highlightFollowsCurrentItem: true
            highlightMoveDuration: Motion.indicator
            highlightMoveVelocity: -1
            highlightResizeDuration: Motion.indicator
            highlightResizeVelocity: -1
            highlight: Item {
                z: 2
                Rectangle {
                    objectName: "readerTabIndicator"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: Metrics.radiusControl
                    anchors.rightMargin: Metrics.radiusControl
                    height: 2
                    color: Theme.accent
                }
            }
            add: Transition {
                enabled: Motion.enabled
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                NumberAnimation { property: "y"; from: Motion.moves ? 6 : 0; to: 0; duration: Motion.fade; easing.type: Motion.decelerate }
            }
            remove: Transition {
                enabled: Motion.enabled
                NumberAnimation { property: "opacity"; to: 0; duration: Motion.fast; easing.type: Motion.accelerate }
            }
            displaced: Transition {
                enabled: Motion.moves
                NumberAnimation { properties: "x"; duration: Motion.expand; easing.type: Motion.decelerate }
            }

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
                        Layout.maximumWidth: Metrics.readerTabMaxWidth - 84
                        text: tab.name
                        font: tab.active ? Typography.bodyStrong : Typography.body
                        elide: Text.ElideMiddle
                    }
                    // ungespeichert: Punkt (Platz immer reserviert, damit der Tab nicht springt)
                    Rectangle {
                        objectName: "readerTabDirty"
                        Layout.preferredWidth: 6
                        Layout.preferredHeight: 6
                        radius: 3
                        color: tab.active ? Theme.textPrimary : Theme.textSecondary
                        opacity: tab.dirty ? 1 : 0
                        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
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
