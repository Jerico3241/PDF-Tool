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
        title: root.view ? root.view.noteTitle : ""
        message: root.view ? root.view.noteText : ""
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        spacing: 12
        PText { text: root.view ? root.view.headline : ""; textStyle: "bodyStrong"; Layout.fillWidth: true }
        PButton {
            visible: root.showOpen
            text: "Vergleich öffnen"
            iconName: "branch_compare"
            tip: "Alle Änderungen mit Einzelheiten anzeigen"
            onClicked: Comparison.openDetails()
        }
    }
    PCountBar {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        items: root.view ? root.view.counts : []
    }
}
