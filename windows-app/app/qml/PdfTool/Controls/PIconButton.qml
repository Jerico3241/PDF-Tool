import QtQuick
import PdfTool.Style

// Symbolschaltfläche ohne Fläche (z. B. »Pfad kopieren«) – der Tooltip nennt die Aktion.
PButton {
    id: control
    kind: "subtle"
    text: ""
    implicitWidth: Metrics.controlHeight
    implicitHeight: Metrics.controlHeight
}
