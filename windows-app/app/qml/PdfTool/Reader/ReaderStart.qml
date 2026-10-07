import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Reader ohne Dokument. Normalerweise nie zu sehen: PDFs öffnet man auf der Startseite (oder über »+«, Strg+O,
// Ziehen), der Reader erscheint mit dem ersten Dokument, und nach dem letzten geschlossenen Dokument geht es
// zur Startseite. Nur beim Start mit einer PDF (»Öffnen mit«) steht der Reader schon da, während sie lädt.
Item {
    id: root
    objectName: "readerStart"

    ColumnLayout {
        x: (parent.width - width) / 2
        y: Math.max(Metrics.s24, parent.height * 0.22)
        width: Math.min(parent.width - 48, 380)
        spacing: Metrics.s12

        PProgressRing { Layout.alignment: Qt.AlignHCenter; size: 32; visible: Reader.opening > 0; running: visible }
        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            visible: Reader.opening === 0
            implicitWidth: 48
            implicitHeight: 48
            radius: 24
            color: Theme.subtleHover
            PIcon { anchors.centerIn: parent; name: "document_pdf"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
        }
        PText {
            Layout.fillWidth: true
            text: Reader.opening > 0 ? "Wird geöffnet …" : "Kein Dokument geöffnet"
            textStyle: "bodyStrong"
            horizontalAlignment: Text.AlignHCenter
        }
        PText {
            Layout.fillWidth: true
            visible: Reader.opening === 0
            text: "PDFs öffnen Sie auf der Startseite, mit »+« in der Tab-Leiste oder mit Strg+O."
            tone: "secondary"
            wrap: true
            horizontalAlignment: Text.AlignHCenter
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: Metrics.s4
            spacing: Metrics.s8
            visible: Reader.opening === 0
            PButton { objectName: "readerOpenButton"; kind: "accent"; iconName: "folder_open"; text: "PDF öffnen"; tip: "Strg+O"; onClicked: Reader.openDialog() }
            PButton { iconName: "home"; text: "Zur Startseite"; onClicked: App.navigate("home") }
        }
    }
}
