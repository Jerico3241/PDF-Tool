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
    readonly property var office: sheet || textDoc
    // PDF (seit 5.0 Beta 3 wie Texte): links Seite und die letzte Meldung, rechts Speichern/Drucken und der Zoom
    readonly property var pdfDoc: App.currentPage === "reader" && Reader.current && Reader.current.kind !== "tabelle" && Reader.current.kind !== "text" ? Reader.current : null
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
    readonly property string sheetText: {
        if (!sheet) return ""
        var stats = sheet.stats || {}
        var parts = []
        if (stats.sum) parts.push(I18n.tr("Summe", I18n.revision) + ": " + stats.sum)
        if (stats.numbers > 1 && stats.average) parts.push(I18n.tr("Mittelwert", I18n.revision) + ": " + stats.average)
        if (stats.count > 0) parts.push(I18n.tr("Anzahl", I18n.revision) + ": " + stats.count)
        return parts.join("     ")
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 1
        color: Theme.divider
    }
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
            text: bar.zoomDoc && App.statusKind !== "busy" && App.statusKind !== "error" ? (bar.sheet ? bar.sheetText : (bar.textDoc ? bar.textText : bar.pdfText)) : (I18n.tr(App.statusText, I18n.revision) || "")
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
        Text {
            objectName: "textHints"
            visible: (bar.textDoc !== null || bar.pdfDoc !== null) && bar.width > 640
            readonly property string saveKey: (Shortcuts.hints["reader.save"] || "").replace(/[()]/g, "").trim()
            readonly property string printKey: (Shortcuts.hints["reader.print"] || "").replace(/[()]/g, "").trim()
            text: (saveKey ? saveKey + " " : "") + I18n.tr("Speichern", I18n.revision) + " · " + (printKey ? printKey + " " : "") + I18n.tr("Drucken", I18n.revision)
            font: Typography.caption
            color: Theme.textSecondary
            Layout.rightMargin: 12
        }
        Text {
            objectName: "sheetZoomText"
            visible: bar.zoomDoc !== null
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
