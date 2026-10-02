import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Controls

// Umschalter im Kopf einer Seitenleiste: kleine Symbol-Reiter (der Name steht im Tooltip). Der gewählte
// Reiter liegt auf einer zurückhaltenden Akzentfläche mit Akzentsymbol; die Fläche gleitet zum neu
// gewählten Reiter (»Reduziert«/»Aus«: ohne Weg). Ein Klick auf den gewählten Reiter ändert nichts.
Item {
    id: root
    property var tabs: []           // [{key, icon, tip, name}]
    property string current: ""
    signal selected(string key)

    implicitWidth: row.implicitWidth
    implicitHeight: Metrics.readerPanelTab
    Accessible.role: Accessible.PageTabList

    // Akzentfläche des gewählten Reiters (unter den Reitern; alle Reiter sind gleich breit)
    Rectangle {
        id: selection
        readonly property int index: {
            for (var i = 0; i < root.tabs.length; ++i)
                if (root.tabs[i].key === root.current) return i
            return -1
        }
        objectName: "readerPanelTabSelection"
        width: Metrics.readerPanelTab
        height: Metrics.readerPanelTab
        radius: Metrics.radiusControl
        color: Theme.selectedSubtle
        x: index >= 0 ? index * (Metrics.readerPanelTab + row.spacing) : x
        opacity: index >= 0 ? 1 : 0
        Behavior on x { enabled: Motion.moves && selection.opacity > 0.5; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
    }

    Row {
        id: row
        spacing: 2
        Repeater {
            model: root.tabs
            T.AbstractButton {
                id: tab
                required property var modelData
                readonly property bool active: root.current === modelData.key
                objectName: modelData.name || ""
                width: Metrics.readerPanelTab
                height: Metrics.readerPanelTab
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.tip
                Accessible.selected: active
                onClicked: root.selected(modelData.key)
                Keys.onReturnPressed: root.selected(modelData.key)
                Keys.onEnterPressed: root.selected(modelData.key)
                background: Rectangle {
                    radius: Metrics.radiusControl
                    color: tab.pressed ? Theme.subtlePressed : (tab.hovered ? Theme.subtleHover : "transparent")
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                    PFocusRing { visible: tab.visualFocus; inset: -1 }
                }
                contentItem: Item {
                    PIcon {
                        anchors.centerIn: parent
                        name: tab.modelData.icon
                        color: tab.active ? Theme.accent : Theme.textSecondary
                    }
                }
                PToolTip {
                    text: tab.modelData.tip
                    visible: tab.hovered && !tab.pressed
                    x: (tab.width - implicitWidth) / 2
                    y: tab.height + Metrics.s4
                }
            }
        }
    }
}
