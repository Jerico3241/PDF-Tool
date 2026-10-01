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
    // Die erzeugten Inhalte von Kopf- und Fußbereich (z. B. für focusSearch() einer Seite)
    property Item headerContentItem: null
    property Item footerContentItem: null
    readonly property real columnWidth: Math.max(0, Math.min(Metrics.pageMaxWidth, width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight))
    readonly property real columnX: Metrics.pagePaddingLeft + Math.max(0, (width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight - Metrics.pageMaxWidth) / 2)
    readonly property int columns: columnWidth >= Metrics.twoColumnsFrom ? 2 : 1

    function scrollToTop() { positionViewAtBeginning() }

    // Wächst oder schrumpft der Kopfbereich (Hinweise, aufklappende Bereiche), bleibt eine Liste,
    // die ganz oben stand, oben – ListView hielte sonst die Zeilen fest und schöbe den Seitentitel
    // aus dem Bild. Wer gescrollt hat, behält seine Zeilen im Blick. Zurückgesetzt wird erst nach
    // dem Aufbau der Seite und verzögert (Qt.callLater): nie mitten in der Anordnung der ListView
    // oder während ihre Zeilen noch entstehen.
    property bool pinnedTop: true
    property bool _ready: false
    property bool _repin: false
    property real _headerHeight: -1
    Component.onCompleted: _ready = true
    function _trackTop() {
        // Während ListView auf einen geänderten Kopfbereich reagiert, gilt der alte Stand
        if (_repin || (headerItem && headerItem.height !== _headerHeight))
            return
        pinnedTop = contentY <= originY + 0.5
    }
    function _headerResized(height) {
        _headerHeight = height
        if (_ready && pinnedTop && !_repin) {
            _repin = true
            Qt.callLater(_keepTop)
        }
    }
    function _keepTop() {
        _repin = false
        if (!moving && contentY > originY + 0.5)
            positionViewAtBeginning()
        _trackTop()
    }
    onContentYChanged: _trackTop()
    onOriginYChanged: _trackTop()
    // Pos1/Ende und Bild ↑/↓ (5 Zeilen) wie bis 2.6; ↑/↓ übernimmt die ListView selbst
    function moveCurrent(index) {
        if (count === 0) return
        currentIndex = Math.max(0, Math.min(count - 1, index))
        positionViewAtIndex(currentIndex, ListView.Contain)
    }
    Keys.onPressed: (event) => {
        switch (event.key) {
        case Qt.Key_Home: moveCurrent(0); break
        case Qt.Key_End: moveCurrent(count - 1); break
        case Qt.Key_PageUp: moveCurrent(currentIndex - 5); break
        case Qt.Key_PageDown: moveCurrent(currentIndex < 0 ? 4 : currentIndex + 5); break
        default: return
        }
        event.accepted = true
    }

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
        onHeightChanged: page._headerResized(height)
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
                onLoaded: page.headerContentItem = item
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
            onLoaded: page.footerContentItem = item
        }
    }
}
