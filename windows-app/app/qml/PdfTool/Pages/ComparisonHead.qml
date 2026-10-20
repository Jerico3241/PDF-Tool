import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

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
        title: I18n.tr(root.view ? root.view.noteTitle : "", I18n.revision)
        message: I18n.tr(root.view ? root.view.noteText : "", I18n.revision)
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.view !== null && root.view.mode === "comparison"
        spacing: 8
        PText { text: I18n.tr(root.view ? root.view.headline : "", I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
        PText { text: I18n.tr("Vergleichen mit", I18n.revision); textStyle: "caption"; tone: "secondary" }
        PComboBox {
            preferredWidth: 250
            label: I18n.tr("Vergleichen mit", I18n.revision)
            tip: I18n.tr("Früheren Vertragsstand dieses Kunden zum Vergleich wählen", I18n.revision)
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
