import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// Streifen am rechten Rand (seit 5.0 Beta 3, gleich für PDFs und Texte): die Inhalte der Seitenleiste als Symbole
// untereinander. Ein Klick öffnet die Seitenleiste daneben mit diesem Inhalt, ein Klick auf den gezeigten schließt
// sie. Der gezeigte Inhalt ist markiert (Fläche und Akzentstrich zur Seitenleiste hin). Gruppen trennt ein Strich (``separator``).
Rectangle {
    id: root
    objectName: "sideRail"
    property var items: []          // [{key, icon, tip, name, separator}]
    property string current: ""     // gezeigter Inhalt ("" = Seitenleiste zu)
    property color accentColor: Theme.accent
    property string side: "right"   // Seite des Fensters; Trennlinie und Akzentstrich liegen zur Seitenleiste hin
    signal selected(string key)

    implicitWidth: Metrics.readerRailWidth
    color: Theme.layer
    Accessible.role: Accessible.PageTabList
    Accessible.name: I18n.tr("Seitenleiste", I18n.revision)
    Rectangle { x: root.side === "right" ? 0 : root.width - 1; width: 1; height: parent.height; color: Theme.divider }

    Column {
        x: (root.width - Metrics.readerRailButton) / 2
        y: Metrics.s8
        spacing: Metrics.s4
        Repeater {
            model: root.items
            Column {
                id: entry
                required property var modelData
                spacing: Metrics.s4
                Rectangle {
                    visible: entry.modelData.separator === true
                    x: 6
                    width: Metrics.readerRailButton - 12
                    height: visible ? 1 : 0
                    color: Theme.divider
                }
                T.AbstractButton {
                    id: button
                    objectName: entry.modelData.name || ""
                    readonly property bool selected: root.current === entry.modelData.key
                    width: Metrics.readerRailButton
                    height: Metrics.readerRailButton
                    hoverEnabled: true
                    focusPolicy: Qt.TabFocus
                    checkable: false
                    checked: selected
                    Accessible.role: Accessible.PageTab
                    Accessible.name: I18n.tr(entry.modelData.tip, I18n.revision)
                    Accessible.selected: selected
                    onClicked: root.selected(entry.modelData.key)
                    Keys.onReturnPressed: root.selected(entry.modelData.key)
                    Keys.onEnterPressed: root.selected(entry.modelData.key)
                    background: Rectangle {
                        radius: Metrics.radiusControl
                        color: button.pressed ? Theme.subtlePressed : (button.selected ? Theme.subtleHover : (button.hovered ? Theme.subtleHover : "transparent"))
                        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                        PFocusRing { visible: button.visualFocus; inset: -1 }
                        Rectangle {
                            visible: button.selected
                            x: root.side === "right" ? 0 : parent.width - width
                            anchors.verticalCenter: parent.verticalCenter
                            width: 3
                            height: 16
                            radius: 1.5
                            color: root.accentColor
                        }
                    }
                    contentItem: Item {
                        PIcon { anchors.centerIn: parent; name: entry.modelData.icon; color: button.selected ? Theme.textPrimary : Theme.textSecondary }
                    }
                    PToolTip {
                        text: I18n.tr(entry.modelData.tip, I18n.revision)
                        visible: button.hovered && !button.pressed
                        x: root.side === "right" ? -implicitWidth - Metrics.s8 : button.width + Metrics.s8
                        y: (button.height - implicitHeight) / 2
                    }
                }
            }
        }
    }
}
