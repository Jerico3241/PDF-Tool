import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »KI-Assistent einrichten«: Sprachmodell wählen – mit Größe, Bedarf an Arbeitsspeicher und Empfehlung für diesen PC.
// Geladen wird erst nach »Herunterladen«, von Hugging Face, mit Prüfung der Prüfsumme. Alles bleibt lokal.
ColumnLayout {
    id: root
    objectName: "assistantSetupContent"
    property var request: ({})
    readonly property var data_: request.data || ({})
    property string choice: ""
    readonly property bool acceptable: choice !== ""
    function collect() { return { "model": choice } }
    spacing: 0

    property var shownId: undefined
    onRequestChanged: {
        if (request.id === undefined || request.id === shownId) return
        shownId = request.id
        choice = (request.data || {}).choice || ""
    }

    PText {
        Layout.fillWidth: true
        wrap: true
        text: "Der Assistent beantwortet Fragen zum geöffneten PDF und fasst Dokumente zusammen – vollständig auf diesem PC. Dafür braucht er ein Sprachmodell, das einmal geladen wird."
    }
    PFieldLabel { text: "Sprachmodell" }
    Repeater {
        model: root.data_.models || []
        Rectangle {
            required property var modelData
            objectName: "assistantModel_" + modelData.key
            Layout.fillWidth: true
            Layout.bottomMargin: 6
            implicitHeight: modelRow.implicitHeight + 20
            radius: Metrics.radiusControl
            color: root.choice === modelData.key ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.16 : 0.08) : Theme.surfaceSecondary
            border.color: root.choice === modelData.key ? Theme.accent : Theme.controlStroke
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.choice = modelData.key }
            RowLayout {
                id: modelRow
                anchors.fill: parent
                anchors.margins: 10
                spacing: 10
                PRadioButton { Layout.alignment: Qt.AlignTop; checked: root.choice === modelData.key; onClicked: root.choice = modelData.key; text: "" }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    RowLayout {
                        spacing: 8
                        PText { text: modelData.name; textStyle: "bodyStrong" }
                        PBadge { visible: modelData.recommended; text: "Empfohlen für diesen PC"; tone: "accent" }
                        PBadge { visible: modelData.installed; text: "Eingerichtet"; tone: "success" }
                    }
                    PText { Layout.fillWidth: true; wrap: true; text: modelData.description; tone: "secondary" }
                    PText {
                        Layout.fillWidth: true
                        wrap: true
                        textStyle: "caption"
                        tone: "secondary"
                        text: "Download " + modelData.size + " · braucht beim Antworten rund " + modelData.memory + " Arbeitsspeicher" + (modelData.resume !== "" ? " · " + modelData.resume + " schon geladen (wird fortgesetzt)" : "")
                    }
                }
            }
        }
    }
    PText {
        objectName: "assistantSetupSystem"
        Layout.fillWidth: true
        Layout.topMargin: 4
        wrap: true
        textStyle: "caption"
        tone: root.data_.lowMemory ? "warning" : "secondary"
        text: (root.data_.ram ? "Arbeitsspeicher dieses PCs: " + root.data_.ram + " · " : "") + "frei auf dem Laufwerk: " + (root.data_.free || "–")
              + (root.data_.lowMemory ? " – wenig Arbeitsspeicher: Antworten können sehr lange dauern." : "")
    }
    PText {
        Layout.fillWidth: true
        Layout.topMargin: 10
        wrap: true
        textStyle: "caption"
        tone: "secondary"
        text: "Quelle: Hugging Face (Modelle Qwen3.5, Apache-Lizenz 2.0). PDF Tool lädt die Datei über HTTPS und prüft ihre Prüfsumme, bevor sie verwendet wird. Dokumente, Fragen und Antworten verlassen diesen PC nicht. Das Modell lässt sich in den Einstellungen jederzeit wieder entfernen."
    }
}
