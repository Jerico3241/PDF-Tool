import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Kopf-/Fußzeilen-Editor: Formatleiste (Schrift, Größe, Fett, Kursiv, Unterstrichen,
// Durchgestrichen, Farbe, Ausrichtung, Rückgängig/Wiederholen) und ein Textfeld auf weißem
// »Papier« wie in der PDF. Der Inhalt samt Formatierung gehört dem Python-Modell ``document``
// (``RichTextDocument``): Es liest jede Änderung sofort aus dem ``QTextDocument`` des Textfelds
// zurück. Rückgängig und Wiederholen (Strg+Z / Strg+Y) gelten für Text und Formatierung.
ColumnLayout {
    id: editor
    property QtObject document: null
    property int lines: 4
    property int maxLines: 14
    property string label: ""
    property string placeholderText: ""
    readonly property alias textArea: area
    spacing: 8

    function refocus() { area.forceActiveFocus() }
    function pastePlain() { editor.document.pastePlain(area.selectionStart, area.selectionEnd) }

    component Separator: Item {
        implicitWidth: 9
        implicitHeight: Metrics.controlHeight
        Rectangle { anchors.centerIn: parent; width: 1; height: 20; color: Theme.divider }
    }

    // Formatleiste: Gruppen mit Trennlinie, alle Elemente 32 px hoch und mittig ausgerichtet
    Flow {
        id: toolbar
        Layout.fillWidth: true
        spacing: 4
        PComboBox {
            id: fontCombo
            preferredWidth: 156
            label: "Schriftart"
            tip: "Schriftart"
            placeholder: "Schriftart"
            model: editor.document ? editor.document.families : []
            currentIndex: editor.document ? editor.document.families.indexOf(editor.document.fontFamily) : -1
            displayText: editor.document && editor.document.fontFamily !== "" ? editor.document.fontFamily : ""
            onActivated: (index) => { editor.document.setFontFamily(editor.document.families[index]); editor.refocus() }
        }
        PComboBox {
            id: sizeCombo
            preferredWidth: 72
            label: "Schriftgröße"
            tip: "Schriftgröße (pt)"
            placeholder: "Größe"
            model: editor.document ? editor.document.sizes : []
            currentIndex: editor.document ? editor.document.sizes.indexOf(editor.document.fontSize) : -1
            displayText: editor.document ? editor.document.fontSize : ""
            onActivated: (index) => { editor.document.setFontSize(editor.document.sizes[index]); editor.refocus() }
        }
        Separator {}
        Row {
            spacing: 2
            PFormatButton { glyph: "B"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, weight: Font.Bold }); tip: "Fett (Strg+B)"; active: editor.document ? editor.document.bold : false; mixed: editor.document ? editor.document.mixed.indexOf("bold") >= 0 : false; onClicked: { editor.document.toggle("bold"); editor.refocus() } }
            PFormatButton { glyph: "I"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, italic: true }); tip: "Kursiv (Strg+I)"; active: editor.document ? editor.document.italic : false; mixed: editor.document ? editor.document.mixed.indexOf("italic") >= 0 : false; onClicked: { editor.document.toggle("italic"); editor.refocus() } }
            PFormatButton { glyph: "U"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, underline: true }); tip: "Unterstrichen (Strg+U)"; active: editor.document ? editor.document.underline : false; mixed: editor.document ? editor.document.mixed.indexOf("underline") >= 0 : false; onClicked: { editor.document.toggle("underline"); editor.refocus() } }
            PFormatButton { glyph: "S"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, strikeout: true }); tip: "Durchgestrichen"; active: editor.document ? editor.document.strike : false; mixed: editor.document ? editor.document.mixed.indexOf("strike") >= 0 : false; onClicked: { editor.document.toggle("strike"); editor.refocus() } }
        }
        T.AbstractButton {
            id: colorButton
            objectName: "colorButton"
            implicitWidth: 40
            implicitHeight: Metrics.controlHeight
            hoverEnabled: true
            focusPolicy: Qt.TabFocus
            Accessible.role: Accessible.Button
            Accessible.name: "Schriftfarbe"
            background: Rectangle {
                radius: Metrics.radiusControl
                color: colorButton.pressed ? Theme.subtlePressed : (colorButton.hovered || flyout.visible ? Theme.subtleHover : "transparent")
                Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                PFocusRing { visible: colorButton.visualFocus }
            }
            contentItem: Item {
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 5
                    text: "A"
                    font: Qt.font({ family: Typography.family, pixelSize: 15, weight: Font.DemiBold })
                    color: Theme.textPrimary
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 23
                    width: 18
                    height: 4
                    radius: 1
                    readonly property bool known: editor.document !== null && editor.document.color !== ""
                    color: known ? editor.document.color : "transparent"
                    // ohne einheitliche Farbe nur Umriss; im dunklen Design immer mit Umriss (dunkle Textfarben)
                    border.width: !known || Theme.dark ? 1 : 0
                    border.color: Theme.strongStroke
                }
            }
            onClicked: flyout.visible ? flyout.close() : flyout.open()
            PToolTip { text: "Schriftfarbe"; visible: colorButton.hovered && !flyout.visible }
            PColorFlyout {
                id: flyout
                y: colorButton.height + 4
                document: editor.document
                onPicked: (color) => { editor.document.setColor(color); editor.refocus() }
            }
        }
        Separator {}
        Row {
            spacing: 2
            PFormatButton { iconName: "text_align_left"; tip: "Linksbündig (Strg+L)"; active: editor.document ? editor.document.alignment === "left" : false; onClicked: { editor.document.setAlignment("left"); editor.refocus() } }
            PFormatButton { iconName: "text_align_center"; tip: "Zentriert (Strg+E)"; active: editor.document ? editor.document.alignment === "center" : false; onClicked: { editor.document.setAlignment("center"); editor.refocus() } }
            PFormatButton { iconName: "text_align_right"; tip: "Rechtsbündig (Strg+R)"; active: editor.document ? editor.document.alignment === "right" : false; onClicked: { editor.document.setAlignment("right"); editor.refocus() } }
        }
        Separator {}
        Row {
            spacing: 2
            PFormatButton { iconName: "arrow_undo"; tip: "Rückgängig (Strg+Z)"; enabled: area.canUndo; opacity: enabled ? 1 : 0.4; onClicked: { area.undo(); editor.refocus() } }
            PFormatButton { iconName: "arrow_redo"; tip: "Wiederholen (Strg+Y)"; enabled: area.canRedo; opacity: enabled ? 1 : 0.4; onClicked: { area.redo(); editor.refocus() } }
        }
    }

    // Papier: wächst mit dem Inhalt (mindestens ``lines``, höchstens ``maxLines`` Zeilen), darüber
    // hinaus scrollt das Textfeld.
    Rectangle {
        id: paper
        Layout.fillWidth: true
        readonly property real lineHeight: 20
        implicitHeight: Math.min(editor.maxLines * lineHeight, Math.max(editor.lines * lineHeight, area.implicitHeight)) + 2
        radius: Metrics.radiusControl
        color: Theme.paper
        border.width: 1
        border.color: paperHover.hovered && !area.activeFocus ? Theme.inputEdge : Theme.controlStroke
        Behavior on implicitHeight { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }
        Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        HoverHandler { id: paperHover; cursorShape: Qt.IBeamCursor }

        Flickable {
            id: flick
            anchors.fill: parent
            anchors.margins: 1
            contentWidth: width
            contentHeight: area.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: area.implicitHeight > height
            T.ScrollBar.vertical: PScrollBar {}
            function ensureVisible(rect) {
                if (contentY >= rect.y) contentY = rect.y
                else if (contentY + height <= rect.y + rect.height) contentY = rect.y + rect.height - height
            }
            T.TextArea {
                id: area
                width: flick.width
                // Die Vorlage »T.TextArea« leitet ihre Größe nicht aus dem Inhalt ab (das übernimmt
                // sonst ein Stil). Ohne diese Angaben bliebe das Feld eine Zeile hoch: Qt zeichnet
                // nur, was im Feld liegt, und Klicks darunter erreichen es nicht. Das Feld füllt das
                // ganze Papier – ein Klick in den freien Bereich setzt den Cursor ans Textende.
                implicitWidth: contentWidth + leftPadding + rightPadding
                implicitHeight: contentHeight + topPadding + bottomPadding
                height: Math.max(implicitHeight, flick.height)
                leftPadding: 12
                rightPadding: 12
                topPadding: 8
                bottomPadding: 8
                textFormat: TextEdit.RichText
                wrapMode: TextEdit.Wrap
                color: Theme.paperText
                selectionColor: "#3390FF"
                selectedTextColor: "#FFFFFF"
                selectByMouse: true
                persistentSelection: true
                Accessible.role: Accessible.EditableText
                Accessible.name: editor.label
                Component.onCompleted: if (editor.document) editor.document.attach(area.textDocument)
                Component.onDestruction: if (editor.document) editor.document.detach()
                onCursorPositionChanged: if (editor.document) editor.document.setCursor(cursorPosition, selectionStart, selectionEnd)
                onSelectionStartChanged: if (editor.document) editor.document.setCursor(cursorPosition, selectionStart, selectionEnd)
                onSelectionEndChanged: if (editor.document) editor.document.setCursor(cursorPosition, selectionStart, selectionEnd)
                onCursorRectangleChanged: flick.ensureVisible(cursorRectangle)
                Keys.onPressed: (event) => {
                    if (event.matches(StandardKey.Paste)) { editor.pastePlain(); event.accepted = true; return }
                    if (event.key === Qt.Key_Tab) { area.nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason); event.accepted = true; return }
                    if (event.key === Qt.Key_Backtab) { area.nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason); event.accepted = true; return }
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ShiftModifier) && !(event.modifiers & Qt.ControlModifier)) {
                        // weicher Umbruch wäre kein Absatz der PDF – immer ein neuer Absatz
                        editor.document.newParagraph(area.selectionStart, area.selectionEnd)
                        event.accepted = true
                        return
                    }
                    if (!(event.modifiers & Qt.ControlModifier) || (event.modifiers & Qt.AltModifier)) return
                    var actions = { [Qt.Key_B]: "bold", [Qt.Key_I]: "italic", [Qt.Key_U]: "underline" }
                    if (actions[event.key] !== undefined) { editor.document.toggle(actions[event.key]); event.accepted = true; return }
                    if (event.key === Qt.Key_L) { editor.document.setAlignment("left"); event.accepted = true; return }
                    if (event.key === Qt.Key_E) { editor.document.setAlignment("center"); event.accepted = true; return }
                    if (event.key === Qt.Key_R) { editor.document.setAlignment("right"); event.accepted = true; return }
                }
                Text {
                    x: area.leftPadding
                    y: area.topPadding
                    width: area.width - area.leftPadding - area.rightPadding
                    text: editor.placeholderText
                    font: Typography.body
                    color: Theme.paperPlaceholder
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                    visible: text !== "" && area.length === 0 && !area.preeditText
                    Accessible.ignored: true
                }
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: (point) => { area.forceActiveFocus(); menu.popup(area, point.position.x, point.position.y) }
                }
                PTextMenu { id: menu; target: area; pasteHandler: editor.pastePlain }
            }
        }
        // Unterkante wie bei Eingabefeldern: im Fokus in Akzentfarbe (2 px)
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            height: area.activeFocus ? 2 : 1
            radius: 1
            color: area.activeFocus ? Theme.accent : Theme.inputEdge
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        }
    }
}
