import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Leiste unten in der Ansicht: Seite (erste, vorherige, Nummer eingeben, nächste, letzte) und
// Zoom (Stufen 25–400 %, eigener Wert 10–800 % zum Eintippen, frei per Strg+Mausrad, Seitenbreite, ganze
// Seite, Originalgröße). Zoom über diese Leiste gleitet kurz (DocumentView.smoothly).
Rectangle {
    id: root
    objectName: "readerViewControls"
    property var doc: null
    property var view: null
    function zoom(action) {
        if (view) view.smoothly(action)
        else action()
    }
    // Strg+G: Seitennummer eingeben
    function focusPage() {
        pageField.forceActiveFocus(Qt.ShortcutFocusReason)
        pageField.selectAll()
    }
    function zoomText() { return doc ? Math.round(doc.zoom) + " %" : "" }
    implicitWidth: row.implicitWidth + 12
    implicitHeight: Metrics.controlHeight + 12
    radius: Metrics.radiusOverlay
    color: Theme.flyout
    border.color: Theme.flyoutStroke
    PShadow { radius: Metrics.radiusOverlay }

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 2
        PIconButton { objectName: "readerFirstPage"; iconName: "arrow_previous"; tip: I18n.tr("Erste Seite (Pos1)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage > 0; onClicked: root.doc.goTo(0) }
        PIconButton { iconName: "chevron_left"; tip: I18n.tr("Vorherige Seite (Bild ↑)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage > 0; onClicked: root.doc.step(-1) }
        PTextField {
            id: pageField
            objectName: "readerPageField"
            preferredWidth: 56
            horizontalAlignment: TextInput.AlignHCenter
            label: I18n.tr("Seite", I18n.revision)
            text: root.doc ? String(root.doc.currentPage + 1) : ""
            validator: IntValidator { bottom: 1; top: root.doc ? Math.max(1, root.doc.pageCount) : 1 }
            onAccepted: {
                root.doc.goTo(parseInt(text) - 1)
                text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
            }
            onActiveFocusChanged: if (!activeFocus) text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
        }
        PText { text: I18n.tr(root.doc ? "/ " + root.doc.pageCount : "", I18n.revision); tone: "secondary"; Layout.rightMargin: 4 }
        PIconButton { iconName: "chevron_right"; tip: I18n.tr("Nächste Seite (Bild ↓)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage < root.doc.pageCount - 1; onClicked: root.doc.step(1) }
        PIconButton { objectName: "readerLastPage"; iconName: "arrow_next"; tip: I18n.tr("Letzte Seite (Ende)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage < root.doc.pageCount - 1; onClicked: root.doc.goTo(root.doc.pageCount - 1) }
        Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; Layout.leftMargin: 4; Layout.rightMargin: 4; color: Theme.divider }
        PIconButton { objectName: "readerZoomOut"; iconName: "zoom_out"; tip: I18n.tr("Verkleinern" + Shortcuts.hints["reader.zoomOut"], I18n.revision); onClicked: root.zoom(function() { root.doc.zoomOut() }) }
        // Zoom: eigenen Wert eintippen (Eingabetaste) oder eine Stufe aus dem Menü wählen
        PTextField {
            id: zoomField
            objectName: "readerZoomField"
            preferredWidth: 64
            horizontalAlignment: TextInput.AlignHCenter
            label: I18n.tr("Zoom in Prozent", I18n.revision)
            text: root.zoomText()
            validator: RegularExpressionValidator { regularExpression: /^\s*\d{1,3}([,.]\d)?\s*%?\s*$/ }
            onAccepted: {
                var value = parseFloat(text.replace(",", ".").replace("%", ""))
                if (!isNaN(value) && root.doc) root.zoom(function() { root.doc.setZoom(value) })
                text = Qt.binding(root.zoomText)
                root.view.forceActiveFocus()
            }
            onActiveFocusChanged: {
                if (activeFocus) selectAll()
                else text = Qt.binding(root.zoomText)
            }
            Keys.onEscapePressed: { text = Qt.binding(root.zoomText); root.view.forceActiveFocus() }
        }
        PIconButton {
            id: zoomButton
            objectName: "readerZoom"
            implicitWidth: 24
            iconName: "chevron_down"
            tip: I18n.tr("Zoomstufe wählen", I18n.revision)
            onClicked: zoomMenu.popup(zoomButton, 0, -zoomMenu.implicitHeight - 4)
        }
        PIconButton { objectName: "readerZoomIn"; iconName: "zoom_in"; tip: I18n.tr("Vergrößern" + Shortcuts.hints["reader.zoomIn"], I18n.revision); onClicked: root.zoom(function() { root.doc.zoomIn() }) }
        PIconButton { objectName: "readerFitWidth"; iconName: "arrow_autofit_width"; tip: I18n.tr("Seitenbreite", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.fit === "width"; onClicked: root.zoom(function() { root.doc.fitWidth() }) }
        PIconButton { objectName: "readerFitPage"; iconName: "page_fit"; tip: I18n.tr("Ganze Seite" + Shortcuts.hints["reader.fitPage"], I18n.revision); toggle: true; checked: root.doc !== null && root.doc.fit === "page"; onClicked: root.zoom(function() { root.doc.fitPage() }) }
        Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; Layout.leftMargin: 4; Layout.rightMargin: 4; color: Theme.divider }
        PIconButton {
            objectName: "readerFullScreen"
            iconName: Reader.fullScreen ? "full_screen_minimize" : "full_screen_maximize"
            tip: I18n.tr(Reader.fullScreen ? "Vollbild beenden (" + (Shortcuts.labels["reader.fullScreen"] ? Shortcuts.labels["reader.fullScreen"] + ", " : "") + "Esc)" : "Vollbild" + Shortcuts.hints["reader.fullScreen"], I18n.revision)
            onClicked: Reader.toggleFullScreen()
        }
    }
    PMenu {
        id: zoomMenu
        PMenuItem { text: I18n.tr("25 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(25) }) }
        PMenuItem { text: I18n.tr("50 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(50) }) }
        PMenuItem { text: I18n.tr("75 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(75) }) }
        PMenuItem { text: I18n.tr("100 % (Originalgröße)", I18n.revision); onTriggered: root.zoom(function() { root.doc.actualSize() }) }
        PMenuItem { text: I18n.tr("125 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(125) }) }
        PMenuItem { text: I18n.tr("150 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(150) }) }
        PMenuItem { text: I18n.tr("200 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(200) }) }
        PMenuItem { text: I18n.tr("300 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(300) }) }
        PMenuItem { text: I18n.tr("400 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(400) }) }
        PMenuItem { text: I18n.tr("Seitenbreite", I18n.revision); iconName: "arrow_autofit_width"; onTriggered: root.zoom(function() { root.doc.fitWidth() }) }
        PMenuItem { text: I18n.tr("Ganze Seite", I18n.revision); iconName: "page_fit"; onTriggered: root.zoom(function() { root.doc.fitPage() }) }
    }
}
