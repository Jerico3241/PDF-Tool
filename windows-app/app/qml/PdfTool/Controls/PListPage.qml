import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Seite mit langer Liste: Titel und Kopfbereich scrollen mit, die Zeilen sind virtualisiert
// (nur sichtbare Zeilen existieren – auch 500 Einträge bleiben flüssig).
// Zeilen setzen ihren Inhalt mit ``page.columnX`` und ``page.columnWidth`` auf die Seitenspalte.
ListView {
    id: page
    property string title: ""
    property string subtitle: ""
    property Component headerContent: null
    property Component footerContent: null
    readonly property real columnWidth: Math.max(0, Math.min(Metrics.pageMaxWidth, width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight))
    readonly property real columnX: Metrics.pagePaddingLeft + Math.max(0, (width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight - Metrics.pageMaxWidth) / 2)
    readonly property int columns: columnWidth >= Metrics.twoColumnsFrom ? 2 : 1

    function scrollToTop() { positionViewAtBeginning() }

    clip: true
    boundsBehavior: Flickable.StopAtBounds
    reuseItems: true
    cacheBuffer: 320
    keyNavigationEnabled: true
    highlightFollowsCurrentItem: false
    currentIndex: -1
    T.ScrollBar.vertical: PScrollBar {}

    header: Item {
        width: page.width
        height: headerColumn.implicitHeight + Metrics.pagePaddingTop
        ColumnLayout {
            id: headerColumn
            x: page.columnX
            y: Metrics.pagePaddingTop
            width: page.columnWidth
            spacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 20
                spacing: 2
                visible: page.title !== ""
                PText { text: page.title; textStyle: "title"; Layout.fillWidth: true; Accessible.role: Accessible.Heading }
                PText { text: page.subtitle; tone: "secondary"; wrap: true; visible: text !== ""; Layout.fillWidth: true }
            }
            Loader {
                Layout.fillWidth: true
                sourceComponent: page.headerContent
                visible: status === Loader.Ready
            }
        }
    }
    footer: Item {
        width: page.width
        height: footerLoader.implicitHeight + Metrics.pagePaddingBottom
        Loader {
            id: footerLoader
            x: page.columnX
            width: page.columnWidth
            sourceComponent: page.footerContent
        }
    }
}
