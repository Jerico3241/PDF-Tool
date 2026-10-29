import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite von Novadesk (seit 5.0 Beta 2 nach dem freigegebenen Design): links die Navigation – »+ Neu« im blauen
// Verlauf aus dem App-Symbol, Start, Zuletzt verwendet, Datei öffnen, die Dateiarten und »Mehr« (Vorlagen, Alle
// Werkzeuge, Übersichten-Ersteller); ≡ in der Tab-Leiste blendet sie aus und ein. Rechts der gewählte Bereich:
// »Start« mit Willkommenskopf, den vier Karten (Neue Tabelle, Neuer Text, Neue Präsentation, PDF öffnen), den
// Schnellwerkzeugen und »Zuletzt verwendet« (Name, Ordner, Geöffnet); »Zuletzt verwendet« mit allen Einträgen; je
// Dateiart ihre zuletzt verwendeten Dateien; »Alle Werkzeuge« mit den Werkzeugen, Schnellwerkzeugen und der
// Ablagefläche.
Item {
    id: page
    objectName: "homePage"
    readonly property string section: App.homeSection
    readonly property real contentWidth: content.contentWidth
    readonly property bool wide: contentWidth >= Metrics.homeSideBySideFrom
    readonly property var kindTitles: ({ "text": "Texte", "tabelle": "Tabellen", "praesentation": "Präsentationen", "pdf": "PDFs" })
    readonly property string kindShown: section.indexOf("kind:") === 0 ? section.substring(5) : ""
    onSectionChanged: content.scrollToTop()

    function entriesOf(kind) {
        if (kind === "") return Reader.recent
        return Reader.recent.filter(function(entry) { return entry.kind === kind || (kind === "tabelle" && entry.kind === "csv") })
    }
    function createNew(kind) {
        if (kind === "tabelle") Reader.newSheet()
        else Reader.newOffice(kind)
    }

    // Eintrag der Navigation: Symbol (Fluent oder Dateiart), Name; gewählt: hinterlegt mit Akzentstrich links
    component NavItem: T.AbstractButton {
        id: navItem
        property string iconName: ""
        property url imageSource: ""
        property bool selected: false
        implicitHeight: 38
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(text, I18n.revision)
        Accessible.selected: selected
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        background: Rectangle {
            radius: Metrics.radiusControl
            color: navItem.selected ? Theme.navSelected : (navItem.pressed ? Theme.subtlePressed : (navItem.hovered ? Theme.subtleHover : "transparent"))
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            Rectangle {
                objectName: "navIndicator"
                x: 0
                anchors.verticalCenter: parent.verticalCenter
                width: 3
                height: 16
                radius: 1.5
                color: Theme.accent
                visible: navItem.selected
            }
            PFocusRing { visible: navItem.visualFocus; radius_: Metrics.radiusControl }
        }
        contentItem: Item {}
        Row {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            PIcon {
                anchors.verticalCenter: parent.verticalCenter
                name: navItem.iconName
                color: Theme.textPrimary
                visible: navItem.imageSource == ""
            }
            Image {
                anchors.verticalCenter: parent.verticalCenter
                width: Metrics.iconSize
                height: Metrics.iconSize
                source: navItem.imageSource
                sourceSize: Qt.size(Metrics.iconSize, Metrics.iconSize)
                visible: navItem.imageSource != ""
                Accessible.ignored: true
            }
            PText {
                anchors.verticalCenter: parent.verticalCenter
                text: I18n.tr(navItem.text, I18n.revision)
            }
        }
    }
    component NavHeading: PText {
        Layout.fillWidth: true
        Layout.leftMargin: 12
        Layout.topMargin: Metrics.s16
        Layout.bottomMargin: Metrics.s4
        textStyle: "caption"
        tone: "secondary"
        font.weight: Font.DemiBold
    }

    // Karte »Neu« bzw. »PDF öffnen«: oben eine Linie in der Farbe der Dateiart, Symbol, Name und Beschreibung
    component KindCard: T.AbstractButton {
        id: kindCard
        property string kind: ""
        property string title: ""
        property string description: ""
        implicitHeight: 91
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
            radius: Metrics.radiusControl + 2
            color: FileKinds.color(kindCard.kind)
            Rectangle {
                anchors.fill: parent
                anchors.topMargin: 3
                radius: Metrics.radiusControl + 2
                color: kindCard.pressed ? Theme.controlPressed : (kindCard.hovered ? Theme.controlHover : Theme.surface)
                border.width: 1
                border.color: Theme.border
                // oben gerade (an der farbigen Linie)
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 1
                    anchors.rightMargin: 1
                    height: Metrics.radiusControl + 2
                    color: parent.color
                }
            }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 22
            anchors.rightMargin: Metrics.s16
            anchors.topMargin: 3 + 14
            anchors.bottomMargin: Metrics.s12
            spacing: 18
            Image {
                objectName: "kindIcon"
                Layout.preferredWidth: 40
                Layout.preferredHeight: 40
                Layout.alignment: Qt.AlignTop
                source: FileKinds.image(kindCard.kind, 48)
                sourceSize: Qt.size(48, 48)
                fillMode: Image.PreserveAspectFit
                smooth: true
                scale: kindCard.hovered && Motion.moves ? 1.06 : 1
                Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
                Accessible.ignored: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: 2
                PText { Layout.fillWidth: true; text: I18n.tr(kindCard.title, I18n.revision); textStyle: "bodyStrong"; wrap: true }
                PText { Layout.fillWidth: true; text: I18n.tr(kindCard.description, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; font.pixelSize: 13 }
            }
        }
        PFocusRing { visible: kindCard.visualFocus; radius_: Metrics.radiusControl + 2 }
    }

    // Karte einer Vorlage (seit 5.0 Beta 6): oben das Vorschaubild (Anfang der ersten Seite bzw. die erste Folie), darunter
    // Dateiart, Name und Beschreibung
    component TemplateCard: T.AbstractButton {
        id: templateCard
        property var entry: ({})
        implicitWidth: 232
        implicitHeight: 262
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(entry.title || "", I18n.revision)
        Accessible.description: I18n.tr(entry.description || "", I18n.revision)
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        contentItem: Item {}
        background: Rectangle {
            radius: Metrics.radiusControl + 2
            color: templateCard.pressed ? Theme.controlPressed : (templateCard.hovered ? Theme.controlHover : Theme.surface)
            border.width: 1
            border.color: templateCard.hovered ? Theme.controlEdge : Theme.border
        }
        Rectangle {
            id: previewBox
            x: 8
            y: 8
            width: parent.width - 16
            height: 150
            radius: Metrics.radiusControl
            color: Theme.layer
            clip: true
            Image {
                objectName: "templatePreview"
                anchors.fill: parent
                anchors.margins: templateCard.entry.kind === "praesentation" ? 0 : 1
                source: templateCard.entry.key ? Qt.resolvedUrl("../../images/vorlagen/" + templateCard.entry.key + ".png") : ""
                fillMode: templateCard.entry.kind === "praesentation" ? Image.PreserveAspectFit : Image.PreserveAspectCrop
                verticalAlignment: Image.AlignTop
                smooth: true
                mipmap: true
                asynchronous: true
                Accessible.ignored: true
            }
            Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.width: 1; border.color: Theme.divider }
        }
        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: previewBox.bottom
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            anchors.topMargin: 10
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                spacing: 6
                Image {
                    Layout.preferredWidth: 16
                    Layout.preferredHeight: 16
                    source: FileKinds.image(templateCard.entry.kind || "", 16)
                    sourceSize: Qt.size(16, 16)
                    Accessible.ignored: true
                }
                PText { Layout.fillWidth: true; text: I18n.tr(templateCard.entry.title || "", I18n.revision); textStyle: "bodyStrong"; elide: Text.ElideRight }
            }
            PText {
                Layout.fillWidth: true
                text: I18n.tr(templateCard.entry.description || "", I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                wrap: true
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }
        PFocusRing { visible: templateCard.visualFocus; radius_: Metrics.radiusControl + 2 }
    }

    // Schaltfläche der Schnellwerkzeuge oben auf der Startseite: Rahmen, Symbol, Name (wie im Design)
    component StartTool: T.AbstractButton {
        id: startTool
        property string iconName: ""
        property string description: ""
        implicitHeight: Metrics.controlHeight
        implicitWidth: Math.ceil(startRow.implicitWidth) + 2 * 12
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: I18n.tr(text, I18n.revision)
        Accessible.description: I18n.tr(description, I18n.revision)
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        background: Rectangle {
            radius: Metrics.radiusControl
            color: startTool.pressed ? Theme.controlPressed : (startTool.hovered ? Theme.controlHover : Theme.control)
            border.width: 1
            border.color: Theme.controlStroke
            PFocusRing { visible: startTool.visualFocus; radius_: Metrics.radiusControl }
        }
        contentItem: Item {}
        Row {
            id: startRow
            anchors.centerIn: parent
            spacing: 8
            PIcon { anchors.verticalCenter: parent.verticalCenter; name: startTool.iconName; color: Theme.textPrimary }
            PText { anchors.verticalCenter: parent.verticalCenter; text: I18n.tr(startTool.text, I18n.revision) }
        }
        PToolTip { text: I18n.tr(startTool.description, I18n.revision); visible: startTool.hovered && startTool.description !== "" }
    }

    // Tabelle »Zuletzt verwendet« (Start und Dateiarten): Name mit Symbol, Ordner, Geöffnet – ein Klick öffnet die Datei
    component RecentTable: Rectangle {
        id: table
        property var entries: []
        property int limit: 0
        property string prefix: "homeStartRecent"
        readonly property var shown: limit > 0 ? entries.slice(0, limit) : entries
        readonly property bool showFolder: width >= Metrics.homeRecentFolderFrom
        readonly property real nameWidth: showFolder ? Math.floor((width - 2 * 16) * 0.45) : width - 2 * 16 - Metrics.homeRecentWhenWidth - 24
        readonly property real folderWidth: showFolder ? Math.floor((width - 2 * 16) * 0.32) : 0
        implicitHeight: tableColumn.implicitHeight
        radius: Metrics.radiusCard
        color: Theme.surface
        border.width: 1
        border.color: Theme.border
        ColumnLayout {
            id: tableColumn
            anchors.left: parent.left
            anchors.right: parent.right
            spacing: 0
            Item {
                objectName: table.prefix + "Header"
                Layout.fillWidth: true
                implicitHeight: 34
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    PText { width: table.nameWidth; text: I18n.tr("Name", I18n.revision); textStyle: "caption"; tone: "secondary" }
                    PText { width: table.folderWidth; visible: table.showFolder; text: I18n.tr("Ordner", I18n.revision); textStyle: "caption"; tone: "secondary" }
                    PText { text: I18n.tr("Geöffnet", I18n.revision); textStyle: "caption"; tone: "secondary" }
                }
            }
            Repeater {
                model: table.shown
                Item {
                    id: row
                    required property var modelData
                    required property int index
                    objectName: table.prefix + "_" + index
                    Layout.fillWidth: true
                    implicitHeight: 40
                    Accessible.role: Accessible.ListItem
                    Accessible.name: I18n.tr(modelData.name + (modelData.missing ? " (nicht mehr vorhanden)" : ""), I18n.revision)
                    Rectangle { anchors.left: parent.left; anchors.right: parent.right; height: 1; color: Theme.divider }
                    Rectangle {
                        anchors.fill: parent
                        anchors.topMargin: 1
                        radius: row.index === table.shown.length - 1 ? Metrics.radiusCard : 0
                        color: tap.pressed ? Theme.subtlePressed : (hover.hovered && !row.modelData.missing ? Theme.subtleHover : "transparent")
                    }
                    HoverHandler { id: hover; cursorShape: row.modelData.missing ? Qt.ArrowCursor : Qt.PointingHandCursor }
                    TapHandler { id: tap; enabled: !row.modelData.missing; onTapped: Reader.openRecent(row.modelData.path) }
                    PToolTip { text: I18n.tr(row.modelData.path, I18n.revision); visible: hover.hovered }
                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        Row {
                            width: table.nameWidth
                            spacing: 10
                            Image {
                                objectName: table.prefix + "Icon"
                                anchors.verticalCenter: parent.verticalCenter
                                width: 20
                                height: 20
                                source: FileKinds.image(row.modelData.kind || "pdf", 24)
                                sourceSize: Qt.size(20, 20)
                                opacity: row.modelData.missing ? 0.4 : 1
                                Accessible.ignored: true
                            }
                            PText {
                                anchors.verticalCenter: parent.verticalCenter
                                width: table.nameWidth - 30 - 12
                                text: I18n.tr(row.modelData.name, I18n.revision)
                                tone: row.modelData.missing ? "tertiary" : ""
                                elide: Text.ElideMiddle
                            }
                        }
                        PText {
                            anchors.verticalCenter: parent.verticalCenter
                            width: table.folderWidth - 12
                            visible: table.showFolder
                            text: I18n.tr(row.modelData.place || row.modelData.folder, I18n.revision)
                            tone: "secondary"
                            elide: Text.ElideMiddle
                        }
                        Item { width: 12; height: 1; visible: table.showFolder }
                        PText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: I18n.tr(row.modelData.missing ? "Nicht mehr vorhanden" : row.modelData.opened, I18n.revision)
                            tone: row.modelData.missing ? "tertiary" : "secondary"
                        }
                    }
                }
            }
        }
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


    // Navigation links
    Rectangle {
        id: nav
        objectName: "homeNav"
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: App.navOpen ? 240 : 0
        visible: width > 0
        clip: true
        color: Theme.background
        Behavior on width { enabled: Motion.moves; NumberAnimation { duration: Motion.pane; easing.type: Motion.decelerate } }
        Rectangle { anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 1; color: Theme.divider }

        ColumnLayout {
            x: 10
            y: 12
            width: 240 - 2 * 10 - 1
            spacing: 0

            // »+ Neu«: blauer Verlauf aus dem App-Symbol; öffnet das Menü mit den neuen Dateiarten
            T.AbstractButton {
                id: newButton
                objectName: "homeNewButton"
                Layout.fillWidth: true
                Layout.leftMargin: 2
                Layout.rightMargin: 2
                Layout.bottomMargin: 14
                implicitHeight: 36
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                text: I18n.tr("Neu", I18n.revision)
                Accessible.role: Accessible.ButtonMenu
                Accessible.name: I18n.tr("Neu", I18n.revision)
                onClicked: newMenu.opened ? newMenu.close() : newMenu.popup(newButton, 0, newButton.height + 4)
                background: Rectangle {
                    radius: Metrics.radiusControl + 2
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.brandStart }
                        GradientStop { position: 1; color: Theme.brandEnd }
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: newButton.pressed ? Qt.rgba(0, 0, 0, 0.12) : (newButton.hovered ? Qt.rgba(1, 1, 1, 0.08) : "transparent")
                    }
                    PFocusRing { visible: newButton.visualFocus; radius_: Metrics.radiusControl + 2 }
                }
                contentItem: Item {}
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10
                    PIcon { anchors.verticalCenter: parent.verticalCenter; name: "add"; color: "white" }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: I18n.tr("Neu", I18n.revision)
                        font: Typography.bodyStrong
                        color: "white"
                        textFormat: Text.PlainText
                    }
                }
            }
            PMenu {
                id: newMenu
                objectName: "homeNewMenu"
                PMenuItem { objectName: "homeNewSheet"; text: I18n.tr("Neue Tabelle", I18n.revision); hint: I18n.tr(Shortcuts.labels["app.new"] || "", I18n.revision); imageSource: FileKinds.image("tabelle", 16); onTriggered: newMenu.afterClose = function() { page.createNew("tabelle") } }
                PMenuItem { objectName: "homeNewText"; text: I18n.tr("Neuer Text", I18n.revision); imageSource: FileKinds.image("text", 16); onTriggered: newMenu.afterClose = function() { page.createNew("text") } }
                PMenuItem { objectName: "homeNewPresentation"; text: I18n.tr("Neue Präsentation", I18n.revision); imageSource: FileKinds.image("praesentation", 16); onTriggered: newMenu.afterClose = function() { page.createNew("praesentation") } }
                PMenuItem { objectName: "homeNewTemplate"; text: I18n.tr("Aus Vorlage …", I18n.revision); iconName: "book_template"; onTriggered: newMenu.afterClose = function() { App.showHomeSection("templates") } }
                PMenuItem { objectName: "homeNewImages"; text: I18n.tr("PDF aus Bildern", I18n.revision); imageSource: FileKinds.image("pdf", 16); onTriggered: newMenu.afterClose = function() { Reader.imagesToPdf() } }
            }

            NavItem { objectName: "navStart"; Layout.fillWidth: true; text: I18n.tr("Start", I18n.revision); iconName: "home"; selected: page.section === "start"; onClicked: App.showHomeSection("start") }
            NavItem { objectName: "navRecent"; Layout.fillWidth: true; text: I18n.tr("Zuletzt verwendet", I18n.revision); iconName: "history"; selected: page.section === "recent"; onClicked: App.showHomeSection("recent") }
            NavItem { objectName: "navOpen"; Layout.fillWidth: true; text: I18n.tr("Datei öffnen", I18n.revision); iconName: "folder_open"; onClicked: Reader.openDialog() }
            NavHeading { text: I18n.tr("Dateiarten", I18n.revision) }
            Repeater {
                model: [
                    { kind: "text", title: "Texte" },
                    { kind: "tabelle", title: "Tabellen" },
                    { kind: "praesentation", title: "Präsentationen" },
                    { kind: "pdf", title: "PDFs" }
                ]
                NavItem {
                    required property var modelData
                    objectName: "navKind_" + modelData.kind
                    Layout.fillWidth: true
                    text: I18n.tr(modelData.title, I18n.revision)
                    imageSource: FileKinds.image(modelData.kind, 16)
                    selected: page.section === "kind:" + modelData.kind
                    onClicked: App.showHomeSection("kind:" + modelData.kind)
                }
            }
            NavHeading { text: I18n.tr("Mehr", I18n.revision) }
            NavItem { objectName: "navTemplates"; Layout.fillWidth: true; text: I18n.tr("Vorlagen", I18n.revision); iconName: "library"; selected: page.section === "templates"; onClicked: App.showHomeSection("templates") }
            NavItem { objectName: "navTools"; Layout.fillWidth: true; text: I18n.tr("Alle Werkzeuge", I18n.revision); iconName: "toolbox"; selected: page.section === "tools"; onClicked: App.showHomeSection("tools") }
            NavItem { objectName: "navContracts"; Layout.fillWidth: true; text: I18n.tr("Übersichten-Ersteller", I18n.revision); iconName: "document_table"; onClicked: App.openTool("contracts") }
        }
    }

    PPage {
        id: content
        anchors.left: nav.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        centered: true
        maxContentWidth: Metrics.homeMaxWidth

        // Hinweise nach dem Start (z. B. Ergebnis einer Wiederherstellung) und zum Öffnen von Dateien
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

        // Start --------------------------------------------------------------------------------------------------
        ColumnLayout {
            objectName: "homeStart"
            Layout.fillWidth: true
            spacing: 0
            visible: page.section === "start"

            // Willkommenskopf: Name und Satz links, rechts das App-Symbol (die bunten Seiten als Erkennungszeichen)
            Rectangle {
                objectName: "homeHero"
                Layout.fillWidth: true
                implicitHeight: 120
                radius: Metrics.radiusCard + 4
                border.width: 1
                border.color: Theme.border
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.heroStart }
                    GradientStop { position: 1; color: Theme.heroEnd }
                }
                ColumnLayout {
                    anchors.left: parent.left
                    anchors.right: heroImage.left
                    anchors.leftMargin: 29
                    anchors.rightMargin: Metrics.s16
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6
                    PText {
                        objectName: "homeTitle"
                        Layout.fillWidth: true
                        text: I18n.tr("Willkommen bei " + App.appName, I18n.revision)
                        textStyle: "title"
                        elide: Text.ElideRight
                        Accessible.role: Accessible.Heading
                    }
                    PText {
                        Layout.fillWidth: true
                        text: I18n.tr("Tabellen, Texte, Präsentationen und PDFs, alles lokal auf diesem PC.", I18n.revision)
                        tone: "secondary"
                        wrap: true
                    }
                }
                Image {
                    id: heroImage
                    objectName: "homeHeroImage"
                    anchors.right: parent.right
                    anchors.rightMargin: 44
                    anchors.verticalCenter: parent.verticalCenter
                    width: page.contentWidth >= 560 ? 112 : 0
                    height: 112
                    visible: width > 0
                    source: Qt.resolvedUrl("../../images/app-96.png")
                    sourceSize: Qt.size(224, 224)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    mipmap: true
                    Accessible.ignored: true
                }
            }

            GridLayout {
                id: kinds
                objectName: "homeKinds"
                Layout.fillWidth: true
                Layout.topMargin: 22
                columns: page.contentWidth >= 820 ? 4 : 2
                columnSpacing: 13
                rowSpacing: 13
                uniformCellWidths: true
                Repeater {
                    model: [
                        { kind: "tabelle", title: "Neue Tabelle", description: "Wie Excel (.xlsx)" },
                        { kind: "text", title: "Neuer Text", description: "Wie Word (.docx)" },
                        { kind: "praesentation", title: "Neue Präsentation", description: "Wie PowerPoint (.pptx)" },
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
                        onClicked: modelData.kind === "pdf" ? Reader.openKind("pdf") : page.createNew(modelData.kind)
                    }
                }
            }

            PText {
                Layout.topMargin: 26
                Layout.bottomMargin: 10
                text: I18n.tr("Schnellwerkzeuge", I18n.revision)
                textStyle: "bodyStrong"
                font.pixelSize: 15
                font.weight: Font.DemiBold
                Accessible.role: Accessible.Heading
            }
            Flow {
                objectName: "homeStartTools"
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: Reader.startTools
                    StartTool {
                        required property var modelData
                        objectName: "startTool_" + modelData.action
                        text: I18n.tr(modelData.title, I18n.revision)
                        iconName: modelData.icon
                        description: I18n.tr(modelData.description, I18n.revision)
                        onClicked: Reader.quickTool(modelData.action)
                    }
                }
            }

            PText {
                Layout.topMargin: 26
                Layout.bottomMargin: 10
                text: I18n.tr("Zuletzt verwendet", I18n.revision)
                textStyle: "bodyStrong"
                font.pixelSize: 15
                font.weight: Font.DemiBold
                Accessible.role: Accessible.Heading
            }
            RecentTable {
                objectName: "homeStartRecent"
                Layout.fillWidth: true
                visible: Reader.recent.length > 0
                entries: Reader.recent
                limit: 6
            }
            PText {
                objectName: "homeStartRecentEmpty"
                Layout.fillWidth: true
                visible: Reader.recent.length === 0
                text: I18n.tr("Noch keine Dateien geöffnet. Geöffnete Dateien erscheinen hier – ein Klick öffnet sie wieder.", I18n.revision)
                tone: "secondary"
                wrap: true
            }
        }

        // Eine Dateiart: »Neu …« und »Öffnen …«, darunter ihre zuletzt verwendeten Dateien -----------------------
        ColumnLayout {
            objectName: "homeKind"
            Layout.fillWidth: true
            spacing: 0
            visible: page.kindShown !== ""
            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: Metrics.s16
                spacing: Metrics.s8
                Image {
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 32
                    source: page.kindShown !== "" ? FileKinds.image(page.kindShown, 32) : ""
                    sourceSize: Qt.size(32, 32)
                    Accessible.ignored: true
                }
                PText {
                    objectName: "homeKindTitle"
                    Layout.fillWidth: true
                    text: I18n.tr(page.kindTitles[page.kindShown] || "", I18n.revision)
                    textStyle: "title"
                    Accessible.role: Accessible.Heading
                }
                PButton {
                    objectName: "homeKindNew"
                    kind: "accent"
                    iconName: "add"
                    visible: page.kindShown !== "pdf"
                    text: I18n.tr(page.kindShown === "tabelle" ? "Neue Tabelle" : (page.kindShown === "text" ? "Neuer Text" : "Neue Präsentation"), I18n.revision)
                    onClicked: page.createNew(page.kindShown)
                }
                PButton {
                    objectName: "homeKindOpen"
                    kind: page.kindShown === "pdf" ? "accent" : "standard"
                    iconName: "folder_open"
                    text: I18n.tr("Öffnen …", I18n.revision)
                    onClicked: Reader.openKind(page.kindShown)
                }
            }
            RecentTable {
                objectName: "homeKindRecent"
                prefix: "homeKindRecent"
                Layout.fillWidth: true
                entries: page.entriesOf(page.kindShown)
                visible: entries.length > 0
            }
            PText {
                Layout.fillWidth: true
                visible: page.entriesOf(page.kindShown).length === 0
                text: I18n.tr("Noch keine Dateien dieser Art geöffnet.", I18n.revision)
                tone: "secondary"
                wrap: true
            }
        }

        // Zuletzt verwendet (alle Einträge, mit Filter, Größe, »Im Ordner zeigen« und »Liste leeren«) --------------
        ColumnLayout {
            objectName: "homeRecentSection"
            Layout.fillWidth: true
            spacing: 0
            visible: page.section === "recent"
            // Zuletzt verwendet: nur Pfade, Zeitpunkt und Größe (keine Inhalte); leeren lässt sich die Liste jederzeit. Über der
            // Liste lässt sie sich nach Dateiart filtern (Tabellen schließen CSV ein).
            PCard {
                id: recentCard
                objectName: "homeRecent"
                Layout.fillWidth: true
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

        }

        // Vorlagen (seit 5.0 Beta 6): neue Texte, Tabellen und Präsentationen aus einer Vorlage ------------------------
        ColumnLayout {
            id: templatesSection
            objectName: "homeTemplates"
            Layout.fillWidth: true
            spacing: 0
            visible: page.section === "templates"
            property string kindFilter: ""
            readonly property var entries: kindFilter === "" ? Reader.officeTemplates
                                                             : Reader.officeTemplates.filter(function(entry) { return entry.kind === kindFilter })
            PText {
                objectName: "homeTemplatesTitle"
                Layout.fillWidth: true
                text: I18n.tr("Vorlagen", I18n.revision)
                textStyle: "title"
                Accessible.role: Accessible.Heading
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: Metrics.s4
                text: I18n.tr("Ein Klick legt ein neues Dokument an. Die Felder in [eckigen Klammern] ersetzen Sie durch Ihre Angaben.", I18n.revision)
                tone: "secondary"
                wrap: true
            }
            Flow {
                objectName: "homeTemplatesKinds"
                Layout.fillWidth: true
                Layout.topMargin: Metrics.s16
                Layout.bottomMargin: Metrics.s12
                spacing: Metrics.s4
                Repeater {
                    model: [
                        { key: "", label: "Alle" },
                        { key: "text", label: "Texte" },
                        { key: "tabelle", label: "Tabellen" },
                        { key: "praesentation", label: "Präsentationen" }
                    ]
                    PButton {
                        required property var modelData
                        objectName: "homeTemplatesKind_" + (modelData.key || "alle")
                        kind: "subtle"
                        toggle: true
                        checked: templatesSection.kindFilter === modelData.key
                        text: I18n.tr(modelData.label, I18n.revision)
                        onClicked: templatesSection.kindFilter = modelData.key
                    }
                }
            }
            // Karten gleich breit auf ganzen Pixeln, so viele nebeneinander, wie hineinpassen (mindestens 200 px breit)
            Item {
                Layout.fillWidth: true
                implicitHeight: templateGrid.implicitHeight
                GridLayout {
                    id: templateGrid
                    objectName: "homeTemplateGrid"
                    readonly property int available: Math.floor(parent.width)
                    width: available
                    columns: Math.max(1, Math.min(4, Math.floor((available + columnSpacing) / (200 + columnSpacing))))
                    readonly property int cardWidth: Math.floor((available - (columns - 1) * columnSpacing) / columns)
                    columnSpacing: Metrics.s12
                    rowSpacing: Metrics.s12
                    Repeater {
                        model: templatesSection.entries
                        TemplateCard {
                            required property var modelData
                            objectName: "homeTemplate_" + modelData.key
                            Layout.preferredWidth: templateGrid.cardWidth
                            entry: modelData
                            onClicked: Reader.newFromTemplate(modelData.key)
                        }
                    }
                }
            }
            // Die Vorlagen der Vertragsübersichten bleiben, wo sie waren
            RowLayout {
                objectName: "homeTemplatesContracts"
                Layout.fillWidth: true
                Layout.topMargin: Metrics.s20
                spacing: Metrics.s8
                PIcon { name: "document_table"; color: Theme.textSecondary }
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("Vorlagen für Vertragsübersichten verwalten Sie im Übersichten-Ersteller.", I18n.revision)
                    tone: "secondary"
                    wrap: true
                }
                PButton {
                    objectName: "homeTemplatesContractsOpen"
                    kind: "subtle"
                    text: I18n.tr("Übersichten-Vorlagen öffnen", I18n.revision)
                    onClicked: App.openTool("templates")
                }
            }
        }

        // Alle Werkzeuge: Werkzeuge mit Schnellwerkzeugen und die Ablagefläche --------------------------------------
        ColumnLayout {
            objectName: "homeToolsSection"
            Layout.fillWidth: true
            spacing: 0
            visible: page.section === "tools"
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
    }
}
