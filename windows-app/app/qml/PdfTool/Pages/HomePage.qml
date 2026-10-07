import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite (⌂ in der Tab-Leiste) nach dem Vorbild von Adobe Acrobat: oben die Werkzeuge in einer Karte und
// daneben die Ablagefläche zum Öffnen, darunter »Zuletzt verwendet« (Name, Ordner, wann geöffnet, Größe).
// Die Gruppe steht mittig und ist höchstens ``Metrics.homeMaxWidth`` breit; bei schmalem Fenster stehen
// Werkzeuge und Ablagefläche untereinander, die Werkzeuge in einer Spalte.
PPage {
    id: page
    objectName: "homePage"
    title: "Willkommen bei " + App.appName
    subtitle: "Werkzeuge für PDF-Dateien – alle Dateien werden lokal auf diesem PC verarbeitet."
    centered: true
    maxContentWidth: Metrics.homeMaxWidth
    readonly property bool wide: contentWidth >= Metrics.homeSideBySideFrom

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
        // Breite, die Symbol und Fußzeile mindestens brauchen (Titel und Beschreibung brechen um)
        readonly property int minimumWidth: 3 * Metrics.s12 + 40 + Math.ceil(footer.implicitWidth)
        implicitHeight: Math.ceil(toolColumn.implicitHeight) + 2 * Metrics.s12
        hoverEnabled: true
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: title
        Accessible.description: description
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
                PText { objectName: "toolTitle"; Layout.fillWidth: true; text: tool.title; textStyle: "bodyStrong"; wrap: true }
                PText { objectName: "toolDescription"; Layout.fillWidth: true; text: tool.description; tone: "secondary"; textStyle: "caption"; wrap: true }
                Item { Layout.fillHeight: true }  // Fußzeile unten – bei allen Werkzeugen auf derselben Höhe
                RowLayout {
                    id: footer
                    Layout.fillWidth: true
                    Layout.topMargin: Metrics.s4
                    spacing: Metrics.s6
                    PText { objectName: "toolOpen"; text: "Öffnen"; tone: "accent" }
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
                    PText { objectName: "toolShortcut"; text: tool.shortcut; textStyle: "caption"; tone: "tertiary"; visible: text !== "" }
                }
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
            title: "Werkzeuge"
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
                    columns: toolsCard.width >= Metrics.homeToolsInRowFrom && Math.floor((available - 2 * columnSpacing) / 3) >= toolMinimum ? 3 : 1
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
                            title: modelData.title
                            description: modelData.description
                            shortcut: modelData.shortcut
                            // Reader ohne geöffnetes Dokument: Dateiauswahl (er zeigt Dokumente, keine eigene Seite)
                            onClicked: App.openTool(modelData.key)
                            onMinimumWidthChanged: toolGrid.measure()
                            Component.onCompleted: toolGrid.measure()
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
            title: Reader.opening > 0 ? "Wird geöffnet …" : "PDF hierher ziehen"
            text: "oder eine Datei auswählen. Mehrere PDFs öffnen sich in eigenen Tabs."
            actions: [
                PButton {
                    objectName: "homeOpenButton"
                    kind: "accent"
                    iconName: "folder_open"
                    text: "Datei öffnen"
                    tip: "Strg+O"
                    busy: Reader.opening > 0
                    onClicked: Reader.openDialog()
                }
            ]
        }
    }

    // Zuletzt verwendet: nur Pfade, Zeitpunkt und Größe (keine Inhalte); leeren lässt sich die Liste jederzeit
    PCard {
        id: recentCard
        objectName: "homeRecent"
        Layout.fillWidth: true
        Layout.topMargin: Metrics.toolCardGap
        title: "Zuletzt verwendet"
        iconName: "history"
        readonly property bool showFolder: width >= Metrics.homeRecentFolderFrom
        // Spalten (Kopf und Zeilen gleich): Symbol, Name, Ordner, Geöffnet, Größe, zwei Schaltflächen
        readonly property int buttonsWidth: 2 * Metrics.controlHeight + Metrics.s12  // zwei Schaltflächen mit Abstand
        readonly property int gaps: (showFolder ? 5 : 4) * Metrics.s12
        readonly property real textColumns: Math.max(0, body.width - 12 - 4 - Metrics.iconSizeMedium - buttonsWidth - Metrics.homeRecentWhenWidth - Metrics.homeRecentSizeWidth - gaps)
        readonly property real nameWidth: showFolder ? Math.floor(textColumns * 0.45) : textColumns
        readonly property real folderWidth: showFolder ? textColumns - nameWidth : 0
        headerRight: PButton {
            objectName: "homeRecentClear"
            kind: "subtle"
            iconName: "delete"
            text: "Liste leeren"
            visible: Reader.recent.length > 0
            onClicked: Reader.clearRecent()
        }
        PText {
            objectName: "homeRecentEmpty"
            Layout.fillWidth: true
            visible: Reader.recent.length === 0
            text: "Noch keine PDFs geöffnet. Geöffnete PDFs erscheinen hier – ein Klick öffnet sie wieder."
            tone: "secondary"
            wrap: true
        }
        // Spaltenköpfe (gleiche Spalten wie die Zeilen darunter)
        Item {
            objectName: "homeRecentHeader"
            Layout.fillWidth: true
            implicitHeight: headerRow.implicitHeight
            visible: Reader.recent.length > 0
            RowLayout {
                id: headerRow
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 4
                spacing: Metrics.s12
                Item { Layout.preferredWidth: Metrics.iconSizeMedium }
                PText { Layout.preferredWidth: recentCard.nameWidth; text: "Name"; textStyle: "caption"; tone: "secondary" }
                PText { Layout.preferredWidth: recentCard.folderWidth; text: "Ordner"; textStyle: "caption"; tone: "secondary"; visible: recentCard.showFolder }
                PText { Layout.preferredWidth: Metrics.homeRecentWhenWidth; text: "Geöffnet"; textStyle: "caption"; tone: "secondary" }
                PText { Layout.preferredWidth: Metrics.homeRecentSizeWidth; text: "Größe"; textStyle: "caption"; tone: "secondary"; horizontalAlignment: Text.AlignRight }
                Item { Layout.preferredWidth: recentCard.buttonsWidth }
            }
        }
        Repeater {
            model: Reader.recent
            Item {
                id: entry
                required property var modelData
                required property int index
                objectName: "homeRecent_" + index
                Layout.fillWidth: true
                implicitHeight: 44
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.name + (modelData.missing ? " (nicht mehr vorhanden)" : "")
                PListItem { anchors.fill: parent; hovered: hover.hovered && !entry.modelData.missing; pressed: tap.pressed }
                HoverHandler { id: hover; cursorShape: entry.modelData.missing ? Qt.ArrowCursor : Qt.PointingHandCursor }
                TapHandler { id: tap; enabled: !entry.modelData.missing; onTapped: Reader.openRecent(entry.modelData.path) }
                PToolTip { text: entry.modelData.path; visible: hover.hovered && !recentCard.showFolder }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 4
                    spacing: Metrics.s12
                    PIcon {
                        Layout.preferredWidth: Metrics.iconSizeMedium
                        name: entry.modelData.missing ? "document_dismiss" : "document_pdf"
                        color: entry.modelData.missing ? Theme.textTertiary : Theme.accent
                        size: Metrics.iconSizeMedium
                    }
                    PText { Layout.preferredWidth: recentCard.nameWidth; text: entry.modelData.name; tone: entry.modelData.missing ? "tertiary" : ""; elide: Text.ElideMiddle }
                    PText {
                        Layout.preferredWidth: recentCard.folderWidth
                        visible: recentCard.showFolder
                        text: entry.modelData.folder
                        textStyle: "caption"
                        tone: "secondary"
                        elide: Text.ElideMiddle
                    }
                    PText {
                        Layout.preferredWidth: Metrics.homeRecentWhenWidth
                        text: entry.modelData.missing ? "Nicht mehr vorhanden" : entry.modelData.opened
                        textStyle: "caption"
                        tone: entry.modelData.missing ? "tertiary" : "secondary"
                        elide: Text.ElideRight
                    }
                    PText {
                        Layout.preferredWidth: Metrics.homeRecentSizeWidth
                        text: entry.modelData.size
                        textStyle: "caption"
                        tone: "secondary"
                        horizontalAlignment: Text.AlignRight
                    }
                    PIconButton {
                        iconName: "folder_open"
                        tip: "Im Ordner zeigen"
                        enabled: !entry.modelData.missing
                        onClicked: Reader.showInFolder(entry.modelData.path)
                    }
                    PIconButton {
                        iconName: "dismiss"
                        tip: "Aus der Liste entfernen"
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
            text: "Alle Dateien werden lokal auf diesem PC verarbeitet. Es wird nichts hochgeladen. PDF-JavaScript wird nie ausgeführt. Gespeichert wird erst nach einer Prüfung der neuen Datei – das Original bleibt bei einem Fehler unverändert."
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
