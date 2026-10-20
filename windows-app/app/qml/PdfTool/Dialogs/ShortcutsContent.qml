import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Übersicht der Tastenkürzel (Einstellungen › Tastenkürzel, Strg+F1): je Bereich die Befehle mit ihren Kürzeln.
// »Ändern« wartet auf die neue Tastenkombination (Esc bricht ab); ein Kürzel, das schon ein anderer Befehl hat,
// wechselt zu diesem Befehl. Feste Tasten stehen darunter zur Information. Änderungen gelten sofort.
ColumnLayout {
    id: root
    objectName: "shortcutsContent"
    property var request: ({})
    property string capturing: ""   // Befehl, der gerade auf Tasten wartet
    property string note: ""        // letzte Meldung (z. B. »… dort entfernt«)
    property string noteKey: ""     // Befehl, zu dem die Meldung gehört
    readonly property bool handlesReturn: capturing !== ""
    function collect() { return ({}) }
    spacing: 4

    function startCapture(key) {
        note = ""
        capturing = key
        capture.forceActiveFocus()
    }
    function stopCapture() {
        capturing = ""
        root.forceActiveFocus()
    }

    // Nimmt die Tasten auf, solange »Ändern« läuft – vor allen Tastenkürzeln des Fensters
    Item {
        id: capture
        objectName: "shortcutsCapture"
        width: 0
        height: 0
        Keys.onShortcutOverride: (event) => { if (root.capturing !== "") event.accepted = true }
        Keys.onPressed: (event) => {
            if (root.capturing === "") return
            event.accepted = true
            if (event.key === Qt.Key_Escape && event.modifiers === Qt.NoModifier) { root.stopCapture(); return }
            var sequence = Shortcuts.sequenceFor(event.key, event.modifiers)
            if (sequence === "") return  // nur Strg, Umschalt oder Alt: weiter warten
            var key = root.capturing
            var message = Shortcuts.assign(key, sequence)
            root.noteKey = key
            root.note = message
            // Ungültig: weiter warten; sonst fertig
            if (Shortcuts.keys[key].indexOf(sequence) >= 0) root.stopCapture()
        }
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: "Eigene Kürzel gelten sofort und bleiben gespeichert. Ein Kürzel gehört immer nur einem Befehl."
    }

    Repeater {
        model: Shortcuts.groups
        ColumnLayout {
            id: group
            required property var modelData
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 2
            PText { text: group.modelData.title; textStyle: "bodyStrong"; Accessible.role: Accessible.Heading }
            Repeater {
                model: group.modelData.items
                ColumnLayout {
                    id: entry
                    required property var modelData
                    readonly property bool waiting: root.capturing === modelData.key
                    Layout.fillWidth: true
                    spacing: 0
                    RowLayout {
                        objectName: "shortcutRow_" + entry.modelData.key
                        Layout.fillWidth: true
                        Layout.minimumHeight: 36
                        spacing: 8
                        PText { Layout.fillWidth: true; text: entry.modelData.label; elide: Text.ElideRight }
                        PText {
                            objectName: "shortcutKeys_" + entry.modelData.key
                            Layout.preferredWidth: 300
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                            textStyle: entry.waiting ? "body" : "bodyStrong"
                            tone: entry.waiting ? "accent" : (entry.modelData.keys.length ? "primary" : "tertiary")
                            text: entry.waiting ? "Tasten drücken … (Esc: abbrechen)" : (entry.modelData.keys.length ? entry.modelData.keys.join("  oder  ") : "ohne Kürzel")
                        }
                        PIconButton {
                            objectName: "shortcutChange_" + entry.modelData.key
                            iconName: "edit"
                            tip: "Ändern"
                            onClicked: entry.waiting ? root.stopCapture() : root.startCapture(entry.modelData.key)
                        }
                        PIconButton {
                            objectName: "shortcutClear_" + entry.modelData.key
                            iconName: "dismiss"
                            tip: "Kürzel entfernen"
                            enabled: entry.modelData.keys.length > 0
                            onClicked: { root.note = ""; Shortcuts.clear(entry.modelData.key) }
                        }
                        PIconButton {
                            objectName: "shortcutReset_" + entry.modelData.key
                            iconName: "arrow_reset"
                            tip: "Standard wiederherstellen"
                            opacity: entry.modelData.custom ? 1 : 0
                            enabled: entry.modelData.custom
                            onClicked: { root.note = ""; Shortcuts.reset(entry.modelData.key) }
                        }
                    }
                    PText {
                        objectName: "shortcutNote_" + entry.modelData.key
                        visible: root.note !== "" && root.noteKey === entry.modelData.key
                        Layout.fillWidth: true
                        Layout.bottomMargin: 4
                        wrap: true
                        textStyle: "caption"
                        tone: "warning"
                        text: root.note
                    }
                }
            }
            Repeater {
                model: group.modelData.fixed
                RowLayout {
                    id: fixed
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.minimumHeight: 30
                    spacing: 8
                    PText { Layout.fillWidth: true; text: fixed.modelData.label; tone: "secondary"; wrap: true }
                    PText {
                        Layout.preferredWidth: 300
                        horizontalAlignment: Text.AlignRight
                        tone: "secondary"
                        text: fixed.modelData.keys
                    }
                    // Platz der drei Schaltflächen oben, damit die Spalten bündig bleiben
                    Item { Layout.preferredWidth: 3 * Metrics.controlHeight + 16; Layout.preferredHeight: 1 }
                }
            }
        }
    }

    PButton {
        objectName: "shortcutsResetAll"
        Layout.topMargin: 12
        text: "Alle Tastenkürzel zurücksetzen"
        iconName: "arrow_reset"
        onClicked: { root.note = ""; root.stopCapture(); Shortcuts.resetAll() }
    }
}
