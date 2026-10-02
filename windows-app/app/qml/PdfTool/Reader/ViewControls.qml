import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Leiste unten in der Ansicht: Seite (vor, zurück, Nummer eingeben) und Zoom
// (25–400 % in Stufen, frei per Strg+Mausrad, Seitenbreite, ganze Seite, Originalgröße).
Rectangle {
    id: root
    objectName: "readerViewControls"
    property var doc: null
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
        PIconButton { iconName: "chevron_left"; tip: "Vorherige Seite (Bild ↑)"; enabled: root.doc !== null && root.doc.currentPage > 0; onClicked: root.doc.step(-1) }
        PTextField {
            id: pageField
            objectName: "readerPageField"
            preferredWidth: 56
            horizontalAlignment: TextInput.AlignHCenter
            label: "Seite"
            text: root.doc ? String(root.doc.currentPage + 1) : ""
            validator: IntValidator { bottom: 1; top: root.doc ? Math.max(1, root.doc.pageCount) : 1 }
            onAccepted: {
                root.doc.goTo(parseInt(text) - 1)
                text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
            }
            onActiveFocusChanged: if (!activeFocus) text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
        }
        PText { text: root.doc ? "/ " + root.doc.pageCount : ""; tone: "secondary"; Layout.rightMargin: 4 }
        PIconButton { iconName: "chevron_right"; tip: "Nächste Seite (Bild ↓)"; enabled: root.doc !== null && root.doc.currentPage < root.doc.pageCount - 1; onClicked: root.doc.step(1) }
        Rectangle { Layout.preferredWidth: 1; Layout.preferredHeight: 20; Layout.leftMargin: 4; Layout.rightMargin: 4; color: Theme.divider }
        PIconButton { objectName: "readerZoomOut"; iconName: "zoom_out"; tip: "Verkleinern (Strg+−)"; onClicked: root.doc.zoomOut() }
        PButton {
            id: zoomButton
            objectName: "readerZoom"
            kind: "subtle"
            minimumWidth: 72
            text: root.doc ? Math.round(root.doc.zoom) + " %" : ""
            tip: "Zoomstufe wählen"
            onClicked: zoomMenu.popup(zoomButton, 0, -zoomMenu.implicitHeight - 4)
        }
        PIconButton { objectName: "readerZoomIn"; iconName: "zoom_in"; tip: "Vergrößern (Strg++)"; onClicked: root.doc.zoomIn() }
        PIconButton { objectName: "readerFitWidth"; iconName: "arrow_autofit_width"; tip: "Seitenbreite"; checkable: true; checked: root.doc !== null && root.doc.fit === "width"; onClicked: root.doc.fitWidth() }
        PIconButton { objectName: "readerFitPage"; iconName: "page_fit"; tip: "Ganze Seite (Strg+0)"; checkable: true; checked: root.doc !== null && root.doc.fit === "page"; onClicked: root.doc.fitPage() }
    }
    PMenu {
        id: zoomMenu
        PMenuItem { text: "25 %"; onTriggered: root.doc.setZoom(25) }
        PMenuItem { text: "50 %"; onTriggered: root.doc.setZoom(50) }
        PMenuItem { text: "75 %"; onTriggered: root.doc.setZoom(75) }
        PMenuItem { text: "100 % (Originalgröße)"; onTriggered: root.doc.actualSize() }
        PMenuItem { text: "125 %"; onTriggered: root.doc.setZoom(125) }
        PMenuItem { text: "150 %"; onTriggered: root.doc.setZoom(150) }
        PMenuItem { text: "200 %"; onTriggered: root.doc.setZoom(200) }
        PMenuItem { text: "300 %"; onTriggered: root.doc.setZoom(300) }
        PMenuItem { text: "400 %"; onTriggered: root.doc.setZoom(400) }
        PMenuItem { text: "Seitenbreite"; iconName: "arrow_autofit_width"; onTriggered: root.doc.fitWidth() }
        PMenuItem { text: "Ganze Seite"; iconName: "page_fit"; onTriggered: root.doc.fitPage() }
    }
}
