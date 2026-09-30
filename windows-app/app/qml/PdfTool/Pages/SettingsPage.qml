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
