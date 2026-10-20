import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Signaturen prüfen« (seit 4.0 Beta 6): je Signatur das Ergebnis (gültig, danach geändert, ungültig), wer wann
// unterschrieben hat und ob Windows dem Zertifikat vertraut. »Zum Feld« springt zur Seite eines sichtbaren Felds.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var signatures: (request.data || {}).signatures || []
    property int page: -1
    function collect() { return { "page": root.page } }
    spacing: 12

    Repeater {
        model: root.signatures
        PCard {
            id: card
            required property var modelData
            required property int index
            objectName: "signatureResult_" + index
            Layout.fillWidth: true
            padding: 12
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PIcon {
                    name: card.modelData.tone === "success" ? "shield_checkmark" : (card.modelData.tone === "error" ? "warning_shield" : "shield")
                    color: card.modelData.tone === "success" ? Theme.success : (card.modelData.tone === "error" ? Theme.error : (card.modelData.tone === "warning" ? Theme.warning : Theme.textSecondary))
                }
                PText {
                    objectName: "signatureTitle_" + card.index
                    Layout.fillWidth: true
                    textStyle: "bodyStrong"
                    text: card.modelData.title
                }
                PButton {
                    visible: card.modelData.visible && card.modelData.page >= 0
                    kind: "subtle"
                    text: "Zum Feld"
                    onClicked: { root.page = card.modelData.page; Dialogs.answer(root.request.id, "close", root.collect()) }
                }
            }
            PText {
                Layout.fillWidth: true
                wrap: true
                text: card.modelData.detail
            }
            PText {
                visible: card.modelData.trustDetail !== ""
                Layout.fillWidth: true
                wrap: true
                tone: card.modelData.trust === "trusted" ? "success" : "warning"
                text: card.modelData.trustDetail
            }
            PFactList {
                Layout.fillWidth: true
                labelWidth: 140
                facts: card.modelData.lines
            }
        }
    }
}
