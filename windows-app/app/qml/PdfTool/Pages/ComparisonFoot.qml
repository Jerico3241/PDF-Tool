import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// Unter der Liste: unveränderte Verträge zeigen, Änderungen kopieren, Angaben zum Stand.
ColumnLayout {
    id: root
    property QtObject view: null
    spacing: 8
    Flow {
        Layout.fillWidth: true
        spacing: 8
        PButton {
            kind: "subtle"
            iconName: "list"
            visible: root.view !== null && root.view.unchangedCount > 0
            text: I18n.tr(root.view ? root.view.unchangedLabel : "", I18n.revision)
            onClicked: root.view.toggleUnchanged()
        }
        PButton {
            kind: "subtle"
            iconName: "copy"
            visible: root.view !== null && root.view.canCopy
            text: I18n.tr("Änderungen kopieren", I18n.revision)
            tip: I18n.tr("Änderungen als Text in die Zwischenablage kopieren", I18n.revision)
            onClicked: root.view.copy()
        }
    }
    PFactList { Layout.fillWidth: true; labelWidth: 110; facts: root.view ? root.view.meta : [] }
}
