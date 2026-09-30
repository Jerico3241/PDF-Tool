import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Über«: Symbol, Name, Version, Entwickler, Beschreibung und Zitat.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return ({}) }
    spacing: 16

    RowLayout {
        spacing: 16
        Layout.fillWidth: true
        Image {
            source: "image://appicon/64"
            sourceSize: Qt.size(64 * Screen.devicePixelRatio, 64 * Screen.devicePixelRatio)
            Layout.preferredWidth: 64
            Layout.preferredHeight: 64
            Layout.alignment: Qt.AlignTop
            smooth: true
            Accessible.ignored: true
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            PText { text: root.data_.name || ""; textStyle: "bodyLarge" }
            PText { text: "Version " + (root.data_.version || ""); tone: "secondary" }
            PText { text: "Entwickler und Inhaber: " + (root.data_.developer || ""); tone: "secondary"; Layout.topMargin: 2 }
        }
    }
    PText {
        text: root.data_.text || ""
        wrap: true
        Layout.fillWidth: true
    }
    RowLayout {
        spacing: 12
        Layout.fillWidth: true
        Rectangle {
            Layout.preferredWidth: 3
            Layout.fillHeight: true
            color: Theme.accent
            radius: 1.5
        }
        ColumnLayout {
            spacing: 4
            Layout.fillWidth: true
            PText { text: root.data_.quote || ""; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            PText { text: root.data_.author || ""; textStyle: "caption"; tone: "tertiary" }
        }
    }
}
