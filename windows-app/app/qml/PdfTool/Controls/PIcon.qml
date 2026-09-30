import QtQuick
import QtQuick.Window
import PdfTool.Style

// Fluent-Symbol in beliebiger Farbe – scharf in jeder Skalierung (gerendert in Gerätepixeln).
Image {
    id: root
    property string name: ""
    property color color: Theme.textPrimary
    property int size: Metrics.iconSize
    readonly property real ratio: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1

    width: size
    height: size
    visible: name !== ""
    source: name !== "" ? Theme.icon(name, color) : ""
    sourceSize: Qt.size(Math.ceil(size * ratio), Math.ceil(size * ratio))
    fillMode: Image.PreserveAspectFit
    smooth: true
    cache: true
    Accessible.ignored: true
}
