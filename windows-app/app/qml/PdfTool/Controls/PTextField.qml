import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Eingabefeld mit den Zuständen Normal, Hover, Fokus, Ungültig und Deaktiviert (weiche Übergänge).
T.TextField {
    id: control
    property bool invalid: false
    property string label: ""
    property int preferredWidth: 240
    signal submitted()

    implicitWidth: preferredWidth
    implicitHeight: Metrics.controlHeight
    leftPadding: 11
    rightPadding: 11
    topPadding: 5
    bottomPadding: 6
    font: Typography.body
    color: enabled ? Theme.textPrimary : Theme.disabled
    selectionColor: Theme.accent
    selectedTextColor: Theme.textOnAccent
    placeholderTextColor: enabled ? Theme.textSecondary : Theme.disabled
    verticalAlignment: TextInput.AlignVCenter
    selectByMouse: true
    hoverEnabled: true
    Accessible.role: Accessible.EditableText
    Accessible.name: label !== "" ? label : placeholderText
    onAccepted: submitted()

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: (point) => {
            control.forceActiveFocus()
            menu.popup(control, point.position.x, point.position.y)
        }
    }
    PTextMenu { id: menu; target: control }

    Text {
        x: control.leftPadding
        y: control.topPadding
        width: control.width - control.leftPadding - control.rightPadding
        height: control.height - control.topPadding - control.bottomPadding
        text: control.placeholderText
        font: control.font
        color: control.placeholderTextColor
        verticalAlignment: Text.AlignVCenter
        visible: !control.length && !control.preeditText
        elide: Text.ElideRight
        textFormat: Text.PlainText
        Accessible.ignored: true
    }

    background: Rectangle {
        implicitWidth: control.preferredWidth
        implicitHeight: Metrics.controlHeight
        radius: Metrics.radiusControl
        color: {
            if (!control.enabled) return Theme.controlDisabled
            if (control.activeFocus) return Theme.inputFocus
            if (control.hovered) return Theme.controlHover
            return Theme.control
        }
        border.width: 1
        border.color: control.invalid ? Theme.error : Theme.controlStroke
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        // Unterkante: im Fokus in Akzentfarbe (2 px), ungültig in Fehlerfarbe
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            height: control.activeFocus || control.invalid ? 2 : 1
            radius: 1
            color: control.invalid ? Theme.error : (control.activeFocus ? Theme.accent : (control.enabled ? Theme.inputEdge : "transparent"))
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        }
    }
}
