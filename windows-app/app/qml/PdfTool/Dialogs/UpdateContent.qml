import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Details eines Updates: neue Version, Kanal, installierte Version, Datum, Größe und Release Notes.
// Die Release Notes kommen als geprüfte Blöcke aus Python (``updater.notes``): nur maskierter Text
// mit fett, kursiv, Code und https-Links – keine Bilder, kein HTML von außen. Links öffnen sich
// erst bei einem Klick im Standardbrowser.
ColumnLayout {
    id: root
    objectName: "updateDetails"
    property var request: ({})
    readonly property var data_: request.data || ({})
    function collect() { return ({}) }
    spacing: 12

    GridLayout {
        columns: 2
        columnSpacing: 20
        rowSpacing: 4
        Layout.fillWidth: true
        PText { text: "Neue Version"; tone: "secondary" }
        RowLayout {
            spacing: 8
            PText { objectName: "updateDetailsVersion"; text: root.data_.version || ""; textStyle: "bodyStrong" }
            PBadge { text: root.data_.beta ? "Beta" : ""; tone: "accent" }
        }
        PText { text: "Kanal"; tone: "secondary" }
        PText { text: root.data_.channel || "" }
        PText { text: "Installiert"; tone: "secondary" }
        PText { text: root.data_.installed || "" }
        PText { text: "Veröffentlicht"; tone: "secondary"; visible: (root.data_.date || "") !== "" }
        PText { text: root.data_.date || ""; visible: text !== "" }
        PText { text: "Downloadgröße"; tone: "secondary"; visible: (root.data_.size || "") !== "" }
        PText { text: root.data_.size || ""; visible: text !== "" }
    }

    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider; Layout.topMargin: 4 }

    PText { text: "Release Notes"; textStyle: "bodyStrong" }
    PText {
        text: "Für diese Version liegen keine Release Notes vor."
        tone: "secondary"
        visible: !root.data_.blocks || root.data_.blocks.length === 0
    }

    ColumnLayout {
        objectName: "updateNotes"
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: root.data_.blocks || []
            delegate: RowLayout {
                id: block
                required property var modelData
                readonly property string kind: modelData.kind
                Layout.fillWidth: true
                Layout.topMargin: kind === "heading" ? 8 : 0
                Layout.leftMargin: kind === "bullet" ? 4 + 18 * modelData.level : 0
                spacing: 8

                Rectangle {
                    visible: block.kind === "quote"
                    Layout.preferredWidth: 3
                    Layout.fillHeight: true
                    radius: 1.5
                    color: Theme.accent
                }
                Text {
                    visible: block.kind === "bullet"
                    text: block.modelData.marker
                    font: Typography.body
                    color: Theme.textSecondary
                    textFormat: Text.PlainText
                    Layout.alignment: Qt.AlignTop
                    Layout.minimumWidth: 12
                }
                Rectangle {
                    visible: block.kind === "rule"
                    Layout.fillWidth: true
                    height: 1
                    color: Theme.divider
                }
                Text {
                    visible: block.kind !== "rule"
                    Layout.fillWidth: true
                    text: block.modelData.html
                    textFormat: Text.RichText
                    wrapMode: Text.Wrap
                    font: block.kind === "heading" ? (block.modelData.level <= 2 ? Typography.subtitle : Typography.bodyStrong) : Typography.body
                    color: block.kind === "quote" ? Theme.textSecondary : Theme.textPrimary
                    linkColor: Theme.accentText
                    onLinkActivated: (link) => Updates.openLink(link)
                    Accessible.role: block.kind === "heading" ? Accessible.Heading : Accessible.StaticText
                    Accessible.name: block.modelData.html.replace(/<[^>]*>/g, "")
                    HoverHandler { cursorShape: parent.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
                }
            }
        }
    }

    PButton {
        visible: (root.data_.page || "") !== ""
        text: "Release auf GitHub ansehen"
        kind: "subtle"
        iconName: "open"
        onClicked: Updates.openLink(root.data_.page)
    }
}
