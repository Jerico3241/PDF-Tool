import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Ansichtswahl eines Werkzeugs (z. B. »Übersicht erstellen · Stapel · Darstellung · …«).
// Die Markierung gleitet zur gewählten Ansicht; Einträge erscheinen und verschwinden weich
// (Deckkraft + Breite), etwa »Kunden« beim Ein- und Ausschalten der Kundenakte.
// ``items``: Liste aus {key, label, available}
Item {
    id: root
    property var items: []
    property string current: ""
    signal selected(string key)

    implicitHeight: 40
    implicitWidth: row.implicitWidth
    activeFocusOnTab: true
    Accessible.role: Accessible.PageTabList
    Accessible.name: "Ansichten"

    property int focusIndex: -1
    function availableKeys() {
        var keys = []
        for (var i = 0; i < items.length; ++i)
            if (items[i].available !== false) keys.push(items[i].key)
        return keys
    }
    function step(delta) {
        var keys = availableKeys()
        if (keys.length === 0) return
        var start = focusIndex >= 0 ? focusIndex : Math.max(0, keys.indexOf(current))
        focusIndex = (start + delta + keys.length) % keys.length
    }
    Keys.onLeftPressed: step(-1)
    Keys.onRightPressed: step(1)
    Keys.onReturnPressed: { var keys = availableKeys(); if (focusIndex >= 0 && focusIndex < keys.length) root.selected(keys[focusIndex]) }
    Keys.onSpacePressed: { var keys = availableKeys(); if (focusIndex >= 0 && focusIndex < keys.length) root.selected(keys[focusIndex]) }
    onActiveFocusChanged: focusIndex = activeFocus ? Math.max(0, availableKeys().indexOf(current)) : -1

    Row {
        id: row
        height: parent.height
        spacing: 4
        Repeater {
            id: repeater
            model: root.items
            Item {
                id: entry
                required property var modelData
                required property int index
                readonly property bool available: modelData.available !== false
                readonly property bool isCurrent: modelData.key === root.current
                readonly property bool keyboardFocus: root.activeFocus && root.focusIndex >= 0 && root.availableKeys()[root.focusIndex] === modelData.key
                height: row.height
                width: available ? label.implicitWidth + 24 : 0
                opacity: available ? 1 : 0
                visible: width > 0.5
                clip: width < label.implicitWidth + 24
                Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
                Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade } }
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.label
                Accessible.selected: isCurrent

                Rectangle {
                    anchors.fill: parent
                    anchors.topMargin: 2
                    anchors.bottomMargin: 6
                    radius: Metrics.radiusControl
                    color: mouse.pressed ? Theme.subtlePressed : (mouse.containsMouse ? Theme.subtleHover : "transparent")
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                    PFocusRing { visible: entry.keyboardFocus }
                }
                Text {
                    id: label
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -2
                    text: entry.modelData.label
                    font: entry.isCurrent ? Typography.bodyStrong : Typography.body
                    color: entry.isCurrent ? Theme.textPrimary : Theme.textSecondary
                    textFormat: Text.PlainText
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.selected(entry.modelData.key)
                }
            }
        }
    }
    // Markierung unter der gewählten Ansicht
    Rectangle {
        id: indicator
        property Item target: {
            for (var i = 0; i < repeater.count; ++i) {
                var item = repeater.itemAt(i)
                if (item && item.isCurrent && item.available) return item
            }
            return null
        }
        visible: target !== null
        height: 3
        radius: 1.5
        color: Theme.accent
        y: root.height - 6
        x: target ? target.x + (target.width - width) / 2 : 0
        width: target ? Math.max(16, Math.min(target.width - 24, 24)) : 0
        Behavior on x { enabled: Motion.moves; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
    }
}
