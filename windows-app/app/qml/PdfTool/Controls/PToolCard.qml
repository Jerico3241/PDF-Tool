import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Große Werkzeugkarte der Startseite: Symbol, Titel, Beschreibung und Tastenkürzel.
// Hover hebt die Karte leicht an, Drücken gibt nach; Eingabe oder Leertaste öffnen.
T.AbstractButton {
    id: card
    property string iconName: ""
    property string title: ""
    property string description: ""
    property string shortcut: ""

    implicitWidth: 360
    implicitHeight: Math.max(148, layout.implicitHeight + 40)
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
        RowLayout {
            id: layout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Rectangle {
                Layout.alignment: Qt.AlignTop
                implicitWidth: 48
                implicitHeight: 48
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
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 4
                PText {
                    text: card.title
                    textStyle: "subtitle"
                    Layout.fillWidth: true
                }
                PText {
                    text: card.description
                    tone: "secondary"
                    wrap: true
                    Layout.fillWidth: true
                }
                RowLayout {
                    Layout.topMargin: 8
                    spacing: 6
                    PText {
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
                        text: card.shortcut
                        textStyle: "caption"
                        tone: "tertiary"
                        visible: text !== ""
                    }
                }
            }
        }
    }
}
