import QtQuick
import QtQuick.Shapes
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Aufbau des Hauptfensters (Adobe-Prinzip): oben die Tab-Leiste mit ⌂ Start, den Tabs der geöffneten
// Werkzeuge und PDFs; darunter die Inhaltsebene mit Seiten und Statuszeile über die ganze Breite. Dazu
// Dialoge, Drag & Drop und Tastenkürzel.
FocusScope {
    id: shell
    property alias pages: host
    // Vollbild (F11 im Reader): nur das Dokument – Tab-Leiste und Statuszeile ausgeblendet
    readonly property bool fullScreen: Reader.fullScreen

    // Themawechsel: das bisherige Bild blendet über dem neuen aus (kurz, »Aus«: sofort)
    property var pendingTheme: null
    function changeTheme(apply) {
        if (!Motion.enabled || GraphicsInfo.api === GraphicsInfo.Software || !shell.visible) {
            apply()
            return
        }
        snapshot.scheduleUpdate()
        snapshot.opacity = 1
        snapshot.visible = true
        pendingTheme = apply
    }
    Connections {
        target: shell.Window.window
        enabled: shell.pendingTheme !== null
        function onFrameSwapped() {
            var apply = shell.pendingTheme
            shell.pendingTheme = null
            if (apply) apply()
            themeFade.restart()
        }
    }

    Item {
        id: scene
        anchors.fill: parent

        // Hintergrund: Mica aus dem Desktophintergrund (aktives Fenster) oder die Grundfarbe
        Rectangle {
            anchors.fill: parent
            color: Theme.background
        }
        // Seit 5.0 Beta 10 (Entwürfe 7/8): feiner Farbverlauf (hell: kühles Blau → Grau → zartes Lila), im Neon-Modus
        // zwei Lichtflecken in den Neon-Farben oben links und unten rechts. Ohne Mica sichtbar, Mica liegt darüber.
        Shape {
            id: backdrop
            anchors.fill: parent
            visible: !Theme.dark || Theme.neon
            ShapePath {
                strokeWidth: -1
                fillGradient: LinearGradient {
                    x1: 0; y1: 0; x2: backdrop.width * 0.55; y2: backdrop.height
                    GradientStop { position: 0.0; color: Theme.neon ? "#0A0C11" : "#EEF3FA" }
                    GradientStop { position: 0.38; color: Theme.neon ? "#0A0C11" : "#F3F3F3" }
                    GradientStop { position: 1.0; color: Theme.neon ? "#0A0C11" : "#F4F1F8" }
                }
                PathRectangle { width: backdrop.width; height: backdrop.height }
            }
            ShapePath {
                strokeWidth: -1
                fillGradient: RadialGradient {
                    centerX: backdrop.width * 0.12; centerY: -backdrop.height * 0.1; centerRadius: Math.max(600, backdrop.width * 0.55)
                    focalX: centerX; focalY: centerY
                    GradientStop { position: 0.0; color: Theme.neon ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.20) : "transparent" }
                    GradientStop { position: 0.6; color: "transparent" }
                }
                PathRectangle { width: backdrop.width; height: backdrop.height }
            }
            ShapePath {
                strokeWidth: -1
                fillGradient: RadialGradient {
                    centerX: backdrop.width * 1.05; centerY: backdrop.height * 1.1; centerRadius: Math.max(500, backdrop.width * 0.45)
                    focalX: centerX; focalY: centerY
                    GradientStop { position: 0.0; color: Theme.neon ? Qt.rgba(0.49, 0.30, 1.0, 0.18) : "transparent" }
                    GradientStop { position: 0.6; color: "transparent" }
                }
                PathRectangle { width: backdrop.width; height: backdrop.height }
            }
        }
        Image {
            id: mica
            readonly property var win: shell.Window.window
            visible: ThemeBackend.micaSource !== "" && shell.Window.active && status === Image.Ready
            source: ThemeBackend.micaSource !== "" && shell.Screen.width > 0 ? ThemeBackend.micaSource + "/" + Math.round(shell.Screen.width) + "x" + Math.round(shell.Screen.height) : ""
            x: win ? shell.Screen.virtualX - win.x : 0
            y: win ? shell.Screen.virtualY - win.y : 0
            width: shell.Screen.width
            height: shell.Screen.height
            smooth: true
            asynchronous: true
            cache: true
        }

        AppTabs {
            id: tabs
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            visible: !shell.fullScreen
            height: shell.fullScreen ? 0 : implicitHeight
            z: 1  // über der Kante der Inhaltsebene: der aktive Tab geht in sie über
        }

        // Inhaltsebene über die ganze Breite unter den Tabs; ihre obere Kante ist eine feine Linie, die unter dem
        // aktiven Tab verschwindet.
        Rectangle {
            id: layer
            x: 0
            y: tabs.height
            width: parent.width
            height: parent.height - y
            // 3D-Design: keine eigene Ebene mehr – Leisten und Karten schweben über dem Hintergrund (Vollbild: Fläche der Seiten)
            color: shell.fullScreen ? Theme.layer : "transparent"

            PageHost {
                id: host
                x: 0
                y: shell.fullScreen ? 0 : 1
                width: layer.width
                height: layer.height - y - status.height
            }
            StatusBar {
                id: status
                x: 0
                y: layer.height - height
                width: layer.width
                // Startseite (Entwurf 11): ohne Statuszeile, solange es nichts zu melden gibt – eine Meldung schiebt sie herein
                readonly property bool quiet: App.currentPage === "home" && (App.statusText === "Bereit" || App.statusText === "")
                height: shell.fullScreen || quiet ? 0 : implicitHeight
                Behavior on height { enabled: Motion.moves && !shell.fullScreen; NumberAnimation { duration: Motion.expand; easing.type: Motion.decelerate } }
                clip: true
                visible: !shell.fullScreen && height > 0
            }
        }
    }

    ShaderEffectSource {
        id: snapshot
        anchors.fill: parent
        sourceItem: scene
        live: false
        visible: false
        hideSource: false
        z: 900
        NumberAnimation on opacity {
            id: themeFade
            running: false
            from: 1
            to: 0
            duration: Motion.theme
            easing.type: Motion.standard
            onFinished: snapshot.visible = false
        }
    }

    // 3D-Tab-Übersicht (Strg+Tab, Entwurf 10) über allem außer den Dialogen
    TabSwitcher {
        anchors.fill: parent
        source: host
        z: 50
    }
    DialogHost {}

    DropArea {
        anchors.fill: parent
        onEntered: (drag) => {
            var accepted = App.dragEnter(drag.urls)
            drag.accepted = accepted
            if (accepted) drag.acceptProposedAction()
        }
        onExited: App.dragLeave()
        onDropped: (drop) => {
            if (drop.hasUrls) {
                drop.acceptProposedAction()
                App.drop(drop.urls)
            } else {
                App.dragLeave()
            }
        }
    }

    // Text, Tabelle oder Präsentation im Vordergrund: dort gehören Strg+1 … Strg+8 und Strg+Eingabe dem Dokument
    // (wie in Word, Excel und PowerPoint: Zeilenabstand, Zellen formatieren, Seitenumbruch …), nicht der Navigation
    readonly property string officeKind: App.currentPage === "reader" && Reader.current !== null && Reader.current !== undefined
                                         && ["text", "praesentation", "tabelle"].indexOf(Reader.current.kind) >= 0 ? Reader.current.kind : ""

    // Tastenkürzel (nicht, solange ein Dialog offen ist)
    Shortcut { sequences: Shortcuts.keys["app.primary"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.primaryAction() }
    Shortcut { sequences: Shortcuts.keys["app.open"] || []; enabled: !Dialogs.open; onActivated: App.openAction() }
    Shortcut { objectName: "newSheetShortcut"; sequences: Shortcuts.keys["app.new"] || []; enabled: !Dialogs.open; onActivated: shell.officeKind === "text" ? Reader.newText() : (shell.officeKind === "praesentation" ? Reader.newSlides() : Reader.newSheet()) }
    Shortcut { sequences: Shortcuts.keys["app.find"] || []; enabled: !Dialogs.open; onActivated: App.findAction() }
    Shortcut { sequences: Shortcuts.keys["app.help"] || []; enabled: !Dialogs.open; onActivated: App.showHelp() }
    Shortcut { sequences: Shortcuts.keys["app.shortcuts"] || []; enabled: !Dialogs.open; onActivated: Shortcuts.showOverview() }
    Shortcut { sequences: Shortcuts.keys["app.home"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(1) }
    Shortcut { sequences: Shortcuts.keys["app.contracts"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(2) }
    Shortcut { sequences: Shortcuts.keys["app.repair"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(3) }
    Shortcut { sequences: Shortcuts.keys["app.settings"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(4) }
    Shortcut { sequences: Shortcuts.keys["app.reader"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(5) }
    Shortcut { sequences: Shortcuts.keys["app.actions"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(6) }
    Shortcut { sequences: Shortcuts.keys["app.convert"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(7) }
    Shortcut { sequences: Shortcuts.keys["app.versions"] || []; enabled: !Dialogs.open && shell.officeKind === ""; onActivated: App.openShortcut(8) }
    // Tab eines Werkzeugs schließen (im Reader schließt Strg+W das Dokument); die Einstellungen (ohne eigenen Tab)
    // schließt Strg+W zurück zur Seite davor
    Shortcut { sequences: Shortcuts.keys["app.closeTab"] || []; enabled: !Dialogs.open && App.currentPage !== "reader" && App.openTabs.indexOf(App.currentTool) >= 0; onActivated: App.closeTab(App.currentTool) }
    Shortcut { objectName: "closeSettingsShortcut"; sequences: Shortcuts.keys["app.closeTab"] || []; enabled: !Dialogs.open && App.currentPage === "settings"; onActivated: App.leaveSettings() }
    // Zuletzt geschlossenes Dokument wieder öffnen – auf jeder Seite, wie im Browser
    Shortcut { objectName: "reopenShortcut"; sequences: Shortcuts.keys["app.reopen"] || []; enabled: !Dialogs.open && Reader.canReopen; onActivated: Reader.reopenClosed() }
}
