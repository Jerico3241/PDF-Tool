import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Texteingabe über der Seite: Textblock ändern (Werkzeug »Text bearbeiten«), ein einzelnes Segment
// oder Wort ändern (»Objekt bearbeiten«, einzeilig: Eingabe übernimmt), Text hinzufügen, Notiz oder
// Textfeld. Strg+Eingabe übernimmt, Esc bricht ab. Beim Ändern eines Blocks nennt die
// Zeile unter dem Feld Schrift und Größe und ob die Änderung direkt im PDF möglich ist; welcher
// Weg tatsächlich genommen wurde (»Direkt im PDF geändert«, »Neu gesetzt«, »Kompatibilitätsmodus«),
// meldet der Hinweis nach dem Übernehmen. Nur geänderte Stilwerte gehen an Python – so bleibt der
// direkte Weg mit der Originalschrift möglich.
Item {
    id: root
    objectName: "readerTextEditor"
    property var host: null
    property var doc: null
    property var request: null
    signal finished()

    // Bindungen lesen ``request`` selbst (nicht abgeleitete Werte wie ``open``) – ein Handler kann
    // laufen, bevor abgeleitete Bindungen neu berechnet sind
    readonly property bool open: !!request
    readonly property string kind: request ? request.kind : ""
    readonly property real s: host ? host.zoomScale : 1
    readonly property rect pageArea: request && host ? host.pageRectFor(request.page, host.layoutSerial) : Qt.rect(0, 0, 0, 0)
    readonly property var block: request && request.kind === "block" ? request.block : null
    readonly property bool styled: kind === "block" || kind === "text"

    property real size: 12
    property bool bold: false
    property bool italic: false
    property string color: "#000000"
    property string family: "Helvetica"
    property string align: "left"
    property bool underline: false   // Linie unter bzw. durch den Text (wird beim Übernehmen gezeichnet)
    property bool strike: false
    property bool styleTouched: false
    property bool familyTouched: false  // die Schrift wird nur geschickt, wenn sie gewählt wurde

    visible: open
    // Öffnen: kurz einblenden (wie Menüs und Hinweise); ein Wechsel zum nächsten Textblock bleibt ruhig
    onOpenChanged: if (open && Motion.enabled) appear.restart()
    NumberAnimation { id: appear; target: root; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
    // An der Stelle in der Seite – die Leiste bleibt aber ganz im sichtbaren Bereich (breite Leiste, Text am
    // rechten Rand)
    readonly property real wantedX: pageArea.x + (request ? request.rect[0] * s : 0) - 4
    x: host ? Math.max(host.contentX + 8, Math.min(wantedX, host.contentX + host.width - width - 8)) : wantedX
    y: pageArea.y + (request ? request.rect[1] * s : 0) - 4 - bar.height - 6
    width: Math.max(box.width + 8, bar.wanted)
    height: column.implicitHeight

    onRequestChanged: if (request) setup(request)

    // Breite aller sichtbaren Elemente in einer Zeile (Wiederholer selbst haben keine Breite)
    function rowWidth(container) {
        var total = 0, count = 0
        for (var i = 0; i < container.children.length; ++i) {
            var item = container.children[i]
            if (!item.visible || item.width <= 0) continue
            total += item.width
            count += 1
        }
        return total + Math.max(0, count - 1) * container.spacing
    }
    function displayFamily(name) {
        var lower = String(name).toLowerCase()
        if (lower.indexOf("times") >= 0 || lower.indexOf("serif") >= 0 && lower.indexOf("sans") < 0) return "Times New Roman"
        if (lower.indexOf("courier") >= 0 || lower.indexOf("mono") >= 0) return "Courier New"
        return "Arial"
    }
    function setup(r) {
        styleTouched = false
        familyTouched = false
        underline = false
        strike = false
        if (r.kind === "block") {
            var b = r.block
            size = b.size
            bold = b.bold
            italic = b.italic
            color = b.color
            family = b.font
            align = b.align || "left"
        } else if (r.kind === "text") {
            size = doc ? doc.fontSize : 12
            bold = false
            italic = false
            color = "#000000"
            family = "Helvetica"
            align = "left"
        } else if (r.kind === "object") {
            var o = r.object
            size = o.size
            bold = String(o.font).toLowerCase().indexOf("bold") >= 0
            italic = String(o.font).toLowerCase().indexOf("italic") >= 0 || String(o.font).toLowerCase().indexOf("oblique") >= 0
            color = o.color
            family = o.font
            align = "left"
        } else {
            size = r.kind === "textbox" && doc ? doc.fontSize : 11
            color = r.kind === "textbox" && doc ? doc.toolColor : "#000000"
        }
        input.text = r.text || ""
        Qt.callLater(function() {
            if (root.request !== r) return
            input.forceActiveFocus(Qt.OtherFocusReason)
            if (r.kind === "block") input.selectAll()
            else if (r.kind === "object") input.cursorPosition = Math.max(0, Math.min(input.length, r.caret !== undefined ? r.caret : input.length))
            else input.cursorPosition = input.length
        })
    }
    function commit() {
        var r = request
        if (!r || !doc) return
        var text = input.text
        var block = r.block
        if (r.kind === "block") {
            var style = {}
            if (styleTouched) {
                if (Math.abs(size - block.size) > 0.05) style.size = size
                if (bold !== block.bold) style.bold = bold
                if (italic !== block.italic) style.italic = italic
                if (color.toUpperCase() !== String(block.color).toUpperCase()) style.color = color
                if (familyTouched) style.family = family
                if (align !== (block.align || "left")) style.align = align
                if (underline) style.underline = true
                if (strike) style.strike = true
            }
            if (text !== block.text || Object.keys(style).length > 0) doc.editBlock(r.page, block.id, text, style)
        } else if (r.kind === "text") {
            if (text.trim() !== "") doc.addText(r.page, r.rect[0], r.rect[1], text, { "family": family, "size": size, "bold": bold, "italic": italic, "color": color, "align": align, "underline": underline, "strike": strike })
        } else if (r.kind === "note") {
            if (text.trim() !== "") doc.addNote(r.page, r.rect[0], r.rect[1], text)
        } else if (r.kind === "textbox") {
            if (text.trim() !== "") doc.addTextbox(r.page, r.rect, text)
        } else if (r.kind === "object") {
            if (text !== r.text) doc.editObject(r.page, r.object.id, text)
        }
        finished()
        if (host) host.focusByPointer()  // Tastatur wieder in der Seite (Pfeiltasten, Entf, Tab)
    }
    function cancel() {
        finished()
        if (host) host.focusByPointer()
    }

    ColumnLayout {
        id: column
        width: parent.width
        spacing: 6

        // Leiste: Stil (Text ändern/hinzufügen), Abbrechen, Übernehmen
        Rectangle {
            id: bar
            // So breit wie nötig, höchstens so breit wie die sichtbare Ansicht – dann bricht die Leiste um
            readonly property real room: root.host ? Math.max(200, root.host.width - 16) : 100000
            readonly property real wanted: Math.min(root.rowWidth(barRow) + 12, room)
            Layout.preferredWidth: wanted
            Layout.preferredHeight: barRow.height + 12
            color: Theme.flyout
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusOverlay
            PShadow { radius: Metrics.radiusOverlay }
            Flow {
                id: barRow
                x: 6
                y: 6
                width: bar.width - 12
                spacing: 4
                PComboBox {
                    objectName: "readerEditorFamily"
                    visible: root.styled
                    preferredWidth: 190
                    label: "Schriftart"
                    model: Reader.fontFamilies
                    textRole: "label"
                    valueRole: "value"
                    // Ein bestehender Block zeigt seine Schrift, solange keine andere gewählt ist
                    displayText: root.kind === "block" && !root.familyTouched ? String(root.family).split("+").pop() : currentText
                    currentIndex: Math.max(0, indexOfValue(root.family))
                    onActivated: (index) => { root.family = Reader.fontFamilies[index].value; root.familyTouched = true; root.styleTouched = true }
                }
                PTextField {
                    visible: root.styled
                    objectName: "readerEditorSize"
                    preferredWidth: 64
                    label: "Schriftgröße (pt)"
                    text: (Math.round(root.size * 10) / 10).toLocaleString(Qt.locale("de_DE"), "f", root.size % 1 === 0 ? 0 : 1)
                    validator: DoubleValidator { bottom: 4; top: 144; decimals: 1; locale: "de_DE" }
                    onEditingFinished: {
                        var value = Number.fromLocaleString(Qt.locale("de_DE"), text)
                        if (!isNaN(value) && value >= 4 && value <= 144) { root.size = value; root.styleTouched = true }
                    }
                }
                PIconButton {
                    visible: root.styled
                    iconName: "text_bold"
                    tip: "Fett"
                    toggle: true
                    checked: root.bold
                    onClicked: { root.bold = !root.bold; root.styleTouched = true }
                }
                PIconButton {
                    visible: root.styled
                    iconName: "text_italic"
                    tip: "Kursiv"
                    toggle: true
                    checked: root.italic
                    onClicked: { root.italic = !root.italic; root.styleTouched = true }
                }
                PIconButton {
                    objectName: "readerEditorUnderline"
                    visible: root.styled
                    iconName: "text_underline"
                    tip: "Unterstreichen (zeichnet eine Linie in der Textfarbe)"
                    toggle: true
                    checked: root.underline
                    onClicked: { root.underline = !root.underline; root.styleTouched = true }
                }
                PIconButton {
                    objectName: "readerEditorStrike"
                    visible: root.styled
                    iconName: "text_strikethrough"
                    tip: "Durchstreichen (zeichnet eine Linie in der Textfarbe)"
                    toggle: true
                    checked: root.strike
                    onClicked: { root.strike = !root.strike; root.styleTouched = true }
                }
                Rectangle { visible: root.styled; width: 1; height: Metrics.controlHeight; color: Theme.divider }
                Repeater {
                    model: root.styled ? [{ value: "left", icon: "text_align_left", tip: "Linksbündig" }, { value: "center", icon: "text_align_center", tip: "Zentriert" }, { value: "right", icon: "text_align_right", tip: "Rechtsbündig" }] : []
                    PIconButton {
                        required property var modelData
                        objectName: "readerEditorAlign_" + modelData.value
                        iconName: modelData.icon
                        tip: modelData.tip
                        toggle: true
                        checked: root.align === modelData.value
                        onClicked: { root.align = modelData.value; root.styleTouched = true }
                    }
                }
                PIconButton {
                    id: colorButton
                    visible: root.styled
                    iconName: "text_color"
                    tip: "Textfarbe"
                    onClicked: colors.open()
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 4
                        width: 16
                        height: 3
                        color: root.color
                    }
                    ColorChooser {
                        id: colors
                        y: colorButton.height + 4
                        current: root.color
                        onPicked: (value) => { root.color = value; root.styleTouched = true }
                    }
                }
                Rectangle { visible: root.styled; width: 1; height: Metrics.controlHeight; color: Theme.divider }
                PButton {
                    text: "Abbrechen"
                    onClicked: root.cancel()
                }
                PButton {
                    objectName: "readerEditorApply"
                    kind: "accent"
                    text: "Übernehmen"
                    tip: "Strg+Eingabe"
                    onClicked: root.commit()
                }
            }
        }

        Rectangle {
            id: box
            readonly property real minWidth: root.block ? (root.block.view[2] - root.block.view[0]) * root.s + 8 : (root.kind === "object" && root.request ? (root.request.rect[2] - root.request.rect[0]) * root.s + 24 : 160)
            Layout.preferredWidth: Math.max(minWidth, Math.min(input.contentWidth + 16, 900), 160)
            Layout.preferredHeight: Math.max(input.contentHeight + 8, root.request ? (root.request.rect[3] - root.request.rect[1]) * root.s + 8 : 0, 28)
            color: Theme.paper
            border.width: 2
            border.color: Theme.accent
            radius: 2
            TextEdit {
                id: input
                objectName: "readerEditorInput"
                anchors.fill: parent
                anchors.margins: 4
                color: root.color
                font.family: root.displayFamily(root.family)
                font.pixelSize: Math.max(6, root.size * root.s)
                font.bold: root.bold
                font.italic: root.italic
                font.underline: root.underline
                font.strikeout: root.strike
                horizontalAlignment: root.align === "center" ? TextEdit.AlignHCenter : (root.align === "right" ? TextEdit.AlignRight : TextEdit.AlignLeft)
                wrapMode: TextEdit.NoWrap
                selectByMouse: true
                selectionColor: Theme.accent
                selectedTextColor: Theme.textOnAccent
                textFormat: TextEdit.PlainText
                Accessible.role: Accessible.EditableText
                Accessible.name: root.kind === "note" ? "Notiz" : "Text"
                Keys.onShortcutOverride: (event) => {
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (root.kind === "object" || (event.modifiers & Qt.ControlModifier))) event.accepted = true
                    else if (event.key === Qt.Key_Escape) event.accepted = true
                }
                Keys.onPressed: (event) => {
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (root.kind === "object" || (event.modifiers & Qt.ControlModifier))) {
                        root.commit()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Escape) {
                        root.cancel()
                        event.accepted = true
                    }
                }
            }
        }
        PText {
            visible: root.kind === "object" && root.request !== null
            Layout.preferredWidth: Math.max(box.width, 320)
            wrap: true
            textStyle: "caption"
            readonly property var o: root.request && root.kind === "object" ? root.request.object : null
            tone: o && o.native ? "secondary" : "warning"
            text: !o ? "" : o.font + " · " + (Math.round(o.size * 10) / 10) + " pt · " + (o.native ? "Nur dieses Objekt wird geändert – direkt im PDF, wenn die Originalschrift alle Zeichen hat" : "Direkt nicht möglich: " + o.reason + ". Der Text wird überlagert – der Hinweis nennt danach den Weg.")
            Rectangle { anchors.fill: parent; anchors.margins: -4; z: -1; color: Theme.flyout; radius: Metrics.radiusControl; border.color: Theme.flyoutStroke }
        }
        PText {
            visible: root.kind === "block" && root.block !== null
            Layout.preferredWidth: Math.max(box.width, 320)
            wrap: true
            textStyle: "caption"
            tone: root.block && root.block.native ? "secondary" : "warning"
            text: !root.block ? "" : root.block.font + " · " + (Math.round(root.block.size * 10) / 10) + " pt · " + (root.block.native ? "Änderung direkt im PDF möglich (Originalschrift)" : "Direkt nicht möglich: " + root.block.reason + ". Der Text wird neu gesetzt oder überlagert – der Hinweis nennt danach den Weg.")
            Rectangle { anchors.fill: parent; anchors.margins: -4; z: -1; color: Theme.flyout; radius: Metrics.radiusControl; border.color: Theme.flyoutStroke }
        }
    }
}
