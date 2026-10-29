import QtQuick
import QtMultimedia
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Videos und Töne beim Vorführen (seit 5.0 Beta 6): je Video oder Ton der gezeigten Folie ein Spieler an seiner
// Stelle auf der Folie. Beide starten von selbst; ein Klick auf ein Video hält es an bzw. spielt weiter (statt
// weiterzublättern). Eigene Datei, damit die Präsentationsansicht auch ohne Qt Multimedia lädt.
Item {
    id: root
    objectName: "slideShowMedia"
    property var doc: null
    readonly property var entries: doc ? doc.media.filter(function(entry) { return entry.part === doc.presentIndex && entry.path !== "" }) : []

    Repeater {
        model: root.entries
        Item {
            id: clip
            required property var modelData
            required property int index
            objectName: "slideShowMedia_" + index
            readonly property bool playing: player.playbackState === MediaPlayer.PlayingState
            x: modelData.x * root.width
            y: modelData.y * root.height
            width: modelData.w * root.width
            height: modelData.h * root.height

            MediaPlayer {
                id: player
                source: "file:///" + String(clip.modelData.path).replace(/^\/+/, "")
                loops: clip.modelData.loop ? MediaPlayer.Infinite : 1
                audioOutput: AudioOutput {}
                videoOutput: clip.modelData.audio ? null : output
                Component.onCompleted: play()
            }
            Rectangle {
                anchors.fill: parent
                visible: !clip.modelData.audio
                color: "#000000"
            }
            VideoOutput {
                id: output
                anchors.fill: parent
                visible: !clip.modelData.audio
                fillMode: VideoOutput.PreserveAspectFit
            }
            // Angehalten: Zeichen in der Mitte
            Rectangle {
                anchors.centerIn: parent
                visible: !clip.modelData.audio && !clip.playing
                width: 56
                height: 56
                radius: 28
                color: "#99000000"
                PIcon { anchors.centerIn: parent; name: "play"; color: "#FFFFFF"; size: 24 }
            }
            MouseArea {
                anchors.fill: parent
                enabled: !clip.modelData.audio
                cursorShape: Qt.PointingHandCursor
                onClicked: clip.playing ? player.pause() : player.play()
            }
        }
    }
}
