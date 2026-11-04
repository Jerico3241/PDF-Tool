import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Statuszeile: aktueller Zustand (weich überblendet) links, Tastenhinweise rechts.
Item {
    id: bar
    implicitHeight: Metrics.statusBarHeight
    Accessible.role: Accessible.StatusBar
    Accessible.name: I18n.tr(App.statusText, I18n.revision)
    // Tabelle (seit 5.0): links Summe und Anzahl der Auswahl, rechts der Zoom – wie in Excel
    readonly property var sheet: App.currentPage === "reader" && Reader.current && Reader.current.kind === "tabelle" ? Reader.current : null
    // Text (seit 5.0 Beta 3, wie im Design): links Seite, Wörter und Sprache, rechts Speichern/Drucken und der Zoom
    readonly property var textDoc: App.currentPage === "reader" && Reader.current && Reader.current.kind === "text" ? Reader.current : null
    // Präsentation (seit 5.0 Beta 4, wie im Entwurf): links die Folie und die Sprache, rechts Speichern,
    // »F5 Präsentieren« und der Zoom
    readonly property var slidesDoc: App.currentPage === "reader" && Reader.current && Reader.current.kind === "praesentation" ? Reader.current : null
    readonly property var office: sheet || textDoc || slidesDoc
    // PDF (seit 5.0 Beta 3 wie Texte): links Seite und die letzte Meldung, rechts Speichern/Drucken und der Zoom
    readonly property var pdfDoc: App.currentPage === "reader" && Reader.current && Reader.current.kind !== "tabelle" && Reader.current.kind !== "text" && Reader.current.kind !== "praesentation" ? Reader.current : null
    readonly property var zoomDoc: office || pdfDoc
    readonly property string pdfText: {
        if (!pdfDoc) return ""
        var parts = [I18n.tr("Seite " + (pdfDoc.currentPage + 1) + " von " + pdfDoc.pageCount, I18n.revision)]
        if (App.statusText && App.statusKind !== "neutral") parts.push(I18n.tr(App.statusText, I18n.revision))
        return parts.join("     ")
    }
    readonly property string textText: {
        if (!textDoc) return ""
        var parts = []
        if (textDoc.pageText) parts.push(I18n.tr(textDoc.pageText, I18n.revision))
        if (textDoc.wordText) parts.push(I18n.tr(textDoc.wordText, I18n.revision))
        if (textDoc.languageText) parts.push(I18n.tr(textDoc.languageText, I18n.revision))
        return parts.join("     ")
    }
    readonly property string slidesText: {
        if (!slidesDoc) return ""
        var parts = [I18n.tr("Folie " + (slidesDoc.slideIndex + 1) + " von " + slidesDoc.slideCount, I18n.revision)]
        if (slidesDoc.languageText) parts.push(I18n.tr(slidesDoc.languageText, I18n.revision))
        return parts.join("     ")
    }
    readonly property string sheetText: {
        if (!sheet) return ""
        var stats = sheet.stats || {}
        var parts = []
        if (stats.sum) parts.push(I18n.tr("Summe", I18n.revision) + ": " + stats.sum)
        if (stats.numbers > 1 && stats.average) parts.push(I18n.tr("Mittelwert", I18n.revision) + ": " + stats.average)
        if (stats.count > 0) parts.push(I18n.tr("Anzahl", I18n.revision) + ": " + stats.count)
        return parts.join("     ")
    }

    // 3D-Design: die Statuszeile liegt ohne Trennlinie auf dem Hintergrund (Entwurf 7)
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        spacing: 8
        Item {
            id: statusIcon
            objectName: "statusIcon"
            implicitWidth: 16
            implicitHeight: 16
            visible: !bar.zoomDoc || App.statusKind === "busy" || App.statusKind === "error"
            // Neuer Zustand: das Symbol blendet mit dem Text ein (»Vollständig«: wächst dabei leicht)
            readonly property string kind: App.statusKind
            onKindChanged: if (Motion.enabled && bar.visible) appear.restart()
            ParallelAnimation {
                id: appear
                NumberAnimation { target: statusIcon; property: "opacity"; from: 0; to: 1; duration: Motion.status; easing.type: Motion.decelerate }
                NumberAnimation { target: statusIcon; property: "scale"; from: Motion.moves ? 0.6 : 1; to: 1; duration: Motion.status; easing.type: Motion.decelerate }
            }
            PProgressRing {
                anchors.centerIn: parent
                size: 14
                visible: App.statusKind === "busy"
                running: visible
            }
            PIcon {
                anchors.centerIn: parent
                size: 14
                visible: App.statusKind !== "busy" && App.statusKind !== "neutral"
                name: Theme.toneIcon(App.statusKind)
                color: Theme.toneIconColor(App.statusKind)
            }
        }
        PCrossfadeText {
            id: status
            Layout.fillWidth: true
            Layout.fillHeight: true
            text: bar.zoomDoc && App.statusKind !== "busy" && App.statusKind !== "error" ? (bar.sheet ? bar.sheetText : (bar.textDoc ? bar.textText : (bar.slidesDoc ? bar.slidesText : bar.pdfText))) : (I18n.tr(App.statusText, I18n.revision) || "")
            font: Typography.caption
            color: Theme.textSecondary
            // Gekürzte Meldung: vollständig als Tooltip (wie bis 2.6.1)
            MouseArea {
                id: statusHover
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }
            PToolTip {
                text: I18n.tr(App.statusText, I18n.revision)
                visible: statusHover.containsMouse && status.truncated
            }
        }
        // Ansichten wie unten rechts in Word und PowerPoint (seit 5.0 Beta 10, Entwurf 7): Seitenlayout bzw. Normal ist
        // gewählt, daneben Lesemodus bzw. Präsentieren
        Row {
            objectName: "statusViews"
            visible: (bar.textDoc !== null || bar.slidesDoc !== null) && bar.width > 640
            spacing: 4
            Layout.rightMargin: 8
            PIconButton {
                objectName: "statusViewLayout"
                implicitWidth: 30
                implicitHeight: 24
                iconName: bar.slidesDoc ? "slide_multiple" : "document_one_page"
                tip: I18n.tr(bar.slidesDoc ? "Normal" : "Seitenlayout", I18n.revision)
                toggle: true
                checked: true
            }
            PIconButton {
                objectName: "statusViewSecond"
                implicitWidth: 30
                implicitHeight: 24
                iconName: bar.slidesDoc ? "presenter" : "book_open"
                tip: I18n.tr(bar.slidesDoc ? "Präsentieren (F5)" : "Lesemodus", I18n.revision)
                onClicked: bar.slidesDoc ? bar.slidesDoc.present() : bar.textDoc.requestReading()
            }
        }
        // Zoom: − Regler + und der Wert (100 % in der Mitte, links bis 10 %, rechts bis 500 % – wie in Office)
        PIconButton {
            objectName: "statusZoomOut"
            visible: bar.zoomDoc !== null && bar.width > 640
            implicitWidth: 24
            implicitHeight: 24
            iconName: "zoom_out"
            tip: I18n.tr("Verkleinern", I18n.revision)
            onClicked: bar.zoomDoc.setZoom(Math.max(10, Math.round(bar.zoomDoc.zoom / 10) * 10 - 10))
        }
        Item {
            id: zoomSlider
            objectName: "statusZoomSlider"
            visible: bar.zoomDoc !== null && bar.width > 640
            implicitWidth: 120
            implicitHeight: 20
            readonly property real zoom: bar.zoomDoc ? bar.zoomDoc.zoom : 100
            readonly property real position: zoom <= 100 ? 0.5 * (zoom - 10) / 90 : 0.5 + 0.5 * Math.min(1, (zoom - 100) / 400)
            function zoomAt(pos) {
                pos = Math.max(0, Math.min(1, pos))
                var value = pos <= 0.5 ? 10 + 90 * pos / 0.5 : 100 + 400 * (pos - 0.5) / 0.5
                return Math.abs(value - 100) < 6 ? 100 : Math.round(value)  // rastet bei 100 % ein
            }
            Accessible.role: Accessible.Slider
            Accessible.name: I18n.tr("Zoom", I18n.revision)
            Rectangle {
                id: track
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                height: 4
                radius: 2
                color: Theme.controlStroke
                Rectangle {
                    width: knob.x + knob.width / 2
                    height: parent.height
                    radius: 2
                    color: Theme.accent
                    Repeater {
                        model: Theme.glow > 0 ? 3 : 0
                        Rectangle {
                            required property int index
                            x: -(index + 1); y: -(index + 1)
                            width: parent.width + 2 * (index + 1); height: parent.height + 2 * (index + 1)
                            radius: height / 2
                            color: "transparent"
                            border.width: 1
                            border.color: Theme.accent
                            opacity: 0.25 * Theme.glow * (1 - index / 3)
                        }
                    }
                }
                Rectangle { x: parent.width / 2 - 0.5; y: -3; width: 1; height: 10; color: Theme.textTertiary }  // 100 %
            }
            Rectangle {
                id: knob
                width: 16
                height: 16
                radius: 8
                anchors.verticalCenter: parent.verticalCenter
                x: zoomSlider.position * (zoomSlider.width - width)
                color: Theme.neon ? Theme.surface : "#FFFFFF"
                border.width: 3
                border.color: Theme.accent
                scale: zoomDrag.pressed ? 1.15 : 1
                Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
                PShadow { radius: 8; depth: 2 }
            }
            MouseArea {
                id: zoomDrag
                anchors.fill: parent
                anchors.margins: -4
                onPressed: (mouse) => bar.zoomDoc.setZoom(zoomSlider.zoomAt((mouse.x - 4 - 8) / (zoomSlider.width - 16)))
                onPositionChanged: (mouse) => { if (pressed) bar.zoomDoc.setZoom(zoomSlider.zoomAt((mouse.x - 4 - 8) / (zoomSlider.width - 16))) }
            }
        }
        PIconButton {
            objectName: "statusZoomIn"
            visible: bar.zoomDoc !== null && bar.width > 640
            implicitWidth: 24
            implicitHeight: 24
            iconName: "zoom_in"
            tip: I18n.tr("Vergrößern", I18n.revision)
            onClicked: bar.zoomDoc.setZoom(Math.min(500, Math.round(bar.zoomDoc.zoom / 10) * 10 + 10))
        }
        Text {
            objectName: "sheetZoomText"
            visible: bar.zoomDoc !== null
            Layout.preferredWidth: 40
            horizontalAlignment: Text.AlignRight
            text: I18n.tr(bar.zoomDoc ? Math.round(bar.zoomDoc.zoom) + " %" : "", I18n.revision)
            font: Typography.caption
            color: Theme.textSecondary
        }
        Text {
            // Tastenhinweise behalten ihren Platz (wie 2.6.1) – gekürzt wird die Meldung links
            Layout.minimumWidth: implicitWidth
            text: I18n.tr(App.hint, I18n.revision)
            font: Typography.caption
            color: Theme.textTertiary
            elide: Text.ElideLeft
            textFormat: Text.PlainText
            visible: bar.width > 640 && bar.zoomDoc === null
        }
    }
}
