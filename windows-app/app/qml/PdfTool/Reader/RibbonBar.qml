import QtQuick
import QtQuick.Layouts
import PdfTool.Backend

// Leiste eines Menübands (seit 5.0 Beta 9): Reicht die Breite nicht für alle Beschriftungen (kleines Fenster,
// Anzeige mit 125 % oder 150 %), zeigen die Knöpfe mit Symbol nur noch das Symbol – die Beschriftung steht dann in der
// Kurzinfo. Vorher wurden die letzten Knöpfe am Fensterrand abgeschnitten und waren nicht mehr erreichbar.
// »Menüband: Nur Symbole« (Personalisieren, seit 5.0 Beta 10) schiebt jede Leiste immer zusammen.
// Die Knöpfe folgen ``squeezed`` über ``compact: parent.squeezed === true`` (ToolButton der Ansichten).
RowLayout {
    id: bar
    property bool squeezed: false
    property real underX: -1  // Linie des gewählten Reiters (RibbonTab): Startpunkt, wenn ein anderer gewählt wird
    property real underW: 0
    property real fullWidth: 0  // Breite mit allen Beschriftungen – gemessen, solange die Leiste nicht zusammengeschoben ist

    function fit() {
        if (width <= 0)
            return
        if (!ThemeBackend.ribbonLabels) {
            squeezed = true
            return
        }
        if (!squeezed)
            fullWidth = implicitWidth
        squeezed = fullWidth > width + 0.5
    }

    // Inhalt geändert (z. B. Knöpfe je nach Platz ein- oder ausgeblendet): mit Beschriftungen neu messen
    function refit() {
        squeezed = false
        Qt.callLater(fit)
    }

    readonly property bool labels: ThemeBackend.ribbonLabels
    onLabelsChanged: refit()
    onWidthChanged: fit()
    onImplicitWidthChanged: if (!squeezed) fit()
    onVisibleChanged: if (visible) fit()
    Component.onCompleted: fit()
}
