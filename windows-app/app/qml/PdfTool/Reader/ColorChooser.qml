import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Farbwahl der Werkzeuge (Text, Zeichnen, Markieren, Kommentare): Farben wie auf dem Papier.
T.Popup {
    id: popup
    property string current: ""
    signal picked(string color)
    padding: 8
    implicitWidth: grid.implicitWidth + leftPadding + rightPadding
    implicitHeight: grid.implicitHeight + topPadding + bottomPadding
    focus: true
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent

    background: Rectangle {
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusOverlay
        PShadow { radius: Metrics.radiusOverlay }
    }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.menu; easing.type: Motion.decelerate } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.enabled ? 83 : 0 } }

    contentItem: Grid {
        id: grid
        columns: 5
        spacing: 2
        Repeater {
            model: Reader.toolColors
            PSwatch {
                required property var modelData
                size: 30
                swatchColor: modelData.value
                tip: modelData.name
                selected: popup.current.toUpperCase() === String(modelData.value).toUpperCase()
                onClicked: {
                    popup.picked(modelData.value)
                    popup.close()
                }
            }
        }
    }
}
