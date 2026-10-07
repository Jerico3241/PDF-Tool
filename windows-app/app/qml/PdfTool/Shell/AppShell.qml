import QtQuick
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Aufbau des Hauptfensters: Mica-Hintergrund, Navigation, Inhaltsebene mit Seiten und
// Statuszeile, Dialoge, Drag & Drop und Tastenkürzel.
FocusScope {
    id: shell
    property alias pages: host
    // Breakpoints: breit (Navigation ausgeklappt), mittel und kompakt (Navigation eingeklappt) – mit
    // kleiner Hysterese, damit ein Fenster an der Grenze nicht hin- und herspringt (wie 2.6.1).
    // Ein Breakpoint stellt sofort um; animiert wird nur das Ein- und Ausklappen per Schaltfläche.
    property string mode: "wide"
    property bool userExpanded: false
    property bool paneAnimated: false
    // Im Dokument (Reader mit geöffneter PDF) zählt die Breite: dort ist die Navigation eingeklappt.
    // Die Menüschaltfläche klappt sie nur vorübergehend aus – bis zum nächsten geöffneten Dokument oder
    // bis der Reader verlassen wird; die gespeicherte Wahl (»nav_kompakt«) bleibt unberührt.
    readonly property bool documentFocus: App.currentPage === "reader" && Reader.hasDocument
    property bool documentExpanded: false
    readonly property int documentCount: Reader.tabs.count
    property int knownDocuments: 0
    onDocumentCountChanged: {
        if (documentCount > knownDocuments) documentExpanded = false  // neues Dokument: wieder kompakt
        knownDocuments = documentCount
    }
    onDocumentFocusChanged: {
        paneAnimated = true
        documentExpanded = false
    }
    readonly property bool paneExpanded: documentFocus ? documentExpanded : (App.navCompact ? false : (mode === "wide" ? true : userExpanded))
    // Vollbild (F11 im Reader): nur das Dokument – Navigation, Hinweisleiste und Statuszeile ausgeblendet
    readonly property bool fullScreen: Reader.fullScreen

    function modeFor(w) {
        var hysteresis = Metrics.breakpointHysteresis
        if (w >= Metrics.wideFrom - (mode === "wide" ? hysteresis : 0)) return "wide"
        if (w >= Metrics.mediumFrom - (mode !== "compact" ? hysteresis : 0)) return "medium"
        return "compact"
    }
    function updateMode() {
        var next = modeFor(width)
        if (next === mode) return
        paneAnimated = false
        if (next === "wide" || mode === "wide") userExpanded = false
        mode = next
    }
    onWidthChanged: updateMode()

    function togglePane() {
        paneAnimated = true
        if (documentFocus) {
            documentExpanded = !documentExpanded
            return
        }
        if (paneExpanded) {
            App.setNavCompact(true)
            userExpanded = false
        } else {
            App.setNavCompact(false)
            // auch bei schmalem Fenster klappt die Menüschaltfläche die Navigation aus
            userExpanded = mode !== "wide"
        }
    }

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

        NavigationPane {
            id: nav
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            visible: !shell.fullScreen
            expanded: shell.paneExpanded
            animated: shell.paneAnimated
            onToggleRequested: shell.togglePane()
        }

        // Inhaltsebene: nur die obere linke Ecke ist abgerundet (Windows 11). Klappt die Navigation
        // ein oder aus, gleitet die Ebene mit; Seite und Statuszeile nehmen ihre neue Breite sofort
        // an – sie werden einmal neu angeordnet, nicht in jedem Bild der Animation (wie 2.6.1).
        Rectangle {
            id: layer
            readonly property real navSpace: shell.fullScreen ? 0 : nav.targetWidth
            x: shell.fullScreen ? 0 : nav.width
            y: 0
            width: parent.width - x + radius
            height: parent.height + radius
            radius: shell.fullScreen ? 0 : Metrics.radiusCard
            color: Theme.layer
            border.width: shell.fullScreen ? 0 : 1
            border.color: Theme.layerStroke

            // Hinweisleiste für Updates über den Seiten (die Seiten rücken einmal um ihre Höhe)
            UpdateBanner {
                id: updateBanner
                x: 1
                y: 1
                width: shell.width - layer.navSpace - 1
                height: implicitHeight
                suppressed: shell.fullScreen
            }
            PageHost {
                id: host
                x: 1
                y: 1 + updateBanner.height
                width: shell.width - layer.navSpace - 1
                height: shell.height - 1 - status.height - updateBanner.height
            }
            StatusBar {
                id: status
                x: 1
                y: shell.height - height
                width: shell.width - layer.navSpace - 1
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
    Shortcut { sequences: ["Ctrl+Return", "Ctrl+Enter"]; enabled: !Dialogs.open; onActivated: App.primaryAction() }
    Shortcut { sequence: "Ctrl+O"; enabled: !Dialogs.open; onActivated: App.openAction() }
    Shortcut { sequence: "Ctrl+F"; enabled: !Dialogs.open; onActivated: App.findAction() }
    Shortcut { sequence: "F1"; enabled: !Dialogs.open; onActivated: App.showHelp() }
    Shortcut { sequence: "Ctrl+1"; enabled: !Dialogs.open; onActivated: App.openShortcut(1) }
    Shortcut { sequence: "Ctrl+2"; enabled: !Dialogs.open; onActivated: App.openShortcut(2) }
    Shortcut { sequence: "Ctrl+3"; enabled: !Dialogs.open; onActivated: App.openShortcut(3) }
    Shortcut { sequence: "Ctrl+4"; enabled: !Dialogs.open; onActivated: App.openShortcut(4) }
    Shortcut { sequence: "Ctrl+5"; enabled: !Dialogs.open; onActivated: App.openShortcut(5) }
}
