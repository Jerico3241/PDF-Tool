import QtQuick
import QtQuick.Layouts
import PdfTool.Style

// Beschriftung über einem Eingabefeld.
PText {
    property bool first: false
    textStyle: "body"
    Layout.fillWidth: true
    Layout.topMargin: first ? 0 : 12
    Layout.bottomMargin: 4
}
