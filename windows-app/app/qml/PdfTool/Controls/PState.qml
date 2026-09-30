import QtQuick
import PdfTool.Style

// Ein Zustand innerhalb von PStateStack (blendet beim Wechsel weich über).
Item {
    implicitHeight: childrenRect.height
    implicitWidth: childrenRect.width
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.status; easing.type: Motion.decelerate } }
}
