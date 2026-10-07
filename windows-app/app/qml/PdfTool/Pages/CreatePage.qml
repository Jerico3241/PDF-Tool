import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Übersicht erstellen«: Kundendaten (mit optionaler Kundenakte), Dateien,
// Excel-Prüfung, Vertragsänderungen, Bereitschaft und PDF-Erstellung.
PPage {
    id: page
    objectName: "createPage"
    title: "Vertragsübersichten"
    subtitle: "Kundendaten und Excel-Liste – daraus entsteht die PDF."

    Connections {
        target: Contracts
        function onFocusRequested(field) {
            var target = { "kd": fieldKd, "firma": fieldFirma, "mail": mailFocus() }[field]
            if (target) {
                target.forceActiveFocus(Qt.OtherFocusReason)
                page.reveal(target)
            }
        }
    }
    function mailFocus() { return Contracts.mailChoices.length > 1 ? mailCombo : fieldMail }

    ContractViews {}

    GridLayout {
        Layout.fillWidth: true
        columns: page.columns
        columnSpacing: 12
        rowSpacing: 12

        // Kundendaten --------------------------------------------------------------
        PCard {
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            title: "Kundendaten"
            iconName: "contact_card"
            headerRight: [
                PIconButton { iconName: "dismiss"; tip: "Kundendaten leeren"; onClicked: Contracts.clearCustomer() }
            ]

            // Aktive Kundenakte (nur, wenn eine übernommen wurde)
            PCollapse {
                Layout.fillWidth: true
                expanded: Customers.enabled && Customers.activeId !== ""
                ColumnLayout {
                    width: parent.width
                    spacing: 0
                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: activeColumn.implicitHeight + 20
                        radius: Metrics.radiusControl
                        color: Theme.surfaceSecondary
                        border.width: 1
                        border.color: Theme.border
                        ColumnLayout {
                            id: activeColumn
                            x: 12
                            y: 10
                            width: parent.width - 24
                            spacing: 6
                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                PIcon { name: "people"; color: Theme.accentText; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    PText { text: Customers.activeTitle; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                                    PText { text: Customers.activeCaption; textStyle: "caption"; tone: Customers.activeCaptionTone; wrap: true; Layout.fillWidth: true }
                                }
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 4
                                PButton { kind: "subtle"; iconName: "open"; text: "Kundenakte öffnen"; tip: "Kundenakte in der Ansicht »Kunden« öffnen"; onClicked: Customers.openActive() }
                                PButton { kind: "subtle"; iconName: "dismiss_circle"; text: "Lösen"; tip: "Kundenakte für diese Übersicht nicht mehr verwenden – die Angaben bleiben"; onClicked: Customers.detach() }
                            }
                        }
                    }
                    Item { implicitHeight: 12 }
                }
            }

            // Bekannten Kunden auswählen (nur mit Kundenakte)
            PCollapse {
                Layout.fillWidth: true
                expanded: Customers.enabled
                ColumnLayout {
                    width: parent.width
                    spacing: 0
                    PFieldLabel { text: "Bekannten Kunden auswählen"; first: true }
                    PPickerField {
                        Layout.fillWidth: true
                        objectName: "customerPicker"
                        placeholder: Customers.pickerPlaceholder
                        tip: "Kundenakte suchen und übernehmen (Strg+F)"
                        onClicked: Customers.pickCustomer()
                    }
                    Item { implicitHeight: 12 }
                }
            }

            PFieldLabel { text: "Firmenname"; first: !Customers.enabled }
            PTextField {
                id: fieldFirma
                objectName: "fieldFirma"
                Layout.fillWidth: true
                label: "Firmenname"
                placeholderText: "z. B. Muster GmbH"
                text: Contracts.firma
                onTextEdited: Contracts.firma = text
                invalid: Contracts.errors.firma === true
            }
            PFieldLabel { text: "Kundennummer" }
            PTextField {
                id: fieldKd
                objectName: "fieldKd"
                Layout.fillWidth: true
                label: "Kundennummer"
                placeholderText: "z. B. 10042"
                text: Contracts.kd
                onTextEdited: Contracts.kd = text
                invalid: (Contracts.kdRequired || Contracts.errors.kd === true) && text.trim() === ""
            }
            PFieldLabel { text: "Rechnungsempfänger (optional)" }
            PTextField {
                id: fieldMail
                objectName: "fieldMail"
                Layout.fillWidth: true
                label: "Rechnungsempfänger"
                placeholderText: "E-Mail-Adresse"
                text: Contracts.mail
                onTextEdited: Contracts.mail = text
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunde_info") }
            PCollapse {
                Layout.fillWidth: true
                expanded: Customers.enabled
                Item {
                    width: parent.width
                    height: saveButton.height + 12
                    PButton {
                        id: saveButton
                        y: 12
                        objectName: "saveCustomer"
                        iconName: "save"
                        text: Customers.saveText
                        enabled: Customers.saveEnabled
                        tip: "Kundendaten bewusst als Kundenakte speichern bzw. die aktive Kundenakte aktualisieren"
                        onClicked: Customers.saveOrUpdate()
                    }
                }
            }
        }

        // Dateien --------------------------------------------------------------------
        PCard {
            id: filesCard
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            title: "Dateien"
            iconName: "folder"
            border.color: Contracts.dropHighlight ? Theme.accent : Theme.border
            border.width: Contracts.dropHighlight ? 2 : 1
            Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.normal } }

            PFileRow {
                Layout.fillWidth: true
                iconName: "document_table"
                label: "Excel-Liste"
                value: Contracts.excelLabel
                fullPath: Contracts.excelPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; tip: "Excel-Datei wählen (Strg+O)"; onClicked: Contracts.pickExcel() }
                PIconButton { iconName: "copy"; tip: "Pfad der Excel-Datei kopieren"; onClicked: Contracts.copyExcelPath() }
            }
            // Status der Prüfung: die einzige Stelle mit den Vertragszahlen (die Statusleiste unten
            // nennt nur das Ergebnis, z. B. »Excel geprüft.«)
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("info_excel"); closable: false }
            // Darunter nur, was die Statuszeile nicht schon sagt
            PCollapse {
                Layout.fillWidth: true
                expanded: Contracts.detailsVisible
                animate: Contracts.detailsAnimate
                ColumnLayout {
                    width: parent.width
                    spacing: 4
                    Item { implicitHeight: 4 }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: Contracts.mailValue !== ""
                        spacing: 12
                        PText { text: "Rechnungsempfänger"; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150 }
                        PText { text: Contracts.mailValue; Layout.fillWidth: true }
                        PComboBox {
                            id: mailCombo
                            visible: Contracts.mailChoices.length > 1
                            preferredWidth: 210
                            label: "Rechnungsempfänger wählen"
                            tip: "Übernimmt die Adresse als Rechnungsempfänger"
                            placeholder: "Empfänger wählen"
                            model: Contracts.mailChoices
                            currentIndex: Contracts.mailChoices.indexOf(Contracts.mail)
                            onActivated: (index) => Contracts.pickMail(Contracts.mailChoices[index])
                        }
                    }
                    PFactList { Layout.fillWidth: true; facts: Contracts.facts }
                }
            }
            // Wiedererkennung nach der Excel-Prüfung (Schließen = Ignorieren) – nur mit Kundenakte
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("kunde_match"); visible: Customers.enabled && (shown || animating) }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "image"
                label: "Logo"
                value: Contracts.logoLabel
                fullPath: Contracts.logoPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; tip: "Logo-Datei wählen"; onClicked: Contracts.pickLogo() }
                PIconButton { iconName: "arrow_reset"; tip: "Standardlogo verwenden"; onClicked: Contracts.useDefaultLogo() }
                PIconButton { iconName: "copy"; tip: "Pfad des Logos kopieren"; onClicked: Contracts.copyLogoPath() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: "Zielordner"
                value: Contracts.zielLabel
                fullPath: Contracts.zielPath
                PButton { text: "Durchsuchen"; iconName: "folder_open"; tip: "Ordner für die PDF wählen"; onClicked: Contracts.pickZiel() }
                PIconButton { iconName: "copy"; tip: "Pfad des Zielordners kopieren"; onClicked: Contracts.copyTargetPath() }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("dateien_info") }
        }
    }

    // Vertragsänderungen (nur mit Kundenakte und geprüfter Excel) -------------------------
    PCollapse {
        Layout.fillWidth: true
        Layout.topMargin: Comparison.visible ? 12 : 0
        expanded: Comparison.visible
        PCard {
            width: parent.width
            title: "Vertragsänderungen"
            iconName: "history"
            subtitle: "Vergleich mit einem gespeicherten Vertragsstand dieses Kunden – nur zur Kontrolle, die PDF bleibt unverändert."
            ComparisonSummary {
                Layout.fillWidth: true
                view: Comparison.single
            }
        }
    }

    // Aktionen ---------------------------------------------------------------------------
    PCard {
        Layout.fillWidth: true
        Layout.topMargin: 12
        // Bereitschaft: zeigt vor dem Erstellen, was noch fehlt (Klick springt zum Feld).
        PStatusLine {
            Layout.fillWidth: true
            objectName: "readiness"
            kind: Contracts.readyKind
            text: Contracts.readyText
            clickable: Contracts.readyKind !== "success" && Contracts.readyKind !== "busy"
            onActivated: Contracts.fixReadiness()
        }
        // Gewähltes Regelwerk: nie eine stille Änderung – was es an der Excel ändert, steht hier.
        PCollapse {
            objectName: "ruleSetLine"
            Layout.fillWidth: true
            expanded: Contracts.ruleSetId !== "" && Rules.activeSummary !== ""
            RowLayout {
                width: parent.width
                spacing: 8
                PIcon { name: "filter"; color: Rules.activeTone === "caution" ? Theme.warning : Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 10 }
                PText { text: Rules.activeSummary; tone: Rules.activeTone === "caution" ? "warning" : "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8 }
                PButton { kind: "subtle"; iconName: "open"; text: "Regeln ansehen"; tip: "Vorher → nachher in der Ansicht »Regeln«"; Layout.topMargin: 4; onClicked: Rules.openActive() }
            }
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PButton {
                objectName: "createPdf"
                kind: "accent"
                large: true
                minimumWidth: 180
                iconName: "document_pdf"
                text: "PDF erstellen"
                busy: Contracts.busy
                busyText: "PDF wird erstellt …"
                tip: "PDF erstellen (Strg+Enter)"
                onClicked: Contracts.startPdf()
            }
            PButton { large: true; iconName: "folder_open"; text: "Ordner öffnen"; tip: "Zielordner im Explorer öffnen"; onClicked: Contracts.openFolder() }
            // Nach dem Erstellen: die PDF als Anhang einer neuen E-Mail (an den Rechnungsempfänger, falls bekannt)
            PButton {
                objectName: "createMailPdf"
                large: true
                iconName: "mail"
                text: "Per E-Mail senden"
                tip: Contracts.lastPdfMailTip
                visible: Contracts.lastPdf !== ""
                enabled: !Contracts.busy
                onClicked: Contracts.sendPdfByMail()
            }
            Row {
                spacing: 8
                height: Metrics.controlHeightLarge
                leftPadding: 8
                PText { text: "PDF nach dem Erstellen öffnen"; anchors.verticalCenter: parent.verticalCenter }
                PToggle {
                    anchors.verticalCenter: parent.verticalCenter
                    showState: false
                    label: "PDF nach dem Erstellen öffnen"
                    checked: Contracts.pdfOeffnen
                    onToggled: { Contracts.pdfOeffnen = checked; App.scheduleSave() }
                }
            }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("pdf_info") }
        PInfoBar { objectName: "createMailInfo"; Layout.fillWidth: true; notice: Notices.area("pdf_mail_info") }
        Rectangle { Layout.fillWidth: true; Layout.topMargin: 14; Layout.bottomMargin: 12; height: 1; color: Theme.divider }
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            PText { text: "Zuletzt erstellt" }
            PComboBox {
                Layout.fillWidth: true
                preferredWidth: 200
                label: "Zuletzt erstellt"
                tip: "Zuletzt erstellte PDFs – mit »Öffnen« anzeigen"
                placeholder: "Noch keine PDF erstellt"
                model: Contracts.recentModel
                textRole: "label"
                currentIndex: Contracts.recentModel.indexOf(Contracts.recentChoice)
                onActivated: (index) => Contracts.chooseRecent(Contracts.recentModel.get(index).label)
            }
            PButton { text: "Öffnen"; iconName: "open"; tip: "Ausgewählte PDF öffnen"; enabled: Contracts.recentChoice !== ""; onClicked: Contracts.openRecentPdf() }
        }
    }
}
