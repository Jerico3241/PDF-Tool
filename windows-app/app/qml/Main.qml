import QtQuick
import QtQuick.Controls
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Shell
import PdfTool.Pages
import PdfTool.Reader

// Hauptfenster von PDF Tool. Das Fenster bleibt verborgen, bis Python Lage und Titelleiste
// gesetzt hat; es erscheint mit dem ersten vollständig gezeichneten Bild.
// Titel: »PDF Tool«, bei einer Beta mit Versionsnummer (»PDF Tool 2.8.0 Beta«).
ApplicationWindow {
    id: window
    objectName: "mainWindow"
    width: 1140
    height: 800
    visible: false
    title: App.windowTitle
    color: Theme.background
    font: Typography.body

    onClosing: (close) => { close.accepted = App.requestClose() }

    AppShell {
        id: shell
        objectName: "shell"
        anchors.fill: parent
        focus: true
        pages.order: ["home", "reader", "create", "layout", "preview", "templates", "rules", "batch", "comparison", "customers", "repair", "settings"]
        pages.components: ({
            "home": homePage,
            "reader": readerPage,
            "create": createPage,
            "layout": layoutPage,
            "preview": previewPage,
            "templates": templatesPage,
            "rules": rulesPage,
            "batch": batchPage,
            "comparison": comparisonPage,
            "customers": customersPage,
            "repair": repairPage,
            "settings": settingsPage
        })
    }
    Component { id: homePage; HomePage {} }
    Component { id: readerPage; ReaderPage {} }
    Component { id: createPage; CreatePage {} }
    Component { id: layoutPage; LayoutPage {} }
    Component { id: previewPage; PreviewPage {} }
    Component { id: templatesPage; TemplatesPage {} }
    Component { id: rulesPage; RulesPage {} }
    Component { id: batchPage; BatchPage {} }
    Component { id: comparisonPage; ComparisonPage {} }
    Component { id: customersPage; CustomersPage {} }
    Component { id: repairPage; RepairPage {} }
    Component { id: settingsPage; SettingsPage { onThemeRequested: (apply) => shell.changeTheme(apply) } }
}
