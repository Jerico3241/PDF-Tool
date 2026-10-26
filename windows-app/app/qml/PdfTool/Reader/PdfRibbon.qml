import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Menüband der PDFs (seit 5.0 Beta 3) – aufgebaut wie bei Texten und Tabellen: oben die Reiter Datei, Start,
// Kommentieren, Bearbeiten, Seiten und Ansicht (der aktive in PDF-Rot unterstrichen) mit Speichern, Drucken,
// Rückgängig, Wiederholen und »Alle Werkzeuge« rechts; darunter die Leiste des Reiters. Ein erneuter Klick auf das
// gewählte Werkzeug zeigt seine Einstellungen (Farbe, Stärke …). Was hier keinen Platz hat, steht in »Alle Werkzeuge«.
Rectangle {
    id: root
    objectName: "readerToolbar"
    property var doc: null
    property var view: null      // DocumentView: Zoom gleitet kurz
    property var tools: null     // AllTools: dessen Befehle (Schützen, Umwandeln …) nutzt das Menüband mit
    property bool allToolsOpen: false
    property string ribbon: "start"
    signal allToolsRequested()
    signal searchRequested()
    signal settingsRequested()
    readonly property color kindColor: FileKinds.color("pdf")
    readonly property bool ready: doc !== null
    readonly property string tool: doc ? doc.tool : "select"
    // Schmale Fenster: Schaltflächen nur mit Symbol
    readonly property bool roomy: width >= 1180
    readonly property bool wide: width >= 1260   // genug Platz auch für »Unterschreiben« mit Text

    implicitHeight: 38 + 46
    color: Theme.layer
    Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

    function chooseTool(key) {
        if (!doc) return
        if (Reader.organize) Reader.setOrganize(false)
        if (doc.tool === key) {
            if (key !== "select" && key !== "hand") root.settingsRequested()
            return
        }
        doc.setTool(key)
    }
    function zoom(action) {
        if (view) view.smoothly(action)
        else action()
    }
    function run(command) {
        if (tools && doc) tools.perform(command)
    }
    function toggleLeft(key) {
        if (Reader.leftPanel === key) Reader.setLeftPanel(key)
        else Reader.showLeftPanel(key)
    }
    function toggleRight(key) {
        if (Reader.rightPanel === key) Reader.setRightPanel(key)
        else Reader.showRightPanel(key)
    }
    // Strg+G: Seitennummer eingeben
    function focusPage() {
        ribbon = "start"
        pageField.forceActiveFocus(Qt.ShortcutFocusReason)
        pageField.selectAll()
    }
    function zoomText() { return doc ? Math.round(doc.zoom) + " %" : "" }

    // Schaltfläche der Leiste: Symbol und (optional) Text, ohne Fläche
    component ToolButton: PButton {
        kind: "subtle"
        leftPadding: text === "" ? 0 : 8
        rightPadding: text === "" ? 0 : 10
        enabled: root.ready
    }
    // Werkzeug: markiert, solange es gewählt ist
    component ToolChoice: ToolButton {
        property string toolKey: ""
        property string label: ""
        property bool needsWide: false    // Text erst im breiten Fenster
        text: label !== "" && root.roomy && (root.wide || !needsWide) ? I18n.tr(label, I18n.revision) : ""
        toggle: true
        checked: root.tool === toolKey && !Reader.organize
        onClicked: root.chooseTool(toolKey)
        Accessible.role: Accessible.RadioButton
    }
    component Bar: RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.bottomMargin: 1
        spacing: 2
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Reiter und Befehle rechts -----------------------------------------------------------------------------
        RowLayout {
            objectName: "readerRibbonTabs"
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            Layout.leftMargin: 12
            Layout.rightMargin: 12
            spacing: 2
            Repeater {
                model: [
                    { key: "file", label: "Datei" }, { key: "start", label: "Start" }, { key: "comment", label: "Kommentieren" },
                    { key: "edit", label: "Bearbeiten" }, { key: "pages", label: "Seiten" }, { key: "view", label: "Ansicht" }
                ]
                RibbonTab {
                    required property var modelData
                    objectName: "readerRibbon_" + modelData.key
                    key: modelData.key
                    text: I18n.tr(modelData.label, I18n.revision)
                    current: root.ribbon
                    kindColor: root.kindColor
                    onClicked: root.ribbon = key
                }
            }
            Item { Layout.fillWidth: true }
            // »Speichern …« → »Gespeichert« (kurz), ohne Dialog; feste Breite: die Leiste springt nicht
            PCrossfadeText {
                objectName: "readerSaveState"
                Layout.rightMargin: 6
                Layout.preferredWidth: saveStateWidth.advanceWidth + 4
                Layout.fillHeight: true
                font: Typography.caption
                color: Theme.textSecondary
                horizontalAlignment: Text.AlignRight
                text: I18n.tr(root.doc === null ? "" : (root.doc.saveState === "saving" ? "Speichern …" : (root.doc.saveState === "saved" ? "Gespeichert" : "")), I18n.revision)
                TextMetrics { id: saveStateWidth; font: Typography.caption; text: I18n.tr("Speichern …", I18n.revision) }
            }
            PIconButton {
                objectName: "readerSave"
                iconName: "save"
                tip: I18n.tr("Speichern" + Shortcuts.hints["reader.save"], I18n.revision)
                enabled: root.doc !== null && !root.doc.busy && (root.doc.dirty || root.doc.path === "")
                busy: root.doc !== null && root.doc.saving
                onClicked: root.doc.saveDocument()
            }
            PIconButton { objectName: "readerPrint"; iconName: "print"; tip: I18n.tr("Drucken" + Shortcuts.hints["reader.print"], I18n.revision); enabled: root.ready; onClicked: root.doc.printDocument() }
            PIconButton {
                objectName: "readerUndo"
                iconName: "arrow_undo"
                tip: I18n.tr((root.doc && root.doc.undoText ? "Rückgängig: " + root.doc.undoText : "Rückgängig") + Shortcuts.hints["reader.undo"], I18n.revision)
                enabled: root.doc !== null && root.doc.undoText !== "" && !root.doc.busy
                onClicked: root.doc.undo()
            }
            PIconButton {
                objectName: "readerRedo"
                iconName: "arrow_redo"
                tip: I18n.tr((root.doc && root.doc.redoText ? "Wiederholen: " + root.doc.redoText : "Wiederholen") + Shortcuts.hints["reader.redo"], I18n.revision)
                enabled: root.doc !== null && root.doc.redoText !== "" && !root.doc.busy
                onClicked: root.doc.redo()
            }
            RibbonSeparator {}
            // »Alle Werkzeuge« mit Namen – wie »Als PDF speichern« bei Texten an derselben Stelle
            PButton {
                objectName: "readerAllTools"
                kind: "link"
                iconName: "apps"
                text: I18n.tr("Alle Werkzeuge", I18n.revision)
                tip: I18n.tr("Alle Werkzeuge mit Namen zeigen", I18n.revision)
                enabled: root.ready
                onClicked: root.allToolsRequested()
            }
        }

        // Leiste des Reiters -------------------------------------------------------------------------------------
        Item {
            objectName: "readerRibbonBar"
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            clip: true

            // Start: Auswählen, Verschieben | Markieren, Notiz, Freihand, Text hinzufügen | Text bearbeiten,
            // Unterschreiben | Seite | Zoom … Suchen, Seitenleiste
            Bar {
                objectName: "readerRibbonBar_start"
                visible: root.ribbon === "start"
                ToolChoice { objectName: "readerToolSelect"; toolKey: "select"; iconName: "cursor"; label: I18n.tr("Auswählen", I18n.revision); tip: I18n.tr("Auswählen: Text markieren und kopieren, Kommentare verschieben", I18n.revision) }
                ToolChoice { objectName: "readerToolHand"; toolKey: "hand"; iconName: "hand_left"; tip: I18n.tr("Verschieben: das Dokument mit gedrückter Maustaste bewegen", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { objectName: "readerToolComment"; toolKey: "highlight"; iconName: "highlight"; label: I18n.tr("Markieren", I18n.revision); tip: I18n.tr("Text markieren", I18n.revision) }
                ToolChoice { toolKey: "note"; iconName: "comment"; tip: I18n.tr("Notiz", I18n.revision) }
                ToolChoice { objectName: "readerToolDraw"; toolKey: "ink"; iconName: "pen"; tip: I18n.tr("Freihand zeichnen", I18n.revision) }
                ToolChoice { objectName: "readerToolAddText"; toolKey: "addText"; iconName: "text_add"; label: I18n.tr("Text hinzufügen", I18n.revision); tip: I18n.tr("Text hinzufügen", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { objectName: "readerToolEditText"; toolKey: "editText"; iconName: "text_edit_style"; label: I18n.tr("Text bearbeiten", I18n.revision); tip: I18n.tr("Text bearbeiten: Absätze mit Cursor ändern, ergänzen, umbrechen", I18n.revision) }
                ToolChoice { objectName: "readerToolSign"; toolKey: "signature"; iconName: "signature"; needsWide: true; label: I18n.tr("Unterschreiben", I18n.revision); tip: I18n.tr("Unterschreiben: Unterschrift zeichnen oder einlesen und auf die Seite setzen (keine digitale Signatur)", I18n.revision) }
                RibbonSeparator {}
                ToolButton { iconName: "chevron_left"; tip: I18n.tr("Vorherige Seite (Bild ↑)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage > 0; onClicked: root.doc.step(-1) }
                PTextField {
                    id: pageField
                    objectName: "readerPageField"
                    preferredWidth: 48
                    horizontalAlignment: TextInput.AlignHCenter
                    label: I18n.tr("Seite", I18n.revision)
                    enabled: root.ready
                    text: root.doc ? String(root.doc.currentPage + 1) : ""
                    validator: IntValidator { bottom: 1; top: root.doc ? Math.max(1, root.doc.pageCount) : 1 }
                    onAccepted: {
                        root.doc.goTo(parseInt(text) - 1)
                        text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
                        if (root.view) root.view.forceActiveFocus()
                    }
                    onActiveFocusChanged: if (!activeFocus) text = Qt.binding(function() { return root.doc ? String(root.doc.currentPage + 1) : "" })
                }
                PText { text: I18n.tr(root.doc ? "/ " + root.doc.pageCount : "", I18n.revision); tone: "secondary"; Layout.leftMargin: 4; Layout.rightMargin: 2 }
                ToolButton { iconName: "chevron_right"; tip: I18n.tr("Nächste Seite (Bild ↓)", I18n.revision); enabled: root.doc !== null && root.doc.currentPage < root.doc.pageCount - 1; onClicked: root.doc.step(1) }
                RibbonSeparator {}
                ToolButton { objectName: "readerZoomOut"; iconName: "zoom_out"; tip: I18n.tr("Verkleinern" + Shortcuts.hints["reader.zoomOut"], I18n.revision); onClicked: root.zoom(function() { root.doc.zoomOut() }) }
                // Zoom: eigenen Wert eintippen (Eingabetaste) oder eine Stufe aus dem Menü wählen
                PTextField {
                    id: zoomField
                    objectName: "readerZoomField"
                    preferredWidth: 60
                    horizontalAlignment: TextInput.AlignHCenter
                    label: I18n.tr("Zoom in Prozent", I18n.revision)
                    enabled: root.ready
                    text: root.zoomText()
                    validator: RegularExpressionValidator { regularExpression: /^\s*\d{1,3}([,.]\d)?\s*%?\s*$/ }
                    onAccepted: {
                        var value = parseFloat(text.replace(",", ".").replace("%", ""))
                        if (!isNaN(value) && root.doc) root.zoom(function() { root.doc.setZoom(value) })
                        text = Qt.binding(root.zoomText)
                        if (root.view) root.view.forceActiveFocus()
                    }
                    onActiveFocusChanged: {
                        if (activeFocus) selectAll()
                        else text = Qt.binding(root.zoomText)
                    }
                    Keys.onEscapePressed: { text = Qt.binding(root.zoomText); if (root.view) root.view.forceActiveFocus() }
                }
                ToolButton {
                    id: zoomButton
                    objectName: "readerZoom"
                    implicitWidth: 24
                    iconName: "chevron_down"
                    tip: I18n.tr("Zoomstufe wählen", I18n.revision)
                    onClicked: zoomMenu.popup(zoomButton, 0, zoomButton.height + 4)
                }
                ToolButton { objectName: "readerZoomIn"; iconName: "zoom_in"; tip: I18n.tr("Vergrößern" + Shortcuts.hints["reader.zoomIn"], I18n.revision); onClicked: root.zoom(function() { root.doc.zoomIn() }) }
                Item { Layout.fillWidth: true }
                PIconButton { objectName: "readerSearchButton"; iconName: "search"; tip: I18n.tr("Suchen" + Shortcuts.hints["app.find"], I18n.revision); enabled: root.ready; onClicked: root.searchRequested() }
                PIconButton {
                    objectName: "readerSidebarToggle"
                    iconName: "panel_right"
                    tip: I18n.tr("Seitenleiste ein- oder ausblenden", I18n.revision)
                    toggle: true
                    checked: Reader.leftPanel !== "" || Reader.rightPanel !== ""
                    onClicked: {
                        if (Reader.leftPanel !== "") Reader.setLeftPanel(Reader.leftPanel)
                        else if (Reader.rightPanel !== "") Reader.setRightPanel(Reader.rightPanel)
                        else Reader.showLeftPanel("thumbs")
                    }
                }
            }

            // Datei
            Bar {
                objectName: "readerRibbonBar_file"
                visible: root.ribbon === "file"
                ToolButton { objectName: "readerOpen"; iconName: "folder_open"; text: I18n.tr("Öffnen", I18n.revision); tip: I18n.tr("Öffnen" + Shortcuts.hints["app.open"], I18n.revision); enabled: true; onClicked: Reader.openDialog() }
                RibbonSeparator {}
                ToolButton { iconName: "save"; text: I18n.tr("Speichern", I18n.revision); enabled: root.doc !== null && !root.doc.busy; onClicked: root.doc.saveDocument() }
                ToolButton { objectName: "readerSaveAs"; iconName: "save"; text: I18n.tr("Speichern unter …", I18n.revision); onClicked: root.doc.saveDocumentAs() }
                ToolButton { iconName: "print"; text: I18n.tr("Drucken", I18n.revision); onClicked: root.doc.printDocument() }
                ToolButton { iconName: "eye"; tip: I18n.tr("Druckvorschau", I18n.revision); onClicked: root.doc.previewPrint() }
                RibbonSeparator {}
                ToolButton { id: protectButton; iconName: "lock_closed"; text: I18n.tr("Schützen", I18n.revision); onClicked: protectMenu.popup(protectButton, 0, protectButton.height + 4) }
                ToolButton { id: convertButton; iconName: "arrow_export"; text: I18n.tr("Umwandeln", I18n.revision); onClicked: convertMenu.popup(convertButton, 0, convertButton.height + 4) }
                RibbonSeparator {}
                ToolButton { objectName: "readerMail"; iconName: "mail"; text: root.roomy ? I18n.tr("Per E-Mail senden", I18n.revision) : ""; tip: I18n.tr("Per E-Mail senden", I18n.revision); onClicked: Reader.sendByMail() }
                ToolButton { iconName: "folder"; text: I18n.tr("Ordner öffnen", I18n.revision); enabled: root.doc !== null && root.doc.path !== ""; onClicked: Reader.showInFolder(root.doc.path) }
                ToolButton { iconName: "info"; tip: I18n.tr("Eigenschaften", I18n.revision); onClicked: root.doc.showProperties() }
                ToolButton { iconName: "dismiss"; text: I18n.tr("Schließen", I18n.revision); onClicked: Reader.closeCurrent() }
                Item { Layout.fillWidth: true }
            }

            // Kommentieren: Text markieren, Notizen, Formen, Stempel … Kommentare
            Bar {
                objectName: "readerRibbonBar_comment"
                visible: root.ribbon === "comment"
                ToolChoice { toolKey: "highlight"; iconName: "highlight"; label: I18n.tr("Markieren", I18n.revision); tip: I18n.tr("Markieren", I18n.revision) }
                ToolChoice { toolKey: "underline"; iconName: "text_underline"; label: I18n.tr("Unterstreichen", I18n.revision); tip: I18n.tr("Unterstreichen", I18n.revision) }
                ToolChoice { toolKey: "strikeout"; iconName: "text_strikethrough"; label: I18n.tr("Durchstreichen", I18n.revision); tip: I18n.tr("Durchstreichen", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { toolKey: "note"; iconName: "comment"; label: I18n.tr("Notiz", I18n.revision); tip: I18n.tr("Notiz", I18n.revision) }
                ToolChoice { toolKey: "textbox"; iconName: "textbox"; label: I18n.tr("Textfeld", I18n.revision); tip: I18n.tr("Textfeld", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { toolKey: "ink"; iconName: "pen"; label: I18n.tr("Freihand", I18n.revision); tip: I18n.tr("Freihand (auch für eine sichtbare Unterschrift)", I18n.revision) }
                ToolChoice { toolKey: "rect"; iconName: "square"; tip: I18n.tr("Rechteck", I18n.revision) }
                ToolChoice { toolKey: "ellipse"; iconName: "circle"; tip: I18n.tr("Ellipse", I18n.revision) }
                ToolChoice { toolKey: "line"; iconName: "line"; tip: I18n.tr("Linie", I18n.revision) }
                ToolChoice { toolKey: "arrow"; iconName: "arrow_up_right"; tip: I18n.tr("Pfeil", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { objectName: "readerToolStamp"; toolKey: "stamp"; iconName: "document_checkmark"; label: I18n.tr("Stempel", I18n.revision); tip: I18n.tr("Stempel setzen (GENEHMIGT, ENTWURF, eigener Text …)", I18n.revision) }
                Item { Layout.fillWidth: true }
                ToolButton {
                    objectName: "readerCommentsToggle"
                    iconName: "comment"
                    text: I18n.tr("Kommentare", I18n.revision)
                    toggle: true
                    checked: Reader.rightPanel === "comments"
                    onClicked: root.toggleRight("comments")
                }
            }

            // Bearbeiten: Text und Objekte, Bilder, Links, Formulare, Unterschrift, Schwärzen, Texterkennung
            Bar {
                objectName: "readerRibbonBar_edit"
                visible: root.ribbon === "edit"
                ToolChoice { toolKey: "editText"; iconName: "text_edit_style"; label: I18n.tr("Text bearbeiten", I18n.revision); tip: I18n.tr("Text bearbeiten: Absätze mit Cursor ändern, ergänzen, umbrechen", I18n.revision) }
                ToolChoice { objectName: "readerToolObjects"; toolKey: "objects"; iconName: "select_object"; label: I18n.tr("Objekt bearbeiten", I18n.revision); tip: I18n.tr("Objekt bearbeiten: Text und andere PDF-Inhalte einzeln auswählen und bearbeiten.", I18n.revision) }
                ToolChoice { toolKey: "addText"; iconName: "text_add"; label: I18n.tr("Text hinzufügen", I18n.revision); tip: I18n.tr("Text hinzufügen", I18n.revision) }
                ToolChoice { toolKey: "image"; iconName: "image"; label: I18n.tr("Bild", I18n.revision); tip: I18n.tr("Bilder einfügen, verschieben, ersetzen", I18n.revision) }
                ToolChoice { toolKey: "link"; iconName: "link"; label: I18n.tr("Link", I18n.revision); tip: I18n.tr("Links", I18n.revision) }
                RibbonSeparator {}
                ToolChoice { toolKey: "form"; iconName: "form"; label: I18n.tr("Formular ausfüllen", I18n.revision); tip: I18n.tr("Formular ausfüllen", I18n.revision) }
                ToolChoice { objectName: "readerRibbonFormDesign"; toolKey: "formDesign"; iconName: "form_new"; tip: I18n.tr("Formular gestalten", I18n.revision) }
                RibbonSeparator {}
                ToolButton { id: signButton; objectName: "readerSignMenu"; iconName: "signature"; text: root.roomy ? I18n.tr("Unterschrift", I18n.revision) : ""; tip: I18n.tr("Unterschrift, digitale Signatur oder Stempel", I18n.revision); onClicked: signMenu.popup(signButton, 0, signButton.height + 4) }
                ToolChoice { toolKey: "redact"; iconName: "eye_off"; label: I18n.tr("Schwärzen", I18n.revision); tip: I18n.tr("Schwärzen", I18n.revision) }
                ToolButton { iconName: "document_search"; text: root.roomy ? I18n.tr("Text erkennen", I18n.revision) : ""; tip: I18n.tr("Text erkennen (OCR) …", I18n.revision); onClicked: root.run("ocr") }
                Item { Layout.fillWidth: true }
            }

            // Seiten
            Bar {
                objectName: "readerRibbonBar_pages"
                visible: root.ribbon === "pages"
                ToolButton { objectName: "readerOrganize"; iconName: "grid"; text: I18n.tr("Seiten organisieren", I18n.revision); toggle: true; checked: Reader.organize; onClicked: Reader.setOrganize(!Reader.organize) }
                RibbonSeparator {}
                ToolButton { iconName: "document_page_number"; text: I18n.tr("Kopf- und Fußzeile", I18n.revision); tip: I18n.tr("Kopf- und Fußzeile, Seitenzahlen …", I18n.revision); onClicked: root.run("headerFooter") }
                ToolButton { iconName: "layer"; text: I18n.tr("Wasserzeichen", I18n.revision); onClicked: root.run("watermark") }
                ToolButton { iconName: "crop"; text: I18n.tr("Zuschneiden", I18n.revision); tip: I18n.tr("Seiten zuschneiden …", I18n.revision); onClicked: root.run("crop") }
                RibbonSeparator {}
                ToolButton { iconName: "merge"; text: I18n.tr("PDFs anhängen", I18n.revision); onClicked: root.run("merge") }
                ToolButton { iconName: "document_landscape_split"; text: I18n.tr("Teilen", I18n.revision); tip: I18n.tr("Dokument teilen …", I18n.revision); onClicked: root.run("split") }
                RibbonSeparator {}
                ToolButton { iconName: "bookmark_add"; text: I18n.tr("Lesezeichen", I18n.revision); tip: I18n.tr("Lesezeichen für diese Seite …", I18n.revision); onClicked: root.run("bookmark") }
                Item { Layout.fillWidth: true }
            }

            // Ansicht: Seitenansicht, Zoom, Seitenleisten, Vergleichen und Präsentation
            Bar {
                objectName: "readerRibbonBar_view"
                visible: root.ribbon === "view"
                ToolButton { objectName: "readerViewSingle"; iconName: "document_one_page"; tip: I18n.tr("Einzelseite", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.viewMode === "single"; onClicked: root.doc.setViewMode("single") }
                ToolButton { objectName: "readerViewMode"; iconName: "document_one_page_multiple"; tip: I18n.tr("Fortlaufend", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.viewMode === "continuous"; onClicked: root.doc.setViewMode("continuous") }
                ToolButton { iconName: "book_open"; tip: I18n.tr("Zwei Seiten", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.viewMode === "two"; onClicked: root.doc.setViewMode("two") }
                ToolButton { iconName: "layout_column_two"; tip: I18n.tr("Fortlaufend, zwei Seiten", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.viewMode === "continuousTwo"; onClicked: root.doc.setViewMode("continuousTwo") }
                RibbonSeparator {}
                ToolButton { objectName: "readerFitWidth"; iconName: "arrow_autofit_width"; tip: I18n.tr("Seitenbreite", I18n.revision); toggle: true; checked: root.doc !== null && root.doc.fit === "width"; onClicked: root.zoom(function() { root.doc.fitWidth() }) }
                ToolButton { objectName: "readerFitPage"; iconName: "page_fit"; tip: I18n.tr("Ganze Seite" + Shortcuts.hints["reader.fitPage"], I18n.revision); toggle: true; checked: root.doc !== null && root.doc.fit === "page"; onClicked: root.zoom(function() { root.doc.fitPage() }) }
                RibbonSeparator {}
                ToolButton { iconName: "document_one_page_multiple"; text: I18n.tr("Seiten", I18n.revision); toggle: true; checked: Reader.leftPanel === "thumbs"; onClicked: root.toggleLeft("thumbs") }
                ToolButton { iconName: "bookmark"; text: root.roomy ? I18n.tr("Lesezeichen", I18n.revision) : ""; tip: I18n.tr("Lesezeichen", I18n.revision); toggle: true; checked: Reader.leftPanel === "outline"; onClicked: root.toggleLeft("outline") }
                ToolButton { iconName: "attach"; text: root.roomy ? I18n.tr("Anhänge", I18n.revision) : ""; tip: I18n.tr("Anhänge", I18n.revision); toggle: true; checked: Reader.leftPanel === "attachments"; onClicked: root.toggleLeft("attachments") }
                ToolButton { iconName: "text_font"; text: root.roomy ? I18n.tr("Eigenschaften", I18n.revision) : ""; tip: I18n.tr("Eigenschaften", I18n.revision); toggle: true; checked: Reader.rightPanel === "properties"; onClicked: root.toggleRight("properties") }
                ToolButton { visible: Assistant.enabled; iconName: "sparkle"; tip: I18n.tr("KI-Assistent", I18n.revision); toggle: true; checked: Reader.rightPanel === "assistant"; onClicked: root.toggleRight("assistant") }
                RibbonSeparator {}
                ToolButton { objectName: "readerViewSplit"; iconName: "layout_column_two"; text: root.roomy ? I18n.tr("Geteilt", I18n.revision) : ""; tip: I18n.tr(Reader.splitKey !== "" ? "Geteilte Ansicht schließen" : "Geteilte Ansicht (zwei PDFs nebeneinander)", I18n.revision); toggle: true; checked: Reader.splitKey !== ""; onClicked: Reader.toggleSplit() }
                ToolButton { iconName: "branch_compare"; text: root.roomy ? I18n.tr("Vergleichen", I18n.revision) : ""; tip: I18n.tr("Mit anderer Fassung vergleichen …", I18n.revision); onClicked: root.run("compare") }
                ToolButton { objectName: "readerViewPresent"; iconName: "play"; tip: I18n.tr("Präsentation" + Shortcuts.hints["reader.present"], I18n.revision); onClicked: Reader.startPresentation() }
                ToolButton { objectName: "readerFullScreen"; iconName: "full_screen_maximize"; tip: I18n.tr("Vollbild" + Shortcuts.hints["reader.fullScreen"], I18n.revision); onClicked: Reader.toggleFullScreen() }
                ToolButton { objectName: "readerMenuSpeech"; iconName: "speaker_2"; tip: I18n.tr((Speech.active ? "Vorlesen beenden" : "Vorlesen") + Shortcuts.hints["reader.speech"], I18n.revision); toggle: true; checked: Speech.active; onClicked: Speech.toggle() }
                ToolButton { objectName: "readerNightMode"; iconName: "weather_moon"; tip: I18n.tr("Nachtmodus (Seiten dunkel)", I18n.revision); toggle: true; checked: Reader.nightMode; enabled: true; onClicked: Reader.setNightMode(!Reader.nightMode) }
                Item { Layout.fillWidth: true }
            }
        }
    }

    PMenu {
        id: zoomMenu
        PMenuItem { text: I18n.tr("50 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(50) }) }
        PMenuItem { text: I18n.tr("75 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(75) }) }
        PMenuItem { text: I18n.tr("100 % (Originalgröße)", I18n.revision); onTriggered: root.zoom(function() { root.doc.actualSize() }) }
        PMenuItem { text: I18n.tr("125 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(125) }) }
        PMenuItem { text: I18n.tr("150 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(150) }) }
        PMenuItem { text: I18n.tr("200 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(200) }) }
        PMenuItem { text: I18n.tr("400 %", I18n.revision); onTriggered: root.zoom(function() { root.doc.setZoom(400) }) }
        PMenuItem { text: I18n.tr("Seitenbreite", I18n.revision); iconName: "arrow_autofit_width"; onTriggered: root.zoom(function() { root.doc.fitWidth() }) }
        PMenuItem { text: I18n.tr("Ganze Seite", I18n.revision); iconName: "page_fit"; onTriggered: root.zoom(function() { root.doc.fitPage() }) }
    }
    PMenu {
        id: signMenu
        objectName: "readerSignToolMenu"
        PMenuItem { objectName: "readerToolSignature"; text: I18n.tr("Unterschrift setzen", I18n.revision); iconName: "signature"; onTriggered: root.chooseTool("signature") }
        PMenuItem { text: I18n.tr("Neue Unterschrift …", I18n.revision); iconName: "pen"; onTriggered: signMenu.afterClose = function() { root.run("newSignature") } }
        PMenuItem { text: I18n.tr("Digital signieren (Zertifikat) …", I18n.revision); iconName: "shield_checkmark"; onTriggered: signMenu.afterClose = function() { root.run("digitalSign") } }
        PMenuItem { text: I18n.tr("Signaturen prüfen", I18n.revision); iconName: "shield"; onTriggered: signMenu.afterClose = function() { root.run("checkSignatures") } }
        PMenuItem { text: I18n.tr("Stempel", I18n.revision); iconName: "document_checkmark"; onTriggered: root.chooseTool("stamp") }
    }
    PMenu {
        id: protectMenu
        PMenuItem { text: I18n.tr("Kennwortschutz …", I18n.revision); iconName: "lock_closed"; onTriggered: protectMenu.afterClose = function() { root.run("protect") } }
        PMenuItem { text: I18n.tr("Suchen und schwärzen …", I18n.revision); iconName: "document_search"; onTriggered: protectMenu.afterClose = function() { root.run("searchRedact") } }
        PMenuItem { text: I18n.tr("Dokument bereinigen …", I18n.revision); iconName: "shield_checkmark"; onTriggered: protectMenu.afterClose = function() { root.run("clean") } }
        PMenuItem { text: I18n.tr("Reduzieren (Formulare und Kommentare fest übernehmen) …", I18n.revision); iconName: "layer"; onTriggered: protectMenu.afterClose = function() { root.run("flatten") } }
        PMenuItem { text: I18n.tr("PDF verkleinern …", I18n.revision); iconName: "arrow_minimize"; onTriggered: protectMenu.afterClose = function() { root.run("optimize") } }
        PMenuItem { text: I18n.tr("Als PDF/A speichern …", I18n.revision); iconName: "library"; onTriggered: protectMenu.afterClose = function() { root.run("pdfa") } }
    }
    PMenu {
        id: convertMenu
        PMenuItem { text: I18n.tr("In Word umwandeln (.docx) …", I18n.revision); iconName: "document"; onTriggered: convertMenu.afterClose = function() { root.run("toWord") } }
        PMenuItem { text: I18n.tr("In Excel umwandeln (.xlsx) …", I18n.revision); iconName: "document_table"; onTriggered: convertMenu.afterClose = function() { root.run("toExcel") } }
        PMenuItem { text: I18n.tr("Als Text speichern (.txt) …", I18n.revision); iconName: "text_bullet_list_ltr"; onTriggered: convertMenu.afterClose = function() { root.run("toText") } }
        PMenuItem { text: I18n.tr("Seiten als PNG exportieren (150 dpi)", I18n.revision); iconName: "arrow_export"; onTriggered: convertMenu.afterClose = function() { root.run("png150") } }
        PMenuItem { text: I18n.tr("Seiten als JPEG exportieren (150 dpi)", I18n.revision); iconName: "arrow_export"; onTriggered: convertMenu.afterClose = function() { root.run("jpeg150") } }
    }
}
