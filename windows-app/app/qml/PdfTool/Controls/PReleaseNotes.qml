import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style

// Release Notes als geprüfte Blöcke aus Python (``updater.notes``): Überschriften, Punkte, Zitate, Absätze – nur
// maskierter Text mit fett, kursiv, Code und https-Links. Links öffnen sich erst bei einem Klick (``Updates.openLink``).
// In den Update-Details und (seit 4.0 Beta 7) direkt in der Update-Karte der Einstellungen.
ColumnLayout {
    id: notesRoot
    property var blocks: []
    spacing: 6
    Repeater {
        model: notesRoot.blocks || []
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
                text: I18n.tr(block.modelData.marker, I18n.revision)
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
                text: I18n.tr(block.modelData.html, I18n.revision)
                textFormat: Text.RichText
                wrapMode: Text.Wrap
                font: block.kind === "heading" ? (block.modelData.level <= 2 ? Typography.subtitle : Typography.bodyStrong) : Typography.body
                color: block.kind === "quote" ? Theme.textSecondary : Theme.textPrimary
                linkColor: Theme.accentText
                onLinkActivated: (link) => Updates.openLink(link)
                Accessible.role: block.kind === "heading" ? Accessible.Heading : Accessible.StaticText
                Accessible.name: I18n.tr(block.modelData.html.replace(/<[^>]*>/g, ""), I18n.revision)
                HoverHandler { cursorShape: parent.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
        }
    }
}
