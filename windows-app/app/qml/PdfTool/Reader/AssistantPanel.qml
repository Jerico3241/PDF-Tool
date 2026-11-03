import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// KI-Assistent zum geöffneten PDF: Fragen stellen, Dokument zusammenfassen oder übersetzen (neues PDF). Antworten nennen
// die Seiten, auf die sie sich stützen – ein Klick springt dorthin. Das Gespräch gehört zum Tab und lebt nur im
// Arbeitsspeicher. »Mehrere PDFs fragen«: Fragen an gewählte PDFs oder einen Ordner, die Antwort nennt Datei und Seite.
// Ohne Sprachmodell: »Einrichten …« (wie in den Einstellungen); während des Downloads dessen Fortschritt.
// Seit 5.0 Beta 8 auch für Texte, Präsentationen und Tabellen (``Assistant.docKind``): Antworten nennen dort Seiten,
// Folien bzw. Blätter; Knöpfe unter einer Antwort (``actions``) übernehmen ein Ergebnis (Ersetzen, Einfügen, Diagramm),
// Korrekturen der Grammatikprüfung (``changes``) lassen sich einzeln übernehmen.
// Kopf (Titel, Schließen) und Breite kommen von der rechten Seitenleiste (RightPanel).
ColumnLayout {
    id: root
    objectName: "readerAssistantPanel"
    property var doc: null
    readonly property var conversation: Assistant.conversationModel
    readonly property string phase: Assistant.state
    readonly property bool ready: phase === "ready"
    readonly property bool loading: phase === "download" || phase === "verify"
    readonly property bool several: Assistant.scopeLabel !== ""  // Fragen an mehrere PDFs
    readonly property string docKind: Assistant.docKind  // pdf, text, praesentation, tabelle
    readonly property bool isPdf: docKind === "pdf"
    readonly property string docWord: docKind === "text" ? "diesem Text" : docKind === "praesentation" ? "dieser Präsentation" : docKind === "tabelle" ? "dieser Tabelle" : "diesem PDF"
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
                text: I18n.tr(root.loading ? "Sprachmodell wird geladen" : (Assistant.available ? "KI-Assistent einrichten" : "KI-Assistent nicht enthalten"), I18n.revision)
                textStyle: "bodyStrong"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            PText {
                objectName: "readerAssistantSetupText"
                width: parent.width
                text: I18n.tr(!Assistant.available ? "Diese Installation enthält den KI-Assistenten nicht."
                      : root.loading ? Assistant.statusText
                      : "Fragen beantworten, zusammenfassen, Texte schreiben und übersetzen – vollständig auf diesem PC. Dafür wird einmal ein Sprachmodell geladen.", I18n.revision)
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
                text: I18n.tr(Assistant.partial !== "" ? "Download fortsetzen" : "Einrichten …", I18n.revision)
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
                text: I18n.tr(Assistant.progressText, I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            PButton {
                objectName: "readerAssistantPause"
                anchors.horizontalCenter: parent.horizontalCenter
                visible: root.phase === "download"
                text: I18n.tr("Anhalten", I18n.revision)
                tip: I18n.tr("Download anhalten – er lässt sich später fortsetzen", I18n.revision)
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
            PText { objectName: "readerAssistantIntroTitle"; width: parent.width; text: I18n.tr("Fragen zu " + root.docWord, I18n.revision); textStyle: "bodyStrong"; horizontalAlignment: Text.AlignHCenter; wrap: true }
            PText {
                width: parent.width
                text: I18n.tr(root.docKind === "praesentation" ? "Der Assistent antwortet nur anhand dieser Präsentation und nennt die Folien, auf die er sich stützt."
                              : root.docKind === "tabelle" ? "Der Assistent antwortet nur anhand dieser Tabelle und nennt Blatt und Zeile. Kennzahlen rechnet Novadesk selbst."
                              : "Der Assistent antwortet nur anhand dieses Dokuments und nennt die Seiten, auf die er sich stützt.", I18n.revision)
                tone: "secondary"
                horizontalAlignment: Text.AlignHCenter
                wrap: true
            }
            Item { width: 1; height: Metrics.s8 }
            PButton {
                objectName: "readerAssistantSummarize"
                width: parent.width
                iconName: "text_bullet_list_square"
                text: I18n.tr("Dokument zusammenfassen", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.summarize() }
            }
            PButton {
                objectName: "readerAssistantTranslate"
                width: parent.width
                visible: root.docKind !== "tabelle"
                iconName: "local_language"
                text: I18n.tr("Dokument übersetzen …", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.translate() }
            }
            PButton {
                objectName: "readerAssistantWrite"
                width: parent.width
                visible: root.docKind === "text"
                iconName: "pen_sparkle"
                text: I18n.tr("Text schreiben lassen …", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.writeText() }
            }
            PButton {
                objectName: "readerAssistantGrammar"
                width: parent.width
                visible: root.docKind === "text"
                iconName: "text_grammar_wand"
                text: I18n.tr("Grammatik prüfen", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.checkGrammar() }
            }
            PButton {
                objectName: "readerAssistantAnalyze"
                width: parent.width
                visible: root.docKind === "tabelle"
                iconName: "data_trending"
                text: I18n.tr("Tabelle auswerten", I18n.revision)
                tip: I18n.tr("Die Tabelle um die markierte Zelle auswerten", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.analyzeTable() }
            }
            PButton {
                objectName: "readerAssistantChart"
                width: parent.width
                visible: root.docKind === "tabelle"
                iconName: "data_bar_vertical"
                text: I18n.tr("Diagramm vorschlagen", I18n.revision)
                enabled: !Assistant.busy && root.doc !== null
                onClicked: { flick.stick = true; Assistant.suggestChart() }
            }
            PButton {
                id: severalButton
                objectName: "readerAssistantSeveral"
                visible: root.isPdf
                width: parent.width
                iconName: "library"
                text: I18n.tr("Mehrere PDFs fragen …", I18n.revision)
                tip: I18n.tr("Fragen an gewählte PDFs oder alle PDFs eines Ordners", I18n.revision)
                enabled: !Assistant.busy
                onClicked: severalMenu.popup(severalButton, 0, severalButton.height)
            }
            Repeater {
                model: root.isPdf || root.docKind === "text" ? [
                    { label: "Fristen und Termine", question: "Welche Fristen und Termine nennt das Dokument?" },
                    { label: "Beträge und Kosten", question: "Welche Beträge und Kosten nennt das Dokument?" },
                    { label: "Beteiligte Personen und Firmen", question: "Welche Personen und Firmen sind beteiligt, und in welcher Rolle?" }
                ] : []
                PButton {
                    required property var modelData
                    width: parent.width
                    kind: "subtle"
                    iconName: "chat_sparkle"
                    text: I18n.tr(modelData.label, I18n.revision)
                    tip: I18n.tr(modelData.question, I18n.revision)
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
        Accessible.name: I18n.tr("Gespräch mit dem KI-Assistenten", I18n.revision)
        // Am Ende bleiben, solange man dort ist: Eine wachsende Antwort bleibt sichtbar; wer nach oben scrollt,
        // liest dort ungestört weiter.
        readonly property real endY: Math.max(0, contentHeight - height)
        property bool stick: true
        property bool scrolling: false
        property real lastContentHeight: 0
        property int lastCount: 0
        function toEnd() {
            scrolling = true
            contentY = Math.max(0, contentHeight - height)  // nicht ``endY``: die Bindung ist im Signal evtl. noch alt
            scrolling = false
        }
        // Nur Scrollen durch den Benutzer löst vom Ende – nicht das Neuberechnen der Höhe (Umbruch, neue Knöpfe)
        onContentYChanged: if (!scrolling && contentHeight === lastContentHeight) stick = contentY >= endY - 24
        onContentHeightChanged: {
            lastContentHeight = contentHeight
            if (stick) toEnd()
        }
        onHeightChanged: if (stick) toEnd()
        // Neue Frage (auch aus dem Menüband): wieder ans Ende
        Connections {
            target: root.conversation
            function onCountChanged() {
                if (root.conversation.count > flick.lastCount) flick.stick = true
                flick.lastCount = root.conversation.count
                if (flick.stick) Qt.callLater(flick.toEnd)
            }
        }

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
                    required property var sources
                    required property bool own  // vom Benutzer getippte Frage (nie übersetzen)
                    required property var actions  // Knöpfe unter der Antwort: {key, label, icon, tip}
                    required property var changes  // Korrekturen: {index, before, after, rich, state}
                    Layout.fillWidth: true
                    implicitHeight: kind === "question" ? bubble.height : details.implicitHeight
                    Accessible.role: Accessible.ListItem
                    Accessible.name: own ? I18n.tr("Frage: ", I18n.revision) + text : I18n.tr((kind === "question" ? "Frage: " : "") + text, I18n.revision)

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
                            // Eigene Fragen bleiben, wie sie getippt wurden – nur Fragen der App (»Dokument zusammenfassen«) werden übersetzt
                            text: entry.kind !== "question" ? "" : (entry.own ? entry.text : I18n.tr(entry.text, I18n.revision))
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
                            PText { text: I18n.tr("KI-Assistent", I18n.revision); textStyle: "caption"; tone: "secondary" }
                        }
                        Text {
                            id: answerText
                            objectName: "readerAssistantAnswer"
                            Layout.fillWidth: true
                            visible: entry.kind === "answer" && entry.text !== ""
                            // ``rich`` ist maskiert und kennt nur fett, Stichpunkte und Seitenverweise (assistant.text.rich)
                            text: I18n.tr(entry.rich, I18n.revision)
                            textFormat: Text.StyledText
                            wrapMode: Text.Wrap
                            font: Typography.body
                            color: Theme.textPrimary
                            linkColor: Theme.accentText
                            lineHeight: 1.1
                            onLinkActivated: (link) => {
                                if (link.indexOf("page:") === 0) Assistant.openPage(parseInt(link.slice(5)))
                                else if (link.indexOf("src:") === 0) {
                                    var part = link.split(":")
                                    Assistant.openSource(parseInt(part[1]), parseInt(part[2]))
                                }
                            }
                            HoverHandler { cursorShape: answerText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
                            Accessible.role: Accessible.StaticText
                            Accessible.name: I18n.tr(entry.text, I18n.revision)
                        }
                        RowLayout {
                            objectName: "readerAssistantPending"
                            visible: entry.pending
                            spacing: Metrics.s8
                            PProgressRing { size: 14; running: entry.pending && root.visible }
                            PText { Layout.fillWidth: true; text: I18n.tr(entry.note, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight }
                        }
                        PInfoBar {
                            objectName: "readerAssistantError"
                            Layout.fillWidth: true
                            visible: entry.kind === "error"
                            shown: entry.kind === "error"
                            topMargin: 0
                            severity: "error"
                            message: I18n.tr(entry.kind === "error" ? entry.text : "", I18n.revision)
                            closable: false
                        }
                        PText {
                            Layout.fillWidth: true
                            visible: entry.kind === "note" || (!entry.pending && entry.kind === "answer" && entry.note !== "")
                            text: I18n.tr(entry.kind === "note" ? entry.text : entry.note, I18n.revision)
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
                                    text: I18n.tr((root.docKind === "praesentation" ? "Folie " : "S. ") + modelData, I18n.revision)
                                    tip: I18n.tr((root.docKind === "praesentation" ? "Zur Folie " : "Zur Seite ") + modelData, I18n.revision)
                                    onClicked: Assistant.openPage(modelData)
                                }
                            }
                            Repeater {
                                model: entry.sources
                                PButton {
                                    required property var modelData
                                    objectName: "readerAssistantSource"
                                    implicitHeight: 28
                                    leftPadding: 8
                                    rightPadding: 8
                                    text: I18n.tr(modelData.label, I18n.revision)
                                    tip: I18n.tr("Datei öffnen und zur Seite " + modelData.page + " springen", I18n.revision)
                                    onClicked: Assistant.openSource(modelData.file, modelData.page)
                                }
                            }
                            PIconButton {
                                objectName: "readerAssistantCopy"
                                implicitWidth: 28
                                implicitHeight: 28
                                iconName: "copy"
                                tip: I18n.tr("Antwort kopieren", I18n.revision)
                                onClicked: Assistant.copy(entry.key)
                            }
                        }
                        // Korrekturen der Grammatikprüfung: je Satz vorher/nachher, einzeln übernehmen
                        Repeater {
                            model: entry.kind === "answer" && !entry.pending ? entry.changes : []
                            Rectangle {
                                id: changeCard
                                required property var modelData
                                objectName: "readerAssistantChange"
                                Layout.fillWidth: true
                                implicitHeight: changeColumn.implicitHeight + 16
                                radius: Metrics.radiusControl
                                color: Theme.control
                                border.width: 1
                                border.color: Theme.controlStroke
                                opacity: modelData.state === "done" ? 0.7 : 1
                                ColumnLayout {
                                    id: changeColumn
                                    x: 8
                                    y: 8
                                    width: parent.width - 16
                                    spacing: Metrics.s6
                                    Text {
                                        Layout.fillWidth: true
                                        // ``rich`` ist maskiert: <s> gestrichen, <b> neu (assistant.writing.diff_rich)
                                        text: I18n.tr(changeCard.modelData.rich, I18n.revision)
                                        textFormat: Text.StyledText
                                        wrapMode: Text.Wrap
                                        font: Typography.body
                                        color: Theme.textPrimary
                                        Accessible.role: Accessible.StaticText
                                        Accessible.name: I18n.tr("Vorschlag: ", I18n.revision) + changeCard.modelData.after
                                    }
                                    RowLayout {
                                        spacing: Metrics.s6
                                        PButton {
                                            objectName: "readerAssistantChangeApply"
                                            visible: changeCard.modelData.state === ""
                                            implicitHeight: 28
                                            iconName: "checkmark"
                                            text: I18n.tr("Übernehmen", I18n.revision)
                                            enabled: !Assistant.busy
                                            onClicked: Assistant.applyChange(entry.key, changeCard.modelData.index)
                                        }
                                        PIcon {
                                            visible: changeCard.modelData.state !== ""
                                            name: changeCard.modelData.state === "done" ? "checkmark" : "warning"
                                            size: 14
                                            color: changeCard.modelData.state === "done" ? Theme.success : Theme.textSecondary
                                        }
                                        PText {
                                            objectName: "readerAssistantChangeState"
                                            visible: changeCard.modelData.state !== ""
                                            text: I18n.tr(changeCard.modelData.state === "done" ? "Übernommen" : "Nicht mehr im Text gefunden", I18n.revision)
                                            textStyle: "caption"
                                            tone: "secondary"
                                        }
                                    }
                                }
                            }
                        }
                        // Ergebnis übernehmen: Ersetzen, Einfügen, Diagramm einfügen, alle Korrekturen …
                        Flow {
                            Layout.fillWidth: true
                            visible: entry.kind === "answer" && !entry.pending && entry.actions.length > 0
                            spacing: Metrics.s6
                            Repeater {
                                model: entry.kind === "answer" && !entry.pending ? entry.actions : []
                                PButton {
                                    required property var modelData
                                    required property int index
                                    objectName: "readerAssistantAction_" + modelData.key
                                    implicitHeight: 30
                                    kind: index === 0 ? "accent" : "standard"
                                    iconName: modelData.icon
                                    text: I18n.tr(modelData.label, I18n.revision)
                                    tip: I18n.tr(modelData.tip, I18n.revision)
                                    enabled: !Assistant.busy
                                    onClicked: Assistant.act(entry.key, modelData.key)
                                }
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
        // Wen die Fragen erreichen: dieses PDF oder mehrere
        RowLayout {
            Layout.fillWidth: true
            spacing: Metrics.s6
            PIcon { name: root.several ? "library" : "document"; size: 14; color: Theme.textSecondary }
            PText {
                objectName: "readerAssistantScope"
                Layout.fillWidth: true
                text: I18n.tr("Fragen an: " + (root.several ? Assistant.scopeLabel : root.docKind === "text" ? "diesen Text" : root.docKind === "praesentation" ? "diese Präsentation" : root.docKind === "tabelle" ? "diese Tabelle" : "dieses PDF"), I18n.revision)
                textStyle: "caption"
                tone: "secondary"
                elide: Text.ElideRight
            }
            PButton {
                id: scopeButton
                objectName: "readerAssistantScopeButton"
                visible: !root.several && root.isPdf
                implicitHeight: 24
                leftPadding: 6
                rightPadding: 6
                kind: "subtle"
                text: I18n.tr("Mehrere PDFs …", I18n.revision)
                enabled: !Assistant.busy
                onClicked: severalMenu.popup(scopeButton, 0, scopeButton.height)
            }
            PIconButton {
                objectName: "readerAssistantScopeClear"
                visible: root.several
                implicitWidth: 24
                implicitHeight: 24
                iconName: "dismiss"
                tip: I18n.tr("Wieder nur dieses PDF fragen", I18n.revision)
                onClicked: Assistant.clearScope()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Metrics.s8
            PTextArea {
                id: input
                objectName: "readerAssistantInput"
                Layout.fillWidth: true
                minLines: 1
                maxLines: 5
                label: I18n.tr(root.several ? "Frage an die gewählten PDFs" : "Frage zum Dokument", I18n.revision)
                placeholderText: I18n.tr(root.several ? "Frage an die gewählten PDFs …" : "Frage zu " + root.docWord + " …", I18n.revision)
                enabled: root.doc !== null
                submitOnEnter: true
                onSubmitted: if (root.send(input.text)) input.text = ""
            }
            PIconButton {
                objectName: "readerAssistantSummarizeMore"
                Layout.alignment: Qt.AlignBottom
                visible: root.conversation.count > 0 && !Assistant.busy && !root.several
                iconName: "text_bullet_list_square"
                tip: I18n.tr("Dokument zusammenfassen", I18n.revision)
                enabled: root.doc !== null
                onClicked: { flick.stick = true; Assistant.summarize() }
            }
            PIconButton {
                objectName: "readerAssistantTranslateMore"
                Layout.alignment: Qt.AlignBottom
                visible: root.conversation.count > 0 && !Assistant.busy && !root.several && root.docKind !== "tabelle"
                iconName: "local_language"
                tip: I18n.tr("Dokument übersetzen", I18n.revision)
                enabled: root.doc !== null
                onClicked: { flick.stick = true; Assistant.translate() }
            }
            PIconButton {
                objectName: "readerAssistantSend"
                Layout.alignment: Qt.AlignBottom
                visible: !Assistant.busy
                kind: "accent"
                iconName: "send"
                tip: I18n.tr("Frage senden (Eingabetaste)", I18n.revision)
                enabled: input.text.trim() !== "" && root.doc !== null
                onClicked: if (root.send(input.text)) input.text = ""
            }
            PIconButton {
                objectName: "readerAssistantStop"
                Layout.alignment: Qt.AlignBottom
                visible: Assistant.busy
                iconName: "stop"
                tip: I18n.tr("Antwort anhalten", I18n.revision)
                onClicked: Assistant.stop()
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Metrics.s6
            PIcon { Layout.alignment: Qt.AlignTop; name: "shield_checkmark"; size: 14; color: Theme.textTertiary }
            PText {
                Layout.fillWidth: true
                text: I18n.tr(root.docKind === "tabelle" ? "Läuft nur auf diesem PC. Antworten können Fehler enthalten – bitte in der Tabelle prüfen."
                              : root.docKind === "praesentation" ? "Läuft nur auf diesem PC. Antworten können Fehler enthalten – bitte auf den genannten Folien prüfen."
                              : "Läuft nur auf diesem PC. Antworten können Fehler enthalten – bitte auf den genannten Seiten prüfen.", I18n.revision)
                textStyle: "caption"
                tone: "tertiary"
                wrap: true
            }
        }
    }

    PMenu {
        id: severalMenu
        objectName: "readerAssistantSeveralMenu"
        PMenuItem { text: I18n.tr("PDFs wählen …", I18n.revision); iconName: "document_multiple"; onTriggered: severalMenu.afterClose = function() { flick.stick = true; Assistant.chooseFiles() } }
        PMenuItem { text: I18n.tr("Ordner wählen (mit Unterordnern) …", I18n.revision); iconName: "folder_open"; onTriggered: severalMenu.afterClose = function() { flick.stick = true; Assistant.chooseFolder() } }
    }
}
