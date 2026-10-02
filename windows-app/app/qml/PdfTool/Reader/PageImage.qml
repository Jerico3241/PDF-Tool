import QtQuick
import PdfTool.Style

// Seitenbild aus »image://pdfpage/<Dokument>/<Seite>/<Breite>/<Fassung>…« (Ansicht, Miniaturen, Seiten
// organisieren). Das erste fertige Bild einer Seite blendet kurz über das weiße Blatt ein; neue Fassungen
// derselben Seite (Zoom, Änderung) tauschen ohne Blinken. Zeigt der Platz eine andere Seite (wiederverwendete
// Zeile, anderes Dokument), ist das alte Bild im selben Moment weg: Ausblenden hängt an keiner Animation, nur
// das Einblenden läuft über eine eigens gestartete Animation – unabhängig davon, in welcher Reihenfolge QML
// Bindungen auswertet (ein Behavior würde das Ausblenden abfangen und das alte Bild kurz stehen lassen).
Image {
    id: image
    // Seite einer Quelle (Dokument und Index), ohne Breite und Fassung
    function pageOf(url) {
        var parts = String(url).split("/")
        return parts.length > 4 ? parts[3] + "/" + parts[4] : ""
    }
    property string readyPage: ""   // Seite, deren Bild fertig dasteht
    readonly property bool ready: readyPage !== "" && readyPage === pageOf(source)
    property real reveal: 1
    signal imageReady()             // ein Bild der aktuellen Quelle ist da (auch eine neue Fassung)

    asynchronous: true
    retainWhileLoading: true
    cache: false
    smooth: true
    opacity: ready ? reveal : 0
    onStatusChanged: {
        if (status !== Image.Ready) return
        var page = pageOf(source)
        if (page !== readyPage) {
            revealing.stop()
            reveal = Motion.enabled ? 0 : 1
            readyPage = page
            if (Motion.enabled) revealing.start()
        }
        imageReady()
    }
    NumberAnimation { id: revealing; target: image; property: "reveal"; to: 1; duration: Motion.renderFade; easing.type: Motion.decelerate }
}
