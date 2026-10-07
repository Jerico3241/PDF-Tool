import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Controls

// Ein Tab der Leiste oben: ⌂ Start, ein Werkzeug oder ein Dokument. Der aktive Tab hat die Farbe der
// Inhaltsebene und geht nahtlos in sie über (wie Tabs in Windows 11); die übrigen liegen auf dem Hintergrund,
// beim Zeigen leicht hinterlegt. Schließen: ×, mittlere Maustaste. Die Schrift wechselt beim Aktivieren nicht
// – der Tab behält seine Breite. Ist er schmaler als nötig (Name gekürzt), steht × wie in Browsern nur am
// aktiven Tab und beim Zeigen, der Punkt nur, wenn ungespeichert – der Platz geht an den Namen.
T.AbstractButton {
    id: tab
    property string iconName: ""
    property string title: ""
    property string tooltip: title
    property bool active: false
    property bool closable: false
    property string closeTip: "Schließen"
    property bool unsaved: false
    property bool showDirty: false      // Platz für den Punkt »ungespeichert« (nur Dokumente)
    property string closeName: "tabClose"
    property string dirtyName: "tabDirty"
    property int elideMode: Text.ElideRight   // Dateinamen: in der Mitte (Anfang und Endung bleiben lesbar)
    readonly property bool iconOnly: title === ""
    // Volle Breite mit ganzem Namen, Punkt und × – unabhängig davon, was gerade zu sehen ist (die Breite kommt von
    // außen; so entsteht keine Schleife über die Breite)
    readonly property real fullWidth: iconOnly ? Metrics.appTabIconOnly
        : Math.min(Metrics.appTabMaxWidth, leftPadding + rightPadding + (iconName !== "" ? Metrics.iconSize + row.spacing : 0)
                   + Math.ceil(label.implicitWidth) + (showDirty ? 6 + row.spacing : 0) + (closable ? 24 + row.spacing : 0))
    readonly property bool narrow: !iconOnly && width < fullWidth - 0.5
    signal closeRequested()

    implicitHeight: Metrics.appTabHeight
    implicitWidth: fullWidth
    leftPadding: iconOnly ? 0 : 12
    rightPadding: iconOnly ? 0 : (closable ? 4 : 12)
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    Accessible.role: Accessible.PageTab
    Accessible.name: (iconOnly ? tooltip : title) + (unsaved ? " (ungespeichert)" : "")
    Accessible.selected: active
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()

    TapHandler {
        acceptedButtons: Qt.MiddleButton
        enabled: tab.closable
        onTapped: tab.closeRequested()
    }

    background: Item {
        // Aktiv: oben gerundet, unten offen – 1 px über die Kante der Inhaltsebene, deren Linie dort verschwindet
        Item {
            anchors.fill: parent
            anchors.bottomMargin: -1
            clip: true
            opacity: tab.active ? 1 : 0
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
            Rectangle {
                width: parent.width
                height: parent.height + Metrics.radiusCard
                radius: Metrics.radiusCard
                color: Theme.layer
                border.width: 1
                border.color: Theme.layerStroke
            }
        }
        Rectangle {
            anchors.fill: parent
            anchors.topMargin: 3
            anchors.bottomMargin: 3
            radius: Metrics.radiusControl + 2
            color: tab.pressed ? Theme.subtlePressed : Theme.subtleHover
            opacity: !tab.active && (tab.hovered || tab.pressed) ? 1 : 0
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
        }
        PFocusRing { visible: tab.visualFocus; inset: 2 }
    }

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight
        RowLayout {
            id: row
            anchors.fill: parent
            spacing: 8
            PIcon {
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: tab.iconOnly ? (tab.width - width) / 2 : 0
                name: tab.iconName
                color: tab.active ? Theme.accent : Theme.textSecondary
                visible: tab.iconName !== ""
                Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            }
            PText {
                id: label
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                text: tab.title
                tone: tab.active ? "primary" : "secondary"
                elide: tab.elideMode
                visible: !tab.iconOnly
            }
            // ungespeichert: Punkt (Platz reserviert, damit der Tab nicht springt – nur im gekürzten Tab nicht)
            Rectangle {
                objectName: tab.dirtyName
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 6
                Layout.preferredHeight: 6
                radius: 3
                visible: tab.showDirty && (!tab.narrow || tab.unsaved)
                color: tab.active ? Theme.textPrimary : Theme.textSecondary
                opacity: tab.unsaved ? 1 : 0
                Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
            }
            PIconButton {
                objectName: tab.closeName
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: 24
                implicitHeight: 24
                visible: tab.closable && (!tab.narrow || tab.active || tab.hovered)
                iconName: "dismiss"
                tip: tab.closeTip
                focusPolicy: Qt.NoFocus
                onClicked: tab.closeRequested()
            }
        }
    }

    PToolTip {
        text: tab.tooltip
        visible: tab.hovered && tab.tooltip !== "" && (tab.iconOnly || tab.tooltip !== tab.title)
        y: parent.height + 6
    }
}
