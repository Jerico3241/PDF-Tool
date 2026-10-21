import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Kurzfassung des Vertragsvergleichs (in »Übersicht erstellen«): Hinweis oder »Seit …« mit den
// Anzahlen je Kategorie – die Einzelheiten zeigt die Ansicht »Vergleich«.
ColumnLayout {
    id: root
    property QtObject view: null
    property bool showOpen: true
    spacing: 8

    PInfoBar {
        Layout.fillWidth: true
        topMargin: 0
        closable: false
        shown: root.view !== null && root.view.noteText !== ""
        severity: root.view ? root.view.noteSeverity : "info"
        title: I18n.tr(root.view ? root.view.noteTitle : "", I18n.revision)
        message: I18n.tr(root.view ? root.view.noteText : "", I18n.revision)
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        spacing: 12
        PText { text: I18n.tr(root.view ? root.view.headline : "", I18n.revision); textStyle: "bodyStrong"; Layout.fillWidth: true }
        PButton {
            visible: root.showOpen
            text: I18n.tr("Vergleich öffnen", I18n.revision)
            iconName: "branch_compare"
            tip: I18n.tr("Alle Änderungen mit Einzelheiten anzeigen", I18n.revision)
            onClicked: Comparison.openDetails()
        }
    }
    PCountBar {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        items: root.view ? root.view.counts : []
    }
}
