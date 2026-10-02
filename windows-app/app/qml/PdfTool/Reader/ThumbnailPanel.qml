import QtQuick
import QtQuick.Templates as T
import QtQuick.Window
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Miniaturen aller Seiten – virtualisiert (nur sichtbare entstehen und werden gerendert, mit
// niedriger Priorität nach den Seiten der Ansicht). Klick springt zur Seite; die aktuelle Seite
// ist markiert und bleibt im Blick. Ein fertiges Bild blendet kurz über das weiße Blatt ein (keine
// Bewegung); zeigt eine wiederverwendete Zeile eine andere Seite oder ein anderes Dokument, ist das alte
// Bild sofort weg (PageImage).
// Die Markierung der aktuellen Seite wechselt weich (Rahmenfarbe, Fläche, Strich links).
ListView {
    id: list
    objectName: "readerThumbnails"
    property var doc: null
    readonly property real ratio: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    readonly property int thumbWidth: Reader.thumbWidth

    model: doc ? doc.pageCount : 0
    clip: true
    reuseItems: true
    spacing: 4
    topMargin: 8
    bottomMargin: 8
    cacheBuffer: 400
    boundsBehavior: Flickable.StopAtBounds
    activeFocusOnTab: true
    currentIndex: doc ? doc.currentPage : -1
    highlightFollowsCurrentItem: false
    T.ScrollBar.vertical: PScrollBar {}
    Accessible.role: Accessible.List
    Accessible.name: "Seitenminiaturen"

    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
    Keys.onUpPressed: if (doc) doc.goTo(doc.currentPage - 1)
    Keys.onDownPressed: if (doc) doc.goTo(doc.currentPage + 1)

    delegate: Item {
        id: row
        required property int index
        readonly property var size: list.doc && index < list.doc.pageSizes.length ? list.doc.pageSizes[index] : [595, 842]
        readonly property real aspect: size[1] / Math.max(1, size[0])
        readonly property real thumbW: Math.min(list.thumbWidth, 200 / aspect)  // sehr hohe Seiten: höchstens 200 hoch
        readonly property real thumbHeight: thumbW * aspect
        readonly property bool current: list.doc !== null && list.doc.currentPage === index
        width: list.width
        height: thumbHeight + 32
        Accessible.role: Accessible.ListItem
        Accessible.name: "Seite " + (index + 1)
        Accessible.selected: current

        PListItem {
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            hovered: tap.hovered
            selected: row.current
        }
        Rectangle {
            id: paper
            anchors.horizontalCenter: parent.horizontalCenter
            y: 6
            width: row.thumbW
            height: row.thumbHeight
            color: Theme.paper
            border.width: row.current ? 2 : 1
            border.color: row.current ? Theme.accent : Theme.border
            Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            PageImage {
                id: image
                anchors.fill: parent
                anchors.margins: row.current ? 2 : 1
                source: list.doc ? "image://pdfpage/" + list.doc.docId + "/" + row.index + "/" + Math.round(paper.width * list.ratio) + "/" + list.doc.revision + "/thumb" : ""
            }
        }
        PText {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: paper.bottom
            anchors.topMargin: 4
            text: String(row.index + 1)
            textStyle: "caption"
            tone: row.current ? "accent" : "secondary"
        }
        HoverHandler { id: tap }
        TapHandler { onTapped: if (list.doc) list.doc.goTo(row.index) }
    }
}
