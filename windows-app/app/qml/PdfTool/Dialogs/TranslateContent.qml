import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Dokument übersetzen« (KI-Assistent, seit 4.0 Beta 6): Zielsprache und Seiten wählen. Das Ergebnis ist ein neues PDF
// mit dem übersetzten Text; das Original bleibt unverändert. Seit 5.0 Beta 8 auch »nebeneinander«: Original und
// Übersetzung Absatz für Absatz in zwei Spalten als neues Text-Dokument – für Texte und Präsentationen der einzige Weg.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var languages: data_.languages || []
    readonly property int pageCount: data_.pageCount || 1
    readonly property string kind: data_.kind || "pdf"
    readonly property bool paged: kind !== "text"
    property string language: ""
    property string mode: "pdf"
    readonly property bool acceptable: language !== ""
    function collect() {
        var first = Math.max(1, Math.min(root.pageCount, parseInt(fromBox.text) || 1))
        var last = Math.max(first, Math.min(root.pageCount, parseInt(toBox.text) || root.pageCount))
        return { "language": root.language, "first": first - 1, "last": last - 1, "mode": root.kind === "pdf" ? root.mode : "side" }
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        root.language = data.language || ((data.languages || []).length ? data.languages[0].key : "")
        root.mode = data.mode === "side" ? "side" : "pdf"
        fromBox.text = "1"
        toBox.text = String(data.pageCount || 1)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: root.kind === "pdf"
              ? I18n.tr("Der Assistent übersetzt den Text Seite für Seite auf diesem PC und speichert ihn als neues PDF. Das Layout des Originals wird nicht nachgebaut. Je Seite dauert das etwa eine halbe bis zwei Minuten.", I18n.revision)
              : I18n.tr("Der Assistent übersetzt den Text Absatz für Absatz auf diesem PC. Das Ergebnis öffnet sich als neues Dokument mit Original und Übersetzung nebeneinander – zum Lesen, Bearbeiten oder Speichern.", I18n.revision)
    }
    PFieldLabel { visible: root.kind === "pdf"; text: I18n.tr("Ergebnis", I18n.revision) }
    ColumnLayout {
        visible: root.kind === "pdf"
        spacing: 2
        PRadioButton {
            objectName: "translateModePdf"
            text: I18n.tr("Als neues PDF (nur die Übersetzung)", I18n.revision)
            checked: root.mode === "pdf"
            onClicked: root.mode = "pdf"
        }
        PRadioButton {
            objectName: "translateModeSide"
            text: I18n.tr("Nebeneinander: Original und Übersetzung als neues Dokument", I18n.revision)
            checked: root.mode === "side"
            onClicked: root.mode = "side"
        }
    }
    PFieldLabel { text: I18n.tr("Übersetzen ins", I18n.revision) }
    Flow {
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: root.languages
            PRadioButton {
                required property var modelData
                objectName: "translateLanguage_" + modelData.key
                width: 150
                text: I18n.tr(modelData.label, I18n.revision)
                checked: root.language === modelData.key
                onClicked: root.language = modelData.key
            }
        }
    }
    PFieldLabel { visible: root.paged; text: root.kind === "praesentation" ? I18n.tr("Folien", I18n.revision) : I18n.tr("Seiten", I18n.revision) }
    RowLayout {
        visible: root.paged
        spacing: 8
        PText { text: I18n.tr("von", I18n.revision) }
        PTextField {
            id: fromBox
            objectName: "translateFrom"
            preferredWidth: 64
            label: root.kind === "praesentation" ? I18n.tr("Erste Folie", I18n.revision) : I18n.tr("Erste Seite", I18n.revision)
            validator: IntValidator { bottom: 1; top: root.pageCount }
        }
        PText { text: I18n.tr("bis", I18n.revision) }
        PTextField {
            id: toBox
            objectName: "translateTo"
            preferredWidth: 64
            label: root.kind === "praesentation" ? I18n.tr("Letzte Folie", I18n.revision) : I18n.tr("Letzte Seite", I18n.revision)
            validator: IntValidator { bottom: 1; top: root.pageCount }
        }
        PText { text: I18n.tr("von " + root.pageCount, I18n.revision); tone: "secondary" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        visible: root.kind === "pdf"
        text: I18n.tr("Scans ohne Text erkennt Novadesk vorher mit der Texterkennung, wenn sie eingerichtet ist. Übersetzungen können Fehler enthalten – wichtige Stellen bitte im Original prüfen.", I18n.revision)
    }
}
