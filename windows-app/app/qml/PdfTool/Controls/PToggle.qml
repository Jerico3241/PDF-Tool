import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Umschalter: Daumen gleitet, Spur wechselt die Farbe; Hover vergrößert den Daumen leicht.
// Links steht auf Wunsch »Ein«/»Aus« (wie in den Einstellungen von Windows 11).
T.Switch {
    id: control
    property bool showState: true
    property string label: ""
    property string tip: ""

    implicitWidth: (showState ? stateText.implicitWidth + 12 : 0) + 40
    implicitHeight: Metrics.controlHeight
    padding: 0
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font: Typography.body
    Accessible.role: Accessible.CheckBox
    Accessible.name: label !== "" ? label : (text !== "" ? text : tip)
    Accessible.checked: checked

    Text {
        id: stateText
        visible: control.showState
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: track.left
        anchors.rightMargin: 12
        text: control.checked ? "Ein" : "Aus"
        font: control.font
        color: control.enabled ? Theme.textPrimary : Theme.disabled
        // Breite von »Aus« und »Ein« angleichen – der Schalter bleibt an seinem Platz
        width: Math.max(metrics.advanceWidth, implicitWidth)
        horizontalAlignment: Text.AlignRight
        TextMetrics { id: metrics; font: control.font; text: "Aus" }
    }

    indicator: Rectangle {
        id: track
        x: control.width - width
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: 40
        implicitHeight: 20
        radius: 10
        color: {
            if (!control.enabled) return control.checked ? Theme.accentDisabled : "transparent"
            if (control.checked) return control.pressed ? Theme.accentPressed : (control.hovered ? Theme.accentHover : Theme.accent)
            return control.pressed ? Theme.subtlePressed : (control.hovered ? Theme.subtleHover : "transparent")
        }
        border.width: control.checked ? 0 : 1
        border.color: control.enabled ? Theme.strongStroke : Theme.disabled
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.normal } }

        Rectangle {
            id: thumb
            readonly property real size: control.pressed ? 14 : (control.hovered ? 14 : 12)
            width: control.pressed ? 17 : size
            height: size
            radius: size / 2
            anchors.verticalCenter: parent.verticalCenter
            x: control.checked ? parent.width - width - 4 : 4
            color: control.checked ? (control.enabled ? Theme.textOnAccent : Theme.textOnAccentDisabled) : (control.enabled ? Theme.strong : Theme.disabled)
            Behavior on x { enabled: Motion.moves; NumberAnimation { duration: Motion.toggle; easing.type: Motion.decelerate } }
            Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
            Behavior on height { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.normal } }
        }
        PFocusRing { visible: control.visualFocus; radius_: 10 }
    }

    contentItem: Item {}

    PToolTip {
        text: control.tip
        visible: control.tip !== "" && control.hovered
    }
}
