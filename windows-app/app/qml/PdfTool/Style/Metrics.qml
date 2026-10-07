pragma Singleton
import QtQuick

// Abstände, Radien und Größen – zentral, damit alle Seiten dieselben Maße verwenden.
QtObject {
    // Abstandsskala
    readonly property int s2: 2
    readonly property int s4: 4
    readonly property int s6: 6
    readonly property int s8: 8
    readonly property int s12: 12
    readonly property int s16: 16
    readonly property int s20: 20
    readonly property int s24: 24
    readonly property int s32: 32
    readonly property int s40: 40

    // Radien
    readonly property int radiusSmall: 2
    readonly property int radiusControl: 4
    readonly property int radiusCard: 8
    readonly property int radiusOverlay: 8
    readonly property int radiusDialog: 8

    // Größen
    readonly property int controlHeight: 32
    readonly property int controlHeightLarge: 40
    readonly property int iconSize: 16
    readonly property int iconSizeMedium: 20
    readonly property int iconSizeLarge: 24
    readonly property int iconSizeHero: 40
    readonly property int focusWidth: 2

    // Tab-Leiste oben (⌂ Start, Werkzeuge, Dokumente) und Seiten
    readonly property int appBarHeight: 40
    readonly property int appTabHeight: 34
    readonly property int appTabMaxWidth: 240
    readonly property int appTabIconOnly: 40   // ⌂ Start: nur das Symbol
    readonly property int appTabMinWidth: 76   // Werkzeug-Tab bei Platzmangel: Symbol, Anfang des Namens, ×
    readonly property int appDocsMinWidth: 200 // Platz der Dokument-Tabs bei Platzmangel (mindestens)
    readonly property int appDocTabMinWidth: 144 // Dokument-Tab bei Platzmangel; noch weniger Platz: ganze Tabs mit ‹ ›
    readonly property int appTabScroll: 24       // ‹ › neben den Dokument-Tabs, wenn nicht alle Platz haben
    readonly property int pageMaxWidth: 1180
    readonly property int pagePaddingLeft: 36
    readonly property int pagePaddingRight: 28
    readonly property int pagePaddingTop: 28
    readonly property int pagePaddingBottom: 28
    readonly property int statusBarHeight: 32
    readonly property int cardPadding: 16

    // Startseite: Werkzeuge und Ablagefläche, darunter »Zuletzt verwendet« – in einer zentrierten Gruppe
    readonly property int homeMaxWidth: 1080      // Breite der Gruppe (Kopf, Karten, Hinweis) höchstens
    readonly property int toolCardGap: 16         // Abstand zwischen den Karten – waagerecht und senkrecht
    readonly property int homeSideBySideFrom: 860 // ab dieser Breite stehen Werkzeuge und Ablagefläche nebeneinander
    readonly property int homeToolsInRowFrom: 700 // ab dieser Kartenbreite stehen die Werkzeuge nebeneinander
    readonly property int homeDropWidth: 260
    readonly property int homeRecentFolderFrom: 640  // schmaler: »Zuletzt verwendet« ohne Spalte »Ordner«
    readonly property int homeRecentWhenWidth: 130
    readonly property int homeRecentSizeWidth: 72

    // PDF Reader & Editor
    readonly property int readerToolbarHeight: 48
    // Seitenleisten: feste Breiten je Seite – gleich, welcher Inhalt gezeigt wird (kein Springen)
    readonly property int readerLeftPanelWidth: 300  // Platz für vier Umschalter (Seiten, Lesezeichen, Suche, Anhänge) und den ganzen Titel
    readonly property int readerRightPanelWidth: 280
    readonly property int readerPanelHeaderHeight: 44
    readonly property int readerPanelTab: 28      // Umschalter und Schließen im Kopf einer Seitenleiste
    readonly property int readerRailWidth: 44     // eingeklappte Seitenleiste: Streifen mit ihren Symbolen
    readonly property int readerRailButton: 36
    readonly property int readerViewMargin: 16    // wie VIEW_MARGIN in qtapp/reader/document.py
    readonly property int readerNarrowFrom: 820   // schmaler: Seitenleisten liegen über der Ansicht
    readonly property int readerHandle: 10        // Anfasser zum Ändern der Bildgröße

    // Responsive Zustände (Breite in geräteunabhängigen Pixeln)
    readonly property int twoColumnsFrom: 740
}
