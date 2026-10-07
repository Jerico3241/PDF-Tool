import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// KI-Assistent zum geöffneten PDF: Fragen stellen, Dokument zusammenfassen. Antworten nennen die Seiten, auf die sie
// sich stützen – ein Klick springt dorthin. Das Gespräch gehört zum Tab und lebt nur im Arbeitsspeicher.
// Ohne Sprachmodell: »Einrichten …« (wie in den Einstellungen); während des Downloads dessen Fortschritt.
// Kopf (Titel, Schließen) und Breite kommen von der rechten Seitenleiste (RightPanel).
ColumnLayout {
    id: root
    objectName: "readerAssistantPanel"
    property var doc: null
    readonly property var conversation: Assistant.conversationModel
    readonly property string phase: Assistant.state
    readonly property bool ready: phase === "ready"
    readonly property bool loading: phase === "download" || phase === "verify"
    spacing: 0

    function send(question) {
        const text = String(question || "").trim()
        if (text === "" || Assistant.busy || root.doc === null) return false
        flick.stick = true
        Assistant.ask(text)
        return true
    }

    // Nicht eingerichtet oder Download läuft
    Item {
        objectName: "readerAssistantSetup"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: !root.ready
        Column {
            width: Math.min(parent.width - 2 * Metrics.s24, 240)
            x: (parent.width - width) / 2
            y: Math.max(Metrics.s24, parent.height * 0.16)
            spacing: Metrics.s8
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 48
                height: 48
                radius: 24
                color: Theme.subtleHover
                PIcon { anchors.centerIn: parent; name: "sparkle"; size: Metrics.iconSizeLarge; color: Theme.accentText }
            }
            Item { width: 1; height: Metrics.s4 }
            PText {
                width: parent.width
                text: root.loading ? "Sprachmodell wird geladen" : (Assistant.available ? "KI-Assistent einrichten" : "KI-Assistent nicht enthalten")
                textStyle: "bodyStrong"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            PText {
                objectName: "readerAssistantSetupText"
                width: parent.width
                text: !Assistant.available ? "Diese Installation enthält den KI-Assistenten nicht."
                      : root.loading ? Assistant.statusText
                      : "Fragen zum PDF beantworten und Dokumente zusammenfassen – vollständig auf diesem PC. Dafür wird einmal ein Sprachmodell geladen."
                tone: "secondary"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            Item { width: 1; height: Metrics.s4 }
            PButton {
                objectName: "readerAssistantSetupButton"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: Assistant.available && !root.loading
                kind: "accent"
                iconName: Assistant.partial !== "" ? "arrow_download" : ""
                text: Assistant.partial !== "" ? "Download fortsetzen" : "Einrichten …"
                onClicked: Assistant.partial !== "" ? Assistant.download(Assistant.partial) : Assistant.setup()
            }
            PProgressBar {
                objectName: "readerAssistantProgress"
                width: parent.width
                visible: root.loading
                value: Assistant.progress
                indeterminate: root.phase === "verify"
            }
            PText {
                width: parent.width
                visible: root.loading && Assistant.progressText !== ""
                text: Assistant.progressText
                textStyle: "caption"
                tone: "secondary"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            PButton {
                objectName: "readerAssistantPause"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: root.phase === "download"
                text: "Anhalten"
                tip: "Download anhalten – er lässt sich später fortsetzen"
                onClicked: Assistant.cancelDownload()
            }
        }
    }

    // Bereit, noch keine Frage: Vorschläge
    Item {
        objectName: "readerAssistantIntro"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.ready && root.conversation.count === 0
        Column {
            width: Math.min(parent.width - 2 * Metrics.s24, 240)
            x: (parent.width - width) / 2
            y: Math.max(Metrics.s24, parent.height * 0.12)
            spacing: Metrics.s8
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 48
                height: 48
                radius: 24
                color: Theme.subtleHover
                PIcon { anchors.centerIn: parent; name: "chat_sparkle"; size: Metrics.iconSizeLarge; color: Theme.accentText }
            }
            Item { width: 1; height: Metrics.s4 }
            PText { width: parent.width; text: "Fragen zu diesem PDF"; textStyle: "bodyStrong"; horizontalAlignment: Text.AlignHCenter; wrap: true }
            PText {
                width: parent.width
                text: "Der Assistent antwortet nur anhand dieses Dokuments und nennt die Seiten, auf die er sich stützt."
                tone: "secondary"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            Item { width: 1; height: Metrics.s8 }
            PButton {
                objectName: "readerAssistantSummarize"
                width: parent.width
                iconName: "text_bullet_list_square"
                text: "Dokument zusammenfassen"
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.summarize() }
            }
            Repeater {
                model: [
                    { label: "Fristen und Termine", question: "Welche Fristen und Termine nennt das Dokument?" },
                    { label: "Beträge und Kosten", question: "Welche Beträge und Kosten nennt das Dokument?" },
                    { label: "Beteiligte Personen und Firmen", question: "Welche Personen und Firmen sind beteiligt, und in welcher Rolle?" }
                ]
                PButton {
                    required property var modelData
                    width: parent.width
                    kind: "subtle"
                    iconName: "chat_sparkle"
                    text: modelData.label
                    tip: modelData.question
                    enabled: !Assistant.busy && root.doc !== null
                    onClicked: root.send(modelData.question)
                }
            }
        }
    }

    // Gespräch
    Flickable {
        id: flick
        objectName: "readerAssistantConversation"
        PWheelScroll { flickable: flick }
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: root.ready && root.conversation.count > 0
        clip: true
        contentWidth: width
        contentHeight: entries.implicitHeight + 2 * Metrics.s12
        boundsBehavior: Flickable.StopAtBounds
        T.ScrollBar.vertical: PScrollBar {}
        Accessible.role: Accessible.List
        Accessible.name: "Gespräch mit dem KI-Assistenten"
        // Am Ende bleiben, solange man dort ist: Eine wachsende Antwort bleibt sichtbar; wer nach oben scrollt,
        // liest dort ungestört weiter.
        readonly property real endY: Math.max(0, contentHeight - height)
        property bool stick: true
        property bool scrolling: false
        function toEnd() {
            scrolling = true
            contentY = endY
            scrolling = false
        }
        onContentYChanged: if (!scrolling) stick = contentY >= endY - 24
        onContentHeightChanged: if (stick) toEnd()
        onHeightChanged: if (stick) toEnd()

        ColumnLayout {
            id: entries
            x: Metrics.s12
            y: Metrics.s12
            width: flick.width - 2 * Metrics.s12
            spacing: Metrics.s16
            Repeater {
                model: root.conversation
                Item {
                    id: entry
                    required property string key
                    required property string kind
                    required property string text
                    required property string rich
                    required property bool pending
                    required property string note
                    required property var pages
                    Layout.fillWidth: true
                    implicitHeight: kind === "question" ? bubble.height : details.implicitHeight
                    Accessible.role: Accessible.ListItem
                    Accessible.name: (kind === "question" ? "Frage: " : "") + text

                    // Frage: rechts, in einer Blase
                    Rectangle {
                        id: bubble
                        visible: entry.kind === "question"
                        anchors.right: parent.right
                        width: Math.min(parent.width * 0.88, questionText.implicitWidth + 24)
                        height: questionText.implicitHeight + 16
                        radius: Metrics.radiusCard
                        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, Theme.dark ? 0.24 : 0.10)
                        PText {
                            id: questionText
                            objectName: "readerAssistantQuestion"
                            x: 12
                            y: 8
                            width: bubble.width - 24
                            text: entry.kind === "question" ? entry.text : ""
                            wrap: true
                        }
                    }

                    // Antwort, Fehler oder Hinweis
                    ColumnLayout {
                        id: details
                        visible: entry.kind !== "question"
                        width: parent.width
                        spacing: Metrics.s6
                        RowLayout {
                            visible: entry.kind === "answer"
                            spacing: Metrics.s6
                            PIcon { name: "sparkle"; size: 16; color: Theme.accentText }
                            PText { text: "KI-Assistent"; textStyle: "caption"; tone: "secondary" }
                        }
                        Text {
                            id: answerText
                            objectName: "readerAssistantAnswer"
                            Layout.fillWidth: true
                            visible: entry.kind === "answer" && entry.text !== ""
                            // ``rich`` ist maskiert und kennt nur fett, Stichpunkte und Seitenverweise (assistant.text.rich)
                            text: entry.rich
                            textFormat: Text.StyledText
                            wrapMode: Text.Wrap
                            font: Typography.body
                            color: Theme.textPrimary
                            linkColor: Theme.accentText
                            lineHeight: 1.1
                            onLinkActivated: (link) => {
                                if (link.indexOf("page:") === 0) Assistant.openPage(parseInt(link.slice(5)))
                            }
                            HoverHandler { cursorShape: answerText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
                            Accessible.role: Accessible.StaticText
                            Accessible.name: entry.text
                        }
                        RowLayout {
                            objectName: "readerAssistantPending"
                            visible: entry.pending
                            spacing: Metrics.s8
                            PProgressRing { size: 14; running: entry.pending && root.visible }
                            PText { Layout.fillWidth: true; text: entry.note; textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight }
                        }
                        PInfoBar {
                            objectName: "readerAssistantError"
                            Layout.fillWidth: true
                            visible: entry.kind === "error"
                            shown: entry.kind === "error"
                            topMargin: 0
                            severity: "error"
                            message: entry.kind === "error" ? entry.text : ""
                            closable: false
                        }
                        PText {
                            Layout.fillWidth: true
                            visible: entry.kind === "note" || (!entry.pending && entry.kind === "answer" && entry.note !== "")
                            text: entry.kind === "note" ? entry.text : entry.note
                            textStyle: "caption"
                            tone: "tertiary"
                            horizontalAlignment: entry.kind === "note" ? Text.AlignHCenter : Text.AlignLeft
                            wrap: true
                        }
                        Flow {
                            Layout.fillWidth: true
                            visible: entry.kind === "answer" && !entry.pending && entry.text !== ""
                            spacing: Metrics.s4
                            Repeater {
                                model: entry.pages
                                PButton {
                                    required property var modelData
                                    objectName: "readerAssistantPage"
                                    implicitHeight: 28
                                    leftPadding: 8
                                    rightPadding: 8
                                    text: "S. " + modelData
                                    tip: "Zur Seite " + modelData
                                    onClicked: Assistant.openPage(modelData)
                                }
                            }
                            PIconButton {
                                objectName: "readerAssistantCopy"
                                implicitWidth: 28
                                implicitHeight: 28
                                iconName: "copy"
                                tip: "Antwort kopieren"
                                onClicked: Assistant.copy(entry.key)
                            }
                        }
                    }
                }
            }
        }
    }

    // Eingabe
    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.divider; visible: root.ready }
    ColumnLayout {
        Layout.fillWidth: true
        Layout.margins: Metrics.s12
        visible: root.ready
        spacing: Metrics.s8
        RowLayout {
            Layout.fillWidth: true
            spacing: Metrics.s8
            PTextArea {
                id: input
                objectName: "readerAssistantInput"
                Layout.fillWidth: true
                minLines: 1
                maxLines: 5
                label: "Frage zum Dokument"
                placeholderText: "Frage zu diesem PDF …"
                enabled: root.doc !== null
                submitOnEnter: true
                onSubmitted: if (root.send(input.text)) input.text = ""
            }
            PIconButton {
                objectName: "readerAssistantSummarizeMore"
                Layout.alignment: Qt.AlignBottom
                visible: root.conversation.count > 0 && !Assistant.busy
                iconName: "text_bullet_list_square"
                tip: "Dokument zusammenfassen"
                enabled: root.doc !== null
                onClicked: { flick.stick = true; Assistant.summarize() }
            }
            PIconButton {
                objectName: "readerAssistantSend"
                Layout.alignment: Qt.AlignBottom
                visible: !Assistant.busy
                kind: "accent"
                iconName: "send"
                tip: "Frage senden (Eingabetaste)"
                enabled: input.text.trim() !== "" && root.doc !== null
                onClicked: if (root.send(input.text)) input.text = ""
            }
            PIconButton {
                objectName: "readerAssistantStop"
                Layout.alignment: Qt.AlignBottom
                visible: Assistant.busy
                iconName: "stop"
                tip: "Antwort anhalten"
                onClicked: Assistant.stop()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Metrics.s6
            PIcon { Layout.alignment: Qt.AlignTop; name: "shield_checkmark"; size: 14; color: Theme.textTertiary }
            PText {
                Layout.fillWidth: true
                text: "Läuft nur auf diesem PC. Antworten können Fehler enthalten – bitte auf den genannten Seiten prüfen."
                textStyle: "caption"
                tone: "tertiary"
                wrap: true
            }
        }
    }
}
