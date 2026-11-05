import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style
import PdfTool.Backend

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
    property int sidePadding: Metrics.pagePaddingLeft   // Rand links und rechts (zentriert)
    property int topPadding: Metrics.pagePaddingTop
    default property alias content: column.data
    property alias flickable: flick
    property alias header: headerSlot.data
    // Navigation links neben dem Inhalt (seit 5.0 Beta 10, Einstellungen wie im Entwurf 5): scrollt nicht mit
    property real sideWidth: 0
    property alias side: sideSlot.data
    readonly property real contentWidth: column.width
    readonly property int columns: contentWidth >= Metrics.twoColumnsFrom ? 2 : 1

    function scrollToTop() { revealAnim.stop(); flick.contentY = 0 }
    // Neuer Inhalt (z. B. anderer Bereich der Einstellungen, seit 5.0 Beta 11): gleitet von unten herein
    function enter() {
        if (!Motion.intros) return
        enterAnim.stop()
        column.opacity = 0
        enterShift.y = 40
        enterAnim.start()
    }
    ParallelAnimation {
        id: enterAnim
        NumberAnimation { target: column; property: "opacity"; to: 1; duration: 360; easing.type: Easing.OutCubic }
        NumberAnimation { target: enterShift; property: "y"; to: 0; duration: 620; easing.type: Easing.OutBack; easing.overshoot: 1.0 }
    }
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

    Item {
        id: sideSlot
        width: page.sideWidth
        height: parent.height
        visible: page.sideWidth > 0
    }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.leftMargin: page.sideWidth
        contentWidth: width
        contentHeight: column.implicitHeight + page.topPadding + Metrics.pagePaddingBottom
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        clip: true
        T.ScrollBar.vertical: PScrollBar {}
        PWheelScroll { flickable: flick }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich

        ColumnLayout {
            id: column
            transform: Translate { id: enterShift; y: 0 }
            x: page.centered
               ? Math.round((flick.width - width) / 2)
               : Metrics.pagePaddingLeft + Math.max(0, (flick.width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight - page.maxContentWidth) / 2)
            y: page.topPadding
            width: page.centered
                   ? Math.max(0, 2 * Math.floor(Math.min(page.maxContentWidth, flick.width - 2 * page.sidePadding) / 2))
                   : Math.min(page.maxContentWidth, flick.width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight)
            spacing: 0

            ColumnLayout {
                objectName: "pageHeader"
                Layout.fillWidth: true
                Layout.bottomMargin: 20
                spacing: 2
                visible: page.title !== ""
                PText {
                    text: I18n.tr(page.title, I18n.revision)
                    textStyle: "title"
                    Layout.fillWidth: true
                    Accessible.role: Accessible.Heading
                }
                PText {
                    text: I18n.tr(page.subtitle, I18n.revision)
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
