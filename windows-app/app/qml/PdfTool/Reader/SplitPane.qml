import QtQml
import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Geteilte Ansicht (seit 4.0): rechts neben dem aktuellen PDF ein zweites geöffnetes PDF mit eigener Seite,
// eigenem Zoom und eigenem Werkzeug. Der Kopf nennt das PDF; ein Klick darauf wählt ein anderes geöffnetes
// PDF. Daneben: die Seiten tauschen, ein PDF öffnen und die geteilte Ansicht schließen.
Rectangle {
    id: root
    objectName: "readerSplitPane"
    readonly property var doc: Reader.splitDoc
    readonly property alias view: splitView
    color: Theme.viewer
    Rectangle { width: 1; height: parent.height; color: Theme.divider; z: 2 }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 1
        spacing: 0
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Metrics.readerPanelHeaderHeight
            color: Theme.layer
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.divider }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Metrics.s8
                anchors.rightMargin: Metrics.s6
                spacing: 2
                PButton {
                    id: chooser
                    objectName: "readerSplitChoose"
                    Layout.fillWidth: true
                    Layout.maximumWidth: implicitWidth
                    kind: "subtle"
                    iconName: "document_pdf"
                    text: root.doc ? root.doc.name + "  ▾" : ""
                    tip: "Anderes geöffnetes PDF rechts zeigen"
                    onClicked: chooseMenu.popup(chooser, 0, chooser.height)
                }
                Item { Layout.fillWidth: true }
                PIconButton { objectName: "readerSplitSwap"; iconName: "arrow_swap"; tip: "Seiten tauschen"; onClicked: Reader.swapSplit() }
                PIconButton { objectName: "readerSplitOpen"; iconName: "folder_open"; tip: "PDF rechts öffnen …"; onClicked: Reader.openSplitDialog() }
                PIconButton { objectName: "readerSplitClose"; iconName: "dismiss"; tip: "Geteilte Ansicht schließen"; onClicked: Reader.toggleSplit() }
            }
        }
        DocumentView {
            id: splitView
            objectName: "readerSplitView"
            Layout.fillWidth: true
            Layout.fillHeight: true
            doc: root.doc
        }
    }

    PMenu {
        id: chooseMenu
        objectName: "readerSplitMenu"
        Instantiator {
            model: Reader.tabs
            delegate: PMenuItem {
                required property string key
                required property string name
                text: name
                iconName: "document_pdf"
                visible: key !== Reader.currentKey
                checkable: true
                checked: key === Reader.splitKey
                onTriggered: Reader.setSplit(key)
            }
            onObjectAdded: (index, object) => chooseMenu.insertItem(index, object)
            onObjectRemoved: (index, object) => chooseMenu.removeItem(object)
        }
    }
}
