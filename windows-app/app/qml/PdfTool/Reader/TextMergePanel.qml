import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Serienbrief (seit 5.0 Beta 5): 1. Empfänger wählen (Excel-Mappe oder CSV, erste Zeile = Feldnamen), 2. Felder an
// der Schreibmarke einfügen (Klick auf den Namen; im Text steht dann »«Name»«), 3. Vorschau eines Empfängers,
// 4. »Briefe erstellen« – ein neues Dokument mit einem Brief je Empfänger.
Flickable {
    id: root
    objectName: "textMergePanel"
    property var doc: null
    property int record: 0
    readonly property bool hasSource: doc !== null && doc.mergeCount > 0
    readonly property var values: hasSource ? doc.mergeRecord(Math.min(record, doc.mergeCount - 1)) : ({})
    signal done()
    clip: true
    contentWidth: width
    contentHeight: column.implicitHeight + 24
    boundsBehavior: Flickable.StopAtBounds
    T.ScrollBar.vertical: PScrollBar {}
    PWheelScroll { flickable: root }
    onDocChanged: record = 0

    Connections {
        target: root.doc
        function onMergeNameChanged() { root.record = 0 }
    }

    component Step: RowLayout {
        property int number: 1
        property string title: ""
        Layout.fillWidth: true
        Layout.topMargin: 4
        spacing: 8
        Rectangle {
            Layout.preferredWidth: 22
            Layout.preferredHeight: 22
            radius: 11
            color: Theme.selectedSubtle
            PText { anchors.centerIn: parent; text: I18n.tr(String(parent.parent.number), I18n.revision); textStyle: "caption"; font.weight: Font.DemiBold }
        }
        PText { Layout.fillWidth: true; text: I18n.tr(parent.title, I18n.revision); font.weight: Font.DemiBold; elide: Text.ElideRight }
    }

    ColumnLayout {
        id: column
        x: 12
        y: 12
        width: root.width - 24
        spacing: 8

        Step { number: 1; title: I18n.tr("Empfänger", I18n.revision) }
        PText {
            Layout.fillWidth: true
            wrap: true
            tone: root.hasSource ? "primary" : "secondary"
            text: I18n.tr(root.hasSource ? root.doc.mergeName + " – " + root.doc.mergeCount + " Empfänger" : "Eine Excel-Mappe oder CSV-Datei: in der ersten Zeile die Feldnamen (Anrede, Name, Straße …), darunter je Zeile ein Empfänger.", I18n.revision)
        }
        PButton {
            objectName: "textMergeSource"
            Layout.fillWidth: true
            iconName: "people_list"
            text: I18n.tr(root.hasSource ? "Andere Tabelle wählen …" : "Empfänger wählen …", I18n.revision)
            enabled: root.doc !== null && root.doc.ready
            onClicked: root.doc.chooseMergeSource()
        }

        Step { number: 2; title: I18n.tr("Felder einfügen", I18n.revision); visible: root.hasSource }
        PText {
            Layout.fillWidth: true
            visible: root.hasSource
            wrap: true
            textStyle: "caption"
            tone: "secondary"
            text: I18n.tr("Klick auf ein Feld fügt es an der Schreibmarke ein.", I18n.revision)
        }
        Flow {
            Layout.fillWidth: true
            visible: root.hasSource
            spacing: 6
            Repeater {
                model: root.doc ? root.doc.mergeFields : []
                PButton {
                    required property string modelData
                    objectName: "textMergeField_" + modelData
                    text: I18n.tr("«" + modelData + "»", I18n.revision)
                    onClicked: { root.doc.insertMergeField(modelData); root.done() }
                }
            }
        }

        Step { number: 3; title: I18n.tr("Vorschau", I18n.revision); visible: root.hasSource }
        RowLayout {
            Layout.fillWidth: true
            visible: root.hasSource
            spacing: 4
            PIconButton { iconName: "chevron_left"; tip: I18n.tr("Voriger Empfänger", I18n.revision); enabled: root.record > 0; onClicked: root.record -= 1 }
            PText { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: I18n.tr("Empfänger " + (root.record + 1) + " von " + (root.doc ? root.doc.mergeCount : 0), I18n.revision) }
            PIconButton { iconName: "chevron_right"; tip: I18n.tr("Nächster Empfänger", I18n.revision); enabled: root.doc !== null && root.record < root.doc.mergeCount - 1; onClicked: root.record += 1 }
        }
        Rectangle {
            Layout.fillWidth: true
            visible: root.hasSource
            implicitHeight: preview.implicitHeight + 16
            radius: Metrics.radiusControl
            color: Theme.surface
            border.color: Theme.border
            ColumnLayout {
                id: preview
                x: 10
                y: 8
                width: parent.width - 20
                spacing: 2
                Repeater {
                    model: root.doc ? root.doc.mergeFields : []
                    RowLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        spacing: 8
                        PText { Layout.preferredWidth: 96; text: I18n.tr(modelData, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight }
                        PText { Layout.fillWidth: true; text: I18n.tr(root.values[modelData] || "–", I18n.revision); textStyle: "caption"; elide: Text.ElideRight }
                    }
                }
            }
        }

        Step { number: 4; title: I18n.tr("Briefe erstellen", I18n.revision); visible: root.hasSource }
        PButton {
            objectName: "textMergeCreate"
            Layout.fillWidth: true
            visible: root.hasSource
            kind: "accent"
            iconName: "mail_multiple"
            busy: root.doc !== null && root.doc.mergeBusy
            enabled: root.doc !== null && root.doc.ready && !root.doc.mergeBusy
            text: I18n.tr(root.doc ? root.doc.mergeCount + (root.doc.mergeCount === 1 ? " Brief erstellen" : " Briefe erstellen") : "", I18n.revision)
            onClicked: root.doc.createLetters()
        }
        PText {
            Layout.fillWidth: true
            visible: root.hasSource
            wrap: true
            textStyle: "caption"
            tone: "secondary"
            text: I18n.tr("Die Briefe kommen in ein neues Dokument, jeder auf eine eigene Seite – zum Speichern, Drucken oder als PDF.", I18n.revision)
        }
    }
}
