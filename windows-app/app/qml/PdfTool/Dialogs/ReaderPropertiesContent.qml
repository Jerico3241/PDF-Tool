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

    PSectionTitle { text: "Beschreibung"; Layout.fillWidth: true; Layout.topMargin: 0 }
    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        columns: 2
        columnSpacing: 12
        rowSpacing: 6
        PText { text: "Titel"; tone: "secondary" }
        PTextField { id: title; objectName: "readerPropTitle"; Layout.fillWidth: true; label: "Titel"; enabled: root.editable; maximumLength: 500 }
        PText { text: "Autor"; tone: "secondary" }
        PTextField { id: author; Layout.fillWidth: true; label: "Autor"; enabled: root.editable; maximumLength: 500 }
        PText { text: "Thema"; tone: "secondary" }
        PTextField { id: subject; Layout.fillWidth: true; label: "Thema"; enabled: root.editable; maximumLength: 1000 }
        PText { text: "Stichwörter"; tone: "secondary" }
        PTextField { id: keywords; Layout.fillWidth: true; label: "Stichwörter"; enabled: root.editable; maximumLength: 1000 }
    }
    PSectionTitle { text: "Dokument"; Layout.fillWidth: true; Layout.topMargin: 16 }
    PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: root.props.facts || []; labelWidth: 170 }
    PSectionTitle { text: "Schriften"; Layout.fillWidth: true; Layout.topMargin: 16; visible: (root.props.fonts || []).length > 0 }
    PFactList { Layout.fillWidth: true; Layout.topMargin: 4; facts: root.props.fonts || []; labelWidth: 220 }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 4
        visible: text !== ""
        text: root.props.fontsNote || ""
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }
}
