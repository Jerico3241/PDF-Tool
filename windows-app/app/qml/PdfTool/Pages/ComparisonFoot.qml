import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

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
            text: root.view ? root.view.unchangedLabel : ""
            onClicked: root.view.toggleUnchanged()
        }
        PButton {
            kind: "subtle"
            iconName: "copy"
            visible: root.view !== null && root.view.canCopy
            text: "Änderungen kopieren"
            tip: "Änderungen als Text in die Zwischenablage kopieren"
            onClicked: root.view.copy()
        }
    }
    PFactList { Layout.fillWidth: true; labelWidth: 110; facts: root.view ? root.view.meta : [] }
}
