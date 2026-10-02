import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Ein Formularfeld (Widget) über der Seite (Werkzeug »Formular ausfüllen«): Textfelder zum Tippen,
// Kontrollkästchen und Optionsfelder zum Anklicken, Auswahlfelder als Menü. Das Erscheinungsbild
// im PDF erzeugt Python neu – der Wert sieht danach in jedem Programm gleich aus. Felder, die sich
// nicht ausfüllen lassen (schreibgeschützt, Signatur, Schaltfläche), nennen den Grund im Tooltip.
Item {
    id: root
    property var field: ({})
    property var doc: null
    property var host: null         // Ansicht (DocumentView): bekommt die Tastatur nach der Eingabe zurück
    property real s: 1
    readonly property var r: field.view || [0, 0, 0, 0]
    readonly property string kind: field.kind || ""
    readonly property bool editable: field.editable === true
    readonly property bool textKind: kind === "text"
    readonly property bool checked: kind === "checkbox" ? field.value === true : (kind === "radio" ? field.value !== "" && field.value === field.onValue : false)
    property bool editing: false

    x: r[0] * s
    y: r[1] * s
    width: Math.max(4, (r[2] - r[0]) * s)
    height: Math.max(4, (r[3] - r[1]) * s)
    objectName: "readerField_" + (field.name || "")
    Accessible.role: kind === "checkbox" ? Accessible.CheckBox : (kind === "radio" ? Accessible.RadioButton : (kind === "combo" || kind === "list" ? Accessible.ComboBox : Accessible.EditableText))
    Accessible.name: field.name || ""
    Accessible.checked: checked

    function commit() {
        if (!editing) return
        editing = false
        var value = input.text
        if (value !== String(field.value) && doc) doc.setField(field.key, value)
    }
    // Eingabe mit der Tastatur beendet (Eingabetaste, Escape): Tastatur wieder in der Seite wie nach dem
    // Textbearbeiten – sonst bliebe sie im ausgeblendeten Eingabefeld und die Fokusmarkierung stehen
    function leave() {
        if (host) host.focusByPointer()
    }
    function choose() {
        if (!editable || !doc) return
        if (kind === "checkbox") doc.setField(field.key, !(field.value === true))
        else if (kind === "radio" && !checked) doc.setField(field.key, field.onValue)
        else if (kind === "combo" || kind === "list") options.popup(root, 0, root.height)
        else if (textKind) {
            input.text = String(field.value)
            editing = true
            input.forceActiveFocus(Qt.MouseFocusReason)
            input.selectAll()
        }
    }

    HoverHandler { id: hover; cursorShape: root.editable ? (root.textKind ? Qt.IBeamCursor : Qt.PointingHandCursor) : Qt.ForbiddenCursor }
    TapHandler { enabled: !root.editing; onTapped: root.choose() }

    Rectangle {
        anchors.fill: parent
        color: root.editing ? Theme.paper : Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, hover.hovered ? 0.14 : 0.06)
        border.width: 1
        border.color: root.editable ? Theme.accent : Theme.warning
        radius: root.kind === "radio" ? Math.min(width, height) / 2 : 2
        // Fokus: der kräftigere Rahmen blendet kurz ein (kein Glühen). Fläche und Eingabe wechseln sofort –
        // sonst schiene der Wert aus dem PDF kurz unter der Eingabe durch.
        Rectangle {
            objectName: "readerFieldFocus"
            anchors.fill: parent
            radius: parent.radius
            color: "transparent"
            border.width: 2
            border.color: parent.border.color
            opacity: root.editing || input.activeFocus ? 1 : 0
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast; easing.type: Motion.decelerate } }
        }
    }
    // Eingabe (nur Textfelder; sichtbar während der Eingabe – sonst zeigt das PDF den Wert)
    TextEdit {
        id: input
        anchors.fill: parent
        anchors.margins: 2
        visible: root.editing
        enabled: root.textKind && root.editable
        color: Theme.paperText
        font.family: Typography.family
        font.pixelSize: Math.max(8, Math.min(root.field.multiline ? 11 * root.s : root.height * 0.62, 48))
        wrapMode: root.field.multiline ? TextEdit.Wrap : TextEdit.NoWrap
        verticalAlignment: root.field.multiline ? TextEdit.AlignTop : TextEdit.AlignVCenter
        selectByMouse: true
        selectionColor: Theme.accent
        selectedTextColor: Theme.textOnAccent
        clip: true
        textFormat: TextEdit.PlainText
        Accessible.name: root.field.name || ""
        onActiveFocusChanged: if (!activeFocus) root.commit()
        onTextChanged: if (root.field.maxLength > 0 && length > root.field.maxLength) remove(root.field.maxLength, length)
        Keys.onPressed: (event) => {
            if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && (!root.field.multiline || (event.modifiers & Qt.ControlModifier))) {
                root.commit()
                root.leave()
                event.accepted = true
            } else if (event.key === Qt.Key_Escape) {
                root.editing = false
                root.leave()
                event.accepted = true
            }
        }
        Keys.onShortcutOverride: (event) => { if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Escape) event.accepted = true }
    }
    PMenu { id: options }
    Instantiator {
        model: root.kind === "combo" || root.kind === "list" ? root.field.options : []
        delegate: PMenuItem {
            required property var modelData
            text: modelData.label || modelData.value
            iconName: modelData.value === String(root.field.value) ? "checkmark" : ""
            onTriggered: if (root.doc) root.doc.setField(root.field.key, modelData.value)
        }
        onObjectAdded: (index, object) => options.insertItem(index, object)
        onObjectRemoved: (index, object) => options.removeItem(object)
    }
    PToolTip {
        text: root.editable ? (root.field.name || "") + (root.field.required ? " (Pflichtfeld)" : "") : (root.field.reason || "")
        visible: hover.hovered && text !== "" && !root.editing
    }
}
