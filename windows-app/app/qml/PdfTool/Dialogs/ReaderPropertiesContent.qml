import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Eigenschaften eines PDFs: Titel, Autor, Thema und Stichwörter (änderbar, rückgängig machbar)
// und technische Angaben (Version, Seiten, Verschlüsselung, Einschränkungen, Formular, Signaturen,
// Schriften …). Alle Texte kommen fertig aus Python.
ColumnLayout {
    id: root
    property var request: ({})
    readonly property var data_: request.data || ({})
    readonly property var props: data_.props || ({})
    readonly property bool editable: data_.editable === true
    function collect() { return { "title": title.text, "author": author.text, "subject": subject.text, "keywords": keywords.text } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        var p = (request.data || {}).props || {}
        title.text = p.title || ""
        author.text = p.author || ""
        subject.text = p.subject || ""
        keywords.text = p.keywords || ""
    }

    PSectionTitle { text: I18n.tr("Beschreibung", I18n.revision); Layout.fillWidth: true; Layout.topMargin: 0 }
    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        columns: 2
        columnSpacing: 12
        rowSpacing: 6
        PText { text: I18n.tr("Titel", I18n.revision); tone: "secondary" }
        PTextField { id: title; objectName: "readerPropTitle"; Layout.fillWidth: true; label: I18n.tr("Titel", I18n.revision); enabled: root.editable; maximumLength: 500 }
        PText { text: I18n.tr("Autor", I18n.revision); tone: "secondary" }
        PTextField { id: author; Layout.fillWidth: true; label: I18n.tr("Autor", I18n.revision); enabled: root.editable; maximumLength: 500 }
        PText { text: I18n.tr("Thema", I18n.revision); tone: "secondary" }
        PTextField { id: subject; Layout.fillWidth: true; label: I18n.tr("Thema", I18n.revision); enabled: root.editable; maximumLength: 1000 }
        PText { text: I18n.tr("Stichwörter", I18n.revision); tone: "secondary" }
        PTextField { id: keywords; Layout.fillWidth: true; label: I18n.tr("Stichwörter", I18n.revision); enabled: root.editable; maximumLength: 1000 }
    }
    PSectionTitle { text: I18n.tr("Dokument", I18n.revision); Layout.fillWidth: true; Layout.topMargin: 16 }
    PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: root.props.facts || []; labelWidth: 170 }
    PSectionTitle { text: I18n.tr("Schriften", I18n.revision); Layout.fillWidth: true; Layout.topMargin: 16; visible: (root.props.fonts || []).length > 0 }
    PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: root.props.fonts || []; labelWidth: 220 }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: text !== ""
        text: I18n.tr(root.props.fontsNote || "", I18n.revision)
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }
}
