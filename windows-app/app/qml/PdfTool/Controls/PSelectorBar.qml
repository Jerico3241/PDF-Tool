import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Ansichtswahl eines Werkzeugs (z. B. »Übersicht erstellen · Stapel · Darstellung · …«).
// Die Markierung gleitet zur gewählten Ansicht; Einträge erscheinen und verschwinden weich
// (Deckkraft + Breite), etwa »Kunden« beim Ein- und Ausschalten der Kundenakte.
// ``items``: Liste aus {key, label, available}; ``hiddenKeys``: gerade ausgeblendete Einträge –
// die Liste selbst bleibt dabei unverändert, damit Einträge weich aus- und einblenden.
// Reicht die Breite nicht für alle Ansichten, lässt sich die Leiste waagerecht verschieben; die
// gewählte (und die per Tastatur markierte) Ansicht rückt dabei immer ganz ins Bild.
Item {
    id: root
    property var items: []
    property var hiddenKeys: []
    property string current: ""
    signal selected(string key)

    function isAvailable(entry) {
        return entry.available !== false && hiddenKeys.indexOf(entry.key) < 0
    }

    implicitHeight: 40
    implicitWidth: row.implicitWidth
    activeFocusOnTab: true
    Accessible.role: Accessible.PageTabList
    Accessible.name: "Ansichten"

    property int focusIndex: -1
    // Der Repeater meldet ``count``, bevor er die Einträge erzeugt (Seiten entstehen im Hintergrund):
    // ``itemsRevision`` lässt die Markierung ihr Ziel neu suchen, sobald die Einträge da sind.
    property int itemsRevision: 0
    function availableKeys() {
        var keys = []
        for (var i = 0; i < items.length; ++i)
            if (isAvailable(items[i])) keys.push(items[i].key)
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
    onFocusIndexChanged: if (focusIndex >= 0) Qt.callLater(revealKey, availableKeys()[focusIndex])
    onCurrentChanged: Qt.callLater(revealKey, current)
    onWidthChanged: Qt.callLater(revealKey, current)

    readonly property bool overflowing: row.width > root.width + 0.5
    // Ansicht ``key`` ganz in den sichtbaren Bereich holen (nur bei zu schmaler Leiste)
    function revealKey(key) {
        if (!overflowing) { flick.contentX = 0; return }
        for (var i = 0; i < repeater.count; ++i) {
            var item = repeater.itemAt(i)
            if (!item || item.modelData.key !== key) continue
            var left = item.x - 24
            var right = item.x + item.width + 24
            var target = flick.contentX
            if (left < flick.contentX) target = left
            else if (right > flick.contentX + flick.width) target = right - flick.width
            target = Math.max(0, Math.min(row.width - flick.width, target))
            if (Math.abs(target - flick.contentX) < 1) return
            if (Motion.moves) { scrollAnim.to = target; scrollAnim.restart() } else flick.contentX = target
            return
        }
    }
    NumberAnimation { id: scrollAnim; target: flick; property: "contentX"; duration: Motion.indicator; easing.type: Motion.decelerate }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: row.width
        contentHeight: height
        flickableDirection: Flickable.HorizontalFlick
        boundsBehavior: Flickable.StopAtBounds
        interactive: root.overflowing
        clip: root.overflowing

        Row {
            id: row
            height: flick.height
            spacing: 4
            Repeater {
                id: repeater
                model: root.items
                onItemAdded: root.itemsRevision += 1
                onItemRemoved: root.itemsRevision += 1
                Item {
                    id: entry
                    required property var modelData
                    required property int index
                    readonly property bool available: root.isAvailable(modelData)
                    readonly property bool isCurrent: modelData.key === root.current
                    readonly property bool keyboardFocus: root.activeFocus && root.focusIndex >= 0 && root.availableKeys()[root.focusIndex] === modelData.key
                    // Breite für die fette Schrift der gewählten Ansicht – beim Wechsel springt nichts
                    readonly property real fullWidth: Math.ceil(Math.max(label.implicitWidth, strongWidth.advanceWidth)) + 24
                    TextMetrics { id: strongWidth; font: Typography.bodyStrong; text: entry.modelData.label }
                    height: row.height
                    width: available ? fullWidth : 0
                    opacity: available ? 1 : 0
                    visible: width > 0.5
                    clip: width < fullWidth
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
    }
    // Ränder andeuten, wenn weitere Ansichten außerhalb liegen
    Rectangle {
        visible: root.overflowing && flick.contentX > 1
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        width: 24
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Theme.layer }
            GradientStop { position: 1; color: "transparent" }
        }
    }
    Rectangle {
        visible: root.overflowing && flick.contentX < row.width - flick.width - 1
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        width: 24
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "transparent" }
            GradientStop { position: 1; color: Theme.layer }
        }
    }
    // Markierung unter der gewählten Ansicht
    Rectangle {
        id: indicator
        parent: flick.contentItem  // verschiebt sich mit den Einträgen
        property Item target: {
            root.itemsRevision
            for (var i = 0; i < repeater.count; ++i) {
                var item = repeater.itemAt(i)
                if (item && item.isCurrent && item.available) return item
            }
            return null
        }
        objectName: "selectorIndicator"
        // erst nach der ersten Lage gleiten – nicht beim Aufbau von links herein
        property bool placed: false
        onTargetChanged: if (target !== null && !placed) Qt.callLater(function() { indicator.placed = true })
        visible: target !== null
        height: 3
        radius: 1.5
        color: Theme.accent
        y: row.height - 6
        x: target ? target.x + (target.width - width) / 2 : 0
        width: target ? Math.max(16, Math.min(target.width - 24, 24)) : 0
        Behavior on x { enabled: Motion.moves && indicator.placed; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on width { enabled: Motion.moves && indicator.placed; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
    }
}
