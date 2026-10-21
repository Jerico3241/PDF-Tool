import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Text erkennen (OCR)«: welche Seiten (alle, aktuelle, ausgewählte) und welche Sprachen. Seiten, die schon
// Text haben, werden übersprungen (sie sind bereits durchsuchbar); eine frühere Erkennung von PDF Tool lässt
// sich wiederholen. Die Sprachen kommen von der installierten Texterkennung – solange sie noch gesucht wird,
// ist »Erkennen« gesperrt.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var selected: data_.selected || []
    property string scope: "all"
    property var languages: []
    readonly property bool ready: Reader.ocrState === "bereit"
    readonly property bool acceptable: ready && languages.length > 0
    function collect() { return { "scope": root.scope, "languages": root.languages, "redo": redo.checked } }
    function toggle(code, on) {
        var next = root.languages.filter(function(item) { return item !== code })
        if (on) next.push(code)
        root.languages = next
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        root.scope = data.scope || "all"
        root.languages = (data.languages || []).slice()
        redo.checked = false
        root.preselect()
    }
    // Wird die Texterkennung erst gefunden, während der Dialog offen ist: Deutsch (sonst die erste Sprache)
    // vorwählen – »Erkennen« bliebe sonst gesperrt
    function preselect() {
        var codes = (Reader.ocrLanguages || []).map(function(entry) { return entry.code })
        if (root.languages.length > 0 || codes.length === 0) return
        root.languages = [codes.indexOf("deu") >= 0 ? "deu" : codes[0]]
    }
    Connections {
        target: Reader
        function onOcrLanguagesChanged() { root.preselect() }
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("Gescannte Seiten werden durchsuchbar: Der erkannte Text liegt unsichtbar über dem Scan – Suchen, Markieren und Kopieren finden ihn, das Aussehen der Seiten bleibt unverändert. Die Erkennung läuft vollständig auf diesem PC.", I18n.revision)
    }

    PFieldLabel { text: I18n.tr("Seiten", I18n.revision) }
    ColumnLayout {
        spacing: 0
        PRadioButton {
            objectName: "ocrScopeAll"
            text: I18n.tr("Alle Seiten (" + (root.data_.pageCount || 0) + ")", I18n.revision)
            checked: root.scope === "all"
            onClicked: root.scope = "all"
        }
        PRadioButton {
            objectName: "ocrScopeCurrent"
            text: I18n.tr("Aktuelle Seite (" + ((root.data_.current || 0) + 1) + ")", I18n.revision)
            checked: root.scope === "current"
            onClicked: root.scope = "current"
        }
        PRadioButton {
            objectName: "ocrScopeSelected"
            visible: root.selected.length > 0
            text: I18n.tr("Ausgewählte Seiten (" + root.selected.length + ")", I18n.revision)
            checked: root.scope === "selected"
            onClicked: root.scope = "selected"
        }
    }

    PFieldLabel { text: I18n.tr("Sprache des Textes", I18n.revision) }
    PText {
        visible: !root.ready
        Layout.fillWidth: true
        wrap: true
        tone: Reader.ocrState === "fehlt" ? "warning" : "secondary"
        text: I18n.tr(Reader.ocrState === "fehlt" ? "Die Texterkennung wurde nicht gefunden. Bitte PDF Tool neu installieren." : "Die Texterkennung wird vorbereitet …", I18n.revision)
    }
    Flow {
        Layout.fillWidth: true
        visible: root.ready
        spacing: 12
        Repeater {
            model: Reader.ocrLanguages
            PCheckBox {
                required property var modelData
                objectName: "ocrLanguage_" + modelData.code
                text: I18n.tr(modelData.label, I18n.revision)
                checked: root.languages.indexOf(modelData.code) >= 0
                onToggled: root.toggle(modelData.code, checked)
            }
        }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: root.ready && root.languages.length > 1
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Mehrere Sprachen: für Seiten mit gemischtem Text – die Erkennung dauert etwas länger.", I18n.revision)
    }

    PCheckBox {
        id: redo
        objectName: "ocrRedo"
        Layout.topMargin: 12
        Layout.fillWidth: true
        text: I18n.tr("Bereits erkannte Seiten erneut erkennen (ersetzt den früher erkannten Text)", I18n.revision)
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Seiten mit echtem PDF-Text werden nie erneut erkannt – sie sind bereits durchsuchbar. Rückgängig nimmt die Erkennung vollständig zurück.", I18n.revision)
    }
}
