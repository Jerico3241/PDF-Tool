import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Linke Seitenleiste: Seiten (Miniaturen), Lesezeichen, Suche oder Anhänge. Umgeschaltet wird in ihrem Kopf, die
// geschlossene Leiste öffnet der Streifen am linken Rand (PanelRail). Die Breite ist fest – gleich, welcher
// Inhalt gezeigt wird. Der Inhalt wechselt mit einer kurzen Überblendung; beim Schließen bleibt er
// stehen, bis die Leiste weggeglitten ist.
Rectangle {
    id: root
    objectName: "readerLeftPanel"
    property var doc: null
    readonly property string panel: Reader.leftPanel
    // Zuletzt gezeigter Inhalt (bleibt beim Schließen, damit die Leiste nicht leer hinausgleitet)
    property string shown: "thumbs"
    onPanelChanged: if (panel !== "") shown = panel
    Component.onCompleted: if (panel !== "") shown = panel
    readonly property var titles: ({ thumbs: "Seiten", outline: "Lesezeichen", search: "Suchen", attachments: "Anhänge" })
    signal chosen(string key)  // Inhalt im Kopf gewählt
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider; z: 1 }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        PanelHeader {
            title: I18n.tr(root.titles[root.shown] || "", I18n.revision)
            current: root.shown
            // Umschalter stehen im Streifen links (SideRail), nicht mehr im Kopf
            onCloseRequested: Reader.setLeftPanel(root.panel)
            PText {
                objectName: "readerAttachmentsCount"
                visible: root.shown === "attachments" && root.doc !== null && root.doc.attachmentCount > 0
                text: I18n.tr(root.doc ? String(root.doc.attachmentCount) : "", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            PanelContent { shown: root.shown === "thumbs" && root.visible; sourceComponent: ThumbnailPanel { doc: root.doc } }
            PanelContent { shown: root.shown === "outline" && root.visible; sourceComponent: OutlinePanel { doc: root.doc } }
            PanelContent { shown: root.shown === "search" && root.visible; sourceComponent: SearchPanel { doc: root.doc } }
            PanelContent { shown: root.shown === "attachments" && root.visible; sourceComponent: AttachmentsPanel { doc: root.doc } }
        }
    }
}
