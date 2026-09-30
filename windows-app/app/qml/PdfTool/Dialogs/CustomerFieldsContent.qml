import QtQuick
import QtQuick.Layouts
import PdfTool.Style
import PdfTool.Controls

// »Neue Kundenakte«: Firmenname, Kundennummer und optional eine E-Mail-Adresse.
ColumnLayout {
    id: root
    property var request: ({})
    function collect() { return { "company": company.text, "number": number.text, "email": email.text } }
    spacing: 0
    PFieldLabel { text: "Firmenname"; first: true }
    PTextField { id: company; Layout.fillWidth: true; label: "Firmenname"; placeholderText: "z. B. Muster GmbH"; focus: true; Component.onCompleted: forceActiveFocus() }
    PFieldLabel { text: "Kundennummer" }
    PTextField { id: number; Layout.fillWidth: true; label: "Kundennummer"; placeholderText: "z. B. 10042" }
    PFieldLabel { text: "Rechnungsempfänger-E-Mail (optional)" }
    PTextField { id: email; Layout.fillWidth: true; label: "Rechnungsempfänger-E-Mail"; placeholderText: "rechnung@kunde.de" }
    PText { text: "Kundendaten werden ausschließlich lokal auf diesem PC gespeichert."; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 12 }
}
