import QtQuick
import PdfTool.Style

// Kleines Etikett (z. B. »Bereit«, »+2 neu«) in einem Statuston; Farbwechsel weich.
Rectangle {
    id: badge
    property string text: ""
    // success, caution/warning, critical/error, info, neutral, accent
    property string tone: "neutral"
    property bool strong: false
    implicitWidth: label.implicitWidth + 16
    implicitHeight: 22
    radius: 11
    visible: text !== ""
    color: strong ? Theme.toneIconColor(tone) : (tone === "neutral" ? Theme.surfaceSecondary : Theme.toneBackground(tone))
    border.width: strong ? 0 : 1
    border.color: Theme.border
    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.status } }
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    Text {
        id: label
        anchors.centerIn: parent
        text: badge.text
        font: Typography.caption
        color: badge.strong ? Theme.textOnStatus : (badge.tone === "neutral" ? Theme.textSecondary : Theme.tone(badge.tone))
        textFormat: Text.PlainText
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.status } }
    }
}
