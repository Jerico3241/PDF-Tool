import QtQuick
import PdfTool.Style

// Inhalt einer Seitenleiste: existiert nur, solange er gezeigt wird (versteckte Miniaturen würden sonst
// gerendert). Beim Wechsel überblenden alter und neuer Inhalt; der neue kommt mit leichtem Versatz von
// rechts, der alte weicht nach links (»Reduziert«: nur Überblenden, »Aus«: sofort). Der alte Inhalt
// bleibt geladen, bis er ausgeblendet ist.
Loader {
    id: loader
    property bool shown: false
    anchors.fill: parent
    active: shown || opacity > 0
    opacity: shown && status === Loader.Ready ? 1 : 0
    transform: Translate { x: (loader.shown ? 1 : -1) * (1 - loader.opacity) * Motion.paneShift }
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
}
