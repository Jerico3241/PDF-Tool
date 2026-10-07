import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite: Auswahl der Werkzeuge – eine mittig stehende Gruppe (gleicher Abstand links und
// rechts, höchstens ``Metrics.homeMaxWidth`` breit). Titel, Karten und Datenschutzhinweis stehen
// an derselben linken Kante.
//
// Karten: alle gleich breit und gleich hoch (die größte benötigte Höhe), die Fußzeile mit »Öffnen«
// und Tastenkürzel liegt daher überall auf derselben Höhe. Abstand ``Metrics.toolCardGap``.
//   breit  (Platz für die ganze Gruppe, ``homeMaxWidth``): drei Spalten
//   mittel (ab ``2 × toolCardMinWidth + toolCardGap``):   zwei Spalten
//   schmal:                                               eine Spalte, Karten untereinander
// Eine unvollständige letzte Zeile (z. B. die dritte Karte bei zwei Spalten) steht mittig – in
// derselben Breite. Kartenbreite und Abstand sind gerade, die Gruppe ist genau so breit wie die
// Karten mit ihren Abständen: Lage und Größe sind ganzzahlig (geräteunabhängige Pixel), die Ränder
// links und rechts sind bei jeder Skalierung gleich (bei ungerader Seitenbreite 1 px Rundung).
PPage {
    id: page
    objectName: "homePage"
    title: App.appName
    subtitle: "Werkzeuge für PDF-Dateien – wählen Sie, was Sie erledigen möchten."
    centered: true
    maxContentWidth: grid.groupWidth

    // Hinweise nach dem Start (z. B. Ergebnis einer Wiederherstellung)
    PInfoBar {
        objectName: "homeInfo"
        Layout.fillWidth: true
        Layout.bottomMargin: shown ? Metrics.s12 : 0
        topMargin: 0
        notice: Notices.area("home_info")
    }

    Item {
        id: grid
        objectName: "homeGrid"
        Layout.fillWidth: true
        readonly property int gap: Metrics.toolCardGap
        // Platz für die Gruppe: höchstens ``homeMaxWidth``, links und rechts mindestens der Seitenrand
        readonly property int available: Math.max(0, Math.min(Metrics.homeMaxWidth, Math.floor(page.width) - 2 * Metrics.pagePaddingLeft))
        readonly property int columns: available >= Metrics.homeMaxWidth ? 3 : (available >= 2 * Metrics.toolCardMinWidth + gap ? 2 : 1)
        readonly property int cardWidth: 2 * Math.floor((available - (columns - 1) * gap) / (2 * columns))
        readonly property int groupWidth: columns * cardWidth + (columns - 1) * gap
        readonly property int rows: Math.ceil(cards.count / columns)
        // Der Repeater meldet ``count``, bevor er die Karten erzeugt: ``itemsRevision`` sorgt dafür,
        // dass die Höhe neu berechnet wird (und von den Karten abhängt), sobald sie entstanden sind.
        property int itemsRevision: 0
        // Höhe der größten Karte bei dieser Breite – für alle Karten (Fußzeilen auf einer Linie)
        readonly property int cardHeight: {
            itemsRevision
            var height = Metrics.toolCardMinHeight
            for (var i = 0; i < cards.count; ++i) {
                var card = cards.itemAt(i)
                if (card) height = Math.max(height, Math.ceil(card.implicitHeight))
            }
            return height
        }
        implicitHeight: rows > 0 ? rows * cardHeight + (rows - 1) * gap : 0

        // Lage der Karte ``index``: Spalte und Zeile; eine unvollständige letzte Zeile steht mittig
        // (der freie Platz daneben ist gerade – auch sie liegt auf ganzen Pixeln)
        function cardX(index) {
            var row = Math.floor(index / grid.columns)
            var inRow = Math.min(grid.columns, cards.count - row * grid.columns)
            return (grid.columns - inRow) * (grid.cardWidth + grid.gap) / 2 + (index % grid.columns) * (grid.cardWidth + grid.gap)
        }
        function cardY(index) {
            return Math.floor(index / grid.columns) * (grid.cardHeight + grid.gap)
        }

        Repeater {
            id: cards
            model: App.tools
            onItemAdded: grid.itemsRevision++
            onItemRemoved: grid.itemsRevision++
            PToolCard {
                required property var modelData
                required property int index
                objectName: "toolCard_" + modelData.key
                x: grid.cardX(index)
                y: grid.cardY(index)
                width: grid.cardWidth
                height: grid.cardHeight
                iconName: modelData.icon
                title: modelData.title
                description: modelData.description
                shortcut: modelData.shortcut
                onClicked: App.openTool(modelData.key)
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
            text: "Alle Dateien werden lokal auf diesem PC verarbeitet. Es wird nichts hochgeladen."
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            Layout.fillWidth: true
        }
    }
}
