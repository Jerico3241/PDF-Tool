import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Text bearbeiten (seit 5.0 Beta 3, nach dem Entwurf »2-text«): oben die Reiter Datei, Start, Einfügen, Seite,
// Überprüfen und Ansicht (der aktive blau unterstrichen) mit Speichern, Drucken, Rückgängig, Wiederholen und »Als PDF
// speichern« rechts; darunter die Leiste des Reiters, in der Mitte die Seiten auf grauem Grund (TextCanvas), rechts
// die zuklappbaren Formatvorlagen und am Fensterrand der Streifen mit ihren Symbolen (SideRail) – wie bei PDFs. Seite, Wörter und Sprache stehen in der Statuszeile des Fensters.
// Seit Beta 5: Reiter »Referenzen« (Inhaltsverzeichnis, Fuß- und Endnoten, Querverweise) und »Sendungen«
// (Serienbrief), in »Überprüfen« Kommentare, Änderungen annehmen/ablehnen und Vergleichen; die Seitenleiste zeigt
// Formatvorlagen, Kommentare, Änderungen oder den Serienbrief. »Ansicht« hat Lesemodus (nur lesen, ohne Menüband)
// und Augenschutz (Seiten in sanftem Ton).
FocusScope {
    id: view
    objectName: "textView"
    property var doc: null
    property string ribbon: "start"
    readonly property bool active: App.currentPage === "reader" && !Dialogs.open && doc !== null
    readonly property color kindColor: FileKinds.color("text")
    readonly property bool ready: doc !== null && doc.ready
    readonly property var fonts: ["Calibri", "Aptos", "Arial", "Segoe UI", "Cambria", "Times New Roman", "Georgia", "Verdana", "Tahoma", "Courier New", "Liberation Serif", "Liberation Sans"]
    readonly property var sizes: ["8", "9", "10", "10,5", "11", "12", "14", "16", "18", "20", "24", "28", "36", "48", "72"]
    readonly property var swatches: ["#000000", "#404040", "#7F7F7F", "#C00000", "#FF0000", "#ED7D31", "#FFC000", "#00B050", "#0070C0", "#002060", "#7030A0", "#1F4E79"]
    readonly property var sidebarStyles: ["Überschrift 1", "Überschrift 2", "Standard", "Zitat"]
    readonly property var galleryStyles: ["Standard", "Überschrift 1", "Überschrift 2", "Zitat"]  // Leiste wie in Word
    readonly property bool roomy: width >= 1440   // genug Platz für alle Beschriftungen in »Überprüfen«
    // Reiter Start: 3 alles mit Formatvorlagen-Leiste, 2 Vorlagen als Liste, 1 ohne Seltenes, 0 nur das Wichtigste –
    // die höchste Stufe, deren Knöpfe in die Leiste passen (gemessen an den Knöpfen selbst, auch an verborgenen)
    property int startLevel: 3
    onStartLevelChanged: startBar.refit()
    function updateStartLevel() {
        var level = 3
        while (level > 0 && startWidth(level) > startBar.width)
            level--
        startLevel = level
    }
    function startWidth(level) {
        var total = 0, count = 0
        for (var i = 0; i < startBar.children.length; i++) {
            var item = startBar.children[i]
            var from = item.minLevel === undefined ? 0 : item.minLevel
            var to = item.maxLevel === undefined ? 3 : item.maxLevel
            if (item.ribbonWidth !== undefined) {  // Trennstrich: schmal, aber mit Rand
                total += item.ribbonWidth
                count++
                continue
            }
            if (level < from || level > to || item.implicitWidth <= 0)
                continue
            total += item.minWidth !== undefined ? item.minWidth : item.implicitWidth
            count++
        }
        return total + Math.max(0, count - 1) * startBar.spacing
    }
    readonly property var highlights: ["#FFFF00", "#00FF00", "#00FFFF", "#FF00FF", "#0000FF", "#FF0000", "#000080", "#008080", "#008000", "#800080", "#800000", "#808000"]
    property string lastHighlight: "#FFFF00"  // zuletzt gewählter Textmarker (wie in Word unter dem Knopf)
    property bool reading: false   // Lesemodus: nur lesen, ohne Menüband und Seitenleiste
    property bool eyeCare: false   // Augenschutz: Seiten sanft grün getönt (wie WPS), gilt für alle Texte
    readonly property string panel: doc !== null && doc.sidebar ? doc.panel : ""
    readonly property var panelTitles: ({ "styles": "Formatvorlagen", "comments": "Kommentare", "changes": "Änderungen", "merge": "Serienbrief", "assistant": "KI-Assistent" })

    onDocChanged: { reading = false; if (doc) Qt.callLater(function() { canvas.forceActiveFocus() }) }
    function back() { canvas.forceActiveFocus() }
    function startReading() {
        findBar.visible = false
        reading = true
        back()
    }
    function stopReading() {
        reading = false
        back()
    }

    Connections {
        target: view.doc
        function onFindRequested() { findBar.show() }
        function onReplaceRequested() { findBar.replacing = true; findBar.show() }
        function onReadingRequested() { view.startReading() }
    }

    // Schaltfläche der Leiste: Symbol und (optional) Text, ohne Fläche
    component ToolButton: PButton {
        kind: "subtle"
        implicitHeight: 30
        leftPadding: text === "" ? 0 : 8
        rightPadding: text === "" ? 0 : 10
        compact: parent !== null && parent.squeezed === true
        enabled: view.ready
    }
    component Bar: RibbonBar {
        anchors.fill: parent
        anchors.leftMargin: 8
        anchors.rightMargin: 8
        anchors.bottomMargin: 1
        spacing: 2
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Reiter und Befehle rechts -----------------------------------------------------------------------------
        Rectangle {
            objectName: "textRibbonTabs"
            Layout.fillWidth: true
            visible: !view.reading
            implicitHeight: 38
            color: "transparent"  // 3D-Design: Reiter liegen auf dem Hintergrund
            RibbonBar {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: 2
                Repeater {
                    model: [
                        { key: "file", label: "Datei" }, { key: "start", label: "Start" }, { key: "insert", label: "Einfügen" },
                        { key: "page", label: "Seite" }, { key: "references", label: "Referenzen" }, { key: "mailings", label: "Sendungen" },
                        { key: "review", label: "Überprüfen" }, { key: "view", label: "Ansicht" }, { key: "ai", label: "KI" }
                    ]
                    RibbonTab {
                        required property var modelData
                        objectName: "textRibbon_" + modelData.key
                        key: modelData.key
                        text: I18n.tr(modelData.label, I18n.revision)
                        current: view.ribbon
                        kindColor: view.kindColor
                        onClicked: view.ribbon = key
                    }
                }
                Item { Layout.fillWidth: true }
                PIconButton {
                    objectName: "textSave"
                    iconName: "save"
                    tip: I18n.tr("Speichern" + Shortcuts.hints["reader.save"], I18n.revision)
                    enabled: view.ready && !view.doc.saving
                    busy: view.doc !== null && view.doc.saving
                    onClicked: view.doc.saveNow()
                }
                PIconButton {
                    objectName: "textPrint"
                    iconName: "print"
                    tip: I18n.tr("Drucken" + Shortcuts.hints["reader.print"], I18n.revision)
                    enabled: view.ready
                    onClicked: view.doc.printText()
                }
                PIconButton {
                    objectName: "textUndo"
                    iconName: "arrow_undo"
                    tip: I18n.tr("Rückgängig" + Shortcuts.hints["reader.undo"], I18n.revision)
                    enabled: view.ready && view.doc.canUndo
                    onClicked: { view.doc.undo(); view.back() }
                }
                PIconButton {
                    objectName: "textRedo"
                    iconName: "arrow_redo"
                    tip: I18n.tr("Wiederholen" + Shortcuts.hints["reader.redo"], I18n.revision)
                    enabled: view.ready && view.doc.canRedo
                    onClicked: { view.doc.redo(); view.back() }
                }
                RibbonSeparator {}
                PButton {
                    objectName: "textPdf"
                    kind: "link"
                    compact: parent.squeezed === true
                    iconName: "document_pdf"
                    text: I18n.tr("Als PDF speichern", I18n.revision)
                    enabled: view.ready
                    onClicked: view.doc.exportPdf()
                }
            }
        }

        // Leiste des Reiters -------------------------------------------------------------------------------------
        // Befehlsleiste: schwebende Karte mit Glanz und Schatten (seit 5.0 Beta 10, Entwurf 7)
        PGloss {
            objectName: "textToolbar"
            Layout.fillWidth: true
            Layout.leftMargin: 14
            Layout.rightMargin: 14
            Layout.topMargin: 4
            Layout.bottomMargin: 14
            visible: !view.reading
            implicitHeight: Metrics.commandBarHeight

            // Start wie in Word (seit 5.0 Beta 10, Entwurf »beta10-entwurf/1-text-modern-hell«): Zwischenablage | Schrift |
            // Zeichen | Absatz | Ausrichtung und Zeilenabstand | Formatvorlagen … Suchen, Seitenleiste. Bei wenig Platz
            // weichen zuerst die Formatvorlagen in eine Liste, dann seltene Knöpfe (startLevel), dann die Beschriftungen.
            Bar {
                id: startBar
                objectName: "textRibbonBar_start"
                // Stufe erst nach dem Layout neu bestimmen (keine Bindung: die Knöpfe ändern ihre Breite mit der Stufe)
                onWidthChanged: Qt.callLater(view.updateStartLevel)
                onVisibleChanged: if (visible) Qt.callLater(view.updateStartLevel)
                Component.onCompleted: Qt.callLater(view.updateStartLevel)
                visible: view.ribbon === "start"
                RibbonBigButton {
                    objectName: "textPaste"
                    iconName: "clipboard_paste"
                    text: I18n.tr("Einfügen", I18n.revision)
                    tip: I18n.tr("Einfügen (Strg+V)", I18n.revision)
                    enabled: view.ready
                    onClicked: { view.doc.paste(); view.back() }
                }
                ToolButton { objectName: "textCut"; iconName: "cut"; tip: I18n.tr("Ausschneiden (Strg+X)", I18n.revision); enabled: view.ready && view.doc.canCopy; onClicked: { view.doc.cut(); view.back() } }
                ToolButton { objectName: "textCopy"; iconName: "copy"; tip: I18n.tr("Kopieren (Strg+C)", I18n.revision); enabled: view.ready && view.doc.canCopy; onClicked: { view.doc.copy(); view.back() } }
                ToolButton { objectName: "textPaintbrush"; readonly property int minLevel: 2; visible: view.startLevel >= minLevel; iconName: "paint_brush"; tip: I18n.tr("Format übertragen", I18n.revision); onClicked: { view.doc.toggle("paintbrush"); view.back() } }
                RibbonSeparator {}
                PComboBox {
                    objectName: "textFont"
                    preferredWidth: 112
                    label: I18n.tr("Schriftart", I18n.revision)
                    enabled: view.ready
                    readonly property string value: view.doc && view.doc.fontName ? view.doc.fontName : ""
                    model: value === "" || view.fonts.indexOf(value) >= 0 ? view.fonts : [value].concat(view.fonts)
                    currentIndex: value === "" ? -1 : model.indexOf(value)
                    displayText: I18n.tr(value, I18n.revision)
                    onActivated: (index) => { view.doc.setFont(model[index]); view.back() }
                }
                PComboBox {
                    objectName: "textSize"
                    preferredWidth: 58
                    label: I18n.tr("Schriftgröße", I18n.revision)
                    enabled: view.ready
                    readonly property string value: view.doc && view.doc.fontSize ? view.doc.fontSize.replace(".", ",") : ""
                    model: value === "" || view.sizes.indexOf(value) >= 0 ? view.sizes : [value].concat(view.sizes)
                    currentIndex: value === "" ? -1 : model.indexOf(value)
                    displayText: I18n.tr(value, I18n.revision)
                    onActivated: (index) => { view.doc.setFontSize(model[index]); view.back() }
                }
                ToolButton { objectName: "textGrow"; iconName: "font_increase"; tip: I18n.tr("Schrift vergrößern (Strg+>)", I18n.revision); onClicked: { view.doc.toggle("grow"); view.back() } }
                ToolButton { objectName: "textShrink"; iconName: "font_decrease"; tip: I18n.tr("Schrift verkleinern (Strg+<)", I18n.revision); onClicked: { view.doc.toggle("shrink"); view.back() } }
                ToolButton { id: caseButton; objectName: "textCase"; readonly property int minLevel: 1; visible: view.startLevel >= minLevel; iconName: "text_change_case"; tip: I18n.tr("Groß-/Kleinschreibung (Umschalt+F3)", I18n.revision); onClicked: caseMenu.popup(caseButton, 0, caseButton.height + 4) }
                ToolButton { objectName: "textClear"; readonly property int minLevel: 1; visible: view.startLevel >= minLevel; iconName: "text_clear_formatting"; tip: I18n.tr("Formatierung löschen (Strg+Leertaste)", I18n.revision); onClicked: { view.doc.toggle("clear"); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textBold"; iconName: "text_bold"; tip: I18n.tr("Fett (Strg+B)", I18n.revision); toggle: true; checked: view.ready && view.doc.bold; onClicked: { view.doc.toggle("bold"); view.back() } }
                ToolButton { objectName: "textItalic"; iconName: "text_italic"; tip: I18n.tr("Kursiv (Strg+I)", I18n.revision); toggle: true; checked: view.ready && view.doc.italic; onClicked: { view.doc.toggle("italic"); view.back() } }
                ToolButton { objectName: "textUnderline"; iconName: "text_underline"; tip: I18n.tr("Unterstrichen (Strg+U)", I18n.revision); toggle: true; checked: view.ready && view.doc.underline; onClicked: { view.doc.toggle("underline"); view.back() } }
                ToolButton { objectName: "textStrike"; iconName: "text_strikethrough"; tip: I18n.tr("Durchgestrichen", I18n.revision); toggle: true; checked: view.ready && view.doc.strike; onClicked: { view.doc.toggle("strike"); view.back() } }
                ToolButton { objectName: "textSubscript"; readonly property int minLevel: 2; visible: view.startLevel >= minLevel; iconName: "text_subscript"; tip: I18n.tr("Tiefgestellt", I18n.revision); toggle: true; checked: view.ready && view.doc.subscript; onClicked: { view.doc.toggle("subscript"); view.back() } }
                ToolButton { objectName: "textSuperscript"; readonly property int minLevel: 2; visible: view.startLevel >= minLevel; iconName: "text_superscript"; tip: I18n.tr("Hochgestellt", I18n.revision); toggle: true; checked: view.ready && view.doc.superscript; onClicked: { view.doc.toggle("superscript"); view.back() } }
                ToolButton {
                    id: highlightButton
                    objectName: "textHighlight"
                    iconName: "highlight"
                    tip: I18n.tr("Texthervorhebungsfarbe", I18n.revision)
                    toggle: true
                    checked: highlightFlyout.opened
                    onClicked: highlightFlyout.opened ? highlightFlyout.close() : highlightFlyout.open()
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 5
                        width: 14
                        height: 3
                        radius: 1
                        color: view.lastHighlight
                    }
                }
                ToolButton {
                    id: colorButton
                    objectName: "textColor"
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
                ToolButton { objectName: "textBullets"; iconName: "text_bullet_list_ltr"; tip: I18n.tr("Aufzählungszeichen (Strg+Umschalt+L)", I18n.revision); toggle: true; checked: view.ready && view.doc.bullets; onClicked: { view.doc.toggle("bullets"); view.back() } }
                ToolButton { objectName: "textNumbering"; iconName: "text_number_list_ltr"; tip: I18n.tr("Nummerierung", I18n.revision); toggle: true; checked: view.ready && view.doc.numbering; onClicked: { view.doc.toggle("numbering"); view.back() } }
                ToolButton { objectName: "textOutdent"; readonly property int minLevel: 1; visible: view.startLevel >= minLevel; iconName: "text_indent_decrease_ltr"; tip: I18n.tr("Einzug verkleinern (Strg+Umschalt+M)", I18n.revision); onClicked: { view.doc.toggle("outdent"); view.back() } }
                ToolButton { objectName: "textIndent"; readonly property int minLevel: 1; visible: view.startLevel >= minLevel; iconName: "text_indent_increase_ltr"; tip: I18n.tr("Einzug vergrößern (Strg+M)", I18n.revision); onClicked: { view.doc.toggle("indent"); view.back() } }
                ToolButton { objectName: "textMarksStart"; readonly property int minLevel: 2; visible: view.startLevel >= minLevel; iconName: "text_paragraph"; tip: I18n.tr("Alle anzeigen (Absatzmarken und Formatierungszeichen)", I18n.revision); toggle: true; checked: view.ready && view.doc.marks; onClicked: { view.doc.toggle("marks"); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textAlignLeft"; iconName: "text_align_left"; tip: I18n.tr("Linksbündig (Strg+L)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "left"; onClicked: { view.doc.setAlign("left"); view.back() } }
                ToolButton { objectName: "textAlignCenter"; iconName: "text_align_center"; tip: I18n.tr("Zentriert (Strg+E)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "center"; onClicked: { view.doc.setAlign("center"); view.back() } }
                ToolButton { objectName: "textAlignRight"; iconName: "text_align_right"; tip: I18n.tr("Rechtsbündig (Strg+R)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "right"; onClicked: { view.doc.setAlign("right"); view.back() } }
                ToolButton { objectName: "textAlignJustify"; iconName: "text_align_justify"; tip: I18n.tr("Blocksatz (Strg+J)", I18n.revision); toggle: true; checked: view.ready && view.doc.align === "justify"; onClicked: { view.doc.setAlign("justify"); view.back() } }
                ToolButton { id: spacingButton; objectName: "textSpacing"; iconName: "text_line_spacing"; tip: I18n.tr("Zeilen- und Absatzabstand", I18n.revision); onClicked: spacingMenu.popup(spacingButton, 0, spacingButton.height + 4) }
                RibbonSeparator {}
                // Formatvorlagen: bei genug Platz als Leiste wie in Word, sonst als Liste
                Rectangle {
                    id: gallery
                    objectName: "textStyleGallery"
                    readonly property int minLevel: 3
                    // Wie in Word: bei weniger Platz zeigt die Leiste weniger Vorlagen (mindestens zwei), der Rest über ⌄
                    readonly property real minWidth: galleryWidth(2)
                    function galleryWidth(count) {
                        var total = galleryMore.implicitWidth + 8
                        for (var i = 0; i < count && i < galleryItems.count; i++)
                            total += galleryItems.itemAt(i) ? galleryItems.itemAt(i).implicitWidth + 2 : 0
                        return total
                    }
                    readonly property int fitCount: {
                        var count = 0
                        while (count < galleryItems.count && galleryWidth(count + 1) <= width + 0.5)
                            count++
                        return Math.max(2, count)
                    }
                    visible: view.startLevel >= minLevel
                    implicitWidth: galleryWidth(galleryItems.count)
                    Layout.fillWidth: true
                    Layout.minimumWidth: minWidth
                    Layout.preferredWidth: minWidth  // die Leiste misst sich mit der kleinsten Galerie (kein Zusammenschieben)
                    Layout.maximumWidth: implicitWidth
                    Layout.horizontalStretchFactor: 100
                    implicitHeight: 38
                    radius: Metrics.radiusControl + 4
                    color: Theme.control
                    border.color: Theme.controlStroke
                    clip: true
                    RowLayout {
                        id: galleryRow
                        anchors.left: parent.left
                        anchors.leftMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Repeater {
                            id: galleryItems
                            model: view.galleryStyles
                            PButton {
                                required property string modelData
                                required property int index
                                kind: "subtle"
                                compact: false
                                visible: index < gallery.fitCount
                                implicitHeight: 30
                                leftPadding: 10
                                rightPadding: 10
                                text: I18n.tr(modelData, I18n.revision)
                                // Vorschau wie in Word: Überschriften blau, Zitat kursiv
                                font: Qt.font({ family: Typography.family, pixelSize: index === 1 ? 15 : (index === 2 ? 13 : 14), italic: index === 3 })
                                labelColor: index === 1 || index === 2 ? (Theme.dark ? "#7FA6E8" : "#2F5496") : (index === 3 ? Theme.textSecondary : "transparent")
                                toggle: true
                                checked: view.ready && view.doc.styleName === modelData
                                enabled: view.ready
                                onClicked: { view.doc.applyStyle(modelData); view.back() }
                            }
                        }
                    }
                    PIconButton {
                        id: galleryMore
                        anchors.right: parent.right
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        implicitWidth: 24
                        iconName: "chevron_down"
                        tip: I18n.tr("Alle Formatvorlagen", I18n.revision)
                        enabled: view.ready
                        onClicked: view.doc.showPanel("styles")
                    }
                }
                PComboBox {
                    objectName: "textStyle"
                    readonly property int maxLevel: 2
                    visible: view.startLevel <= maxLevel
                    preferredWidth: 140
                    label: I18n.tr("Formatvorlage", I18n.revision)
                    enabled: view.ready
                    readonly property string value: view.doc ? view.doc.styleName : ""
                    readonly property var styles: view.doc ? view.doc.styleList() : []
                    model: value === "" || styles.indexOf(value) >= 0 ? styles : [value].concat(styles)
                    currentIndex: value === "" ? -1 : model.indexOf(value)
                    displayText: I18n.tr(value, I18n.revision)
                    onActivated: (index) => { view.doc.applyStyle(model[index]); view.back() }
                }
                Item { Layout.fillWidth: true }
                PIconButton { objectName: "textSearch"; iconName: "search"; tip: I18n.tr("Suchen (Strg+F) und Ersetzen (Strg+H)", I18n.revision); enabled: view.ready; onClicked: findBar.show() }
                PIconButton {
                    objectName: "textSidebarToggle"
                    iconName: "panel_right"
                    tip: I18n.tr("Seitenleiste ein- oder ausblenden", I18n.revision)
                    toggle: true
                    checked: view.doc !== null && view.doc.sidebar
                    onClicked: view.doc.toggleSidebar()
                }
            }

            // Datei
            Bar {
                objectName: "textRibbonBar_file"
                visible: view.ribbon === "file"
                ToolButton { objectName: "textFileNew"; iconName: "document_add"; text: I18n.tr("Neuer Text", I18n.revision); enabled: true; onClicked: Reader.newText() }
                ToolButton { iconName: "folder_open"; text: I18n.tr("Öffnen", I18n.revision); enabled: true; onClicked: Reader.openDialog() }
                RibbonSeparator {}
                ToolButton { iconName: "save"; text: I18n.tr("Speichern", I18n.revision); onClicked: view.doc.saveNow() }
                ToolButton { objectName: "textSaveAs"; iconName: "save"; text: I18n.tr("Speichern unter …", I18n.revision); onClicked: view.doc.saveAs() }
                ToolButton { iconName: "document_pdf"; text: I18n.tr("Als PDF speichern …", I18n.revision); onClicked: view.doc.exportPdf() }
                ToolButton { objectName: "textExportImages"; iconName: "image"; text: I18n.tr("Als Bild speichern …", I18n.revision); onClicked: view.doc.exportPageImages() }
                ToolButton { iconName: "print"; text: I18n.tr("Drucken", I18n.revision); onClicked: view.doc.printText() }
                RibbonSeparator {}
                ToolButton { iconName: "mail"; text: I18n.tr("Per E-Mail senden", I18n.revision); onClicked: Reader.sendByMail() }
                ToolButton { iconName: "folder"; text: I18n.tr("Ordner öffnen", I18n.revision); enabled: view.doc !== null && view.doc.path !== ""; onClicked: Reader.showInFolder(view.doc.path) }
                ToolButton { iconName: "dismiss"; text: I18n.tr("Schließen", I18n.revision); enabled: true; onClicked: Reader.closeCurrent() }
                Item { Layout.fillWidth: true }
            }

            // Einfügen
            Bar {
                objectName: "textRibbonBar_insert"
                visible: view.ribbon === "insert"
                ToolButton { objectName: "textInsertImage"; iconName: "image_add"; text: I18n.tr("Bild", I18n.revision); tip: I18n.tr("Bild aus einer Datei einfügen", I18n.revision); onClicked: { view.doc.insertImage(); view.back() } }
                ToolButton { id: tableButton; objectName: "textInsertTable"; iconName: "table_simple"; text: I18n.tr("Tabelle", I18n.revision); onClicked: tableMenu.popup(tableButton, 0, tableButton.height + 4) }
                ToolButton { objectName: "textInsertChart"; iconName: "data_bar_vertical"; text: I18n.tr("Diagramm", I18n.revision); tip: I18n.tr("Säulen-, Balken-, Linien- oder Kreisdiagramm aus eigenen Werten", I18n.revision); onClicked: view.doc.insertChart() }
                ToolButton { objectName: "textInsertFormula"; iconName: "math_formula"; text: I18n.tr("Formel", I18n.revision); tip: I18n.tr("Mathematische Formel einfügen oder die ausgewählte ändern", I18n.revision); onClicked: view.doc.insertFormula() }
                RibbonSeparator {}
                ToolButton { objectName: "textInsertComment"; iconName: "comment_add"; text: I18n.tr("Kommentar", I18n.revision); tip: I18n.tr("Kommentar zur Auswahl", I18n.revision); onClicked: view.doc.requestComment() }
                ToolButton { iconName: "text_footnote"; text: I18n.tr("Fußnote", I18n.revision); onClicked: { view.doc.insertFootnote(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textPageBreak"; iconName: "document_page_break"; text: I18n.tr("Seitenumbruch", I18n.revision); tip: I18n.tr("Neue Seite beginnen", I18n.revision); onClicked: { view.doc.insertPageBreak(); view.back() } }
                RibbonSeparator {}
                ToolButton { iconName: "document_page_number"; text: I18n.tr("Seitenzahl", I18n.revision); onClicked: { view.doc.insertField("page"); view.back() } }
                ToolButton { iconName: "number_symbol"; text: I18n.tr("Seitenanzahl", I18n.revision); onClicked: { view.doc.insertField("pages"); view.back() } }
                ToolButton { iconName: "calendar_date"; text: I18n.tr("Datum", I18n.revision); onClicked: { view.doc.insertField("date"); view.back() } }
                Item { Layout.fillWidth: true }
            }

            // Seite
            Bar {
                objectName: "textRibbonBar_page"
                visible: view.ribbon === "page"
                ToolButton { objectName: "textPortrait"; iconName: "document"; text: I18n.tr("Hochformat", I18n.revision); toggle: true; checked: view.ready && !view.doc.landscape; onClicked: { view.doc.setLandscape(false); view.back() } }
                ToolButton { objectName: "textLandscape"; iconName: "document_landscape"; text: I18n.tr("Querformat", I18n.revision); toggle: true; checked: view.ready && view.doc.landscape; onClicked: { view.doc.setLandscape(true); view.back() } }
                RibbonSeparator {}
                ToolButton { id: marginButton; objectName: "textMargins"; iconName: "document_margins"; text: I18n.tr("Seitenränder", I18n.revision); onClicked: marginMenu.popup(marginButton, 0, marginButton.height + 4) }
                RibbonSeparator {}
                ToolButton { iconName: "document_header"; text: I18n.tr("Kopfzeile", I18n.revision); onClicked: { view.doc.headerFooter("header"); view.back() } }
                ToolButton { iconName: "document_footer"; text: I18n.tr("Fußzeile", I18n.revision); onClicked: { view.doc.headerFooter("footer"); view.back() } }
                RibbonSeparator {}
                ToolButton { iconName: "document_page_break"; text: I18n.tr("Seitenumbruch", I18n.revision); onClicked: { view.doc.insertPageBreak(); view.back() } }
                Item { Layout.fillWidth: true }
            }

            // Referenzen (seit Beta 5)
            Bar {
                objectName: "textRibbonBar_references"
                visible: view.ribbon === "references"
                ToolButton { objectName: "textToc"; iconName: "text_bullet_list_tree"; text: I18n.tr("Inhaltsverzeichnis", I18n.revision); tip: I18n.tr("Verzeichnis der Überschriften an der Schreibmarke einfügen", I18n.revision); onClicked: { view.doc.insertToc(); view.back() } }
                ToolButton { objectName: "textTocUpdate"; iconName: "arrow_sync"; text: I18n.tr("Aktualisieren", I18n.revision); tip: I18n.tr("Verzeichnisse, Seitenzahlen und Querverweise auf den neuesten Stand bringen", I18n.revision); onClicked: { view.doc.updateToc(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textFootnote"; iconName: "text_footnote"; text: I18n.tr("Fußnote", I18n.revision); tip: I18n.tr("Fußnote unten auf der Seite", I18n.revision); onClicked: { view.doc.insertFootnote(); view.back() } }
                ToolButton { objectName: "textEndnote"; iconName: "document_endnote"; text: I18n.tr("Endnote", I18n.revision); tip: I18n.tr("Endnote am Ende des Textes", I18n.revision); onClicked: { view.doc.insertEndnote(); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textCrossReference"; iconName: "link_multiple"; text: I18n.tr("Querverweis", I18n.revision); tip: I18n.tr("Auf eine Überschrift, Textmarke oder Fußnote verweisen (»siehe Seite 4«)", I18n.revision); onClicked: view.doc.insertCrossReference() }
                Item { Layout.fillWidth: true }
            }

            // Sendungen: Serienbrief (seit Beta 5)
            Bar {
                objectName: "textRibbonBar_mailings"
                visible: view.ribbon === "mailings"
                ToolButton { objectName: "textMergeChoose"; iconName: "people_list"; text: I18n.tr("Empfänger wählen", I18n.revision); tip: I18n.tr("Excel-Mappe oder CSV-Datei mit den Empfängern", I18n.revision); onClicked: view.doc.chooseMergeSource() }
                ToolButton { id: fieldButton; objectName: "textMergeInsertField"; iconName: "text_field"; text: I18n.tr("Feld einfügen", I18n.revision); enabled: view.ready && view.doc.mergeFields.length > 0; onClicked: fieldMenu.popup(fieldButton, 0, fieldButton.height + 4) }
                ToolButton { objectName: "textMergeLetters"; iconName: "mail_multiple"; text: I18n.tr("Briefe erstellen", I18n.revision); tip: I18n.tr("Ein neues Dokument mit einem Brief je Empfänger", I18n.revision); enabled: view.ready && view.doc.mergeCount > 0 && !view.doc.mergeBusy; onClicked: view.doc.createLetters() }
                RibbonSeparator {}
                ToolButton { objectName: "textMergePanelToggle"; iconName: "panel_right"; text: I18n.tr("Serienbrief", I18n.revision); tip: I18n.tr("Schritte des Serienbriefs rechts zeigen", I18n.revision); toggle: true; checked: view.panel === "merge"; onClicked: view.doc.showPanel("merge") }
                Item { Layout.fillWidth: true }
            }

            // Überprüfen
            Bar {
                objectName: "textRibbonBar_review"
                visible: view.ribbon === "review"
                ToolButton { objectName: "textSpelling"; iconName: "text_proofing_tools"; text: I18n.tr("Rechtschreibung", I18n.revision); tip: I18n.tr("Falsch geschriebene Wörter rot unterstreichen", I18n.revision); toggle: true; checked: view.ready && view.doc.spelling; onClicked: { view.doc.toggle("spelling"); view.back() } }
                RibbonSeparator {}
                ToolButton { objectName: "textReviewComment"; iconName: "comment_add"; text: I18n.tr(view.roomy ? "Neuer Kommentar" : "", I18n.revision); tip: I18n.tr("Kommentar zur Auswahl", I18n.revision); onClicked: view.doc.requestComment() }
                ToolButton { objectName: "textReviewComments"; iconName: "comment_multiple"; text: I18n.tr(view.roomy ? "Kommentare" : "", I18n.revision); tip: I18n.tr("Alle Kommentare rechts zeigen", I18n.revision); toggle: true; checked: view.panel === "comments"; onClicked: view.doc.showPanel("comments") }
                RibbonSeparator {}
                ToolButton { objectName: "textTrack"; iconName: "edit"; text: I18n.tr("Nachverfolgen", I18n.revision); tip: I18n.tr("Änderungen nachverfolgen: farbig markieren, statt sie gleich zu übernehmen", I18n.revision); toggle: true; checked: view.ready && view.doc.trackChanges; onClicked: { view.doc.toggle("trackChanges"); view.back() } }
                ToolButton { objectName: "textShowChanges"; iconName: "eye"; tip: I18n.tr("Markierte Änderungen im Text zeigen oder ausblenden", I18n.revision); toggle: true; checked: view.ready && view.doc.showChanges; onClicked: { view.doc.toggleShowChanges(); view.back() } }
                ToolButton { iconName: "arrow_previous"; tip: I18n.tr("Vorherige Änderung", I18n.revision); onClicked: { view.doc.previousChange(); view.back() } }
                ToolButton { iconName: "arrow_next"; tip: I18n.tr("Nächste Änderung", I18n.revision); onClicked: { view.doc.nextChange(); view.back() } }
                ToolButton { id: acceptButton; objectName: "textAccept"; iconName: "checkmark"; text: I18n.tr("Annehmen", I18n.revision); onClicked: acceptMenu.popup(acceptButton, 0, acceptButton.height + 4) }
                ToolButton { id: rejectButton; objectName: "textReject"; iconName: "dismiss"; text: I18n.tr("Ablehnen", I18n.revision); onClicked: rejectMenu.popup(rejectButton, 0, rejectButton.height + 4) }
                ToolButton { objectName: "textReviewChanges"; iconName: "document_edit"; text: I18n.tr(view.roomy ? "Änderungen" : "", I18n.revision); tip: I18n.tr("Alle Änderungen rechts zeigen", I18n.revision); toggle: true; checked: view.panel === "changes"; onClicked: view.doc.showPanel("changes") }
                RibbonSeparator {}
                ToolButton { objectName: "textCompare"; iconName: "branch_compare"; text: I18n.tr("Vergleichen", I18n.revision); tip: I18n.tr("Mit einer anderen Fassung vergleichen – Unterschiede erscheinen als Änderungen", I18n.revision); onClicked: view.doc.compareWith() }
                Item { Layout.fillWidth: true }
                PIconButton { iconName: "search"; tip: I18n.tr("Suchen und ersetzen (Strg+F)", I18n.revision); enabled: view.ready; onClicked: findBar.show() }
            }

            // Ansicht
            Bar {
                objectName: "textRibbonBar_view"
                visible: view.ribbon === "view"
                ToolButton { iconName: "zoom_out"; tip: I18n.tr("Verkleinern", I18n.revision); onClicked: view.doc.zoomStep(-1) }
                ToolButton { text: I18n.tr(view.doc ? view.doc.zoom + " %" : "", I18n.revision); tip: I18n.tr("Zoom auf 100 %", I18n.revision); onClicked: view.doc.setZoom(100) }
                ToolButton { iconName: "zoom_in"; tip: I18n.tr("Vergrößern", I18n.revision); onClicked: view.doc.zoomStep(1) }
                RibbonSeparator {}
                ToolButton { objectName: "textMarks"; iconName: "text_paragraph"; text: I18n.tr("Formatierungszeichen", I18n.revision); tip: I18n.tr("Absatzmarken, Leerzeichen und Tabulatoren zeigen", I18n.revision); toggle: true; checked: view.ready && view.doc.marks; onClicked: { view.doc.toggle("marks"); view.back() } }
                ToolButton { iconName: "panel_right"; text: I18n.tr("Formatvorlagen", I18n.revision); toggle: true; enabled: true; checked: view.panel === "styles"; onClicked: view.doc.showPanel("styles") }
                RibbonSeparator {}
                ToolButton { objectName: "textReading"; iconName: "book_open"; text: I18n.tr("Lesemodus", I18n.revision); tip: I18n.tr("Nur lesen – ohne Menüband und Seitenleiste (Esc beendet)", I18n.revision); onClicked: view.startReading() }
                ToolButton { objectName: "textEyeCare"; iconName: "eye_lines"; text: I18n.tr("Augenschutz", I18n.revision); tip: I18n.tr("Seiten in sanftem Grün statt grellem Weiß – angenehmer bei langem Lesen", I18n.revision); toggle: true; enabled: true; checked: view.eyeCare; onClicked: view.eyeCare = !view.eyeCare }
                Item { Layout.fillWidth: true }
            }

            // KI (seit Beta 8)
            AiRibbon {
                objectName: "textRibbonBar_ai"
                visible: view.ribbon === "ai"
                kind: "text"
                ready: view.ready
                kindColor: view.kindColor
                panelOpen: view.panel === "assistant"
                onPanelToggled: if (view.doc) view.doc.showPanel("assistant")
            }
        }

        // Seiten und Formatvorlagen --------------------------------------------------------------------------------
        // 3D-Design (Entwurf 7): die Arbeitsfläche ist eine Mulde mit runden Ecken, die Seitenleiste eine schwebende Karte
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: view.reading ? 0 : 14
            Layout.bottomMargin: view.reading ? 0 : 6
            spacing: 12

            Item {
                id: pageArea
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                Rectangle {
                    anchors.fill: parent
                    radius: view.reading ? 0 : Metrics.radiusFloat
                    color: Theme.viewer
                }

                TextCanvas {
                    id: canvas
                    objectName: "textCanvas"
                    anchors.fill: parent  // Bildlaufleisten liegen darüber (wie in Windows 11)
                    controller: view.doc
                    pixelRatio: Screen.devicePixelRatio
                    focus: true
                    backgroundColor: view.reading ? Theme.viewer : "transparent"  // Grund: die Mulde dahinter (wie bei PDFs)
                    glowColor: Theme.neon ? Theme.glowColor(Theme.accent, 0.9) : "transparent"
                    paperColor: "#FFFFFF"
                    caretColor: Theme.neon ? Theme.accent : "#000000"
                    selectionColor: Theme.neon ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.35) : (Theme.dark ? "#5A4CA0E0" : "#4D0078D4")
                    accentColor: Theme.dark ? "#4CA0E0" : "#0F6CBD"
                    readOnly: view.reading
                    tintColor: view.eyeCare ? "#D7EDD1" : "transparent"  // Augenschutz: Weiß wird zu sanftem Grün
                    onContextMenuRequested: (x, y) => { if (!view.reading) textMenu.popup(canvas, x, y) }
                }

                PScrollBar {
                    id: vbar
                    objectName: "textVScroll"
                    orientation: Qt.Vertical
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: hbar.visible ? hbar.top : parent.bottom
                    policy: T.ScrollBar.AlwaysOn
                    size: canvas && canvas.contentHeight > 0 ? Math.min(1, canvas.viewHeight / canvas.contentHeight) : 1
                    position: canvas && canvas.contentHeight > 0 ? canvas.scrollY / canvas.contentHeight : 0
                    onPositionChanged: if (pressed) canvas.scrollY = position * canvas.contentHeight
                }
                PScrollBar {
                    id: hbar
                    objectName: "textHScroll"
                    orientation: Qt.Horizontal
                    anchors.left: parent.left
                    anchors.right: vbar.left
                    anchors.bottom: parent.bottom
                    visible: canvas !== null && canvas.contentWidth > canvas.viewWidth + 1
                    policy: T.ScrollBar.AlwaysOn
                    size: canvas && canvas.contentWidth > 0 ? Math.min(1, canvas.viewWidth / canvas.contentWidth) : 1
                    position: canvas && canvas.contentWidth > 0 ? canvas.scrollX / canvas.contentWidth : 0
                    onPositionChanged: if (pressed) canvas.scrollX = position * canvas.contentWidth
                }

                // Suchen und ersetzen (Strg+F)
                Rectangle {
                    id: findBar
                    objectName: "textFindBar"
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
                    anchors.right: vbar.left
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
                                objectName: "textFindField"
                                Layout.fillWidth: true
                                preferredWidth: 180
                                placeholderText: I18n.tr("Suchen im Text", I18n.revision)
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
                                objectName: "textReplaceField"
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

                // Lesemodus: oben rechts beenden (wie Esc)
                Rectangle {
                    objectName: "textReadingBar"
                    visible: view.reading
                    anchors.right: vbar.left
                    anchors.top: parent.top
                    anchors.rightMargin: 16
                    anchors.topMargin: 12
                    width: readingRow.implicitWidth + 16
                    height: readingRow.implicitHeight + 12
                    radius: Metrics.radiusOverlay
                    color: Theme.flyout
                    border.color: Theme.flyoutStroke
                    PShadow { radius: Metrics.radiusOverlay }
                    RowLayout {
                        id: readingRow
                        anchors.centerIn: parent
                        spacing: 4
                        PIcon { name: "book_open"; color: Theme.textSecondary }
                        PText { text: I18n.tr("Lesemodus", I18n.revision); tone: "secondary"; Layout.rightMargin: 6 }
                        PIconButton { iconName: "zoom_out"; tip: I18n.tr("Verkleinern", I18n.revision); onClicked: view.doc.zoomStep(-1) }
                        PIconButton { iconName: "zoom_in"; tip: I18n.tr("Vergrößern", I18n.revision); onClicked: view.doc.zoomStep(1) }
                        PIconButton { iconName: "eye_lines"; tip: I18n.tr("Augenschutz", I18n.revision); toggle: true; checked: view.eyeCare; onClicked: view.eyeCare = !view.eyeCare }
                        PButton { objectName: "textReadingExit"; kind: "accent"; text: I18n.tr("Bearbeiten", I18n.revision); tip: I18n.tr("Lesemodus beenden (Esc)", I18n.revision); onClicked: view.stopReading() }
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
                PWell { visible: !view.reading; radius: Metrics.radiusFloat }
            }

            // Formatvorlagen rechts neben der Seite, der Streifen mit den Symbolen am Fensterrand (wie bei PDFs) ---------
            PGloss {
                objectName: "textSidebar"
                slideIn: true
                Layout.fillHeight: true
                Layout.preferredWidth: Metrics.readerLeftPanelWidth
                visible: view.doc !== null && view.doc.sidebar && !view.reading
                // Kopf wie bei den Seitenleisten der PDFs (Titel, Schließen, Trennlinie)
                PanelHeader {
                    id: sidebarHeader
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 1
                    title: I18n.tr(view.panelTitles[view.panel] || "", I18n.revision)
                    onCloseRequested: { view.doc.toggleSidebar(); view.back() }
                }
                ColumnLayout {
                    objectName: "textStylesPanel"
                    visible: view.panel === "styles"
                    anchors.top: sidebarHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 13
                    anchors.rightMargin: 12
                    anchors.topMargin: 12
                    spacing: 6
                    Repeater {
                        model: view.sidebarStyles
                        T.AbstractButton {
                            id: styleItem
                            required property string modelData
                            required property int index
                            readonly property bool current: view.doc !== null && view.doc.styleName === modelData
                            objectName: "textSidebarStyle_" + index
                            Layout.fillWidth: true
                            enabled: view.ready
                            hoverEnabled: true
                            Accessible.role: Accessible.Button
                            Accessible.name: I18n.tr(modelData, I18n.revision)
                            onClicked: { view.doc.applyStyle(modelData); view.back() }
                            implicitHeight: styleItem.index === 0 ? 54 : 52
                            background: Rectangle {
                                radius: Metrics.radiusControl + 2
                                color: styleItem.current ? Theme.pressedFill : (styleItem.hovered ? Theme.controlHover : Theme.control)
                                border.width: styleItem.current ? 2 : 1
                                border.color: styleItem.current ? (Theme.neon ? Theme.accent : view.kindColor) : Theme.controlStroke
                                Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                                // Neon: die gewählte Vorlage leuchtet
                                Repeater {
                                    model: styleItem.current && Theme.glow > 0 ? 4 : 0
                                    Rectangle {
                                        required property int index
                                        x: -(index + 1); y: -(index + 1)
                                        width: parent.width + 2 * (index + 1); height: parent.height + 2 * (index + 1)
                                        radius: parent.radius + index + 1
                                        color: "transparent"
                                        border.width: 1
                                        border.color: Theme.accent
                                        opacity: 0.25 * Theme.glow * (1 - index / 4)
                                    }
                                }
                            }
                            contentItem: Text {
                                leftPadding: 10
                                rightPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                text: I18n.tr(styleItem.modelData, I18n.revision)
                                font.family: Typography.family
                                // Vorschau wie in Word: Überschriften blau und leicht, Zitat kursiv
                                font.pixelSize: styleItem.index === 0 ? 20 : (styleItem.index === 1 ? 16 : 15)
                                font.weight: Font.Normal
                                font.italic: styleItem.index === 3
                                color: styleItem.index <= 1 ? (Theme.dark ? "#7FA6E8" : "#2F5496") : (styleItem.index === 3 ? Theme.textSecondary : Theme.textPrimary)
                                textFormat: Text.PlainText
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
                TextCommentsPanel {
                    visible: view.panel === "comments"
                    anchors.top: sidebarHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 1
                    doc: view.doc
                    onDone: view.back()
                }
                TextChangesPanel {
                    visible: view.panel === "changes"
                    anchors.top: sidebarHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 1
                    doc: view.doc
                }
                Loader {
                    objectName: "textAssistantPanel"
                    active: view.panel === "assistant" && Assistant.enabled
                    visible: active
                    anchors.top: sidebarHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 1
                    sourceComponent: AssistantPanel { doc: view.doc }
                }
                TextMergePanel {
                    visible: view.panel === "merge"
                    anchors.top: sidebarHeader.bottom
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.leftMargin: 1
                    doc: view.doc
                    onDone: view.back()
                }
            }

            // Streifen mit den Inhalten der Seitenleiste – wie bei PDFs
            SideRail {
                objectName: "textSideRail"
                Layout.fillHeight: true
                Layout.preferredWidth: Metrics.readerRailWidth
                visible: !view.reading
                current: view.panel
                accentColor: view.kindColor
                items: [
                    { key: "styles", icon: "text_edit_style", tip: "Formatvorlagen", name: "textRailStyles" },
                    { key: "comments", icon: "comment_multiple", tip: "Kommentare", name: "textRailComments" },
                    { key: "changes", icon: "document_edit", tip: "Änderungen", name: "textRailChanges" },
                    { key: "merge", icon: "mail_multiple", tip: "Serienbrief", name: "textRailMerge" },
                    { key: "assistant", icon: "sparkle", tip: "KI-Assistent", name: "textRailAssistant" },
                    { key: "search", icon: "search", tip: "Suchen und ersetzen (Strg+F)", name: "textRailSearch", separator: true }
                ]
                onSelected: (key) => {
                    if (!view.doc) return
                    if (key === "search") findBar.show()
                    else { view.doc.showPanel(key); view.back() }
                }
            }

        }
    }

    // Menüs und Flyouts ----------------------------------------------------------------------------------------------
    T.Popup {
        id: colorFlyout
        objectName: "textColorFlyout"
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
    T.Popup {
        id: highlightFlyout
        objectName: "textHighlightFlyout"
        parent: highlightButton
        y: highlightButton.height + 4
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
            PText { text: I18n.tr("Texthervorhebungsfarbe", I18n.revision); textStyle: "caption"; tone: "secondary" }
            Flow {
                Layout.fillWidth: true
                spacing: 2
                Repeater {
                    model: view.highlights
                    PSwatch {
                        required property var modelData
                        size: 32
                        swatchColor: modelData
                        tip: I18n.tr(modelData, I18n.revision)
                        selected: view.doc !== null && view.doc.highlight.toUpperCase() === modelData
                        onClicked: { view.lastHighlight = modelData; view.doc.setHighlight(modelData); highlightFlyout.close() }
                    }
                }
            }
            PButton { text: I18n.tr("Keine Farbe", I18n.revision); kind: "subtle"; onClicked: { view.doc.setHighlight(""); highlightFlyout.close() } }
        }
    }
    PMenu {
        id: caseMenu
        objectName: "textCaseMenu"
        PMenuItem { text: I18n.tr("Satzanfang groß", I18n.revision); onTriggered: { view.doc.toggle("sentenceCase"); view.back() } }
        PMenuItem { text: I18n.tr("kleinbuchstaben", I18n.revision); onTriggered: { view.doc.toggle("lowerCase"); view.back() } }
        PMenuItem { text: I18n.tr("GROSSBUCHSTABEN", I18n.revision); onTriggered: { view.doc.toggle("upperCase"); view.back() } }
        PMenuItem { text: I18n.tr("Ersten Buchstaben Jedes Wortes Groß", I18n.revision); onTriggered: { view.doc.toggle("titleCase"); view.back() } }
        PMenuItem { text: I18n.tr("gROSS-/kLEINSCHREIBUNG UMKEHREN", I18n.revision); onTriggered: { view.doc.toggle("toggleCase"); view.back() } }
    }
    PMenu {
        id: spacingMenu
        objectName: "textSpacingMenu"
        PMenuItem { text: I18n.tr("1,0", I18n.revision); onTriggered: { view.doc.setLineSpacing(100); view.back() } }
        PMenuItem { text: I18n.tr("1,08", I18n.revision); onTriggered: { view.doc.setLineSpacing(108); view.back() } }
        PMenuItem { text: I18n.tr("1,15", I18n.revision); onTriggered: { view.doc.setLineSpacing(115); view.back() } }
        PMenuItem { text: I18n.tr("1,5", I18n.revision); onTriggered: { view.doc.setLineSpacing(150); view.back() } }
        PMenuItem { text: I18n.tr("2,0", I18n.revision); onTriggered: { view.doc.setLineSpacing(200); view.back() } }
        PMenuItem { text: I18n.tr("Abstand nach Absatz hinzufügen", I18n.revision); onTriggered: { view.doc.setParagraphSpace(true); view.back() } }
        PMenuItem { text: I18n.tr("Abstand nach Absatz entfernen", I18n.revision); onTriggered: { view.doc.setParagraphSpace(false); view.back() } }
    }
    PMenu {
        id: tableMenu
        objectName: "textTableMenu"
        PMenuItems {
            menu: tableMenu
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
        id: acceptMenu
        objectName: "textAcceptMenu"
        PMenuItem { text: I18n.tr("Diese Änderung annehmen", I18n.revision); iconName: "checkmark"; onTriggered: { view.doc.acceptCurrentChange(); view.back() } }
        PMenuItem { objectName: "textAcceptAll"; text: I18n.tr("Alle Änderungen annehmen", I18n.revision); iconName: "checkmark_circle"; onTriggered: { view.doc.acceptAllChanges(); view.back() } }
    }
    PMenu {
        id: rejectMenu
        objectName: "textRejectMenu"
        PMenuItem { text: I18n.tr("Diese Änderung ablehnen", I18n.revision); iconName: "dismiss"; onTriggered: { view.doc.rejectCurrentChange(); view.back() } }
        PMenuItem { text: I18n.tr("Alle Änderungen ablehnen", I18n.revision); iconName: "dismiss_circle"; onTriggered: { view.doc.rejectAllChanges(); view.back() } }
    }
    PMenu {
        id: fieldMenu
        objectName: "textFieldMenu"
        PMenuItems {
            menu: fieldMenu
            model: view.doc ? view.doc.mergeFields : []
            PMenuItem {
                required property string modelData
                text: I18n.tr("«" + modelData + "»", I18n.revision)
                onTriggered: { view.doc.insertMergeField(modelData); view.back() }
            }
        }
    }
    PMenu {
        id: marginMenu
        objectName: "textMarginMenu"
        PMenuItem { text: I18n.tr("Normal (2,5 cm)", I18n.revision); onTriggered: { view.doc.setMargins("normal"); view.back() } }
        PMenuItem { text: I18n.tr("Schmal (1,27 cm)", I18n.revision); onTriggered: { view.doc.setMargins("narrow"); view.back() } }
        PMenuItem { text: I18n.tr("Breit (links und rechts 5 cm)", I18n.revision); onTriggered: { view.doc.setMargins("wide"); view.back() } }
    }
    PMenu {
        id: textMenu
        objectName: "textContextMenu"
        onClosed: view.back()
        PMenuItem { text: I18n.tr("Ausschneiden", I18n.revision); hint: I18n.tr("Strg+X", I18n.revision); iconName: "cut"; enabled: view.ready && view.doc.canCopy; onTriggered: view.doc.cut() }
        PMenuItem { text: I18n.tr("Kopieren", I18n.revision); hint: I18n.tr("Strg+C", I18n.revision); iconName: "copy"; enabled: view.ready && view.doc.canCopy; onTriggered: view.doc.copy() }
        PMenuItem { text: I18n.tr("Einfügen", I18n.revision); hint: I18n.tr("Strg+V", I18n.revision); iconName: "clipboard_paste"; onTriggered: view.doc.paste() }
        PMenuItem { text: I18n.tr("Nur den Text einfügen", I18n.revision); hint: I18n.tr("Strg+Umschalt+V", I18n.revision); iconName: "clipboard_paste"; onTriggered: view.doc.pastePlain() }
        PMenuItem { text: I18n.tr("Alles auswählen", I18n.revision); hint: I18n.tr("Strg+A", I18n.revision); iconName: "select_all_on"; onTriggered: view.doc.selectAll() }
        PMenuItem { objectName: "textContextComment"; text: I18n.tr("Neuer Kommentar", I18n.revision); iconName: "comment_add"; onTriggered: view.doc.requestComment() }
    }

    // Tastenkürzel (Strg+C/X/V/Z/Y/A, Formate und Bewegen nimmt der Zeichenbereich selbst)
    Shortcut { sequences: Shortcuts.keys["reader.save"] || []; enabled: view.active; onActivated: view.doc.saveNow() }
    Shortcut { sequences: Shortcuts.keys["reader.saveAs"] || []; enabled: view.active; onActivated: view.doc.saveAs() }
    Shortcut { sequences: Shortcuts.keys["reader.print"] || []; enabled: view.active; onActivated: view.doc.printText() }
    Shortcut { sequences: Shortcuts.keys["reader.zoomIn"] || []; enabled: view.active; onActivated: view.doc.zoomStep(1) }
    Shortcut { sequences: Shortcuts.keys["reader.zoomOut"] || []; enabled: view.active; onActivated: view.doc.zoomStep(-1) }
    Shortcut { sequences: Shortcuts.keys["reader.nextTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: App.switchTab(1) }
    Shortcut { sequences: Shortcuts.keys["reader.previousTab"] || []; enabled: view.active && Reader.tabs.count > 1; onActivated: App.switchTab(-1) }
    Shortcut { sequences: ["Escape"]; enabled: view.active && findBar.visible; onActivated: findBar.hide() }
    Shortcut { sequences: ["Escape"]; enabled: view.active && view.reading && !findBar.visible; onActivated: view.stopReading() }
}
