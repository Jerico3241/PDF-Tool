import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Präsentation mit KI erstellen« (seit 5.0 Beta 8): aus einem Thema oder aus dem geöffneten Dokument, mit wie vielen
// Folien. Die Präsentation öffnet sich als neues Dokument im Design »Projektvorstellung« – mit Notizen je Folie.
ColumnLayout {
    id: root
    objectName: "aiSlidesContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property string documentName: data_.document || ""
    readonly property int minimum: data_.min || 3
    readonly property int maximum: data_.max || 15
    property string source: "topic"
    property int count: 7
    readonly property bool acceptable: source === "document" ? documentName !== "" : topic.text.trim() !== ""
    function collect() { return { "source": root.source, "topic": topic.text, "count": root.count } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var data = request.data || {}
        root.source = data.source === "document" && data.document ? "document" : "topic"
        root.count = data.count || 7
        topic.text = ""
        if (root.source === "topic") topic.forceActiveFocus(Qt.OtherFocusReason)
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        tone: "secondary"
        text: I18n.tr("Der Assistent schreibt eine Gliederung mit Titeln, Stichpunkten und Notizen. Die Präsentation öffnet sich als neues Dokument – Texte, Design und Folien lassen sich danach frei ändern.", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Grundlage", I18n.revision) }
    PRadioButton {
        objectName: "aiSlidesFromDocument"
        visible: root.documentName !== ""
        text: I18n.tr("Aus diesem Dokument: " + root.documentName, I18n.revision)
        checked: root.source === "document"
        onClicked: root.source = "document"
    }
    PRadioButton {
        objectName: "aiSlidesFromTopic"
        text: I18n.tr("Zu einem Thema", I18n.revision)
        checked: root.source === "topic"
        onClicked: { root.source = "topic"; topic.forceActiveFocus() }
    }
    PTextField {
        id: topic
        objectName: "aiSlidesTopic"
        Layout.fillWidth: true
        Layout.leftMargin: 28
        Layout.topMargin: 4
        enabled: root.source === "topic"
        maximumLength: 300
        label: I18n.tr("Thema", I18n.revision)
        placeholderText: I18n.tr("Zum Beispiel: Einführung der neuen Urlaubsplanung im Team", I18n.revision)
    }
    PFieldLabel { text: I18n.tr("Anzahl der Folien", I18n.revision) }
    RowLayout {
        spacing: 8
        PIconButton {
            objectName: "aiSlidesFewer"
            iconName: "subtract"
            tip: I18n.tr("Weniger Folien", I18n.revision)
            enabled: root.count > root.minimum
            onClicked: root.count = Math.max(root.minimum, root.count - 1)
        }
        PText {
            objectName: "aiSlidesCount"
            Layout.preferredWidth: 32
            horizontalAlignment: Text.AlignHCenter
            text: I18n.tr(String(root.count), I18n.revision)
            textStyle: "bodyStrong"
        }
        PIconButton {
            objectName: "aiSlidesMore"
            iconName: "add"
            tip: I18n.tr("Mehr Folien", I18n.revision)
            enabled: root.count < root.maximum
            onClicked: root.count = Math.min(root.maximum, root.count + 1)
        }
        PText { text: I18n.tr("plus Titelfolie (" + root.minimum + " bis " + root.maximum + ")", I18n.revision); tone: "secondary" }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 12
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: I18n.tr("Das dauert je nach PC etwa ein bis drei Minuten. Inhalte bitte prüfen – die KI kann sich irren.", I18n.revision)
    }
}
