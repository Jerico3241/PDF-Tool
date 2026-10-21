import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Farbwahl der Werkzeuge (Text, Zeichnen, Markieren, Kommentare): Farben wie auf dem Papier – oder eine eigene
// Farbe als Hexwert.
T.Popup {
    id: popup
    property string current: ""
    signal picked(string color)
    padding: 8
    implicitWidth: column.implicitWidth + leftPadding + rightPadding
    implicitHeight: column.implicitHeight + topPadding + bottomPadding
    // Eigene Farbe als Hexwert (#RRGGBB)
    function custom(text) {
        var value = String(text).trim()
        if (value.charAt(0) !== "#") value = "#" + value
        if (!/^#[0-9a-fA-F]{6}$/.test(value)) return false
        popup.picked(value.toUpperCase())
        popup.close()
        return true
    }
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

    contentItem: Column {
        id: column
        spacing: 8
        Grid {
            id: grid
            columns: 5
            spacing: 2
            Repeater {
                model: Reader.toolColors
                PSwatch {
                    required property var modelData
                    size: 30
                    swatchColor: modelData.value
                    tip: I18n.tr(modelData.name, I18n.revision)
                    selected: popup.current.toUpperCase() === String(modelData.value).toUpperCase()
                    onClicked: {
                        popup.picked(modelData.value)
                        popup.close()
                    }
                }
            }
        }
        Row {
            spacing: 4
            PTextField {
                id: hex
                objectName: "colorCustom"
                preferredWidth: grid.width - customButton.width - 4
                label: I18n.tr("Eigene Farbe (#RRGGBB)", I18n.revision)
                placeholderText: I18n.tr("#1E88E5", I18n.revision)
                text: popup.current
                onSubmitted: popup.custom(text)
            }
            PButton {
                id: customButton
                text: I18n.tr("OK", I18n.revision)
                onClicked: popup.custom(hex.text)
            }
        }
    }
}
