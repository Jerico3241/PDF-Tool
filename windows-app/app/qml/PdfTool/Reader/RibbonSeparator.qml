import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Trennstrich zwischen Gruppen im Menüband
Rectangle {
    Layout.preferredWidth: 1
    Layout.preferredHeight: 20
    Layout.leftMargin: 4
    Layout.rightMargin: 4
    readonly property int ribbonWidth: 9  // Platz samt Rand (für das Messen der Leisten)
    color: Theme.divider
}
