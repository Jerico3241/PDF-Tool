import QtQuick
import PdfTool.Style

// Fortschrittsbalken: bestimmt (value 0…1) oder unbestimmt (laufendes Segment – nur sichtbar aktiv).
Item {
    id: root
    property real value: 0
    property bool indeterminate: false
    property color color: Theme.accent
    implicitHeight: 4
    implicitWidth: 200
    Accessible.role: Accessible.ProgressBar
    Accessible.name: indeterminate ? "Wird bearbeitet" : Math.round(value * 100) + " %"

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        height: 1
        color: Theme.strongStroke
        opacity: 0.6
    }
    Item {
        anchors.fill: parent
        clip: true
        Rectangle {
            id: bar
            height: parent.height
            radius: height / 2
            color: root.color
            visible: !root.indeterminate
            width: Math.max(0, Math.min(1, root.value)) * parent.width
            Behavior on width { enabled: Motion.enabled; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
        }
        Rectangle {
            id: runner
            height: parent.height
            radius: height / 2
            color: root.color
            visible: root.indeterminate
            width: parent.width * 0.4
            x: -width
            NumberAnimation on x {
                running: root.indeterminate && root.visible && root.Window.visibility !== Window.Minimized
                from: -runner.width
                to: runner.parent.width
                duration: 1400
                loops: Animation.Infinite
                easing.type: Easing.InOutQuad
            }
        }
    }
}
