import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Ansichtswahl von »Vertragsübersichten«. »Vergleich« und »Kunden« erscheinen nur mit Kundenakte
// (weich ein- und ausgeblendet).
PSelectorBar {
    id: bar
    Layout.bottomMargin: 16
    current: App.currentPage
    items: {
        var views = Contracts.views
        var blocked = App.unavailablePages
        var result = []
        for (var i = 0; i < views.length; ++i)
            result.push({ key: views[i].key, label: views[i].label, available: blocked.indexOf(views[i].key) < 0 })
        return result
    }
    onSelected: (key) => App.navigate(key)
}
