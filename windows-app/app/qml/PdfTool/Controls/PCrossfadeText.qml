import QtQuick
import PdfTool.Style

// Text, der bei Änderungen weich überblendet (alter Text aus, neuer ein – gleichzeitig).
Item {
    id: root
    property string text: ""
    property font font: Typography.body
    property color color: Theme.textPrimary
    property int elide: Text.ElideRight
    property int horizontalAlignment: Text.AlignLeft
    property bool _front: true

    implicitWidth: Math.max(a.implicitWidth, b.implicitWidth)
    implicitHeight: Math.max(a.implicitHeight, b.implicitHeight, 1)
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    onTextChanged: {
        var target = _front ? b : a
        var other = _front ? a : b
        target.text = text
        _front = !_front
        if (!Motion.enabled || !root.visible) {
            target.opacity = 1
            other.opacity = 0
            return
        }
        fadeIn.target = target
        fadeOut.target = other
        swap.restart()
    }
    Component.onCompleted: a.text = text

    ParallelAnimation {
        id: swap
        NumberAnimation { id: fadeIn; property: "opacity"; to: 1; duration: Motion.status; easing.type: Motion.decelerate }
        NumberAnimation { id: fadeOut; property: "opacity"; to: 0; duration: Motion.status * 0.7; easing.type: Motion.accelerate }
    }
    Text {
        id: a
        width: root.width
        opacity: 1
        font: root.font
        color: root.color
        elide: root.elide
        horizontalAlignment: root.horizontalAlignment
        verticalAlignment: Text.AlignVCenter
        height: root.height
        textFormat: Text.PlainText
        Accessible.ignored: true
    }
    Text {
        id: b
        width: root.width
        opacity: 0
        font: root.font
        color: root.color
        elide: root.elide
        horizontalAlignment: root.horizontalAlignment
        verticalAlignment: Text.AlignVCenter
        height: root.height
        textFormat: Text.PlainText
        Accessible.ignored: true
    }
}
