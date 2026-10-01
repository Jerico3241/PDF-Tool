import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Darstellung«: geladene Vorlage (»Vorlage geändert« mit Aktualisieren,
// Verwerfen, Als neue Vorlage speichern), PDF-Einstellungen, Kopf- und Fußzeile (mit Formatierung),
// Zyklus-Regeln, Regelwerk und Verlauf. Verwaltet werden Vorlagen und Regelwerke in eigenen Ansichten.
PPage {
    id: page
    objectName: "layoutPage"
    title: "Vertragsübersichten"
    subtitle: "Vorlage, Layout der PDF, Kopf- und Fußzeile, Zyklus-Regeln und Regelwerk."

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

    // Vorlage ----------------------------------------------------------------------------------
    PCard {
        objectName: "templateCard"
        Layout.fillWidth: true
        title: "Vorlage"
        iconName: "library"
        subtitle: "Hält die ganze Darstellung fest: Logo, Format, Titel, Dateiname, Kopf- und Fußzeile, Zyklus-Regeln und Regelwerk."
        headerRight: [
            PButton { kind: "subtle"; iconName: "library"; text: "Vorlagen verwalten"; tip: "Ansicht »Vorlagen«: umbenennen, duplizieren, Standard festlegen, löschen"; onClicked: App.navigate("templates") }
        ]
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PComboBox {
                objectName: "templateCombo"
                Layout.fillWidth: true
                label: "Geladene Vorlage"
                placeholder: Contracts.templateModel.count ? "Keine Vorlage geladen" : "Noch keine Vorlage gespeichert"
                model: Contracts.templateModel
                textRole: "name"
                currentIndex: { Contracts.templateRevision; return Contracts.templateModel.indexOf(Contracts.vorlageId) }
                onActivated: (index) => Contracts.applyTemplate(Contracts.templateModel.get(index).id)
            }
            PBadge { text: Contracts.vorlageId !== "" && Contracts.vorlageId === Contracts.defaultTemplate ? "Standard" : ""; tone: "accent" }
            PBadge { objectName: "templateModifiedBadge"; text: Contracts.templateModified ? "Vorlage geändert" : ""; tone: "caution" }
            PIconButton { iconName: "dismiss"; tip: "Vorlage lösen – die Darstellung bleibt, wie sie ist"; visible: Contracts.vorlageId !== ""; onClicked: Contracts.detachTemplate() }
        }
        PText {
            objectName: "templateState"
            Layout.fillWidth: true
            Layout.topMargin: 6
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            text: Contracts.vorlageId === ""
                  ? "Keine Vorlage geladen – Änderungen gelten für die aktuelle Darstellung."
                  : (Contracts.templateModified
                     ? "Die Darstellung weicht von der Vorlage „" + Contracts.templateLabel + "“ ab. Aktualisieren, als neue Vorlage speichern oder verwerfen."
                     : "Die Darstellung entspricht der Vorlage „" + Contracts.templateLabel + "“.")
        }
        PCollapse {
            Layout.fillWidth: true
            expanded: Contracts.templateModified
            Flow {
                width: parent.width
                topPadding: 10
                spacing: 8
                PButton { objectName: "updateTemplate"; kind: "accent"; iconName: "save"; text: "Vorlage aktualisieren"; tip: "Die geladene Vorlage mit der aktuellen Darstellung überschreiben"; onClicked: Contracts.updateTemplate() }
                PButton { iconName: "arrow_undo"; text: "Änderungen verwerfen"; tip: "Darstellung wieder auf den Stand der Vorlage setzen"; onClicked: Contracts.discardTemplateChanges() }
            }
        }
        PFieldLabel { text: "Als neue Vorlage speichern" }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PTextField {
                id: fieldVorlage
                objectName: "newTemplateName"
                property string problem: text.trim() === "" ? "" : Contracts.templateNameProblem(text)
                Layout.fillWidth: true
                label: "Name der neuen Vorlage"
                placeholderText: "Name der neuen Vorlage"
                invalid: problem !== "" || Contracts.errors.vorlage === true
                onTextEdited: if (text.trim() !== "") Contracts.clearError("vorlage")
                onSubmitted: if (Contracts.saveAsTemplate(text)) text = ""
            }
            PButton {
                iconName: "add"
                text: "Speichern"
                tip: "Aktuelle Darstellung als neue Vorlage speichern"
                enabled: fieldVorlage.text.trim() !== "" && fieldVorlage.problem === ""
                onClicked: if (Contracts.saveAsTemplate(fieldVorlage.text)) fieldVorlage.text = ""
            }
        }
        PText { text: fieldVorlage.problem; visible: text !== ""; textStyle: "caption"; tone: "warning"; Layout.fillWidth: true; Layout.topMargin: 4 }
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

    // Regelwerk ------------------------------------------------------------------------------------------------
    PCard {
        objectName: "ruleSetCard"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: "Regelwerk"
        iconName: "filter"
        subtitle: "Ändert Werte der Übersicht nach eigenen Regeln (WENN … DANN …). Die Excel-Datei bleibt immer unverändert."
        headerRight: [
            PButton { kind: "subtle"; iconName: "filter"; text: "Regeln verwalten"; tip: "Ansicht »Regeln«: Regelwerke anlegen und bearbeiten"; onClicked: App.navigate("rules") }
        ]
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PComboBox {
                objectName: "ruleSetCombo"
                Layout.fillWidth: true
                label: "Regelwerk der Übersicht"
                model: Contracts.ruleSetChoices
                textRole: "label"
                currentIndex: {
                    for (var i = 0; i < Contracts.ruleSetChoices.length; ++i)
                        if (Contracts.ruleSetChoices[i].key === Contracts.ruleSetId) return i
                    return 0
                }
                onActivated: (index) => Contracts.setRuleSet(Contracts.ruleSetChoices[index].key)
            }
            PButton { iconName: "edit"; text: "Bearbeiten"; enabled: Contracts.ruleSetId !== ""; tip: "Regeln dieses Regelwerks ansehen und bearbeiten"; onClicked: Rules.openActive() }
        }
        PText {
            objectName: "ruleSetSummary"
            Layout.fillWidth: true
            Layout.topMargin: 6
            textStyle: "caption"
            wrap: true
            tone: Rules.activeTone === "caution" ? "warning" : "secondary"
            text: Contracts.ruleSetId === "" ? "Kein Regelwerk – die Werte stehen so in der PDF, wie sie sich aus der Excel und den Zyklus-Regeln ergeben." : Rules.activeSummary
        }
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
