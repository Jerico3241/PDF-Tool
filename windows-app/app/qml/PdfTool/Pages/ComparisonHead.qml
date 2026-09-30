import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// Kopf eines Vergleichs: Hinweis, »Seit …« mit »Vergleichen mit« und die Anzahlen je Kategorie.
ColumnLayout {
    id: root
    property QtObject view: null
    spacing: 8

    PInfoBar {
        Layout.fillWidth: true
        topMargin: 0
        closable: false
        shown: root.view !== null && root.view.noteText !== ""
        severity: root.view ? root.view.noteSeverity : "info"
        title: root.view ? root.view.noteTitle : ""
        message: root.view ? root.view.noteText : ""
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        spacing: 8
        PText { text: root.view ? root.view.headline : ""; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
        PText { text: "Vergleichen mit"; textStyle: "caption"; tone: "secondary" }
        PComboBox {
            preferredWidth: 250
            label: "Vergleichen mit"
            tip: "Früheren Vertragsstand dieses Kunden zum Vergleich wählen"
            model: root.view ? root.view.choices : []
            textRole: "label"
            valueRole: "value"
            currentIndex: {
                if (!root.view) return -1
                var choices = root.view.choices
                for (var i = 0; i < choices.length; ++i)
                    if (choices[i].value === root.view.baseline) return i
                return choices.length ? 0 : -1
            }
            onActivated: (index) => root.view.chooseBaseline(root.view.choices[index].value)
        }
    }
    PCountBar {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        items: root.view ? root.view.counts : []
    }
}
