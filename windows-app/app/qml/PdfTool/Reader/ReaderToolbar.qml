import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Befehlsleiste des Readers: Datei (Öffnen, Speichern, Drucken), Rückgängig/Wiederholen, Werkzeuge
// (Auswählen, Text bearbeiten, Objekt bearbeiten, Text hinzufügen, Bilder, Kommentieren, Zeichnen, Formular),
// rechts Ansicht, Seiten organisieren und »Mehr«. Bei schmalem Fenster wandern die rechten Einträge in
// »Mehr«. Die Umschalter der Seitenleisten (Seiten, Lesezeichen, Suchen; Kommentare, Eigenschaften)
// sitzen nicht hier, sondern in den Randleisten bei ihrer Seitenleiste.
Rectangle {
    id: root
    objectName: "readerToolbar"
    property var doc: null
    readonly property string tool: doc ? doc.tool : "select"
    readonly property bool roomy: width >= 760
    readonly property var commentTools: ["highlight", "underline", "strikeout", "note", "textbox"]
    readonly property var drawTools: ["ink", "rect", "ellipse", "line", "arrow"]
    property string lastComment: "highlight"
    property string lastDraw: "ink"
    onToolChanged: {
        if (commentTools.indexOf(tool) >= 0) lastComment = tool
        if (drawTools.indexOf(tool) >= 0) lastDraw = tool
    }

    function toolIcon(name) {
        switch (name) {
        case "highlight": return "highlight"
        case "underline": return "text_underline"
        case "strikeout": return "text_strikethrough"
        case "note": return "comment"
        case "textbox": return "textbox"
        case "ink": return "pen"
        case "rect": return "square"
        case "ellipse": return "circle"
        case "line": return "line"
        case "arrow": return "arrow_up_right"
        default: return "cursor"
        }
    }
    function toolName(name) {
        switch (name) {
        case "highlight": return "Markieren"
        case "underline": return "Unterstreichen"
        case "strikeout": return "Durchstreichen"
        case "note": return "Notiz"
        case "textbox": return "Textfeld"
        case "ink": return "Freihand"
        case "rect": return "Rechteck"
        case "ellipse": return "Ellipse"
        case "line": return "Linie"
        case "arrow": return "Pfeil"
        default: return name
        }
    }

    implicitHeight: Metrics.readerToolbarHeight
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

    component Separator: Rectangle {
        Layout.preferredWidth: 1
        Layout.preferredHeight: 20
        Layout.leftMargin: 4
        Layout.rightMargin: 4
        color: Theme.divider
    }
    // Gewähltes Werkzeug: Akzentmarkierung am unteren Rand, gleitet zum neu gewählten Werkzeug
    property Item activeTool: null
    component ToolButton: PIconButton {
        id: toolButton
        property string toolKey: ""
        checkable: true
        checked: root.tool === toolKey
        onCheckedChanged: if (checked) root.activeTool = toolButton
        Component.onCompleted: if (checked) root.activeTool = toolButton
        onClicked: if (root.doc) root.doc.setTool(toolKey)
        Accessible.role: Accessible.RadioButton
        Accessible.checked: checked
    }

    RowLayout {
        id: bar
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        spacing: 2

        PIconButton { objectName: "readerOpen"; iconName: "folder_open"; tip: "Öffnen (Strg+O)"; onClicked: Reader.openDialog() }
        PIconButton {
            objectName: "readerSave"
            iconName: "save"
            tip: "Speichern (Strg+S)"
            enabled: root.doc !== null && !root.doc.busy && (root.doc.dirty || root.doc.path === "")
            busy: root.doc !== null && root.doc.saving
            onClicked: root.doc.saveDocument()
        }
        // »Speichern …« → »Gespeichert« (kurz), ohne Dialog; feste Breite: die Leiste springt nicht
        PCrossfadeText {
            objectName: "readerSaveState"
            Layout.preferredWidth: saveStateWidth.advanceWidth + 4
            Layout.fillHeight: true
            font: Typography.caption
            color: Theme.textSecondary
            text: root.doc === null ? "" : (root.doc.saveState === "saving" ? "Speichern …" : (root.doc.saveState === "saved" ? "Gespeichert" : ""))
            TextMetrics { id: saveStateWidth; font: Typography.caption; text: "Speichern …" }
        }
        PIconButton { objectName: "readerPrint"; iconName: "print"; tip: "Drucken (Strg+P)"; enabled: root.doc !== null; onClicked: root.doc.printDocument() }
        Separator {}
        PIconButton {
            objectName: "readerUndo"
            iconName: "arrow_undo"
            tip: root.doc && root.doc.undoText ? "Rückgängig: " + root.doc.undoText + " (Strg+Z)" : "Rückgängig (Strg+Z)"
            enabled: root.doc !== null && root.doc.undoText !== "" && !root.doc.busy
            onClicked: root.doc.undo()
        }
        PIconButton {
            objectName: "readerRedo"
            iconName: "arrow_redo"
            tip: root.doc && root.doc.redoText ? "Wiederholen: " + root.doc.redoText + " (Strg+Y)" : "Wiederholen (Strg+Y)"
            enabled: root.doc !== null && root.doc.redoText !== "" && !root.doc.busy
            onClicked: root.doc.redo()
        }
        Separator {}
        ToolButton { objectName: "readerToolSelect"; toolKey: "select"; iconName: "cursor"; tip: "Auswählen: Text markieren und kopieren, Kommentare verschieben" }
        ToolButton { objectName: "readerToolEditText"; toolKey: "editText"; iconName: "text_edit_style"; tip: "Text bearbeiten: Absätze mit Cursor ändern, ergänzen, umbrechen" }
        ToolButton { objectName: "readerToolObjects"; toolKey: "objects"; iconName: "select_object"; tip: "Objekt bearbeiten: Text und andere PDF-Inhalte einzeln auswählen und bearbeiten." }
        ToolButton { objectName: "readerToolAddText"; toolKey: "addText"; iconName: "text_add"; tip: "Text hinzufügen" }
        ToolButton { objectName: "readerToolImage"; toolKey: "image"; iconName: "image"; tip: "Bilder: auswählen, verschieben, Größe ändern, einfügen" }
        // Kommentieren und Zeichnen: zuletzt benutztes Werkzeug + Auswahl
        Row {
            spacing: 0
            ToolButton { id: commentButton; objectName: "readerToolComment"; toolKey: root.lastComment; iconName: root.toolIcon(root.lastComment); tip: "Kommentieren: " + root.toolName(root.lastComment) }
            PIconButton { implicitWidth: 18; iconName: "chevron_down"; tip: "Kommentarwerkzeug wählen"; onClicked: commentMenu.popup(commentButton, 0, commentButton.height) }
        }
        Row {
            spacing: 0
            ToolButton { id: drawButton; objectName: "readerToolDraw"; toolKey: root.lastDraw; iconName: root.toolIcon(root.lastDraw); tip: "Zeichnen: " + root.toolName(root.lastDraw) }
            PIconButton { implicitWidth: 18; iconName: "chevron_down"; tip: "Zeichenwerkzeug wählen"; onClicked: drawMenu.popup(drawButton, 0, drawButton.height) }
        }
        ToolButton { objectName: "readerToolForm"; toolKey: "form"; iconName: "form"; tip: "Formular ausfüllen" }

        Item { Layout.fillWidth: true }

        PIconButton {
            id: viewButton
            objectName: "readerViewMode"
            visible: root.roomy
            iconName: root.doc && root.doc.viewMode === "single" ? "document_one_page" : (root.doc && root.doc.viewMode === "two" ? "book_open" : (root.doc && root.doc.viewMode === "continuousTwo" ? "layout_column_two" : "document_one_page_multiple"))
            tip: "Seitenansicht"
            onClicked: viewMenu.popup(viewButton, 0, viewButton.height)
        }
        PIconButton {
            objectName: "readerOrganize"
            visible: root.roomy
            iconName: "grid"
            tip: "Seiten organisieren"
            checkable: true
            checked: Reader.organize
            onClicked: Reader.setOrganize(!Reader.organize)
        }
        PIconButton { id: moreButton; objectName: "readerMore"; iconName: "more_horizontal"; tip: "Weitere Befehle"; onClicked: moreMenu.popup(moreButton, 0, moreButton.height) }
    }
    Rectangle {
        id: toolIndicator
        objectName: "readerToolIndicator"
        readonly property Item target: root.activeTool !== null && root.activeTool.visible && root.activeTool.checked ? root.activeTool : null
        width: 16
        height: 3
        radius: 1.5
        color: Theme.accent
        // Lage aus der Schaltfläche (auch in verschachtelten Zeilen); hängt an Breite und Anordnung der Leiste
        x: target ? (target.x, target.parent.x, bar.x, root.width, target.mapToItem(root, target.width / 2, 0).x - width / 2) : x
        y: target ? (target.y, target.parent.y, target.mapToItem(root, 0, target.height).y - height - 2) : y
        opacity: target ? 1 : 0
        Behavior on x { enabled: Motion.moves && toolIndicator.opacity > 0.5; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
    }

    PMenu {
        id: commentMenu
        PMenuItem { text: "Markieren"; iconName: "highlight"; onTriggered: root.doc.setTool("highlight") }
        PMenuItem { text: "Unterstreichen"; iconName: "text_underline"; onTriggered: root.doc.setTool("underline") }
        PMenuItem { text: "Durchstreichen"; iconName: "text_strikethrough"; onTriggered: root.doc.setTool("strikeout") }
        PMenuItem { text: "Notiz"; iconName: "comment"; onTriggered: root.doc.setTool("note") }
        PMenuItem { text: "Textfeld"; iconName: "textbox"; onTriggered: root.doc.setTool("textbox") }
    }
    PMenu {
        id: drawMenu
        PMenuItem { text: "Freihand (auch für eine sichtbare Unterschrift)"; iconName: "pen"; onTriggered: root.doc.setTool("ink") }
        PMenuItem { text: "Rechteck"; iconName: "square"; onTriggered: root.doc.setTool("rect") }
        PMenuItem { text: "Ellipse"; iconName: "circle"; onTriggered: root.doc.setTool("ellipse") }
        PMenuItem { text: "Linie"; iconName: "line"; onTriggered: root.doc.setTool("line") }
        PMenuItem { text: "Pfeil"; iconName: "arrow_up_right"; onTriggered: root.doc.setTool("arrow") }
    }
    PMenu {
        id: viewMenu
        PMenuItem { text: "Einzelseite"; iconName: "document_one_page"; onTriggered: root.doc.setViewMode("single") }
        PMenuItem { text: "Fortlaufend"; iconName: "document_one_page_multiple"; onTriggered: root.doc.setViewMode("continuous") }
        PMenuItem { text: "Zwei Seiten"; iconName: "book_open"; onTriggered: root.doc.setViewMode("two") }
        PMenuItem { text: "Fortlaufend, zwei Seiten"; iconName: "layout_column_two"; onTriggered: root.doc.setViewMode("continuousTwo") }
    }
    PMenu {
        id: moreMenu
        PMenuItem { text: "Speichern unter …"; iconName: "save"; enabled: root.doc !== null; onTriggered: root.doc.saveDocumentAs() }
        PMenuItem { text: "Druckvorschau"; iconName: "eye"; enabled: root.doc !== null; onTriggered: root.doc.previewPrint() }
        PMenuItem { text: "Seiten organisieren"; iconName: "grid"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: Reader.setOrganize(!Reader.organize) }
        PMenuItem { text: "Seitenansicht …"; iconName: "document_one_page_multiple"; visible: !root.roomy; height: visible ? implicitHeight : 0; onTriggered: viewMenu.popup(moreButton, 0, moreButton.height) }
        PMenuItem { text: "Seiten als PNG exportieren (150 dpi)"; iconName: "arrow_export"; enabled: root.doc !== null; onTriggered: root.doc.exportImages([], "png", 150) }
        PMenuItem { text: "Seiten als PNG exportieren (300 dpi)"; iconName: "arrow_export"; enabled: root.doc !== null; onTriggered: root.doc.exportImages([], "png", 300) }
        PMenuItem { text: "Seiten als JPEG exportieren (150 dpi)"; iconName: "arrow_export"; enabled: root.doc !== null; onTriggered: root.doc.exportImages([], "jpeg", 150) }
        PMenuItem { objectName: "readerMenuOcr"; text: "Text erkennen (OCR) …"; iconName: "document_search"; enabled: root.doc !== null && !root.doc.ocrRunning; onTriggered: root.doc.recognizeText([]) }
        PMenuItem { text: "Erkannten Text entfernen"; iconName: "eraser"; enabled: root.doc !== null && !root.doc.ocrRunning; onTriggered: root.doc.removeRecognizedText([]) }
        PMenuItem { text: "PDFs anhängen …"; iconName: "merge"; enabled: root.doc !== null; onTriggered: root.doc.mergeFiles() }
        PMenuItem { text: "Dokument teilen …"; iconName: "document_landscape_split"; enabled: root.doc !== null; onTriggered: root.doc.splitDocument("") }
        PMenuItem { text: "Eigenschaften"; iconName: "info"; enabled: root.doc !== null; onTriggered: root.doc.showProperties() }
        PMenuItem { text: "Pfad kopieren"; iconName: "copy"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: App.copyPath(root.doc.path) }
        PMenuItem { text: "Ordner öffnen"; iconName: "folder"; enabled: root.doc !== null && root.doc.path !== ""; onTriggered: Reader.showInFolder(root.doc.path) }
        PMenuItem { text: "Schließen (Strg+W)"; iconName: "dismiss"; enabled: root.doc !== null; onTriggered: Reader.closeCurrent() }
    }
}
