import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Leiste oben nach dem Vorbild von Adobe Acrobat: ≡ Menü, ⌂ Start, je ein Tab für geöffnete Werkzeuge
// (Vertragsübersichten, PDF reparieren, Einstellungen) und für jedes geöffnete PDF, »+« öffnet weitere PDFs;
// rechts Kurzanleitung und Einstellungen. Sie liegt auf dem Hintergrund (Mica), der aktive Tab geht in die
// Inhaltsebene darunter über. Die Akzentmarkierung gleitet zum aktiven Tab und folgt ihm, wenn Tabs
// hinzukommen, wegfallen oder die Dokument-Tabs gescrollt werden.
// Bewegung der Dokument-Tabs: ein neuer Tab blendet ein, ein geschlossener blendet aus, die übrigen rücken weich
// nach; der Punkt für »ungespeichert« blendet ein und aus (sein Platz ist immer reserviert). »Reduziert«: nur
// Überblenden, »Aus«: alles sofort.
// Dokument-Tabs lassen sich mit der Maus an eine andere Stelle ziehen (Strg+Umschalt+←/→ im fokussierten Tab): Der
// gezogene Tab folgt dem Zeiger, die Nachbarn weichen weich aus, beim Loslassen gleitet er an seinen Platz. Rechtsklick
// (Kontextmenü-Taste, Umschalt+F10) öffnet das Kontextmenü des Tabs.
Item {
    id: bar
    objectName: "appTabs"
    implicitHeight: Metrics.appBarHeight
    Accessible.role: Accessible.PageTabList
    Accessible.name: "Start, Werkzeuge und Dokumente"

    function toolInfo(key) {
        if (key === "settings") return { title: "Einstellungen", icon: "settings" }
        var tools = App.tools
        for (var i = 0; i < tools.length; ++i)
            if (tools[i].key === key) return { title: tools[i].title, icon: tools[i].icon }
        return { title: key, icon: "" }
    }
    // Aktiver Tab: Start, ein Werkzeug-Tab (»contracts«, »repair«, »settings«) oder das aktive Dokument
    // Platz bei vielen Tabs: Die Werkzeug-Tabs behalten ihre Breite, solange die Dokument-Tabs ihren Mindestplatz haben
    // (sonst werden sie gleichmäßig schmaler, der Name gekürzt); die Dokument-Tabs teilen sich den Rest und werden wie in
    // Edge schmaler – reicht auch das nicht, zeigt die Leiste nur ganze, gleich breite Tabs und ‹ › zum Blättern.
    // Alle Breiten folgen aus der Breite der Leiste, nie aus der Liste selbst (das gäbe eine Schleife).
    readonly property real fixedWidth: menuButton.width + homeTab.width + addButton.width + helpButton.width + settingsButton.width + 6 * row.spacing
    readonly property real toolTabCap: {
        var count = toolTabs.count
        if (count === 0) return 0
        var free = row.width - fixedWidth - (Reader.tabs.count > 0 ? Metrics.appDocsMinWidth : 0)
        return Math.floor(free / count) - row.spacing
    }
    readonly property real toolTabsWidth: {
        tabsRevision
        var width = 0
        for (var i = 0; i < toolTabs.count; ++i) {
            var item = toolTabs.itemAt(i)
            if (item) width += item.width + row.spacing
        }
        return width
    }
    readonly property real docsRoom: row.width - fixedWidth - toolTabsWidth  // Platz für die Dokument-Tabs
    readonly property real docTabCap: {
        var count = Reader.tabs.count
        if (count === 0) return 0
        return Math.max(Metrics.appDocTabMinWidth, Math.floor(docsRoom / count) - docs.spacing)
    }
    readonly property int docPitch: Metrics.appDocTabMinWidth + docs.spacing  // ein Tab samt Abstand beim Blättern
    readonly property bool docsOverflow: Reader.tabs.count * docPitch - docs.spacing > docsRoom + 0.5
    readonly property real docsScrollWidth: 2 * (Metrics.appTabScroll + docs.spacing)  // ‹ und › samt Abstand
    readonly property int docsShown: Math.max(1, Math.floor((docsRoom - docsScrollWidth + docs.spacing) / docPitch))
    readonly property string activeKey: App.currentPage === "home" ? "home"
                                       : (App.currentPage === "settings" ? "settings"
                                       : (App.currentTool === "reader" ? (Reader.hasDocument ? "doc:" + Reader.currentKey : "") : App.currentTool))
    function tabItem(key) {
        if (key === "") return null
        if (key === "home") return homeTab
        if (key.indexOf("doc:") === 0) {
            var index = Reader.tabs.indexOf(key.substring(4))
            return index >= 0 ? docs.itemAtIndex(index) : null
        }
        for (var i = 0; i < toolTabs.count; ++i) {
            var item = toolTabs.itemAt(i)
            if (item && item.key === key) return item
        }
        return null
    }

    // Ziehen eines Dokument-Tabs. Lagen in Inhaltskoordinaten der Liste; Reihenfolge aus dem Modell, Breiten von den Tabs
    // selbst (bei Platzmangel sind alle gleich breit) – nie Lagen, die gerade eine Animation verschiebt.
    property string dragKey: ""     // gezogener Tab ("" = keiner)
    property real dragStart: 0      // seine Lage beim Beginn
    property real dragScroll: 0     // Bildlauf der Liste beim Beginn
    property real dragShift: 0      // Weg des Zeigers seit dem Beginn
    property real dragWidth: 0
    readonly property real dragRaw: dragStart + dragShift + docs.contentX - dragScroll
    // Lage des gezogenen Tabs: folgt dem Zeiger und bleibt ganz im sichtbaren Teil der Liste
    readonly property real dragX: {
        var low = Math.max(0, docs.contentX)
        var high = Math.max(low, Math.min(docs.contentWidth, docs.contentX + docs.width) - dragWidth)
        return Math.max(low, Math.min(high, dragRaw))
    }
    function slotWidth(row) {
        if (bar.docsOverflow) return Metrics.appDocTabMinWidth
        var key = Reader.tabs.get(row).key
        var slots = docs.contentItem.children
        for (var i = 0; i < slots.length; ++i)
            if (slots[i].key === key) return slots[i].width
        return Metrics.appDocTabMinWidth
    }
    function slotLeft(row) {
        var left = 0
        for (var i = 0; i < row; ++i) left += slotWidth(i) + docs.spacing
        return left
    }
    function startTabDrag(slot) {
        dragStart = slotLeft(slot.index)
        dragScroll = docs.contentX
        dragShift = 0
        dragWidth = slot.width
        dragKey = slot.key
    }
    // Überschreitet die Mitte des gezogenen Tabs die Mitte eines Nachbarn, tauschen beide die Stelle – ein Schritt je
    // Aufruf (die Liste ordnet ihre Einträge erst danach neu an)
    function dragTabTo(shift) {
        if (dragKey === "") return
        dragShift = shift
        var row = Reader.tabs.indexOf(dragKey)
        if (row < 0) {
            dragKey = ""
            return
        }
        var center = dragX + dragWidth / 2
        if (row < Reader.tabs.count - 1 && center > slotLeft(row + 1) + slotWidth(row + 1) / 2)
            Reader.moveTab(row, row + 1)
        else if (row > 0 && center < slotLeft(row - 1) + slotWidth(row - 1) / 2)
            Reader.moveTab(row, row - 1)
    }
    // Bei Platzmangel: am Rand der Liste blättert sie um einen Tab weiter, solange der Zeiger dort bleibt
    Timer {
        interval: 350
        repeat: true
        running: bar.dragKey !== "" && bar.docsOverflow
        onTriggered: {
            if (bar.dragRaw < docs.contentX - 0.5)
                docsWheel.move(true, -bar.docPitch, true)
            else if (bar.dragRaw + bar.dragWidth > docs.contentX + docs.width + 0.5)
                docsWheel.move(true, bar.docPitch, true)
        }
    }
    // Kontextmenü eines Dokument-Tabs an der Stelle ``at`` im Tab (Rechtsklick) bzw. unter ihm (Tastatur)
    function openTabMenu(slot, tab, at) {
        tabMenu.key = slot.key
        tabMenu.path = slot.path
        tabMenu.row = slot.index
        if (at) tabMenu.popup(tab, at.x, at.y)
        else tabMenu.popup(tab, 0, tab.height + 4)
    }

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        spacing: 2

        PIconButton {
            id: menuButton
            objectName: "appMenuButton"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: (Metrics.appTabHeight - height) / 2
            iconName: "navigation"
            tip: "Menü"
            onClicked: appMenu.popup(menuButton, 0, menuButton.height + 4)
        }
        AppTab {
            id: homeTab
            objectName: "tabHome"
            Layout.alignment: Qt.AlignBottom
            iconName: "home"
            tooltip: "Start (Strg+1)"
            active: bar.activeKey === "home"
            onClicked: App.navigate("home")
        }
        Repeater {
            id: toolTabs
            model: App.openTabs
            onItemAdded: bar.tabsRevision++
            onItemRemoved: bar.tabsRevision++
            AppTab {
                id: toolTab
                required property string modelData
                readonly property string key: modelData
                readonly property var info: bar.toolInfo(modelData)
                objectName: "tab_" + modelData
                Layout.alignment: Qt.AlignBottom
                // volle Breite, solange die Dokument-Tabs ihren Mindestplatz haben – sonst schmaler (Name gekürzt)
                Layout.preferredWidth: Math.min(implicitWidth, Math.max(Metrics.appTabMinWidth, bar.toolTabCap))
                iconName: info.icon
                title: info.title
                closable: true
                closeTip: "Tab schließen (Strg+W) – Eingaben bleiben erhalten"
                active: bar.activeKey === modelData
                onClicked: App.navigate(modelData)
                onCloseRequested: App.closeTab(modelData)
                // neu geöffnet: einblenden und leicht heben
                transform: Translate { id: lift }
                Component.onCompleted: if (Motion.enabled && App.ready) appear.start()
                ParallelAnimation {
                    id: appear
                    NumberAnimation { target: toolTab; property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                    NumberAnimation { target: lift; property: "y"; from: Motion.moves ? 6 : 0; to: 0; duration: Motion.fade; easing.type: Motion.decelerate }
                }
            }
        }
        // Dokumente: ein Tab je PDF; der aktive bleibt im Blick. Haben nicht alle Platz, zeigt die Leiste nur ganze,
        // gleich breite Tabs und ‹ › zum Blättern – das Mausrad verschiebt ebenfalls um ganze Tabs. Ziehen mit der Maus
        // ordnet einen Tab um (am Rand der Leiste blättert sie dabei weiter). Die Liste reicht 1 px über die Leiste
        // hinaus: Dort geht der aktive Tab in die Inhaltsebene über.
        Item {
            id: docsArea
            readonly property real wanted: bar.docsOverflow ? bar.docsShown * bar.docPitch - docs.spacing + bar.docsScrollWidth : docs.contentWidth
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: wanted
            Layout.maximumWidth: wanted
            Layout.minimumWidth: bar.docsOverflow ? wanted : Math.min(docs.contentWidth, Metrics.appDocsMinWidth)
            PIconButton {
                objectName: "readerTabsBack"
                visible: bar.docsOverflow
                x: 0
                y: parent.height - Metrics.appTabHeight + (Metrics.appTabHeight - height) / 2
                implicitWidth: Metrics.appTabScroll
                implicitHeight: 28
                iconName: "chevron_left"
                tip: "Vorherige Tabs"
                focusPolicy: Qt.NoFocus
                enabled: docs.contentX > docs.originX + 0.5
                onClicked: docsWheel.move(true, -bar.docPitch, true)
            }
            ListView {
                id: docs
                objectName: "readerTabs"
                x: bar.docsOverflow ? Metrics.appTabScroll + spacing : 0
                width: bar.docsOverflow ? bar.docsShown * bar.docPitch - spacing : parent.width
                height: parent.height + 1
                orientation: ListView.Horizontal
                model: Reader.tabs
                spacing: 2
                clip: true
                // Ziehen gehört den Tabs (umordnen) – die Liste selbst blättert nur mit Mausrad, ‹ › und am Rand beim Ziehen
                interactive: false
                boundsBehavior: Flickable.StopAtBounds
                snapMode: bar.docsOverflow ? ListView.SnapToItem : ListView.NoSnap
                Accessible.role: Accessible.PageTabList
                Accessible.name: "Geöffnete Dokumente"
                readonly property string activeKey: Reader.currentKey
                function revealActive() {
                    var index = Reader.tabs.indexOf(activeKey)
                    if (index >= 0) positionViewAtIndex(index, ListView.Contain)
                }
                onActiveKeyChanged: Qt.callLater(revealActive)
                onCountChanged: { Qt.callLater(revealActive); bar.tabsRevision++ }
                // schmaleres Fenster oder schmalere Tabs: der aktive bleibt ganz zu sehen
                onWidthChanged: Qt.callLater(revealActive)
                onContentWidthChanged: Qt.callLater(revealActive)
                // Blättert die Liste beim Ziehen weiter, folgt der gezogene Tab dem Zeiger und tauscht weiter die Stelle
                onContentXChanged: if (bar.dragKey !== "") bar.dragTabTo(bar.dragShift)
                Component.onCompleted: revealActive()
                // Mausrad über den Tabs: waagerecht um ganze Tabs (nur wenn nicht alle Platz haben)
                PWheelScroll { id: docsWheel; objectName: "readerTabsWheel"; flickable: docs; sideways: true; notch: bar.docsOverflow ? bar.docPitch : 0 }
                // Beim Beenden (alle PDFs werden geschlossen) ohne Übergänge: Die Oberfläche endet gleich danach
                add: Transition {
                    enabled: Motion.enabled && !App.closing
                    NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
                }
                remove: Transition {
                    enabled: Motion.enabled && !App.closing
                    NumberAnimation { property: "opacity"; to: 0; duration: Motion.fast; easing.type: Motion.accelerate }
                }
                displaced: Transition {
                    enabled: Motion.moves && !App.closing
                    NumberAnimation { properties: "x"; duration: Motion.expand; easing.type: Motion.decelerate }
                }
                // Umgeordnet (Ziehen, Strg+Umschalt+←/→): der Tab gleitet an seine neue Stelle
                move: Transition {
                    enabled: Motion.moves && !App.closing
                    NumberAnimation { properties: "x"; duration: Motion.expand; easing.type: Motion.decelerate }
                }
                // Die Liste legt ihre Einträge oben an: Der Tab steht unten in einer Hülle über die ganze Höhe
                delegate: Item {
                    id: docSlot
                    required property string key
                    required property string name
                    required property bool dirty
                    required property string tip
                    required property string path
                    required property int index
                    readonly property real shift: docTab.x  // Versatz des Tabs beim Ziehen – die Markierung folgt ihm
                    width: docTab.width
                    height: docs.height
                    z: docTab.dragged ? 1 : 0
                    // Die Liste legt Einträge erst nach der Änderung des Modells an: dann die Markierung neu ausrichten
                    Component.onCompleted: bar.tabsRevision++
                    Component.onDestruction: bar.tabsRevision++
                    AppTab {
                        id: docTab
                        readonly property bool dragged: bar.dragKey === docSlot.key
                        property real settle: 0  // nach dem Loslassen: Versatz zum Platz, gleitet weich auf 0
                        objectName: "readerTab_" + docSlot.index
                        x: dragged ? bar.dragX - docSlot.x : settle
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 1
                        width: bar.docsOverflow ? Metrics.appDocTabMinWidth : Math.min(implicitWidth, bar.docTabCap)
                        elideMode: Text.ElideMiddle
                        iconName: "document_pdf"
                        // ohne ».pdf« (das Symbol zeigt es) – der vollständige Pfad steht im Tooltip
                        title: docSlot.name.replace(/\.pdf$/i, "") || docSlot.name
                        tooltip: docSlot.tip
                        unsaved: docSlot.dirty
                        showDirty: true
                        closable: true
                        closeName: "readerTabClose"
                        dirtyName: "readerTabDirty"
                        closeTip: "Schließen (Strg+W)"
                        active: bar.activeKey === "doc:" + docSlot.key
                        onClicked: Reader.showTab(docSlot.key)
                        onCloseRequested: Reader.closeTab(docSlot.key)
                        // Kontextmenü (Kontextmenü-Taste, Umschalt+F10); Strg+Umschalt+←/→ verschiebt den Tab
                        Keys.onPressed: (event) => {
                            if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
                                bar.openTabMenu(docSlot, docTab, null)
                                event.accepted = true
                            } else if ((event.key === Qt.Key_Left || event.key === Qt.Key_Right) && (event.modifiers & Qt.ControlModifier) && (event.modifiers & Qt.ShiftModifier)) {
                                Reader.moveTab(docSlot.index, docSlot.index + (event.key === Qt.Key_Left ? -1 : 1))
                                event.accepted = true
                            }
                        }
                        TapHandler {
                            objectName: "readerTabMenuTap"
                            acceptedButtons: Qt.RightButton
                            onTapped: (eventPoint) => bar.openTabMenu(docSlot, docTab, eventPoint.position)
                        }
                        // Ziehen: der Tab folgt dem Zeiger (nur waagerecht), beim Loslassen gleitet er an seinen Platz
                        DragHandler {
                            objectName: "readerTabDrag"
                            target: null
                            yAxis.enabled: false
                            acceptedButtons: Qt.LeftButton
                            enabled: Reader.tabs.count > 1
                            onActiveChanged: {
                                if (active) {
                                    settleTab.stop()
                                    docTab.settle = 0
                                    bar.startTabDrag(docSlot)
                                } else if (docTab.dragged) {
                                    docTab.settle = bar.dragX - docSlot.x
                                    bar.dragKey = ""
                                    settleTab.restart()
                                }
                            }
                            onActiveTranslationChanged: if (active) bar.dragTabTo(activeTranslation.x)
                        }
                        NumberAnimation { id: settleTab; target: docTab; property: "settle"; to: 0; duration: Motion.expand; easing.type: Motion.decelerate }
                    }
                }
            }
            PIconButton {
                objectName: "readerTabsForward"
                visible: bar.docsOverflow
                x: docs.x + docs.width + docs.spacing
                y: parent.height - Metrics.appTabHeight + (Metrics.appTabHeight - height) / 2
                implicitWidth: Metrics.appTabScroll
                implicitHeight: 28
                iconName: "chevron_right"
                tip: "Weitere Tabs"
                focusPolicy: Qt.NoFocus
                enabled: docs.contentX < docs.originX + docs.contentWidth - docs.width - 0.5
                onClicked: docsWheel.move(true, bar.docPitch, true)
            }
        }
        PIconButton {
            id: addButton
            objectName: "readerTabAdd"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: (Metrics.appTabHeight - height) / 2
            iconName: "add"
            tip: "PDF öffnen (Strg+O)"
            onClicked: Reader.openDialog()
        }
        Item { Layout.fillWidth: true }
        PIconButton {
            id: helpButton
            objectName: "appHelpButton"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: (Metrics.appTabHeight - height) / 2
            iconName: "question_circle"
            tip: "Kurzanleitung (F1)"
            onClicked: App.showHelp()
        }
        PIconButton {
            id: settingsButton
            objectName: "appSettingsButton"
            Layout.alignment: Qt.AlignBottom
            Layout.bottomMargin: (Metrics.appTabHeight - height) / 2
            iconName: "settings"
            tip: "Einstellungen (Strg+4)"
            onClicked: App.navigate("settings")
        }
    }

    // Akzentmarkierung des aktiven Tabs. Ihre Lage ergibt sich in jedem Bild aus der Startlage und dem Tab
    // (auch wenn Tabs hinzukommen oder die Dokument-Tabs gescrollt werden), animiert wird nur der Fortschritt.
    property int tabsRevision: 0
    Rectangle {
        id: indicator
        objectName: "tabIndicator"
        readonly property Item target: { bar.tabsRevision; return bar.tabItem(bar.activeKey) }
        property Item shown: null
        property real fromX: 0
        property real fromWidth: 0
        property real progress: 1
        // Lage und Breite eines Tabs in der Leiste (Dokument-Tabs: verschoben um den Bildlauf, sichtbarer Teil)
        function frame(item) {
            var inDocs = item.parent === docs.contentItem
            var left = inDocs ? docsArea.x + docs.x + item.x + item.shift - docs.contentX : item.x
            var right = left + item.width
            if (inDocs) {
                left = Math.max(left, docsArea.x + docs.x)
                right = Math.min(right, docsArea.x + docs.x + docs.width)
            }
            return { x: row.x + left + Metrics.radiusCard, width: Math.max(0, right - left - 2 * Metrics.radiusCard) }
        }
        onTargetChanged: {
            // Zwischenzustand ohne Tab (die App setzt Werkzeug und Seite nacheinander, ein neuer Tab entsteht erst
            // danach): die Markierung merkt sich, wo sie steht, und gleitet von dort zum nächsten Tab
            if (target === null) return
            // von dort, wo die Markierung gerade steht – auch mitten in einem Gleiten
            var start = null
            if (shown !== null) {
                var before = frame(shown)
                start = { x: fromX + (before.x - fromX) * progress, width: fromWidth + (before.width - fromWidth) * progress }
            }
            var glides = start !== null && target !== null && Motion.moves
            glide.stop()
            fromX = start ? start.x : 0
            fromWidth = start ? start.width : 0
            shown = target
            progress = glides ? 0 : 1
            if (glides) glide.start()
        }
        Component.onCompleted: shown = target
        readonly property var goal: target ? frame(target) : { x: 0, width: 0 }
        visible: target !== null && goal.width > 0
        x: progress < 1 ? fromX + (goal.x - fromX) * progress : goal.x
        width: progress < 1 ? fromWidth + (goal.width - fromWidth) * progress : goal.width
        y: bar.height - Metrics.appTabHeight
        height: 2
        radius: 1
        color: Theme.accent
        NumberAnimation { id: glide; target: indicator; property: "progress"; to: 1; duration: Motion.indicator; easing.type: Motion.decelerate }
    }

    PMenu {
        id: appMenu
        objectName: "appMenu"
        PMenuItem { objectName: "menuOpen"; text: "PDF öffnen …"; iconName: "folder_open"; onTriggered: Reader.openDialog() }
        PMenuItem { objectName: "menuHome"; text: "Start"; iconName: "home"; onTriggered: App.navigate("home") }
        PMenuItem { objectName: "menuSettings"; text: "Einstellungen"; iconName: "settings"; onTriggered: App.navigate("settings") }
        T.MenuSeparator {
            topPadding: 4
            bottomPadding: 4
            contentItem: Rectangle { implicitWidth: 180; implicitHeight: 1; color: Theme.divider }
        }
        PMenuItem { objectName: "menuHelp"; text: "Kurzanleitung"; iconName: "question_circle"; onTriggered: App.showHelp() }
        PMenuItem { objectName: "menuNews"; text: "Neu in dieser Version"; iconName: "megaphone"; onTriggered: App.showChangelog() }
        PMenuItem { objectName: "menuAbout"; text: "Über PDF Tool"; iconName: "info"; onTriggered: App.showAbout() }
    }

    // Kontextmenü eines Dokument-Tabs. Die Aktion läuft erst nach dem Ausblenden (Rückfragen beim Schließen).
    PMenu {
        id: tabMenu
        objectName: "readerTabMenu"
        property string key: ""
        property string path: ""
        property int row: -1
        PMenuItem {
            objectName: "tabMenuClose"
            text: "Schließen"
            iconName: "dismiss"
            onTriggered: { var key = tabMenu.key; tabMenu.afterClose = function() { Reader.closeTab(key) } }
        }
        PMenuItem {
            objectName: "tabMenuCloseOthers"
            text: "Andere Tabs schließen"
            iconName: "dismiss_circle"
            enabled: Reader.tabs.count > 1
            onTriggered: { var key = tabMenu.key; tabMenu.afterClose = function() { Reader.closeOtherTabs(key) } }
        }
        PMenuItem {
            objectName: "tabMenuCloseRight"
            text: "Tabs rechts schließen"
            iconName: "arrow_next"
            enabled: tabMenu.row >= 0 && tabMenu.row < Reader.tabs.count - 1
            onTriggered: { var key = tabMenu.key; tabMenu.afterClose = function() { Reader.closeTabsRight(key) } }
        }
        PMenuItem {
            objectName: "tabMenuCopyPath"
            text: "Pfad kopieren"
            iconName: "copy"
            enabled: tabMenu.path !== ""
            onTriggered: App.copyPath(tabMenu.path)
        }
        PMenuItem {
            objectName: "tabMenuShowFolder"
            text: "Im Ordner anzeigen"
            iconName: "folder_open"
            enabled: tabMenu.path !== ""
            onTriggered: { var path = tabMenu.path; tabMenu.afterClose = function() { Reader.showInFolder(path) } }
        }
        T.MenuSeparator {
            topPadding: 4
            bottomPadding: 4
            contentItem: Rectangle { implicitWidth: 180; implicitHeight: 1; color: Theme.divider }
        }
        PMenuItem {
            objectName: "tabMenuReopen"
            text: "Geschlossenen Tab wieder öffnen"
            iconName: "arrow_undo"
            enabled: Reader.canReopen
            onTriggered: tabMenu.afterClose = function() { Reader.reopenClosed() }
        }
    }
}
