import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Kontextmenü: blendet mit Deckkraft und leichter Bewegung ein (120–160 ms).
// ``afterClose``: Aktion, die erst nach dem Ausblenden läuft – etwa einen Editor öffnen. Beim Schließen gibt
// das Menü den Tastaturfokus zurück; ein schon geöffneter Editor verlöre ihn sonst wieder.
T.Menu {
    id: control
    property var afterClose: null
    onClosed: {
        var run = afterClose
        afterClose = null
        if (run) run()
    }
    implicitWidth: Math.max(200, contentItem.implicitWidth + leftPadding + rightPadding)
    implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
    margins: 8
    padding: 4
    overlap: 1
    font: Typography.body
    delegate: PMenuItem {}
    contentItem: ListView {
        implicitHeight: contentHeight
        implicitWidth: {
            var width = 0
            for (var i = 0; i < count; ++i) {
                var item = itemAtIndex(i)
                if (item) width = Math.max(width, item.implicitWidth)
            }
            return width
        }
        model: control.contentModel
        interactive: Window.window ? contentHeight + control.topPadding + control.bottomPadding > Window.window.height : false
        clip: true
        currentIndex: control.currentIndex
    }
    background: Rectangle {
        implicitWidth: 200
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusOverlay
        PShadow { radius: Metrics.radiusOverlay }
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.menu; easing.type: Motion.decelerate }
            NumberAnimation { property: "y"; from: control.y - Motion.menuShift; to: control.y; duration: Motion.menu; easing.type: Motion.decelerate }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.enabled ? 83 : 0; easing.type: Motion.accelerate }
    }
}
