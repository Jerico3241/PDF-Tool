import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Formel einfügen oder ändern (Texte, seit 5.0 Beta 5): die Formel in der Schreibweise von LibreOffice Math (Word
// und LibreOffice zeigen sie als echte Formel). Die Bausteine darunter fügen Bruch, Wurzel, Summe … an der
// Schreibmarke ein; »x« und »y« darin sind Platzhalter zum Überschreiben.
ColumnLayout {
    id: root
    objectName: "formulaContent"
    property var request: ({})
    readonly property bool acceptable: field.text.trim() !== ""
    readonly property bool handlesReturn: false
    readonly property var blocks: [
        { label: "Bruch", code: "{x} over {y}" }, { label: "Wurzel", code: "sqrt{x}" }, { label: "n-te Wurzel", code: "nroot{n}{x}" },
        { label: "Hochgestellt", code: "x^{2}" }, { label: "Tiefgestellt", code: "x_{i}" }, { label: "Summe", code: "sum from{i=1} to{n} x_i" },
        { label: "Integral", code: "int from{a} to{b} f(x) dx" }, { label: "Grenzwert", code: "lim from{x -> 0} f(x)" },
        { label: "Klammern", code: "left( x right)" }, { label: "Matrix", code: "left( matrix{a # b ## c # d} right)" },
        { label: "≤", code: " <= " }, { label: "≥", code: " >= " }, { label: "≠", code: " <> " }, { label: "≈", code: " approx " },
        { label: "·", code: " cdot " }, { label: "±", code: " +- " }, { label: "∞", code: "infinity" }, { label: "π", code: "%pi" },
        { label: "α", code: "%alpha" }, { label: "β", code: "%beta" }, { label: "Δ", code: "%DELTA" }, { label: "Σ", code: "%SIGMA" }
    ]
    function collect() { return { "formula": field.text } }
    function insert(code) {
        var area = field.area
        var start = area.selectionStart, end = area.selectionEnd
        area.remove(start, end)
        area.insert(start, code)
        area.cursorPosition = start + code.length
        area.forceActiveFocus()
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        field.text = (request.data || {}).formula || ""
        field.area.selectAll()
        field.area.forceActiveFocus(Qt.OtherFocusReason)
    }

    PFieldLabel { text: I18n.tr("Formel", I18n.revision); first: true }
    PTextArea {
        id: field
        objectName: "formulaText"
        Layout.fillWidth: true
        minLines: 3
        maxLines: 8
        label: I18n.tr("Formel", I18n.revision)
        placeholderText: I18n.tr("z. B. a^2 + b^2 = c^2", I18n.revision)
        area.font.family: "Consolas"
    }
    PFieldLabel { text: I18n.tr("Bausteine", I18n.revision) }
    Flow {
        Layout.fillWidth: true
        spacing: 4
        Repeater {
            model: root.blocks
            PButton {
                required property var modelData
                text: I18n.tr(modelData.label, I18n.revision)
                tip: I18n.tr(modelData.code.trim(), I18n.revision)
                minimumWidth: 36
                onClicked: root.insert(modelData.code)
            }
        }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 10
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Geschweifte Klammern fassen zusammen: »{a + b} over 2«. Eine eingefügte Formel lässt sich ändern, indem Sie sie anklicken und noch einmal »Formel« wählen.", I18n.revision)
    }
}
