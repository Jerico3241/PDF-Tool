import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Vergleich« (nur mit Kundenakte): Neu, Entfernt, Geändert, Unverändert
// gegenüber einem gespeicherten Vertragsstand. Die Liste ist virtualisiert; geänderte Verträge
// klappen weich auf (Klick, Eingabe oder Leertaste).
PListPage {
    id: page
    objectName: "comparisonPage"
    title: I18n.tr("Vertragsübersichten", I18n.revision)
    subtitle: I18n.tr("Vertragsvergleich: was sich seit einem gespeicherten Stand dieses Kunden geändert hat.", I18n.revision)
    readonly property QtObject view: Comparison.single
    readonly property bool hasComparison: view.mode === "comparison"
    model: hasComparison ? view.changeModel : null
    Accessible.role: Accessible.List
    Accessible.name: I18n.tr("Vertragsänderungen", I18n.revision)
    Keys.onReturnPressed: toggleCurrent()
    Keys.onEnterPressed: toggleCurrent()
    Keys.onSpacePressed: toggleCurrent()
    onActiveFocusChanged: if (activeFocus && currentIndex < 0 && count > 0) currentIndex = 0
    function toggleCurrent() {
        if (currentIndex >= 0 && model) view.toggle(model.get(currentIndex).key)
    }

    headerContent: ColumnLayout {
        spacing: 0
        ContractViews {}
        // Ohne geprüfte Excel oder ohne früheren Stand: nur ein Hinweis
        Rectangle {
            Layout.fillWidth: true
            visible: !Comparison.visible
            implicitHeight: emptyColumn.implicitHeight + 56
            radius: Metrics.radiusCard
            color: Theme.surface
            border.color: Theme.border
            ColumnLayout {
                id: emptyColumn
                x: 24
                y: 28
                width: parent.width - 48
                spacing: 4
                PIcon { name: "branch_compare"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                PText { text: I18n.tr("Noch kein Vergleich", I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 6 }
                PText { text: I18n.tr("Der Vergleich erscheint, sobald in »Übersicht erstellen« eine geprüfte Excel-Liste und eine Kundenakte vorliegen.", I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                PButton { kind: "accent"; iconName: "document"; text: I18n.tr("Zu »Übersicht erstellen«", I18n.revision); Layout.topMargin: 10; onClicked: App.navigate("create") }
            }
        }
        PCard {
            Layout.fillWidth: true
            visible: Comparison.visible
            title: I18n.tr("Vertragsänderungen", I18n.revision)
            iconName: "history"
            subtitle: I18n.tr("Vergleich mit einem gespeicherten Vertragsstand dieses Kunden – nur zur Kontrolle, die PDF bleibt unverändert.", I18n.revision)
            ComparisonHead { Layout.fillWidth: true; view: page.view }
        }
        Item { implicitHeight: page.hasComparison && page.count > 0 ? 12 : 0 }
    }

    // Karte hinter den Zeilen
    Rectangle {
        parent: page.contentItem
        z: -1
        x: page.columnX
        y: -6  // die erste Zeile beginnt bei 0, der Kopfbereich liegt darüber
        width: page.columnWidth
        height: page.contentHeight - (page.headerItem ? page.headerItem.height : 0) - (page.footerItem ? page.footerItem.height : 0) + 12
        visible: page.count > 0
        radius: Metrics.radiusCard
        color: Theme.surface
        border.color: Theme.border
    }

    delegate: ChangeRow {
        listPage: page
        view: page.view
    }

    footerContent: ColumnLayout {
        spacing: 0
        ComparisonFoot { Layout.fillWidth: true; Layout.topMargin: 14; view: page.view; visible: page.hasComparison }
    }
}
