import QtQuick
import PdfTool.Style

// Einfügemarke der Textfelder mit Formatierung (Kopf- und Fußzeile, ``PRichTextEditor``).
//
// Qt zeichnet von sich aus einen Strich über die ganze Zeilenhöhe, 1 logisches Pixel breit – bei
// 125 … 175 % also 1,25 … 1,75 Gerätepixel, je nach Lage ein bis vier Pixel verwischt. Diese Marke
// ist so hoch wie die Schrift, die als Nächstes entsteht (Ober- plus Unterlänge aus deren Font
// Metrics, ``ascent``/``descent``), steht auf der Grundlinie der Zeile (``lineBaseline``) und hat
// Breite, Höhe und Lage in ganzen Gerätepixeln: bei jeder Skalierung gleich schmal und scharf.
//
// Das Textfeld legt die Marke als ``cursorDelegate`` an und setzt x (Einfügestelle), y (Oberkante
// der Zeile) und height (Zeilenhöhe) selbst; gezeichnet wird nur der Strich. Sichtbar nur, solange
// das Textfeld den Textfokus hat; sie blinkt wie unter Windows eingestellt.
Item {
    id: caret
    objectName: "caret"
    property Item textItem: parent      // das Textfeld (Eltern-Element des Delegates)
    property real ascent: 0             // Oberlänge der Schrift am Cursor (logische Pixel)
    property real descent: 0            // Unterlänge
    property real lineBaseline: ascent  // Grundlinie ab Oberkante der Zeile
    property color color: Theme.paperText
    property bool blinkOn: true
    readonly property real dpr: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    readonly property int flashTime: Qt.styleHints.cursorFlashTime  // ≤ 0: nicht blinken

    width: 0
    visible: textItem !== null && textItem.cursorVisible && !textItem.readOnly && blinkOn

    // Strich auf das Gerätepixelraster legen (Lage im Fenster): linke Kante und Oberkante auf ganzen
    // Gerätepixeln – nie ein halbes Pixel. Alle Kanten liegen ein Hundertstel Pixel innerhalb des
    // Rasters: Rundungsreste (z. B. 4/3 × 1,5 = 2,0000001) füllen so nie ein Pixel zusätzlich.
    readonly property real inset: 0.01
    function realign() {
        const p = caret.mapToItem(null, 0, 0)
        bar.x = (Math.round(p.x * dpr) + inset) / dpr - p.x
        bar.y = (Math.round((p.y + lineBaseline - ascent) * dpr) + inset) / dpr - p.y
    }
    // Nach jeder Bewegung sofort sichtbar, dann wieder blinken
    function restartBlink() {
        blinkOn = true
        if (blink.running)
            blink.restart()
    }

    onXChanged: { realign(); restartBlink() }
    onYChanged: { realign(); restartBlink() }
    onLineBaselineChanged: realign()
    onAscentChanged: realign()
    onDprChanged: realign()
    onVisibleChanged: if (visible) realign()  // auch nach Scrollen: beim nächsten Aufblinken
    Component.onCompleted: realign()

    Rectangle {
        id: bar
        objectName: "caretBar"
        // ≈ 1 px breit und so hoch wie die Schrift – jeweils ganze Gerätepixel
        width: (Math.max(1, Math.round(caret.dpr)) - 2 * caret.inset) / caret.dpr
        height: (Math.max(1, Math.round((caret.ascent + caret.descent) * caret.dpr)) - 2 * caret.inset) / caret.dpr
        color: caret.color
    }

    Timer {
        id: blink
        interval: Math.max(50, caret.flashTime / 2)
        running: caret.textItem !== null && caret.textItem.cursorVisible && caret.flashTime > 0
        repeat: true
        onTriggered: caret.blinkOn = !caret.blinkOn
        onRunningChanged: caret.blinkOn = true
    }
}
