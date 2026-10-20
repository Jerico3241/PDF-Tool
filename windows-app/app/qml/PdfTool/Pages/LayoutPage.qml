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
    title: I18n.tr("Vertragsübersichten", I18n.revision)
    subtitle: I18n.tr("Vorlage, Layout der PDF, Kopf- und Fußzeile, Zyklus-Regeln und Regelwerk.", I18n.revision)

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
        title: I18n.tr("Vorlage", I18n.revision)
        iconName: "library"
        subtitle: I18n.tr("Hält die ganze Darstellung fest: Logo, Format, Titel, Dateiname, Kopf- und Fußzeile, Zyklus-Regeln und Regelwerk.", I18n.revision)
        headerRight: [
            PButton { kind: "subtle"; iconName: "library"; text: I18n.tr("Vorlagen verwalten", I18n.revision); tip: I18n.tr("Ansicht »Vorlagen«: umbenennen, duplizieren, Standard festlegen, löschen", I18n.revision); onClicked: App.navigate("templates") }
        ]
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PComboBox {
                objectName: "templateCombo"
                Layout.fillWidth: true
                label: I18n.tr("Geladene Vorlage", I18n.revision)
                placeholder: I18n.tr(Contracts.templateModel.count ? "Keine Vorlage geladen" : "Noch keine Vorlage gespeichert", I18n.revision)
                model: Contracts.templateModel
                textRole: "name"
                currentIndex: { Contracts.templateRevision; return Contracts.templateModel.indexOf(Contracts.vorlageId) }
                onActivated: (index) => Contracts.applyTemplate(Contracts.templateModel.get(index).id)
            }
            PBadge { text: I18n.tr(Contracts.vorlageId !== "" && Contracts.vorlageId === Contracts.defaultTemplate ? "Standard" : "", I18n.revision); tone: "accent" }
            PBadge { objectName: "templateModifiedBadge"; text: I18n.tr(Contracts.templateModified ? "Vorlage geändert" : "", I18n.revision); tone: "caution" }
            PIconButton { iconName: "dismiss"; tip: I18n.tr("Vorlage lösen – die Darstellung bleibt, wie sie ist", I18n.revision); visible: Contracts.vorlageId !== ""; onClicked: Contracts.detachTemplate() }
        }
        PText {
            objectName: "templateState"
            Layout.fillWidth: true
            Layout.topMargin: 6
            textStyle: "caption"
            tone: "secondary"
            wrap: true
            text: I18n.tr(Contracts.vorlageId === ""
                  ? "Keine Vorlage geladen – Änderungen gelten für die aktuelle Darstellung."
                  : (Contracts.templateModified
                     ? "Die Darstellung weicht von der Vorlage „" + Contracts.templateLabel + "“ ab. Aktualisieren, als neue Vorlage speichern oder verwerfen."
                     : "Die Darstellung entspricht der Vorlage „" + Contracts.templateLabel + "“."), I18n.revision)
        }
        PCollapse {
            Layout.fillWidth: true
            expanded: Contracts.templateModified
            Flow {
                width: parent.width
                topPadding: 10
                spacing: 8
                PButton { objectName: "updateTemplate"; kind: "accent"; iconName: "save"; text: I18n.tr("Vorlage aktualisieren", I18n.revision); tip: I18n.tr("Die geladene Vorlage mit der aktuellen Darstellung überschreiben", I18n.revision); onClicked: Contracts.updateTemplate() }
                PButton { iconName: "arrow_undo"; text: I18n.tr("Änderungen verwerfen", I18n.revision); tip: I18n.tr("Darstellung wieder auf den Stand der Vorlage setzen", I18n.revision); onClicked: Contracts.discardTemplateChanges() }
            }
        }
        PFieldLabel { text: I18n.tr("Als neue Vorlage speichern", I18n.revision) }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PTextField {
                id: fieldVorlage
                objectName: "newTemplateName"
                property string problem: text.trim() === "" ? "" : Contracts.templateNameProblem(text)
                Layout.fillWidth: true
                label: I18n.tr("Name der neuen Vorlage", I18n.revision)
                placeholderText: I18n.tr("Name der neuen Vorlage", I18n.revision)
                invalid: problem !== "" || Contracts.errors.vorlage === true
                onTextEdited: if (text.trim() !== "") Contracts.clearError("vorlage")
                onSubmitted: if (Contracts.saveAsTemplate(text)) text = ""
            }
            PButton {
                iconName: "add"
                text: I18n.tr("Speichern", I18n.revision)
                tip: I18n.tr("Aktuelle Darstellung als neue Vorlage speichern", I18n.revision)
                enabled: fieldVorlage.text.trim() !== "" && fieldVorlage.problem === ""
                onClicked: if (Contracts.saveAsTemplate(fieldVorlage.text)) fieldVorlage.text = ""
            }
        }
        PText { text: I18n.tr(fieldVorlage.problem, I18n.revision); visible: text !== ""; textStyle: "caption"; tone: "warning"; Layout.fillWidth: true; Layout.topMargin: 4 }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("vorlagen_info") }
    }

    // PDF-Einstellungen --------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("PDF-Einstellungen", I18n.revision)
        iconName: "document"
        subtitle: I18n.tr("Titel, Dateiname, Logo und Seitenformat der erstellten PDF.", I18n.revision)
        headerRight: [
            PIconButton { iconName: "arrow_undo"; tip: I18n.tr("Standardwerte wiederherstellen", I18n.revision); onClicked: Contracts.resetPdfSettings() }
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
                PFieldLabel { text: I18n.tr("Titel", I18n.revision); first: true }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Titel", I18n.revision); placeholderText: I18n.tr("Vertragsübersicht", I18n.revision); text: Contracts.titel; onTextEdited: Contracts.titel = text }
                PFieldLabel { text: I18n.tr("Dateiname", I18n.revision) }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Dateiname", I18n.revision); placeholderText: I18n.tr("Vertragsuebersicht_Kd{kd}.pdf", I18n.revision); text: Contracts.dateiname; onTextEdited: Contracts.dateiname = text }
                PText { text: I18n.tr(Contracts.texts.filenamePlaceholders, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 4 }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 0
                PFieldLabel { text: I18n.tr("Untertitel", I18n.revision); first: page.contentWidth >= 620 }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Untertitel", I18n.revision); placeholderText: I18n.tr("Wartungs- und Nutzungsverträge", I18n.revision); text: Contracts.untertitel; onTextEdited: Contracts.untertitel = text }
                PFieldLabel { text: I18n.tr("Logo-Breite (mm)", I18n.revision) }
                PTextField {
                    id: fieldBreite
                    preferredWidth: 120
                    label: I18n.tr("Logo-Breite in Millimetern", I18n.revision)
                    placeholderText: I18n.tr("62", I18n.revision)
                    text: Contracts.breite
                    invalid: !Contracts.validWidth(text) || Contracts.errors.breite === true
                    onTextEdited: { Contracts.breite = text; if (Contracts.validWidth(text)) Contracts.clearError("breite") }
                }
            }
        }
        PFieldLabel { text: I18n.tr("Seitenformat", I18n.revision) }
        Row {
            spacing: 24
            PRadioButton { text: I18n.tr("Hochformat A4", I18n.revision); checked: Contracts.format === "hoch"; onClicked: Contracts.setFormat("hoch") }
            PRadioButton { text: I18n.tr("Querformat A4", I18n.revision); checked: Contracts.format === "quer"; onClicked: Contracts.setFormat("quer") }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("pdf_settings_info") }
    }

    // Kopfzeile ---------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Kopfzeile", I18n.revision)
        iconName: "text_align_left"
        subtitle: I18n.tr("Optional. Erscheint oben auf jeder Seite. Leer lassen, wenn keine Kopfzeile gewünscht ist.", I18n.revision)
        PRichTextEditor {
            objectName: "headerEditor"
            Layout.fillWidth: true
            document: Contracts.headerDocument
            lines: 3
            label: I18n.tr("Kopfzeile", I18n.revision)
            placeholderText: I18n.tr("Keine Kopfzeile – hier Text eingeben, wenn oben auf jeder Seite etwas stehen soll", I18n.revision)
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 10
            spacing: 8
            PButton { kind: "accent"; iconName: "save"; text: I18n.tr("Kopfzeile speichern", I18n.revision); onClicked: Contracts.saveHeader() }
            PText { text: I18n.tr(Contracts.texts.placeholders, I18n.revision); textStyle: "caption"; tone: "secondary"; height: 32 }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("kopf_info") }
    }

    // Fußzeile -------------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Fußzeile", I18n.revision)
        iconName: "text_align_center"
        subtitle: I18n.tr("Erscheint unten auf jeder Seite. Die Seitenzahl wird automatisch ergänzt.", I18n.revision)
        GridLayout {
            Layout.fillWidth: true
            columns: page.contentWidth >= 620 ? 2 : 1
            columnSpacing: 12
            rowSpacing: 0
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                spacing: 0
                PFieldLabel { text: I18n.tr("Textbaustein", I18n.revision); first: true }
                PComboBox {
                    Layout.fillWidth: true
                    label: I18n.tr("Textbaustein", I18n.revision)
                    placeholder: I18n.tr(Contracts.textBlockModel.count ? "Textbaustein wählen" : "Noch kein Textbaustein", I18n.revision)
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
                PFieldLabel { text: I18n.tr("Name des Textbausteins (optional)", I18n.revision); first: true; Layout.topMargin: page.contentWidth >= 620 ? 0 : 12 }
                PTextField { Layout.fillWidth: true; label: I18n.tr("Name des Textbausteins", I18n.revision); placeholderText: I18n.tr("Zum Speichern als Textbaustein", I18n.revision); text: Contracts.baustein; onTextEdited: Contracts.baustein = text }
            }
        }
        PFieldLabel { text: I18n.tr("Text", I18n.revision) }
        PRichTextEditor {
            objectName: "footerEditor"
            Layout.fillWidth: true
            document: Contracts.footerDocument
            lines: 5
            label: I18n.tr("Fußzeile", I18n.revision)
            placeholderText: I18n.tr("Text der Fußzeile", I18n.revision)
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 10
            spacing: 8
            PButton { kind: "accent"; iconName: "save"; text: I18n.tr("Fußzeile speichern", I18n.revision); onClicked: Contracts.saveFooter() }
            PButton { iconName: "arrow_undo"; text: I18n.tr("Standard wiederherstellen", I18n.revision); tip: I18n.tr("Setzt Text und Formatierung der Fußzeile auf den Standard der App zurück", I18n.revision); onClicked: Contracts.restoreDefaultFooter() }
            PButton { iconName: "delete"; text: I18n.tr("Textbaustein löschen", I18n.revision); onClicked: Contracts.deleteBaustein() }
            PText { text: I18n.tr(Contracts.texts.placeholders, I18n.revision); textStyle: "caption"; tone: "secondary"; height: 32 }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("fuss_info") }
    }

    // Zyklus-Regeln -------------------------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Zyklus-Regeln", I18n.revision)
        iconName: "arrow_repeat_all"
        subtitle: I18n.tr("Enthält die Beschreibung den Begriff, wird der Abrechnungszyklus in der PDF ersetzt. Das Datum bleibt stehen.", I18n.revision)
        Rectangle {
            Layout.fillWidth: true
            visible: Contracts.ruleModel.count === 0
            implicitHeight: 40
            radius: Metrics.radiusControl
            color: Theme.surfaceSecondary
            PText { x: 12; anchors.verticalCenter: parent.verticalCenter; text: I18n.tr("Keine Regeln. Neue Regel unten eintragen.", I18n.revision); tone: "secondary" }
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
                    PText { text: I18n.tr(enthaelt, I18n.revision); textStyle: "bodyStrong" }
                    PIcon { name: "arrow_right"; color: Theme.textSecondary; size: 14 }
                    PText { text: I18n.tr(zyklus, I18n.revision); Layout.fillWidth: true }
                    PIconButton { iconName: "edit"; tip: I18n.tr("In das Formular übernehmen", I18n.revision); onClicked: Contracts.editRegel(index) }
                    PIconButton { iconName: "delete"; tip: I18n.tr("Regel „" + enthaelt + "“ löschen", I18n.revision); onClicked: Contracts.deleteRegel(index) }
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
                PFieldLabel { text: I18n.tr("Begriff", I18n.revision); first: true }
                PTextField {
                    id: fieldSuch
                    Layout.fillWidth: true
                    label: I18n.tr("Begriff", I18n.revision)
                    placeholderText: I18n.tr("z. B. Hott-KI", I18n.revision)
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
                PFieldLabel { text: I18n.tr("Zyklus", I18n.revision); first: true; Layout.topMargin: page.contentWidth >= 580 ? 0 : 12 }
                PTextField {
                    id: fieldZyk
                    Layout.fillWidth: true
                    label: I18n.tr("Zyklus", I18n.revision)
                    placeholderText: I18n.tr("z. B. jährlich", I18n.revision)
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
            PButton { kind: "accent"; iconName: "add"; text: I18n.tr("Regel speichern", I18n.revision); onClicked: Contracts.addRegel() }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("regeln_info") }
    }

    // Regelwerk ------------------------------------------------------------------------------------------------
    PCard {
        objectName: "ruleSetCard"
        Layout.fillWidth: true
        Layout.topMargin: 12
        title: I18n.tr("Regelwerk", I18n.revision)
        iconName: "filter"
        subtitle: I18n.tr("Ändert Werte der Übersicht nach eigenen Regeln (WENN … DANN …). Die Excel-Datei bleibt immer unverändert.", I18n.revision)
        headerRight: [
            PButton { kind: "subtle"; iconName: "filter"; text: I18n.tr("Regeln verwalten", I18n.revision); tip: I18n.tr("Ansicht »Regeln«: Regelwerke anlegen und bearbeiten", I18n.revision); onClicked: App.navigate("rules") }
        ]
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            PComboBox {
                objectName: "ruleSetCombo"
                Layout.fillWidth: true
                label: I18n.tr("Regelwerk der Übersicht", I18n.revision)
                model: Contracts.ruleSetChoices
                textRole: "label"
                currentIndex: {
                    for (var i = 0; i < Contracts.ruleSetChoices.length; ++i)
                        if (Contracts.ruleSetChoices[i].key === Contracts.ruleSetId) return i
                    return 0
                }
                onActivated: (index) => Contracts.setRuleSet(Contracts.ruleSetChoices[index].key)
            }
            PButton { iconName: "edit"; text: I18n.tr("Bearbeiten", I18n.revision); enabled: Contracts.ruleSetId !== ""; tip: I18n.tr("Regeln dieses Regelwerks ansehen und bearbeiten", I18n.revision); onClicked: Rules.openActive() }
        }
        PText {
            objectName: "ruleSetSummary"
            Layout.fillWidth: true
            Layout.topMargin: 6
            textStyle: "caption"
            wrap: true
            tone: Rules.activeTone === "caution" ? "warning" : "secondary"
            text: I18n.tr(Contracts.ruleSetId === "" ? "Kein Regelwerk – die Werte stehen so in der PDF, wie sie sich aus der Excel und den Zyklus-Regeln ergeben." : Rules.activeSummary, I18n.revision)
        }
    }

    // Verlauf -------------------------------------------------------------------------------------------------------
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        iconName: "history"
        title: I18n.tr("Verlauf löschen", I18n.revision)
        description: I18n.tr("Leert die Liste »Zuletzt erstellt«. PDF-Dateien und Kundenakten bleiben erhalten – Kundenakten verwalten Sie in der Ansicht »Kunden«.", I18n.revision)
        PButton { iconName: "delete"; text: I18n.tr("Löschen", I18n.revision); onClicked: Contracts.clearHistory() }
    }
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("daten_info") }
}
