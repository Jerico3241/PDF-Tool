import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Navigationsbereich links (auf Mica): Start, Tools, Einstellungen. Die Markierung gleitet zum
// gewählten Eintrag; ausgeklappt/kompakt wechselt mit einer Breitenanimation, Texte blenden
// weich ein und aus, die Symbole bleiben an ihrem Platz.
FocusScope {
    id: pane
    property bool expanded: true
    property real amount: expanded ? 1 : 0
    signal toggleRequested()

    width: Metrics.paneCompact + (Metrics.paneExpanded - Metrics.paneCompact) * amount
    Behavior on amount { enabled: Motion.moves; NumberAnimation { duration: Motion.pane; easing.type: Motion.decelerate } }
    Accessible.role: Accessible.Pane
    Accessible.name: "Navigation"

    readonly property string selectedKey: {
        var page = App.currentPage
        if (page === "home" || page === "settings") return page
        return App.currentTool !== "" ? App.currentTool : page
    }
    readonly property var mainItems: {
        var items = [{ key: "home", label: "Start", icon: "home", header: false }, { key: "tools", label: "Tools", icon: "", header: true }]
        var tools = App.tools
        for (var i = 0; i < tools.length; ++i)
            items.push({ key: tools[i].key, label: tools[i].title, icon: tools[i].icon, header: false })
        return items
    }

    function itemFor(key) {
        for (var i = 0; i < mainRepeater.count; ++i) {
            var item = mainRepeater.itemAt(i)
            if (item && item.key === key) return item
        }
        return key === "settings" ? settingsItem : null
    }
    function focusable() {
        var list = [toggle]
        for (var i = 0; i < mainRepeater.count; ++i) {
            var item = mainRepeater.itemAt(i)
            if (item && !item.header) list.push(item)
        }
        list.push(settingsItem)
        return list
    }
    function moveFocus(delta) {
        var list = focusable()
        for (var i = 0; i < list.length; ++i) {
            if (list[i].activeFocus) {
                list[(i + delta + list.length) % list.length].forceActiveFocus(Qt.TabFocusReason)
                return
            }
        }
    }
    Keys.onUpPressed: moveFocus(-1)
    Keys.onDownPressed: moveFocus(1)

    component NavEntry: T.AbstractButton {
        id: entry
        property string key: ""
        property string label: ""
        property string iconName: ""
        property bool header: false
        readonly property bool selected: key === pane.selectedKey
        width: pane.width
        height: header ? Metrics.navHeaderHeight : Metrics.navItemHeight
        focusPolicy: header ? Qt.NoFocus : Qt.TabFocus
        enabled: !header
        hoverEnabled: true
        Accessible.role: header ? Accessible.StaticText : Accessible.PageTab
        Accessible.name: label
        Accessible.selected: selected
        onClicked: App.navigate(key)
        Keys.onReturnPressed: App.navigate(key)
        Keys.onSpacePressed: App.navigate(key)

        background: Rectangle {
            visible: !entry.header
            x: 4
            width: entry.width - 8
            height: entry.height
            radius: Metrics.radiusControl
            color: entry.pressed ? Theme.subtlePressed : ((entry.hovered || entry.selected) ? Theme.subtleHover : "transparent")
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            PFocusRing { visible: entry.visualFocus; inset: -1 }
        }
        contentItem: Item {
            PIcon {
                x: 16
                anchors.verticalCenter: parent.verticalCenter
                name: entry.iconName
                size: Metrics.iconSize
                visible: !entry.header && entry.iconName !== ""
            }
            Text {
                x: entry.header ? 16 : 48
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: entry.header ? 3 : 0
                width: Math.max(0, pane.width - x - 12)
                text: entry.label
                font: entry.header ? Typography.bodyStrong : Typography.body
                color: entry.header ? Theme.textSecondary : Theme.textPrimary
                opacity: pane.amount
                visible: opacity > 0.01
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }
            // Kompakt: Abschnittsüberschrift wird zur Trennlinie
            Rectangle {
                visible: entry.header
                x: 12
                width: pane.width - 24
                height: 1
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: 3
                color: Theme.divider
                opacity: 1 - pane.amount
            }
        }
        PToolTip {
            text: entry.label
            visible: !entry.header && entry.hovered && pane.amount < 0.5
            x: pane.width + 4
            y: (entry.height - implicitHeight) / 2
        }
    }

    // Menüschaltfläche und App-Name
    PIconButton {
        id: toggle
        x: 8
        y: 4
        width: 36
        height: Metrics.navItemHeight
        iconName: "navigation"
        tip: pane.expanded ? "Navigation einklappen" : "Navigation ausklappen"
        focusPolicy: Qt.TabFocus
        onClicked: pane.toggleRequested()
    }
    Text {
        x: 56
        anchors.verticalCenter: toggle.verticalCenter
        width: Math.max(0, pane.width - x - 12)
        text: App.appName
        font: Typography.caption
        color: Theme.textPrimary
        opacity: pane.amount
        visible: opacity > 0.01
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }

    Column {
        id: mainColumn
        y: toggle.y + toggle.height + 8
        width: pane.width
        spacing: 4
        Repeater {
            id: mainRepeater
            model: pane.mainItems
            NavEntry {
                required property var modelData
                key: modelData.key
                label: modelData.label
                iconName: modelData.icon
                header: modelData.header
            }
        }
    }

    NavEntry {
        id: settingsItem
        y: pane.height - height - 8
        key: "settings"
        label: "Einstellungen"
        iconName: "settings"
    }

    // Markierung des gewählten Eintrags – gleitet zum neuen Eintrag
    Rectangle {
        id: indicator
        readonly property Item target: pane.itemFor(pane.selectedKey)
        readonly property real targetY: target ? target.y + (target === settingsItem ? 0 : mainColumn.y) + (target.height - 16) / 2 : 0
        visible: target !== null
        x: 4
        width: 3
        height: 16
        radius: 1.5
        color: Theme.accent
        y: targetY
        Behavior on y { enabled: Motion.moves; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
    }
}
