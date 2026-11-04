import QtQuick
import PdfTool.Style

// Erhabene Fläche im 3D-Design (Entwürfe 7/8): Glanzverlauf von oben nach unten, helle Oberkante, feine Kontur und
// schwebender Schatten (PLift). Für Befehlsleiste, Seitenleisten, Startseiten-Karten und den aktiven Tab.
Rectangle {
    id: root
    property bool high: false
    property bool lifted: true
    property color glowColor: "transparent"
    property color stroke: Theme.neon ? Theme.dockStroke : Theme.dark ? "#3A3A3A" : "#E6E9EE"
    // Seitenleiste: beim Einblenden von rechts hereingleiten und einblenden (seit 5.0 Beta 10)
    property bool slideIn: false
    transform: Translate { id: slideShift }
    onVisibleChanged: {
        if (!slideIn || !visible || !Motion.moves)
            return
        slideAnimation.restart()
    }
    ParallelAnimation {
        id: slideAnimation
        NumberAnimation { target: slideShift; property: "x"; from: 24; to: 0; duration: Motion.normal; easing.type: Motion.decelerate }
        NumberAnimation { target: root; property: "opacity"; from: 0; to: 1; duration: Motion.normal; easing.type: Motion.decelerate }
    }
    radius: Metrics.radiusFloat
    border.width: 1
    border.color: stroke
    gradient: Gradient {
        GradientStop { position: 0.0; color: Theme.glossTop }
        GradientStop { position: 0.55; color: Theme.glossMid }
        GradientStop { position: 1.0; color: Theme.glossBottom }
    }
    PLift {
        visible: root.lifted
        radius: root.radius
        high: root.high
        glowColor: root.glowColor
    }
    // Licht von oben: helle Kante innen oben
    Rectangle {
        x: root.radius * 0.6
        y: 1
        width: root.width - root.radius * 1.2
        height: 1
        color: Theme.glossEdge
        opacity: Theme.dark ? 0.9 : 1
    }
}
