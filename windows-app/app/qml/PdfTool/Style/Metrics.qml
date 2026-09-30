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

    // Navigation und Seiten
    readonly property int navItemHeight: 36
    readonly property int navHeaderHeight: 32
    readonly property int paneExpanded: 240
    readonly property int paneCompact: 48
    readonly property int pageMaxWidth: 1180
    readonly property int pagePaddingLeft: 36
    readonly property int pagePaddingRight: 28
    readonly property int pagePaddingTop: 28
    readonly property int pagePaddingBottom: 28
    readonly property int statusBarHeight: 32
    readonly property int cardPadding: 16

    // Responsive Zustände (Fensterbreite in geräteunabhängigen Pixeln)
    readonly property int wideFrom: 1008
    readonly property int mediumFrom: 820
    readonly property int breakpointHysteresis: 8
    readonly property int twoColumnsFrom: 740
}
