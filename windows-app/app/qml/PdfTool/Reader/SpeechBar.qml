import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schwebende Leiste oben über der Seite, solange vorgelesen wird: Seite, Pause/Weiter, Tempo, Stimme und
// »Beenden«. Das gesprochene Wort markiert die Seite selbst (PageView). Blendet weich ein und aus.
Item {
    id: root
    objectName: "readerSpeechBar"
    readonly property bool present: Speech.active
    readonly property bool animating: heightAnim.running || fadeAnim.running
    readonly property int gap: 8

    implicitHeight: present ? card.height + gap : 0
    visible: present || animating
    opacity: present ? 1 : 0
    Behavior on implicitHeight { enabled: Motion.infoBar > 0; NumberAnimation { id: heightAnim; duration: Motion.infoBar; easing.type: Motion.decelerate } }
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { id: fadeAnim; duration: Motion.fade; easing.type: Motion.decelerate } }

    Rectangle {
        id: card
        y: root.gap
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(root.width, row.implicitWidth + 24)
        height: row.implicitHeight + 16
        radius: Metrics.radiusOverlay
        color: Theme.flyout
        border.color: Theme.flyoutStroke
        PShadow { radius: Metrics.radiusOverlay }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; preventStealing: true }

        RowLayout {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 14
            anchors.rightMargin: 10
            spacing: 8
            PIcon { name: "speaker_2"; Layout.alignment: Qt.AlignVCenter }
            PText {
                objectName: "readerSpeechStatus"
                Layout.fillWidth: true
                Layout.minimumWidth: 60
                elide: Text.ElideRight
                textStyle: "bodyStrong"
                text: I18n.tr(Speech.paused ? "Pausiert · " + Speech.status : (Speech.status !== "" ? "Vorlesen · " + Speech.status : "Vorlesen …"), I18n.revision)
            }
            PIconButton {
                objectName: "readerSpeechPause"
                iconName: Speech.paused ? "play" : "pause"
                tip: I18n.tr(Speech.paused ? "Weiter" : "Pause", I18n.revision)
                onClicked: Speech.togglePause()
            }
            PComboBox {
                objectName: "readerSpeechRate"
                preferredWidth: 92
                label: I18n.tr("Tempo", I18n.revision)
                tip: I18n.tr("Tempo", I18n.revision)
                model: Speech.rates
                textRole: "label"
                valueRole: "value"
                currentIndex: Speech.rates.findIndex(function(item) { return item.value === Speech.rate })
                onActivated: (index) => Speech.setRate(Speech.rates[index].value)
            }
            PComboBox {
                objectName: "readerSpeechVoice"
                visible: Speech.voices.length > 1
                preferredWidth: 200
                label: I18n.tr("Stimme", I18n.revision)
                tip: I18n.tr("Stimme", I18n.revision)
                model: Speech.voices
                textRole: "name"
                valueRole: "ident"
                currentIndex: Speech.voices.findIndex(function(item) { return item.ident === Speech.voice })
                onActivated: (index) => Speech.setVoice(Speech.voices[index].ident)
            }
            PButton {
                objectName: "readerSpeechStop"
                text: I18n.tr("Beenden", I18n.revision)
                onClicked: Speech.stop()
            }
        }
    }
}
