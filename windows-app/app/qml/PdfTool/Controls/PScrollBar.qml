import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Schlanke Bildlaufleiste, die beim Überfahren breiter wird (wie in Windows 11).
T.ScrollBar {
    id: control
    implicitWidth: orientation === Qt.Vertical ? 12 : 100
    implicitHeight: orientation === Qt.Horizontal ? 12 : 100
    padding: 2
    minimumSize: 0.08
    visible: policy !== T.ScrollBar.AlwaysOff && size < 1.0
    hoverEnabled: true
    // Auch beim Scrollen ohne Ziehen (Mausrad, Tastatur, Sprung) kurz zeigen, wo man ist – wie Windows 11
    property bool recent: false
    onPositionChanged: if (size < 1.0) { recent = true; hideLater.restart() }
    Timer { id: hideLater; interval: 900; onTriggered: control.recent = false }

    contentItem: Rectangle {
        implicitWidth: control.hovered || control.pressed ? 6 : 2
        implicitHeight: control.hovered || control.pressed ? 6 : 2
        radius: 3
        color: control.pressed ? Theme.textSecondary : Theme.textTertiary
        opacity: control.active || control.hovered || control.recent ? 1.0 : 0.0
        x: control.orientation === Qt.Vertical ? control.width - width - 3 : 0
        y: control.orientation === Qt.Horizontal ? control.height - height - 3 : 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade } }
        Behavior on implicitWidth { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
        Behavior on implicitHeight { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
    }
    background: Rectangle {
        radius: 6
        color: Theme.flyout
        opacity: control.hovered || control.pressed ? 0.8 : 0.0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade } }
    }
}
