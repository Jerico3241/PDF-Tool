import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Überschrift eines Abschnitts innerhalb einer Seite (z. B. »Darstellung« in den Einstellungen).
PText {
    textStyle: "bodyStrong"
    Layout.fillWidth: true
    Layout.topMargin: 20
    Layout.bottomMargin: 8
    Accessible.role: Accessible.Heading
}
