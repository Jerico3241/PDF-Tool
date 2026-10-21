import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Backend

// InfoBar (Hinweis) mit Stufe, Titel, Text und Aktionen. Erscheint mit Höhe, Deckkraft und
// leichter Bewegung, verschwindet ebenso – ohne hektische Sprünge. Ein neuer Inhalt in einem
// sichtbaren Hinweis wird kurz überblendet.
//
// Gebunden an einen Hinweisbereich aus Python (``notice: Notices.area("pdf_info")``) oder frei
// über ``shown``, ``severity``, ``title``, ``message`` und ``actions``.
Item {
    id: root
    property QtObject notice: null
    property bool closable: true
    property bool shown: notice ? notice.shown : false
    property string severity: notice ? notice.severity : "info"
    property string title: notice ? notice.title : ""
    property string message: notice ? notice.message : ""
    property var actions: notice ? notice.actions : []
    property bool animate: notice ? notice.animate : true
    property int topMargin: 8
    // Nach so vielen Millisekunden von selbst schließen (0 = bleibt); solange die Maus darauf steht, nicht
    property int autoHide: 0
    signal actionTriggered(int index)
    signal closed()

    function dismiss() {
        if (root.notice)
            root.notice.close()
        root.closed()
    }
    onShownChanged: if (shown && autoHide > 0) hideTimer.restart(); else hideTimer.stop()
    Component.onCompleted: if (shown && autoHide > 0) hideTimer.restart()
    onMessageChanged: if (shown && autoHide > 0) hideTimer.restart()
    Timer {
        id: hideTimer
        interval: root.autoHide
        onTriggered: {
            if (barHover.hovered) restart()
            else if (root.shown) root.dismiss()
        }
    }
    HoverHandler { id: barHover }

    readonly property bool animating: heightAnim.running || fadeAnim.running
    readonly property real barHeight: bar.implicitHeight + topMargin

    implicitHeight: shown ? barHeight : 0
    implicitWidth: 300
    visible: shown || animating
    clip: animating
    opacity: shown ? 1 : 0
    Accessible.role: Accessible.AlertMessage
    Accessible.name: I18n.tr((title !== "" ? title + ": " : "") + message, I18n.revision)

    Behavior on implicitHeight {
        enabled: root.animate && Motion.infoBar > 0
        NumberAnimation { id: heightAnim; duration: Motion.infoBar; easing.type: Motion.decelerate }
    }
    Behavior on opacity {
        enabled: root.animate && Motion.enabled
        NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    // Neuer Inhalt in einem sichtbaren Hinweis: kurz überblenden. Eigener Signal-Handler statt
    // »Connections« (siehe PProgressRing – Hinweise stecken in fast jeder Seite).
    readonly property int noticeSerial: notice ? notice.serial : 0
    onNoticeSerialChanged: {
        if (root.shown && root.animate && Motion.enabled && root.opacity > 0.99)
            refresh.restart()
    }
    SequentialAnimation {
        id: refresh
        NumberAnimation { target: bar; property: "opacity"; to: 0.35; duration: 60 }
        NumberAnimation { target: bar; property: "opacity"; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    Rectangle {
        id: bar
        y: root.topMargin + (root.shown ? 0 : -Motion.infoBarShift)
        width: root.width
        implicitHeight: row.implicitHeight + 20
        height: implicitHeight
        radius: Metrics.radiusControl
        color: root.severity === "neutral" ? Theme.surfaceSecondary : Theme.toneBackground(root.severity)
        border.width: 1
        border.color: Theme.border
        Behavior on y { enabled: root.animate && Motion.moves; NumberAnimation { duration: Motion.infoBar; easing.type: Motion.decelerate } }
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.status } }

        RowLayout {
            id: row
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: root.closable ? 6 : 14
            anchors.topMargin: 10
            spacing: 12

            PIcon {
                name: Theme.toneIcon(root.severity)
                color: Theme.toneIconColor(root.severity)
                size: Metrics.iconSize
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
            }
            Flow {
                id: flow
                Layout.fillWidth: true
                spacing: 12
                Text {
                    id: text
                    width: Math.min(implicitWidth, flow.width)
                    text: I18n.tr(root.title !== "" ? "<b>" + root.escapeHtml(root.title) + "</b>&nbsp;&nbsp;" + root.escapeHtml(root.message) : root.escapeHtml(root.message), I18n.revision)
                    textFormat: Text.StyledText
                    font: Typography.body
                    color: Theme.textPrimary
                    wrapMode: Text.Wrap
                    lineHeight: 1.1
                }
                Repeater {
                    model: root.actions
                    PButton {
                        required property int index
                        required property var modelData
                        text: I18n.tr(String(modelData), I18n.revision)
                        onClicked: {
                            // Die Aktion kann denselben Hinweis mit anderen Aktionen ersetzen – dann
                            // entsteht diese Schaltfläche neu. Danach nur noch lokale Werte verwenden.
                            var bar = root, action = index
                            if (bar.notice)
                                bar.notice.trigger(action)
                            bar.actionTriggered(action)
                        }
                    }
                }
            }
            PIconButton {
                visible: root.closable
                iconName: "dismiss"
                tip: I18n.tr("Schließen", I18n.revision)
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: -4
                onClicked: root.dismiss()
            }
        }
    }

    function escapeHtml(value) {
        return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>")
    }
}
