import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Einstellungen: Design, Akzentfarbe, Mica, Animationen, PDF Reader, Kundenakte, Sicherung,
// Updates, Diagnose und Info. Alles wirkt sofort.
PPage {
    id: page
    objectName: "settingsPage"
    title: "Einstellungen"
    signal themeRequested(var apply)

    function indexOfValue(list, value) {
        for (var i = 0; i < list.length; ++i)
            if (list[i].value === value) return i
        return -1
    }

    PSectionTitle { text: "Darstellung"; Layout.topMargin: 0 }

    PSettingsCard {
        Layout.fillWidth: true
        iconName: "dark_theme"
        title: "App-Design"
        description: "Hell, Dunkel oder automatisch wie der Windows-App-Modus"
        PComboBox {
            id: themeCombo
            objectName: "themeCombo"
            preferredWidth: 180
            label: "App-Design"
            model: Settings.themes
            textRole: "label"
            valueRole: "value"
            currentIndex: page.indexOfValue(Settings.themes, ThemeBackend.mode)
            onActivated: (index) => {
                var value = Settings.themes[index].value
                page.themeRequested(function() { Settings.setTheme(value) })
            }
        }
    }

    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "color"
        title: "Akzentfarbe"
        description: "Für Schaltflächen, Auswahl, Hinweise und die Tabs"
        expandable: true
        expanded: true
        PText {
            text: ThemeBackend.accentName
            tone: "secondary"
            height: 32
        }
        extra: Flow {
            width: parent ? parent.width - 68 : 300
            spacing: 2
            Repeater {
                model: ThemeBackend.accents
                PSwatch {
                    required property var modelData
                    swatchColor: modelData.color
                    selected: String(ThemeBackend.accentChoice).toLowerCase() === String(modelData.value).toLowerCase()
                    iconName: modelData.system ? "desktop" : ""
                    tip: modelData.name
                    onClicked: {
                        var value = modelData.value
                        page.themeRequested(function() { Settings.setAccent(value) })
                    }
                }
            }
        }
    }

    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "lightbulb"
        title: "Mica-Material"
        description: ThemeBackend.micaDescription
        PToggle {
            objectName: "micaToggle"
            label: "Mica-Material"
            enabled: ThemeBackend.micaAvailable
            checked: ThemeBackend.micaAvailable && ThemeBackend.micaEnabled
            onToggled: Settings.setMica(checked)
        }
    }

    PSectionTitle { text: "Verhalten" }

    PSettingsCard {
        Layout.fillWidth: true
        iconName: "play"
        title: "Animationen"
        description: {
            var profiles = Settings.profiles
            var index = page.indexOfValue(profiles, ThemeBackend.profile)
            var text = index >= 0 ? profiles[index].text : ""
            return ThemeBackend.profileNote !== "" ? text + " " + ThemeBackend.profileNote : text
        }
        PComboBox {
            objectName: "profileCombo"
            preferredWidth: 180
            label: "Animationen"
            model: Settings.profiles
            textRole: "label"
            valueRole: "value"
            currentIndex: page.indexOfValue(Settings.profiles, ThemeBackend.profile)
            onActivated: (index) => Settings.setProfile(Settings.profiles[index].value)
        }
    }

    // Ansicht neu geöffneter PDFs – »Zuletzt verwendet« (Standard) wie bisher
    PSectionTitle { text: "PDF Reader" }

    PSettingsCard {
        objectName: "readerZoomCard"
        Layout.fillWidth: true
        iconName: "zoom_in"
        title: "Standardzoom beim Öffnen"
        description: "Für neu geöffnete PDFs. »Zuletzt verwendet« übernimmt die zuletzt eingestellte Ansicht."
        PComboBox {
            objectName: "readerZoomCombo"
            preferredWidth: 180
            label: "Standardzoom beim Öffnen"
            model: Settings.readerZooms
            textRole: "label"
            valueRole: "value"
            currentIndex: page.indexOfValue(model, Settings.readerZoom)
            onActivated: (index) => Settings.setReaderZoom(model[index].value)
        }
    }

    PSettingsCard {
        objectName: "readerPanelCard"
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "panel_left"
        title: "Seitenleiste beim Öffnen"
        description: "Linke Seitenleiste, wenn ein PDF geöffnet wird. »Zuletzt verwendet« zeigt die zuletzt gewählte."
        PComboBox {
            objectName: "readerPanelCombo"
            preferredWidth: 180
            label: "Seitenleiste beim Öffnen"
            model: Settings.readerPanels
            textRole: "label"
            valueRole: "value"
            currentIndex: page.indexOfValue(model, Settings.readerPanel)
            onActivated: (index) => Settings.setReaderPanel(model[index].value)
        }
    }

    // Nachtmodus: nur die Anzeige der Seiten – Datei, Drucken und Export bleiben unverändert
    PSettingsCard {
        objectName: "readerNightCard"
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "weather_moon"
        title: "Nachtmodus"
        description: "Seiten dunkelgrau mit heller Schrift – angenehmer bei wenig Licht. Nur die Anzeige: Datei, Drucken und Export bleiben unverändert."
        PToggle {
            objectName: "readerNightToggle"
            label: "Nachtmodus"
            checked: Reader.nightMode
            onToggled: Reader.setNightMode(checked)
        }
    }

    // Letzte Sitzung: beim Beenden gemerkt (nur Pfade, lokal in den Einstellungen), beim nächsten Start wieder geöffnet
    PSettingsCard {
        objectName: "readerSessionCard"
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "history"
        title: "PDFs der letzten Sitzung beim Start wieder öffnen"
        description: "Beim Beenden merkt sich PDF Tool die geöffneten PDFs (nur Pfade, lokal auf diesem PC) und öffnet sie beim nächsten Start wieder – ungespeicherte Änderungen nicht."
        PToggle {
            objectName: "readerSessionToggle"
            label: "PDFs der letzten Sitzung beim Start wieder öffnen"
            checked: Settings.readerRestoreSession
            onToggled: Settings.setReaderRestoreSession(checked)
        }
    }

    PSectionTitle { text: "Vertragsübersichten" }

    PSettingsCard {
        Layout.fillWidth: true
        iconName: "people"
        title: Settings.texts.customerTitle
        description: Settings.texts.customerText
        expandable: true
        expanded: true
        PToggle {
            objectName: "customerRecordsToggle"
            label: Settings.texts.customerTitle
            checked: Settings.customerRecords
            onToggled: Settings.setCustomerRecords(checked)
        }
        extra: RowLayout {
            width: parent ? parent.width - 68 : 300
            spacing: 8
            PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
            PText { text: Settings.texts.customerNote; textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
        }
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        text: "Einstellungen der einzelnen Werkzeuge stehen im jeweiligen Werkzeug – z. B. Vorlagen und Verlauf unter »Vertragsübersichten · Darstellung«."
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }

    PSectionTitle { text: "Sicherung & Wiederherstellung" }

    // Sicherung: Status, Jetzt sichern, Wiederherstellen, gesicherte Stände
    PCard {
        objectName: "backupCard"
        Layout.fillWidth: true
        title: "Sicherung"
        iconName: "shield_checkmark"
        subtitle: "Einstellungen, Kundenakten mit Vertragsständen, Vorlagen und Regelwerke in einer Datei (.pdtbackup) – lokal auf diesem PC, keine Cloud."
        PFactList {
            objectName: "backupStatus"
            Layout.fillWidth: true
            labelWidth: 210
            facts: [
                { "label": "Letzte automatische Sicherung", "value": Backup.lastAuto },
                { "label": "Letzte manuelle Sicherung", "value": Backup.lastManual }
            ]
        }
        PCollapse {
            Layout.fillWidth: true
            expanded: Backup.busy
            ColumnLayout {
                width: parent.width
                spacing: 6
                PText { objectName: "backupBusy"; text: Backup.busyText; Layout.topMargin: 10 }
                PProgressBar { Layout.fillWidth: true; value: Backup.progress; indeterminate: Backup.progress <= 0 }
            }
        }
        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 12
            spacing: 8
            PButton { objectName: "backupNow"; kind: "accent"; iconName: "save"; text: "Jetzt sichern …"; tip: "Sicherung in einen Ordner Ihrer Wahl (z. B. USB-Stick)"; enabled: !Backup.busy; onClicked: Backup.backupNow() }
            PButton { objectName: "restoreBackup"; iconName: "arrow_undo"; text: "Wiederherstellen …"; tip: "Sicherung wählen, prüfen und Bereiche wiederherstellen"; enabled: !Backup.busy; onClicked: Backup.restoreFrom() }
            PButton { kind: "subtle"; iconName: "folder_open"; text: "Ordner öffnen"; tip: "Ordner der automatischen Sicherungen öffnen"; onClicked: Backup.openFolder() }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("sicherung_info") }
        PInfoBar {
            objectName: "backupPending"
            Layout.fillWidth: true
            notice: null
            shown: Backup.pending !== ""
            severity: "info"
            message: Backup.pending
            closable: false
            actions: ["Verwerfen"]
            onActionTriggered: (index) => Backup.discardPending()
        }
        PText {
            Layout.fillWidth: true
            Layout.topMargin: 14
            visible: Backup.recentModel.count > 0
            text: "Gesicherte Stände im Ordner der automatischen Sicherungen"
            textStyle: "bodyStrong"
        }
        Repeater {
            model: Backup.recentModel
            Rectangle {
                required property int index
                required property string path
                required property string name
                required property string kind
                required property string date
                required property string size
                required property string version
                Layout.fillWidth: true
                Layout.topMargin: index === 0 ? 6 : 4
                implicitHeight: 44
                radius: Metrics.radiusControl
                color: Theme.surfaceSecondary
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 4
                    spacing: 10
                    PText { text: date; Layout.preferredWidth: 140 }
                    PText { text: kind + (version !== "" ? " · " + version : "") + " · " + size; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                    PButton { kind: "subtle"; text: "Wiederherstellen …"; enabled: !Backup.busy; tip: name; onClicked: Backup.restore(path) }
                }
            }
        }
    }
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "clock"
        title: "Automatisch sichern"
        description: "Einmal am Tag, wenn sich etwas geändert hat, und vor jedem Update. Die letzten 10 automatischen Sicherungen bleiben erhalten – manuelle Sicherungen werden nie automatisch gelöscht."
        PToggle {
            objectName: "backupAutomaticToggle"
            label: "Automatisch sichern"
            checked: Backup.automatic
            onToggled: Backup.setAutomatic(checked)
        }
    }
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "folder"
        title: "Ordner der automatischen Sicherungen"
        description: Backup.folderText
        Row {
            spacing: 4
            PButton { text: "Ändern …"; onClicked: Backup.pickAutoFolder() }
            PIconButton { iconName: "arrow_reset"; tip: "Standardordner verwenden"; onClicked: Backup.resetAutoFolder() }
        }
    }

    PSectionTitle { text: "Updates" }

    // Version, Zustand des Updaters, verfügbares Update mit Fortschritt und Aktionen
    Rectangle {
        id: updateCard
        objectName: "updateCard"
        Layout.fillWidth: true
        implicitHeight: updateColumn.implicitHeight + 32
        radius: Metrics.radiusCard
        color: Theme.surface
        border.width: 1
        border.color: Theme.border
        readonly property string phase: Updates.state
        readonly property bool working: phase === "checking" || phase === "downloading" || phase === "verifying" || phase === "installing"
        readonly property bool offerShown: Updates.hasOffer && phase !== "up_to_date" && phase !== "checking"

        ColumnLayout {
            id: updateColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 16
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 16
                PIcon { name: "arrow_sync"; size: Metrics.iconSizeMedium; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    RowLayout {
                        spacing: 8
                        PText { objectName: "updateCurrentVersion"; text: "PDF Tool " + Updates.currentVersion }
                        PBadge { objectName: "updateCurrentBeta"; text: Updates.currentBeta ? "Beta" : ""; tone: "accent" }
                    }
                    PText {
                        objectName: "updateLastCheck"
                        text: "Letzte Prüfung: " + Updates.lastCheck
                        textStyle: "caption"
                        tone: "secondary"
                        Layout.fillWidth: true
                    }
                }
                PButton {
                    objectName: "updateCheckButton"
                    text: "Nach Updates suchen"
                    iconName: "arrow_sync"
                    enabled: Updates.canCheck
                    busy: Updates.state === "checking"
                    busyText: "Suche …"
                    onClicked: Updates.checkNow()
                }
            }

            // Zustand: »PDF Tool ist aktuell.«, »Nach Updates wird gesucht …«, Fehler …
            RowLayout {
                objectName: "updateStatus"
                Layout.fillWidth: true
                Layout.leftMargin: 36
                spacing: 8
                visible: !updateCard.offerShown
                Item {
                    Layout.preferredWidth: 16
                    Layout.preferredHeight: 16
                    Layout.alignment: Qt.AlignTop
                    Layout.topMargin: 2
                    PProgressRing { anchors.centerIn: parent; size: 14; visible: updateCard.working; running: visible }
                    PIcon {
                        anchors.centerIn: parent
                        size: 14
                        visible: !updateCard.working && Updates.statusKind !== "neutral"
                        name: Theme.toneIcon(Updates.statusKind)
                        color: Theme.toneIconColor(Updates.statusKind)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    PText { objectName: "updateStatusTitle"; text: Updates.statusTitle; wrap: true; Layout.fillWidth: true }
                    PText { text: Updates.statusText; textStyle: "caption"; tone: "secondary"; wrap: true; visible: text !== ""; Layout.fillWidth: true }
                }
            }

            // Verfügbares Update (auch während Download, Prüfung, bereit, abgebrochen oder Fehler)
            Rectangle {
                objectName: "updateOffer"
                Layout.fillWidth: true
                Layout.leftMargin: 36
                visible: updateCard.offerShown
                implicitHeight: offerColumn.implicitHeight + 24
                radius: Metrics.radiusControl
                color: Theme.surfaceSecondary
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    id: offerColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 6
                    RowLayout {
                        spacing: 8
                        Layout.fillWidth: true
                        PText { objectName: "updateOfferTitle"; text: Updates.offerTitle; textStyle: "bodyStrong" }
                        PBadge { text: Updates.offerBeta ? "Beta-Update" : ""; tone: "accent" }
                        Item { Layout.fillWidth: true }
                    }
                    PText {
                        text: [Updates.offerDate !== "" ? "Veröffentlicht am " + Updates.offerDate : "", Updates.offerSize !== "" ? "Größe: " + Updates.offerSize : ""].filter(function(part) { return part !== "" }).join(" · ")
                        textStyle: "caption"
                        tone: "secondary"
                        Layout.fillWidth: true
                    }
                    PText {
                        objectName: "updateOfferStatus"
                        text: Updates.statusTitle
                        tone: Updates.statusKind === "error" ? "error" : (Updates.statusKind === "success" ? "success" : "")
                        wrap: true
                        visible: updateCard.phase !== "available"
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                    }
                    PProgressBar {
                        objectName: "updateProgress"
                        Layout.fillWidth: true
                        visible: updateCard.phase === "downloading" || updateCard.phase === "verifying"
                        indeterminate: updateCard.phase === "verifying"
                        value: Updates.progress
                    }
                    PText {
                        objectName: "updateProgressText"
                        text: updateCard.phase === "downloading" ? Updates.progressText : Updates.statusText
                        textStyle: "caption"
                        tone: "secondary"
                        wrap: true
                        visible: text !== "" && updateCard.phase !== "available"
                        Layout.fillWidth: true
                    }
                    PInfoBar {
                        Layout.fillWidth: true
                        shown: Updates.workHint !== ""
                        severity: "warning"
                        message: Updates.workHint
                        closable: false
                        topMargin: 4
                    }
                    Flow {
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        spacing: 8
                        PButton { objectName: "updateNotesButton"; text: "Release Notes"; iconName: "document_bullet_list"; onClicked: Updates.showDetails() }
                        PButton { objectName: "updateDownloadButton"; text: updateCard.phase === "error" ? "Erneut versuchen" : "Herunterladen"; kind: "accent"; visible: Updates.canDownload; onClicked: Updates.download() }
                        PButton { objectName: "updateCancelButton"; text: "Abbrechen"; visible: Updates.canCancel; onClicked: Updates.cancel() }
                        PButton { objectName: "updateInstallButton"; text: "Jetzt installieren"; kind: "accent"; visible: Updates.canInstall; onClicked: Updates.installNow() }
                    }
                }
            }
        }
    }

    // Aus: Kanal Stable (Standard), an: Beta – beim ersten Einschalten mit Rückfrage
    PSettingsCard {
        id: betaCard
        objectName: "updateBetaCard"
        readonly property bool beta: Updates.beta
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "branch_compare"
        title: "Beta-Versionen erhalten"
        description: "Vorabversionen zum Testen – sie können Fehler enthalten. Ausgeschaltet erhalten Sie nur freigegebene Versionen (empfohlen)."
        PToggle {
            objectName: "updateBetaToggle"
            label: "Beta-Versionen erhalten"
            checked: betaCard.beta
            onToggled: {
                Updates.setBeta(checked)
                // Abgelehnte Rückfrage: wieder der gespeicherte Kanal
                checked = Qt.binding(function() { return betaCard.beta })
            }
        }
    }
    PText {
        objectName: "updateChannelHint"
        Layout.fillWidth: true
        Layout.topMargin: 6
        text: Updates.hint
        visible: text !== ""
        textStyle: "caption"
        tone: "secondary"
        wrap: true
    }

    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "clock"
        title: "Automatisch nach Updates suchen"
        description: "Höchstens einmal täglich im Hintergrund – der Start wartet nie darauf. Installiert wird nur, wenn Sie es bestätigen."
        PToggle {
            objectName: "updateAutomaticToggle"
            label: "Automatisch nach Updates suchen"
            checked: Updates.automatic
            onToggled: Updates.setAutomatic(checked)
        }
    }

    PSectionTitle { text: "Diagnose" }

    PCard {
        objectName: "diagnoseCard"
        Layout.fillWidth: true
        title: "Diagnose"
        iconName: "status"
        subtitle: "Prüft Einstellungen und Daten von PDF Tool – lokal und ohne etwas zu verändern."
        Flow {
            Layout.fillWidth: true
            spacing: 8
            PButton { objectName: "runChecks"; kind: "accent"; iconName: "checkmark_circle"; text: "Daten prüfen"; busy: Diagnose.busy && Diagnose.busyText.indexOf("geprüft") >= 0; busyText: "Wird geprüft …"; enabled: !Diagnose.busy; onClicked: Diagnose.runChecks() }
            PButton { objectName: "supportPackage"; iconName: "arrow_export"; text: "Support-Paket erstellen …"; tip: "ZIP mit Bericht und bereinigten Protokollen – ohne Kunden- oder Dokumentdaten, wird nicht versendet"; enabled: !Diagnose.busy; onClicked: Diagnose.createPackage() }
            PButton { kind: "subtle"; iconName: "document_bullet_list"; text: "Protokolle öffnen"; tip: "Datenordner mit pdf-tool.log, fehler.log, stapel.log und pdf-repair.log"; onClicked: Diagnose.openLogs() }
            PButton { kind: "subtle"; iconName: "delete"; text: "Temporäre Dateien aufräumen"; tip: "Entfernt nur eigene temporäre Dateien früherer Sitzungen"; onClicked: Diagnose.cleanupNow() }
        }
        PCollapse {
            Layout.fillWidth: true
            expanded: Diagnose.busy
            ColumnLayout {
                width: parent.width
                PText { text: Diagnose.busyText; Layout.topMargin: 10 }
                PProgressBar { Layout.fillWidth: true; indeterminate: true }
            }
        }
        RowLayout {
            objectName: "diagnoseVerdict"
            Layout.fillWidth: true
            Layout.topMargin: 12
            visible: Diagnose.verdict !== ""
            spacing: 8
            PIcon { name: Theme.toneIcon(Diagnose.verdictKind); color: Theme.toneIconColor(Diagnose.verdictKind); Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                PText { text: Diagnose.verdict; textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                PText { text: Diagnose.lastRun; textStyle: "caption"; tone: "secondary" }
            }
        }
        Repeater {
            model: Diagnose.results
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 8
                PIcon { name: Theme.toneIcon(modelData.status); color: Theme.toneIconColor(modelData.status); size: 14; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                PText { text: modelData.label; Layout.preferredWidth: 150; Layout.alignment: Qt.AlignTop }
                PText { text: modelData.detail; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
        }
        PInfoBar { Layout.fillWidth: true; notice: Notices.area("diagnose_info") }
        PText { text: "Systeminformationen"; textStyle: "bodyStrong"; Layout.topMargin: 16 }
        // Feste Zeilen (Diagnose.factModel) – beim ersten Öffnen kommen nur die Werte hinzu
        ColumnLayout {
            objectName: "diagnoseFacts"
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 4
            Repeater {
                model: Diagnose.factModel
                RowLayout {
                    required property string label
                    required property string value
                    Layout.fillWidth: true
                    spacing: 12
                    PText { text: label; textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                    PText { text: value; wrap: true; Layout.fillWidth: true }
                }
            }
        }
    }

    PSectionTitle { text: "Info" }

    PSettingsCard {
        objectName: "infoCard"
        Layout.fillWidth: true
        iconName: "info"
        title: App.appName
        description: "Version " + App.version + " · Entwickler und Inhaber: " + App.developer
        // Beta-Version: dasselbe Etikett wie in der Karte »Updates«
        PBadge { objectName: "infoBeta"; text: App.beta ? "Beta" : ""; tone: "accent"; anchors.verticalCenter: parent.verticalCenter }
        PButton { text: "Über"; onClicked: App.showAbout() }
    }
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "question_circle"
        title: "Kurzanleitung"
        description: "So arbeiten Sie mit den Werkzeugen von PDF Tool (F1)"
        PButton { text: "Öffnen"; onClicked: App.showHelp() }
    }
    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "megaphone"
        title: "Neuerungen"
        description: "Was ist neu in Version " + App.version
        PButton { text: "Anzeigen"; onClicked: App.showChangelog() }
    }
}
