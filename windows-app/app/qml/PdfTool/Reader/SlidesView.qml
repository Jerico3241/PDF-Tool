import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Präsentation bearbeiten (seit 5.0 Beta 4, nach dem Entwurf »4-praesentation«): oben die Reiter Datei, Start,
// Einfügen, Entwurf, Überprüfen und Ansicht mit Speichern, Drucken, Rückgängig, Wiederholen, »Präsentieren« und
// »Als PDF speichern« rechts; darunter die Leiste des Reiters, in der Mitte die Folie auf grauem Grund und darunter
// die Notizen, rechts die Folienleiste und am Fensterrand der Streifen mit ihren Symbolen (SideRail) – wie bei
// Texten und PDFs. Folie und Sprache stehen in der Statuszeile des Fensters.
FocusScope {
    id: view
    objectName: "slidesView"
    property var doc: null
    property string ribbon: "start"
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open && doc !== null
    readonly property color kindColor: FileKinds.color("praesentation")
    readonly property bool ready: doc !== null && doc.ready
    readonly property var fonts: ["Calibri", "Aptos", "Arial", "Segoe UI", "Cambria", "Times New Roman", "Georgia", "Verdana", "Tahoma", "Courier New", "Liberation Sans", "Liberation Serif"]
    readonly property var sizes: ["8", "9", "10", "12", "14", "16", "18", "20", "24", "28", "32", "36", "40", "44", "54", "72"]
    readonly property var swatches: ["#000000", "#404040", "#7F7F7F", "#C00000", "#FF0000", "#ED7D31", "#FFC000", "#00B050", "#0070C0", "#002060", "#7030A0", "#1F4E79"]

    onDocChanged: if (doc) Qt.callLater(function() { canvas.forceActiveFocus() })
    function back() { canvas.forceActiveFocus() }

    // Die Folie füllt die Ansicht: beim Laden, bei neuer Fenstergröße und nach »An die Ansicht anpassen«
    function fitSlide() { if (view.doc) view.doc.fitSlide(canvas.width, canvas.height) }

    Connections {
        target: view.doc
        function onFindRequested() { findBar.show() }
        function onFitRequested() { view.fitSlide() }
        function onReadyChanged() { view.fitSlide() }
        function onDocWidthChanged() { view.fitSlide() }
        function onDocHeightChanged() { view.fitSlide() }
    }

    component ToolButton: PButton {
        kind: "subtle"
        leftPadding: text === "" ? 0 : 8
        rightPadding: text === "" ? 0 : 10
        enabled: view.ready
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
        Rectangle {
            objectName: "slidesRibbonTabs"
            Layout.fillWidth: true
            implicitHeight: 38
            color: Theme.layer
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                Repeater {
                    model: [
                        { key: "file", label: "Datei" }, { key: "start", label: "Start" }, { key: "insert", label: "Einfügen" },
                        { key: "design", label: "Entwurf" }, { key: "review", label: "Überprüfen" }, { key: "view", label: "Ansicht" }
                    ]
                    RibbonTab {
                        required property var modelData
                        objectName: "slidesRibbon_" + modelData.key
                        key: modelData.key
                        text: I18n.tr(modelData.label, I18n.revision)
                        current: view.ribbon
                        kindColor: view.kindColor
                        onClicked: view.ribbon = key
                    }
                }
                Item { Layout.fillWidth: true }
                PIconButton {
                    objectName: "slidesSave"
                    iconName: "save"
                    tip: I18n.tr("Speichern" + Shortcuts.hints["reader.save"], I18n.revision)
                    enabled: view.ready && !view.doc.saving
                    busy: view.doc !== null && view.doc.saving
                    onClicked: view.doc.saveNow()
                }
                PIconButton {
                    objectName: "slidesPrint"
                    iconName: "print"
                    tip: I18n.tr("Drucken" + Shortcuts.hints["reader.print"], I18n.revision)
                    enabled: view.ready
                    onClicked: view.doc.printText()
                }
                PIconButton {
                    objectName: "slidesUndo"
                    iconName: "arrow_undo"
                    tip: I18n.tr("Rückgängig" + Shortcuts.hints["reader.undo"], I18n.revision)
                    enabled: view.ready && view.doc.canUndo
                    onClicked: { view.doc.undo(); view.back() }
                }
                PIconButton {
                    objectName: "slidesRedo"
                    iconName: "arrow_redo"
                    tip: I18n.tr("Wiederholen" + Shortcuts.hints["reader.redo"], I18n.revision)
                    enabled: view.ready && view.doc.canRedo
                    onClicked: { view.doc.redo(); view.back() }
                }
                RibbonSeparator {}
                PButton {
                    objectName: "slidesPresent"
                    kind: "link"
                    iconName: "play"
                    text: I18n.tr("Präsentieren", I18n.revision)
                    tip: I18n.tr("Vollbild ab dieser Folie (F5)", I18n.revision)
                    enabled: view.ready
                    onClicked: view.doc.present()
                }
                PButton {
                    objectName: "slidesPdf"
                    kind: "link"
                    iconName: "document_pdf"
                    text: I18n.tr("Als PDF speichern", I18n.revision)
                    enabled: view.ready
                    onClicked: view.doc.exportPdf()
                }
            }
        }

        // Leiste des Reiters -------------------------------------------------------------------------------------
        Rectangle {
            objectName: "slidesToolbar"
            Layout.fillWidth: true
            implicitHeight: 46
            color: Theme.layer
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

            // Start (wie im Entwurf): Einfügen, Ausschneiden, Kopieren | Neue Folie, Layout | Schrift, Größe |
            // F, K, U, Farbe | Ausrichtung, Aufzählung | Formen, Bild … Suchen, Folienleiste
            Bar {
                objectName: "slidesRibbonBar_start"
                visible: view.ribbon === "start"
                ToolButton {
                    objectName: "slidesPaste"
                    iconName: "clipboard_paste"
                    text: I18n.tr("Einfügen", I18n.revision)
                    tip: I18n.tr("Einfügen (Strg+V)", I18n.revision)
                    onClicked: { view.doc.paste(); view.back() }
                }
                ToolButton { objectName: "slidesCut"; iconName: "cut"; tip: I18n.tr("Ausschneiden (Strg+X)", I18n.revision); enabled: view.ready && view.doc.canCopy; onClicked: { view.doc.cut(); view.back() } }
                ToolButton { objectName: "slidesCopy"; iconName: "copy"; tip: I18n.tr("Kopieren (Strg+C)", I18n.revision); enabled: view.ready && view.doc.canCopy; onClicked: { view.doc.copy(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "slidesNew"; iconName: "document_add"; text: I18n.tr("Neue Folie", I18n.revision); tip: I18n.tr("Folie hinter der gezeigten einfügen", I18n.revision); onClicked: { view.doc.newSlide(); view.back() } }
                ToolButton { id: layoutButton; objectName: "slidesLayout"; iconName: "layout_column_two"; text: I18n.tr("Layout", I18n.revision); onClicked: layoutMenu.popup(layoutButton, 0, layoutButton.height + 4) }
                RibbonSeparator {}
                PComboBox {
                    objectName: "slidesFont"
                    preferredWidth: 136
                    label: I18n.tr("Schriftart", I18n.revision)
                    enabled: view.ready
                    readonly property string value: view.doc && view.doc.fontName ? view.doc.fontName : ""
                    model: value === "" || view.fonts.indexOf(value) >= 0 ? view.fonts : [value].concat(view.fonts)
                    currentIndex: value === "" ? -1 : model.indexOf(value)
                    displayText: I18n.tr(value, I18n.revision)
                    onActivated: (index) => { view.doc.setFont(model[index]); view.back() }
                }
                PComboBox {
                    objectName: "slidesSize"
                    preferredWidth: 64
                    label: I18n.tr("Schriftgröße", I18n.revision)
                    enabled: view.ready
                    readonly property string value: view.doc && view.doc.fontSize ? view.doc.fontSize.replace(".", ",") : ""
                    model: value === "" || view.sizes.indexOf(value) >= 0 ? view.sizes : [value].concat(view.sizes)
                    currentIndex: value === "" ? -1 : model.indexOf(value)
                    displayText: I18n.tr(value, I18n.revision)
                    onActivated: (index) => { view.doc.setFontSize(model[index]); view.back() }
                }
                ToolButton { objectName: "slidesBold"; iconName: "text_bold"; tip: I18n.tr("Fett (Strg+B)", I18n.revision); toggle: true; checked: view.ready && view.doc.bold; onClicked: { view.doc.toggle("bold"); view.back() } }
                ToolButton { objectName: "slidesItalic"; iconName: "text_italic"; tip: I18n.tr("Kursiv (Strg+I)", I18n.revision); toggle: true; checked: view.ready && view.doc.italic; onClicked: { view.doc.toggle("italic"); view.back() } }
                ToolButton { objectName: "slidesUnderline"; iconName: "text_underline"; tip: I18n.tr("Unterstrichen (Strg+U)", I18n.revision); toggle: true; checked: view.ready && view.doc.underline; onClicked: { view.doc.toggle("underline"); view.back() } }
                ToolButton {
                    id: colorButton
                    objectName: "slidesColor"
                    iconName: "text_color"
                    tip: I18n.tr("Schriftfarbe", I18n.revision)
                    toggle: true
                    checked: colorFlyout.opened
                    onClicked: colorFlyout.opened ? colorFlyout.close() : colorFlyout.open()
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 5
                        width: 14
                        height: 3
                        radius: 1
                        color: view.doc && view.doc.fontColor ? view.doc.fontColor : Theme.textPrimary
                    }
                }
                RibbonSeparator {}
                ToolButton { objectName: "slidesAlignLeft"; iconName: "text_align_left"; tip: I18n.tr("Linksbündig (Strg+L)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "left"; onClicked: { view.doc.setAlign("left"); view.back() } }
                ToolButton { objectName: "slidesAlignCenter"; iconName: "text_align_center"; tip: I18n.tr("Zentriert (Strg+E)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "center"; onClicked: { view.doc.setAlign("center"); view.back() } }
                ToolButton { objectName: "slidesBullets"; iconName: "text_bullet_list_ltr"; tip: I18n.tr("Aufzählung", I18n.revision); toggle: true; checked: view.ready && view.doc.bullets; onClicked: { view.doc.toggle("bullets"); view.back() } }
                RibbonSeparator {}
                ToolButton { id: shapeButton; objectName: "slidesShapes"; iconName: "shapes"; text: I18n.tr("Formen", I18n.revision); tip: I18n.tr("Form wählen und auf der Folie aufziehen", I18n.revision); onClicked: shapeMenu.popup(shapeButton, 0, shapeButton.height + 4) }
                ToolButton { objectName: "slidesImage"; iconName: "image_add"; tip: I18n.tr("Bild aus einer Datei einfügen", I18n.revision); onClicked: { view.doc.insertImage(); view.back() } }
                Item { Layout.fillWidth: true }
                PIconButton { objectName: "slidesSearch"; iconName: "search"; tip: I18n.tr("Suchen (Strg+F)", I18n.revision); enabled: view.ready; onClicked: findBar.show() }
                PIconButton {
                    objectName: "slidesPanelToggle"
                    iconName: "panel_right"
                    tip: I18n.tr("Folienleiste ein- oder ausblenden", I18n.revision)
                    toggle: true
                    checked: view.doc !== null && view.doc.panel !== ""
                    onClicked: view.doc.togglePanel("slides")
                }
            }

            // Datei
            Bar {
                objectName: "slidesRibbonBar_file"
                visible: view.ribbon === "file"
                ToolButton { objectName: "slidesFileNew"; iconName: "document_add"; text: I18n.tr("Neue Präsentation", I18n.revision); enabled: true; onClicked: Reader.newSlides() }
                ToolButton { iconName: "folder_open"; text: I18n.tr("Öffnen", I18n.revision); enabled: true; onClicked: Reader.openDialog() }
                RibbonSeparator {}
                ToolButton { iconName: "save"; text: I18n.tr("Speichern", I18n.revision); onClicked: view.doc.saveNow() }
                ToolButton { objectName: "slidesSaveAs"; iconName: "save"; text: I18n.tr("Speichern unter …", I18n.revision); onClicked: view.doc.saveAs() }
                ToolButton { iconName: "document_pdf"; text: I18n.tr("Als PDF speichern …", I18n.revision); onClicked: view.doc.exportPdf() }
                ToolButton { iconName: "print"; text: I18n.tr("Drucken", I18n.revision); onClicked: view.doc.printText() }
                RibbonSeparator {}
                ToolButton { iconName: "mail"; text: I18n.tr("Per E-Mail senden", I18n.revision); onClicked: Reader.sendByMail() }
                ToolButton { iconName: "folder"; text: I18n.tr("Ordner öffnen", I18n.revision); enabled: view.doc !== null && view.doc.path !== ""; onClicked: Reader.showInFolder(view.doc.path) }
                ToolButton { iconName: "dismiss"; text: I18n.tr("Schließen", I18n.revision); enabled: true; onClicked: Reader.closeCurrent() }
                Item { Layout.fillWidth: true }
            }

            // Einfügen
            Bar {
                objectName: "slidesRibbonBar_insert"
                visible: view.ribbon === "insert"
                ToolButton { iconName: "document_add"; text: I18n.tr("Neue Folie", I18n.revision); onClicked: { view.doc.newSlide(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "slidesInsertText"; iconName: "textbox"; text: I18n.tr("Textfeld", I18n.revision); tip: I18n.tr("Textfeld auf der Folie aufziehen", I18n.revision); onClicked: { view.doc.insertShape("text"); view.back() } }
                ToolButton { objectName: "slidesInsertImage"; iconName: "image_add"; text: I18n.tr("Bild", I18n.revision); onClicked: { view.doc.insertImage(); view.back() } }
                ToolButton { id: insertShapeButton; iconName: "shapes"; text: I18n.tr("Formen", I18n.revision); onClicked: shapeMenu.popup(insertShapeButton, 0, insertShapeButton.height + 4) }
                ToolButton { id: insertTableButton; objectName: "slidesInsertTable"; iconName: "table_simple"; text: I18n.tr("Tabelle", I18n.revision); onClicked: tableMenu.popup(insertTableButton, 0, insertTableButton.height + 4) }
                Item { Layout.fillWidth: true }
            }

            // Entwurf: Layout und die Reihenfolge der Folien
            Bar {
                objectName: "slidesRibbonBar_design"
                visible: view.ribbon === "design"
                ToolButton { id: designLayoutButton; objectName: "slidesDesignLayout"; iconName: "layout_column_two"; text: I18n.tr("Layout", I18n.revision); onClicked: layoutMenu.popup(designLayoutButton, 0, designLayoutButton.height + 4) }
                RibbonSeparator {}
                ToolButton { objectName: "slidesDuplicate"; iconName: "copy"; text: I18n.tr("Folie duplizieren", I18n.revision); onClicked: { view.doc.duplicateSlide(); view.back() } }
                ToolButton { objectName: "slidesDelete"; iconName: "delete"; text: I18n.tr("Folie löschen", I18n.revision); onClicked: { view.doc.deleteSlide(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "slidesMoveUp"; iconName: "chevron_up"; text: I18n.tr("Nach vorn", I18n.revision); tip: I18n.tr("Folie eine Stelle nach vorn schieben", I18n.revision); enabled: view.ready && view.doc.slideIndex > 0; onClicked: { view.doc.moveSlide(-1); view.back() } }
                ToolButton { objectName: "slidesMoveDown"; iconName: "chevron_down"; text: I18n.tr("Nach hinten", I18n.revision); tip: I18n.tr("Folie eine Stelle nach hinten schieben", I18n.revision); enabled: view.ready && view.doc.slideIndex < view.doc.slideCount - 1; onClicked: { view.doc.moveSlide(1); view.back() } }
                Item { Layout.fillWidth: true }
            }

            // Überprüfen
            Bar {
                objectName: "slidesRibbonBar_review"
                visible: view.ribbon === "review"
                ToolButton { objectName: "slidesSpelling"; iconName: "text_proofing_tools"; text: I18n.tr("Rechtschreibung prüfen", I18n.revision); tip: I18n.tr("Falsch geschriebene Wörter rot unterstreichen", I18n.revision); toggle: true; checked: view.ready && view.doc.spelling; onClicked: { view.doc.toggle("spelling"); view.back() } }
                RibbonSeparator {}
                ToolButton { iconName: "search"; text: I18n.tr("Suchen und ersetzen", I18n.revision); onClicked: findBar.show() }
                Item { Layout.fillWidth: true }
            }

            // Ansicht
            Bar {
                objectName: "slidesRibbonBar_view"
                visible: view.ribbon === "view"
                ToolButton { iconName: "zoom_out"; tip: I18n.tr("Verkleinern", I18n.revision); onClicked: view.doc.zoomStep(-1) }
                ToolButton { text: I18n.tr(view.doc ? view.doc.zoom + " %" : "", I18n.revision); tip: I18n.tr("Zoom auf 100 %", I18n.revision); onClicked: view.doc.setZoom(100) }
                ToolButton { iconName: "zoom_in"; tip: I18n.tr("Vergrößern", I18n.revision); onClicked: view.doc.zoomStep(1) }
                ToolButton { objectName: "slidesFit"; iconName: "page_fit"; text: I18n.tr("An die Ansicht anpassen", I18n.revision); toggle: true; checked: view.doc !== null && view.doc.fitting; onClicked: view.doc.fitAgain() }
                RibbonSeparator {}
                ToolButton { objectName: "slidesNotesToggle"; iconName: "comment"; text: I18n.tr("Notizen", I18n.revision); toggle: true; enabled: true; checked: view.doc !== null && view.doc.notesOpen; onClicked: view.doc.toggleNotes() }
                ToolButton { iconName: "panel_right"; text: I18n.tr("Folienleiste", I18n.revision); toggle: true; enabled: true; checked: view.doc !== null && view.doc.panel !== ""; onClicked: view.doc.togglePanel("slides") }
                RibbonSeparator {}
                ToolButton { objectName: "slidesPresentFromStart"; iconName: "play"; text: I18n.tr("Von der ersten Folie", I18n.revision); onClicked: view.doc.presentFromStart() }
                Item { Layout.fillWidth: true }
            }
        }

        // Folie, Notizen und die Folienleiste ----------------------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Item {
                id: stage
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        // Grund hinter der Folie; die Folie selbst bekommt oben und unten etwas Luft (wie im Entwurf)
                        Rectangle { anchors.fill: parent; color: Theme.viewer }

                        TextCanvas {
                            id: canvas
                            objectName: "slidesCanvas"
                            anchors.fill: parent
                            anchors.topMargin: 16
                            anchors.bottomMargin: 10
                            controller: view.doc
                            pixelRatio: Screen.devicePixelRatio
                            focus: true
                            backgroundColor: Theme.viewer
                            paperColor: "#FFFFFF"
                            caretColor: "#000000"
                            selectionColor: Theme.dark ? "#5A4CA0E0" : "#4D0078D4"
                            accentColor: Theme.dark ? "#4CA0E0" : "#0F6CBD"
                            onContextMenuRequested: (x, y) => slideMenu.popup(canvas, x, y)
                            onWidthChanged: view.fitSlide()
                            onHeightChanged: view.fitSlide()
                            Component.onCompleted: view.fitSlide()
                        }

                        PScrollBar {
                            id: vbar
                            objectName: "slidesVScroll"
                            orientation: Qt.Vertical
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            policy: T.ScrollBar.AlwaysOn
                            visible: canvas !== null && canvas.contentHeight > canvas.viewHeight + 1
                            size: canvas && canvas.contentHeight > 0 ? Math.min(1, canvas.viewHeight / canvas.contentHeight) : 1
                            position: canvas && canvas.contentHeight > 0 ? canvas.scrollY / canvas.contentHeight : 0
                            onPositionChanged: if (pressed) canvas.scrollY = position * canvas.contentHeight
                        }

                        // Suchen und ersetzen (Strg+F)
                        Rectangle {
                            id: findBar
                            objectName: "slidesFindBar"
                            property bool replacing: false
                            function show() {
                                visible = true
                                findField.forceActiveFocus()
                                findField.selectAll()
                            }
                            function hide() {
                                visible = false
                                view.back()
                            }
                            visible: false
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.rightMargin: 16
                            anchors.topMargin: 12
                            width: 400
                            height: findColumn.implicitHeight + 12
                            radius: Metrics.radiusOverlay
                            color: Theme.flyout
                            border.color: Theme.flyoutStroke
                            PShadow { radius: Metrics.radiusOverlay }
                            ColumnLayout {
                                id: findColumn
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 4
                                RowLayout {
                                    spacing: 4
                                    PIconButton {
                                        iconName: findBar.replacing ? "chevron_down" : "chevron_right"
                                        tip: I18n.tr("Ersetzen", I18n.revision)
                                        onClicked: findBar.replacing = !findBar.replacing
                                    }
                                    PTextField {
                                        id: findField
                                        objectName: "slidesFindField"
                                        Layout.fillWidth: true
                                        preferredWidth: 180
                                        placeholderText: I18n.tr("Suchen in der Präsentation", I18n.revision)
                                        onSubmitted: view.doc.find(text, false)
                                        Keys.onEscapePressed: findBar.hide()
                                    }
                                    PText { text: I18n.tr(view.doc ? view.doc.findResult : "", I18n.revision); textStyle: "caption"; tone: "secondary" }
                                    PIconButton { iconName: "chevron_up"; tip: I18n.tr("Vorheriger Treffer", I18n.revision); onClicked: view.doc.find(findField.text, true) }
                                    PIconButton { iconName: "chevron_down"; tip: I18n.tr("Nächster Treffer", I18n.revision); onClicked: view.doc.find(findField.text, false) }
                                    PIconButton { iconName: "dismiss"; tip: I18n.tr("Schließen", I18n.revision); onClicked: findBar.hide() }
                                }
                                RowLayout {
                                    visible: findBar.replacing
                                    spacing: 4
                                    Item { implicitWidth: 32 }
                                    PTextField {
                                        id: replaceField
                                        objectName: "slidesReplaceField"
                                        Layout.fillWidth: true
                                        preferredWidth: 140
                                        placeholderText: I18n.tr("Ersetzen durch", I18n.revision)
                                        onSubmitted: view.doc.replace(findField.text, text, false)
                                        Keys.onEscapePressed: findBar.hide()
                                    }
                                    PButton { text: I18n.tr("Ersetzen", I18n.revision); onClicked: view.doc.replace(findField.text, replaceField.text, false) }
                                    PButton { text: I18n.tr("Alle", I18n.revision); tip: I18n.tr("Alle Treffer ersetzen", I18n.revision); onClicked: view.doc.replace(findField.text, replaceField.text, true) }
                                }
                            }
                        }

                        // Textkern startet bzw. speichert
                        PProgressBar {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            indeterminate: true
                            visible: view.doc !== null && (!view.doc.ready || view.doc.saving)
                        }
                    }

                    // Notizen unter der Folie (wie im Entwurf): so breit wie die Folie, darin der Notizenrahmen
                    // der gezeigten Folie aus dem Textkern
                    Item {
                        objectName: "slidesNotesArea"
                        visible: view.doc !== null && view.doc.notesOpen
                        Layout.fillWidth: true
                        Layout.preferredHeight: 118
                        Rectangle {
                            id: notesBox
                            objectName: "slidesNotesBox"
                            anchors.centerIn: parent
                            width: Math.min(parent.width - 32, Math.max(320, canvas.contentWidth))
                            height: parent.height - 14
                            radius: Metrics.radiusControl
                            color: Theme.layer
                            border.color: Theme.divider
                            PText {
                                id: notesTitle
                                x: 12
                                y: 6
                                text: I18n.tr("Notizen", I18n.revision)
                                textStyle: "caption"
                                tone: "secondary"
                            }
                            TextCanvas {
                                id: notesCanvas
                                objectName: "slidesNotesCanvas"
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: notesTitle.bottom
                                anchors.bottom: parent.bottom
                                anchors.margins: 1
                                anchors.topMargin: 2
                                controller: view.doc ? view.doc.notes : null
                                pixelRatio: Screen.devicePixelRatio
                                backgroundColor: Theme.layer
                                paperColor: Theme.layer
                                caretColor: Theme.textPrimary
                                selectionColor: Theme.dark ? "#5A4CA0E0" : "#4D0078D4"
                                accentColor: view.kindColor
                                onWidthChanged: if (view.doc) view.doc.notes.fit(width)
                                Component.onCompleted: if (view.doc) view.doc.notes.fit(width)
                            }
                        }
                    }
                }
            }

            // Folienleiste rechts, der Streifen mit den Symbolen am Fensterrand (wie bei Texten und PDFs) ---------
            Rectangle {
                objectName: "slidesPanel"
                Layout.fillHeight: true
                Layout.preferredWidth: Metrics.readerLeftPanelWidth
                visible: view.doc !== null && view.doc.panel !== ""
                color: Theme.layer
                Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider; z: 1 }
                PanelHeader {
                    id: panelHeader
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 1
                    title: I18n.tr(view.doc && view.doc.panel === "layouts" ? "Layouts" : "Folien", I18n.revision)
                    onCloseRequested: { view.doc.togglePanel(view.doc.panel); view.back() }
                }

                // Folien mit Nummer und Bild (die gezeigte ist umrandet)
                ListView {
                    id: slideList
                    objectName: "slidesList"
                    visible: view.doc !== null && view.doc.panel === "slides"
                    anchors.top: panelHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 13
                    anchors.rightMargin: 12
                    anchors.topMargin: 10
                    clip: true
                    spacing: 10
                    model: view.doc ? view.doc.slideCount : 0
                    currentIndex: view.doc ? view.doc.slideIndex : 0
                    delegate: Item {
                        id: slideItem
                        required property int index
                        readonly property bool current: view.doc !== null && view.doc.slideIndex === index
                        objectName: "slidesThumb_" + index
                        width: slideList.width
                        height: Math.round((width - 24) * 9 / 16) + 2
                        PText {
                            id: number
                            width: 16
                            anchors.left: parent.left
                            anchors.top: parent.top
                            anchors.topMargin: 14
                            horizontalAlignment: Text.AlignRight
                            text: I18n.tr(String(slideItem.index + 1), I18n.revision)
                            textStyle: "caption"
                            tone: "secondary"
                        }
                        Rectangle {
                            anchors.left: number.right
                            anchors.leftMargin: 8
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            color: "#FFFFFF"
                            border.width: slideItem.current ? 2 : 1
                            border.color: slideItem.current ? view.kindColor : Theme.controlStroke
                            SlideImage {
                                anchors.fill: parent
                                anchors.margins: slideItem.current ? 2 : 1
                                controller: view.doc
                                part: slideItem.index
                                revision: view.doc ? view.doc.slideRevision : 0
                                pixelRatio: Screen.devicePixelRatio
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: { view.doc.goSlide(slideItem.index); view.back() }
                            }
                        }
                    }
                }

                // Layouts
                ColumnLayout {
                    visible: view.doc !== null && view.doc.panel === "layouts"
                    anchors.top: panelHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 13
                    anchors.rightMargin: 12
                    anchors.topMargin: 12
                    spacing: 6
                    Repeater {
                        model: view.doc ? view.doc.layoutList() : []
                        PButton {
                            required property var modelData
                            required property int index
                            objectName: "slidesLayout_" + index
                            Layout.fillWidth: true
                            kind: "subtle"
                            text: I18n.tr(modelData.label, I18n.revision)
                            enabled: view.ready
                            onClicked: { view.doc.setLayout(modelData.value); view.back() }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            SideRail {
                objectName: "slidesSideRail"
                Layout.fillHeight: true
                Layout.preferredWidth: Metrics.readerRailWidth
                current: view.doc !== null ? view.doc.panel : ""
                accentColor: view.kindColor
                items: [
                    { key: "slides", icon: "document_one_page_multiple", tip: "Folien", name: "slidesRailSlides" },
                    { key: "layouts", icon: "document_bullet_list", tip: "Layouts", name: "slidesRailLayouts" },
                    { key: "notes", icon: "comment", tip: "Notizen ein- oder ausblenden", name: "slidesRailNotes" },
                    { key: "search", icon: "search", tip: "Suchen und ersetzen (Strg+F)", name: "slidesRailSearch", separator: true }
                ]
                onSelected: (key) => {
                    if (!view.doc) return
                    if (key === "notes") { view.doc.toggleNotes(); view.back() }
                    else if (key === "search") findBar.show()
                    else { view.doc.togglePanel(key); view.back() }
                }
            }
        }
    }

    // Vorführen: Vollbild, nur die Folie auf schwarzem Grund ----------------------------------------------------------
    Window {
        id: showWindow
        objectName: "slidesShowWindow"
        visibility: view.doc !== null && view.doc.presenting ? Window.FullScreen : Window.Hidden
        color: "#000000"
        title: view.doc ? view.doc.name : ""
        onVisibleChanged: if (visible) showItem.forceActiveFocus()
        FocusScope {
            id: showItem
            anchors.fill: parent
            focus: true
            SlideImage {
                objectName: "slidesShowImage"
                anchors.centerIn: parent
                readonly property real ratio: view.doc && view.doc.docHeight > 0 ? view.doc.docWidth / view.doc.docHeight : 16 / 9
                width: Math.min(parent.width, parent.height * ratio)
                height: Math.round(width / ratio)
                controller: view.doc
                part: view.doc ? view.doc.presentIndex : 0
                revision: view.doc ? view.doc.slideRevision : 0
                pixelRatio: Screen.devicePixelRatio
            }
            PText {
                objectName: "slidesShowCounter"
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 16
                text: I18n.tr(view.doc ? (view.doc.presentIndex + 1) + " / " + view.doc.slideCount : "", I18n.revision)
                color: "#8A8A8A"
                textStyle: "caption"
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: (mouse) => view.doc.presentStep(mouse.button === Qt.RightButton ? -1 : 1)
            }
            Keys.onPressed: (event) => {
                if (event.key === Qt.Key_Escape) view.doc.endPresent()
                else if (event.key === Qt.Key_Left || event.key === Qt.Key_Up || event.key === Qt.Key_PageUp || event.key === Qt.Key_Backspace) view.doc.presentStep(-1)
                else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down || event.key === Qt.Key_PageDown || event.key === Qt.Key_Space || event.key === Qt.Key_Return) view.doc.presentStep(1)
                else return
                event.accepted = true
            }
        }
    }

    // Menüs und Flyouts ----------------------------------------------------------------------------------------------
    T.Popup {
        id: colorFlyout
        objectName: "slidesColorFlyout"
        parent: colorButton
        y: colorButton.height + 4
        padding: 12
        width: 232
        implicitHeight: contentHeight + topPadding + bottomPadding
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent
        onClosed: view.back()
        background: Rectangle {
            color: Theme.flyout
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusOverlay
            PShadow { radius: Metrics.radiusOverlay }
        }
        contentItem: ColumnLayout {
            spacing: 8
            PText { text: I18n.tr("Schriftfarbe", I18n.revision); textStyle: "caption"; tone: "secondary" }
            Flow {
                Layout.fillWidth: true
                spacing: 2
                Repeater {
                    model: view.swatches
                    PSwatch {
                        required property var modelData
                        size: 32
                        swatchColor: modelData
                        tip: I18n.tr(modelData, I18n.revision)
                        selected: view.doc !== null && view.doc.fontColor.toUpperCase() === modelData
                        onClicked: { view.doc.setFontColor(modelData); colorFlyout.close() }
                    }
                }
            }
            PButton { text: I18n.tr("Automatisch", I18n.revision); kind: "subtle"; onClicked: { view.doc.setFontColor(""); colorFlyout.close() } }
        }
    }
    PMenu {
        id: layoutMenu
        objectName: "slidesLayoutMenu"
        Repeater {
            model: view.doc ? view.doc.layoutList() : []
            PMenuItem {
                required property var modelData
                text: I18n.tr(modelData.label, I18n.revision)
                iconName: "layout_column_two"
                onTriggered: { view.doc.setLayout(modelData.value); view.back() }
            }
        }
    }
    PMenu {
        id: shapeMenu
        objectName: "slidesShapeMenu"
        Repeater {
            model: view.doc ? view.doc.shapeList() : []
            PMenuItem {
                required property var modelData
                text: I18n.tr(modelData.label, I18n.revision)
                iconName: "shapes"
                onTriggered: { view.doc.insertShape(modelData.key); view.back() }
            }
        }
    }
    PMenu {
        id: tableMenu
        objectName: "slidesTableMenu"
        Repeater {
            model: [[2, 2], [3, 3], [4, 3], [5, 4], [8, 5]]
            PMenuItem {
                required property var modelData
                text: I18n.tr(modelData[0] + " Zeilen × " + modelData[1] + " Spalten", I18n.revision)
                iconName: "table_simple"
                onTriggered: { view.doc.insertTable(modelData[0], modelData[1]); view.back() }
            }
        }
    }
    PMenu {
        id: slideMenu
        objectName: "slidesContextMenu"
        onClosed: view.back()
        PMenuItem { text: I18n.tr("Ausschneiden", I18n.revision); hint: I18n.tr("Strg+X", I18n.revision); iconName: "cut"; enabled: view.ready && view.doc.canCopy; onTriggered: view.doc.cut() }
        PMenuItem { text: I18n.tr("Kopieren", I18n.revision); hint: I18n.tr("Strg+C", I18n.revision); iconName: "copy"; enabled: view.ready && view.doc.canCopy; onTriggered: view.doc.copy() }
        PMenuItem { text: I18n.tr("Einfügen", I18n.revision); hint: I18n.tr("Strg+V", I18n.revision); iconName: "clipboard_paste"; onTriggered: view.doc.paste() }
        PMenuItem { text: I18n.tr("Nur den Text einfügen", I18n.revision); hint: I18n.tr("Strg+Umschalt+V", I18n.revision); iconName: "clipboard_paste"; onTriggered: view.doc.pastePlain() }
        PMenuItem { text: I18n.tr("Alles auswählen", I18n.revision); hint: I18n.tr("Strg+A", I18n.revision); iconName: "select_all_on"; onTriggered: view.doc.selectAll() }
        T.MenuSeparator {
            topPadding: 4
            bottomPadding: 4
            contentItem: Rectangle { implicitWidth: 200; implicitHeight: 1; color: Theme.divider }
        }
        PMenuItem { text: I18n.tr("Neue Folie", I18n.revision); iconName: "document_add"; onTriggered: view.doc.newSlide() }
        PMenuItem { text: I18n.tr("Folie duplizieren", I18n.revision); iconName: "copy"; onTriggered: view.doc.duplicateSlide() }
        PMenuItem { text: I18n.tr("Folie löschen", I18n.revision); iconName: "delete"; onTriggered: view.doc.deleteSlide() }
    }

    // Tastenkürzel (Strg+C/X/V/Z/Y/A, Formate und Bewegen nimmt der Zeichenbereich selbst)
    Shortcut { sequences: Shortcuts.keys["reader.save"] || []; enabled: view.active; onActivated: view.doc.saveNow() }
    Shortcut { sequences: Shortcuts.keys["reader.saveAs"] || []; enabled: view.active; onActivated: view.doc.saveAs() }
    Shortcut { sequences: Shortcuts.keys["reader.print"] || []; enabled: view.active; onActivated: view.doc.printText() }
    Shortcut { sequences: Shortcuts.keys["reader.zoomIn"] || []; enabled: view.active; onActivated: view.doc.zoomStep(1) }
    Shortcut { sequences: Shortcuts.keys["reader.zoomOut"] || []; enabled: view.active; onActivated: view.doc.zoomStep(-1) }
    Shortcut { sequences: Shortcuts.keys["reader.nextTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(1) }
    Shortcut { sequences: Shortcuts.keys["reader.previousTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(-1) }
    Shortcut { sequences: ["F5"]; enabled: view.active; onActivated: view.doc.present() }
    Shortcut { sequences: ["Escape"]; enabled: view.active && findBar.visible; onActivated: findBar.hide() }
}
