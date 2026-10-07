import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Hinweisleiste für Updates über den Seiten (nicht in den Einstellungen – dort steht alles in der
// Karte »Updates«). Sie erscheint einmal je Version, ohne die Arbeit zu unterbrechen; Inhalt,
// Fortschritt und Schaltflächen folgen dem Zustand des Updaters (``Updates``).
// Die Seiten rücken einmal um die Höhe der Leiste (kein Neuanordnen in jedem Bild); die Leiste
// selbst blendet ein und gleitet leicht – »Reduziert« nur Überblendung, »Aus« sofort.
Item {
    id: root
    objectName: "updateBanner"
    readonly property bool shown: Updates.bannerShown
    readonly property string phase: Updates.state
    readonly property bool working: phase === "downloading" || phase === "verifying" || phase === "installing"
    readonly property real columnWidth: Math.max(0, Math.min(Metrics.pageMaxWidth, width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight))
    readonly property real columnX: Metrics.pagePaddingLeft + Math.max(0, (width - Metrics.pagePaddingLeft - Metrics.pagePaddingRight - Metrics.pageMaxWidth) / 2)
    // Vollbild im Reader: keine Leiste (der Hinweis kommt danach wieder, solange er gilt)
    property bool suppressed: false
    // Beim Ausblenden bleibt der Platz, bis die Leiste verschwunden ist – erst dann rücken die Seiten
    readonly property bool occupied: (shown || fadeAnim.running) && !suppressed
    implicitHeight: occupied ? bar.height + 16 : 0
    visible: occupied
    Accessible.role: Accessible.AlertMessage
    Accessible.name: Updates.bannerTitle + (Updates.bannerText !== "" ? ": " + Updates.bannerText : "")

    Rectangle {
        id: bar
        objectName: "updateBannerBar"
        x: root.columnX
        y: 12 + (root.shown ? 0 : -Motion.infoBarShift)
        width: root.columnWidth
        height: row.implicitHeight + 20
        radius: Metrics.radiusControl
        color: Theme.toneBackground(Updates.bannerKind)
        border.width: 1
        border.color: Theme.border
        opacity: root.shown ? 1 : 0
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate } }
        Behavior on y { enabled: Motion.moves; NumberAnimation { duration: Motion.infoBar; easing.type: Motion.decelerate } }
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.status } }

        RowLayout {
            id: row
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 6
            anchors.topMargin: 10
            spacing: 12

            Item {
                Layout.preferredWidth: Metrics.iconSize
                Layout.preferredHeight: Metrics.iconSize
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: 2
                PProgressRing { anchors.centerIn: parent; size: 16; visible: root.working; running: visible }
                PIcon {
                    anchors.centerIn: parent
                    visible: !root.working
                    name: root.phase === "available" || root.phase === "cancelled" ? "arrow_download" : Theme.toneIcon(Updates.bannerKind)
                    color: root.phase === "available" ? Theme.accentText : Theme.toneIconColor(Updates.bannerKind)
                    size: Metrics.iconSize
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                PText {
                    objectName: "updateBannerTitle"
                    text: Updates.bannerTitle
                    textStyle: "bodyStrong"
                    wrap: true
                    Layout.fillWidth: true
                }
                RowLayout {
                    spacing: 8
                    Layout.fillWidth: true
                    visible: Updates.offerBeta || Updates.bannerText !== ""  // nach den Daten, nicht nach der Sichtbarkeit der Kinder
                    PBadge { id: betaBadge; objectName: "updateBannerBeta"; text: Updates.offerBeta ? "Beta" : ""; tone: "accent" }
                    PText {
                        id: bannerText
                        objectName: "updateBannerText"
                        text: Updates.bannerText
                        textStyle: "caption"
                        tone: "secondary"
                        wrap: true
                        visible: text !== ""
                        Layout.fillWidth: true
                    }
                }
                PProgressBar {
                    objectName: "updateBannerProgress"
                    Layout.fillWidth: true
                    Layout.topMargin: 6
                    Layout.bottomMargin: 2
                    visible: root.phase === "downloading" || root.phase === "verifying"
                    indeterminate: root.phase === "verifying"
                    value: Updates.progress
                }
            }
            Row {
                spacing: 8
                Layout.alignment: Qt.AlignVCenter
                PButton {
                    text: "Details"
                    visible: root.phase === "available"
                    onClicked: Updates.showDetails()
                }
                PButton {
                    objectName: "updateBannerDownload"
                    text: root.phase === "error" ? "Erneut versuchen" : "Herunterladen"
                    kind: "accent"
                    visible: Updates.canDownload
                    onClicked: Updates.download()
                }
                PButton {
                    objectName: "updateBannerCancel"
                    text: "Abbrechen"
                    visible: Updates.canCancel
                    onClicked: Updates.cancel()
                }
                PButton {
                    text: "Später installieren"
                    visible: Updates.canInstall
                    onClicked: Updates.later()
                }
                PButton {
                    objectName: "updateBannerInstall"
                    text: "Jetzt installieren"
                    kind: "accent"
                    visible: Updates.canInstall
                    onClicked: Updates.installNow()
                }
            }
            PIconButton {
                objectName: "updateBannerClose"
                visible: root.phase !== "installing"
                iconName: "dismiss"
                tip: "Später"
                Layout.alignment: Qt.AlignTop
                Layout.topMargin: -4
                onClicked: Updates.later()
            }
        }
    }
}
