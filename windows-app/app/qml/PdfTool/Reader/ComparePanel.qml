import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vergleichen (seit 4.0): Ergebnis und Liste aller Unterschiede zwischen der älteren Fassung (links) und der
// neueren (rechts). Ein Klick zeigt die Stelle in beiden Fassungen; Pfeile springen weiter. Farben wie auf den
// Seiten: geändert gelb, neu grün, entfernt rot.
ColumnLayout {
    id: root
    objectName: "readerComparePanel"
    spacing: 8

    function kindName(kind) {
        return kind === "added" ? "Neu" : (kind === "removed" ? "Entfernt" : "Geändert")
    }
    function kindColor(kind) {
        return Theme.compareMarks[kind === "added" ? 1 : (kind === "removed" ? 2 : 0)]
    }

    PText {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        Layout.topMargin: 8
        visible: Reader.compareNames.length === 2
        text: Reader.compareNames.length === 2 ? "Links (älter): " + Reader.compareNames[0] + "\nRechts (neuer): " + Reader.compareNames[1] : ""
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }
    PText {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        visible: Reader.compareItems.length > 0
        text: Reader.compareSummary
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }
    PProgressBar {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        visible: Reader.compareRunning
        indeterminate: true
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 8
        PText {
            objectName: "readerCompareSummary"
            Layout.fillWidth: true
            text: Reader.compareItems.length > 0 && Reader.compareIndex >= 0 ? "Unterschied " + (Reader.compareIndex + 1) + " von " + Reader.compareItems.length : Reader.compareSummary
            wrap: true
        }
        PIconButton { objectName: "readerComparePrevious"; iconName: "chevron_up"; tip: "Vorheriger Unterschied"; enabled: Reader.compareItems.length > 0; onClicked: Reader.previousCompare() }
        PIconButton { objectName: "readerCompareNext"; iconName: "chevron_down"; tip: "Nächster Unterschied"; enabled: Reader.compareItems.length > 0; onClicked: Reader.nextCompare() }
    }
    ListView {
        id: list
        objectName: "readerCompareList"
        PWheelScroll { flickable: list }
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: Reader.compareItems
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: "Unterschiede"
        currentIndex: Reader.compareIndex
        onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
        delegate: Item {
            id: row
            required property var modelData
            required property int index
            width: list.width
            height: texts.implicitHeight + 14
            Accessible.role: Accessible.ListItem
            Accessible.name: root.kindName(modelData.kind) + ": " + (modelData.before || "") + " " + (modelData.after || "")
            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
                selected: Reader.compareIndex === row.index
            }
            HoverHandler { id: hover }
            Rectangle {
                x: 10
                width: 4
                radius: 2
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.margins: 8
                color: root.kindColor(row.modelData.kind)
            }
            Column {
                id: texts
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 22
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                PText {
                    text: root.kindName(row.modelData.kind) + " · Seite " + ((row.modelData.kind === "removed" ? row.modelData.oldPage : row.modelData.newPage) + 1)
                    textStyle: "caption"
                    tone: "secondary"
                }
                PText { width: parent.width; visible: row.modelData.before !== ""; text: (row.modelData.kind === "changed" ? "Vorher: " : "") + row.modelData.before; wrap: true; maximumLineCount: 2; elide: Text.ElideRight }
                PText { width: parent.width; visible: row.modelData.after !== ""; text: (row.modelData.kind === "changed" ? "Nachher: " : "") + row.modelData.after; wrap: true; maximumLineCount: 2; elide: Text.ElideRight }
            }
            TapHandler { onTapped: Reader.showCompare(row.index) }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        Layout.bottomMargin: 10
        PButton { objectName: "readerRecompare"; text: "Neu vergleichen"; iconName: "arrow_sync"; enabled: !Reader.compareRunning && Reader.compareActive; onClicked: Reader.recompare() }
        Item { Layout.fillWidth: true }
        PButton { objectName: "readerEndCompare"; text: "Beenden"; onClicked: Reader.endCompare() }
    }
}
