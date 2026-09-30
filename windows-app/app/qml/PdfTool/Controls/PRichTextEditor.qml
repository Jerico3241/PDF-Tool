import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Style

// Kopf-/Fußzeilen-Editor: Formatleiste (Schrift, Größe, Fett, Kursiv, Unterstrichen,
// Durchgestrichen, Farbe, Ausrichtung) und ein Textfeld auf weißem »Papier« wie in der PDF.
// Die Formatierung verwaltet ``document`` (Python, ``RichTextDocument``); Rückgängig und
// Wiederholen (Strg+Z / Strg+Y) gelten für Text und Formatierung.
ColumnLayout {
    id: editor
    property QtObject document: null
    property int lines: 4
    property int maxLines: 14
    property string label: ""
    spacing: 8

    function refocus() { area.forceActiveFocus() }
    function pastePlain() { editor.document.pastePlain(area.selectionStart, area.selectionEnd) }

    Flow {
        Layout.fillWidth: true
        spacing: 6
        PComboBox {
            id: fontCombo
            preferredWidth: 160
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
            preferredWidth: 76
            label: "Schriftgröße"
            tip: "Schriftgröße (pt)"
            placeholder: "Größe"
            model: editor.document ? editor.document.sizes : []
            currentIndex: editor.document ? editor.document.sizes.indexOf(editor.document.fontSize) : -1
            displayText: editor.document ? editor.document.fontSize : ""
            onActivated: (index) => { editor.document.setFontSize(editor.document.sizes[index]); editor.refocus() }
        }
        Row {
            spacing: 2
            PFormatButton { glyph: "B"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, weight: Font.Bold }); tip: "Fett (Strg+B)"; active: editor.document ? editor.document.bold : false; onClicked: { editor.document.toggle("bold"); editor.refocus() } }
            PFormatButton { glyph: "I"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, italic: true }); tip: "Kursiv (Strg+I)"; active: editor.document ? editor.document.italic : false; onClicked: { editor.document.toggle("italic"); editor.refocus() } }
            PFormatButton { glyph: "U"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, underline: true }); tip: "Unterstrichen (Strg+U)"; active: editor.document ? editor.document.underline : false; onClicked: { editor.document.toggle("underline"); editor.refocus() } }
            PFormatButton { glyph: "S"; glyphFont: Qt.font({ family: Typography.family, pixelSize: 15, strikeout: true }); tip: "Durchgestrichen"; active: editor.document ? editor.document.strike : false; onClicked: { editor.document.toggle("strike"); editor.refocus() } }
        }
        T.AbstractButton {
            id: colorButton
            implicitWidth: 40
            implicitHeight: 32
            hoverEnabled: true
            focusPolicy: Qt.TabFocus
            Accessible.role: Accessible.Button
            Accessible.name: "Schriftfarbe"
            background: Rectangle {
                radius: Metrics.radiusControl
                color: colorButton.pressed ? Theme.subtlePressed : (colorButton.hovered || flyout.visible ? Theme.subtleHover : "transparent")
                PFocusRing { visible: colorButton.visualFocus }
            }
            contentItem: Item {
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 4
                    text: "A"
                    font: Qt.font({ family: Typography.family, pixelSize: 15, weight: Font.DemiBold })
                    color: Theme.textPrimary
                }
                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 23
                    width: 20
                    height: 4
                    radius: 1
                    color: editor.document && editor.document.color !== "" ? editor.document.color : "transparent"
                    border.width: editor.document && editor.document.color !== "" ? 0 : 1
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
        Row {
            spacing: 2
            PFormatButton { iconName: "text_align_left"; tip: "Linksbündig (Strg+L)"; active: editor.document ? editor.document.alignment === "left" : false; onClicked: { editor.document.setAlignment("left"); editor.refocus() } }
            PFormatButton { iconName: "text_align_center"; tip: "Zentriert (Strg+E)"; active: editor.document ? editor.document.alignment === "center" : false; onClicked: { editor.document.setAlignment("center"); editor.refocus() } }
            PFormatButton { iconName: "text_align_right"; tip: "Rechtsbündig (Strg+R)"; active: editor.document ? editor.document.alignment === "right" : false; onClicked: { editor.document.setAlignment("right"); editor.refocus() } }
        }
        Row {
            spacing: 2
            PFormatButton { iconName: "arrow_undo"; tip: "Rückgängig (Strg+Z)"; enabled: area.canUndo; opacity: enabled ? 1 : 0.4; onClicked: { area.undo(); editor.refocus() } }
            PFormatButton { iconName: "arrow_redo"; tip: "Wiederholen (Strg+Y)"; enabled: area.canRedo; opacity: enabled ? 1 : 0.4; onClicked: { area.redo(); editor.refocus() } }
        }
    }

    // Papier
    Rectangle {
        id: paper
        Layout.fillWidth: true
        readonly property real lineHeight: 20
        implicitHeight: Math.min(editor.maxLines * lineHeight, Math.max(editor.lines * lineHeight, area.implicitHeight)) + 2
        radius: Metrics.radiusControl
        color: Theme.paper
        border.width: 1
        border.color: Theme.dark ? Theme.controlStroke : Theme.controlStroke
        Behavior on implicitHeight { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } }

        Flickable {
            id: flick
            anchors.fill: parent
            anchors.margins: 1
            contentWidth: width
            contentHeight: area.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            T.ScrollBar.vertical: PScrollBar {}
            function ensureVisible(rect) {
                if (contentY >= rect.y) contentY = rect.y
                else if (contentY + height <= rect.y + rect.height) contentY = rect.y + rect.height - height
            }
            T.TextArea {
                id: area
                width: flick.width
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
                    if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (event.modifiers & Qt.ShiftModifier)) {
                        // weicher Umbruch wäre kein Absatz der PDF – immer ein neuer Absatz
                        area.remove(area.selectionStart, area.selectionEnd)
                        area.insert(area.cursorPosition, "\n")
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
                TapHandler {
                    acceptedButtons: Qt.RightButton
                    onTapped: (point) => { area.forceActiveFocus(); menu.popup(area, point.position.x, point.position.y) }
                }
                PTextMenu { id: menu; target: area; pasteHandler: editor.pastePlain }
            }
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 1
            anchors.rightMargin: 1
            height: area.activeFocus ? 2 : 1
            color: area.activeFocus ? Theme.accent : "#868686"
        }
    }
}
