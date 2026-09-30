pragma Singleton
import QtQuick
import PdfTool.Backend

// Design-Tokens der App. Die Werte kommen aus der Palette in Python (WinUI-Farben, Windows-Akzent)
// und ändern sich live mit Hell/Dunkel/System und der Akzentfarbe. Controls verwenden
// ausschließlich diese Tokens – keine fest eingetragenen Farben.
QtObject {
    readonly property var c: ThemeBackend.colors
    readonly property bool dark: ThemeBackend.dark

    // Kern-Tokens
    readonly property color background: c.mica || "#F3F3F3"
    readonly property color surface: c.card || "#FDFDFD"
    readonly property color surfaceSecondary: c.card_secondary || "#F6F6F6"
    readonly property color border: c.card_stroke || "#E5E5E5"
    readonly property color textPrimary: c.text || "#1A1A1A"
    readonly property color textSecondary: c.text2 || "#5D5D5D"
    readonly property color textTertiary: c.text3 || "#8A8A8A"
    readonly property color accent: c.accent || "#005FB8"
    readonly property color success: c.success || "#0F7B0F"
    readonly property color warning: c.caution || "#9D5D00"
    readonly property color error: c.critical || "#C42B1E"
    readonly property color disabled: c.text_disabled || "#A0A0A0"

    // Flächen
    readonly property color layer: c.layer || "#F9F9F9"
    readonly property color layerStroke: c.layer_stroke || "#E5E5E5"
    readonly property color divider: c.divider || "#EBEBEB"
    readonly property color flyout: c.flyout || "#F9F9F9"
    readonly property color flyoutStroke: c.flyout_stroke || "#D2D2D2"
    readonly property color dialog: c.dialog || "#FFFFFF"
    readonly property color dialogFooter: c.dialog_footer || "#F3F3F3"
    readonly property color smoke: c.smoke || "#4D000000"
    readonly property color shadow: c.shadow || "#24000000"

    // Eingabeelemente
    readonly property color control: c.control || "#FEFEFE"
    readonly property color controlHover: c.control_hover || "#F6F6F6"
    readonly property color controlPressed: c.control_pressed || "#F1F1F1"
    readonly property color controlDisabled: c.control_disabled || "#F7F7F7"
    readonly property color controlStroke: c.control_stroke || "#E3E3E3"
    readonly property color controlEdge: c.control_edge || "#C9C9C9"
    readonly property color inputFocus: c.input_focus || "#FFFFFF"
    readonly property color inputEdge: c.input_edge || "#868686"
    readonly property color strong: c.strong || "#5D5D5D"
    readonly property color strongStroke: c.strong_stroke || "#8A8A8A"
    readonly property color subtleHover: c.subtle_hover_rgba || "#0B000000"
    readonly property color subtlePressed: c.subtle_pressed_rgba || "#07000000"

    // Akzent
    readonly property color accentHover: c.accent_hover || "#196FBF"
    readonly property color accentPressed: c.accent_pressed || "#337FC6"
    readonly property color accentDisabled: c.accent_disabled || "#C5C5C5"
    readonly property color accentText: c.accent_text || "#00519C"
    readonly property color textOnAccent: c.on_accent || "#FFFFFF"
    readonly property color textOnAccentPressed: c.on_accent_pressed || "#BFD7ED"
    readonly property color textOnAccentDisabled: c.on_accent_disabled || "#FFFFFF"
    readonly property color accentStroke: c.accent_stroke || "#146CBE"
    readonly property color accentEdge: c.accent_edge || "#00417D"

    // Fokus
    readonly property color focusOuter: c.focus_outer || "#1A1A1A"
    readonly property color focusInner: c.focus_inner || "#FFFFFF"

    // Status
    readonly property color successBackground: c.success_bg || "#DFF6DD"
    readonly property color warningBackground: c.caution_bg || "#FFF4CE"
    readonly property color errorBackground: c.critical_bg || "#FDE7E9"
    readonly property color infoBackground: c.info_bg || "#F6F6F6"
    readonly property color neutral: c.neutral || "#8A8A8A"
    readonly property color textOnStatus: c.on_status || "#FFFFFF"
    readonly property color errorHover: c.critical_hover || "#CA4034"
    readonly property color errorPressed: c.critical_pressed || "#CF554B"

    // Papier der Kopf-/Fußzeilen-Editoren (wie in der PDF – auch im dunklen Design weiß)
    readonly property color paper: "#FFFFFF"
    readonly property color paperText: "#333333"

    // Hilfen ---------------------------------------------------------------------------
    // Farbe eines Status (»success«, »warning«/»caution«, »error«/»critical«, »info«, »neutral«)
    function tone(name) {
        switch (name) {
        case "success": return success
        case "warning": case "caution": return warning
        case "error": case "critical": return error
        case "info": case "accent": return accentText
        case "muted": return textSecondary
        case "neutral": return neutral
        default: return textPrimary
        }
    }
    function toneBackground(name) {
        switch (name) {
        case "success": return successBackground
        case "warning": case "caution": return warningBackground
        case "error": case "critical": return errorBackground
        default: return infoBackground
        }
    }
    // Symbol eines Status
    function toneIcon(name) {
        switch (name) {
        case "success": return "checkmark_circle_filled"
        case "warning": case "caution": return "warning_filled"
        case "error": case "critical": return "error_circle_filled"
        case "info": return "info_filled"
        default: return "info_filled"
        }
    }
    function toneIconColor(name) {
        switch (name) {
        case "success": return success
        case "warning": case "caution": return warning
        case "error": case "critical": return error
        case "info": return accent
        default: return neutral
        }
    }
    // Symbol-URL für den Bild-Provider: eingefärbtes Fluent-Symbol
    function icon(name, color) {
        return "image://icons/" + name + "/" + String(color).replace("#", "").slice(-6)
    }
}
