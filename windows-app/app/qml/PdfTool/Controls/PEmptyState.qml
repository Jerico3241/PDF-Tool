import QtQuick
import PdfTool.Style

// Leerer Zustand einer Fläche (Seitenleiste, Liste): Symbol in einem ruhigen Kreis, kurzer Titel und ein
// freundlicher Hinweis – im oberen Drittel statt verloren in der Mitte. Blendet beim Erscheinen kurz ein
// (Animationen »Aus«: sofort).
Item {
    id: root
    property string iconName: ""
    property string title: ""
    property string text: ""
    property real topShare: 0.16  // Abstand oben als Anteil der Höhe (ruhiger als genau mittig)

    implicitHeight: column.implicitHeight + Metrics.s32
    opacity: visible ? 1 : 0
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade; easing.type: Motion.decelerate } }
    Accessible.role: Accessible.StaticText
    Accessible.name: title + (text !== "" ? ". " + text : "")

    Column {
        id: column
        width: Math.min(root.width - 2 * Metrics.s24, 260)
        x: (root.width - width) / 2
        y: Math.max(Metrics.s24, root.height * root.topShare)
        spacing: Metrics.s8
        Rectangle {
            visible: root.iconName !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            width: 48
            height: 48
            radius: 24
            color: Theme.subtleHover
            PIcon { anchors.centerIn: parent; name: root.iconName; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
        }
        Item { width: 1; height: Metrics.s4; visible: root.iconName !== "" }
        PText {
            width: parent.width
            visible: root.title !== ""
            text: root.title
            textStyle: "bodyStrong"
            horizontalAlignment: Text.AlignHCenter
            wrap: true
            Accessible.ignored: true
        }
        PText {
            width: parent.width
            visible: root.text !== ""
            text: root.text
            tone: "secondary"
            horizontalAlignment: Text.AlignHCenter
            wrap: true
            Accessible.ignored: true
        }
    }
}
