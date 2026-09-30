import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Tooltip: blendet kurz ein und aus, ohne lange Verzögerung.
T.ToolTip {
    id: control
    delay: 500
    timeout: 10000
    x: parent ? Math.round((parent.width - implicitWidth) / 2) : 0
    y: -implicitHeight - 6
    margins: 8
    padding: 8
    topPadding: 5
    bottomPadding: 7
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent | T.Popup.CloseOnReleaseOutsideParent
    implicitWidth: Math.min(Math.ceil(contentItem.implicitWidth) + leftPadding + rightPadding, 360)
    implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
    font: Typography.caption

    contentItem: Text {
        text: control.text
        font: control.font
        color: Theme.textPrimary
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    background: Rectangle {
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusControl
    }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.tooltip; easing.type: Motion.decelerate }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.tooltip; easing.type: Motion.accelerate }
    }
}
