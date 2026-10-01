import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Ansichtswahl von »Vertragsübersichten«. »Vergleich« und »Kunden« erscheinen nur mit Kundenakte
// (weich ein- und ausgeblendet). Ist die Seite zu schmal, lässt sich die Leiste verschieben.
PSelectorBar {
    id: bar
    objectName: "contractViews"
    Layout.fillWidth: true
    Layout.maximumWidth: implicitWidth
    Layout.bottomMargin: 16
    current: App.currentPage
    // Liste bleibt stabil – nur ausblenden, nicht neu aufbauen (sonst entfällt die Blende)
    items: Contracts.views
    hiddenKeys: App.unavailablePages
    onSelected: (key) => App.navigate(key)
}
