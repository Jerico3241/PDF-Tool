import QtQuick
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// 3D-Tab-Übersicht (Strg+Tab, seit 5.0 Beta 10, Entwurf »10-tab-uebersicht-3d«): Strg+Tab wechselt sofort zum nächsten
// Dokument; solange Strg gedrückt bleibt, drehen sich alle offenen Dokumente als Karussell vorbei (mit Bild der Seite,
// soweit schon gesehen, und Spiegelung am Boden). Loslassen schließt die Übersicht, Entf schließt das Dokument, Esc
// und ein Klick daneben schließen sie ebenfalls, ein Klick auf eine Karte öffnet das Dokument.
Item {
    id: switcher
    objectName: "tabSwitcher"
    property Item source: null          // Bereich, dessen Bild die Karte des aktiven Dokuments zeigt
    property bool shown: false
    property bool keepOpen: false       // offen halten ohne Strg (Bildschirmfotos, Tests)
    property var shots: ({})            // Schlüssel -> Ergebnis von grabToImage (hält das Bild am Leben)
    property size shotSize: Qt.size(0, 0)  // Größe der Bilder (halbe Größe des Bereichs)
    readonly property int current: { Reader.tabs.count; return Math.max(0, Reader.tabs.indexOf(Reader.currentKey)) }
    property real spin: current          // gleitet zum aktiven Dokument
    Behavior on spin { enabled: Motion.moves; NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    visible: opacity > 0.01
    opacity: shown ? 1 : 0
    Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.normal; easing.type: Motion.decelerate } }

    function step(offset) {
        if (Reader.tabs.count < 2) {
            Reader.activateIndex(offset)
            return
        }
        Reader.activateIndex(offset)
        shown = true
        poll.restart()
    }
    function close() {
        shown = false
        poll.stop()
    }
    function snap(key) {
        if (!source || key === "" || source.width <= 0 || source.height <= 0)
            return
        switcher.shotSize = Qt.size(Math.round(source.width / 2), Math.round(source.height / 2))
        source.grabToImage(function(result) {
            var map = Object.assign({}, switcher.shots)
            map[key] = result
            switcher.shots = map
        }, switcher.shotSize)
    }

    Connections {
        target: App
        function onTabSwitchRequested(offset) { switcher.step(offset) }
    }
    // Loslassen von Strg: die Übersicht schließt (das Dokument ist schon gewechselt)
    Timer {
        id: poll
        interval: 60
        repeat: true
        onTriggered: if (!App.ctrlHeld() && !switcher.keepOpen) switcher.close()
    }
    // Bild des Dokuments: kurz nach jedem Wechsel (wenn es fertig gezeichnet ist) – so zeigt jede Karte das Dokument,
    // wie man es zuletzt gesehen hat. Ein Bild vor dem Wechsel geht nicht: grabToImage zeichnet erst im nächsten Bild.
    Timer { id: snapLater; interval: 700; onTriggered: switcher.snap(Reader.currentKey) }
    Connections {
        target: Reader
        function onCurrentKeyChanged() { snapLater.restart() }
    }

    // Hintergrund: abgedunkelt, mit sanftem Licht in der Mitte
    Rectangle {
        anchors.fill: parent
        color: Theme.neon ? "#F2080A0F" : "#EB0B0E14"
    }
    MouseArea {
        anchors.fill: parent
        enabled: switcher.shown
        onClicked: switcher.close()
        onWheel: (wheel) => switcher.step(wheel.angleDelta.y < 0 ? 1 : -1)
    }
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height * 0.12
        spacing: 8
        PText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: I18n.tr("Offene Dokumente", I18n.revision)
            textStyle: "title"
            color: "#F2F5FA"
        }
        PText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: I18n.tr("Strg+Tab weiter · Loslassen öffnet · Entf schließt", I18n.revision)
            color: "#B9C1CE"
        }
    }

    // Karussell
    Item {
        id: stage
        anchors.fill: parent
        readonly property real cardWidth: Math.min(460, width * 0.24)
        readonly property real cardHeight: cardWidth * 1.27
        readonly property real centerY: height * 0.56
        Repeater {
            model: Reader.tabs
            delegate: Item {
                id: card
                required property int index
                required property string key
                required property string name
                required property string kind
                readonly property real offset: index - switcher.spin
                readonly property real distance: Math.abs(offset)
                readonly property bool active: index === switcher.current
                objectName: "tabSwitcherCard_" + index
                visible: distance < 3.2
                width: stage.cardWidth
                height: stage.cardHeight
                x: stage.width / 2 - width / 2 + Math.sign(offset) * Math.min(distance, 1) * width * 0.78 + Math.sign(offset) * Math.max(0, distance - 1) * width * 0.62
                y: stage.centerY - height / 2
                z: 100 - distance * 10
                scale: 1 - Math.min(distance, 3) * 0.1
                opacity: 1 - Math.max(0, distance - 2) * 0.8
                transform: Rotation {
                    origin.x: card.width / 2
                    origin.y: card.height / 2
                    axis { x: 0; y: 1; z: 0 }
                    angle: -Math.max(-1, Math.min(1, card.offset)) * 28
                }

                // Schein um die gewählte Karte
                Repeater {
                    model: card.active ? 5 : 0
                    Rectangle {
                        required property int index
                        anchors.fill: parent
                        anchors.margins: -(index + 1) * 3
                        radius: 16 + (index + 1) * 3
                        color: "transparent"
                        border.width: 3
                        border.color: FileKinds.color(card.kind)
                        opacity: 0.22 * (1 - index / 5)
                    }
                }
                Rectangle {
                    id: face
                    anchors.fill: parent
                    radius: 16
                    color: "#F4F6F9"
                    border.width: card.active ? 2 : 1
                    border.color: card.active ? FileKinds.color(card.kind) : "#2A3140"
                    clip: true
                    Rectangle {
                        id: head
                        width: parent.width
                        height: 54
                        radius: 16
                        color: "#141821"
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 16; color: parent.color }
                        Rectangle {
                            id: tile
                            x: 16
                            anchors.verticalCenter: parent.verticalCenter
                            width: 28
                            height: 28
                            radius: 7
                            gradient: Gradient {
                                GradientStop { position: 0; color: FileKinds.color(card.kind) }
                                GradientStop { position: 1; color: FileKinds.deep(card.kind) }
                            }
                            Image {
                                anchors.centerIn: parent
                                source: FileKinds.whiteImage(card.kind)
                                sourceSize: Qt.size(16, 16)
                            }
                        }
                        Text {
                            anchors.left: tile.right
                            anchors.leftMargin: 12
                            anchors.right: parent.right
                            anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            text: card.name
                            elide: Text.ElideMiddle
                            color: "#F2F5FA"
                            font: Typography.bodyStrong
                        }
                    }
                    // Bild des Dokuments: nur der Dokumentbereich (ohne Leisten oben), mittig zugeschnitten
                    Item {
                        id: shotArea
                        anchors.top: head.bottom
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.margins: 1
                        clip: true
                        readonly property real cut: Math.min(switcher.shotSize.height * 0.3, 80)   // Leisten (halbe Größe)
                        readonly property real zoom: height / Math.max(1, switcher.shotSize.height - cut - 20)
                        Image {
                            id: shotImage
                            width: switcher.shotSize.width * shotArea.zoom
                            height: switcher.shotSize.height * shotArea.zoom
                            x: (shotArea.width - width) / 2
                            y: -shotArea.cut * shotArea.zoom
                            source: switcher.shots[card.key] ? switcher.shots[card.key].url : ""
                            visible: status === Image.Ready
                        }
                    }
                    // Noch kein Bild: großes Symbol der Dateiart auf Papier
                    Image {
                        anchors.centerIn: shotArea
                        visible: !shotImage.visible
                        source: FileKinds.image(card.kind, 48)
                        sourceSize: Qt.size(64, 64)
                        opacity: 0.5
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: switcher.shown
                        onClicked: { Reader.activate(card.key); switcher.close() }
                    }
                }
                // Spiegelung am Boden
                ShaderEffectSource {
                    sourceItem: face
                    width: face.width
                    height: face.height * 0.22
                    y: face.height + 10
                    sourceRect: Qt.rect(0, face.height * 0.78, face.width, face.height * 0.22)
                    textureMirroring: ShaderEffectSource.NoMirroring  // kopfüber: Spiegelbild
                    opacity: 0.10
                    live: switcher.visible
                    Rectangle {
                        anchors.fill: parent
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#000B0E14" }
                            GradientStop { position: 1.0; color: "#FF0B0E14" }
                        }
                    }
                }
            }
        }
    }

    Shortcut { sequences: ["Esc"]; enabled: switcher.shown; onActivated: switcher.close() }
    Shortcut { sequences: ["Del"]; enabled: switcher.shown; onActivated: Reader.closeTab(Reader.currentKey) }
}
