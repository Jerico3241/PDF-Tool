import QtQuick
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Backend

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
    // Umschalter (Werkzeug, Fett, Ausrichtung …): ``checked`` folgt allein dem Zustand, den der Klick
    // ändert. Die Schaltfläche schaltet sich nicht selbst um – sonst ginge die Bindung verloren und sie
    // zeigte einen Zustand, den es nicht gibt.
    property bool toggle: false
    // Schmales Menüband (seit 5.0 Beta 9): nur das Symbol, die Beschriftung steht in der Kurzinfo
    property bool compact: false
    property color labelColor: "transparent"  // eigene Schriftfarbe (Vorschau der Formatvorlagen), sonst wie üblich

    readonly property bool accentKind: kind === "accent"
    readonly property bool subtleKind: kind === "subtle" || kind === "link"
    readonly property bool linkKind: kind === "link"  // wie »subtle«, Schrift und Symbol in der Akzentfarbe
    readonly property bool dangerKind: kind === "danger"
    readonly property bool iconOnly: iconName !== "" && (text === "" || compact)
    // 3D-Design (seit 5.0 Beta 10): eingeschaltete Umschalter ohne Fläche liegen sichtbar tiefer – Akzentton, innerer
    // Schatten oben, im Neon-Modus mit leuchtendem Rand
    readonly property bool sunk: subtleKind && checked && enabled

    implicitHeight: large ? Metrics.controlHeightLarge : Metrics.controlHeight
    implicitWidth: Math.max(minimumWidth, iconOnly ? implicitHeight : Math.ceil(contentItem.implicitWidth) + leftPadding + rightPadding)
    leftPadding: iconOnly ? 0 : (large ? 16 : 12)
    rightPadding: iconOnly ? 0 : (large ? 16 : 12)
    font: large ? Typography.bodyStrong : Typography.body
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    Accessible.role: Accessible.Button
    Accessible.name: I18n.tr(text !== "" ? text : tip, I18n.revision)
    Accessible.description: I18n.tr(tip, I18n.revision)
    Accessible.checkable: toggle
    Accessible.checked: toggle && checked

    readonly property color foreground: {
        if (!enabled) return accentKind || dangerKind ? Theme.textOnAccentDisabled : Theme.disabled
        if (accentKind || dangerKind) return pressed ? Theme.textOnAccentPressed : Theme.textOnAccent
        if (pressed) return Theme.textSecondary
        if (sunk) return Theme.accent
        if (labelColor.a > 0) return labelColor
        return linkKind ? Theme.accentText : Theme.textPrimary
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
                text: control.compact && control.iconName !== "" ? "" : I18n.tr(control.busy && control.busyText !== "" ? control.busyText : control.text, I18n.revision)
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
                if (control.sunk) return Theme.pressedFill
                if (control.hovered) return Theme.subtleHover
                return "transparent"
            }
            if (!control.enabled) return Theme.controlDisabled
            if (control.pressed) return Theme.controlPressed
            if (control.hovered) return Theme.controlHover
            return Theme.control
        }
        border.width: control.subtleKind ? (control.sunk && Theme.neon ? 1 : 0) : 1
        border.color: {
            if (control.subtleKind) return Theme.accent
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
        // Gedrückt/eingeschaltet: innerer Schatten oben (Licht von oben, die Fläche liegt tiefer)
        Repeater {
            model: control.sunk ? 3 : 0
            Rectangle {
                required property int index
                x: Metrics.radiusControl
                y: 1 + index
                width: face.width - 2 * Metrics.radiusControl
                height: 1
                color: Theme.pressedInset
                opacity: 1 - index / 3
            }
        }
        // Neon: leuchtender Schein um den eingeschalteten Knopf
        Repeater {
            model: control.sunk && Theme.glow > 0 ? 4 : 0
            Rectangle {
                required property int index
                x: -(index + 1)
                y: -(index + 1)
                width: face.width + 2 * (index + 1)
                height: face.height + 2 * (index + 1)
                radius: face.radius + index + 1
                color: "transparent"
                border.width: 1
                border.color: Theme.accent
                opacity: 0.22 * Theme.glow * (1 - index / 4)
            }
        }
        PFocusRing {
            visible: control.visualFocus
        }
    }

    scale: pressed ? Motion.pressScale : 1.0
    Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }

    PToolTip {
        // Nur Symbol (schmales Menüband): Beschriftung und Kurzinfo zusammen
        readonly property bool withLabel: control.compact && control.text !== "" && control.text !== control.tip
        text: I18n.tr(withLabel ? (control.tip !== "" ? I18n.tr(control.text, I18n.revision) + " – " + I18n.tr(control.tip, I18n.revision) : control.text) : control.tip, I18n.revision)
        visible: text !== "" && control.hovered && !control.pressed
    }
}
