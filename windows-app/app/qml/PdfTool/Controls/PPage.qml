import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Seite: Titel, Untertitel und Inhalt mit höchstens 1180 px Breite; natürliches Scrollen
// (Mausrad, Touchpad) ohne künstlich träges »Smooth Scrolling«.
// ``centered``: Inhalt mit gleichem Abstand links und rechts mittig (Startseite) – gerade Breite,
// damit zwei Spalten mit geradem Abstand pixelgenau gleich breit sind.
Item {
    id: page
    property string title: ""
    property string subtitle: ""
    property bool centered: false
    property int maxContentWidth: Metrics.pageMaxWidth
    default property alias content: column.data
    property alias flickable: flick
    property alias header: headerSlot.data
    readonly property real contentWidth: column.width
    readonly property int columns: contentWidth >= Metrics.twoColumnsFrom ? 2 : 1

    function scrollToTop() { revealAnim.stop(); flick.contentY = 0 }
    // Element in den sichtbaren Bereich holen (»Vollständig«: weich gescrollt). Ist es höher als
    // die Ansicht, steht sein Anfang oben.
    function reveal(item) {
        if (!item || !item.visible) return
        var top = item.mapToItem(flick.contentItem, 0, 0).y
        var target = flick.contentY
        if (top < flick.contentY || item.height + 32 > flick.height)
            target = top - 16
        else if (top + item.height > flick.contentY + flick.height)
            target = top + item.height - flick.height + 16
        target = Math.max(0, Math.min(Math.max(0, flick.contentHeight - flick.height), target))
        if (Math.abs(target - flick.contentY) < 1) return
        if (Motion.scroll > 0) {
            revealAnim.to = target
            revealAnim.restart()
        } else {
            flick.contentY = target
        }
    }
    NumberAnimation { id: revealAnim; target: flick; property: "contentY"; duration: Motion.scroll; easing.type: Motion.decelerate }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight + Metrics.pagePaddingTop + Metrics.pagePaddingBottom
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        clip: true
        T.ScrollBar.vertical: PScrollBar {}
        PWheelScroll { flickable: flick }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich

        ColumnLayout {
            id: column
            x: page.centered
               ? Math.round((flick.width - width) / 2)
               : Metrics.pagePaddingLeft + Math.max(0, (flick.width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight - page.maxContentWidth) / 2)
            y: Metrics.pagePaddingTop
            width: page.centered
                   ? Math.max(0, 2 * Math.floor(Math.min(page.maxContentWidth, flick.width - 2 * Metrics.pagePaddingLeft) / 2))
                   : Math.min(page.maxContentWidth, flick.width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight)
            spacing: 0

            ColumnLayout {
                objectName: "pageHeader"
                Layout.fillWidth: true
                Layout.bottomMargin: 20
                spacing: 2
                visible: page.title !== ""
                PText {
                    text: page.title
                    textStyle: "title"
                    Layout.fillWidth: true
                    Accessible.role: Accessible.Heading
                }
                PText {
                    text: page.subtitle
                    tone: "secondary"
                    wrap: true
                    visible: text !== ""
                    Layout.fillWidth: true
                }
                Item {
                    id: headerSlot
                    Layout.fillWidth: true
                    implicitHeight: childrenRect.height
                    visible: children.length > 0
                }
            }
        }
    }
}
