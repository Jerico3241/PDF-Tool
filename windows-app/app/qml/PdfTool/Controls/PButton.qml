import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Schaltfläche: »standard«, »accent« (Hauptaktion), »subtle« (ohne Fläche) oder »danger«.
// Hover und Druck ändern Farbe und Rahmen weich; Tastaturfokus zeigt einen deutlichen Rahmen.
T.Button {
    id: control
    property string kind: "standard"
    property string iconName: ""
    property bool busy: false
    property string busyText: ""
    property bool large: false
    property string tip: ""
    property int minimumWidth: 0

    readonly property bool accentKind: kind === "accent"
    readonly property bool subtleKind: kind === "subtle"
    readonly property bool dangerKind: kind === "danger"
    readonly property bool iconOnly: text === "" && iconName !== ""

    implicitHeight: large ? Metrics.controlHeightLarge : Metrics.controlHeight
    implicitWidth: Math.max(minimumWidth, iconOnly ? implicitHeight : Math.ceil(contentItem.implicitWidth) + leftPadding + rightPadding)
    leftPadding: iconOnly ? 0 : (large ? 16 : 12)
    rightPadding: iconOnly ? 0 : (large ? 16 : 12)
    font: large ? Typography.bodyStrong : Typography.body
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    Accessible.role: Accessible.Button
    Accessible.name: text !== "" ? text : tip
    Accessible.description: tip

    readonly property color foreground: {
        if (!enabled) return accentKind || dangerKind ? Theme.textOnAccentDisabled : Theme.disabled
        if (accentKind || dangerKind) return pressed ? Theme.textOnAccentPressed : Theme.textOnAccent
        if (pressed) return Theme.textSecondary
        return Theme.textPrimary
    }

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        Row {
            id: row
            anchors.centerIn: parent
            spacing: control.iconOnly ? 0 : 8
            Item {
                width: control.busy || control.iconName !== "" ? Metrics.iconSize : 0
                height: Metrics.iconSize
                anchors.verticalCenter: parent.verticalCenter
                visible: width > 0
                PIcon {
                    anchors.centerIn: parent
                    name: control.iconName
                    color: control.foreground
                    visible: !control.busy && control.iconName !== ""
                }
                PProgressRing {
                    anchors.centerIn: parent
                    size: Metrics.iconSize
                    color: control.foreground
                    visible: control.busy
                    running: control.busy
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: control.busy && control.busyText !== "" ? control.busyText : control.text
                visible: text !== ""
                font: control.font
                color: control.foreground
                textFormat: Text.PlainText
                Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            }
        }
    }

    background: Rectangle {
        id: face
        implicitWidth: control.implicitHeight
        implicitHeight: control.implicitHeight
        radius: Metrics.radiusControl
        color: {
            if (control.accentKind || control.dangerKind) {
                var base = control.dangerKind ? Theme.error : Theme.accent
                if (!control.enabled) return Theme.accentDisabled
                if (control.pressed) return control.dangerKind ? Theme.errorPressed : Theme.accentPressed
                if (control.hovered) return control.dangerKind ? Theme.errorHover : Theme.accentHover
                return base
            }
            if (control.subtleKind) {
                if (!control.enabled) return "transparent"
                if (control.pressed) return Theme.subtlePressed
                if (control.hovered || control.checked) return Theme.subtleHover
                return "transparent"
            }
            if (!control.enabled) return Theme.controlDisabled
            if (control.pressed) return Theme.controlPressed
            if (control.hovered) return Theme.controlHover
            return Theme.control
        }
        border.width: control.subtleKind ? 0 : 1
        border.color: {
            if (control.accentKind || control.dangerKind) return control.enabled ? (control.dangerKind ? Theme.error : Theme.accentStroke) : "transparent"
            return Theme.controlStroke
        }
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        // Untere Kante etwas dunkler (Tiefe wie bei Windows 11)
        Rectangle {
            visible: !control.subtleKind && control.enabled && !control.pressed
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Metrics.radiusControl
            anchors.rightMargin: Metrics.radiusControl
            height: 1
            color: control.accentKind || control.dangerKind ? Theme.accentEdge : Theme.controlEdge
            opacity: 0.8
        }
        PFocusRing {
            visible: control.visualFocus
        }
    }

    scale: pressed ? Motion.pressScale : 1.0
    Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }

    PToolTip {
        text: control.tip
        visible: control.tip !== "" && control.hovered && !control.pressed
    }
}
