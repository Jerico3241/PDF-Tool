import QtQuick
import PdfTool.Style

// Fokusrahmen für die Tastaturbedienung (zweifarbig wie in Windows 11 – auf jedem Hintergrund sichtbar).
Rectangle {
    id: ring
    property real radius_: Metrics.radiusControl
    property int inset: -3
    anchors.fill: parent
    anchors.margins: inset
    radius: radius_ - inset
    color: "transparent"
    border.width: 2
    border.color: Theme.focusOuter
    Rectangle {
        anchors.fill: parent
        anchors.margins: 2
        radius: Math.max(0, parent.radius - 2)
        color: "transparent"
        border.width: 1
        border.color: Theme.focusInner
    }
}
