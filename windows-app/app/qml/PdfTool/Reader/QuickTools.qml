import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Schnellwerkzeuge (seit 4.0, wie bei Acrobat): eine senkrechte Leiste am linken Rand der Dokumentfläche mit
// den häufigsten Werkzeugen – Auswählen, Verschieben, Kommentieren, Zeichnen, Text hinzufügen, Text bearbeiten,
// Objekt bearbeiten, Unterschreiben – und unten »Alle Werkzeuge«. Kommentieren, Zeichnen und Unterschreiben merken sich das zuletzt
// benutzte Werkzeug; das kleine Dreieck in der Ecke (oder ein Rechtsklick) wählt ein anderes. Ein erneuter Klick auf
// das gewählte Werkzeug zeigt seine Einstellungen (Farbe, Stärke …); Esc beendet es – zurück zu »Auswählen«. Ist ein Werkzeug aus »Alle Werkzeuge« aktiv
// (Bilder, Schwärzen, Formular …), ist »Alle Werkzeuge« markiert. Die Akzentmarkierung links gleitet zum gewählten Werkzeug.
Rectangle {
    id: root
    objectName: "readerQuickTools"
    property var doc: null
    property bool allToolsOpen: false
    signal allToolsRequested()
    signal settingsRequested()  // erneuter Klick auf das gewählte Werkzeug: seine Einstellungen zeigen/verbergen
    readonly property string tool: doc ? doc.tool : "select"
    readonly property var commentTools: ["highlight", "underline", "strikeout", "note", "textbox"]
    readonly property var drawTools: ["ink", "rect", "ellipse", "line", "arrow"]
    readonly property var signTools: ["signature", "stamp"]
    // Werkzeuge mit eigener Schaltfläche in dieser Leiste – alle anderen markieren »Alle Werkzeuge«
    readonly property bool quickTool: tool === "select" || tool === "hand" || tool === "addText" || tool === "editText" || tool === "objects"
        || commentTools.indexOf(tool) >= 0 || drawTools.indexOf(tool) >= 0 || signTools.indexOf(tool) >= 0
    property string lastComment: "highlight"
    property string lastDraw: "ink"
    property string lastSign: "signature"
    onToolChanged: {
        if (commentTools.indexOf(tool) >= 0) lastComment = tool
        if (drawTools.indexOf(tool) >= 0) lastDraw = tool
        if (signTools.indexOf(tool) >= 0) lastSign = tool
    }

    function toolIcon(name) {
        switch (name) {
        case "highlight": return "highlight"
        case "underline": return "text_underline"
        case "strikeout": return "text_strikethrough"
        case "note": return "comment"
        case "textbox": return "textbox"
        case "ink": return "pen"
        case "rect": return "square"
        case "ellipse": return "circle"
        case "line": return "line"
        case "arrow": return "arrow_up_right"
        case "signature": return "signature"
        case "stamp": return "document_checkmark"
        default: return "cursor"
        }
    }
    function toolName(name) {
        switch (name) {
        case "highlight": return "Markieren"
        case "underline": return "Unterstreichen"
        case "strikeout": return "Durchstreichen"
        case "note": return "Notiz"
        case "textbox": return "Textfeld"
        case "ink": return "Freihand"
        case "rect": return "Rechteck"
        case "ellipse": return "Ellipse"
        case "line": return "Linie"
        case "arrow": return "Pfeil"
        case "signature": return "Unterschrift"
        case "stamp": return "Stempel"
        default: return name
        }
    }
    function chooseTool(key) {
        if (!root.doc) return
        if (root.tool === key) {
            if (key !== "select" && key !== "hand") root.settingsRequested()
            return
        }
        root.doc.setTool(key)
    }

    implicitWidth: Metrics.readerQuickToolsWidth
    implicitHeight: column.implicitHeight + 2 * Metrics.s4
    radius: Metrics.radiusCard
    color: Theme.layer
    border.color: Theme.divider
    enabled: doc !== null
    Accessible.role: Accessible.ToolBar
    Accessible.name: "Schnellwerkzeuge"

    component Separator: Rectangle {
        Layout.preferredWidth: 20
        Layout.preferredHeight: 1
        Layout.topMargin: Metrics.s4
        Layout.bottomMargin: Metrics.s4
        Layout.alignment: Qt.AlignHCenter
        color: Theme.divider
    }
    property Item activeTool: null
    component ToolButton: PIconButton {
        id: toolButton
        property string toolKey: ""
        toggle: true
        checked: root.tool === toolKey
        onCheckedChanged: if (checked) root.activeTool = toolButton
        Component.onCompleted: if (checked) root.activeTool = toolButton
        onClicked: root.chooseTool(toolKey)
        Accessible.role: Accessible.RadioButton
    }
    // Werkzeug mit Auswahl (Kommentieren, Zeichnen, Unterschreiben): kleines Dreieck unten rechts in der
    // Schaltfläche wie bei Acrobat – ein Klick darauf oder ein Rechtsklick auf die Schaltfläche öffnet die Auswahl.
    // So stehen alle Schaltflächen in einer Spalte, gleich breit und mittig.
    component MenuCorner: T.AbstractButton {
        id: corner
        property var menu: null
        property string tip: ""
        width: 14
        height: 14
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        hoverEnabled: true
        focusPolicy: Qt.NoFocus
        Accessible.role: Accessible.ButtonMenu
        Accessible.name: tip
        onClicked: menu.popup(parent, parent.width + Metrics.s4, 0)
        contentItem: Item {
            Canvas {
                id: triangle
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 3
                width: 5
                height: 5
                property color fill: corner.hovered ? Theme.textPrimary : Theme.textSecondary
                onFillChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.fillStyle = fill
                    ctx.beginPath()
                    ctx.moveTo(width, 0)
                    ctx.lineTo(width, height)
                    ctx.lineTo(0, height)
                    ctx.closePath()
                    ctx.fill()
                }
            }
        }
        PToolTip { text: corner.tip; visible: corner.hovered && !corner.pressed; x: corner.width + Metrics.s8; y: (corner.height - implicitHeight) / 2 }
    }
    component MenuTool: ToolButton {
        id: menuTool
        property var menu: null
        TapHandler { acceptedButtons: Qt.RightButton; onTapped: menuTool.menu.popup(menuTool, menuTool.width + Metrics.s4, 0) }
    }

    ColumnLayout {
        id: column
        anchors.horizontalCenter: parent.horizontalCenter
        y: Metrics.s4
        spacing: 2

        ToolButton { objectName: "readerToolSelect"; toolKey: "select"; iconName: "cursor"; tip: "Auswählen: Text markieren und kopieren, Kommentare verschieben" }
        ToolButton { objectName: "readerToolHand"; toolKey: "hand"; iconName: "hand_left"; tip: "Verschieben: das Dokument mit gedrückter Maustaste bewegen" }
        Separator {}
        MenuTool {
            objectName: "readerToolComment"; toolKey: root.lastComment; iconName: root.toolIcon(root.lastComment); menu: commentMenu
            tip: "Kommentieren: " + root.toolName(root.lastComment) + " (Auswahl: Dreieck oder Rechtsklick)"
            MenuCorner { objectName: "readerCommentMenu"; menu: commentMenu; tip: "Kommentarwerkzeug wählen" }
        }
        MenuTool {
            objectName: "readerToolDraw"; toolKey: root.lastDraw; iconName: root.toolIcon(root.lastDraw); menu: drawMenu
            tip: "Zeichnen: " + root.toolName(root.lastDraw) + " (Auswahl: Dreieck oder Rechtsklick)"
            MenuCorner { objectName: "readerDrawMenu"; menu: drawMenu; tip: "Zeichenwerkzeug wählen" }
        }
        ToolButton { objectName: "readerToolAddText"; toolKey: "addText"; iconName: "text_add"; tip: "Text hinzufügen" }
        ToolButton { objectName: "readerToolEditText"; toolKey: "editText"; iconName: "text_edit_style"; tip: "Text bearbeiten: Absätze mit Cursor ändern, ergänzen, umbrechen" }
        ToolButton { objectName: "readerToolObjects"; toolKey: "objects"; iconName: "select_object"; tip: "Objekt bearbeiten: Text und andere PDF-Inhalte einzeln auswählen und bearbeiten." }
        MenuTool {
            objectName: "readerToolSign"; toolKey: root.lastSign; iconName: root.toolIcon(root.lastSign); menu: signMenu
            tip: root.lastSign === "stamp" ? "Stempel setzen (GENEHMIGT, ENTWURF, eigener Text …)" : "Unterschreiben: Unterschrift zeichnen oder einlesen und auf die Seite setzen (keine digitale Signatur)"
            MenuCorner { objectName: "readerSignMenu"; menu: signMenu; tip: "Unterschrift oder Stempel wählen" }
        }
        Separator {}
        PIconButton {
            id: allButton
            objectName: "readerQuickAllTools"
            iconName: "apps"
            tip: "Alle Werkzeuge"
            toggle: true
            checked: root.allToolsOpen || (root.doc !== null && !root.quickTool)
            onCheckedChanged: if (checked && !root.quickTool) root.activeTool = allButton
            Component.onCompleted: if (checked && !root.quickTool) root.activeTool = allButton
            onClicked: root.allToolsRequested()
        }
    }
    Connections {
        target: root
        function onQuickToolChanged() { if (!root.quickTool && allButton.checked) root.activeTool = allButton }
    }
    // Gewähltes Werkzeug: Akzentstrich innen links in der Schaltfläche, gleitet zum neu gewählten Werkzeug
    Rectangle {
        id: toolIndicator
        objectName: "readerToolIndicator"
        readonly property Item target: root.activeTool !== null && root.activeTool.visible && root.activeTool.checked ? root.activeTool : null
        width: 4
        height: 18
        radius: 2  // halbe Breite: runde Enden
        color: Theme.accent
        x: column.x + 1  // innen am linken Rand der gewählten Schaltfläche, nie über dem Rand der Leiste
        y: target ? (target.y, target.parent.y, column.y, root.height, target.mapToItem(root, 0, target.height / 2).y - height / 2) : y
        opacity: target ? 1 : 0
        Behavior on y { enabled: Motion.moves && toolIndicator.opacity > 0.5; NumberAnimation { duration: Motion.indicator; easing.type: Motion.decelerate } }
        Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fast } }
    }

    PMenu {
        id: commentMenu
        objectName: "readerCommentToolMenu"
        PMenuItem { text: "Markieren"; iconName: "highlight"; onTriggered: root.doc.setTool("highlight") }
        PMenuItem { text: "Unterstreichen"; iconName: "text_underline"; onTriggered: root.doc.setTool("underline") }
        PMenuItem { text: "Durchstreichen"; iconName: "text_strikethrough"; onTriggered: root.doc.setTool("strikeout") }
        PMenuItem { text: "Notiz"; iconName: "comment"; onTriggered: root.doc.setTool("note") }
        PMenuItem { text: "Textfeld"; iconName: "textbox"; onTriggered: root.doc.setTool("textbox") }
    }
    PMenu {
        id: drawMenu
        objectName: "readerDrawToolMenu"
        PMenuItem { text: "Freihand (auch für eine sichtbare Unterschrift)"; iconName: "pen"; onTriggered: root.doc.setTool("ink") }
        PMenuItem { text: "Rechteck"; iconName: "square"; onTriggered: root.doc.setTool("rect") }
        PMenuItem { text: "Ellipse"; iconName: "circle"; onTriggered: root.doc.setTool("ellipse") }
        PMenuItem { text: "Linie"; iconName: "line"; onTriggered: root.doc.setTool("line") }
        PMenuItem { text: "Pfeil"; iconName: "arrow_up_right"; onTriggered: root.doc.setTool("arrow") }
    }
    PMenu {
        id: signMenu
        objectName: "readerSignToolMenu"
        PMenuItem { objectName: "readerToolSignature"; text: "Unterschrift setzen"; iconName: "signature"; onTriggered: root.doc.setTool("signature") }
        PMenuItem { text: "Neue Unterschrift …"; iconName: "pen"; onTriggered: { var d = root.doc; signMenu.afterClose = function() { d.newSignature() } } }
        PMenuItem { objectName: "readerToolStamp"; text: "Stempel"; iconName: "document_checkmark"; onTriggered: root.doc.setTool("stamp") }
    }
}
