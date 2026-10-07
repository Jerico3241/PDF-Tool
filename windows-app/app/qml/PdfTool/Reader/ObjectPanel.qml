import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Eigenschaften der Auswahl im Modus »Objekt bearbeiten«: Text (Schrift, Fett/Kursiv, Größe, Zeichenabstand,
// Farbe), Bild (Größe, Ersetzen), Vektorobjekt (Linien- und Füllfarbe, Linienstärke) und für alle Deckkraft,
// Drehung, Position und Ebene; mehrere Objekte lassen sich ausrichten und verteilen. Angeboten wird nur, was
// sich zuverlässig ändern lässt. Positionen in Millimetern ab der linken oberen Ecke der Seite.
// Kopf (Titel, Schließen) und Breite kommen von der rechten Seitenleiste (RightPanel).
ColumnLayout {
    id: root
    objectName: "readerObjectPanel"
    property var doc: null
    readonly property var chosen: doc ? doc.objectSelection : []
    readonly property var first: chosen.length ? chosen[0] : null
    function isText(item) { return item !== null && item !== undefined && (item.kind === "text" || item.kind === "word") }
    readonly property bool texts: chosen.length > 0 && chosen.every(function(item) { return root.isText(item) })
    readonly property bool anyText: chosen.some(function(item) { return root.isText(item) })
    readonly property bool paths: chosen.length > 0 && chosen.every(function(item) { return item.kind === "path" })
    readonly property bool editable: texts && chosen.every(function(item) { return item.native })
    // Text lässt sich immer ändern (notfalls neu gesetzt bzw. überlagert); Bilder und Vektorobjekte nur sicher
    readonly property bool changeable: chosen.length > 0 && chosen.every(function(item) { return root.isText(item) || item.editable === true })
    readonly property bool image: chosen.length === 1 && chosen[0].kind === "image"
    // Genau ein Objekt – aus ``first`` abgeleitet, damit Prüfung und Wert in jeder Bindung zusammenpassen
    readonly property var one: first !== null && chosen.length === 1 ? first : null
    readonly property bool oneImage: one !== null && one.kind === "image"
    readonly property bool onePath: one !== null && one.kind === "path"
    readonly property real mm: 25.4 / 72
    // Art der Auswahl: wechselt sie (Text → Bild → mehrere), blendet der Inhalt kurz ein statt hart zu
    // wechseln; neue Werte derselben Art (anderes Wort, verschoben) erscheinen sofort
    readonly property string kind: chosen.length === 0 ? "" : (chosen.length > 1 ? "multi" : (image ? "image" : (onePath ? "path" : "text")))
    onKindChanged: if (kind !== "" && Motion.enabled) reveal.restart()
    spacing: 0

    // Schrift des (ersten) Textes: Familie und Stil aus dem Schriftnamen
    readonly property string fontName: first && texts ? String(first.font || "") : ""
    readonly property string family: /courier|mono|consol/i.test(fontName) ? "Courier" : (/times|serif|roman|georgia|garamond|cambria|book|palatino|minion/i.test(fontName) && !/sans/i.test(fontName) ? "Times" : "Helvetica")
    readonly property bool bold: /bold|black|heavy|semibold|demi/i.test(fontName)
    readonly property bool italic: /italic|oblique/i.test(fontName)
    // Deckkraft: Vektorobjekte nennen sie, sonst gilt 100 %
    readonly property real opacityShown: first && first.opacity !== undefined ? first.opacity : 1

    ParallelAnimation {
        id: reveal
        NumberAnimation { target: details; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
        NumberAnimation { target: detailsShift; property: "y"; from: Motion.paneShift; to: 0; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    function number(text) {
        var value = parseFloat(String(text).replace(",", "."))
        return isNaN(value) ? null : value
    }
    function shown(value, digits) {
        return Number(value).toLocaleString(Qt.locale("de_DE"), "f", digits === undefined ? 1 : digits)
    }

    // Nichts gewählt
    PEmptyState {
        objectName: "readerObjectPanelEmpty"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.chosen.length === 0
        iconName: "select_object"
        title: root.doc && root.doc.tool === "objects" ? "Kein Objekt ausgewählt" : "Eigenschaften einzelner Objekte"
        text: root.doc && root.doc.tool === "objects"
            ? "Text, Bild oder Grafik auf der Seite anklicken. Ein weiterer Klick wählt ein einzelnes Wort, Strg- oder Umschalt+Klick und ein Rahmen wählen mehrere Objekte."
            : "Im Werkzeug »Objekt bearbeiten« zeigt diese Leiste Schrift, Farbe, Größe und Position der Auswahl."
    }

    Flickable {
        id: details
        PWheelScroll { flickable: details }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
        objectName: "readerObjectDetails"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.chosen.length > 0
        transform: Translate { id: detailsShift }
        contentHeight: body.implicitHeight + 24
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}

        ColumnLayout {
            id: body
            x: 16
            y: 12
            width: parent.width - 32
            spacing: 10

            PText {
                objectName: "readerObjectKind"
                textStyle: "caption"
                tone: "secondary"
                text: root.chosen.length > 1 ? root.chosen.length + " Objekte ausgewählt" : (root.image ? "Bild" : (root.onePath ? "Grafik (Vektorobjekt)" : (root.first && root.first.kind === "word" ? "Wort" : "Text")))
            }
            PText {
                Layout.fillWidth: true
                visible: root.chosen.length === 1 && root.texts
                text: root.first && root.texts ? "»" + root.first.text + "«" : ""
                elide: Text.ElideRight
                textStyle: "bodyStrong"
            }

            // --- Text: Schrift und Stil (neu gesetzt) --------------------------------------------------------------
            PText { visible: root.texts; text: "Schrift"; tone: "secondary" }
            RowLayout {
                Layout.fillWidth: true
                visible: root.texts
                spacing: 4
                PComboBox {
                    objectName: "readerObjectFamily"
                    Layout.fillWidth: true
                    preferredWidth: 150
                    label: "Schriftart"
                    model: Reader.fontFamilies
                    textRole: "label"
                    valueRole: "value"
                    currentIndex: Math.max(0, indexOfValue(root.family))
                    onActivated: (index) => { if (Reader.fontFamilies[index].value !== root.family) root.doc.styleObjects("family", Reader.fontFamilies[index].value) }
                }
                PFormatButton {
                    objectName: "readerObjectBold"
                    iconName: "text_bold"
                    tip: "Fett"
                    active: root.bold
                    onClicked: root.doc.styleObjects("bold", !root.bold)
                }
                PFormatButton {
                    objectName: "readerObjectItalic"
                    iconName: "text_italic"
                    tip: "Kursiv"
                    active: root.italic
                    onClicked: root.doc.styleObjects("italic", !root.italic)
                }
            }
            PText {
                Layout.fillWidth: true
                visible: root.texts && root.chosen.length === 1
                wrap: true
                textStyle: "caption"
                tone: "secondary"
                text: root.fontName ? "Im PDF: " + root.fontName + (root.one && root.texts ? " · Drehung " + root.shown(root.one.angle || 0, 0) + "°" : "") : ""
            }

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 12
                rowSpacing: 8
                readonly property bool single: root.chosen.length === 1
                readonly property bool oneText: single && root.texts
                // --- Text: Größe, Zeichenabstand, Farbe -----------------------------------------------------------
                PText { visible: root.texts; text: "Größe (pt)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectSize"
                    visible: root.texts
                    label: "Größe (pt)"
                    preferredWidth: 90
                    enabled: root.editable
                    text: root.first && root.texts ? root.shown(root.first.size) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && value >= 1 && value <= 400) root.doc.styleObjects("size", value) }
                }
                PText { visible: parent.oneText; text: "Zeichenabstand (pt)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectSpacing"
                    visible: parent.oneText
                    label: "Zeichenabstand (pt)"
                    preferredWidth: 90
                    enabled: root.editable
                    text: root.one && root.texts ? root.shown(root.one.spacing || 0, 2) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && value > -5 && value < 50) root.doc.styleObjects("spacing", value) }
                }
                PText { visible: root.texts; text: "Farbe"; tone: "secondary" }
                PSwatch {
                    id: colorButton
                    objectName: "readerObjectColor"
                    visible: root.texts
                    size: 28
                    swatchColor: root.first && root.texts ? root.first.color : "#000000"
                    tip: root.editable ? "Farbe ändern" : "Die Farbe dieses Textes lässt sich nicht direkt ändern"
                    enabled: root.editable
                    onClicked: colors.open()
                    ColorChooser {
                        id: colors
                        y: colorButton.height + 4
                        current: root.first && root.texts ? root.first.color : ""
                        onPicked: (value) => { root.doc.styleObjects("color", value); colors.close() }
                    }
                }

                // --- Vektorobjekte: Linie und Füllung -------------------------------------------------------------
                PText { visible: root.paths; text: "Linienfarbe"; tone: "secondary" }
                PSwatch {
                    id: strokeButton
                    objectName: "readerObjectStroke"
                    visible: root.paths
                    size: 28
                    swatchColor: root.first && root.paths && root.first.stroke ? root.first.stroke : "transparent"
                    tip: root.first && root.paths && !root.first.stroke ? "Ohne Linie – Farbe wählen, um eine Linie zu zeichnen" : "Linienfarbe ändern"
                    enabled: root.changeable
                    onClicked: strokeColors.open()
                    ColorChooser {
                        id: strokeColors
                        y: strokeButton.height + 4
                        current: root.first && root.paths ? root.first.stroke : ""
                        onPicked: (value) => { root.doc.styleObjects("stroke", value); strokeColors.close() }
                    }
                }
                PText { visible: root.paths; text: "Füllfarbe"; tone: "secondary" }
                PSwatch {
                    id: fillButton
                    objectName: "readerObjectFill"
                    visible: root.paths
                    size: 28
                    swatchColor: root.first && root.paths && root.first.fill ? root.first.fill : "transparent"
                    tip: root.first && root.paths && !root.first.fill ? "Ohne Füllung – Farbe wählen, um zu füllen" : "Füllfarbe ändern"
                    enabled: root.changeable
                    onClicked: fillColors.open()
                    ColorChooser {
                        id: fillColors
                        y: fillButton.height + 4
                        current: root.first && root.paths ? root.first.fill : ""
                        onPicked: (value) => { root.doc.styleObjects("fill", value); fillColors.close() }
                    }
                }
                PText { visible: root.paths; text: "Linienstärke (pt)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectWidth"
                    visible: root.paths
                    label: "Linienstärke (pt)"
                    preferredWidth: 90
                    enabled: root.changeable
                    text: root.first && root.paths ? root.shown(root.first.width || 0, 2) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && value >= 0 && value <= 100) root.doc.styleObjects("width", value) }
                }

                // --- Alle: Deckkraft, Position, Größe, Drehung -----------------------------------------------------
                PText { text: "Deckkraft (%)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectOpacity"
                    label: "Deckkraft (%)"
                    preferredWidth: 90
                    enabled: root.changeable && (!root.texts || root.editable)
                    text: root.shown(Math.round(root.opacityShown * 100), 0)
                    onSubmitted: { var value = root.number(text); if (value !== null && value >= 0 && value <= 100) root.doc.styleObjects("opacity", value / 100) }
                }
                PText { visible: parent.single; text: "Links (mm)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectX"
                    visible: parent.single
                    label: "Links (mm)"
                    preferredWidth: 90
                    enabled: root.one !== null && (root.isText(root.one) ? root.editable : root.one.editable === true)
                    text: root.one ? root.shown(root.one.view[0] * root.mm) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && root.one) root.doc.moveObjects(value / root.mm - root.one.view[0], 0) }
                }
                PText { visible: parent.single; text: "Oben (mm)"; tone: "secondary" }
                PTextField {
                    objectName: "readerObjectY"
                    visible: parent.single
                    label: "Oben (mm)"
                    preferredWidth: 90
                    enabled: root.one !== null && (root.isText(root.one) ? root.editable : root.one.editable === true)
                    text: root.one ? root.shown(root.one.view[1] * root.mm) : ""
                    onSubmitted: { var value = root.number(text); if (value !== null && root.one) root.doc.moveObjects(0, value / root.mm - root.one.view[1]) }
                }
                PText { visible: root.image || root.onePath; text: "Größe"; tone: "secondary" }
                PText {
                    visible: root.image || root.onePath
                    Layout.fillWidth: true
                    wrap: true
                    text: root.one && !root.isText(root.one) ? root.shown((root.one.view[2] - root.one.view[0]) * root.mm) + " × " + root.shown((root.one.view[3] - root.one.view[1]) * root.mm) + " mm" + (root.oneImage && root.one.pixels && root.one.pixels[0] ? " · " + root.one.pixels[0] + " × " + root.one.pixels[1] + " Pixel" : "") : ""
                }
                PText { text: "Drehen um (°)"; tone: "secondary" }
                RowLayout {
                    spacing: 2
                    PTextField {
                        objectName: "readerObjectRotate"
                        label: "Drehen um (°, im Uhrzeigersinn)"
                        preferredWidth: 64
                        enabled: root.changeable
                        text: "0"
                        onSubmitted: { var value = root.number(text); if (value !== null && Math.abs(value) > 0.01 && Math.abs(value) <= 360) root.doc.rotateObjects(value); text = "0" }
                    }
                    PIconButton { objectName: "readerObjectRotateLeft"; iconName: "arrow_rotate_counterclockwise"; tip: "90° gegen den Uhrzeigersinn"; enabled: root.changeable; onClicked: root.doc.rotateObjects(-90) }
                    PIconButton { objectName: "readerObjectRotateRight"; iconName: "arrow_rotate_clockwise"; tip: "90° im Uhrzeigersinn"; enabled: root.changeable; onClicked: root.doc.rotateObjects(90) }
                }
            }

            // --- Mehrere: Ausrichten und Verteilen --------------------------------------------------------------
            PText { visible: root.chosen.length > 1; text: "Ausrichten und verteilen"; tone: "secondary" }
            Flow {
                Layout.fillWidth: true
                visible: root.chosen.length > 1
                spacing: 2
                PIconButton { objectName: "readerAlignLeft"; iconName: "align_left"; tip: "Links ausrichten"; enabled: root.changeable; onClicked: root.doc.alignObjects("left") }
                PIconButton { objectName: "readerAlignCenter"; iconName: "align_center_horizontal"; tip: "Horizontal zentrieren"; enabled: root.changeable; onClicked: root.doc.alignObjects("hcenter") }
                PIconButton { objectName: "readerAlignRight"; iconName: "align_right"; tip: "Rechts ausrichten"; enabled: root.changeable; onClicked: root.doc.alignObjects("right") }
                PIconButton { objectName: "readerAlignTop"; iconName: "align_top"; tip: "Oben ausrichten"; enabled: root.changeable; onClicked: root.doc.alignObjects("top") }
                PIconButton { objectName: "readerAlignMiddle"; iconName: "align_center_vertical"; tip: "Vertikal zentrieren"; enabled: root.changeable; onClicked: root.doc.alignObjects("vcenter") }
                PIconButton { objectName: "readerAlignBottom"; iconName: "align_bottom"; tip: "Unten ausrichten"; enabled: root.changeable; onClicked: root.doc.alignObjects("bottom") }
                PIconButton { objectName: "readerDistributeH"; iconName: "align_space_evenly_horizontal"; tip: "Waagerecht gleichmäßig verteilen (ab drei Objekten)"; enabled: root.changeable && root.chosen.length > 2; onClicked: root.doc.alignObjects("hspace") }
                PIconButton { objectName: "readerDistributeV"; iconName: "align_space_evenly_vertical"; tip: "Senkrecht gleichmäßig verteilen (ab drei Objekten)"; enabled: root.changeable && root.chosen.length > 2; onClicked: root.doc.alignObjects("vspace") }
            }

            // --- Ebene (Bilder, Vektorobjekte) -----------------------------------------------------------------
            PText { visible: !root.anyText; text: "Ebene"; tone: "secondary" }
            Flow {
                Layout.fillWidth: true
                visible: !root.anyText
                spacing: 6
                PButton { objectName: "readerObjectFront"; text: "Nach vorn"; iconName: "position_to_front"; enabled: root.changeable; onClicked: root.doc.arrangeObjects(true) }
                PButton { objectName: "readerObjectBack"; text: "Nach hinten"; iconName: "position_to_back"; enabled: root.changeable; onClicked: root.doc.arrangeObjects(false) }
            }

            // --- Aktionen --------------------------------------------------------------------------------------
            Flow {
                Layout.fillWidth: true
                spacing: 6
                PButton { objectName: "readerObjectDuplicate"; text: "Duplizieren"; iconName: "document_copy"; enabled: root.changeable; onClicked: root.doc.duplicateObject() }
                PButton { objectName: "readerObjectCopy"; text: "Kopieren"; iconName: "copy"; onClicked: root.doc.copyObjects() }
                PButton { visible: root.image; text: "Ersetzen …"; iconName: "image"; enabled: root.oneImage && root.one.editable === true; onClicked: root.doc.replaceImage(root.one.page, root.one.index) }
                PButton { objectName: "readerObjectDelete"; text: "Löschen"; iconName: "delete"; kind: "danger"; enabled: root.changeable; onClicked: root.doc.deleteObjects() }
            }

            // Wie geändert wird – ehrlich benannt
            PText {
                Layout.fillWidth: true
                wrap: true
                textStyle: "caption"
                tone: (root.texts && !root.editable) || !root.changeable ? "warning" : "secondary"
                text: {
                    if (!root.changeable)
                        return "Nicht sicher änderbar: " + ((root.chosen.find(function(item) { return !root.isText(item) && item.editable !== true }) || {}).reason || "Dieses Objekt lässt sich hier nicht bearbeiten.")
                    if (root.texts && !root.editable)
                        return "Nicht direkt änderbar: " + (root.chosen.find(function(item) { return !item.native }) || {}).reason + " Text ändern und Löschen sind nur als Überlagerung möglich (der Originaltext bleibt in der Datei)."
                    if (root.anyText)
                        return "Änderungen betreffen nur die Auswahl und erfolgen direkt im PDF. Schrift, Fett und Kursiv setzen den Text neu; fehlen der Originalschrift Zeichen, ebenso."
                    return "Änderungen betreffen nur die Auswahl und erfolgen direkt im PDF; jede Änderung wird vor dem Übernehmen geprüft."
                }
            }
        }
    }
}
