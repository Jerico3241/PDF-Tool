import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Controls

// Eingeklappte Seitenleiste: ein schmaler Streifen am Rand der Dokumentfläche mit den Inhalten *dieser*
// Leiste als Symbole (links Seiten, Lesezeichen, Suchen; rechts Kommentare, Eigenschaften) – ein Klick
// öffnet die Leiste mit diesem Inhalt. Ist die Leiste offen, liegt sie über dem Streifen (der dann so
// breit ist wie sie und nur ihren Hintergrund bildet), und ihre Umschalter sitzen in ihrem Kopf.
Rectangle {
    id: root
    property var items: []          // [{key, icon, tip, name}]
    property bool collapsed: true   // Seitenleiste zu: Symbole zeigen
    property string side: "left"    // Seite des Fensters; die Trennlinie liegt zur Dokumentfläche hin
    signal selected(string key)

    color: Theme.layer
    Accessible.role: Accessible.PageTabList
    Accessible.name: side === "left" ? "Linke Seitenleiste" : "Rechte Seitenleiste"
    Rectangle { x: root.side === "left" ? root.width - 1 : 0; width: 1; height: root.height; color: Theme.divider }

    Column {
        id: column
        x: root.side === "left" ? (Metrics.readerRailWidth - width) / 2 : root.width - Metrics.readerRailWidth + (Metrics.readerRailWidth - width) / 2
        y: Metrics.s8
        spacing: Metrics.s4
        enabled: root.collapsed
        opacity: root.collapsed ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
        Repeater {
            model: root.items
            T.AbstractButton {
                id: button
                required property var modelData
                objectName: modelData.name || ""
                width: Metrics.readerRailButton
                height: Metrics.readerRailButton
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.tip
                onClicked: root.selected(modelData.key)
                Keys.onReturnPressed: root.selected(modelData.key)
                Keys.onEnterPressed: root.selected(modelData.key)
                background: Rectangle {
                    radius: Metrics.radiusControl
                    color: button.pressed ? Theme.subtlePressed : (button.hovered ? Theme.subtleHover : "transparent")
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                    PFocusRing { visible: button.visualFocus; inset: -1 }
                }
                contentItem: Item {
                    PIcon { anchors.centerIn: parent; name: button.modelData.icon; color: Theme.textSecondary }
                }
                PToolTip {
                    text: button.modelData.tip
                    visible: button.hovered && !button.pressed
                    x: root.side === "left" ? button.width + Metrics.s8 : -implicitWidth - Metrics.s8
                    y: (button.height - implicitHeight) / 2
                }
            }
        }
    }
}
