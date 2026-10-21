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
        PText { text: I18n.tr("Neue Version", I18n.revision); tone: "secondary" }
        RowLayout {
            spacing: 8
            PText { objectName: "updateDetailsVersion"; text: I18n.tr(root.data_.version || "", I18n.revision); textStyle: "bodyStrong" }
            PBadge { text: I18n.tr(root.data_.beta ? "Beta" : "", I18n.revision); tone: "accent" }
        }
        PText { text: I18n.tr("Kanal", I18n.revision); tone: "secondary" }
        PText { text: I18n.tr(root.data_.channel || "", I18n.revision) }
        PText { text: I18n.tr("Installiert", I18n.revision); tone: "secondary" }
        PText { text: I18n.tr(root.data_.installed || "", I18n.revision) }
        PText { text: I18n.tr("Veröffentlicht", I18n.revision); tone: "secondary"; visible: (root.data_.date || "") !== "" }
        PText { text: I18n.tr(root.data_.date || "", I18n.revision); visible: text !== "" }
        PText { text: I18n.tr("Downloadgröße", I18n.revision); tone: "secondary"; visible: (root.data_.size || "") !== "" }
        PText { text: I18n.tr(root.data_.size || "", I18n.revision); visible: text !== "" }
    }

    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider; Layout.topMargin: 4 }

    PText { text: I18n.tr("Release Notes", I18n.revision); textStyle: "bodyStrong" }
    PText {
        text: I18n.tr("Für diese Version liegen keine Release Notes vor.", I18n.revision)
        tone: "secondary"
        visible: !root.data_.blocks || root.data_.blocks.length === 0
    }

    PReleaseNotes {
        objectName: "updateNotes"
        Layout.fillWidth: true
        blocks: root.data_.blocks || []
    }

    PButton {
        visible: (root.data_.page || "") !== ""
        text: I18n.tr("Release auf GitHub ansehen", I18n.revision)
        kind: "subtle"
        iconName: "open"
        onClicked: Updates.openLink(root.data_.page)
    }
}
