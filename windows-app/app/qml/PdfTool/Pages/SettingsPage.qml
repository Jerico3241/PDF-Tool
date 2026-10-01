import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Einstellungen: Design, Akzentfarbe, Mica, Animationen, Kundenakte und Info. Alles wirkt sofort.
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
        description: "Für Schaltflächen, Auswahl, Hinweise und die Navigation"
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

    PSettingsCard {
        Layout.fillWidth: true
        Layout.topMargin: 4
        iconName: "branch_compare"
        title: "Update-Kanal"
        description: {
            var list = Updates.channels
            var index = page.indexOfValue(list, Updates.channel)
            return index >= 0 ? list[index].text : ""
        }
        PComboBox {
            id: channelCombo
            objectName: "updateChannelCombo"
            preferredWidth: 180
            label: "Update-Kanal"
            model: Updates.channels
            textRole: "label"
            valueRole: "value"
            currentIndex: page.indexOfValue(Updates.channels, Updates.channel)
            onActivated: (index) => {
                Updates.setChannel(Updates.channels[index].value)
                // Abgelehnte Rückfrage: wieder der gespeicherte Kanal
                currentIndex = Qt.binding(function() { return page.indexOfValue(Updates.channels, Updates.channel) })
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

    PSectionTitle { text: "Info" }

    PSettingsCard {
        Layout.fillWidth: true
        iconName: "info"
        title: App.appName
        description: "Version " + App.version + " · Entwickler und Inhaber: " + App.developer
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
