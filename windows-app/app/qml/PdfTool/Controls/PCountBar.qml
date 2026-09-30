import QtQuick
import PdfTool.Style

// Zähler der Kategorien als farbige Punkte mit Text: »● 2 neu  ● 1 entfernt  ● 3 geändert«.
// Neue oder geänderte Anzahlen blenden dezent ein.
Flow {
    id: root
    property var items: []   // Liste aus {text, tone}
    spacing: 16
    Repeater {
        model: root.items
        Row {
            required property var modelData
            spacing: 6
            opacity: 0
            Component.onCompleted: opacity = 1
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.status } }
            Rectangle {
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.toneIconColor(modelData.tone)
            }
            PText { text: modelData.text; anchors.verticalCenter: parent.verticalCenter }
        }
    }
}
