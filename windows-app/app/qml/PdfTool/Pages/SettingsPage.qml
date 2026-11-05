import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Einstellungen in Bereichen (seit 4.0, oben wählbar): Allgemein (Design, Akzentfarbe, Mica, Animationen,
// Hintergrund), PDF Reader, KI-Assistent, Vertragsübersichten (Kundenakte), Updates, Daten & Diagnose
// (Sicherung, Diagnose) und Info. Sichtbar ist nur der gewählte Bereich. Alles wirkt sofort.
PPage {
    id: page
    objectName: "settingsPage"
    // Breites Fenster (seit 5.0 Beta 10, Entwurf 5): Bereiche links untereinander, rechts der gewählte mit seinem Namen
    // als Überschrift; schmal wie bisher oben nebeneinander
    readonly property bool sideNav: width >= 900
    Connections { target: Settings; function onSectionChanged() { page.enter() } }
    sideWidth: sideNav ? 260 : 0
    readonly property var sectionIcons: ({ general: "settings", personalize: "paint_brush", reader: "document_pdf", assistant: "sparkle",
                                           contracts: "document_table", updates: "arrow_sync", data: "save", info: "info" })
    function sectionLabel(key) {
        var list = Settings.sections
        for (var i = 0; i < list.length; ++i)
            if (list[i].key === key) return list[i].label
        return ""
    }
    title: I18n.tr(sideNav ? sectionLabel(Settings.section) : "Einstellungen", I18n.revision)
    subtitle: I18n.tr(sideNav && Settings.section === "personalize" ? "So sieht Novadesk aus – Änderungen wirken sofort." : "", I18n.revision)
    signal themeRequested(var apply)

    side: Column {
        objectName: "settingsNav"
        x: 10
        y: 18
        width: page.sideWidth - 20
        spacing: 4
        Repeater {
            model: Settings.sections
            T.AbstractButton {
                id: navItem
                required property var modelData
                readonly property bool selected: Settings.section === modelData.key
                objectName: "settingsNav_" + modelData.key
                width: parent.width
                height: 38
                hoverEnabled: true
                focusPolicy: Qt.TabFocus
                Accessible.role: Accessible.PageTab
                Accessible.name: I18n.tr(modelData.label, I18n.revision)
                Accessible.selected: selected
                onClicked: { Settings.setSection(modelData.key); page.scrollToTop() }
                background: Rectangle {
                    radius: Metrics.radiusControl + 2
                    color: navItem.selected ? Theme.navSelected : (navItem.hovered ? Theme.subtleHover : "transparent")
                    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
                    PFocusRing { visible: navItem.visualFocus }
                    Rectangle {
                        visible: navItem.selected
                        x: 0
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: 18
                        radius: 1.5
                        color: Theme.accent
                        Repeater {
                            model: Theme.glow > 0 ? 3 : 0
                            Rectangle {
                                required property int index
                                x: -(index + 1); y: -(index + 1)
                                width: parent.width + 2 * (index + 1); height: parent.height + 2 * (index + 1)
                                radius: width / 2
                                color: "transparent"
                                border.width: 1
                                border.color: Theme.accent
                                opacity: 0.3 * Theme.glow * (1 - index / 3)
                            }
                        }
                    }
                }
                contentItem: Item {}
                Row {
                    x: 14
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 12
                    PIcon { anchors.verticalCenter: parent.verticalCenter; name: page.sectionIcons[navItem.modelData.key] || "settings"; size: 18; color: Theme.textPrimary }
                    PText { anchors.verticalCenter: parent.verticalCenter; text: I18n.tr(navItem.modelData.label, I18n.revision) }
                }
            }
        }
    }

    function indexOfValue(list, value) {
        for (var i = 0; i < list.length; ++i)
            if (list[i].value === value) return i
        return -1
    }

    // Bereiche: nur der gewählte ist sichtbar
    PSelectorBar {
        objectName: "settingsSections"
        visible: !page.sideNav
        Layout.fillWidth: true
        Layout.maximumWidth: implicitWidth
        Layout.bottomMargin: 8
        current: Settings.section
        items: Settings.sections
        onSelected: (key) => { Settings.setSection(key); page.scrollToTop() }
    }

    ColumnLayout {
        objectName: "settingsSection_general"
        Layout.fillWidth: true
        visible: Settings.section === "general"
        spacing: 0
        PSectionTitle { text: I18n.tr("Darstellung", I18n.revision); Layout.topMargin: 0 }

        PSettingsCard {
            objectName: "languageCard"
            Layout.fillWidth: true
            iconName: "local_language"
            title: I18n.tr("Sprache", I18n.revision)
            description: I18n.tr("Deutsch oder Englisch – ohne Neustart. Standard: wie die Sprache von Windows", I18n.revision)
            PComboBox {
                objectName: "languageCombo"
                preferredWidth: 180
                label: I18n.tr("Sprache", I18n.revision)
                model: I18n.choices()
                textRole: "label"
                valueRole: "value"
                currentIndex: page.indexOfValue(model, I18n.choice)
                onActivated: (index) => I18n.setChoice(model[index].value)
            }
        }

        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "dark_theme"
            title: I18n.tr("App-Design", I18n.revision)
            description: I18n.tr("Hell, Dunkel oder automatisch wie der Windows-App-Modus", I18n.revision)
            PComboBox {
                id: themeCombo
                objectName: "themeCombo"
                preferredWidth: 180
                label: I18n.tr("App-Design", I18n.revision)
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
            title: I18n.tr("Akzentfarbe", I18n.revision)
            description: I18n.tr("Für Schaltflächen, Auswahl, Hinweise und die Tabs", I18n.revision)
            expandable: true
            expanded: true
            PText {
                text: I18n.tr(ThemeBackend.accentName, I18n.revision)
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
                        tip: I18n.tr(modelData.name, I18n.revision)
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
            title: I18n.tr("Mica-Material", I18n.revision)
            description: I18n.tr(ThemeBackend.micaDescription, I18n.revision)
            PToggle {
                objectName: "micaToggle"
                label: I18n.tr("Mica-Material", I18n.revision)
                enabled: ThemeBackend.micaAvailable
                checked: ThemeBackend.micaAvailable && ThemeBackend.micaEnabled
                onToggled: Settings.setMica(checked)
            }
        }

        PSectionTitle { text: I18n.tr("Verhalten", I18n.revision) }

        PSettingsCard {
            Layout.fillWidth: true
            iconName: "play"
            title: I18n.tr("Animationen", I18n.revision)
            description: I18n.tr((function() {
                var profiles = Settings.profiles
                var index = page.indexOfValue(profiles, ThemeBackend.profile)
                var text = index >= 0 ? profiles[index].text : ""
                return ThemeBackend.profileNote !== "" ? text + " " + ThemeBackend.profileNote : text
            })(), I18n.revision)
            PComboBox {
                objectName: "profileCombo"
                preferredWidth: 180
                label: I18n.tr("Animationen", I18n.revision)
                model: Settings.profiles
                textRole: "label"
                valueRole: "value"
                currentIndex: page.indexOfValue(Settings.profiles, ThemeBackend.profile)
                onActivated: (index) => Settings.setProfile(Settings.profiles[index].value)
            }
        }

        // Im Hintergrund bereithalten (Standard: an) – Start mit Windows ohne Fenster, Schließen-Kreuz versteckt nur
        PSettingsCard {
            objectName: "backgroundCard"
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "desktop"
            title: I18n.tr(Settings.texts.backgroundTitle, I18n.revision)
            description: I18n.tr(Settings.texts.backgroundText, I18n.revision)
            expandable: true
            PToggle {
                objectName: "backgroundToggle"
                label: I18n.tr(Settings.texts.backgroundTitle, I18n.revision)
                checked: Settings.background
                onToggled: Settings.setBackground(checked)
            }
            extra: RowLayout {
                width: parent ? parent.width - 68 : 300
                spacing: 8
                PIcon { name: "info"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: I18n.tr(Settings.texts.backgroundNote, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
        }
    }

    // Personalisieren (seit 5.0 Beta 10, Entwurf 5): Design, Neon, Startseite, Ecken, Dichte, Menüband, Animationen
    ColumnLayout {
        objectName: "settingsSection_personalize"
        Layout.fillWidth: true
        visible: Settings.section === "personalize"
        spacing: 6

        PSettingsCard {
            Layout.fillWidth: true
            iconName: "dark_theme"
            title: I18n.tr("App-Design", I18n.revision)
            description: I18n.tr(ThemeBackend.neon ? "Im Neon-Modus immer dunkel" : "Hell, Dunkel oder wie Windows", I18n.revision)
            PSegmented {
                objectName: "personalizeTheme"
                label: I18n.tr("App-Design", I18n.revision)
                enabled: !ThemeBackend.neon
                opacity: enabled ? 1 : 0.5
                model: [{ value: "light", label: "Hell" }, { value: "dark", label: "Dunkel" }, { value: "system", label: "Wie Windows" }]
                current: ThemeBackend.neon ? "dark" : ThemeBackend.mode
                onActivated: (value) => page.themeRequested(function() { Settings.setTheme(value) })
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "sparkle"
            title: I18n.tr("Neon-Modus", I18n.revision)
            description: I18n.tr("Leuchtende Akzentfarbe mit sanftem Glühen an Reitern, Auswahl, Zellrahmen und Schreibmarke", I18n.revision)
            PToggle {
                objectName: "neonToggle"
                label: I18n.tr("Neon-Modus", I18n.revision)
                checked: ThemeBackend.neon
                onToggled: { var on = checked; page.themeRequested(function() { Settings.setNeon(on) }) }
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "color"
            title: I18n.tr("Neon-Farbe", I18n.revision)
            description: I18n.tr("Gilt für die ganze App – Dokumente behalten ihre eigenen Farben", I18n.revision)
            Row {
                objectName: "neonColors"
                spacing: 10
                Repeater {
                    model: Settings.choices.neonColors
                    T.AbstractButton {
                        id: neonSwatch
                        required property var modelData
                        readonly property bool selected: String(ThemeBackend.neonColor).toUpperCase() === String(modelData.value).toUpperCase()
                        objectName: "neonColor_" + index
                        required property int index
                        width: 30
                        height: 30
                        hoverEnabled: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: I18n.tr(modelData.name, I18n.revision)
                        Accessible.checked: selected
                        onClicked: { var value = modelData.value; page.themeRequested(function() { Settings.setNeonColor(value); if (!ThemeBackend.neon) Settings.setNeon(true) }) }
                        background: Item {
                            Rectangle {  // Schein
                                anchors.centerIn: parent
                                width: 40; height: 40; radius: 20
                                color: neonSwatch.modelData.value
                                opacity: neonSwatch.hovered || neonSwatch.selected ? 0.35 : 0.2
                                Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
                            }
                            Rectangle { anchors.fill: parent; radius: 15; color: neonSwatch.modelData.value; scale: neonSwatch.pressed ? 0.92 : 1; Behavior on scale { enabled: Motion.moves; NumberAnimation { duration: Motion.fast } } }
                            Rectangle {  // gewählt: Ring mit Abstand
                                visible: neonSwatch.selected
                                anchors.centerIn: parent
                                width: 38; height: 38; radius: 19
                                color: "transparent"
                                border.width: 2
                                border.color: Theme.textPrimary
                            }
                            PFocusRing { visible: neonSwatch.visualFocus }
                        }
                        PToolTip { text: I18n.tr(neonSwatch.modelData.name, I18n.revision); visible: neonSwatch.hovered; y: neonSwatch.height + 8 }
                    }
                }
                // Eigene Farbe
                T.AbstractButton {
                    id: customNeon
                    objectName: "neonColorCustom"
                    readonly property bool selected: {
                        var list = Settings.choices.neonColors
                        for (var i = 0; i < list.length; ++i)
                            if (String(list[i].value).toUpperCase() === String(ThemeBackend.neonColor).toUpperCase()) return false
                        return true
                    }
                    width: 30
                    height: 30
                    hoverEnabled: true
                    Accessible.role: Accessible.Button
                    Accessible.name: I18n.tr("Eigene Farbe", I18n.revision)
                    onClicked: customPopup.open()
                    background: Rectangle {
                        radius: 15
                        color: customNeon.selected ? ThemeBackend.neonColor : (customNeon.hovered ? Theme.subtleHover : "transparent")
                        border.width: customNeon.selected ? 2 : 1
                        border.color: customNeon.selected ? Theme.textPrimary : Theme.textTertiary
                        PFocusRing { visible: customNeon.visualFocus }
                    }
                    contentItem: Item { PIcon { anchors.centerIn: parent; name: "add"; size: 14; color: customNeon.selected ? "#06121A" : Theme.textSecondary } }
                    PToolTip { text: I18n.tr("Eigene Farbe", I18n.revision); visible: customNeon.hovered && !customPopup.opened; y: customNeon.height + 8 }
                    T.Popup {
                        id: customPopup
                        objectName: "neonCustomPopup"
                        y: customNeon.height + 8
                        x: customNeon.width - width
                        padding: 12
                        focus: true
                        background: Rectangle { color: Theme.flyout; border.color: Theme.flyoutStroke; radius: Metrics.radiusOverlay; PShadow { radius: Metrics.radiusOverlay } }
                        contentItem: ColumnLayout {
                            spacing: 8
                            PText { text: I18n.tr("Eigene Neon-Farbe", I18n.revision); textStyle: "bodyStrong" }
                            Grid {
                                columns: 8
                                spacing: 6
                                Repeater {
                                    model: ["#00FFC6", "#00B3FF", "#4D7CFF", "#7C4DFF", "#E040FB", "#FF4081", "#FF6E40", "#FFD740",
                                            "#C6FF00", "#76FF03", "#18FFFF", "#40C4FF", "#B388FF", "#FF80AB", "#FFAB40", "#EEFF41"]
                                    T.AbstractButton {
                                        required property string modelData
                                        width: 22; height: 22
                                        onClicked: { var value = modelData; customPopup.close(); page.themeRequested(function() { Settings.setNeonColor(value); if (!ThemeBackend.neon) Settings.setNeon(true) }) }
                                        background: Rectangle { radius: 11; color: parent.modelData; border.width: parent.hovered ? 2 : 0; border.color: Theme.textPrimary }
                                    }
                                }
                            }
                            RowLayout {
                                spacing: 6
                                PTextField {
                                    id: hexField
                                    objectName: "neonHexField"
                                    preferredWidth: 120
                                    placeholderText: I18n.tr("#RRGGBB", I18n.revision)
                                    text: ThemeBackend.neonColor
                                    onSubmitted: hexApply.clicked()
                                }
                                PButton {
                                    id: hexApply
                                    kind: "accent"
                                    text: I18n.tr("Übernehmen", I18n.revision)
                                    enabled: /^#?[0-9A-Fa-f]{6}$/.test(hexField.text.trim())
                                    onClicked: {
                                        var value = hexField.text.trim()
                                        if (value.charAt(0) !== "#") value = "#" + value
                                        customPopup.close()
                                        page.themeRequested(function() { Settings.setNeonColor(value); if (!ThemeBackend.neon) Settings.setNeon(true) })
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "weather_moon"
            title: I18n.tr("Leuchtstärke", I18n.revision)
            description: I18n.tr("Wie stark Neon glüht", I18n.revision)
            PSegmented {
                objectName: "personalizeGlow"
                label: I18n.tr("Leuchtstärke", I18n.revision)
                model: Settings.choices.glows
                current: ThemeBackend.glow
                onActivated: (value) => Settings.setGlow(value)
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "home"
            title: I18n.tr("Startseite", I18n.revision)
            description: I18n.tr("Hintergrund der Startseite", I18n.revision)
            Row {
                objectName: "personalizeStart"
                spacing: 10
                Repeater {
                    model: Settings.choices.startBackgrounds
                    T.AbstractButton {
                        id: bgChoice
                        required property var modelData
                        readonly property bool selected: ThemeBackend.startBackground === modelData.value
                        objectName: "startBackground_" + modelData.value
                        width: 96
                        height: 80
                        hoverEnabled: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: I18n.tr(modelData.label, I18n.revision)
                        Accessible.checked: selected
                        onClicked: Settings.setStartBackground(modelData.value)
                        background: Item {}
                        contentItem: Item {}
                        Rectangle {
                            id: preview
                            width: 96
                            height: 58
                            radius: Metrics.radiusControl + 2
                            clip: true
                            color: Theme.surface
                            border.width: bgChoice.selected ? 2 : 1
                            border.color: bgChoice.selected ? Theme.accent : Theme.border
                            gradient: bgChoice.modelData.value === "gradient" ? previewGradient : null
                            Gradient {
                                id: previewGradient
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0; color: Theme.dark ? "#1B2A4A" : "#DCE8FB" }
                                GradientStop { position: 1; color: Theme.dark ? "#3A1B4A" : "#EFE3F8" }
                            }
                            // Raster
                            Repeater {
                                model: bgChoice.modelData.value === "grid" ? 8 : 0
                                Rectangle { required property int index; x: index * 12 + 6; width: 1; height: preview.height; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.25) }
                            }
                            Repeater {
                                model: bgChoice.modelData.value === "grid" ? 5 : 0
                                Rectangle { required property int index; y: index * 12 + 6; height: 1; width: preview.width; color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.25) }
                            }
                            Repeater {
                                model: bgChoice.selected && Theme.glow > 0 ? 3 : 0
                                Rectangle {
                                    required property int index
                                    x: -(index + 1); y: -(index + 1)
                                    width: preview.width + 2 * (index + 1); height: preview.height + 2 * (index + 1)
                                    radius: preview.radius + index + 1
                                    color: "transparent"; border.width: 1; border.color: Theme.accent
                                    opacity: 0.25 * Theme.glow * (1 - index / 3)
                                }
                            }
                        }
                        PText {
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: preview.height + 4
                            text: I18n.tr(bgChoice.modelData.label, I18n.revision)
                            textStyle: "caption"
                            tone: "secondary"
                        }
                    }
                }
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "shapes"
            title: I18n.tr("Ecken", I18n.revision)
            description: I18n.tr("Rund wie Windows 11 oder eckig", I18n.revision)
            PSegmented {
                objectName: "personalizeCorners"
                label: I18n.tr("Ecken", I18n.revision)
                model: Settings.choices.corners
                current: ThemeBackend.corners
                onActivated: (value) => Settings.setCorners(value)
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "grid"
            title: I18n.tr("Dichte", I18n.revision)
            description: I18n.tr("Abstände in Leisten und Listen", I18n.revision)
            PSegmented {
                objectName: "personalizeDensity"
                label: I18n.tr("Dichte", I18n.revision)
                model: Settings.choices.densities
                current: ThemeBackend.density
                onActivated: (value) => Settings.setDensity(value)
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "panel_left"
            title: I18n.tr("Menüband", I18n.revision)
            description: I18n.tr("Befehle mit Beschriftung oder nur als Symbole", I18n.revision)
            PSegmented {
                objectName: "personalizeRibbon"
                label: I18n.tr("Menüband", I18n.revision)
                model: Settings.choices.ribbon
                current: ThemeBackend.ribbonLabels ? "text" : "icons"
                onActivated: (value) => Settings.setRibbonLabels(value === "text")
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            iconName: "play"
            title: I18n.tr("Animationen", I18n.revision)
            description: I18n.tr(ThemeBackend.profileNote !== "" ? "Gleitende Reiter, Seitenleisten und Zellrahmen. " + ThemeBackend.profileNote : "Gleitende Reiter, Seitenleisten und Zellrahmen", I18n.revision)
            PSegmented {
                objectName: "personalizeMotion"
                label: I18n.tr("Animationen", I18n.revision)
                model: Settings.profiles
                current: ThemeBackend.profile
                onActivated: (value) => Settings.setProfile(value)
            }
        }
    }

    ColumnLayout {
        objectName: "settingsSection_reader"
        Layout.fillWidth: true
        visible: Settings.section === "reader"
        spacing: 0
        // Ansicht neu geöffneter PDFs – »Zuletzt verwendet« (Standard) wie bisher
        PSectionTitle { text: I18n.tr("PDF Reader", I18n.revision) }

        PSettingsCard {
            objectName: "readerZoomCard"
            Layout.fillWidth: true
            iconName: "zoom_in"
            title: I18n.tr("Standardzoom beim Öffnen", I18n.revision)
            description: I18n.tr("Für neu geöffnete PDFs. »Zuletzt verwendet« übernimmt die zuletzt eingestellte Ansicht.", I18n.revision)
            PComboBox {
                objectName: "readerZoomCombo"
                preferredWidth: 180
                label: I18n.tr("Standardzoom beim Öffnen", I18n.revision)
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
            title: I18n.tr("Seitenleiste beim Öffnen", I18n.revision)
            description: I18n.tr("Linke Seitenleiste, wenn ein PDF geöffnet wird. »Zuletzt verwendet« zeigt die zuletzt gewählte.", I18n.revision)
            PComboBox {
                objectName: "readerPanelCombo"
                preferredWidth: 180
                label: I18n.tr("Seitenleiste beim Öffnen", I18n.revision)
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
            title: I18n.tr("Nachtmodus", I18n.revision)
            description: I18n.tr("Seiten dunkelgrau mit heller Schrift – angenehmer bei wenig Licht. Nur die Anzeige: Datei, Drucken und Export bleiben unverändert.", I18n.revision)
            PToggle {
                objectName: "readerNightToggle"
                label: I18n.tr("Nachtmodus", I18n.revision)
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
            title: I18n.tr("PDFs der letzten Sitzung beim Start wieder öffnen", I18n.revision)
            description: I18n.tr("Beim Beenden merkt sich Novadesk die geöffneten PDFs (nur Pfade, lokal auf diesem PC) und öffnet sie beim nächsten Start wieder – ungespeicherte Änderungen nicht.", I18n.revision)
            PToggle {
                objectName: "readerSessionToggle"
                label: I18n.tr("PDFs der letzten Sitzung beim Start wieder öffnen", I18n.revision)
                checked: Settings.readerRestoreSession
                onToggled: Settings.setReaderRestoreSession(checked)
            }
        }
    }

    ColumnLayout {
        objectName: "settingsSection_assistant"
        Layout.fillWidth: true
        visible: Settings.section === "assistant"
        spacing: 0
        PSectionTitle { text: I18n.tr("KI-Assistent", I18n.revision) }

        // Optional und standardmäßig aus: Erst »Ein« und »Herunterladen« laden ein Sprachmodell (1,3 oder 2,7 GB), das sich
        // jederzeit wieder entfernen lässt. Dokumente, Fragen und Antworten bleiben auf diesem PC.
        PCard {
            id: assistantCard
            objectName: "assistantCard"
            Layout.fillWidth: true
            title: I18n.tr("KI-Assistent (optional)", I18n.revision)
            iconName: "sparkle"
            subtitle: I18n.tr("Beantwortet Fragen zum geöffneten PDF und fasst Dokumente zusammen – mit Seitenangaben, vollständig auf diesem PC. Braucht ein Sprachmodell, das nur auf Wunsch geladen wird.", I18n.revision)
            readonly property string phase: Assistant.state
            readonly property bool loading: phase === "download" || phase === "verify"
            // Welche Schaltflächen passen (eigene Werte, nicht ``visible`` der Schaltflächen: das hinge an der Zeile darüber)
            readonly property bool canSetup: Assistant.enabled && phase === "setup" && Assistant.partial === ""
            readonly property bool canResume: Assistant.enabled && phase === "setup" && Assistant.partial !== ""
            readonly property bool canPause: phase === "download"
            readonly property bool canChange: phase === "ready"
            readonly property bool canRemove: !loading && (Assistant.modelKey !== "" || Assistant.partial !== "")
            headerRight: PToggle {
                objectName: "assistantToggle"
                label: I18n.tr("KI-Assistent", I18n.revision)
                checked: Assistant.enabled
                enabled: Assistant.available || Assistant.enabled
                onToggled: {
                    Assistant.setEnabled(checked)
                    // eingeschaltet, aber noch kein Modell: gleich auswählen lassen
                    if (checked && Assistant.state === "setup" && Assistant.partial === "") Assistant.setup()
                }
            }
            PText {
                objectName: "assistantStatus"
                Layout.fillWidth: true
                text: I18n.tr(Assistant.available || Assistant.enabled ? Assistant.statusText : "In dieser Installation nicht enthalten.", I18n.revision)
                tone: Assistant.state === "ready" ? "" : "secondary"
                wrap: true
            }
            PCollapse {
                Layout.fillWidth: true
                expanded: assistantCard.loading
                ColumnLayout {
                    width: parent.width
                    spacing: 6
                    PProgressBar {
                        objectName: "assistantProgress"
                        Layout.fillWidth: true
                        Layout.topMargin: 12
                        value: Assistant.progress
                        indeterminate: assistantCard.phase === "verify"
                    }
                    PText { objectName: "assistantProgressText"; Layout.fillWidth: true; text: I18n.tr(Assistant.progressText, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                visible: assistantCard.canSetup || assistantCard.canResume || assistantCard.canPause || assistantCard.canChange || assistantCard.canRemove
                PButton {
                    objectName: "assistantSetup"
                    visible: assistantCard.canSetup
                    kind: "accent"
                    iconName: "arrow_download"
                    text: I18n.tr("Einrichten …", I18n.revision)
                    tip: I18n.tr("Sprachmodell wählen und laden", I18n.revision)
                    onClicked: Assistant.setup()
                }
                PButton {
                    objectName: "assistantResume"
                    visible: assistantCard.canResume
                    kind: "accent"
                    iconName: "arrow_download"
                    text: I18n.tr("Download fortsetzen", I18n.revision)
                    onClicked: Assistant.download(Assistant.partial)
                }
                PButton {
                    objectName: "assistantCancel"
                    visible: assistantCard.canPause
                    text: I18n.tr("Anhalten", I18n.revision)
                    tip: I18n.tr("Download anhalten – er lässt sich später fortsetzen", I18n.revision)
                    onClicked: Assistant.cancelDownload()
                }
                PButton {
                    objectName: "assistantChange"
                    visible: assistantCard.canChange
                    text: I18n.tr("Anderes Modell …", I18n.revision)
                    tip: I18n.tr("Genaueres oder kleineres Sprachmodell wählen – das bisherige wird danach gelöscht", I18n.revision)
                    onClicked: Assistant.setup()
                }
                PButton {
                    objectName: "assistantRemove"
                    visible: assistantCard.canRemove
                    kind: "subtle"
                    iconName: "delete"
                    text: I18n.tr("Modell entfernen …", I18n.revision)
                    tip: I18n.tr("Sprachmodell von diesem PC löschen und den Speicherplatz freigeben", I18n.revision)
                    onClicked: Assistant.removeModel()
                }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("assistant") }
            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PIcon { Layout.alignment: Qt.AlignTop; name: "shield_checkmark"; size: 16; color: Theme.textSecondary }
                PText {
                    Layout.fillWidth: true
                    text: I18n.tr("Dokumente, Fragen und Antworten verlassen diesen PC nicht und werden nicht gespeichert. Nur das Sprachmodell wird einmal über HTTPS von Hugging Face geladen und vor der Nutzung geprüft.", I18n.revision)
                    textStyle: "caption"
                    tone: "secondary"
                    wrap: true
                }
            }
        }
    }

    ColumnLayout {
        objectName: "settingsSection_contracts"
        Layout.fillWidth: true
        visible: Settings.section === "contracts"
        spacing: 0
        PSectionTitle { text: I18n.tr("Vertragsübersichten", I18n.revision) }

        PSettingsCard {
            Layout.fillWidth: true
            iconName: "people"
            title: I18n.tr(Settings.texts.customerTitle, I18n.revision)
            description: I18n.tr(Settings.texts.customerText, I18n.revision)
            expandable: true
            expanded: true
            PToggle {
                objectName: "customerRecordsToggle"
                label: I18n.tr(Settings.texts.customerTitle, I18n.revision)
                checked: Settings.customerRecords
                onToggled: Settings.setCustomerRecords(checked)
            }
            extra: RowLayout {
                width: parent ? parent.width - 68 : 300
                spacing: 8
                PIcon { name: "shield"; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 1 }
                PText { text: I18n.tr(Settings.texts.customerNote, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; Layout.fillWidth: true }
            }
        }
        PText {
            Layout.fillWidth: true
            Layout.topMargin: 8
            text: I18n.tr("Einstellungen der einzelnen Werkzeuge stehen im jeweiligen Werkzeug – z. B. Vorlagen und Verlauf unter »Vertragsübersichten · Darstellung«.", I18n.revision)
            textStyle: "caption"
            tone: "secondary"
            wrap: true
        }
    }

    ColumnLayout {
        objectName: "dataBackup"
        Layout.fillWidth: true
        visible: Settings.section === "data"
        spacing: 0
        PSectionTitle { text: I18n.tr("Sicherung & Wiederherstellung", I18n.revision) }

        // Sicherung: Status, Jetzt sichern, Wiederherstellen, gesicherte Stände
        PCard {
            objectName: "backupCard"
            Layout.fillWidth: true
            title: I18n.tr("Sicherung", I18n.revision)
            iconName: "shield_checkmark"
            subtitle: I18n.tr("Einstellungen, Kundenakten mit Vertragsständen, Vorlagen und Regelwerke in einer Datei (.pdtbackup) – lokal auf diesem PC, keine Cloud.", I18n.revision)
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
                    PText { objectName: "backupBusy"; text: I18n.tr(Backup.busyText, I18n.revision); Layout.topMargin: 10 }
                    PProgressBar { Layout.fillWidth: true; value: Backup.progress; indeterminate: Backup.progress <= 0 }
                }
            }
            Flow {
                Layout.fillWidth: true
                Layout.topMargin: 12
                spacing: 8
                PButton { objectName: "backupNow"; kind: "accent"; iconName: "save"; text: I18n.tr("Jetzt sichern …", I18n.revision); tip: I18n.tr("Sicherung in einen Ordner Ihrer Wahl (z. B. USB-Stick)", I18n.revision); enabled: !Backup.busy; onClicked: Backup.backupNow() }
                PButton { objectName: "restoreBackup"; iconName: "arrow_undo"; text: I18n.tr("Wiederherstellen …", I18n.revision); tip: I18n.tr("Sicherung wählen, prüfen und Bereiche wiederherstellen", I18n.revision); enabled: !Backup.busy; onClicked: Backup.restoreFrom() }
                PButton { kind: "subtle"; iconName: "folder_open"; text: I18n.tr("Ordner öffnen", I18n.revision); tip: I18n.tr("Ordner der automatischen Sicherungen öffnen", I18n.revision); onClicked: Backup.openFolder() }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("sicherung_info") }
            PInfoBar {
                objectName: "backupPending"
                Layout.fillWidth: true
                notice: null
                shown: Backup.pending !== ""
                severity: "info"
                message: I18n.tr(Backup.pending, I18n.revision)
                closable: false
                actions: ["Verwerfen"]
                onActionTriggered: (index) => Backup.discardPending()
            }
            PText {
                Layout.fillWidth: true
                Layout.topMargin: 14
                visible: Backup.recentModel.count > 0
                text: I18n.tr("Gesicherte Stände im Ordner der automatischen Sicherungen", I18n.revision)
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
                        PText { text: I18n.tr(date, I18n.revision); Layout.preferredWidth: 140 }
                        PText { text: I18n.tr(kind + (version !== "" ? " · " + version : "") + " · " + size, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight; Layout.fillWidth: true }
                        PButton { kind: "subtle"; text: I18n.tr("Wiederherstellen …", I18n.revision); enabled: !Backup.busy; tip: I18n.tr(name, I18n.revision); onClicked: Backup.restore(path) }
                    }
                }
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "clock"
            title: I18n.tr("Automatisch sichern", I18n.revision)
            description: I18n.tr("Einmal am Tag, wenn sich etwas geändert hat, und vor jedem Update. Die letzten 10 automatischen Sicherungen bleiben erhalten – manuelle Sicherungen werden nie automatisch gelöscht.", I18n.revision)
            PToggle {
                objectName: "backupAutomaticToggle"
                label: I18n.tr("Automatisch sichern", I18n.revision)
                checked: Backup.automatic
                onToggled: Backup.setAutomatic(checked)
            }
        }
        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "folder"
            title: I18n.tr("Ordner der automatischen Sicherungen", I18n.revision)
            description: I18n.tr(Backup.folderText, I18n.revision)
            Row {
                spacing: 4
                PButton { text: I18n.tr("Ändern …", I18n.revision); onClicked: Backup.pickAutoFolder() }
                PIconButton { iconName: "arrow_reset"; tip: I18n.tr("Standardordner verwenden", I18n.revision); onClicked: Backup.resetAutoFolder() }
            }
        }
    }

    ColumnLayout {
        objectName: "settingsSection_updates"
        Layout.fillWidth: true
        visible: Settings.section === "updates"
        spacing: 0
        PSectionTitle { text: I18n.tr("Updates", I18n.revision) }

        // Version, Zustand des Updaters und ein Knopf je Zustand (seit 4.0 Beta 7): »Nach Updates suchen«, nach einem
        // Fund »Jetzt installieren« (lädt, prüft und installiert), während des Downloads »Abbrechen«. Die Release Notes
        // eines gefundenen Updates stehen direkt in der Karte.
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
                    PIcon {
                        name: updateCard.offerShown ? "arrow_download" : "arrow_sync"
                        color: updateCard.offerShown ? Theme.accentText : Theme.textPrimary
                        size: Metrics.iconSizeMedium
                        Layout.alignment: Qt.AlignTop
                        Layout.topMargin: 2
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        RowLayout {
                            spacing: 8
                            PText { objectName: "updateCurrentVersion"; text: I18n.tr("Novadesk " + Updates.currentVersion, I18n.revision) }
                            PBadge { objectName: "updateCurrentBeta"; text: I18n.tr(Updates.currentBeta ? "Beta" : "", I18n.revision); tone: "accent" }
                        }
                        PText {
                            objectName: "updateLastCheck"
                            text: I18n.tr("Letzte Prüfung: " + Updates.lastCheck, I18n.revision)
                            textStyle: "caption"
                            tone: "secondary"
                            Layout.fillWidth: true
                        }
                    }
                    PButton {
                        objectName: "updateActionButton"
                        text: I18n.tr(Updates.action === "install" ? "Jetzt installieren" : (Updates.action === "cancel" ? "Abbrechen" : "Nach Updates suchen"), I18n.revision)
                        iconName: Updates.action === "install" ? "arrow_download" : (Updates.action === "cancel" ? "dismiss" : "arrow_sync")
                        kind: Updates.action === "install" ? "accent" : "standard"
                        enabled: Updates.action === "cancel" ? Updates.canCancel : (Updates.action === "install" ? (Updates.canInstall || Updates.canDownload) : Updates.canCheck)
                        busy: updateCard.phase === "checking" || updateCard.phase === "installing"
                        busyText: I18n.tr(updateCard.phase === "installing" ? "Wird installiert …" : "Suche …", I18n.revision)
                        onClicked: Updates.act()
                    }
                }

                // Zustand: »Novadesk ist aktuell.«, gefundenes Update, Download mit Fortschritt, Fehler …
                RowLayout {
                    objectName: "updateStatus"
                    Layout.fillWidth: true
                    Layout.leftMargin: 36
                    spacing: 8
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
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            PText { objectName: "updateStatusTitle"; text: I18n.tr(Updates.statusTitle, I18n.revision); textStyle: updateCard.offerShown ? "bodyStrong" : "body"; wrap: true; Layout.fillWidth: true }
                            PBadge { objectName: "updateOfferBeta"; text: I18n.tr(updateCard.offerShown && Updates.offerBeta ? "Beta-Update" : "", I18n.revision); tone: "accent" }
                        }
                        PText { objectName: "updateStatusText"; text: I18n.tr(updateCard.phase === "downloading" ? Updates.progressText : Updates.statusText, I18n.revision); textStyle: "caption"; tone: "secondary"; wrap: true; visible: text !== ""; Layout.fillWidth: true }
                        PProgressBar {
                            objectName: "updateProgress"
                            Layout.fillWidth: true
                            Layout.maximumWidth: 420
                            Layout.topMargin: 6
                            visible: updateCard.phase === "downloading" || updateCard.phase === "verifying"
                            indeterminate: updateCard.phase === "verifying"
                            value: Updates.progress
                        }
                        PInfoBar {
                            Layout.fillWidth: true
                            shown: Updates.workHint !== ""
                            severity: "warning"
                            message: I18n.tr(Updates.workHint, I18n.revision)
                            closable: false
                            topMargin: 6
                        }
                    }
                }

                // Release Notes des gefundenen Updates
                ColumnLayout {
                    objectName: "updateOffer"
                    Layout.fillWidth: true
                    Layout.leftMargin: 36
                    visible: updateCard.offerShown
                    spacing: 6
                    Rectangle { Layout.fillWidth: true; height: 1; color: Theme.divider }
                    PText { objectName: "updateOfferTitle"; text: I18n.tr("Was ist neu in " + Updates.offerTitle, I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 4 }
                    PText {
                        text: I18n.tr("Für diese Version liegen keine Release Notes vor.", I18n.revision)
                        tone: "secondary"
                        visible: Updates.notes.length === 0
                    }
                    PReleaseNotes { objectName: "updateCardNotes"; Layout.fillWidth: true; blocks: Updates.notes }
                    PButton { objectName: "updateNotesButton"; text: I18n.tr("Alle Details", I18n.revision); kind: "subtle"; iconName: "document_bullet_list"; onClicked: Updates.showDetails() }
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
            title: I18n.tr("Beta-Versionen erhalten", I18n.revision)
            description: I18n.tr("Vorabversionen zum Testen – sie können Fehler enthalten. Ausgeschaltet erhalten Sie nur freigegebene Versionen (empfohlen).", I18n.revision)
            PToggle {
                objectName: "updateBetaToggle"
                label: I18n.tr("Beta-Versionen erhalten", I18n.revision)
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
            text: I18n.tr(Updates.hint, I18n.revision)
            visible: text !== ""
            textStyle: "caption"
            tone: "secondary"
            wrap: true
        }

        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "clock"
            title: I18n.tr("Automatisch nach Updates suchen", I18n.revision)
            description: I18n.tr("Bei jedem Start im Hintergrund – der Start wartet nie darauf.", I18n.revision)
            PToggle {
                objectName: "updateAutomaticToggle"
                label: I18n.tr("Automatisch nach Updates suchen", I18n.revision)
                checked: Updates.automatic
                onToggled: Updates.setAutomatic(checked)
            }
        }

        PSettingsCard {
            objectName: "updateAutoInstallCard"
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "arrow_download"
            enabled: Updates.automatic
            title: I18n.tr("Updates automatisch installieren", I18n.revision)
            description: I18n.tr("Ein gefundenes Update wird geladen und installiert, danach startet Novadesk neu und öffnet die PDFs wieder. Mit ungespeicherten Änderungen wartet es. Aus: nur »Jetzt installieren«.", I18n.revision)
            PToggle {
                objectName: "updateAutoInstallToggle"
                label: I18n.tr("Updates automatisch installieren", I18n.revision)
                checked: Updates.autoInstall
                onToggled: Updates.setAutoInstall(checked)
            }
        }
    }

    ColumnLayout {
        objectName: "dataDiagnose"
        Layout.fillWidth: true
        visible: Settings.section === "data"
        spacing: 0
        PSectionTitle { text: I18n.tr("Diagnose", I18n.revision) }

        PCard {
            objectName: "diagnoseCard"
            Layout.fillWidth: true
            title: I18n.tr("Diagnose", I18n.revision)
            iconName: "status"
            subtitle: I18n.tr("Prüft Einstellungen und Daten von Novadesk – lokal und ohne etwas zu verändern.", I18n.revision)
            Flow {
                Layout.fillWidth: true
                spacing: 8
                PButton { objectName: "runChecks"; kind: "accent"; iconName: "checkmark_circle"; text: I18n.tr("Daten prüfen", I18n.revision); busy: Diagnose.busy && Diagnose.busyText.indexOf("geprüft") >= 0; busyText: I18n.tr("Wird geprüft …", I18n.revision); enabled: !Diagnose.busy; onClicked: Diagnose.runChecks() }
                PButton { objectName: "supportPackage"; iconName: "arrow_export"; text: I18n.tr("Support-Paket erstellen …", I18n.revision); tip: I18n.tr("ZIP mit Bericht und bereinigten Protokollen – ohne Kunden- oder Dokumentdaten, wird nicht versendet", I18n.revision); enabled: !Diagnose.busy; onClicked: Diagnose.createPackage() }
                PButton { kind: "subtle"; iconName: "document_bullet_list"; text: I18n.tr("Protokolle öffnen", I18n.revision); tip: I18n.tr("Datenordner mit pdf-tool.log, fehler.log, stapel.log und pdf-repair.log", I18n.revision); onClicked: Diagnose.openLogs() }
                PButton { kind: "subtle"; iconName: "delete"; text: I18n.tr("Temporäre Dateien aufräumen", I18n.revision); tip: I18n.tr("Entfernt nur eigene temporäre Dateien früherer Sitzungen", I18n.revision); onClicked: Diagnose.cleanupNow() }
            }
            PCollapse {
                Layout.fillWidth: true
                expanded: Diagnose.busy
                ColumnLayout {
                    width: parent.width
                    PText { text: I18n.tr(Diagnose.busyText, I18n.revision); Layout.topMargin: 10 }
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
                    PText { text: I18n.tr(Diagnose.verdict, I18n.revision); textStyle: "bodyStrong"; wrap: true; Layout.fillWidth: true }
                    PText { text: I18n.tr(Diagnose.lastRun, I18n.revision); textStyle: "caption"; tone: "secondary" }
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
                    PText { text: I18n.tr(modelData.label, I18n.revision); Layout.preferredWidth: 150; Layout.alignment: Qt.AlignTop }
                    PText { text: I18n.tr(modelData.detail, I18n.revision); tone: "secondary"; wrap: true; Layout.fillWidth: true }
                }
            }
            PInfoBar { Layout.fillWidth: true; notice: Notices.area("diagnose_info") }
            PText { text: I18n.tr("Systeminformationen", I18n.revision); textStyle: "bodyStrong"; Layout.topMargin: 16 }
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
                        PText { text: I18n.tr(label, I18n.revision); textStyle: "caption"; tone: "secondary"; Layout.preferredWidth: 150; Layout.alignment: Qt.AlignTop; Layout.topMargin: 2 }
                        PText { text: I18n.tr(value, I18n.revision); wrap: true; Layout.fillWidth: true }
                    }
                }
            }
        }
    }

    ColumnLayout {
        objectName: "settingsSection_info"
        Layout.fillWidth: true
        visible: Settings.section === "info"
        spacing: 0
        PSectionTitle { text: I18n.tr("Info", I18n.revision) }

        PSettingsCard {
            objectName: "infoCard"
            Layout.fillWidth: true
            iconName: "info"
            title: I18n.tr(App.appName, I18n.revision)
            description: I18n.tr("Version " + App.version + " · Entwickler und Inhaber: " + App.developer, I18n.revision)
            // Beta-Version: dasselbe Etikett wie in der Karte »Updates«
            PBadge { objectName: "infoBeta"; text: I18n.tr(App.beta ? "Beta" : "", I18n.revision); tone: "accent"; anchors.verticalCenter: parent.verticalCenter }
            PButton { text: I18n.tr("Über", I18n.revision); onClicked: App.showAbout() }
        }
        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "question_circle"
            title: I18n.tr("Kurzanleitung", I18n.revision)
            description: I18n.tr("So arbeiten Sie mit den Werkzeugen von Novadesk" + Shortcuts.hints["app.help"], I18n.revision)
            PButton { text: I18n.tr("Öffnen", I18n.revision); onClicked: App.showHelp() }
        }
        PSettingsCard {
            objectName: "settingsShortcuts"
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "keyboard"
            title: I18n.tr("Tastenkürzel", I18n.revision)
            description: I18n.tr("Alle Kürzel auf einen Blick – und eigene festlegen" + Shortcuts.hints["app.shortcuts"], I18n.revision)
            PButton { objectName: "settingsShortcutsOpen"; text: I18n.tr("Anzeigen und ändern", I18n.revision); onClicked: Shortcuts.showOverview() }
        }
        PSettingsCard {
            Layout.fillWidth: true
            Layout.topMargin: 4
            iconName: "megaphone"
            title: I18n.tr("Neuerungen", I18n.revision)
            description: I18n.tr("Was ist neu in Version " + App.version, I18n.revision)
            PButton { text: I18n.tr("Anzeigen", I18n.revision); onClicked: App.showChangelog() }
        }
    }

}
