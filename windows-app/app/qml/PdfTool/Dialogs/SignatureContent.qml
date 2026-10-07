import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Unterschrift erstellen«: mit Maus, Stift oder Finger zeichnen – oder ein Bild einlesen (Scan, Foto; der
// Hintergrund wird durchsichtig). Auf Wunsch nur auf diesem PC speichern. Eine Unterschrift ist keine
// digitale Signatur.
ColumnLayout {
    id: root
    objectName: "signatureContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string mode: "draw"  // draw oder image
    property var strokes: []
    property string ink: "#162E78"
    property var picked: ({})     // {preview, data, aspect} aus dem eingelesenen Bild
    property string pickError: ""
    readonly property real pen: 2.6
    readonly property bool storeFull: (data_.stored || 0) >= (data_.limit || 6)
    readonly property bool acceptable: mode === "draw" ? strokes.length > 0 : picked.data !== undefined
    function collect() {
        return { "mode": mode, "strokes": strokes, "pen": pen, "color": ink, "image": picked.data || {}, "save": saveBox.checked && !storeFull, "label": labelField.text }
    }
    function clear() {
        strokes = []
        pad.requestPaint()
    }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        mode = "draw"
        strokes = []
        picked = {}
        pickError = ""
        saveBox.checked = false
        labelField.text = ""
        pad.requestPaint()
    }

    RowLayout {
        spacing: 4
        PButton { objectName: "signatureDraw"; toggle: true; checked: root.mode === "draw"; iconName: "pen"; text: "Zeichnen"; onClicked: root.mode = "draw" }
        PButton { objectName: "signatureImage"; toggle: true; checked: root.mode === "image"; iconName: "image"; text: "Bild verwenden"; onClicked: root.mode = "image" }
        Item { Layout.fillWidth: true }
        Row {
            visible: root.mode === "draw"
            spacing: 6
            PSwatch { size: 24; swatchColor: "#162E78"; tip: "Blau"; selected: root.ink === "#162E78"; onClicked: { root.ink = "#162E78"; pad.requestPaint() } }
            PSwatch { size: 24; swatchColor: "#141414"; tip: "Schwarz"; selected: root.ink === "#141414"; onClicked: { root.ink = "#141414"; pad.requestPaint() } }
        }
        PButton { visible: root.mode === "draw"; kind: "subtle"; iconName: "eraser"; text: "Neu beginnen"; enabled: root.strokes.length > 0; onClicked: root.clear() }
    }

    // Zeichenfläche: Papierweiß (auch im dunklen Design), Linie zum Unterschreiben
    Rectangle {
        id: paper
        Layout.fillWidth: true
        Layout.topMargin: 8
        implicitHeight: 190
        radius: Metrics.radiusControl
        color: Theme.paper
        border.color: Theme.controlStroke
        clip: true
        Rectangle { x: 24; width: parent.width - 48; y: parent.height - 48; height: 1; color: "#B8B8B8" }
        Text {
            x: 24
            y: parent.height - 40
            visible: root.mode === "draw" && root.strokes.length === 0
            text: "Hier unterschreiben"
            color: "#8A8A8A"
            font: Typography.caption
        }
        Canvas {
            id: pad
            objectName: "signaturePad"
            anchors.fill: parent
            visible: root.mode === "draw"
            renderStrategy: Canvas.Cooperative
            property var current: null
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.strokeStyle = root.ink
                ctx.lineWidth = root.pen
                ctx.lineCap = "round"
                ctx.lineJoin = "round"
                var all = current ? root.strokes.concat([current]) : root.strokes
                for (var s = 0; s < all.length; ++s) {
                    var points = all[s]
                    if (points.length === 0) continue
                    ctx.beginPath()
                    ctx.moveTo(points[0][0], points[0][1])
                    if (points.length === 1) ctx.lineTo(points[0][0] + 0.6, points[0][1])
                    for (var i = 1; i < points.length - 1; ++i) {
                        var mx = (points[i][0] + points[i + 1][0]) / 2, my = (points[i][1] + points[i + 1][1]) / 2
                        ctx.quadraticCurveTo(points[i][0], points[i][1], mx, my)
                    }
                    if (points.length > 1) ctx.lineTo(points[points.length - 1][0], points[points.length - 1][1])
                    ctx.stroke()
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.CrossCursor
                preventStealing: true
                onPressed: (mouse) => { pad.current = [[mouse.x, mouse.y]]; pad.requestPaint() }
                onPositionChanged: (mouse) => {
                    if (!pad.current) return
                    var last = pad.current[pad.current.length - 1]
                    if (Math.abs(last[0] - mouse.x) + Math.abs(last[1] - mouse.y) < 1.2) return
                    pad.current.push([Math.max(0, Math.min(pad.width, mouse.x)), Math.max(0, Math.min(pad.height, mouse.y))])
                    pad.requestPaint()
                }
                onReleased: {
                    if (pad.current && pad.current.length > 0) root.strokes = root.strokes.concat([pad.current])
                    pad.current = null
                    pad.requestPaint()
                }
            }
        }
        // Bild: Vorschau oder Hinweis
        Image {
            objectName: "signaturePicked"
            anchors.fill: parent
            anchors.margins: 16
            visible: root.mode === "image" && root.picked.preview !== undefined
            source: root.picked.preview || ""
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
        }
        Column {
            anchors.centerIn: parent
            visible: root.mode === "image" && root.picked.preview === undefined
            spacing: 8
            PButton { anchors.horizontalCenter: parent.horizontalCenter; objectName: "signaturePick"; iconName: "image_add"; text: "Bild auswählen …"; onClicked: {
                    var result = Reader.current ? Reader.current.pickSignatureImage() : ({})
                    if (result.error) { root.pickError = result.error; return }
                    if (result.data) { root.picked = result; root.pickError = "" }
                } }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "PNG oder JPEG, am besten auf weißem Papier"; color: "#6E6E6E"; font: Typography.caption }
        }
    }
    RowLayout {
        Layout.fillWidth: true
        visible: root.mode === "image" && (root.picked.preview !== undefined || root.pickError !== "")
        PText { Layout.fillWidth: true; wrap: true; tone: root.pickError !== "" ? "warning" : "secondary"; textStyle: "caption"; text: root.pickError !== "" ? root.pickError : "Der Hintergrund wurde entfernt; die Tinte behält ihre Farbe." }
        PButton { kind: "subtle"; text: "Anderes Bild …"; onClicked: { root.picked = ({}); root.pickError = "" } }
    }

    PCheckBox {
        id: saveBox
        objectName: "signatureSave"
        Layout.topMargin: 12
        Layout.fillWidth: true
        enabled: !root.storeFull
        text: root.storeFull ? "Speichern nicht möglich – es sind schon " + (root.data_.limit || 6) + " Unterschriften gespeichert." : "Für später auf diesem PC speichern"
    }
    PTextField {
        id: labelField
        Layout.fillWidth: true
        Layout.leftMargin: 28
        visible: saveBox.checked
        label: "Name der Unterschrift"
        placeholderText: "z. B. Unterschrift oder Kürzel"
        maximumLength: 40
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 8
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Gespeicherte Unterschriften bleiben nur auf diesem PC (nicht in Sicherungen oder Support-Paketen) und lassen sich jederzeit löschen. Eine sichtbare Unterschrift ist keine digitale Signatur."
    }
}
