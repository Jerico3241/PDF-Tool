import QtQuick
import PdfTool.Style

// Mausrad wie in anderen Windows-Programmen: Jede Raste verschiebt um dieselbe Strecke – Zeilen aus den
// Windows-Einstellungen × 24 px (``tune_wheel`` rechnet rund 32 px je Zeile, wie Edge und Chrome), bei
// »Eine Bildschirmseite« eine Seite (ohne zwei Zeilen, damit der Anschluss sichtbar bleibt) –, und
// schnell gedrehte Rasten addieren sich: Das Ziel wandert weiter, die laufende Bewegung bricht nicht ab.
// Qts eigene Mausrad-Bewegung begann bei jeder Raste neu an der gerade erreichten Stelle und verlor beim
// zügigen Drehen bis zur Hälfte der Strecke. Weich in 0,16 s; »Reduziert« und »Aus«: sofort.
//
// Liegt unter dem Inhalt der Ansicht: Was darin selbst scrollt (Textfeld, eingebettete Liste), kommt zuerst;
// am Ende des Inhalts geht das Mausrad an die umgebende Ansicht weiter. Mit Strg oder Umschalt bleibt es bei
// den Handlern der Ansicht (Zoom, waagerecht). Touchpads mit Pixelangaben folgen dem Finger direkt.
MouseArea {
    id: root
    objectName: "wheelScroll"
    property Flickable flickable: null
    // Waagerechte Leiste (Tabs): das gewöhnliche Mausrad verschiebt waagerecht, wie die Tab-Leisten von Browsern
    property bool sideways: false
    // Feste Strecke je Raste statt der Windows-Einstellung (z. B. ein Tab); Touchpads sammeln ihre Pixel, bis eine
    // ganze Strecke erreicht ist – die Ansicht steht so immer auf einer ganzen Strecke.
    property real notch: 0
    property real pendingX: 0
    property real pendingY: 0
    // »Eine Bildschirmseite«: Qt meldet dann −1 oder einen sehr großen Wert
    readonly property int lines: Qt.styleHints.wheelScrollLines
    readonly property real step: lines > 0 && lines < 100 ? lines * 24 : (flickable ? Math.max(24, flickable.height - 48) : 72)
    readonly property int duration: Motion.moves ? 160 : 0
    property real targetX: 0
    property real targetY: 0

    // Unterstes Element im Inhalt der Ansicht, stets über dem sichtbaren Ausschnitt: Qt fragt es nach allem
    // Inhalt, aber vor der Ansicht selbst (ein Kind der Ansicht mit negativem z käme erst nach ihr dran).
    parent: flickable ? flickable.contentItem : null
    x: flickable ? flickable.contentX : 0
    y: flickable ? flickable.contentY : 0
    width: flickable ? flickable.width : 0
    height: flickable ? flickable.height : 0
    z: -1
    acceptedButtons: Qt.NoButton

    function minX() { return flickable.originX - flickable.leftMargin }
    function maxX() { return Math.max(minX(), flickable.originX + flickable.contentWidth + flickable.rightMargin - flickable.width) }
    function minY() { return flickable.originY - flickable.topMargin }
    function maxY() { return Math.max(minY(), flickable.originY + flickable.contentHeight + flickable.bottomMargin - flickable.height) }

    // Um ``delta`` Pixel verschieben (positiv: zum Ende). false: in dieser Richtung geht es nicht weiter.
    function move(horizontal, delta, smooth) {
        var animation = horizontal ? animX : animY
        var low = horizontal ? minX() : minY()
        var high = horizontal ? maxX() : maxY()
        var now = horizontal ? flickable.contentX : flickable.contentY
        var from = animation.running ? (horizontal ? targetX : targetY) : now
        var to = Math.max(low, Math.min(high, from + delta))
        if (Math.abs(to - now) < 0.5 && Math.abs(to - from) < 0.5)
            return false
        if (horizontal) targetX = to
        else targetY = to
        if (smooth && duration > 0) {
            animation.stop()
            animation.from = now
            animation.to = to
            animation.start()
        } else {
            animation.stop()
            if (horizontal) flickable.contentX = to
            else flickable.contentY = to
        }
        return true
    }

    onWheel: (wheel) => {
        if (!flickable || wheel.modifiers !== Qt.NoModifier) {
            wheel.accepted = false
            return
        }
        var pixels = wheel.pixelDelta.x !== 0 || wheel.pixelDelta.y !== 0
        var unit = notch > 0 ? notch : step
        var dx = pixels ? -wheel.pixelDelta.x : -wheel.angleDelta.x / 120 * unit
        var dy = pixels ? -wheel.pixelDelta.y : -wheel.angleDelta.y / 120 * unit
        if (sideways) {
            dx += dy
            dy = 0
        }
        if (notch > 0 && pixels) {
            pendingX += dx
            pendingY += dy
            dx = Math.trunc(pendingX / notch) * notch
            dy = Math.trunc(pendingY / notch) * notch
            pendingX -= dx
            pendingY -= dy
            if (dx === 0 && dy === 0) {
                wheel.accepted = true
                return
            }
            pixels = false  // ganze Strecken weich wie mit dem Mausrad
        }
        var moved = false
        if (dy !== 0) moved = move(false, dy, !pixels)
        if (dx !== 0) moved = move(true, dx, !pixels) || moved
        wheel.accepted = moved
    }

    NumberAnimation { id: animY; target: root.flickable; property: "contentY"; duration: root.duration; easing.type: Easing.OutCubic }
    NumberAnimation { id: animX; target: root.flickable; property: "contentX"; duration: root.duration; easing.type: Easing.OutCubic }
}
