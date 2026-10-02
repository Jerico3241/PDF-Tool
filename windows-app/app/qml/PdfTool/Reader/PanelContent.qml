import QtQuick
import PdfTool.Style

// Inhalt einer Seitenleiste: existiert nur, solange er gezeigt wird (versteckte Miniaturen würden sonst
// gerendert), und blendet beim Erscheinen kurz ein (Animationen »Aus«: sofort).
Loader {
    property bool shown: false
    anchors.fill: parent
    active: shown
    opacity: 0
    onLoaded: opacity = 1
    onActiveChanged: if (!active) opacity = 0
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
}
