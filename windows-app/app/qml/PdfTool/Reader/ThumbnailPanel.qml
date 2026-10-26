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
// Die Markierung der aktuellen Seite wechselt weich (Rahmenfarbe, Fläche, Strich links). Rechtsklick öffnet die
// Befehle der Seite (drehen, kopieren, einfügen, extrahieren, drucken, löschen …).
ListView {
    id: list
    PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
    objectName: "readerThumbnails"
    property var doc: null
    readonly property real ratio: Screen.devicePixelRatio > 0 ? Screen.devicePixelRatio : 1
    readonly property int thumbWidth: Reader.thumbWidth

    // Seitenmaße einmal je Änderung holen – nicht je Zeile die ganze Liste (große PDFs)
    readonly property var sizes: doc ? doc.pageSizes : []
    model: doc ? doc.pageCount : 0
    clip: true
    reuseItems: true
    spacing: 4
    topMargin: 8
    bottomMargin: 8
    // Ohne Vorrat außerhalb des Sichtbereichs: dessen Zeilen entstünden asynchron und würden beim schnellen
    // Wechsel der Seitenleiste mitten im Aufbau verworfen; sichtbare Zeilen werden wiederverwendet (reuseItems)
    cacheBuffer: 0
    boundsBehavior: Flickable.StopAtBounds
    activeFocusOnTab: true
    currentIndex: doc ? doc.currentPage : -1
    highlightFollowsCurrentItem: false
    T.ScrollBar.vertical: PScrollBar {}
    Accessible.role: Accessible.List
    Accessible.name: I18n.tr("Seitenminiaturen", I18n.revision)

    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
    // Seiten gelöscht oder eingefügt: das Modell beginnt neu (oben) – zurück zur aktuellen Seite
    onCountChanged: currentIndex = Qt.binding(function() { return list.doc ? list.doc.currentPage : -1 })
    Keys.onUpPressed: if (doc) doc.goTo(doc.currentPage - 1)
    Keys.onDownPressed: if (doc) doc.goTo(doc.currentPage + 1)

    delegate: Item {
        id: row
        required property int index
        readonly property var size: index < list.sizes.length ? list.sizes[index] : [595, 842]
        readonly property real aspect: size[1] / Math.max(1, size[0])
        readonly property real thumbW: Math.min(list.thumbWidth, 200 / aspect)  // sehr hohe Seiten: höchstens 200 hoch
        readonly property real thumbHeight: thumbW * aspect
        readonly property bool current: list.doc !== null && list.doc.currentPage === index
        width: list.width
        height: thumbHeight + 32
        Accessible.role: Accessible.ListItem
        Accessible.name: I18n.tr("Seite " + (index + 1), I18n.revision)
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
                // Beim Tabwechsel zeigen die Zeilen kurz noch Plätze des vorigen Dokuments – keine Bilder für Seiten,
                // die es im neuen Dokument nicht gibt
                url: list.doc && row.index < list.doc.pageCount ? "image://pdfpage/" + list.doc.docId + Reader.imageTag + "/" + row.index + "/" + Math.round(paper.width * list.ratio) + "/" + list.doc.revision + "/thumb" : ""
            }
        }
        PText {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: paper.bottom
            anchors.topMargin: 4
            text: I18n.tr(String(row.index + 1), I18n.revision)
            textStyle: "caption"
            tone: row.current ? "accent" : "secondary"
        }
        HoverHandler { id: tap }
        TapHandler { onTapped: if (list.doc) list.doc.goTo(row.index) }
        // Rechtsklick: Befehle für diese Seite (wie in »Seiten organisieren«)
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: (point) => {
                if (!list.doc) return
                pageMenu.page = row.index
                pageMenu.popup(row, point.position.x, point.position.y)
            }
        }
    }

    PMenu {
        id: pageMenu
        objectName: "readerThumbnailMenu"
        property int page: 0
        readonly property var pages: [page]
        PMenuItem { text: I18n.tr("Anzeigen", I18n.revision); iconName: "eye"; onTriggered: list.doc.goTo(pageMenu.page) }
        PMenuItem { text: I18n.tr("Nach rechts drehen", I18n.revision); iconName: "arrow_rotate_clockwise"; onTriggered: list.doc.rotatePages(pageMenu.pages, 90) }
        PMenuItem { text: I18n.tr("Nach links drehen", I18n.revision); iconName: "arrow_rotate_counterclockwise"; onTriggered: list.doc.rotatePages(pageMenu.pages, -90) }
        PMenuItem { text: I18n.tr("Duplizieren", I18n.revision); iconName: "document_copy"; onTriggered: list.doc.duplicatePages(pageMenu.pages) }
        PMenuItem { text: I18n.tr("Kopieren", I18n.revision); iconName: "copy"; onTriggered: list.doc.copyPages(pageMenu.pages) }
        PMenuItem { text: I18n.tr("Einfügen danach", I18n.revision); iconName: "clipboard_paste"; visible: Reader.pageClip > 0; onTriggered: list.doc.pastePages(pageMenu.page + 1) }
        PMenuItem { text: I18n.tr("Leere Seite danach einfügen", I18n.revision); iconName: "document_add"; onTriggered: list.doc.insertBlankPage(pageMenu.page + 1) }
        PMenuItem { text: I18n.tr("Als neue PDF speichern …", I18n.revision); iconName: "arrow_export"; onTriggered: list.doc.extractPages(pageMenu.pages) }
        PMenuItem { text: I18n.tr("Drucken …", I18n.revision); iconName: "print"; onTriggered: list.doc.printPages(pageMenu.pages) }
        PMenuItem { text: I18n.tr("Löschen", I18n.revision); iconName: "delete"; onTriggered: list.doc.deletePages(pageMenu.pages) }
    }
}
