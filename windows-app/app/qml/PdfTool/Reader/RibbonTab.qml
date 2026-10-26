import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style

// Reiter des Menübands (Datei, Start, Einfügen …): der gewählte fett und in der Farbe der Dateiart unterstrichen –
// gleich für PDFs, Texte und Tabellen.
T.AbstractButton {
    id: ribbonTab
    property string key: ""
    property string current: ""
    property color kindColor: Theme.accent
    readonly property bool selected: current === key
    implicitHeight: 38
    implicitWidth: ribbonLabel.implicitWidth + 2 * 10
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.role: Accessible.PageTab
    Accessible.name: I18n.tr(text, I18n.revision)
    Accessible.selected: selected
    background: Rectangle {
        radius: Metrics.radiusControl
        color: !ribbonTab.selected && ribbonTab.hovered ? Theme.subtleHover : "transparent"
        anchors.fill: parent
        anchors.topMargin: 4
        anchors.bottomMargin: 6
    }
    contentItem: Item {}
    Text {
        id: ribbonLabel
        anchors.centerIn: parent
        text: I18n.tr(ribbonTab.text, I18n.revision)
        font: ribbonTab.selected ? Typography.bodyStrong : Typography.body
        color: Theme.textPrimary
        textFormat: Text.PlainText
    }
    Rectangle {
        objectName: "ribbonUnderline"
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 3
        width: ribbonLabel.implicitWidth
        height: 3
        radius: 1.5
        color: ribbonTab.kindColor
        visible: ribbonTab.selected
    }
}
