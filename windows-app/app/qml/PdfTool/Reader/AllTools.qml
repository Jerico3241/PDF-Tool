import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Alle Werkzeuge« (seit 4.0, wie bei Acrobat): eine Liste aller Werkzeuge und Befehle des Readers mit Namen,
// in Gruppen (Bearbeiten, Kommentieren, Formulare und Unterschrift, Seiten, Schützen, Text erkennen, umwandeln und
// exportieren). Sie gleitet neben den Schnellwerkzeugen über die Seite und schließt sich mit Esc, einem Klick
// daneben oder sobald ein Eintrag gewählt ist. Das aktive Werkzeug ist markiert.
T.Popup {
    id: root
    objectName: "readerAllToolsPanel"
    property var doc: null
    readonly property string tool: doc ? doc.tool : "select"
    readonly property bool restricted: doc !== null && Object.keys(doc.permissions).some(function(key) { return doc.permissions[key] === false })

    // Eintrag: ``tool`` schaltet ein Werkzeug ein, ``run`` führt einen Befehl aus (erst nach dem Schließen –
    // ein Dialog bekäme sonst den Fokus nicht)
    readonly property var groups: [
        { title: "Bearbeiten", items: [
            { name: "readerAllEditText", text: "Text bearbeiten", icon: "text_edit_style", tool: "editText" },
            { name: "readerAllObjects", text: "Objekt bearbeiten", icon: "select_object", tool: "objects", tip: "Objekt bearbeiten: Text und andere PDF-Inhalte einzeln auswählen und bearbeiten." },
            { name: "readerAllAddText", text: "Text hinzufügen", icon: "text_add", tool: "addText" },
            { name: "readerToolImage", text: "Bilder", icon: "image", tool: "image" },
            { name: "readerToolLink", text: "Links", icon: "link", tool: "link" } ] },
        { title: "Kommentieren und Zeichnen", items: [
            { text: "Markieren", icon: "highlight", tool: "highlight" },
            { text: "Unterstreichen", icon: "text_underline", tool: "underline" },
            { text: "Durchstreichen", icon: "text_strikethrough", tool: "strikeout" },
            { text: "Notiz", icon: "comment", tool: "note" },
            { text: "Textfeld", icon: "textbox", tool: "textbox" },
            { text: "Freihand", icon: "pen", tool: "ink" },
            { text: "Rechteck", icon: "square", tool: "rect" },
            { text: "Ellipse", icon: "circle", tool: "ellipse" },
            { text: "Linie", icon: "line", tool: "line" },
            { text: "Pfeil", icon: "arrow_up_right", tool: "arrow" } ] },
        { title: "Formulare und Unterschrift", items: [
            { name: "readerToolFormFill", text: "Formular ausfüllen", icon: "form", tool: "form" },
            { name: "readerToolFormDesign", text: "Formular gestalten", icon: "form_new", tool: "formDesign" },
            { text: "Unterschrift setzen", icon: "signature", tool: "signature" },
            { text: "Neue Unterschrift …", icon: "pen", run: "newSignature" },
            { name: "readerMenuDigitalSign", text: "Digital signieren (Zertifikat) …", icon: "shield_checkmark", run: "digitalSign" },
            { name: "readerMenuCheckSignatures", text: "Signaturen prüfen", icon: "shield", run: "checkSignatures" },
            { text: "Stempel", icon: "document_checkmark", tool: "stamp" } ] },
        { title: "Seiten", items: [
            { name: "readerAllOrganize", text: "Seiten organisieren", icon: "grid", run: "organize" },
            { name: "readerMenuHeaderFooter", text: "Kopf- und Fußzeile, Seitenzahlen …", icon: "document_page_number", run: "headerFooter" },
            { name: "readerMenuWatermark", text: "Wasserzeichen …", icon: "layer", run: "watermark" },
            { text: "Kopf-/Fußzeile und Wasserzeichen entfernen …", icon: "eraser", run: "removeMarks" },
            { name: "readerMenuCrop", text: "Seiten zuschneiden …", icon: "crop", run: "crop" },
            { text: "Lesezeichen für diese Seite …", icon: "bookmark_add", run: "bookmark" },
            { text: "PDFs anhängen …", icon: "merge", run: "merge" },
            { text: "Dokument teilen …", icon: "document_landscape_split", run: "split" } ] },
        { title: "Schützen", items: [
            { name: "readerToolRedact", text: "Schwärzen", icon: "eye_off", tool: "redact" },
            { text: "Suchen und schwärzen …", icon: "document_search", run: "searchRedact" },
            { name: "readerMenuClean", text: "Dokument bereinigen …", icon: "shield_checkmark", run: "clean" },
            { name: "readerMenuProtect", text: "Kennwortschutz …", icon: "lock_closed", run: "protect" },
            { text: "Einschränkungen aufheben …", icon: "key", run: "unlock", onlyRestricted: true },
            { name: "readerMenuFlatten", text: "Reduzieren (Formulare und Kommentare fest übernehmen) …", icon: "layer", run: "flatten" },
            { name: "readerMenuOptimize", text: "PDF verkleinern …", icon: "arrow_minimize", run: "optimize" },
            { name: "readerMenuPdfa", text: "Als PDF/A speichern …", icon: "library", run: "pdfa" } ] },
        { title: "Text erkennen, umwandeln und exportieren", items: [
            { name: "readerMenuOcr", text: "Text erkennen (OCR) …", icon: "document_search", run: "ocr" },
            { text: "Erkannten Text entfernen", icon: "eraser", run: "removeOcr" },
            { text: "Seiten als PNG exportieren (150 dpi)", icon: "arrow_export", run: "png150" },
            { text: "Seiten als PNG exportieren (300 dpi)", icon: "arrow_export", run: "png300" },
            { text: "Seiten als JPEG exportieren (150 dpi)", icon: "arrow_export", run: "jpeg150" },
            { name: "readerMenuToWord", text: "In Word umwandeln (.docx) …", icon: "document", run: "toWord" },
            { name: "readerMenuToExcel", text: "In Excel umwandeln (.xlsx) …", icon: "document_table", run: "toExcel" },
            { name: "readerMenuToPowerPoint", text: "In PowerPoint umwandeln (.pptx) …", icon: "slide_settings", run: "toPowerPoint" },
            { name: "readerMenuToHtml", text: "Als Webseite speichern (.html) …", icon: "local_language", run: "toHtml" },
            { name: "readerMenuToText", text: "Als Text speichern (.txt) …", icon: "text_bullet_list_ltr", run: "toText" },
            { name: "readerMenuOfficeToPdf", text: "Word, Excel oder PowerPoint in PDF umwandeln …", icon: "document_pdf", run: "officeToPdf" } ] },
        { title: "Ansicht und Vergleichen", items: [
            { name: "readerAllCompare", text: "Mit anderer Fassung vergleichen …", icon: "branch_compare", run: "compare" },
            { name: "readerAllSplit", text: Reader.splitKey !== "" ? "Geteilte Ansicht schließen" : "Geteilte Ansicht (zwei PDFs nebeneinander)", icon: "layout_column_two", run: "split2" },
            { name: "readerAllPresent", text: "Präsentation" + Shortcuts.hints["reader.present"], icon: "play", run: "present" },
            { name: "readerAllSpeech", text: "Vorlesen" + Shortcuts.hints["reader.speech"], icon: "speaker_2", run: "speech" } ] }
    ]

    function perform(command) {
        var d = root.doc
        switch (command) {
        case "present": Reader.startPresentation(); break
        case "speech": Speech.readFromHere(); break
        case "split2": Reader.toggleSplit(); break
        case "compare": d.compareWith(); break
        case "newSignature": d.newSignature(); break
        case "digitalSign": d.digitalSign(); break
        case "checkSignatures": d.checkSignatures(); break
        case "organize": Reader.setOrganize(true); break
        case "headerFooter": d.headerFooterDocument(); break
        case "watermark": d.watermarkDocument(); break
        case "removeMarks": d.removePageMarks(); break
        case "crop": d.cropPages([]); break
        case "bookmark": d.addBookmark("", false); break
        case "merge": d.mergeFiles(); break
        case "split": d.splitDocument(""); break
        case "searchRedact": d.searchRedact(); break
        case "clean": d.cleanDocument(); break
        case "protect": d.protectDocument(); break
        case "unlock": d.unlockPermissions(); break
        case "flatten": d.flattenDocument(); break
        case "optimize": d.optimizeDocument(); break
        case "pdfa": d.pdfaDocument(); break
        case "ocr": d.recognizeText([]); break
        case "removeOcr": d.removeRecognizedText([]); break
        case "png150": d.exportImages([], "png", 150); break
        case "png300": d.exportImages([], "png", 300); break
        case "jpeg150": d.exportImages([], "jpeg", 150); break
        case "toWord": d.convertDocument("docx"); break
        case "toExcel": d.convertDocument("xlsx"); break
        case "toText": d.convertDocument("txt"); break
        case "toPowerPoint": d.convertDocument("pptx"); break
        case "toHtml": d.convertDocument("html"); break
        case "officeToPdf": Reader.officeToPdf(); break
        }
    }
    property string pending: ""
    function choose(entry) {
        if (!root.doc) return
        if (entry.tool) {
            if (Reader.organize) Reader.setOrganize(false)
            root.doc.setTool(entry.tool)
        } else {
            pending = entry.run
        }
        dismiss()
    }
    // Schließen ohne Klick daneben (Eintrag gewählt, Esc, ×). Schließt ein Klick daneben die Liste – etwa auf
    // »Alle Werkzeuge« –, öffnet derselbe Klick sie nicht gleich wieder (``closedAt``).
    property bool quietClose: false
    property double closedAt: 0
    function dismiss() {
        quietClose = true
        close()
    }
    Shortcut { sequence: "Escape"; enabled: root.opened; onActivated: root.dismiss() }
    onClosed: {
        closedAt = quietClose ? 0 : Date.now()
        quietClose = false
        var command = pending
        pending = ""
        // erst nach »closed«: ein Dialog, der hier wartet (z. B. »Text erkennen«), bliebe sonst unsichtbar
        if (command !== "" && root.doc) Qt.callLater(perform, command)
    }

    width: Metrics.readerAllToolsWidth
    padding: 0
    modal: false
    focus: true
    closePolicy: T.Popup.CloseOnPressOutsideParent
    background: Rectangle {
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusOverlay
        PShadow { radius: Metrics.radiusOverlay }
    }
    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.menu; easing.type: Motion.decelerate }
            NumberAnimation { property: "x"; from: root.x - Motion.paneShift; to: root.x; duration: Motion.menu; easing.type: Motion.decelerate }
        }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.enabled ? 83 : 0; easing.type: Motion.accelerate }
    }

    contentItem: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Metrics.readerPanelHeaderHeight
            Layout.leftMargin: Metrics.s16
            Layout.rightMargin: Metrics.s6
            PText { text: I18n.tr("Alle Werkzeuge", I18n.revision); textStyle: "bodyStrong"; Layout.fillWidth: true }
            PIconButton { objectName: "readerAllToolsClose"; iconName: "dismiss"; tip: I18n.tr("Schließen (Esc)", I18n.revision); onClicked: root.dismiss() }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.divider }
        Flickable {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: groupsColumn.implicitHeight + 2 * Metrics.s8
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            T.ScrollBar.vertical: PScrollBar {}
            Column {
                id: groupsColumn
                y: Metrics.s8
                width: list.width
                Repeater {
                    model: root.groups
                    Column {
                        id: group
                        required property var modelData
                        required property int index
                        width: groupsColumn.width
                        PText {
                            x: Metrics.s16
                            topPadding: group.index === 0 ? Metrics.s4 : Metrics.s12
                            bottomPadding: Metrics.s4
                            text: I18n.tr(group.modelData.title, I18n.revision)
                            textStyle: "caption"
                            tone: "secondary"
                        }
                        Repeater {
                            model: group.modelData.items
                            T.AbstractButton {
                                id: entry
                                required property var modelData
                                readonly property bool active: modelData.tool !== undefined && root.tool === modelData.tool
                                objectName: modelData.name || ""
                                x: Metrics.s4
                                width: group.width - 2 * Metrics.s4
                                height: visible ? 34 : 0
                                visible: !modelData.onlyRestricted || root.restricted
                                hoverEnabled: true
                                focusPolicy: Qt.TabFocus
                                text: I18n.tr(modelData.text, I18n.revision)
                                Accessible.role: modelData.tool !== undefined ? Accessible.RadioButton : Accessible.Button
                                Accessible.name: I18n.tr(text, I18n.revision)
                                Accessible.checkable: modelData.tool !== undefined
                                Accessible.checked: active
                                onClicked: root.choose(modelData)
                                Keys.onReturnPressed: root.choose(modelData)
                                Keys.onEnterPressed: root.choose(modelData)
                                background: Rectangle {
                                    radius: Metrics.radiusControl
                                    color: entry.pressed ? Theme.subtlePressed : (entry.hovered || entry.active ? Theme.subtleHover : "transparent")
                                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                                    Rectangle { visible: entry.active; x: 0; width: 3; height: 16; radius: 1.5; anchors.verticalCenter: parent.verticalCenter; color: Theme.accent }
                                    PFocusRing { visible: entry.visualFocus; inset: -1 }
                                }
                                contentItem: Row {
                                    leftPadding: Metrics.s12
                                    spacing: Metrics.s12
                                    PIcon { anchors.verticalCenter: parent.verticalCenter; name: entry.modelData.icon; color: entry.active ? Theme.accent : Theme.textPrimary }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: entry.width - Metrics.s12 * 3 - Metrics.iconSize
                                        text: I18n.tr(entry.text, I18n.revision)
                                        font: entry.active ? Typography.bodyStrong : Typography.body
                                        color: Theme.textPrimary
                                        elide: Text.ElideRight
                                        textFormat: Text.PlainText
                                    }
                                }
                                PToolTip { text: I18n.tr(entry.modelData.tip || "", I18n.revision); visible: text !== "" && entry.hovered && !entry.pressed; x: entry.width + Metrics.s8 }
                            }
                        }
                    }
                }
            }
        }
    }
}
