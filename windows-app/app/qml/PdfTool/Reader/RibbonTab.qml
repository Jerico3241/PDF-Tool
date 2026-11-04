import QtQuick
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Reiter des Menübands (Datei, Start, Einfügen …): der gewählte fett und in der Farbe der Dateiart unterstrichen –
// gleich für PDFs, Texte und Tabellen. Seit 5.0 Beta 10 (Entwurf 7) liegt der gewählte als erhabene Kachel mit Glanz
// über dem Hintergrund, die Linie darunter leuchtet.
T.AbstractButton {
    id: ribbonTab
    property string key: ""
    property string current: ""
    property color kindColor: Theme.accent
    readonly property bool selected: current === key
    implicitHeight: 38
    implicitWidth: boldLabel.advanceWidth + 2 * 12
    TextMetrics { id: boldLabel; font: Typography.bodyStrong; text: I18n.tr(ribbonTab.text, I18n.revision) }
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.role: Accessible.PageTab
    Accessible.name: I18n.tr(text, I18n.revision)
    Accessible.selected: selected
    background: Item {
        anchors.fill: parent
        Rectangle {
            radius: Metrics.radiusPill
            color: Theme.subtleHover
            opacity: !ribbonTab.selected && ribbonTab.hovered ? 1 : 0
            anchors.fill: parent
            anchors.topMargin: 3
            anchors.bottomMargin: 3
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
        }
        PGloss {
            anchors.fill: parent
            anchors.topMargin: 3
            anchors.bottomMargin: 3
            radius: Metrics.radiusPill
            opacity: ribbonTab.selected ? 1 : 0
            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }
        }
    }
    contentItem: Item {}
    Text {
        id: ribbonLabel
        anchors.centerIn: parent
        text: I18n.tr(ribbonTab.text, I18n.revision)
        font: ribbonTab.selected ? Typography.bodyStrong : Typography.body
        color: Theme.textPrimary
        textFormat: Text.PlainText
    }
    // Die Linie gleitet vom zuvor gewählten Reiter herüber (seit 5.0 Beta 10): Die Leiste merkt sich Lage und Breite
    // der Linie (``underX``, ``underW``), der neu gewählte Reiter startet dort und läuft an seinen Platz.
    property real glideShift: 0
    property real glideGrow: 0
    function rememberLine() {
        if (parent && parent.underX !== undefined) {
            parent.underX = x + (width - ribbonLabel.implicitWidth) / 2
            parent.underW = ribbonLabel.implicitWidth
        }
    }
    onSelectedChanged: {
        if (!selected)
            return
        var bar = parent
        if (Motion.moves && bar && bar.underX !== undefined && bar.underX >= 0 && visible) {
            glide.stop()
            glideShift = bar.underX - (x + (width - ribbonLabel.implicitWidth) / 2)
            glideGrow = bar.underW - ribbonLabel.implicitWidth
            glide.start()
        }
        rememberLine()
    }
    onXChanged: if (selected) rememberLine()
    onWidthChanged: if (selected) rememberLine()
    Component.onCompleted: if (selected) rememberLine()
    ParallelAnimation {
        id: glide
        NumberAnimation { target: ribbonTab; property: "glideShift"; to: 0; duration: Motion.normal; easing.type: Motion.decelerate }
        NumberAnimation { target: ribbonTab; property: "glideGrow"; to: 0; duration: Motion.normal; easing.type: Motion.decelerate }
    }
    Rectangle {
        objectName: "ribbonUnderline"
        x: (parent.width - width) / 2 + ribbonTab.glideShift + ribbonTab.glideGrow / 2
        anchors.bottom: parent.bottom
        anchors.bottomMargin: -1
        width: Math.max(4, ribbonLabel.implicitWidth + ribbonTab.glideGrow)
        height: 3
        radius: 1.5
        color: Theme.neon ? Theme.accent : ribbonTab.kindColor
        visible: ribbonTab.selected
        // Schein (Neon: mit der Leuchtstärke)
        Repeater {
            model: 3
            Rectangle {
                required property int index
                x: -(index + 1) * 1.5
                y: -(index + 1) * 1.5
                width: parent.width + (index + 1) * 3
                height: parent.height + (index + 1) * 3
                radius: height / 2
                color: "transparent"
                border.width: 1.5
                border.color: Theme.neon ? Theme.accent : ribbonTab.kindColor
                opacity: (Theme.neon ? 0.35 * Theme.glow : 0.12) * (1 - index / 3)
            }
        }
    }
}
