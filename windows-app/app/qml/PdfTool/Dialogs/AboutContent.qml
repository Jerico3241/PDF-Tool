import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// »Über«: Symbol, Name, Version, Entwickler, Beschreibung, Zitat und Namensnennung des Symbols.
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
            PText { text: I18n.tr(root.data_.name || "", I18n.revision); textStyle: "bodyLarge" }
            RowLayout {
                spacing: 8
                PText { objectName: "aboutVersion"; text: I18n.tr("Version " + (root.data_.version || ""), I18n.revision); tone: "secondary" }
                PBadge { text: I18n.tr(root.data_.beta ? "Beta" : "", I18n.revision); tone: "accent" }
            }
            PText { text: I18n.tr("Entwickler und Inhaber: " + (root.data_.developer || ""), I18n.revision); tone: "secondary"; Layout.topMargin: 2 }
        }
    }
    PText {
        text: I18n.tr(root.data_.text || "", I18n.revision)
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
            PText { text: I18n.tr(root.data_.quote || "", I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
            PText { text: I18n.tr(root.data_.author || "", I18n.revision); textStyle: "caption"; tone: "tertiary" }
        }
    }
    // Namensnennung des App-Symbols, von der Flaticon-Lizenz verlangt (siehe THIRD_PARTY_LICENSES.md)
    PText {
        objectName: "aboutIconCredit"
        text: I18n.tr("App-Symbol: »Pdf« von Magnific – Flaticon (flaticon.com)", I18n.revision)
        textStyle: "caption"
        tone: "tertiary"
        wrap: true
        Layout.fillWidth: true
    }
}
