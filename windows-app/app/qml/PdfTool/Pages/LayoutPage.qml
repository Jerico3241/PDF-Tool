import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Darstellung«: Vorlagen, PDF-Einstellungen, Kopf- und Fußzeile (mit
// Formatierung), Zyklus-Regeln und Verlauf.
PPage {
    id: page
    objectName: "layoutPage"
    title: "Vertragsübersichten"
    subtitle: "Vorlagen, Layout der PDF sowie Kopf- und Fußzeile."

    Connections {
        target: Contracts
        function onFocusRequested(field) {
            var target = { "breite": fieldBreite, "vorlage": fieldVorlage, "regelSuch": fieldSuch, "regelZyk": fieldZyk }[field]
            if (target) {
                target.forceActiveFocus(Qt.OtherFocusReason)
                page.reveal(target)
            }
        }
    }

    ContractViews {}

    // Vorlagen ------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        title: "Vorlagen"
        iconName: "library"
        subtitle: "Speichert Logo, Format, Dateiname, Kopfzeile, Fußzeile und Zyklus-Regeln unter einem Namen."
        GridLayout {
            Layout.fillWidth: true
            columns: page.contentWidth >= 620 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Gespeicherte Vorlage"; first: true }
                PComboBox {
                    Layout.fillWidth: true
                    label: "Gespeicherte Vorlage"
                    placeholder: Contracts.templateModel.count ? "Vorlage wählen" : "Noch keine Vorlage"
                    model: Contracts.templateModel
                    textRole: "name"
                    currentIndex: Contracts.templateModel.indexOf(Contracts.vorlage)
                    onActivated: (index) => Contracts.pickVorlage(Contracts.templateModel.get(index).name)
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Name"; first: true; Layout.topMargin: page.contentWidth >= 620 ? 0 : 12 }
                PTextField {
                    id: fieldVorlage
                    Layout.fillWidth: true
                    label: "Name der Vorlage"
                    placeholderText: "Name der Vorlage"
                    text: Contracts.vorlage
                    invalid: Contracts.errors.vorlage === true
                    onTextEdited: { Contracts.vorlage = text; if (text.trim() !== "") Contracts.clearError("vorlage") }
                    onSubmitted: Contracts.saveVorlage()
                }
            }
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PButton { kind: "accent"; iconName: "save"; text: "Vorlage speichern"; onClicked: Contracts.saveVorlage() }
            PButton { iconName: "delete"; text: "Vorlage löschen"; onClicked: Contracts.deleteVorlage() }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_info") }
    }

    // PDF-Einstellungen --------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "PDF-Einstellungen"
        iconName: "document"
        subtitle: "Titel, Dateiname, Logo und Seitenformat der erstellten PDF."
        headerRight: [
            PIconButton { iconName: "arrow_undo"; tip: "Standardwerte wiederherstellen"; onClicked: Contracts.resetPdfSettings() }
        ]
        GridLayout {
            Layout.fillWidth: true
            columns: page.contentWidth >= 620 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 0
                PFieldLabel { text: "Titel"; first: true }
                PTextField { Layout.fillWidth: true; label: "Titel"; placeholderText: "Vertragsübersicht"; text: Contracts.titel; onTextEdited: Contracts.titel = text }
                PFieldLabel { text: "Dateiname" }
                PTextField { Layout.fillWidth: true; label: "Dateiname"; placeholderText: "Vertragsuebersicht_Kd{kd}.pdf"; text: Contracts.dateiname; onTextEdited: Contracts.dateiname = text }
                PText { text: Contracts.texts.filenamePlaceholders; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 0
                PFieldLabel { text: "Untertitel"; first: page.contentWidth >= 620 }
                PTextField { Layout.fillWidth: true; label: "Untertitel"; placeholderText: "Wartungs- und Nutzungsverträge"; text: Contracts.untertitel; onTextEdited: Contracts.untertitel = text }
                PFieldLabel { text: "Logo-Breite (mm)" }
                PTextField {
                    id: fieldBreite
                    preferredWidth: 120
                    label: "Logo-Breite in Millimetern"
                    placeholderText: "62"
                    text: Contracts.breite
                    invalid: !Contracts.validWidth(text) || Contracts.errors.breite === true
                    onTextEdited: { Contracts.breite = text; if (Contracts.validWidth(text)) Contracts.clearError("breite") }
                }
            }
        }
        PFieldLabel { text: "Seitenformat" }
        Row {
            spacing: 24
            PRadioButton { text: "Hochformat A4"; checked: Contracts.format === "hoch"; onClicked: Contracts.setFormat("hoch") }
            PRadioButton { text: "Querformat A4"; checked: Contracts.format === "quer"; onClicked: Contracts.setFormat("quer") }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("pdf_settings_info") }
    }

    // Kopfzeile ---------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Kopfzeile"
        iconName: "text_align_left"
        subtitle: "Optional. Erscheint oben auf jeder Seite. Leer lassen, wenn keine Kopfzeile gewünscht ist."
        PRichTextEditor {
            objectName: "headerEditor"
            Layout.fillWidth: true
            document: Contracts.headerDocument
            lines: 3
            label: "Kopfzeile"
            placeholderText: "Keine Kopfzeile – hier Text eingeben, wenn oben auf jeder Seite etwas stehen soll"
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 10
            spacing: 8
            PButton { kind: "accent"; iconName: "save"; text: "Kopfzeile speichern"; onClicked: Contracts.saveHeader() }
            PText { text: Contracts.texts.placeholders; textStyle: "caption"; tone: "secondary"; height: 32 }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("kopf_info") }
    }

    // Fußzeile -------------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Fußzeile"
        iconName: "text_align_center"
        subtitle: "Erscheint unten auf jeder Seite. Die Seitenzahl wird automatisch ergänzt."
        GridLayout {
            Layout.fillWidth: true
            columns: page.contentWidth >= 620 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Textbaustein"; first: true }
                PComboBox {
                    Layout.fillWidth: true
                    label: "Textbaustein"
                    placeholder: Contracts.textBlockModel.count ? "Textbaustein wählen" : "Noch kein Textbaustein"
                    model: Contracts.textBlockModel
                    textRole: "name"
                    currentIndex: Contracts.textBlockModel.indexOf(Contracts.baustein)
                    onActivated: (index) => Contracts.pickBaustein(Contracts.textBlockModel.get(index).name)
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Name des Textbausteins (optional)"; first: true; Layout.topMargin: page.contentWidth >= 620 ? 0 : 12 }
                PTextField { Layout.fillWidth: true; label: "Name des Textbausteins"; placeholderText: "Zum Speichern als Textbaustein"; text: Contracts.baustein; onTextEdited: Contracts.baustein = text }
            }
        }
        PFieldLabel { text: "Text" }
        PRichTextEditor {
            objectName: "footerEditor"
            Layout.fillWidth: true
            document: Contracts.footerDocument
            lines: 5
            label: "Fußzeile"
            placeholderText: "Text der Fußzeile"
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 10
            spacing: 8
            PButton { kind: "accent"; iconName: "save"; text: "Fußzeile speichern"; onClicked: Contracts.saveFooter() }
            PButton { iconName: "arrow_undo"; text: "Standard wiederherstellen"; tip: "Setzt Text und Formatierung der Fußzeile auf den Standard der App zurück"; onClicked: Contracts.restoreDefaultFooter() }
            PButton { iconName: "delete"; text: "Textbaustein löschen"; onClicked: Contracts.deleteBaustein() }
            PText { text: Contracts.texts.placeholders; textStyle: "caption"; tone: "secondary"; height: 32 }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("fuss_info") }
    }

    // Zyklus-Regeln -------------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Zyklus-Regeln"
        iconName: "arrow_repeat_all"
        subtitle: "Enthält die Beschreibung den Begriff, wird der Abrechnungszyklus in der PDF ersetzt. Das Datum bleibt stehen."
        Rectangle {
            Layout.fillWidth: true
            visible: Contracts.ruleModel.count === 0
            implicitHeight: 40
            radius: Metrics.radiusControl
            color: Theme.surfaceSecondary
            PText { x: 12; anchors.verticalCenter: parent.verticalCenter; text: "Keine Regeln. Neue Regel unten eintragen."; tone: "secondary" }
        }
        Repeater {
            model: Contracts.ruleModel
            Rectangle {
                required property int index
                required property string enthaelt
                required property string zyklus
                Layout.fillWidth: true
                Layout.topMargin: index === 0 ? 0 : 4
                implicitHeight: 40
                radius: Metrics.radiusControl
                color: Theme.surfaceSecondary
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 4
                    spacing: 10
                    PText { text: enthaelt; textStyle: "bodyStrong" }
                    PIcon { name: "arrow_right"; color: Theme.textSecondary; size: 14 }
                    PText { text: zyklus; Layout.fillWidth: true }
                    PIconButton { iconName: "edit"; tip: "In das Formular übernehmen"; onClicked: Contracts.editRegel(index) }
                    PIconButton { iconName: "delete"; tip: "Regel „" + enthaelt + "“ löschen"; onClicked: Contracts.deleteRegel(index) }
                }
            }
        }
        GridLayout {
            Layout.fillWidth: true
            Layout.topMargin: 12
            columns: page.contentWidth >= 580 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Begriff"; first: true }
                PTextField {
                    id: fieldSuch
                    Layout.fillWidth: true
                    label: "Begriff"
                    placeholderText: "z. B. Hott-KI"
                    text: Contracts.regelSuch
                    invalid: Contracts.errors.regelSuch === true
                    onTextEdited: { Contracts.regelSuch = text; if (text.trim() !== "") Contracts.clearError("regelSuch") }
                    onSubmitted: Contracts.addRegel()
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: "Zyklus"; first: true; Layout.topMargin: page.contentWidth >= 580 ? 0 : 12 }
                PTextField {
                    id: fieldZyk
                    Layout.fillWidth: true
                    label: "Zyklus"
                    placeholderText: "z. B. jährlich"
                    text: Contracts.regelZyk
                    invalid: Contracts.errors.regelZyk === true
                    onTextEdited: { Contracts.regelZyk = text; if (text.trim() !== "") Contracts.clearError("regelZyk") }
                    onSubmitted: Contracts.addRegel()
                }
            }
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            PButton { kind: "accent"; iconName: "add"; text: "Regel speichern"; onClicked: Contracts.addRegel() }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_info") }
    }

    // Verlauf -------------------------------------------------------------------------------------------------------
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        iconName: "history"
        title: "Verlauf löschen"
        description: "Leert die Liste »Zuletzt erstellt«. PDF-Dateien und Kundenakten bleiben erhalten – Kundenakten verwalten Sie in der Ansicht »Kunden«."
        PButton { iconName: "delete"; text: "Löschen"; onClicked: Contracts.clearHistory() }
    }
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("daten_info") }
}
