import QtQuick
import PdfTool.Style

// Text in einer der zentralen Schriftstufen und Farbtöne.
Text {
    id: root
    // caption, body, bodyStrong, bodyLarge, subtitle, title, display
    property string textStyle: "body"
    // "", secondary, tertiary, accent, success, warning, error, disabled, onAccent
    property string tone: ""
    property bool wrap: false

    font: Typography[textStyle] !== undefined ? Typography[textStyle] : Typography.body
    color: {
        switch (tone) {
        case "secondary": case "muted": return Theme.textSecondary
        case "tertiary": return Theme.textTertiary
        case "accent": return Theme.accentText
        case "success": return Theme.success
        case "warning": case "caution": return Theme.warning
        case "error": case "critical": return Theme.error
        case "disabled": return Theme.disabled
        case "onAccent": return Theme.textOnAccent
        default: return Theme.textPrimary
        }
    }
    wrapMode: wrap ? Text.Wrap : Text.NoWrap
    elide: wrap ? Text.ElideNone : Text.ElideRight
    textFormat: Text.PlainText
    verticalAlignment: Text.AlignVCenter
    Accessible.role: Accessible.StaticText
    Accessible.name: text
}
