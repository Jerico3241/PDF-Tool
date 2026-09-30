import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Startseite: Auswahl der Werkzeuge – eine mittig stehende Gruppe (gleicher Abstand links und
// rechts, höchstens ``Metrics.homeMaxWidth`` breit). Titel, Karten und Datenschutzhinweis stehen
// an derselben linken Kante.
//
// Karten: zwei exakt gleich breite Spalten mit ``Metrics.toolCardGap`` Abstand (die Breite der
// Gruppe ist gerade, jede Karte daher ganzzahlig breit); alle Karten gleich hoch (die größte
// benötigte Höhe), die Fußzeile mit »Öffnen« und Tastenkürzel liegt daher überall auf derselben
// Höhe. Unter ``2 × toolCardMinWidth + toolCardGap`` Breite: eine Spalte, Karten untereinander.
PPage {
    id: page
    objectName: "homePage"
    title: App.appName
    subtitle: "Werkzeuge für PDF-Dateien – wählen Sie, was Sie erledigen möchten."
    centered: true
    maxContentWidth: Metrics.homeMaxWidth

    Item {
        id: grid
        objectName: "homeGrid"
        Layout.fillWidth: true
        readonly property int gap: Metrics.toolCardGap
        readonly property int columns: width >= 2 * Metrics.toolCardMinWidth + gap ? 2 : 1
        readonly property int rows: Math.ceil(cards.count / columns)
        readonly property int cardWidth: columns === 2 ? Math.floor((width - gap) / 2) : Math.floor(width)
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

        Repeater {
            id: cards
            model: App.tools
            onItemAdded: grid.itemsRevision++
            onItemRemoved: grid.itemsRevision++
            PToolCard {
                required property var modelData
                required property int index
                objectName: "toolCard_" + modelData.key
                x: (index % grid.columns) * (grid.cardWidth + grid.gap)
                y: Math.floor(index / grid.columns) * (grid.cardHeight + grid.gap)
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
