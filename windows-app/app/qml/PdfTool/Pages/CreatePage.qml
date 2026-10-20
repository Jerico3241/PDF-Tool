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
    title: I18n.tr("Vertragsübersichten", I18n.revision)
    subtitle: I18n.tr("Kundendaten und Excel-Liste – daraus entsteht die PDF.", I18n.revision)

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
            title: I18n.tr("Kundendaten", I18n.revision)
            iconName: "contact_card"
            headerRight: [
                PIconButton { iconName: "dismiss"; tip: I18n.tr("Kundendaten leeren", I18n.revision); onClicked: Contracts.clearCustomer() }
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
                                    PText { text: I18n.tr(Customers.activeTitle, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                                    PText { text: I18n.tr(Customers.activeCaption, I18n.revision); textStyle: "caption"; tone: Customers.activeCaptionTone; wrap: true; Layout.fillWidth: true }
                                }
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 4
                                PButton { kind: "subtle"; iconName: "open"; text: I18n.tr("Kundenakte öffnen", I18n.revision); tip: I18n.tr("Kundenakte in der Ansicht »Kunden« öffnen", I18n.revision); onClicked: Customers.openActive() }
                                PButton { kind: "subtle"; iconName: "dismiss_circle"; text: I18n.tr("Lösen", I18n.revision); tip: I18n.tr("Kundenakte für diese Übersicht nicht mehr verwenden – die Angaben bleiben", I18n.revision); onClicked: Customers.detach() }
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
                    PFieldLabel { text: I18n.tr("Bekannten Kunden auswählen", I18n.revision); first: true }
                    PPickerField {
                        Layout.fillWidth: true
                        objectName: "customerPicker"
                        placeholder: I18n.tr(Customers.pickerPlaceholder, I18n.revision)
                        tip: I18n.tr("Kundenakte suchen und übernehmen" + Shortcuts.hints["app.find"], I18n.revision)
                        onClicked: Customers.pickCustomer()
                    }
                    Item { implicitHeight: 12 }
                }
            }

            PFieldLabel { text: I18n.tr("Firmenname", I18n.revision); first: !Customers.enabled }
            PTextField {
                id: fieldFirma
                objectName: "fieldFirma"
                Layout.fillWidth: true
                label: I18n.tr("Firmenname", I18n.revision)
                placeholderText: I18n.tr("z. B. Muster GmbH", I18n.revision)
                text: Contracts.firma
                onTextEdited: Contracts.firma = text
                invalid: Contracts.errors.firma === true
            }
            PFieldLabel { text: I18n.tr("Kundennummer", I18n.revision) }
            PTextField {
                id: fieldKd
                objectName: "fieldKd"
                Layout.fillWidth: true
                label: I18n.tr("Kundennummer", I18n.revision)
                placeholderText: I18n.tr("z. B. 10042", I18n.revision)
                text: Contracts.kd
                onTextEdited: Contracts.kd = text
                invalid: (Contracts.kdRequired || Contracts.errors.kd === true) && text.trim() === ""
            }
            PFieldLabel { text: I18n.tr("Rechnungsempfänger (optional)", I18n.revision) }
            PTextField {
                id: fieldMail
                objectName: "fieldMail"
                Layout.fillWidth: true
                label: I18n.tr("Rechnungsempfänger", I18n.revision)
                placeholderText: I18n.tr("E-Mail-Adresse", I18n.revision)
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
                        text: I18n.tr(Customers.saveText, I18n.revision)
                        enabled: Customers.saveEnabled
                        tip: I18n.tr("Kundendaten bewusst als Kundenakte speichern bzw. die aktive Kundenakte aktualisieren", I18n.revision)
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
            title: I18n.tr("Dateien", I18n.revision)
            iconName: "folder"
            border.color: Contracts.dropHighlight ? Theme.accent : Theme.border
            border.width: Contracts.dropHighlight ? 2 : 1
            Behavior on border.color { enabled: Motion.enabled; ColorAnimation { duration: Motion.normal } }

            PFileRow {
                Layout.fillWidth: true
                iconName: "document_table"
                label: I18n.tr("Excel-Liste", I18n.revision)
                value: Contracts.excelLabel
                fullPath: Contracts.excelPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Excel-Datei wählen" + Shortcuts.hints["app.open"], I18n.revision); onClicked: Contracts.pickExcel() }
                PIconButton { iconName: "copy"; tip: I18n.tr("Pfad der Excel-Datei kopieren", I18n.revision); onClicked: Contracts.copyExcelPath() }
            }
            // Gekündigte bzw. abgelaufene Verträge (Anwenderstatus) mit aufführen – je eigener Schalter, in der PDF mit Status
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("Gekündigte Verträge mit aufführen", I18n.revision)
                    wrapMode: Text.WordWrap
                }
                PToggle {
                    objectName: "createCancelledContracts"
                    showState: false
                    label: I18n.tr("Gekündigte Verträge mit aufführen", I18n.revision)
                    tip: I18n.tr("Verträge mit dem Anwenderstatus »Gekündigt« stehen mit in der Übersicht – mit dem Status unter der Vertragsnummer", I18n.revision)
                    checked: Contracts.gekuendigt
                    onToggled: Contracts.gekuendigt = checked
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("Abgelaufene Verträge mit aufführen", I18n.revision)
                    wrapMode: Text.WordWrap
                }
                PToggle {
                    objectName: "createExpiredContracts"
                    showState: false
                    label: I18n.tr("Abgelaufene Verträge mit aufführen", I18n.revision)
                    tip: I18n.tr("Verträge mit dem Anwenderstatus »Abgelaufen« stehen mit in der Übersicht – mit dem Status unter der Vertragsnummer", I18n.revision)
                    checked: Contracts.abgelaufen
                    onToggled: Contracts.abgelaufen = checked
                }
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
                        PText { text: I18n.tr("Rechnungsempfänger", I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150 }
                        PText { text: I18n.tr(Contracts.mailValue, I18n.revision); Layout.fillWidth: true }
                        PComboBox {
                            id: mailCombo
                            visible: Contracts.mailChoices.length > 1
                            preferredWidth: 210
                            label: I18n.tr("Rechnungsempfänger wählen", I18n.revision)
                            tip: I18n.tr("Übernimmt die Adresse als Rechnungsempfänger", I18n.revision)
                            placeholder: I18n.tr("Empfänger wählen", I18n.revision)
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
                label: I18n.tr("Logo", I18n.revision)
                value: Contracts.logoLabel
                fullPath: Contracts.logoPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Logo-Datei wählen", I18n.revision); onClicked: Contracts.pickLogo() }
                PIconButton { iconName: "arrow_reset"; tip: I18n.tr("Standardlogo verwenden", I18n.revision); onClicked: Contracts.useDefaultLogo() }
                PIconButton { iconName: "copy"; tip: I18n.tr("Pfad des Logos kopieren", I18n.revision); onClicked: Contracts.copyLogoPath() }
            }
            Rectangle { Layout.fillWidth: true; Layout.topMargin: 10; Layout.bottomMargin: 10; height: 1; color: Theme.divider }
            PFileRow {
                Layout.fillWidth: true
                iconName: "folder"
                label: I18n.tr("Zielordner", I18n.revision)
                value: Contracts.zielLabel
                fullPath: Contracts.zielPath
                PButton { text: I18n.tr("Durchsuchen", I18n.revision); iconName: "folder_open"; tip: I18n.tr("Ordner für die PDF wählen", I18n.revision); onClicked: Contracts.pickZiel() }
                PIconButton { iconName: "copy"; tip: I18n.tr("Pfad des Zielordners kopieren", I18n.revision); onClicked: Contracts.copyTargetPath() }
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
            title: I18n.tr("Vertragsänderungen", I18n.revision)
            iconName: "history"
            subtitle: I18n.tr("Vergleich mit einem gespeicherten Vertragsstand dieses Kunden – nur zur Kontrolle, die PDF bleibt unverändert.", I18n.revision)
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
            text: I18n.tr(Contracts.readyText, I18n.revision)
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
                PText { text: I18n.tr(Rules.activeSummary, I18n.revision); tone: Rules.activeTone === "caution" ? "warning" : "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 8 }
                PButton { kind: "subtle"; iconName: "open"; text: I18n.tr("Regeln ansehen", I18n.revision); tip: I18n.tr("Vorher → nachher in der Ansicht »Regeln«", I18n.revision); Layout.topMargin: 4; onClicked: Rules.openActive() }
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
                text: I18n.tr("PDF erstellen", I18n.revision)
                busy: Contracts.busy
                busyText: I18n.tr("PDF wird erstellt …", I18n.revision)
                tip: I18n.tr("PDF erstellen" + Shortcuts.hints["app.primary"], I18n.revision)
                onClicked: Contracts.startPdf()
            }
            PButton { large: true; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); tip: I18n.tr("Zielordner im Explorer öffnen", I18n.revision); onClicked: Contracts.openFolder() }
            // Nach dem Erstellen: die PDF als Anhang einer neuen E-Mail (an den Rechnungsempfänger, falls bekannt)
            PButton {
                objectName: "createMailPdf"
                large: true
                iconName: "mail"
                text: I18n.tr("Per E-Mail senden", I18n.revision)
                tip: I18n.tr(Contracts.lastPdfMailTip, I18n.revision)
                visible: Contracts.lastPdf !== ""
                enabled: !Contracts.busy
                onClicked: Contracts.sendPdfByMail()
            }
            Row {
                spacing: 8
                height: Metrics.controlHeightLarge
                leftPadding: 8
                PText { text: I18n.tr("PDF nach dem Erstellen öffnen", I18n.revision); anchors.verticalCenter: parent.verticalCenter }
                PToggle {
                    anchors.verticalCenter: parent.verticalCenter
                    showState: false
                    label: I18n.tr("PDF nach dem Erstellen öffnen", I18n.revision)
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
            PText { text: I18n.tr("Zuletzt erstellt", I18n.revision) }
            PComboBox {
                Layout.fillWidth: true
                preferredWidth: 200
                label: I18n.tr("Zuletzt erstellt", I18n.revision)
                tip: I18n.tr("Zuletzt erstellte PDFs – mit »Öffnen« anzeigen", I18n.revision)
                placeholder: I18n.tr("Noch keine PDF erstellt", I18n.revision)
                model: Contracts.recentModel
                textRole: "label"
                currentIndex: Contracts.recentModel.indexOf(Contracts.recentChoice)
                onActivated: (index) => Contracts.chooseRecent(Contracts.recentModel.get(index).label)
            }
            PButton { text: I18n.tr("Öffnen", I18n.revision); iconName: "open"; tip: I18n.tr("Ausgewählte PDF öffnen", I18n.revision); enabled: Contracts.recentChoice !== ""; onClicked: Contracts.openRecentPdf() }
        }
    }
}
