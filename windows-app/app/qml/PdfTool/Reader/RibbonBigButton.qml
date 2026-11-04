import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Großer Knopf am Anfang einer Befehlsleiste (seit 5.0 Beta 10, Entwurf 7): Symbol über der Beschriftung wie »Einfügen«
// in Word. Zusammengeschobene Leiste (``compact``): nur das Symbol, die Beschriftung steht in der Kurzinfo.
T.AbstractButton {
    id: control
    property string iconName: ""
    property string tip: ""
    property bool compact: parent !== null && parent.squeezed === true
    readonly property bool bigButton: true  // für die Breitenrechnung der Leisten (Beschriftung unter dem Symbol)
    implicitHeight: compact ? 30 : 46
    implicitWidth: compact ? 30 : Math.max(52, label.implicitWidth + 16)
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: I18n.tr(text, I18n.revision)
    Accessible.description: I18n.tr(tip, I18n.revision)
    background: Rectangle {
        radius: Metrics.radiusControl + 2
        color: control.pressed ? Theme.subtlePressed : (control.hovered ? Theme.subtleHover : "transparent")
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        PFocusRing { visible: control.visualFocus }
    }
    contentItem: Item {
        PIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            y: control.compact ? (parent.height - height) / 2 : 5
            name: control.iconName
            size: Metrics.iconSizeMedium
            color: control.enabled ? Theme.textPrimary : Theme.disabled
        }
        Text {
            id: label
            visible: !control.compact
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            text: I18n.tr(control.text, I18n.revision)
            font: Typography.caption
            color: control.enabled ? Theme.textPrimary : Theme.disabled
            textFormat: Text.PlainText
        }
    }
    scale: pressed ? Motion.pressScale : 1.0
    Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
    PToolTip {
        text: I18n.tr(control.compact ? control.text + (control.tip !== "" ? " – " + control.tip : "") : control.tip, I18n.revision)
        visible: control.hovered && text !== ""
        y: control.height + 6
    }
}
