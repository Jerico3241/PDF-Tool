pragma Singleton
import QtQuick
import PdfTool.Backend

// Animationsprofil der App: »full« (Vollständig), »reduced« (Reduziert) oder »off« (Aus).
// Alle Dauern kommen von hier; 0 bedeutet: sofort. »Reduziert« erlaubt nur kurze Überblendungen
// und Farbwechsel – keine Bewegungen (Slide, Scale, Höhenanimation). Das Profil wirkt sofort.
QtObject {
    readonly property string profile: ThemeBackend.effectiveProfile
    readonly property bool enabled: profile !== "off"
    readonly property bool moves: profile === "full"

    // Farbe und Deckkraft (auch »Reduziert«)
    readonly property int fast: enabled ? 83 : 0          // Hover, Druck
    readonly property int normal: enabled ? (moves ? 167 : 120) : 0
    readonly property int fade: enabled ? (moves ? 150 : 110) : 0
    readonly property int status: enabled ? (moves ? 167 : 120) : 0
    readonly property int theme: enabled ? (moves ? 220 : 150) : 0
    readonly property int tooltip: enabled ? 110 : 0
    readonly property int renderFade: enabled ? (moves ? 120 : 90) : 0  // fertiges Seitenbild/Miniatur einblenden

    // Seitenwechsel: kurz ausblenden, umschalten, fertige Seite einblenden (zusammen ~180 ms)
    readonly property int pageOut: enabled ? (moves ? 70 : 60) : 0
    readonly property int pageIn: enabled ? (moves ? 120 : 90) : 0
    readonly property real pageShift: moves ? 12 : 0

    // Bewegungen (nur »Vollständig«)
    readonly property int menu: enabled ? (moves ? 140 : 90) : 0
    readonly property real menuShift: moves ? 8 : 0
    readonly property real menuScale: moves ? 0.95 : 1.0  // Kontextmenü: 95 % → 100 %
    readonly property int dialog: enabled ? (moves ? 167 : 110) : 0
    readonly property real dialogScale: moves ? 0.96 : 1.0
    readonly property int expand: moves ? 200 : 0
    readonly property int indicator: moves ? 260 : 0
    readonly property int pane: moves ? 200 : 0
    readonly property real paneShift: moves ? 8 : 0      // Inhalt einer Seitenleiste wechselt mit leichtem Versatz
    readonly property int toggle: moves ? 167 : 0
    readonly property int infoBar: moves ? 200 : 0
    readonly property real infoBarShift: moves ? 6 : 0
    readonly property real pressScale: moves ? 0.98 : 1.0
    readonly property int scroll: moves ? 260 : 0       // Karte in den sichtbaren Bereich holen

    // Kurven (Windows 11: schnell herein, sanft abbremsen)
    readonly property int decelerate: Easing.OutCubic
    readonly property int accelerate: Easing.InCubic
    readonly property int standard: Easing.InOutCubic
}
