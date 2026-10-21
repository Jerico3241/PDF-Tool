import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Backend

// »Neue Kundenakte«: Firmenname, Kundennummer und optional eine E-Mail-Adresse.
ColumnLayout {
    id: root
    property var request: ({})
    function collect() { return { "company": company.text, "number": number.text, "email": email.text } }
    spacing: 0
    PFieldLabel { text: I18n.tr("Firmenname", I18n.revision); first: true }
    PTextField { id: company; Layout.fillWidth: true; label: I18n.tr("Firmenname", I18n.revision); placeholderText: I18n.tr("z. B. Muster GmbH", I18n.revision); focus: true; Component.onCompleted: forceActiveFocus() }
    PFieldLabel { text: I18n.tr("Kundennummer", I18n.revision) }
    PTextField { id: number; Layout.fillWidth: true; label: I18n.tr("Kundennummer", I18n.revision); placeholderText: I18n.tr("z. B. 10042", I18n.revision) }
    PFieldLabel { text: I18n.tr("Rechnungsempfänger-E-Mail (optional)", I18n.revision) }
    PTextField { id: email; Layout.fillWidth: true; label: I18n.tr("Rechnungsempfänger-E-Mail", I18n.revision); placeholderText: I18n.tr("rechnung@kunde.de", I18n.revision) }
    PText { text: I18n.tr("Kundendaten werden ausschließlich lokal auf diesem PC gespeichert.", I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
}
