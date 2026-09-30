import QtQuick
import PdfTool.Style

// Bereich, der weich auf- und zuklappt (echte Höhenanimation; »Reduziert«: nur Überblendung).
// Zugeklappt ist der Inhalt unsichtbar – er wird nicht gezeichnet und nimmt keinen Fokus.
Item {
    id: root
    property bool expanded: false
    property bool animate: true
    default property alias content: holder.data
    readonly property real contentHeight: holder.childrenRect.height
    readonly property bool animating: heightAnim.running || fadeAnim.running

    implicitWidth: holder.childrenRect.width
    implicitHeight: expanded ? contentHeight : 0
    clip: animating
    visible: expanded || animating
    opacity: expanded ? 1 : 0

    Behavior on implicitHeight {
        enabled: root.animate && Motion.expand > 0
        NumberAnimation { id: heightAnim; duration: Motion.expand; easing.type: Motion.decelerate }
    }
    Behavior on opacity {
        enabled: root.animate && Motion.enabled
        NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    Item {
        id: holder
        width: root.width
        height: root.contentHeight
    }
}
