import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Farbauswahl für Kopf-/Fußzeile: Schnellfarben, weitere Farben und eigene Farbe (#RRGGBB).
T.Popup {
    id: flyout
    property QtObject document: null
    signal picked(string color)
    padding: 12
    implicitWidth: 260
    implicitHeight: content.implicitHeight + topPadding + bottomPadding
    focus: true
    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent

    function choose(value) {
        flyout.picked(value)
        flyout.close()
    }

    background: Rectangle {
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusOverlay
        PShadow { radius: Metrics.radiusOverlay }
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.menu; easing.type: Motion.decelerate }
            NumberAnimation { property: "y"; from: flyout.y - Motion.menuShift; to: flyout.y; duration: Motion.menu; easing.type: Motion.decelerate }
        }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.enabled ? 83 : 0 } }

    contentItem: ColumnLayout {
        id: content
        spacing: 8
        PText { text: "Schriftfarbe"; textStyle: "caption"; tone: "secondary" }
        Flow {
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: flyout.document ? flyout.document.quickColors : []
                PSwatch {
                    required property var modelData
                    size: 34
                    swatchColor: modelData.value
                    tip: modelData.name + " (" + modelData.value + ")"
                    selected: flyout.document && flyout.document.color.toUpperCase() === String(modelData.value).toUpperCase()
                    onClicked: flyout.choose(modelData.value)
                }
            }
        }
        PText { text: "Weitere Farben"; textStyle: "caption"; tone: "secondary"; Layout.topMargin: 4 }
        Flow {
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: flyout.document ? flyout.document.moreColors : []
                PSwatch {
                    required property var modelData
                    size: 28
                    swatchColor: modelData.value
                    tip: modelData.name + " (" + modelData.value + ")"
                    selected: flyout.document && flyout.document.color.toUpperCase() === String(modelData.value).toUpperCase()
                    onClicked: flyout.choose(modelData.value)
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4
            spacing: 8
            PTextField {
                id: hex
                Layout.fillWidth: true
                preferredWidth: 120
                placeholderText: "#RRGGBB"
                label: "Eigene Farbe"
                text: flyout.document && flyout.document.color !== "" ? flyout.document.color : ""
                validator: RegularExpressionValidator { regularExpression: /#?[0-9A-Fa-f]{0,6}/ }
                onSubmitted: apply.clicked()
            }
            PButton {
                id: apply
                text: "Übernehmen"
                enabled: /^#?[0-9A-Fa-f]{6}$/.test(hex.text)
                onClicked: flyout.choose(hex.text.charAt(0) === "#" ? hex.text : "#" + hex.text)
            }
        }
    }
}
