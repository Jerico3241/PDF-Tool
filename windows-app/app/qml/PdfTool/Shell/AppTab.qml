import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// Ein Tab im Tab-Dock oben (seit 5.0 Beta 10, Entwürfe 7/8): ⌂ Start, ein Werkzeug oder ein Dokument. Die Tabs liegen
// als Kacheln in einer schwebenden Schale; der aktive hebt sich in 3D ab (Glanz, tiefer Schatten, 1 px höher), die
// Farbe seiner Dateiart leuchtet darunter (Markierung in AppTabs). Dokumente zeigen eine farbige Kachel mit weißem
// Symbol. Schließen: ×, mittlere Maustaste. Die Schrift wechselt beim Aktivieren nicht – der Tab behält seine Breite.
// Ist er schmaler als nötig (Name gekürzt), steht × wie in Browsern nur am aktiven Tab und beim Zeigen, der Punkt
// nur, wenn ungespeichert – der Platz geht an den Namen.
T.AbstractButton {
    id: tab
    property string iconName: ""
    property url imageSource: ""        // farbiges Symbol der Dateiart (seit 5.0) statt eines Fluent-Symbols
    property color kindColor: "transparent"  // Farbe der Dateiart: Kachel und Leuchten unter dem aktiven Tab
    property string kind: ""            // Dateiart: farbige Kachel mit weißem Symbol (Entwurf 7)
    property real minWidth: 0
    property bool tile: false           // ⌂ Start: eigene erhabene Kachel neben dem Dock
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
    readonly property real fullWidth: iconOnly ? (tile ? Metrics.dockTabHeight : Metrics.appTabIconOnly)
        : Math.min(Metrics.appTabMaxWidth, leftPadding + rightPadding + (kind !== "" ? 24 + row.spacing : iconName !== "" || imageSource != "" ? Metrics.iconSize + row.spacing : 0)
                   + Math.ceil(boldName.advanceWidth) + (showDirty ? 6 + row.spacing : 0) + (closable ? 24 + row.spacing : 0))
    readonly property bool narrow: !iconOnly && width < fullWidth - 0.5
    signal closeRequested()
    // Breite immer mit fetter Schrift gemessen: der aktive Tab ist fett und wird dadurch nicht breiter
    TextMetrics { id: boldName; font: Typography.bodyStrong; text: I18n.tr(tab.title, I18n.revision) }

    implicitHeight: Metrics.dockTabHeight
    implicitWidth: Math.max(minWidth, fullWidth)
    leftPadding: iconOnly ? 0 : (kind !== "" ? 6 : 10)
    rightPadding: iconOnly ? 0 : (closable ? 4 : 12)
    // Aktiv: hebt sich aus dem Dock (seit 5.0 Beta 11 deutlich, mit Nachfedern); unter der Maus hebt er sich leicht
    transform: Translate { y: tab.active && !tab.tile ? -2 : (tab.hovered && Motion.moves ? -1.5 : 0); Behavior on y { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Easing.OutBack; easing.overshoot: 2 } } }
    focusPolicy: Qt.TabFocus
    hoverEnabled: true
    Accessible.role: Accessible.PageTab
    Accessible.name: I18n.tr((iconOnly ? tooltip : title) + (unsaved ? " (ungespeichert)" : ""), I18n.revision)
    Accessible.selected: active
    Keys.onReturnPressed: clicked()
    Keys.onSpacePressed: clicked()

    TapHandler {
        acceptedButtons: Qt.MiddleButton
        enabled: tab.closable
        onTapped: tab.closeRequested()
    }

    background: Item {
        // Aktiv (bzw. ⌂ Start immer): erhabene Kachel mit Glanz und tiefem Schatten, im Neon-Modus mit farbigem Schein
        PGloss {
            objectName: "tabKindLine"
            anchors.fill: parent
            radius: Metrics.radiusPill
            high: !tab.tile
            glowColor: tab.active ? (tab.kindColor.a > 0 ? tab.kindColor : Theme.accent) : "transparent"
            opacity: tab.active || tab.tile ? 1 : 0
            scale: tab.pressed && Motion.moves ? 0.98 : 1
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
            Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
        }
        Rectangle {
            anchors.fill: parent
            radius: Metrics.radiusPill
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
            // Dateiart: farbige Kachel (Verlauf, Glanzkante) mit weißem Symbol
            Rectangle {
                id: kindTile
                objectName: "tabKindTile"
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 24
                Layout.preferredHeight: 24
                visible: tab.kind !== ""
                // wird der Tab aktiv, dreht sich die Kachel einmal um die senkrechte Achse (seit 5.0 Beta 11)
                transform: Rotation { id: tileTurn; origin.x: 12; origin.y: 12; axis { x: 0; y: 1; z: 0 } angle: 0 }
                Connections {
                    target: tab
                    function onActiveChanged() { if (tab.active && Motion.moves && tab.kind !== "") tileSpin.restart() }
                }
                NumberAnimation { id: tileSpin; target: tileTurn; property: "angle"; from: 0; to: 360; duration: 700; easing.type: Easing.OutBack }
                radius: Metrics.square ? 3 : 7
                gradient: Gradient {
                    orientation: Gradient.Vertical
                    GradientStop { position: 0.0; color: Qt.lighter(tab.kindColor, 1.12) }
                    GradientStop { position: 1.0; color: FileKinds.deep(tab.kind) }
                }
                Rectangle { x: 3; y: 1; width: parent.width - 6; height: 1; color: "#66FFFFFF" }
                Image {
                    anchors.centerIn: parent
                    width: 15
                    height: 15
                    source: tab.kind !== "" ? FileKinds.whiteImage(tab.kind) : ""
                    sourceSize: Qt.size(30, 30)
                    smooth: true
                    Accessible.ignored: true
                }
            }
            PIcon {
                Layout.alignment: Qt.AlignVCenter
                Layout.leftMargin: tab.iconOnly ? (tab.width - width) / 2 : 0
                name: tab.iconName
                color: tab.active ? Theme.accent : (tab.tile ? Theme.textPrimary : Theme.textSecondary)
                visible: tab.iconName !== "" && tab.imageSource == "" && tab.kind === ""
                Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            }
            Image {
                objectName: "tabKindIcon"
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: Metrics.iconSize
                Layout.preferredHeight: Metrics.iconSize
                source: tab.imageSource
                visible: tab.imageSource != "" && tab.kind === ""
                fillMode: Image.PreserveAspectFit
                smooth: true
                Accessible.ignored: true
            }
            PText {
                id: label
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                text: I18n.tr(tab.title, I18n.revision)
                tone: tab.active ? "primary" : "secondary"
                textStyle: tab.active ? "bodyStrong" : "body"
                elide: tab.elideMode
                visible: !tab.iconOnly
            }
            // ungespeichert: Punkt (Platz reserviert, damit der Tab nicht springt – nur im gekürzten Tab nicht)
            Rectangle {
                objectName: tab.dirtyName
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: 7
                Layout.preferredHeight: 7
                radius: 3.5
                visible: tab.showDirty && (!tab.narrow || tab.unsaved)
                color: tab.kindColor.a > 0 ? tab.kindColor : Theme.accent
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
                tip: I18n.tr(tab.closeTip, I18n.revision)
                focusPolicy: Qt.NoFocus
                onClicked: tab.closeRequested()
            }
        }
    }

    PToolTip {
        text: I18n.tr(tab.tooltip, I18n.revision)
        visible: tab.hovered && tab.tooltip !== "" && (tab.iconOnly || tab.tooltip !== tab.title)
        y: parent.height + 6
    }
}
