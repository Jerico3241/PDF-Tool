import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Karte mit optionaler Kopfzeile (Symbol, Titel, Beschreibung, Aktionen rechts).
Rectangle {
    id: card
    property string title: ""
    property string subtitle: ""
    property string iconName: ""
    property int padding: Metrics.cardPadding
    property bool secondary: false
    default property alias content: body.data
    property alias headerRight: headerRightSlot.data
    property alias body: body

    implicitWidth: Math.max(280, body.implicitWidth + 2 * padding)
    implicitHeight: column.implicitHeight + 2 * padding
    radius: Metrics.radiusCard
    color: secondary ? Theme.surfaceSecondary : Theme.surface
    border.width: 1
    border.color: Theme.border

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false
            visible: card.title !== ""
            spacing: 12
            PIcon {
                name: card.iconName
                size: Metrics.iconSizeMedium
                color: Theme.textPrimary
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 1
                visible: card.iconName !== ""
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.alignment: Qt.AlignTop
                spacing: 2
                PText {
                    text: card.title
                    textStyle: "bodyStrong"
                    Layout.fillWidth: true
                    Accessible.role: Accessible.Heading
                }
                PText {
                    text: card.subtitle
                    textStyle: "caption"
                    tone: "secondary"
                    wrap: true
                    visible: text !== ""
                    Layout.fillWidth: true
                }
            }
            Row {
                id: headerRightSlot
                Layout.alignment: Qt.AlignTop
                spacing: 4
            }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: false
            spacing: 0
        }
        // Wird die Karte gestreckt (gleich hohe Karten nebeneinander), bleibt der Inhalt oben.
        Item {
            Layout.fillHeight: true
            Layout.fillWidth: true
            implicitHeight: 0
        }
    }
}
