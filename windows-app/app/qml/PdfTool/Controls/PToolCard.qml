import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Große Werkzeugkarte der Startseite. Aufbau (für alle Karten gleich):
//
//   Karte ─┬─ Symbolfläche (oben links, 48 × 48)
//          ├─ Textbereich: Titel, Beschreibung (oben, neben dem Symbol)
//          └─ Fußzeile: »Öffnen ›« links, Tastenkürzel rechts – am unteren Rand verankert
//
// Die Fußzeile steht immer an derselben Stelle, auch wenn eine Beschreibung mehr Zeilen hat:
// Die Startseite gibt allen Karten dieselbe Höhe (die größte benötigte). Hover hebt die Karte
// leicht an, Drücken gibt nach; Eingabe oder Leertaste öffnen.
T.AbstractButton {
    id: card
    property string iconName: ""
    property string title: ""
    property string description: ""
    property string shortcut: ""
    readonly property int inset: Metrics.toolCardPadding
    readonly property real textX: inset + Metrics.toolIconBox + Metrics.s16

    implicitWidth: 360
    // Platzbedarf bei der aktuellen Breite: Kopf (Symbol bzw. Text, das Größere) + Abstand + Fußzeile
    implicitHeight: Math.max(Metrics.toolCardMinHeight,
                             Math.ceil(inset + Math.max(Metrics.toolIconBox, textBlock.implicitHeight) + Metrics.s16 + footer.implicitHeight + inset))
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: title
    Accessible.description: description

    transform: Translate { y: card.hovered && !card.pressed && Motion.moves ? -2 : 0
        Behavior on y { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } } }
    scale: pressed ? Motion.pressScale : 1
    Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }

    background: Rectangle {
        radius: Metrics.radiusCard
        color: card.pressed ? (Theme.c.pressed_card || Theme.surface) : (card.hovered ? (Theme.c.hover_card || Theme.surface) : Theme.surface)
        border.width: 1
        border.color: card.hovered ? Theme.controlEdge : Theme.border
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        PShadow { radius: Metrics.radiusCard; depth: 2; strength: card.hovered && Motion.moves ? 0.8 : 0.0
            Behavior on strength { enabled: Motion.enabled; NumberAnimation { duration: Motion.normal } } }
        PFocusRing { visible: card.visualFocus; radius_: Metrics.radiusCard }
    }

    contentItem: Item {
        Rectangle {
            objectName: "toolIcon"
            x: card.inset
            y: card.inset
            width: Metrics.toolIconBox
            height: Metrics.toolIconBox
            radius: Metrics.radiusCard
            color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.18 : 0.10)
            PIcon {
                anchors.centerIn: parent
                name: card.iconName
                size: Metrics.iconSizeLarge
                color: Theme.accentText
            }
        }
        ColumnLayout {
            id: textBlock
            x: card.textX
            y: card.inset
            width: Math.max(0, card.width - card.textX - card.inset)
            spacing: Metrics.s4
            PText {
                objectName: "toolTitle"
                text: card.title
                textStyle: "subtitle"
                Layout.fillWidth: true
            }
            PText {
                objectName: "toolDescription"
                text: card.description
                tone: "secondary"
                wrap: true
                Layout.fillWidth: true
            }
        }
        // Fußzeile: am unteren Rand, links bündig mit dem Titel
        RowLayout {
            id: footer
            objectName: "toolFooter"
            x: card.textX
            width: Math.max(0, card.width - card.textX - card.inset)
            anchors.bottom: parent.bottom
            anchors.bottomMargin: card.inset
            spacing: Metrics.s6
            PText {
                objectName: "toolOpen"
                text: "Öffnen"
                tone: "accent"
            }
            PIcon {
                name: "chevron_right"
                size: 12
                color: Theme.accentText
                Layout.leftMargin: card.hovered && Motion.moves ? 3 : 0
                Behavior on Layout.leftMargin { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
            }
            Item { Layout.fillWidth: true }
            PText {
                objectName: "toolShortcut"
                text: card.shortcut
                textStyle: "caption"
                tone: "tertiary"
                visible: text !== ""
            }
        }
    }
}
