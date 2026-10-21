import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite (⌂ in der Tab-Leiste) von Novadesk: oben der Willkommenskopf mit dem App-Symbol, darunter je Dateiart
// eine Karte in ihrer Farbe (Tabelle, Text, Präsentation, PDF öffnen), dann die Werkzeuge in einer Karte und daneben
// die Ablagefläche zum Öffnen, darunter »Zuletzt verwendet« (Name, Ordner, wann geöffnet, Größe; nach Dateiart filterbar).
// Die Gruppe steht mittig und ist höchstens ``Metrics.homeMaxWidth`` breit; bei schmalem Fenster stehen
// Werkzeuge und Ablagefläche untereinander, die Werkzeuge in einer Spalte. In der Karte der Werkzeuge stehen
// darunter die Schnellwerkzeuge (PDF wählen, das Werkzeug startet im Reader) – vier, zwei oder eine Spalte.
PPage {
    id: page
    objectName: "homePage"
    centered: true
    maxContentWidth: Metrics.homeMaxWidth
    readonly property bool wide: contentWidth >= Metrics.homeSideBySideFrom

    // Willkommenskopf: Name und Satz links, rechts das App-Symbol (die bunten Seiten als Erkennungszeichen)
    Rectangle {
        objectName: "homeHero"
        Layout.fillWidth: true
        Layout.bottomMargin: Metrics.toolCardGap
        implicitHeight: Math.max(heroText.implicitHeight, 96) + 2 * Metrics.s24
        radius: Metrics.radiusCard + 4
        border.width: 1
        border.color: Theme.border
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.16 : 0.07) }
            GradientStop { position: 1; color: Theme.surface }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Metrics.s24 + Metrics.s4
            anchors.rightMargin: Metrics.s24 + Metrics.s4
            spacing: Metrics.s16
            ColumnLayout {
                id: heroText
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: Metrics.s4
                PText {
                    objectName: "homeTitle"
                    Layout.fillWidth: true
                    text: I18n.tr("Willkommen bei " + App.appName, I18n.revision)
                    textStyle: "title"
                    wrap: true
                    Accessible.role: Accessible.Heading
                }
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("Tabellen, Texte, Präsentationen und PDFs – alles lokal auf diesem PC.", I18n.revision)
                    tone: "secondary"
                    wrap: true
                }
            }
            Image {
                objectName: "homeHeroImage"
                Layout.preferredWidth: 96
                Layout.preferredHeight: 96
                Layout.alignment: Qt.AlignVCenter
                visible: page.contentWidth >= 520
                source: Qt.resolvedUrl("../../images/app-96.png")
                sourceSize: Qt.size(96, 96)
                fillMode: Image.PreserveAspectFit
                smooth: true
                Accessible.ignored: true
            }
        }
    }

    // Hinweise nach dem Start (z. B. Ergebnis einer Wiederherstellung) und zum Öffnen von PDFs
    PInfoBar {
        objectName: "homeInfo"
        Layout.fillWidth: true
        Layout.bottomMargin: shown ? Metrics.s12 : 0
        topMargin: 0
        notice: Notices.area("home_info")
    }
    PInfoBar {
        objectName: "homeReaderInfo"
        Layout.fillWidth: true
        Layout.bottomMargin: shown ? Metrics.s12 : 0
        topMargin: 0
        notice: Notices.area("reader")
    }

    // Ein Werkzeug in der Karte: Symbol, Name, Beschreibung, »Öffnen ›« und Tastenkürzel. Die ganze Fläche ist
    // anklickbar; Zeigen hinterlegt sie leicht, der Pfeil rückt ein Stück vor.
    component HomeTool: T.AbstractButton {
        id: tool
        property string iconName: ""
        property string title: ""
        property string description: ""
        property string shortcut: ""
        // Breite, die Symbol und Fußzeile mindestens brauchen – und das längste Wort von Name und Beschreibung: Beide
        // brechen zwischen Wörtern um, nie mitten in einem Wort (sonst stehen die Werkzeuge untereinander)
        readonly property int minimumWidth: {
            titleMetrics.font  // neu messen, wenn sich die Schrift ändert
            descriptionMetrics.font
            var widest = 0
            var words = title.split(" ")
            for (var i = 0; i < words.length; ++i)
                widest = Math.max(widest, titleMetrics.advanceWidth(words[i]))
            words = description.split(" ")
            for (var j = 0; j < words.length; ++j)
                widest = Math.max(widest, descriptionMetrics.advanceWidth(words[j]))
            return 3 * Metrics.s12 + 40 + Math.max(Math.ceil(footer.implicitWidth), Math.ceil(widest) + 2)
        }
        FontMetrics { id: titleMetrics; font: Typography.bodyStrong }
        FontMetrics { id: descriptionMetrics; font: Typography.caption }
        implicitHeight: Math.ceil(toolColumn.implicitHeight) + 2 * Metrics.s12
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(title, I18n.revision)
        Accessible.description: I18n.tr(description, I18n.revision)
        background: PListItem { hovered: tool.hovered; pressed: tool.pressed; focused: tool.visualFocus; radius: Metrics.radiusCard }
        contentItem: Item {}
        RowLayout {
            anchors.fill: parent
            anchors.margins: Metrics.s12
            spacing: Metrics.s12
            Rectangle {
                objectName: "toolIcon"
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 40
                Layout.preferredHeight: 40
                radius: Metrics.radiusCard
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.18 : 0.10)
                PIcon { anchors.centerIn: parent; name: tool.iconName; size: Metrics.iconSizeMedium; color: Theme.accentText }
            }
            ColumnLayout {
                id: toolColumn
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: Metrics.s4
                PText { objectName: "toolTitle"; Layout.fillWidth: true; text: I18n.tr(tool.title, I18n.revision); textStyle: "bodyStrong"; wrap: true }
                PText { objectName: "toolDescription"; Layout.fillWidth: true; text: I18n.tr(tool.description, I18n.revision); tone: "secondary"; textStyle: "caption"; wrap: true }
                Item { Layout.fillHeight: true }  // Fußzeile unten – bei allen Werkzeugen auf derselben Höhe
                RowLayout {
                    id: footer
                    Layout.fillWidth: true
                    Layout.topMargin: Metrics.s4
                    spacing: Metrics.s6
                    PText { objectName: "toolOpen"; text: I18n.tr("Öffnen", I18n.revision); tone: "accent" }
                    PIcon {
                        name: "chevron_right"
                        size: 12
                        color: Theme.accentText
                        // rückt nur sichtbar vor – die Anordnung (und damit die Spalten) ändert sich beim Zeigen nicht
                        transform: Translate {
                            x: tool.hovered && Motion.moves ? 3 : 0
                            Behavior on x { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
                        }
                    }
                    Item { Layout.fillWidth: true }
                    PText { objectName: "toolShortcut"; text: I18n.tr(tool.shortcut, I18n.revision); textStyle: "caption"; tone: "tertiary"; visible: text !== "" }
                }
            }
        }
    }

    // Ein Schnellwerkzeug: Symbol und Name (bricht bei Bedarf in eine zweite Zeile um), die Beschreibung im Tooltip.
    // Ein Klick wählt eine PDF; sie öffnet sich im Reader, und das Werkzeug startet. Zeigen hinterlegt die Fläche, das
    // Symbol wächst leicht (nur »Vollständig«).
    component QuickTool: T.AbstractButton {
        id: quick
        property string iconName: ""
        property string title: ""
        property string description: ""
        // Breite, die Symbol und das längste Wort des Namens mindestens brauchen
        readonly property int minimumWidth: {
            quickMetrics.font  // neu messen, wenn sich die Schrift ändert
            var widest = 0
            var words = title.split(" ")
            for (var i = 0; i < words.length; ++i)
                widest = Math.max(widest, quickMetrics.advanceWidth(words[i]))
            return Metrics.s12 + 32 + 2 * Metrics.s8 + Math.ceil(widest) + 2
        }
        implicitHeight: Math.max(32, Math.ceil(quickLabel.implicitHeight)) + 2 * Metrics.s8
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(title, I18n.revision)
        Accessible.description: I18n.tr(description, I18n.revision)
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        background: PListItem { hovered: quick.hovered; pressed: quick.pressed; focused: quick.visualFocus; radius: Metrics.radiusCard }
        contentItem: Item {}
        FontMetrics { id: quickMetrics; font: Typography.body }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Metrics.s12  // Symbole auf einer Linie mit denen der Werkzeuge darüber
            anchors.rightMargin: Metrics.s8
            spacing: Metrics.s8
            Rectangle {
                objectName: "quickToolIcon"
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                Layout.alignment: Qt.AlignVCenter
                radius: Metrics.radiusControl + 2
                color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.18 : 0.10)
                scale: quick.hovered && Motion.moves ? 1.08 : 1
                Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
                PIcon { anchors.centerIn: parent; name: quick.iconName; size: Metrics.iconSizeMedium; color: Theme.accentText }
            }
            PText {
                id: quickLabel
                objectName: "quickToolTitle"
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                text: I18n.tr(quick.title, I18n.revision)
                wrap: true
                maximumLineCount: 2
            }
        }
        PToolTip { text: I18n.tr(quick.description, I18n.revision); visible: quick.hovered && quick.description !== "" }
    }

    // Eine Dateiart: oben eine Linie in ihrer Farbe, Symbol, Name und Endungen. Ein Klick wählt eine Datei dieser Art;
    // sie öffnet sich in einem eigenen Tab (Texte, Tabellen und Präsentationen vorerst als Ansicht).
    component KindCard: T.AbstractButton {
        id: kindCard
        property string kind: ""
        property string title: ""
        property string description: ""
        implicitHeight: Math.max(48, Math.ceil(kindColumn.implicitHeight)) + 2 * Metrics.s16 + 3
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(title, I18n.revision)
        Accessible.description: I18n.tr(description, I18n.revision)
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        contentItem: Item {}
        // Farbige Oberkante wie »border-top« an einer runden Karte: die Karte liegt 3 px tiefer auf einer Fläche in
        // der Farbe der Dateiart
        background: Rectangle {
            objectName: "kindLine"
            radius: Metrics.radiusCard
            color: FileKinds.color(kindCard.kind)
            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 3
                radius: Metrics.radiusCard
                color: kindCard.pressed ? Theme.controlPressed : (kindCard.hovered ? Theme.controlHover : Theme.surface)
                border.width: 1
                border.color: Theme.border
            }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Metrics.s16
            anchors.rightMargin: Metrics.s16
            anchors.topMargin: Metrics.s16 + 3
            anchors.bottomMargin: Metrics.s16
            spacing: Metrics.s12
            Image {
                objectName: "kindIcon"
                Layout.preferredWidth: 48
                Layout.preferredHeight: 48
                Layout.alignment: Qt.AlignTop
                source: FileKinds.image(kindCard.kind, 48)
                sourceSize: Qt.size(48, 48)
                scale: kindCard.hovered && Motion.moves ? 1.06 : 1
                Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
                Accessible.ignored: true
            }
            ColumnLayout {
                id: kindColumn
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: Metrics.s4
                PText { Layout.fillWidth: true; text: I18n.tr(kindCard.title, I18n.revision); textStyle: "bodyStrong"; wrap: true }
                PText { Layout.fillWidth: true; text: I18n.tr(kindCard.description, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true }
            }
        }
        PFocusRing { visible: kindCard.visualFocus; radius_: Metrics.radiusCard }
    }

    GridLayout {
        id: kinds
        objectName: "homeKinds"
        Layout.fillWidth: true
        Layout.bottomMargin: Metrics.toolCardGap
        columns: page.contentWidth >= 820 ? 4 : 2
        columnSpacing: Metrics.toolCardGap
        rowSpacing: Metrics.toolCardGap
        uniformCellWidths: true
        Repeater {
            model: [
                { kind: "tabelle", title: "Tabelle öffnen", description: "Excel, OpenDocument und CSV (.xlsx, .ods, .csv)" },
                { kind: "text", title: "Text öffnen", description: "Word, OpenDocument und RTF (.docx, .odt, .rtf)" },
                { kind: "praesentation", title: "Präsentation öffnen", description: "PowerPoint und OpenDocument (.pptx, .odp)" },
                { kind: "pdf", title: "PDF öffnen", description: "Lesen, bearbeiten, vergleichen" }
            ]
            KindCard {
                required property var modelData
                objectName: "kindCard_" + modelData.kind
                Layout.fillWidth: true
                Layout.fillHeight: true
                kind: modelData.kind
                title: I18n.tr(modelData.title, I18n.revision)
                description: I18n.tr(modelData.description, I18n.revision)
                onClicked: Reader.openKind(modelData.kind)
            }
        }
    }

    GridLayout {
        id: top
        objectName: "homeTop"
        Layout.fillWidth: true
        columns: page.wide ? 2 : 1
        columnSpacing: Metrics.toolCardGap
        rowSpacing: Metrics.toolCardGap

        PCard {
            id: toolsCard
            objectName: "homeTools"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.alignment: Qt.AlignTop
            title: I18n.tr("Werkzeuge", I18n.revision)
            iconName: "toolbox"
            // Werkzeuge gleich breit auf ganzen Pixeln, die Gruppe mittig in der Karte (Rest höchstens 2 px). Die Hülle
            // bekommt die ganze Breite der Karte – ein Raster mit fester Breite begrenzte sonst die Spalte der Karte.
            Item {
                Layout.fillWidth: true
                implicitHeight: toolGrid.implicitHeight
                GridLayout {
                    id: toolGrid
                    objectName: "homeToolGrid"
                    readonly property int available: Math.floor(parent.width)
                    readonly property int toolWidth: Math.max(0, Math.floor((available - (columns - 1) * columnSpacing) / columns))
                    // Nebeneinander nur, wenn jedes Werkzeug seine Fußzeile ganz zeigen kann (Schrift und Skalierung
                    // bestimmen die Breite) – sonst untereinander statt über den Rand hinaus
                    property int toolMinimum: 0
                    function measure() {
                        var most = 0
                        for (var i = 0; i < children.length; ++i)
                            if (children[i].minimumWidth !== undefined)
                                most = Math.max(most, children[i].minimumWidth)
                        toolMinimum = most
                    }
                    x: Math.floor((available - width) / 2)
                    width: columns * toolWidth + (columns - 1) * columnSpacing
                    height: implicitHeight
                    columns: toolsCard.width >= Metrics.homeToolsInRowFrom && Math.floor((available - 3 * columnSpacing) / 4) >= toolMinimum ? 4 : (Math.floor((available - columnSpacing) / 2) >= toolMinimum ? 2 : 1)
                    columnSpacing: Metrics.s8
                    rowSpacing: Metrics.s4
                    Repeater {
                        model: App.tools
                        HomeTool {
                            required property var modelData
                            objectName: "toolCard_" + modelData.key
                            Layout.preferredWidth: toolGrid.toolWidth
                            Layout.fillHeight: true
                            iconName: modelData.icon
                            title: I18n.tr(modelData.title, I18n.revision)
                            description: I18n.tr(modelData.description, I18n.revision)
                            shortcut: Shortcuts.labels["app." + modelData.key] || ""
                            // Reader ohne geöffnetes Dokument: Dateiauswahl (er zeigt Dokumente, keine eigene Seite)
                            onClicked: App.openTool(modelData.key)
                            onMinimumWidthChanged: toolGrid.measure()
                            Component.onCompleted: toolGrid.measure()
                        }
                    }
                }
            }

            // Schnellwerkzeuge: PDF wählen – sie öffnet sich im Reader, und das Werkzeug startet sofort
            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: Metrics.s12
                Layout.bottomMargin: Metrics.s12
                implicitHeight: 1
                color: Theme.divider
            }
            RowLayout {
                objectName: "homeQuickHeader"
                Layout.fillWidth: true
                Layout.bottomMargin: Metrics.s8
                spacing: Metrics.s8
                PText { text: I18n.tr("Schnellwerkzeuge", I18n.revision); textStyle: "bodyStrong"; Accessible.role: Accessible.Heading }
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("PDF wählen – sie öffnet sich im Reader, das Werkzeug startet sofort.", I18n.revision)
                    textStyle: "caption"
                    tone: "secondary"
                }
            }
            // Gleich breite Felder auf ganzen Pixeln: fünf Spalten, sonst zwei bzw. eine – nie schmaler, als Symbol und das
            // längste Wort eines Namens brauchen. Die Hülle bekommt die ganze Breite der Karte (wie bei den Werkzeugen).
            Item {
                Layout.fillWidth: true
                implicitHeight: quickGrid.implicitHeight
                GridLayout {
                    id: quickGrid
                    objectName: "homeQuickGrid"
                    readonly property int available: Math.floor(parent.width)
                    readonly property int tileWidth: Math.max(0, Math.floor((available - (columns - 1) * columnSpacing) / columns))
                    property int tileMinimum: 0
                    function measure() {
                        var most = 0
                        for (var i = 0; i < children.length; ++i)
                            if (children[i].minimumWidth !== undefined)
                                most = Math.max(most, children[i].minimumWidth)
                        tileMinimum = most
                    }
                    width: available
                    height: implicitHeight
                    columns: available >= 5 * tileMinimum + 4 * columnSpacing ? 5 : (available >= 2 * tileMinimum + columnSpacing ? 2 : 1)
                    columnSpacing: Metrics.s8
                    rowSpacing: Metrics.s4
                    Repeater {
                        model: Reader.quickTools
                        QuickTool {
                            required property var modelData
                            objectName: "quickTool_" + modelData.action
                            Layout.preferredWidth: quickGrid.tileWidth
                            Layout.fillHeight: true
                            iconName: modelData.icon
                            title: I18n.tr(modelData.title, I18n.revision)
                            description: I18n.tr(modelData.description, I18n.revision)
                            onClicked: Reader.quickTool(modelData.action)
                            onMinimumWidthChanged: quickGrid.measure()
                            Component.onCompleted: quickGrid.measure()
                        }
                    }
                }
            }
        }

        PDropZone {
            objectName: "homeDropZone"
            Layout.fillWidth: !page.wide
            Layout.fillHeight: page.wide
            Layout.preferredWidth: page.wide ? Metrics.homeDropWidth : -1
            highlighted: App.dragActive && App.dragAccepted
            iconName: "document_pdf"
            title: I18n.tr(Reader.opening > 0 ? "Wird geöffnet …" : "Datei hierher ziehen", I18n.revision)
            text: I18n.tr("oder eine Datei auswählen. Jede Datei öffnet sich in einem eigenen Tab, Bilder werden zu einer PDF.", I18n.revision)
            actions: [
                PButton {
                    objectName: "homeOpenButton"
                    kind: "accent"
                    iconName: "folder_open"
                    text: I18n.tr("Datei öffnen", I18n.revision)
                    tip: I18n.tr(Shortcuts.labels["app.open"], I18n.revision)
                    busy: Reader.opening > 0
                    onClicked: Reader.openDialog()
                }
            ]
        }
    }

    // Zuletzt verwendet: nur Pfade, Zeitpunkt und Größe (keine Inhalte); leeren lässt sich die Liste jederzeit. Über der
    // Liste lässt sie sich nach Dateiart filtern (Tabellen schließen CSV ein).
    PCard {
        id: recentCard
        objectName: "homeRecent"
        Layout.fillWidth: true
        Layout.topMargin: Metrics.toolCardGap
        title: I18n.tr("Zuletzt verwendet", I18n.revision)
        iconName: "history"
        readonly property bool showFolder: width >= Metrics.homeRecentFolderFrom
        property string kindFilter: ""
        readonly property var entries: {
            var filter = kindFilter
            if (filter === "") return Reader.recent
            return Reader.recent.filter(function(entry) { return entry.kind === filter || (filter === "tabelle" && entry.kind === "csv") })
        }
        // Spalten (Kopf und Zeilen gleich): Symbol, Name, Ordner, Geöffnet, Größe, zwei Schaltflächen
        readonly property int buttonsWidth: 2 * Metrics.controlHeight + Metrics.s12  // zwei Schaltflächen mit Abstand
        readonly property int gaps: (showFolder ? 5 : 4) * Metrics.s12
        readonly property real textColumns: Math.max(0, body.width - 12 - 4 - Metrics.iconSizeLarge - buttonsWidth - Metrics.homeRecentWhenWidth - Metrics.homeRecentSizeWidth - gaps)
        readonly property real nameWidth: showFolder ? Math.floor(textColumns * 0.45) : textColumns
        readonly property real folderWidth: showFolder ? textColumns - nameWidth : 0
        headerRight: PButton {
            objectName: "homeRecentClear"
            kind: "subtle"
            iconName: "delete"
            text: I18n.tr("Liste leeren", I18n.revision)
            visible: Reader.recent.length > 0
            onClicked: Reader.clearRecent()
        }
        PText {
            objectName: "homeRecentEmpty"
            Layout.fillWidth: true
            visible: Reader.recent.length === 0
            text: I18n.tr("Noch keine Dateien geöffnet. Geöffnete Dateien erscheinen hier – ein Klick öffnet sie wieder.", I18n.revision)
            tone: "secondary"
            wrap: true
        }
        Flow {
            objectName: "homeRecentKinds"
            Layout.fillWidth: true
            spacing: Metrics.s4
            visible: Reader.recent.length > 0
            Repeater {
                model: [
                    { key: "", label: "Alle" },
                    { key: "text", label: "Texte" },
                    { key: "tabelle", label: "Tabellen" },
                    { key: "praesentation", label: "Präsentationen" },
                    { key: "pdf", label: "PDFs" }
                ]
                PButton {
                    required property var modelData
                    objectName: "homeRecentKind_" + (modelData.key || "alle")
                    kind: "subtle"
                    toggle: true
                    checked: recentCard.kindFilter === modelData.key
                    text: I18n.tr(modelData.label, I18n.revision)
                    onClicked: recentCard.kindFilter = modelData.key
                }
            }
        }
        PText {
            objectName: "homeRecentNone"
            Layout.fillWidth: true
            visible: Reader.recent.length > 0 && recentCard.entries.length === 0
            text: I18n.tr("Keine Dateien dieser Art in der Liste.", I18n.revision)
            tone: "secondary"
            wrap: true
        }
        // Spaltenköpfe (gleiche Spalten wie die Zeilen darunter)
        Item {
            objectName: "homeRecentHeader"
            Layout.fillWidth: true
            implicitHeight: headerRow.implicitHeight
            visible: recentCard.entries.length > 0
            RowLayout {
                id: headerRow
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 4
                spacing: Metrics.s12
                Item { Layout.preferredWidth: Metrics.iconSizeLarge }
                PText { Layout.preferredWidth: recentCard.nameWidth; text: I18n.tr("Name", I18n.revision); textStyle: "caption"; tone: "secondary" }
                PText { Layout.preferredWidth: recentCard.folderWidth; text: I18n.tr("Ordner", I18n.revision); textStyle: "caption"; tone: "secondary"; visible: recentCard.showFolder }
                PText { Layout.preferredWidth: Metrics.homeRecentWhenWidth; text: I18n.tr("Geöffnet", I18n.revision); textStyle: "caption"; tone: "secondary" }
                PText { Layout.preferredWidth: Metrics.homeRecentSizeWidth; text: I18n.tr("Größe", I18n.revision); textStyle: "caption"; tone: "secondary"; horizontalAlignment: Text.AlignRight }
                Item { Layout.preferredWidth: recentCard.buttonsWidth }
            }
        }
        Repeater {
            model: recentCard.entries
            Item {
                id: entry
                required property var modelData
                required property int index
                objectName: "homeRecent_" + index
                Layout.fillWidth: true
                implicitHeight: 44
                Accessible.role: Accessible.ListItem
                Accessible.name: I18n.tr(modelData.name + (modelData.missing ? " (nicht mehr vorhanden)" : ""), I18n.revision)
                PListItem { anchors.fill: parent; hovered: hover.hovered && !entry.modelData.missing; pressed: tap.pressed }
                HoverHandler { id: hover; cursorShape: entry.modelData.missing ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler { id: tap; enabled: !entry.modelData.missing; onTapped: Reader.openRecent(entry.modelData.path) }
                PToolTip { text: I18n.tr(entry.modelData.path, I18n.revision); visible: hover.hovered && !recentCard.showFolder }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 4
                    spacing: Metrics.s12
                    // Symbol der Dateiart (wie im Explorer); fehlt die Datei, ist es blass
                    Image {
                        objectName: "homeRecentIcon"
                        Layout.preferredWidth: Metrics.iconSizeLarge
                        Layout.preferredHeight: Metrics.iconSizeLarge
                        source: FileKinds.image(entry.modelData.kind || "pdf", 24)
                        sourceSize: Qt.size(Metrics.iconSizeLarge, Metrics.iconSizeLarge)
                        opacity: entry.modelData.missing ? 0.4 : 1
                        Accessible.ignored: true
                    }
                    PText { Layout.preferredWidth: recentCard.nameWidth; text: I18n.tr(entry.modelData.name, I18n.revision); tone: entry.modelData.missing ? "tertiary" : ""; elide: Text.ElideMiddle }
                    PText {
                        Layout.preferredWidth: recentCard.folderWidth
                        visible: recentCard.showFolder
                        text: I18n.tr(entry.modelData.folder, I18n.revision)
                        textStyle: "caption"
                        tone: "secondary"
                        elide: Text.ElideMiddle
                    }
                    PText {
                        Layout.preferredWidth: Metrics.homeRecentWhenWidth
                        text: I18n.tr(entry.modelData.missing ? "Nicht mehr vorhanden" : entry.modelData.opened, I18n.revision)
                        textStyle: "caption"
                        tone: entry.modelData.missing ? "tertiary" : "secondary"
                        elide: Text.ElideRight
                    }
                    PText {
                        Layout.preferredWidth: Metrics.homeRecentSizeWidth
                        text: I18n.tr(entry.modelData.size, I18n.revision)
                        textStyle: "caption"
                        tone: "secondary"
                        horizontalAlignment: Text.AlignRight
                    }
                    PIconButton {
                        iconName: "folder_open"
                        tip: I18n.tr("Im Ordner zeigen", I18n.revision)
                        enabled: !entry.modelData.missing
                        onClicked: Reader.showInFolder(entry.modelData.path)
                    }
                    PIconButton {
                        iconName: "dismiss"
                        tip: I18n.tr("Aus der Liste entfernen", I18n.revision)
                        onClicked: Reader.removeRecent(entry.modelData.path)
                    }
                }
            }
        }
    }

    RowLayout {
        objectName: "homePrivacy"
        Layout.fillWidth: true
        Layout.topMargin: Metrics.s20
        spacing: Metrics.s8
        PIcon {
            name: "shield"
            color: Theme.textSecondary
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 1
        }
        PText {
            text: I18n.tr("Alle Dateien werden lokal auf diesem PC verarbeitet. Es wird nichts hochgeladen. PDF-JavaScript wird nie ausgeführt. Gespeichert wird erst nach einer Prüfung der neuen Datei – das Original bleibt bei einem Fehler unverändert.", I18n.revision)
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
