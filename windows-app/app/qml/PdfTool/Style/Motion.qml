pragma Singleton
import QtQuick
import PdfTool.Backend

// Animationsprofil der App: »full« (Vollständig), »reduced« (Reduziert) oder »off« (Aus). Seit 5.0 Beta 11 ist
// »Vollständig« deutlich bewegter (längere Dauern, größere Wege, Auftritte für Dokumente, Seiten und Listen).
// Alle Dauern kommen von hier; 0 bedeutet: sofort. »Reduziert« erlaubt nur kurze Überblendungen
// und Farbwechsel – keine Bewegungen (Slide, Scale, Höhenanimation). Das Profil wirkt sofort.
QtObject {
    readonly property string profile: ThemeBackend.effectiveProfile
    readonly property bool enabled: profile !== "off"
    readonly property bool moves: profile === "full"

    // Farbe und Deckkraft (auch »Reduziert«)
    readonly property int fast: enabled ? (moves ? 130 : 83) : 0   // Hover, Druck
    readonly property int normal: enabled ? (moves ? 280 : 120) : 0
    readonly property int fade: enabled ? (moves ? 240 : 110) : 0
    readonly property int status: enabled ? (moves ? 260 : 120) : 0
    readonly property int theme: enabled ? (moves ? 360 : 150) : 0
    readonly property int tooltip: enabled ? (moves ? 160 : 110) : 0
    readonly property int renderFade: enabled ? (moves ? 220 : 90) : 0  // fertiges Seitenbild/Miniatur einblenden

    // Seitenwechsel: kurz ausblenden, umschalten, fertige Seite einblenden (zusammen ~180 ms)
    readonly property int pageOut: enabled ? (moves ? 110 : 60) : 0
    readonly property int pageIn: enabled ? (moves ? 340 : 90) : 0
    readonly property real pageShift: moves ? 34 : 0
    readonly property real pageScale: moves ? 0.965 : 1.0     // neue Seite wächst beim Einblenden auf 100 %

    // Bewegungen (nur »Vollständig«)
    readonly property int menu: enabled ? (moves ? 220 : 90) : 0
    readonly property real menuShift: moves ? 14 : 0
    readonly property real menuScale: moves ? 0.9 : 1.0   // Kontextmenü: 90 % → 100 %
    readonly property int dialog: enabled ? (moves ? 300 : 110) : 0
    readonly property real dialogScale: moves ? 0.88 : 1.0
    readonly property int expand: moves ? 320 : 0
    readonly property int indicator: moves ? 420 : 0
    readonly property int pane: moves ? 340 : 0
    readonly property real paneShift: moves ? 28 : 0     // Inhalt einer Seitenleiste wechselt mit deutlichem Versatz
    readonly property int toggle: moves ? 240 : 0
    readonly property int infoBar: moves ? 320 : 0
    readonly property real infoBarShift: moves ? 14 : 0
    readonly property real pressScale: moves ? 0.95 : 1.0
    readonly property int scroll: moves ? 380 : 0       // Karte in den sichtbaren Bereich holen

    // Auftritte (seit 5.0 Beta 11 »alles animiert«): Dokument öffnen/wechseln, Startseite, Listen nacheinander
    readonly property bool intros: moves && ThemeBackend.intros
    readonly property int intro: moves ? 620 : 0          // Dokument fliegt aus der Tiefe herein
    readonly property real introTilt: moves ? 14 : 0       // Neigung (Grad) am Anfang des Auftritts
    readonly property real introScale: moves ? 0.86 : 1.0
    readonly property real introShift: moves ? 60 : 0
    readonly property int stagger: moves ? 55 : 0          // Abstand zwischen Elementen, die nacheinander auftreten
    readonly property int spring: Easing.OutBack           // leicht über das Ziel hinaus und zurück

    // Kurven (Windows 11: schnell herein, sanft abbremsen)
    readonly property int decelerate: Easing.OutCubic
    readonly property int accelerate: Easing.InCubic
    readonly property int standard: Easing.InOutCubic
}
