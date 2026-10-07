import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Suche im Dokument (Strg+F): Begriff, Groß-/Kleinschreibung, ganzes Wort. Die Suche läuft im
// Hintergrund Seite für Seite (ab der aktuellen Seite) und lässt sich abbrechen; Treffer erscheinen
// sofort, F3 / Umschalt+F3 springen weiter. Die Liste zeigt die ersten 500 Treffer mit Ausschnitt.
ColumnLayout {
    id: root
    objectName: "readerSearchPanel"
    property var doc: null
    spacing: 8

    function run() {
        if (doc) doc.search(field.text, caseBox.checked, wordBox.checked)
    }
    function focusField() {
        field.forceActiveFocus(Qt.ShortcutFocusReason)
        field.selectAll()
    }
    readonly property int focusSerial: doc ? doc.searchFocusSerial : 0
    onFocusSerialChanged: focusField()
    // Begriff und Optionen gehören zum Dokument (jeder Tab behält seine eigene Suche)
    onDocChanged: {
        field.text = doc ? doc.searchText : ""
        caseBox.checked = doc ? doc.searchCase : false
        wordBox.checked = doc ? doc.searchWords : false
    }
    Component.onCompleted: {
        field.text = doc ? doc.searchText : ""
        caseBox.checked = doc ? doc.searchCase : false
        wordBox.checked = doc ? doc.searchWords : false
        focusField()
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        Layout.topMargin: 8
        spacing: 4
        PTextField {
            id: field
            objectName: "readerSearchField"
            Layout.fillWidth: true
            preferredWidth: 120
            label: "Suchbegriff"
            placeholderText: "Im Dokument suchen"
            onAccepted: {
                if (root.doc && text.trim() === root.doc.searchText && root.doc.searchCount > 0) root.doc.nextHit()
                else root.run()
            }
            Keys.onEscapePressed: (event) => {
                if (root.doc && root.doc.searchRunning) { root.doc.cancelSearch(); event.accepted = true }
                else event.accepted = false
            }
        }
        PIconButton {
            iconName: root.doc && root.doc.searchRunning ? "dismiss" : "search"
            tip: root.doc && root.doc.searchRunning ? "Suche abbrechen" : "Suchen"
            onClicked: root.doc && root.doc.searchRunning ? root.doc.cancelSearch() : root.run()
        }
    }
    Flow {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        spacing: 12
        PCheckBox { id: caseBox; objectName: "readerSearchCase"; text: "Groß-/Kleinschreibung"; onToggled: if (field.text.trim() !== "") root.run() }
        PCheckBox { id: wordBox; objectName: "readerSearchWords"; text: "Ganzes Wort"; onToggled: if (field.text.trim() !== "") root.run() }
    }
    PProgressBar {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 12
        visible: root.doc !== null && root.doc.searchRunning
        value: root.doc ? root.doc.searchProgress : 0
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.rightMargin: 8
        visible: root.doc !== null && root.doc.searchSummary !== ""
        PText {
            objectName: "readerSearchSummary"
            Layout.fillWidth: true
            text: root.doc ? (root.doc.searchCount > 0 && root.doc.searchIndex >= 0 ? (root.doc.searchIndex + 1) + " von " + root.doc.searchSummary : root.doc.searchSummary) : ""
            textStyle: "caption"
            tone: "secondary"
            wrap: true
        }
        PIconButton { iconName: "chevron_up"; tip: "Vorheriger Treffer (Umschalt+F3)"; enabled: root.doc !== null && root.doc.searchCount > 0; onClicked: root.doc.previousHit() }
        PIconButton { iconName: "chevron_down"; tip: "Nächster Treffer (F3)"; enabled: root.doc !== null && root.doc.searchCount > 0; onClicked: root.doc.nextHit() }
    }
    ListView {
        id: hitList
        PWheelScroll { flickable: hitList }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        Layout.fillWidth: true
        Layout.fillHeight: true
        model: root.doc ? root.doc.hits : null
        clip: true
        reuseItems: true
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: "Treffer"
        delegate: Item {
            id: hitRow
            required property int page
            required property int hit
            required property string excerpt
            readonly property int hitIndex: hit
            width: hitList.width
            height: excerptText.implicitHeight + pageText.implicitHeight + 14
            Accessible.role: Accessible.ListItem
            Accessible.name: "Seite " + (page + 1) + ": " + excerpt
            PListItem {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                hovered: hover.hovered
                selected: root.doc !== null && root.doc.searchIndex === hitRow.hitIndex
            }
            HoverHandler { id: hover }
            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                PText { id: pageText; text: "Seite " + (hitRow.page + 1); textStyle: "caption"; tone: "secondary" }
                PText { id: excerptText; width: parent.width; text: hitRow.excerpt; wrap: true; maximumLineCount: 2; elide: Text.ElideRight }
            }
            TapHandler { onTapped: root.doc.showHit(hitRow.hitIndex) }
        }
    }
}
