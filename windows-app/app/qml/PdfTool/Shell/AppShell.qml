import QtQuick
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
            color: Theme.layer
            Rectangle { width: parent.width; height: 1; color: Theme.layerStroke; visible: !shell.fullScreen }

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
                height: shell.fullScreen ? 0 : implicitHeight
                visible: !shell.fullScreen
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

    // Tastenkürzel (nicht, solange ein Dialog offen ist)
    Shortcut { sequences: Shortcuts.keys["app.primary"] || []; enabled: !Dialogs.open; onActivated: App.primaryAction() }
    Shortcut { sequences: Shortcuts.keys["app.open"] || []; enabled: !Dialogs.open; onActivated: App.openAction() }
    Shortcut { sequences: Shortcuts.keys["app.find"] || []; enabled: !Dialogs.open; onActivated: App.findAction() }
    Shortcut { sequences: Shortcuts.keys["app.help"] || []; enabled: !Dialogs.open; onActivated: App.showHelp() }
    Shortcut { sequences: Shortcuts.keys["app.shortcuts"] || []; enabled: !Dialogs.open; onActivated: Shortcuts.showOverview() }
    Shortcut { sequences: Shortcuts.keys["app.home"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(1) }
    Shortcut { sequences: Shortcuts.keys["app.contracts"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(2) }
    Shortcut { sequences: Shortcuts.keys["app.repair"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(3) }
    Shortcut { sequences: Shortcuts.keys["app.settings"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(4) }
    Shortcut { sequences: Shortcuts.keys["app.reader"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(5) }
    Shortcut { sequences: Shortcuts.keys["app.actions"] || []; enabled: !Dialogs.open; onActivated: App.openShortcut(6) }
    // Tab eines Werkzeugs schließen (im Reader schließt Strg+W das Dokument)
    readonly property string currentTab: App.currentPage === "settings" ? "settings" : App.currentTool
    Shortcut { sequences: Shortcuts.keys["app.closeTab"] || []; enabled: !Dialogs.open && App.currentPage !== "reader" && App.openTabs.indexOf(shell.currentTab) >= 0; onActivated: App.closeTab(shell.currentTab) }
    // Zuletzt geschlossenes Dokument wieder öffnen – auf jeder Seite, wie im Browser
    Shortcut { objectName: "reopenShortcut"; sequences: Shortcuts.keys["app.reopen"] || []; enabled: !Dialogs.open && Reader.canReopen; onActivated: Reader.reopenClosed() }
}
