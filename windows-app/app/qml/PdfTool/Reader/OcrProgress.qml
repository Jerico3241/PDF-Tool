import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Karte oben über der Seite, solange die Texterkennung läuft: welche Seite gerade erkannt wird,
// Fortschritt und »Abbrechen«. Lesen, Blättern und Suchen bleiben möglich; Änderungen am Dokument warten,
// bis die Erkennung fertig ist. Blendet weich ein und aus (»Aus«: sofort).
Item {
    id: root
    objectName: "readerOcrProgress"
    property var doc: null
    readonly property bool present: doc !== null && doc.ocrRunning
    readonly property bool animating: heightAnim.running || fadeAnim.running
    readonly property int gap: 8

    implicitHeight: present ? card.height + gap : 0
    visible: present || animating
    opacity: present ? 1 : 0
    Behavior on implicitHeight { enabled: Motion.infoBar > 0; NumberAnimation { id: heightAnim; duration: Motion.infoBar; easing.type: Motion.decelerate } }
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate } }

    Rectangle {
        id: card
        objectName: "readerOcrProgressCard"
        y: root.gap
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(root.width, 460)
        height: column.implicitHeight + 20
        radius: Metrics.radiusOverlay
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        PShadow { radius: Metrics.radiusOverlay }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; preventStealing: true }

        ColumnLayout {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            anchors.leftMargin: 14
            spacing: 6
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PText {
                    objectName: "readerOcrStatus"
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    textStyle: "bodyStrong"
                    text: root.doc ? (root.doc.ocrStatus || "Text wird erkannt …") : ""
                }
                PButton {
                    objectName: "readerOcrCancel"
                    text: "Abbrechen"
                    onClicked: root.doc.cancelOcr()
                }
            }
            PProgressBar {
                objectName: "readerOcrBar"
                Layout.fillWidth: true
                indeterminate: root.doc !== null && root.doc.ocrTotal === 0
                value: root.doc && root.doc.ocrTotal > 0 ? root.doc.ocrDone / root.doc.ocrTotal : 0
            }
        }
    }
}
