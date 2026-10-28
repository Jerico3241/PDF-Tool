import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Tabelle bearbeiten (seit 5.0 Beta 2, nach dem freigegebenen Design): oben die Reiter Datei, Start, Einfügen,
// Formeln, Daten, Überprüfen (seit Beta 5) und Ansicht (der aktive grün unterstrichen) mit Speichern, Drucken, Rückgängig, »Übersicht
// erstellen« und »Als PDF speichern« rechts; darunter die Leiste des Reiters, die Formelzeile (Namenfeld, fx,
// Eingabe), das Raster (SheetGrid) mit Editor, Diagrammen und Filtermenü und unten die Blätter. Summe und Anzahl
// der Auswahl stehen in der Statuszeile des Fensters.
FocusScope {
    id: view
    objectName: "sheetView"
    property var sheet: null
    property string ribbon: "start"
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open && sheet !== null
    readonly property color kindColor: FileKinds.color("tabelle")
    // Bearbeiten einer Zelle: »« (nicht), »cell« (im Raster) oder »bar« (in der Formelzeile)
    property string editing: ""
    property bool enterMode: false  // mit Tippen begonnen: Pfeiltasten übernehmen und gehen weiter (wie Excel)
    property int refStart: -1       // Zeigemodus: Lage und Länge des zuletzt eingefügten Bezugs
    property int refLength: 0
    readonly property var fonts: ["Calibri", "Arial", "Segoe UI", "Aptos", "Cambria", "Times New Roman", "Courier New", "Verdana", "Tahoma", "Georgia"]
    readonly property var sizes: [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 36, 48, 72]
    readonly property var swatches: ["#000000", "#FFFFFF", "#E7E6E6", "#44546A", "#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47",
                                    "#7F7F7F", "#F2F2F2", "#D0CECE", "#D6DCE4", "#D9E1F2", "#FCE4D6", "#EDEDED", "#FFF2CC", "#DDEBF7", "#E2EFDA",
                                    "#C00000", "#FF0000", "#FFC7CE", "#FFEB9C", "#C6EFCE", "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0"]

    onSheetChanged: {
        view.cancelEdit()
        if (sheet) grid.forceActiveFocus()
    }

    // Bearbeiten ---------------------------------------------------------------------------------------------------
    function beginEdit(text, typed) {
        if (!sheet) return
        editor.text = typed ? text : (text !== "" ? text : sheet.cellInput)
        enterMode = typed
        refStart = -1
        editing = "cell"
        editor.forceActiveFocus()
        editor.cursorPosition = editor.text.length
    }
    function commitEdit(dr, dc) {
        if (editing === "" || !sheet) return
        var text = editing === "bar" ? formulaField.text : editor.text
        editing = ""
        refStart = -1
        sheet.commit(text, dr, dc)
        grid.forceActiveFocus()
    }
    function cancelEdit() {
        editing = ""
        refStart = -1
        formulaField.text = Qt.binding(function() { return view.sheet ? view.sheet.cellInput : "" })
        if (sheet) grid.forceActiveFocus()
    }
    // Zeigemodus: Formel, und vor der Einfügemarke steht ein Operator, »(« oder »;«
    readonly property bool pointing: {
        if (editing === "") return false
        var field = editing === "bar" ? formulaField : editor
        var text = field.text
        if (text.charAt(0) !== "=") return false
        if (refStart >= 0) return true
        var before = text.substring(0, field.cursorPosition).replace(/\s+$/, "")
        return /[=(;+\-*\/^&<>:]$/.test(before)
    }
    function insertReference(text, replace) {
        var field = editing === "bar" ? formulaField : editor
        var value = field.text
        if (replace && refStart >= 0) {
            field.text = value.substring(0, refStart) + text + value.substring(refStart + refLength)
        } else {
            var at = field.cursorPosition
            refStart = at
            field.text = value.substring(0, at) + text + value.substring(at)
        }
        refLength = text.length
        field.cursorPosition = refStart + refLength
        field.forceActiveFocus()
    }
    function insertFunction(name) {
        if (!sheet) return
        if (editing === "") beginEdit("=" + name + "(", true)
        else {
            var field = editing === "bar" ? formulaField : editor
            var at = field.cursorPosition
            var prefix = field.text === "" ? "=" : ""
            field.text = field.text.substring(0, at) + prefix + name + "(" + field.text.substring(at)
            field.cursorPosition = at + prefix.length + name.length + 1
            field.forceActiveFocus()
        }
        enterMode = false
    }

    Connections {
        target: view.sheet
        function onEditRequested(text) { view.beginEdit(text, text !== "") }
        function onEditEmptyRequested() { view.beginEdit("", true) }
        function onFindRequested() { findBar.show() }
        function onFilterMenuChanged() {
            if (view.sheet && view.sheet.filterMenu.col !== undefined) filterPopup.openFor(view.sheet.filterMenu)
        }
        function onActiveSheetChanged() { view.cancelEdit() }
    }

    // Leisten: kleine Bausteine ---------------------------------------------------------------------------------------
    // Schaltfläche der Leiste: Symbol und (optional) Text, ohne Fläche
    component ToolButton: PButton {
        kind: "subtle"
        leftPadding: text === "" ? 0 : 8
        rightPadding: text === "" ? 0 : 10
        enabled: view.sheet !== null && view.sheet.ready
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Reiter und Befehle rechts -----------------------------------------------------------------------------
        Rectangle {
            objectName: "sheetRibbonTabs"
            Layout.fillWidth: true
            implicitHeight: 38
            color: Theme.layer
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                RibbonTab { objectName: "ribbon_file"; key: "file"; text: "Datei"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_start"; key: "start"; text: "Start"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_insert"; key: "insert"; text: "Einfügen"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_formulas"; key: "formulas"; text: "Formeln"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_data"; key: "data"; text: "Daten"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_review"; key: "review"; text: "Überprüfen"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                RibbonTab { objectName: "ribbon_view"; key: "view"; text: "Ansicht"; current: view.ribbon; kindColor: view.kindColor; onClicked: view.ribbon = key }
                Item { Layout.fillWidth: true }
                PIconButton {
                    objectName: "sheetSave"
                    iconName: "save"
                    tip: I18n.tr("Speichern" + Shortcuts.hints["reader.save"], I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready && !view.sheet.saving
                    busy: view.sheet !== null && view.sheet.saving
                    onClicked: view.sheet.saveNow()
                }
                PIconButton {
                    objectName: "sheetPrint"
                    iconName: "print"
                    tip: I18n.tr("Drucken" + Shortcuts.hints["reader.print"], I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready
                    onClicked: view.sheet.printSheet()
                }
                PIconButton {
                    objectName: "sheetUndo"
                    iconName: "arrow_undo"
                    tip: I18n.tr((view.sheet && view.sheet.undoText ? "Rückgängig: " + view.sheet.undoText : "Rückgängig") + Shortcuts.hints["reader.undo"], I18n.revision)
                    enabled: view.sheet !== null && view.sheet.undoText !== ""
                    onClicked: view.sheet.undo()
                }
                RibbonSeparator {}
                PButton {
                    objectName: "sheetOverview"
                    kind: "link"
                    iconName: "document_table"
                    text: I18n.tr("Übersicht erstellen", I18n.revision)
                    tip: I18n.tr("Aus dieser Tabelle eine Vertragsübersicht erstellen", I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready
                    onClicked: view.sheet.createOverview()
                }
                PButton {
                    objectName: "sheetPdf"
                    kind: "link"
                    iconName: "document_pdf"
                    text: I18n.tr("Als PDF speichern", I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready
                    onClicked: pdfMenu.popup(this, 0, height + 4)
                }
            }
        }

        // Leiste des Reiters -------------------------------------------------------------------------------------
        Rectangle {
            objectName: "sheetToolbar"
            Layout.fillWidth: true
            implicitHeight: 46
            color: Theme.layer
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.divider }

            // Start (wie im Design): Einfügen, Schrift, F, K, Format, Summe, Sortieren, Filter, Diagramm
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                anchors.bottomMargin: 1
                spacing: 2
                objectName: "sheetRibbonBar_start"
                visible: view.ribbon === "start"
                ToolButton {
                    objectName: "sheetPaste"
                    iconName: "clipboard_paste"
                    text: I18n.tr("Einfügen", I18n.revision)
                    tip: I18n.tr("Einfügen (Strg+V)", I18n.revision)
                    onClicked: { view.sheet.paste(); grid.forceActiveFocus() }
                }
                RibbonSeparator {}
                PComboBox {
                    id: fontBox
                    objectName: "sheetFont"
                    preferredWidth: 118
                    label: I18n.tr("Schriftart", I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready
                    model: {
                        var current = view.sheet && view.sheet.cellStyle.font ? view.sheet.cellStyle.font : "Calibri"
                        return view.fonts.indexOf(current) >= 0 ? view.fonts : [current].concat(view.fonts)
                    }
                    currentIndex: {
                        var current = view.sheet && view.sheet.cellStyle.font ? view.sheet.cellStyle.font : "Calibri"
                        return Math.max(0, model.indexOf(current))
                    }
                    onActivated: (index) => { view.sheet.setFormat("font", model[index]); grid.forceActiveFocus() }
                }
                ToolButton {
                    objectName: "sheetBold"
                    iconName: "text_bold"
                    tip: I18n.tr("Fett (Strg+B)", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.cellStyle.bold === true
                    onClicked: { view.sheet.toggle("bold"); grid.forceActiveFocus() }
                }
                ToolButton {
                    objectName: "sheetItalic"
                    iconName: "text_italic"
                    tip: I18n.tr("Kursiv (Strg+I)", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.cellStyle.italic === true
                    onClicked: { view.sheet.toggle("italic"); grid.forceActiveFocus() }
                }
                ToolButton {
                    id: formatButton
                    objectName: "sheetFormat"
                    iconName: "color"
                    tip: I18n.tr("Format: Farben, Zahlenformat, Rahmen, Ausrichtung", I18n.revision)
                    toggle: true
                    checked: formatFlyout.opened
                    onClicked: formatFlyout.opened ? formatFlyout.close() : formatFlyout.open()
                }
                RibbonSeparator {}
                ToolButton {
                    objectName: "sheetSum"
                    iconName: "add"
                    text: I18n.tr("Summe", I18n.revision)
                    tip: I18n.tr("Summe der Zahlen darüber bzw. links (Alt+=)", I18n.revision)
                    onClicked: view.sheet.autoSum("SUMME")
                }
                ToolButton {
                    id: sortButton
                    objectName: "sheetSort"
                    iconName: "arrow_sort"
                    text: I18n.tr("Sortieren", I18n.revision)
                    onClicked: sortMenu.popup(sortButton, 0, sortButton.height + 4)
                }
                ToolButton {
                    objectName: "sheetFilter"
                    iconName: "filter"
                    text: I18n.tr("Filter", I18n.revision)
                    tip: I18n.tr("Filter ein- oder ausschalten", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.filterOn
                    onClicked: view.sheet.toggleFilter()
                }
                ToolButton {
                    id: conditionalButton
                    objectName: "sheetConditional"
                    iconName: "paint_brush"
                    text: I18n.tr("Bedingte Formatierung", I18n.revision)
                    tip: I18n.tr("Zellen je nach Wert hervorheben oder Datenbalken zeigen", I18n.revision)
                    onClicked: conditionalMenu.popup(conditionalButton, 0, conditionalButton.height + 4)
                }
                RibbonSeparator {}
                ToolButton {
                    id: chartButton
                    objectName: "sheetChart"
                    iconName: "grid"
                    text: I18n.tr("Diagramm", I18n.revision)
                    tip: I18n.tr("Diagramm aus der Auswahl", I18n.revision)
                    onClicked: chartMenu.popup(chartButton, 0, chartButton.height + 4)
                }
                Item { Layout.fillWidth: true }
            }

            // Datei
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_file"
                visible: view.ribbon === "file"
                ToolButton { objectName: "sheetFileNew"; iconName: "document_add"; text: I18n.tr("Neue Tabelle", I18n.revision); tip: I18n.tr("Neue Tabelle" + Shortcuts.hints["app.new"], I18n.revision); enabled: true; onClicked: Reader.newSheet() }
                ToolButton { iconName: "folder_open"; text: I18n.tr("Öffnen", I18n.revision); enabled: true; onClicked: Reader.openDialog() }
                RibbonSeparator {}
                ToolButton { iconName: "save"; text: I18n.tr("Speichern", I18n.revision); onClicked: view.sheet.saveNow() }
                ToolButton { objectName: "sheetSaveAs"; iconName: "save"; text: I18n.tr("Speichern unter …", I18n.revision); onClicked: view.sheet.saveAs() }
                ToolButton { iconName: "document_pdf"; text: I18n.tr("Als PDF speichern …", I18n.revision); onClicked: pdfMenu.popup(this, 0, height + 4) }
                ToolButton { iconName: "print"; text: I18n.tr("Drucken", I18n.revision); onClicked: view.sheet.printSheet() }
                RibbonSeparator {}
                ToolButton { iconName: "mail"; text: I18n.tr("Per E-Mail senden", I18n.revision); onClicked: Reader.sendByMail() }
                ToolButton { iconName: "folder"; text: I18n.tr("Ordner öffnen", I18n.revision); enabled: view.sheet !== null && view.sheet.path !== ""; onClicked: Reader.showInFolder(view.sheet.path) }
                ToolButton { iconName: "dismiss"; text: I18n.tr("Schließen", I18n.revision); onClicked: Reader.closeCurrent() }
                Item { Layout.fillWidth: true }
            }

            // Einfügen
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_insert"
                visible: view.ribbon === "insert"
                ToolButton { objectName: "sheetInsertRows"; iconName: "table_insert_row"; text: I18n.tr("Zeilen", I18n.revision); tip: I18n.tr("Zeilen über der Auswahl einfügen", I18n.revision); onClicked: view.sheet.insertCells("rows", false) }
                ToolButton { objectName: "sheetInsertCols"; iconName: "table_insert_column"; text: I18n.tr("Spalten", I18n.revision); tip: I18n.tr("Spalten links der Auswahl einfügen", I18n.revision); onClicked: view.sheet.insertCells("cols", false) }
                ToolButton { iconName: "table_delete_row"; text: I18n.tr("Zeilen löschen", I18n.revision); onClicked: view.sheet.insertCells("rows", true) }
                ToolButton { iconName: "table_delete_column"; text: I18n.tr("Spalten löschen", I18n.revision); onClicked: view.sheet.insertCells("cols", true) }
                RibbonSeparator {}
                ToolButton { iconName: "data_bar_vertical"; text: I18n.tr("Säulen", I18n.revision); onClicked: view.sheet.addChart("column") }
                ToolButton { iconName: "data_bar_horizontal"; text: I18n.tr("Balken", I18n.revision); onClicked: view.sheet.addChart("bar") }
                ToolButton { iconName: "data_line"; text: I18n.tr("Linie", I18n.revision); onClicked: view.sheet.addChart("line") }
                ToolButton { iconName: "data_pie"; text: I18n.tr("Kreis", I18n.revision); onClicked: view.sheet.addChart("pie") }
                ToolButton { iconName: "data_area"; text: I18n.tr("Fläche", I18n.revision); onClicked: view.sheet.addChart("area") }
                RibbonSeparator {}
                ToolButton { objectName: "sheetAddSheet"; iconName: "table_add"; text: I18n.tr("Blatt", I18n.revision); tip: I18n.tr("Neues Tabellenblatt", I18n.revision); onClicked: view.sheet.addSheet() }
                Item { Layout.fillWidth: true }
            }

            // Formeln
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_formulas"
                visible: view.ribbon === "formulas"
                ToolButton { objectName: "sheetFunctions"; iconName: "math_formula"; text: I18n.tr("Funktion einfügen", I18n.revision); tip: I18n.tr("Funktions-Assistent (Umschalt+F3)", I18n.revision); onClicked: functionDialog.openDialog() }
                RibbonSeparator {}
                ToolButton { iconName: "autosum"; text: I18n.tr("Summe", I18n.revision); onClicked: view.sheet.autoSum("SUMME") }
                ToolButton { text: I18n.tr("Mittelwert", I18n.revision); onClicked: view.sheet.autoSum("MITTELWERT") }
                ToolButton { text: I18n.tr("Anzahl", I18n.revision); onClicked: view.sheet.autoSum("ANZAHL") }
                ToolButton { text: I18n.tr("Max", I18n.revision); onClicked: view.sheet.autoSum("MAX") }
                ToolButton { text: I18n.tr("Min", I18n.revision); onClicked: view.sheet.autoSum("MIN") }
                RibbonSeparator {}
                ToolButton { text: I18n.tr("WENN", I18n.revision); onClicked: view.insertFunction("WENN") }
                ToolButton { text: I18n.tr("SVERWEIS", I18n.revision); onClicked: view.insertFunction("SVERWEIS") }
                ToolButton { text: I18n.tr("HEUTE", I18n.revision); onClicked: view.insertFunction("HEUTE") }
                Item { Layout.fillWidth: true }
            }

            // Daten
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_data"
                visible: view.ribbon === "data"
                ToolButton { objectName: "sheetSortUp"; iconName: "text_sort_ascending"; tip: I18n.tr("Sortieren von A bis Z", I18n.revision); onClicked: view.sheet.sort(true) }
                ToolButton { iconName: "text_sort_descending"; tip: I18n.tr("Sortieren von Z bis A", I18n.revision); onClicked: view.sheet.sort(false) }
                ToolButton { iconName: "filter"; text: I18n.tr("Filter", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.filterOn; onClicked: view.sheet.toggleFilter() }
                RibbonSeparator {}
                ToolButton { objectName: "sheetDuplicates"; iconName: "copy_select"; text: I18n.tr("Duplikate entfernen", I18n.revision); tip: I18n.tr("Doppelte Zeilen der Tabelle entfernen", I18n.revision); onClicked: view.sheet.removeDuplicates() }
                ToolButton { objectName: "sheetTextColumns"; iconName: "text_column_two"; text: I18n.tr("Text in Spalten", I18n.revision); tip: I18n.tr("Texte an einem Trennzeichen auf Spalten verteilen", I18n.revision); onClicked: view.sheet.textToColumns() }
                ToolButton { objectName: "sheetFlashFill"; iconName: "flash"; text: I18n.tr("Blitzvorschau", I18n.revision); tip: I18n.tr("Spalte nach dem Muster der Beispiele ausfüllen (Strg+E)", I18n.revision); onClicked: { view.sheet.flashFill(); grid.forceActiveFocus() } }
                ToolButton { objectName: "sheetValidation"; iconName: "shield_task"; text: I18n.tr("Datenüberprüfung", I18n.revision); tip: I18n.tr("Erlaubte Eingaben festlegen, z. B. eine Auswahlliste", I18n.revision); onClicked: view.sheet.validationDialog() }
                RibbonSeparator {}
                ToolButton { objectName: "sheetPivot"; iconName: "table_settings"; text: I18n.tr("Pivot-Tabelle", I18n.revision); tip: I18n.tr("Daten zusammenfassen: Pivot-Tabelle auf einem neuen Blatt", I18n.revision); onClicked: view.sheet.pivotDialog() }
                ToolButton { objectName: "sheetPivotRefresh"; iconName: "arrow_sync"; tip: I18n.tr("Pivot-Tabellen aktualisieren", I18n.revision); onClicked: view.sheet.refreshPivots() }
                RibbonSeparator {}
                ToolButton { id: combineButton; objectName: "sheetCombine"; iconName: "arrow_join"; text: I18n.tr("Zusammenführen", I18n.revision); tip: I18n.tr("Blätter und Mappen teilen oder zusammenführen", I18n.revision); onClicked: combineMenu.popup(combineButton, 0, combineButton.height + 4) }
                RibbonSeparator {}
                ToolButton { id: fillButton; iconName: "arrow_autofit_content"; tip: I18n.tr("Ausfüllen", I18n.revision); onClicked: fillMenu.popup(fillButton, 0, fillButton.height + 4) }
                ToolButton { iconName: "search"; tip: I18n.tr("Suchen (Strg+F)", I18n.revision); onClicked: findBar.show() }
                Item { Layout.fillWidth: true }
            }

            // Überprüfen: Schutz und Kennwort
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_review"
                visible: view.ribbon === "review"
                ToolButton {
                    objectName: "sheetProtect"
                    iconName: "shield_lock"
                    text: I18n.tr(view.sheet && view.sheet.sheetProtected ? "Blattschutz aufheben" : "Blatt schützen", I18n.revision)
                    tip: I18n.tr("Inhalte und Formate dieses Blatts vor Änderungen schützen", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.sheetProtected
                    onClicked: view.sheet.protectSheet()
                }
                ToolButton {
                    objectName: "sheetProtectBook"
                    iconName: "document_lock"
                    text: I18n.tr(view.sheet && view.sheet.bookProtected ? "Mappenschutz aufheben" : "Mappe schützen", I18n.revision)
                    tip: I18n.tr("Blätter vor Einfügen, Löschen, Umbenennen und Verschieben schützen", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.bookProtected
                    onClicked: view.sheet.protectBook()
                }
                ToolButton {
                    objectName: "sheetEncrypt"
                    iconName: "key"
                    text: I18n.tr("Mit Kennwort verschlüsseln", I18n.revision)
                    tip: I18n.tr("Die Datei lässt sich nur mit Kennwort öffnen", I18n.revision)
                    toggle: true
                    checked: view.sheet !== null && view.sheet.encrypted
                    onClicked: view.sheet.encrypt()
                }
                RibbonSeparator {}
                ToolButton { objectName: "sheetUnlockCells"; iconName: "table_lightning"; text: I18n.tr("Zellen freigeben", I18n.revision); tip: I18n.tr("Ausgewählte Zellen bleiben bei geschütztem Blatt bearbeitbar", I18n.revision); onClicked: view.sheet.lockCells(false) }
                ToolButton { objectName: "sheetLockCells"; iconName: "lock_closed"; text: I18n.tr("Zellen sperren", I18n.revision); tip: I18n.tr("Ausgewählte Zellen wieder sperren (Standard)", I18n.revision); onClicked: view.sheet.lockCells(true) }
                RibbonSeparator {}
                ToolButton { iconName: "shield_task"; text: I18n.tr("Datenüberprüfung", I18n.revision); onClicked: view.sheet.validationDialog() }
                Item { Layout.fillWidth: true }
            }

            // Ansicht
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                objectName: "sheetRibbonBar_view"
                visible: view.ribbon === "view"
                ToolButton { objectName: "sheetFreezeRow"; iconName: "table_freeze_row"; text: I18n.tr("Oberste Zeile fixieren", I18n.revision); onClicked: view.sheet.freezePanes("row") }
                ToolButton { iconName: "table_freeze_column"; text: I18n.tr("Erste Spalte fixieren", I18n.revision); onClicked: view.sheet.freezePanes("col") }
                ToolButton { iconName: "table_freeze_column_and_row"; text: I18n.tr("An der Zelle fixieren", I18n.revision); onClicked: view.sheet.freezePanes("cursor") }
                ToolButton { text: I18n.tr("Aufheben", I18n.revision); enabled: view.sheet !== null && (view.sheet.freeze[0] > 0 || view.sheet.freeze[1] > 0); onClicked: view.sheet.freezePanes("none") }
                RibbonSeparator {}
                ToolButton { objectName: "sheetCrosshair"; iconName: "target"; text: I18n.tr("Lese-Kreuz", I18n.revision); tip: I18n.tr("Zeile und Spalte der aktiven Zelle hervorheben", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.crosshair; onClicked: { view.sheet.toggleCrosshair(); grid.forceActiveFocus() } }
                RibbonSeparator {}
                ToolButton { iconName: "zoom_out"; tip: I18n.tr("Verkleinern", I18n.revision); onClicked: view.sheet.zoomStep(-1) }
                ToolButton { text: view.sheet ? view.sheet.zoom + " %" : ""; tip: I18n.tr("Zoom auf 100 %", I18n.revision); onClicked: view.sheet.setZoom(100) }
                ToolButton { iconName: "zoom_in"; tip: I18n.tr("Vergrößern", I18n.revision); onClicked: view.sheet.zoomStep(1) }
                RibbonSeparator {}
                ToolButton { id: printAreaButton; objectName: "sheetPrintArea"; iconName: "print_add"; text: I18n.tr("Druckbereich", I18n.revision); tip: I18n.tr("Nur die Auswahl drucken bzw. wieder alles", I18n.revision); onClicked: printAreaMenu.popup(printAreaButton, 0, printAreaButton.height + 4) }
                Item { Layout.fillWidth: true }
            }
        }

        // Formelzeile ----------------------------------------------------------------------------------------------
        Rectangle {
            objectName: "sheetFormulaBar"
            Layout.fillWidth: true
            implicitHeight: 40
            color: Theme.layer
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 8
                Rectangle {
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 28
                    radius: Metrics.radiusControl
                    color: Theme.control
                    border.width: 1
                    border.color: nameBox.activeFocus ? Theme.accent : Theme.controlStroke
                    TextInput {
                        id: nameBox
                        objectName: "sheetNameBox"
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 4
                        verticalAlignment: TextInput.AlignVCenter
                        font: Typography.body
                        color: Theme.textPrimary
                        selectByMouse: true
                        clip: true
                        text: view.sheet ? view.sheet.cellName : ""
                        onActiveFocusChanged: if (activeFocus) selectAll()
                        Keys.onEscapePressed: { text = Qt.binding(function() { return view.sheet ? view.sheet.cellName : "" }); grid.forceActiveFocus() }
                        onAccepted: {
                            if (view.sheet && view.sheet.goToName(text)) grid.forceActiveFocus()
                            text = Qt.binding(function() { return view.sheet ? view.sheet.cellName : "" })
                        }
                    }
                }
                T.AbstractButton {
                    objectName: "sheetFx"
                    Layout.preferredWidth: 24
                    Layout.preferredHeight: 28
                    hoverEnabled: true
                    Accessible.name: I18n.tr("Funktion einfügen", I18n.revision)
                    onClicked: functionDialog.openDialog()
                    contentItem: Text {
                        text: "fx"
                        font.family: Typography.family
                        font.pixelSize: 15
                        font.italic: true
                        color: parent.hovered ? Theme.textPrimary : Theme.textSecondary
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    PToolTip { text: I18n.tr("Funktion einfügen", I18n.revision); visible: parent.hovered }
                }
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 28
                    radius: Metrics.radiusControl
                    color: Theme.control
                    border.width: 1
                    border.color: formulaField.activeFocus ? Theme.accent : Theme.controlStroke
                    TextInput {
                        id: formulaField
                        objectName: "sheetFormulaField"
                        anchors.fill: parent
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        verticalAlignment: TextInput.AlignVCenter
                        font: Typography.body
                        color: Theme.textPrimary
                        selectByMouse: true
                        clip: true
                        enabled: view.sheet !== null && view.sheet.ready
                        text: view.editing === "cell" ? editor.text : (view.sheet ? view.sheet.cellInput : "")
                        onActiveFocusChanged: {
                            if (activeFocus && view.editing === "") {
                                view.enterMode = false
                                view.editing = "bar"
                            }
                        }
                        onTextEdited: if (view.editing === "cell") editor.text = text
                        Keys.onPressed: (event) => {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                view.commitEdit((event.modifiers & Qt.ShiftModifier) ? -1 : 1, 0)
                                event.accepted = true
                            } else if (event.key === Qt.Key_Tab) {
                                view.commitEdit(0, 1)
                                event.accepted = true
                            } else if (event.key === Qt.Key_Escape) {
                                view.cancelEdit()
                                event.accepted = true
                            }
                        }
                    }
                }
            }
        }

        // Raster mit Editor, Diagrammen und Bildlaufleisten --------------------------------------------------------
        Item {
            id: gridArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            SheetGrid {
                id: grid
                objectName: "sheetGrid"
                anchors.left: parent.left
                anchors.top: parent.top
                width: parent.width - vbar.width
                height: parent.height - hbar.height
                controller: view.sheet
                focus: true
                pointMode: view.pointing
                headerColor: Theme.surfaceSecondary
                headerTextColor: Theme.textSecondary
                headerLineColor: Theme.divider
                lineColor: Theme.dark ? "#3A3A3A" : "#E1E1E1"
                paperColor: Theme.dark ? "#1F1F1F" : "#FFFFFF"
                textColor: Theme.dark ? "#F0F0F0" : "#000000"
                accentColor: Theme.dark ? "#4CA0E0" : "#1F5FBF"
                selectedHeaderColor: Theme.dark ? "#2D3B4D" : "#E3ECF7"
                selectedHeaderTextColor: Theme.accentText
                onReferencePicked: (text, replace) => view.insertReference(text, replace)
                onContextMenuRequested: (x, y, area) => {
                    if (view.editing !== "") view.commitEdit(0, 0)
                    cellMenu.area = area
                    cellMenu.popup(grid, x, y)
                }
                onFilterButtonClicked: (col, x, y) => {
                    filterPopup.x = Math.min(x, gridArea.width - filterPopup.width - 8)
                    filterPopup.y = y + 2
                    view.sheet.openFilter(col)
                }
                // Klick ins Raster beendet die Eingabe (außer im Zeigemodus)
                onActiveFocusChanged: if (activeFocus && view.editing !== "" && !view.pointing) view.commitEdit(0, 0)
                Keys.onPressed: (event) => {
                    if (event.key === Qt.Key_Equal && (event.modifiers & Qt.AltModifier)) {
                        view.sheet.autoSum("SUMME")
                        event.accepted = true
                    } else if (event.key === Qt.Key_F3 && (event.modifiers & Qt.ShiftModifier)) {
                        functionDialog.openDialog()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Down && (event.modifiers & Qt.AltModifier) && listButton.items.length > 0) {
                        listPopup.open()
                        event.accepted = true
                    } else if (event.key === Qt.Key_Delete && chartLayer.selected >= 0) {
                        view.sheet.deleteObject(chartLayer.selected)
                        chartLayer.selected = -1
                        event.accepted = true
                    }
                }
            }

            // Diagramme und Bilder des Blatts: anklicken, verschieben, Größe ändern, Entf löscht
            Item {
                id: chartLayer
                anchors.fill: grid
                clip: true
                property int selected: -1
                Repeater {
                    model: view.sheet ? view.sheet.objects : []
                    Item {
                        id: chart
                        required property var modelData
                        required property int index
                        objectName: "sheetObject_" + index
                        readonly property rect place: { grid.viewRevision; return grid.objectRect(modelData.px, modelData.py, modelData.pw, modelData.ph) }
                        property real dx: 0
                        property real dy: 0
                        property real dw: 0
                        property real dh: 0
                        x: place.x + dx
                        y: place.y + dy
                        width: Math.max(24, place.width + dw)
                        height: Math.max(24, place.height + dh)
                        Rectangle { anchors.fill: parent; color: grid.paperColor; border.width: 1; border.color: Theme.divider; visible: chart.modelData.image === "" }
                        PProgressRing { anchors.centerIn: parent; size: 20; running: visible; visible: chart.modelData.image === "" }
                        Image {
                            anchors.fill: parent
                            source: chart.modelData.image
                            fillMode: Image.Stretch
                            smooth: true
                            asynchronous: true
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: 2
                            border.color: grid.accentColor
                            visible: chartLayer.selected === chart.index
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            cursorShape: chartLayer.selected === chart.index ? Qt.SizeAllCursor : Qt.ArrowCursor
                            property point start
                            onPressed: (mouse) => {
                                chartLayer.selected = chart.index
                                grid.forceActiveFocus()
                                start = mapToItem(chartLayer, mouse.x, mouse.y)
                                if (mouse.button === Qt.RightButton) {
                                    objectMenu.index = chart.index
                                    objectMenu.name = chart.modelData.name
                                    objectMenu.chart = chart.modelData.kind === "chart"
                                    objectMenu.popup()
                                }
                            }
                            onPositionChanged: (mouse) => {
                                if (!pressed || mouse.buttons !== Qt.LeftButton) return
                                var now = mapToItem(chartLayer, mouse.x, mouse.y)
                                chart.dx = now.x - start.x
                                chart.dy = now.y - start.y
                            }
                            onReleased: (mouse) => {
                                if (mouse.button !== Qt.LeftButton || (Math.abs(chart.dx) < 2 && Math.abs(chart.dy) < 2)) {
                                    chart.dx = 0
                                    chart.dy = 0
                                    return
                                }
                                view.moveObject(chart)
                            }
                        }
                        // Anfasser unten rechts: Größe ändern
                        Rectangle {
                            width: 10
                            height: 10
                            x: parent.width - 5
                            y: parent.height - 5
                            color: grid.paperColor
                            border.width: 1
                            border.color: grid.accentColor
                            visible: chartLayer.selected === chart.index
                            MouseArea {
                                anchors.fill: parent
                                anchors.margins: -4
                                cursorShape: Qt.SizeFDiagCursor
                                property point start
                                onPressed: (mouse) => start = mapToItem(chartLayer, mouse.x, mouse.y)
                                onPositionChanged: (mouse) => {
                                    var now = mapToItem(chartLayer, mouse.x, mouse.y)
                                    chart.dw = now.x - start.x
                                    chart.dh = now.y - start.y
                                }
                                onReleased: view.moveObject(chart)
                            }
                        }
                    }
                }
            }

            // Editor über der aktiven Zelle
            Rectangle {
                id: editorFrame
                objectName: "sheetEditor"
                readonly property rect cell: { if (!grid) return Qt.rect(0, 0, 0, 0); grid.viewRevision; return view.sheet ? (view.sheet.cursorRow, view.sheet.cursorCol, grid.cellRect(view.sheet.cursorRow, view.sheet.cursorCol)) : Qt.rect(0, 0, 0, 0) }
                visible: view.editing === "cell"
                x: cell.x - 1
                y: cell.y - 1
                width: Math.max(cell.width + 2, Math.min(gridArea.width - x - 4, editor.contentWidth + 16))
                height: Math.max(cell.height + 2, editor.contentHeight + 6)
                color: grid ? grid.paperColor : "white"
                border.width: 2
                border.color: grid ? grid.accentColor : "transparent"
                TextInput {
                    id: editor
                    anchors.fill: parent
                    anchors.leftMargin: 4
                    anchors.rightMargin: 4
                    verticalAlignment: TextInput.AlignVCenter
                    font.family: view.sheet && view.sheet.cellStyle.font ? view.sheet.cellStyle.font : "Calibri"
                    font.pixelSize: Math.max(8, Math.round((view.sheet && view.sheet.cellStyle.size ? view.sheet.cellStyle.size : 11) * 96 / 72 * (view.sheet ? view.sheet.zoom : 100) / 100))
                    font.bold: view.sheet !== null && view.sheet.cellStyle.bold === true
                    font.italic: view.sheet !== null && view.sheet.cellStyle.italic === true
                    color: grid ? grid.textColor : "black"
                    selectByMouse: true
                    clip: true
                    onTextEdited: view.refStart = -1
                    Keys.onPressed: (event) => {
                        var shift = (event.modifiers & Qt.ShiftModifier) !== 0
                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                            if (event.modifiers & Qt.AltModifier) return
                            view.commitEdit(shift ? -1 : 1, 0)
                        } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
                            view.commitEdit(0, shift || event.key === Qt.Key_Backtab ? -1 : 1)
                        } else if (event.key === Qt.Key_Escape) {
                            view.cancelEdit()
                        } else if (event.key === Qt.Key_F2) {
                            view.enterMode = !view.enterMode
                        } else if (view.enterMode && !view.pointing && (event.key === Qt.Key_Up || event.key === Qt.Key_Down || event.key === Qt.Key_Left || event.key === Qt.Key_Right)) {
                            view.commitEdit(event.key === Qt.Key_Up ? -1 : (event.key === Qt.Key_Down ? 1 : 0), event.key === Qt.Key_Left ? -1 : (event.key === Qt.Key_Right ? 1 : 0))
                        } else {
                            return
                        }
                        event.accepted = true
                    }
                }
            }

            // Auswahlliste der Datenüberprüfung: Pfeil rechts neben der aktiven Zelle
            T.AbstractButton {
                id: listButton
                objectName: "sheetListButton"
                readonly property var items: view.sheet && view.sheet.validation.kind === "list" && view.sheet.validation.dropdown !== false ? (view.sheet.validation.items || []) : []
                readonly property rect cell: { grid.viewRevision; return view.sheet ? (view.sheet.cursorRow, view.sheet.cursorCol, grid.cellRect(view.sheet.cursorRow, view.sheet.cursorCol)) : Qt.rect(0, 0, 0, 0) }
                visible: items.length > 0 && view.editing === "" && cell.width > 0 && cell.x + cell.width < grid.width
                x: cell.x + cell.width + 1
                y: cell.y + cell.height - height
                width: 18
                height: Math.min(22, Math.max(16, cell.height))
                hoverEnabled: true
                Accessible.name: I18n.tr("Auswahlliste", I18n.revision)
                onClicked: listPopup.open()
                background: Rectangle { color: listButton.hovered ? Theme.subtleHover : grid.paperColor; border.width: 1; border.color: Theme.controlStroke }
                contentItem: PIcon { name: "chevron_down"; size: 12; color: Theme.textSecondary; anchors.centerIn: parent }
                PToolTip { text: I18n.tr("Eintrag aus der Liste wählen", I18n.revision); visible: listButton.hovered }
            }
            T.Popup {
                id: listPopup
                objectName: "sheetListPopup"
                parent: gridArea
                x: Math.max(0, Math.min(listButton.cell.x, gridArea.width - width - 8))
                y: listButton.cell.y + listButton.cell.height + 2
                width: Math.max(160, listButton.cell.width + listButton.width)
                padding: 4
                implicitHeight: Math.min(260, listView.contentHeight) + topPadding + bottomPadding
                focus: true
                closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
                onClosed: grid.forceActiveFocus()
                // andere Zelle oder anderes Blatt: Liste zu (sonst bliebe sie an der alten Stelle stehen)
                Connections {
                    target: view.sheet
                    function onCursorRowChanged() { listPopup.close() }
                    function onCursorColChanged() { listPopup.close() }
                    function onActiveSheetChanged() { listPopup.close() }
                }
                background: Rectangle {
                    color: Theme.flyout
                    border.color: Theme.flyoutStroke
                    radius: Metrics.radiusOverlay
                    PShadow { radius: Metrics.radiusOverlay }
                }
                contentItem: ListView {
                    id: listView
                    clip: true
                    model: listButton.items
                    T.ScrollBar.vertical: PScrollBar {}
                    delegate: T.ItemDelegate {
                        required property var modelData
                        required property int index
                        objectName: "sheetListItem_" + index
                        width: ListView.view.width
                        height: 30
                        hoverEnabled: true
                        onClicked: { var text = String(modelData); listPopup.close(); view.sheet.chooseListItem(text) }
                        background: Rectangle { radius: Metrics.radiusControl; color: parent.hovered ? Theme.subtleHover : "transparent" }
                        contentItem: PText { text: String(parent.modelData); leftPadding: 8; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                    }
                }
            }

            PScrollBar {
                id: vbar
                objectName: "sheetVScroll"
                orientation: Qt.Vertical
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: hbar.top
                policy: T.ScrollBar.AlwaysOn
                size: grid && grid.contentHeight > 0 ? Math.min(1, grid.viewHeight / (grid.contentHeight + grid.viewHeight * 0.0001)) : 1
                position: grid && grid.contentHeight > 0 ? grid.scrollY / grid.contentHeight : 0
                onPositionChanged: if (pressed) grid.scrollY = position * grid.contentHeight
            }
            PScrollBar {
                id: hbar
                objectName: "sheetHScroll"
                orientation: Qt.Horizontal
                anchors.left: parent.left
                anchors.right: vbar.left
                anchors.bottom: parent.bottom
                policy: T.ScrollBar.AlwaysOn
                size: grid && grid.contentWidth > 0 ? Math.min(1, grid.viewWidth / grid.contentWidth) : 1
                position: grid && grid.contentWidth > 0 ? grid.scrollX / grid.contentWidth : 0
                onPositionChanged: if (pressed) grid.scrollX = position * grid.contentWidth
            }

            // Suchleiste (Strg+F)
            Rectangle {
                id: findBar
                objectName: "sheetFindBar"
                function show() {
                    visible = true
                    findField.forceActiveFocus()
                    findField.selectAll()
                }
                visible: false
                anchors.right: vbar.left
                anchors.top: parent.top
                anchors.rightMargin: 16
                anchors.topMargin: 32
                width: 360
                height: 44
                radius: Metrics.radiusOverlay
                color: Theme.flyout
                border.color: Theme.flyoutStroke
                PShadow { radius: Metrics.radiusOverlay }
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 4
                    PTextField {
                        id: findField
                        objectName: "sheetFindField"
                        Layout.fillWidth: true
                        preferredWidth: 180
                        placeholderText: I18n.tr("Suchen in der Tabelle", I18n.revision)
                        onSubmitted: view.sheet.find(text, false)
                        Keys.onEscapePressed: { findBar.visible = false; grid.forceActiveFocus() }
                    }
                    PText { text: I18n.tr(view.sheet ? view.sheet.findResult : "", I18n.revision); textStyle: "caption"; tone: "secondary" }
                    PIconButton { iconName: "chevron_up"; tip: I18n.tr("Vorheriger Treffer", I18n.revision); onClicked: view.sheet.find(findField.text, true) }
                    PIconButton { iconName: "chevron_down"; tip: I18n.tr("Nächster Treffer", I18n.revision); onClicked: view.sheet.find(findField.text, false) }
                    PIconButton { iconName: "dismiss"; tip: I18n.tr("Schließen", I18n.revision); onClicked: { findBar.visible = false; grid.forceActiveFocus() } }
                }
            }

            // Rechenkern startet bzw. arbeitet
            PProgressBar {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                indeterminate: true
                visible: view.sheet !== null && (view.sheet.busy || !view.sheet.ready)
            }
        }

        // Blätter ------------------------------------------------------------------------------------------------------
        Rectangle {
            objectName: "sheetTabs"
            Layout.fillWidth: true
            implicitHeight: 36
            color: Theme.layer
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 1; color: Theme.divider }
            Row {
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Repeater {
                    model: view.sheet ? view.sheet.sheets : []
                    T.AbstractButton {
                        id: sheetTab
                        required property var modelData
                        required property int index
                        readonly property bool selected: view.sheet !== null && view.sheet.activeSheet === index
                        objectName: "sheetTab_" + index
                        visible: modelData.visible !== false
                        implicitHeight: 28
                        implicitWidth: tabRow.implicitWidth + 26
                        hoverEnabled: true
                        Accessible.role: Accessible.PageTab
                        Accessible.name: I18n.tr(modelData.name, I18n.revision)
                        Accessible.selected: selected
                        onClicked: { view.commitEdit(0, 0); view.sheet.activateSheet(index); grid.forceActiveFocus() }
                        onDoubleClicked: view.sheet.renameSheet(index)
                        background: Rectangle {
                            radius: Metrics.radiusControl
                            color: sheetTab.selected ? Theme.surface : (sheetTab.hovered ? Theme.subtleHover : "transparent")
                            border.width: sheetTab.selected ? 1 : 0
                            border.color: Theme.border
                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.margins: 3
                                height: 2
                                radius: 1
                                color: sheetTab.modelData.color || "transparent"
                                visible: !!sheetTab.modelData.color
                            }
                        }
                        contentItem: Item {}
                        Row {
                            id: tabRow
                            anchors.centerIn: parent
                            spacing: 4
                            // geschütztes Blatt: Schloss vor dem Namen
                            PIcon { name: sheetTab.modelData.protected ? "lock_closed" : ""; size: 12; color: Theme.textSecondary; anchors.verticalCenter: parent.verticalCenter }
                            Text {
                                id: tabLabel
                                text: sheetTab.modelData.name
                                font: sheetTab.selected ? Typography.bodyStrong : Typography.body
                                color: sheetTab.selected ? Theme.textPrimary : Theme.textSecondary
                                textFormat: Text.PlainText
                            }
                        }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: {
                                sheetMenu.index = sheetTab.index
                                sheetMenu.popup()
                            }
                        }
                    }
                }
                PIconButton {
                    objectName: "sheetTabAdd"
                    implicitWidth: 28
                    implicitHeight: 28
                    iconName: "add"
                    tip: I18n.tr("Neues Tabellenblatt", I18n.revision)
                    enabled: view.sheet !== null && view.sheet.ready
                    onClicked: view.sheet.addSheet()
                }
            }
        }
    }

    function moveObject(chart) {
        var point = grid.sheetPoint(chart.x, chart.y)
        var zoom = view.sheet.zoom / 100
        view.sheet.moveObject(chart.index, point[0], point[1], chart.width / zoom, chart.height / zoom)
        chart.dx = 0
        chart.dy = 0
        chart.dw = 0
        chart.dh = 0
    }

    // Menüs ----------------------------------------------------------------------------------------------------------
    PMenu {
        id: pdfMenu
        objectName: "sheetPdfMenu"
        PMenuItem { text: I18n.tr("Alle Blätter", I18n.revision); iconName: "document_multiple"; onTriggered: pdfMenu.afterClose = function() { view.sheet.exportPdf("all") } }
        PMenuItem { text: I18n.tr("Nur dieses Blatt", I18n.revision); iconName: "document"; onTriggered: pdfMenu.afterClose = function() { view.sheet.exportPdf("sheet") } }
        PMenuItem { text: I18n.tr("Nur die Auswahl", I18n.revision); iconName: "select_all_on"; onTriggered: pdfMenu.afterClose = function() { view.sheet.exportPdf("selection") } }
    }
    PMenu {
        id: sortMenu
        PMenuItem { objectName: "sheetSortAsc"; text: I18n.tr("Aufsteigend (A bis Z, 1 bis 9)", I18n.revision); iconName: "text_sort_ascending"; onTriggered: view.sheet.sort(true) }
        PMenuItem { text: I18n.tr("Absteigend (Z bis A, 9 bis 1)", I18n.revision); iconName: "text_sort_descending"; onTriggered: view.sheet.sort(false) }
    }
    PMenu {
        id: chartMenu
        PMenuItem { text: I18n.tr("Säulen", I18n.revision); iconName: "data_bar_vertical"; onTriggered: view.sheet.addChart("column") }
        PMenuItem { text: I18n.tr("Balken", I18n.revision); iconName: "data_bar_horizontal"; onTriggered: view.sheet.addChart("bar") }
        PMenuItem { text: I18n.tr("Linie", I18n.revision); iconName: "data_line"; onTriggered: view.sheet.addChart("line") }
        PMenuItem { text: I18n.tr("Kreis", I18n.revision); iconName: "data_pie"; onTriggered: view.sheet.addChart("pie") }
        PMenuItem { text: I18n.tr("Fläche", I18n.revision); iconName: "data_area"; onTriggered: view.sheet.addChart("area") }
    }
    PMenu {
        id: conditionalMenu
        objectName: "sheetConditionalMenu"
        PMenuItem { text: I18n.tr("Größer als …", I18n.revision); iconName: "highlight"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("greater") } }
        PMenuItem { text: I18n.tr("Kleiner als …", I18n.revision); iconName: "highlight"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("less") } }
        PMenuItem { text: I18n.tr("Zwischen …", I18n.revision); iconName: "highlight"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("between") } }
        PMenuItem { text: I18n.tr("Gleich …", I18n.revision); iconName: "highlight"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("equal") } }
        PMenuItem { text: I18n.tr("Text enthält …", I18n.revision); iconName: "highlight"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("contains") } }
        PMenuItem { text: I18n.tr("Doppelte Werte …", I18n.revision); iconName: "copy_select"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("duplicate") } }
        PMenuItem { text: I18n.tr("Obere 10 …", I18n.revision); iconName: "chevron_up"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("top") } }
        PMenuItem { text: I18n.tr("Untere 10 …", I18n.revision); iconName: "chevron_down"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("bottom") } }
        PMenuItem { text: I18n.tr("Über dem Durchschnitt …", I18n.revision); iconName: "data_bar_vertical"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("above") } }
        PMenuItem { text: I18n.tr("Unter dem Durchschnitt …", I18n.revision); iconName: "data_bar_vertical"; onTriggered: conditionalMenu.afterClose = function() { view.sheet.conditional("below") } }
        PMenuItem { objectName: "sheetBarBlue"; text: I18n.tr("Datenbalken blau", I18n.revision); iconName: "data_bar_horizontal"; onTriggered: view.sheet.conditional("bar_blue") }
        PMenuItem { text: I18n.tr("Datenbalken grün", I18n.revision); iconName: "data_bar_horizontal"; onTriggered: view.sheet.conditional("bar_green") }
        PMenuItem { text: I18n.tr("Datenbalken rot", I18n.revision); iconName: "data_bar_horizontal"; onTriggered: view.sheet.conditional("bar_red") }
        PMenuItem { text: I18n.tr("Regeln der Auswahl löschen", I18n.revision); iconName: "eraser"; onTriggered: view.sheet.clearConditional("selection") }
        PMenuItem { text: I18n.tr("Regeln des Blatts löschen", I18n.revision); iconName: "delete"; onTriggered: view.sheet.clearConditional("sheet") }
    }
    PMenu {
        id: combineMenu
        objectName: "sheetCombineMenu"
        PMenuItem { text: I18n.tr("Blatt nach Spalte teilen …", I18n.revision); iconName: "arrow_split"; onTriggered: combineMenu.afterClose = function() { view.sheet.splitSheet() } }
        PMenuItem { text: I18n.tr("Blätter zusammenführen …", I18n.revision); iconName: "arrow_join"; onTriggered: combineMenu.afterClose = function() { view.sheet.mergeSheets() } }
        PMenuItem { text: I18n.tr("Jedes Blatt als eigene Mappe …", I18n.revision); iconName: "document_multiple"; onTriggered: combineMenu.afterClose = function() { view.sheet.exportSheets() } }
        PMenuItem { text: I18n.tr("Mappen anfügen …", I18n.revision); iconName: "table_add"; onTriggered: combineMenu.afterClose = function() { view.sheet.importBook() } }
    }
    PMenu {
        id: printAreaMenu
        PMenuItem { text: I18n.tr("Druckbereich festlegen", I18n.revision); iconName: "print_add"; onTriggered: view.sheet.setPrintArea(true) }
        PMenuItem { text: I18n.tr("Druckbereich aufheben", I18n.revision); iconName: "dismiss"; onTriggered: view.sheet.setPrintArea(false) }
    }
    PMenu {
        id: fillMenu
        PMenuItem { text: I18n.tr("Nach unten ausfüllen", I18n.revision); hint: "Strg+U"; iconName: "chevron_down"; onTriggered: view.sheet.fill("down") }
        PMenuItem { text: I18n.tr("Nach rechts ausfüllen", I18n.revision); hint: "Strg+R"; iconName: "arrow_right"; onTriggered: view.sheet.fill("right") }
        PMenuItem { text: I18n.tr("Blitzvorschau", I18n.revision); hint: "Strg+E"; iconName: "flash"; onTriggered: view.sheet.flashFill() }
    }
    PMenu {
        id: objectMenu
        property int index: -1
        property string name: ""
        property bool chart: false
        PMenuItem { text: I18n.tr("Als Säulen", I18n.revision); iconName: "data_bar_vertical"; visible: objectMenu.chart; onTriggered: view.sheet.chartType(objectMenu.name, "column") }
        PMenuItem { text: I18n.tr("Als Balken", I18n.revision); iconName: "data_bar_horizontal"; visible: objectMenu.chart; onTriggered: view.sheet.chartType(objectMenu.name, "bar") }
        PMenuItem { text: I18n.tr("Als Linie", I18n.revision); iconName: "data_line"; visible: objectMenu.chart; onTriggered: view.sheet.chartType(objectMenu.name, "line") }
        PMenuItem { text: I18n.tr("Als Kreis", I18n.revision); iconName: "data_pie"; visible: objectMenu.chart; onTriggered: view.sheet.chartType(objectMenu.name, "pie") }
        PMenuItem { text: I18n.tr("Als Fläche", I18n.revision); iconName: "data_area"; visible: objectMenu.chart; onTriggered: view.sheet.chartType(objectMenu.name, "area") }
        PMenuItem { text: I18n.tr("Löschen", I18n.revision); iconName: "delete"; onTriggered: { view.sheet.deleteObject(objectMenu.index); chartLayer.selected = -1 } }
    }
    PMenu {
        id: cellMenu
        objectName: "sheetCellMenu"
        property string area: "cell"
        PMenuItem { text: I18n.tr("Ausschneiden", I18n.revision); hint: "Strg+X"; iconName: "cut"; onTriggered: view.sheet.cut() }
        PMenuItem { text: I18n.tr("Kopieren", I18n.revision); hint: "Strg+C"; iconName: "copy"; onTriggered: view.sheet.copy() }
        PMenuItem { text: I18n.tr("Einfügen", I18n.revision); hint: "Strg+V"; iconName: "clipboard_paste"; onTriggered: view.sheet.paste() }
        PMenuItem { text: I18n.tr("Inhalte löschen", I18n.revision); hint: "Entf"; iconName: "eraser"; onTriggered: view.sheet.clearContents() }
        PMenuItem { text: I18n.tr("Formate löschen", I18n.revision); iconName: "text_edit_style"; onTriggered: view.sheet.clear("formats") }
        PMenuItem { text: I18n.tr(cellMenu.area === "cols" ? "Spalten einfügen" : "Zeilen einfügen", I18n.revision); iconName: cellMenu.area === "cols" ? "table_insert_column" : "table_insert_row"; onTriggered: view.sheet.insertCells(cellMenu.area === "cols" ? "cols" : "rows", false) }
        PMenuItem { text: I18n.tr(cellMenu.area === "cols" ? "Spalten löschen" : "Zeilen löschen", I18n.revision); iconName: cellMenu.area === "cols" ? "table_delete_column" : "table_delete_row"; onTriggered: view.sheet.insertCells(cellMenu.area === "cols" ? "cols" : "rows", true) }
        PMenuItem { text: I18n.tr("Spalten einfügen", I18n.revision); iconName: "table_insert_column"; visible: cellMenu.area === "cell"; onTriggered: view.sheet.insertCells("cols", false) }
        PMenuItem { text: I18n.tr("Optimale Breite", I18n.revision); iconName: "arrow_autofit_width"; visible: cellMenu.area === "cols"; onTriggered: view.sheet.autoFit("cols", view.sheet.selection[1]) }
        PMenuItem { text: I18n.tr("Optimale Höhe", I18n.revision); iconName: "arrow_autofit_content"; visible: cellMenu.area === "rows"; onTriggered: view.sheet.autoFit("rows", view.sheet.selection[0]) }
        PMenuItem { text: I18n.tr("Ausblenden", I18n.revision); iconName: "eye_off"; visible: cellMenu.area !== "cell"; onTriggered: view.sheet.hideCells(cellMenu.area, true) }
        PMenuItem { text: I18n.tr("Einblenden", I18n.revision); iconName: "eye"; visible: cellMenu.area !== "cell"; onTriggered: view.sheet.hideCells(cellMenu.area, false) }
        PMenuItem { text: I18n.tr("Sortieren (A bis Z)", I18n.revision); iconName: "text_sort_ascending"; visible: cellMenu.area === "cell"; onTriggered: view.sheet.sort(true) }
        PMenuItem { text: I18n.tr(view.sheet && view.sheet.merged ? "Verbindung aufheben" : "Verbinden und zentrieren", I18n.revision); iconName: "table_cells_merge"; visible: cellMenu.area === "cell"; onTriggered: view.sheet.toggleMerge() }
        PMenuItem { text: I18n.tr("Zellen formatieren …", I18n.revision); iconName: "color"; onTriggered: cellMenu.afterClose = function() { formatFlyout.open() } }
    }
    PMenu {
        id: sheetMenu
        objectName: "sheetTabMenu"
        property int index: -1
        PMenuItem { text: I18n.tr("Umbenennen …", I18n.revision); iconName: "edit"; onTriggered: { var i = sheetMenu.index; sheetMenu.afterClose = function() { view.sheet.renameSheet(i) } } }
        PMenuItem { text: I18n.tr("Neues Blatt", I18n.revision); iconName: "add"; onTriggered: view.sheet.addSheet() }
        PMenuItem { text: I18n.tr("Nach links verschieben", I18n.revision); iconName: "chevron_left"; enabled: sheetMenu.index > 0; onTriggered: view.sheet.moveSheet(sheetMenu.index, sheetMenu.index - 1) }
        PMenuItem { text: I18n.tr("Nach rechts verschieben", I18n.revision); iconName: "chevron_right"; enabled: view.sheet !== null && sheetMenu.index < view.sheet.sheets.length - 1; onTriggered: view.sheet.moveSheet(sheetMenu.index, sheetMenu.index + 1) }
        PMenuItem { text: I18n.tr("Löschen …", I18n.revision); iconName: "delete"; enabled: view.sheet !== null && view.sheet.sheets.length > 1; onTriggered: { var i = sheetMenu.index; sheetMenu.afterClose = function() { view.sheet.deleteSheet(i) } } }
    }

    // Format: Schrift, Farben, Zahlenformat, Ausrichtung, Rahmen, Verbinden -------------------------------------------
    T.Popup {
        id: formatFlyout
        objectName: "sheetFormatFlyout"
        parent: formatButton
        y: formatButton.height + 4
        padding: 12
        width: 372
        implicitHeight: contentHeight + topPadding + bottomPadding
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent
        onClosed: grid.forceActiveFocus()
        background: Rectangle {
            color: Theme.flyout
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusOverlay
            PShadow { radius: Metrics.radiusOverlay }
        }
        component Swatches: Flow {
            id: swatches
            property string key: ""
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: view.swatches
                PSwatch {
                    required property var modelData
                    size: 30
                    swatchColor: modelData
                    tip: modelData
                    selected: view.sheet !== null && String(view.sheet.cellStyle[swatches.key] || "").toUpperCase() === modelData
                    onClicked: view.sheet.setFormat(swatches.key, modelData)
                }
            }
        }
        contentItem: ColumnLayout {
            spacing: 6
            RowLayout {
                spacing: 4
                PComboBox {
                    objectName: "sheetFontSize"
                    preferredWidth: 72
                    label: I18n.tr("Schriftgröße", I18n.revision)
                    model: view.sizes
                    currentIndex: Math.max(0, view.sizes.indexOf(Math.round(view.sheet && view.sheet.cellStyle.size ? view.sheet.cellStyle.size : 11)))
                    onActivated: (index) => view.sheet.setFormat("size", view.sizes[index])
                }
                PIconButton { iconName: "text_underline"; tip: I18n.tr("Unterstrichen (Strg+U)", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.underline === true; onClicked: view.sheet.toggle("underline") }
                PIconButton { iconName: "text_strikethrough"; tip: I18n.tr("Durchgestrichen", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.strike === true; onClicked: view.sheet.toggle("strike") }
                PIconButton { iconName: "text_wrap"; tip: I18n.tr("Zeilenumbruch", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.wrap === true; onClicked: view.sheet.toggle("wrap") }
                PIconButton { iconName: "table_cells_merge"; tip: I18n.tr("Verbinden und zentrieren", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.merged; onClicked: view.sheet.toggleMerge() }
            }
            RowLayout {
                spacing: 4
                PIconButton { iconName: "text_align_left"; tip: I18n.tr("Linksbündig", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.halign === "left"; onClicked: view.sheet.setFormat("halign", "left") }
                PIconButton { iconName: "text_align_center"; tip: I18n.tr("Zentriert", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.halign === "center"; onClicked: view.sheet.setFormat("halign", "center") }
                PIconButton { iconName: "text_align_right"; tip: I18n.tr("Rechtsbündig", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.halign === "right"; onClicked: view.sheet.setFormat("halign", "right") }
                Rectangle { width: 1; height: 20; color: Theme.divider }
                PIconButton { iconName: "align_top"; tip: I18n.tr("Oben", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.valign === "top"; onClicked: view.sheet.setFormat("valign", "top") }
                PIconButton { iconName: "align_center_vertical"; tip: I18n.tr("Mitte", I18n.revision); toggle: true; checked: view.sheet !== null && view.sheet.cellStyle.valign === "center"; onClicked: view.sheet.setFormat("valign", "center") }
                PIconButton { iconName: "align_bottom"; tip: I18n.tr("Unten", I18n.revision); toggle: true; checked: view.sheet !== null && (view.sheet.cellStyle.valign === "bottom" || !view.sheet.cellStyle.valign); onClicked: view.sheet.setFormat("valign", "bottom") }
            }
            PText { text: I18n.tr("Zahlenformat", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.topMargin: 4 }
            Flow {
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: [
                        { key: "standard", label: "Standard" }, { key: "number", label: "Zahl" }, { key: "currency", label: "Währung €" },
                        { key: "percent", label: "Prozent" }, { key: "date", label: "Datum" }, { key: "text", label: "Text" }
                    ]
                    PButton {
                        required property var modelData
                        objectName: "sheetNumber_" + modelData.key
                        kind: "subtle"
                        toggle: true
                        checked: view.sheet !== null && view.sheet.formatKind === modelData.key
                        text: I18n.tr(modelData.label, I18n.revision)
                        onClicked: view.sheet.numberFormat(modelData.key)
                    }
                }
                PIconButton { iconName: "decimal_arrow_left"; tip: I18n.tr("Weniger Dezimalstellen", I18n.revision); onClicked: view.sheet.decimals(-1) }
                PIconButton { iconName: "decimal_arrow_right"; tip: I18n.tr("Mehr Dezimalstellen", I18n.revision); onClicked: view.sheet.decimals(1) }
            }
            PText { text: I18n.tr("Rahmen", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.topMargin: 4 }
            Flow {
                Layout.fillWidth: true
                spacing: 2
                Repeater {
                    model: [
                        { key: "all", icon: "border_all", tip: "Alle Rahmenlinien" }, { key: "outer", icon: "border_outside", tip: "Rahmen außen" },
                        { key: "thick", icon: "border_outside_thick", tip: "Dicker Rahmen außen" }, { key: "top", icon: "border_top", tip: "Oben" },
                        { key: "bottom", icon: "border_bottom", tip: "Unten" }, { key: "left", icon: "border_left", tip: "Links" },
                        { key: "right", icon: "border_right", tip: "Rechts" }, { key: "none", icon: "border_none", tip: "Kein Rahmen" }
                    ]
                    PIconButton {
                        required property var modelData
                        objectName: "sheetBorder_" + modelData.key
                        iconName: modelData.icon
                        tip: I18n.tr(modelData.tip, I18n.revision)
                        onClicked: view.sheet.borders(modelData.key)
                    }
                }
            }
            PText { text: I18n.tr("Schriftfarbe", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.topMargin: 4 }
            Swatches { key: "color" }
            RowLayout {
                Layout.topMargin: 4
                PText { Layout.fillWidth: true; text: I18n.tr("Füllfarbe", I18n.revision); textStyle: "caption"; tone: "secondary" }
                PButton { kind: "subtle"; text: I18n.tr("Keine Füllung", I18n.revision); onClicked: view.sheet.setFormat("background", "") }
            }
            Swatches { key: "background" }
        }
    }

    // Filter einer Spalte: Werte zum Anhaken -------------------------------------------------------------------------
    T.Popup {
        id: filterPopup
        objectName: "sheetFilterPopup"
        parent: gridArea
        width: 260
        padding: 10
        implicitHeight: contentHeight + topPadding + bottomPadding
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
        property int col: -1
        property var values: []
        property var checks: ({})
        property string search: ""
        function openFor(menu) {
            col = menu.col
            values = menu.values || []
            var map = {}
            for (var i = 0; i < values.length; ++i) map[values[i].text] = values[i].checked !== false
            checks = map
            search = ""
            open()
        }
        onClosed: { if (view.sheet) view.sheet.filterMenu = ({}); grid.forceActiveFocus() }
        background: Rectangle {
            color: Theme.flyout
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusOverlay
            PShadow { radius: Metrics.radiusOverlay }
        }
        contentItem: ColumnLayout {
            spacing: 6
            PButton { Layout.fillWidth: true; kind: "subtle"; iconName: "text_sort_ascending"; text: I18n.tr("Aufsteigend sortieren", I18n.revision); onClicked: { view.sheet.select(view.sheet.cursorRow, filterPopup.col, false); view.sheet.sort(true); filterPopup.close() } }
            PButton { Layout.fillWidth: true; kind: "subtle"; iconName: "text_sort_descending"; text: I18n.tr("Absteigend sortieren", I18n.revision); onClicked: { view.sheet.select(view.sheet.cursorRow, filterPopup.col, false); view.sheet.sort(false); filterPopup.close() } }
            PTextField { Layout.fillWidth: true; preferredWidth: 200; placeholderText: I18n.tr("Suchen", I18n.revision); onTextChanged: filterPopup.search = text.toLowerCase() }
            PCheckBox {
                objectName: "sheetFilterAll"
                text: I18n.tr("(Alle auswählen)", I18n.revision)
                checked: { var all = true; for (var key in filterPopup.checks) if (!filterPopup.checks[key]) all = false; return all }
                onClicked: {
                    var map = {}
                    var value = !checked
                    for (var key in filterPopup.checks) map[key] = !value ? false : true
                    filterPopup.checks = map
                }
            }
            ListView {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(220, contentHeight)
                clip: true
                model: filterPopup.values.filter(function(entry) { return filterPopup.search === "" || String(entry.text).toLowerCase().indexOf(filterPopup.search) >= 0 })
                T.ScrollBar.vertical: PScrollBar {}
                delegate: PCheckBox {
                    required property var modelData
                    width: ListView.view.width
                    text: modelData.text === "" ? I18n.tr("(Leer)", I18n.revision) : modelData.text
                    checked: filterPopup.checks[modelData.text] === true
                    onClicked: {
                        var map = Object.assign({}, filterPopup.checks)
                        map[modelData.text] = !(filterPopup.checks[modelData.text] === true)
                        filterPopup.checks = map
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                Item { Layout.fillWidth: true }
                PButton {
                    objectName: "sheetFilterApply"
                    kind: "accent"
                    text: I18n.tr("OK", I18n.revision)
                    onClicked: {
                        var chosen = []
                        var all = true
                        for (var key in filterPopup.checks) {
                            if (filterPopup.checks[key]) chosen.push(key)
                            else all = false
                        }
                        var col = filterPopup.col
                        filterPopup.close()
                        view.sheet.applyFilter(col, all ? null : chosen)
                    }
                }
                PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: filterPopup.close() }
            }
        }
    }

    // Funktions-Assistent: Funktion suchen (deutsche Namen wie SUMME, SVERWEIS), Beschreibung und Argumente ------------
    T.Popup {
        id: functionDialog
        objectName: "sheetFunctionDialog"
        parent: view
        modal: true
        x: Math.round((view.width - width) / 2)
        y: 90
        width: Math.min(620, view.width - 40)
        height: Math.min(460, view.height - 120)
        padding: 16
        closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutside
        property string query: ""
        property string category: ""
        property int chosen: 0
        readonly property var categories: {
            var seen = []
            var list = view.sheet ? view.sheet.functionList : []
            for (var i = 0; i < list.length; ++i) if (seen.indexOf(list[i].category) < 0) seen.push(list[i].category)
            return seen.sort()
        }
        readonly property var matches: {
            var list = view.sheet ? view.sheet.functionList : []
            var q = query.toUpperCase()
            return list.filter(function(f) {
                return (category === "" || f.category === category) && (q === "" || f.name.indexOf(q) >= 0 || String(f.description).toUpperCase().indexOf(q) >= 0)
            })
        }
        readonly property var current: matches.length > 0 ? matches[Math.min(chosen, matches.length - 1)] : null
        function openDialog() {
            if (!view.sheet) return
            view.sheet.loadFunctions()
            query = ""
            category = ""
            chosen = 0
            open()
            functionSearch.forceActiveFocus()
        }
        function take() {
            if (!current) return
            var name = current.name
            close()
            view.insertFunction(name)
        }
        onClosed: if (view.editing === "") grid.forceActiveFocus()
        T.Overlay.modal: Rectangle { color: Theme.smoke }
        background: Rectangle {
            color: Theme.dialog
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusDialog
            PShadow { radius: Metrics.radiusDialog }
        }
        contentItem: ColumnLayout {
            spacing: 10
            PText { text: I18n.tr("Funktion einfügen", I18n.revision); textStyle: "subtitle" }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PTextField {
                    id: functionSearch
                    objectName: "sheetFunctionSearch"
                    Layout.fillWidth: true
                    preferredWidth: 240
                    placeholderText: I18n.tr("Funktion suchen, z. B. SUMME oder SVERWEIS", I18n.revision)
                    onTextChanged: { functionDialog.query = text; functionDialog.chosen = 0 }
                    onSubmitted: functionDialog.take()
                    Keys.onDownPressed: functionDialog.chosen = Math.min(functionDialog.chosen + 1, functionDialog.matches.length - 1)
                    Keys.onUpPressed: functionDialog.chosen = Math.max(0, functionDialog.chosen - 1)
                }
                PComboBox {
                    preferredWidth: 200
                    label: I18n.tr("Kategorie", I18n.revision)
                    model: ["Alle Kategorien"].concat(functionDialog.categories)
                    onActivated: (index) => { functionDialog.category = index === 0 ? "" : functionDialog.categories[index - 1]; functionDialog.chosen = 0 }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12
                ListView {
                    id: functionList
                    objectName: "sheetFunctionList"
                    Layout.preferredWidth: 200
                    Layout.fillHeight: true
                    clip: true
                    model: functionDialog.matches
                    currentIndex: functionDialog.chosen
                    T.ScrollBar.vertical: PScrollBar {}
                    delegate: T.ItemDelegate {
                        required property var modelData
                        required property int index
                        width: ListView.view.width
                        height: 30
                        onClicked: functionDialog.chosen = index
                        onDoubleClicked: { functionDialog.chosen = index; functionDialog.take() }
                        background: Rectangle {
                            radius: Metrics.radiusControl
                            color: index === functionDialog.chosen ? Theme.selectedSubtle : (parent.hovered ? Theme.subtleHover : "transparent")
                        }
                        contentItem: PText { text: modelData.name; leftPadding: 8; verticalAlignment: Text.AlignVCenter }
                    }
                    PText {
                        anchors.centerIn: parent
                        visible: view.sheet !== null && view.sheet.functionList.length === 0
                        text: I18n.tr("Wird geladen …", I18n.revision)
                        tone: "secondary"
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 6
                    PText {
                        objectName: "sheetFunctionSignature"
                        Layout.fillWidth: true
                        text: functionDialog.current ? functionDialog.current.name + "(" + functionDialog.current.arguments.map(function(a) { return a.name }).join("; ") + ")" : ""
                        textStyle: "bodyStrong"
                        wrap: true
                    }
                    PText { Layout.fillWidth: true; text: functionDialog.current ? functionDialog.current.description : ""; wrap: true }
                    Repeater {
                        model: functionDialog.current ? functionDialog.current.arguments : []
                        PText {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.name + ": " + modelData.description
                            textStyle: "caption"
                            tone: "secondary"
                            wrap: true
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                PButton { objectName: "sheetFunctionInsert"; kind: "accent"; text: I18n.tr("Einfügen", I18n.revision); enabled: functionDialog.current !== null; onClicked: functionDialog.take() }
                PButton { text: I18n.tr("Abbrechen", I18n.revision); onClicked: functionDialog.close() }
            }
        }
    }

    // Tastenkürzel (Strg+S, Strg+P, Strg+Z … hat der Reader; hier, was nur Tabellen haben)
    Shortcut { sequences: Shortcuts.keys["reader.save"] || []; enabled: view.active; onActivated: { view.commitEdit(0, 0); view.sheet.saveNow() } }
    Shortcut { sequences: Shortcuts.keys["reader.saveAs"] || []; enabled: view.active; onActivated: { view.commitEdit(0, 0); view.sheet.saveAs() } }
    Shortcut { sequences: Shortcuts.keys["reader.print"] || []; enabled: view.active; onActivated: { view.commitEdit(0, 0); view.sheet.printSheet() } }
    Shortcut { sequences: Shortcuts.keys["reader.zoomIn"] || []; enabled: view.active; onActivated: view.sheet.zoomStep(1) }
    Shortcut { sequences: Shortcuts.keys["reader.zoomOut"] || []; enabled: view.active; onActivated: view.sheet.zoomStep(-1) }
    Shortcut { sequences: Shortcuts.keys["reader.nextTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(1) }
    Shortcut { sequences: Shortcuts.keys["reader.previousTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: Reader.activateIndex(-1) }
    Shortcut { sequences: ["Ctrl+PgDown"]; enabled: view.active && view.sheet.activeSheet < view.sheet.sheets.length - 1; onActivated: view.sheet.activateSheet(view.sheet.activeSheet + 1) }
    Shortcut { sequences: ["Ctrl+PgUp"]; enabled: view.active && view.sheet.activeSheet > 0; onActivated: view.sheet.activateSheet(view.sheet.activeSheet - 1) }
}
