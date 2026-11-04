import QtQuick
import QtQuick.Layouts

// Leiste eines Menübands (seit 5.0 Beta 9): Reicht die Breite nicht für alle Beschriftungen (kleines Fenster,
// Anzeige mit 125 % oder 150 %), zeigen die Knöpfe mit Symbol nur noch das Symbol – die Beschriftung steht dann in der
// Kurzinfo. Vorher wurden die letzten Knöpfe am Fensterrand abgeschnitten und waren nicht mehr erreichbar.
// Die Knöpfe folgen ``squeezed`` über ``compact: parent.squeezed === true`` (ToolButton der Ansichten).
RowLayout {
    id: bar
    property bool squeezed: false
    property real fullWidth: 0  // Breite mit allen Beschriftungen – gemessen, solange die Leiste nicht zusammengeschoben ist

    function fit() {
        if (width <= 0)
            return
        if (!squeezed)
            fullWidth = implicitWidth
        squeezed = fullWidth > width + 0.5
    }

    // Inhalt geändert (z. B. Knöpfe je nach Platz ein- oder ausgeblendet): mit Beschriftungen neu messen
    function refit() {
        squeezed = false
        Qt.callLater(fit)
    }

    onWidthChanged: fit()
    onImplicitWidthChanged: if (!squeezed) fit()
    onVisibleChanged: if (visible) fit()
    Component.onCompleted: fit()
}
