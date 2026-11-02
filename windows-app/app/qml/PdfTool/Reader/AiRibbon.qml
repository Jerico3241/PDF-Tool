import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Reiter »KI« im Menüband (seit 5.0 Beta 8) – für PDFs, Texte, Präsentationen und Tabellen. Links öffnet »KI-Assistent«
// die Seitenleiste mit dem Gespräch; dahinter die Werkzeuge der Dokumentart:
// * Text/Präsentation: Schreiben lassen, Umschreiben, Kürzen, Ausführlicher, Einfache Sprache, Ton ändern | Grammatik
//   (nur Text) | Übersetzen (Markierung oder ganzes Dokument nebeneinander) | Zusammenfassen | Präsentation erstellen
// * Tabelle: Auswerten, Diagramm vorschlagen | Zusammenfassen | Präsentation erstellen
// * PDF: Zusammenfassen, Übersetzen | Formular ausfüllen | Präsentation erstellen
// Ist der Assistent ausgeschaltet, steht hier nur ein Hinweis mit »Einschalten«. Alles läuft auf diesem PC.
RowLayout {
    id: root
    property string kind: "pdf"  // pdf, text, praesentation, tabelle
    property bool ready: true  // Dokument bereit
    // Beschriftungen je nach Platz: 3 = alle, 2 = ohne »Läuft nur auf diesem PC«, 1 = nur die Hauptwerkzeuge, 0 = nur Symbole. Die Leiste misst sich selbst
    // (implicitWidth), damit sie in jeder Sprache und Fensterbreite ohne Abschneiden passt.
    property int level: 3
    readonly property bool roomy: level >= 2
    readonly property bool labels: level >= 1
    property bool panelOpen: false  // Seitenleiste mit dem Assistenten offen
    property color kindColor: Theme.accent
    signal panelToggled()
    signal done()  // Fokus zurück ins Dokument

    readonly property bool on: Assistant.enabled
    readonly property bool writes: kind === "text" || kind === "praesentation"
    anchors.fill: parent
    anchors.leftMargin: 12
    anchors.rightMargin: 12
    anchors.bottomMargin: 1
    spacing: 2

    function fit() {
        if (visible && level > 0 && implicitWidth > width) { level--; Qt.callLater(fit) }
    }
    function refit() { level = 3; Qt.callLater(fit) }
    onWidthChanged: refit()
    onVisibleChanged: refit()
    onKindChanged: refit()
    onOnChanged: refit()
    Connections { target: I18n; function onRevisionChanged() { root.refit() } }
    Component.onCompleted: refit()

    component ToolButton: PButton {
        kind: "subtle"
        leftPadding: text === "" ? 0 : 8
        rightPadding: text === "" ? 0 : 10
        enabled: root.ready && !Assistant.busy
    }

    // Ausgeschaltet oder nicht enthalten ---------------------------------------------------------------------------
    PIcon { visible: !root.on; name: "sparkle"; size: 18; color: Theme.accentText; Layout.rightMargin: 4 }
    PText {
        objectName: "aiRibbonOff"
        visible: !root.on
        text: I18n.tr(Assistant.available ? "Der KI-Assistent ist ausgeschaltet. Er läuft nur auf diesem PC – nichts verlässt den Rechner."
                                          : "Diese Installation enthält den KI-Assistenten nicht.", I18n.revision)
        tone: "secondary"
        elide: Text.ElideRight
        Layout.maximumWidth: root.width - 160
    }
    PButton {
        objectName: "aiRibbonEnable"
        visible: !root.on && Assistant.available
        Layout.leftMargin: 8
        kind: "accent"
        text: I18n.tr("Einschalten", I18n.revision)
        onClicked: { Assistant.setEnabled(true); root.panelToggled() }
    }

    // Seitenleiste -----------------------------------------------------------------------------------------------
    ToolButton {
        objectName: "aiRibbonPanel"
        visible: root.on
        enabled: root.ready
        iconName: "sparkle"
        text: I18n.tr(root.labels ? "KI-Assistent" : "", I18n.revision)
        tip: I18n.tr("Gespräch mit dem KI-Assistenten rechts zeigen", I18n.revision)
        toggle: true
        checked: root.panelOpen
        onClicked: root.panelToggled()
    }
    RibbonSeparator { visible: root.on }

    // Schreiben (Text, Präsentation) --------------------------------------------------------------------------------
    ToolButton {
        objectName: "aiRibbonWrite"
        visible: root.on && root.writes
        iconName: "pen_sparkle"
        text: I18n.tr(root.labels ? "Schreiben lassen" : "", I18n.revision)
        tip: I18n.tr("Einen Text nach Ihrer Anweisung schreiben lassen – er wird an der Schreibmarke eingefügt", I18n.revision)
        onClicked: Assistant.writeText()
    }
    ToolButton {
        objectName: "aiRibbonRewrite"
        visible: root.on && root.writes
        iconName: "arrow_sync"
        text: I18n.tr(root.roomy ? "Umschreiben" : "", I18n.revision)
        tip: I18n.tr("Markierten Text klarer formulieren", I18n.revision)
        onClicked: Assistant.editSelection("rewrite")
    }
    ToolButton {
        objectName: "aiRibbonShorten"
        visible: root.on && root.writes
        iconName: "text_collapse"
        text: I18n.tr(root.roomy ? "Kürzen" : "", I18n.revision)
        tip: I18n.tr("Markierten Text auf etwa die Hälfte kürzen", I18n.revision)
        onClicked: Assistant.editSelection("shorten")
    }
    ToolButton {
        objectName: "aiRibbonExpand"
        visible: root.on && root.writes
        iconName: "text_expand"
        text: I18n.tr(root.roomy ? "Ausführlicher" : "", I18n.revision)
        tip: I18n.tr("Markierten Text ausführlicher schreiben", I18n.revision)
        onClicked: Assistant.editSelection("expand")
    }
    ToolButton {
        objectName: "aiRibbonSimple"
        visible: root.on && root.writes
        iconName: "text_font"
        text: I18n.tr(root.roomy ? "Einfache Sprache" : "", I18n.revision)
        tip: I18n.tr("Markierten Text in einfache Sprache bringen", I18n.revision)
        onClicked: Assistant.editSelection("simple")
    }
    ToolButton {
        id: toneButton
        objectName: "aiRibbonTone"
        visible: root.on && root.writes
        iconName: "emoji"
        text: I18n.tr(root.roomy ? "Ton ändern" : "", I18n.revision)
        tip: I18n.tr("Markierten Text förmlicher, freundlicher, sachlicher … schreiben", I18n.revision)
        onClicked: toneMenu.popup(toneButton, 0, toneButton.height + 4)
    }
    ToolButton {
        objectName: "aiRibbonGrammar"
        visible: root.on && root.kind === "text"
        iconName: "text_grammar_wand"
        text: I18n.tr(root.roomy ? "Grammatik" : "", I18n.revision)
        tip: I18n.tr("Grammatik und Rechtschreibung mit KI prüfen – Markierung oder ganzer Text", I18n.revision)
        onClicked: Assistant.checkGrammar()
    }
    RibbonSeparator { visible: root.on && root.writes }

    // Tabelle --------------------------------------------------------------------------------------------------
    ToolButton {
        objectName: "aiRibbonAnalyze"
        visible: root.on && root.kind === "tabelle"
        iconName: "data_trending"
        text: I18n.tr(root.labels ? "Tabelle auswerten" : "", I18n.revision)
        tip: I18n.tr("Die Tabelle um die markierte Zelle auswerten: Summen, Mittelwerte, Auffälligkeiten", I18n.revision)
        onClicked: Assistant.analyzeTable()
    }
    ToolButton {
        objectName: "aiRibbonChart"
        visible: root.on && root.kind === "tabelle"
        iconName: "data_bar_vertical"
        text: I18n.tr(root.labels ? "Diagramm vorschlagen" : "", I18n.revision)
        tip: I18n.tr("Passendes Diagramm für die Tabelle um die markierte Zelle vorschlagen und einfügen", I18n.revision)
        onClicked: Assistant.suggestChart()
    }
    RibbonSeparator { visible: root.on && root.kind === "tabelle" }

    // Für alle: Zusammenfassen, Übersetzen -------------------------------------------------------------------------
    ToolButton {
        objectName: "aiRibbonSummarize"
        visible: root.on
        iconName: "text_bullet_list_square"
        text: I18n.tr(root.labels ? "Zusammenfassen" : "", I18n.revision)
        tip: I18n.tr("Das ganze Dokument zusammenfassen", I18n.revision)
        onClicked: Assistant.summarize()
    }
    ToolButton {
        id: translateButton
        objectName: "aiRibbonTranslate"
        visible: root.on && root.kind !== "tabelle"
        iconName: "local_language"
        text: I18n.tr(root.labels ? "Übersetzen" : "", I18n.revision)
        tip: I18n.tr(root.writes ? "Markierung oder ganzes Dokument übersetzen" : "Dokument übersetzen – als neues PDF oder nebeneinander", I18n.revision)
        onClicked: root.writes ? translateMenu.popup(translateButton, 0, translateButton.height + 4) : Assistant.translate()
    }
    ToolButton {
        objectName: "aiRibbonForm"
        visible: root.on && root.kind === "pdf"
        iconName: "form_sparkle"
        text: I18n.tr(root.labels ? "Formular ausfüllen" : "", I18n.revision)
        tip: I18n.tr("PDF-Formular mit KI ausfüllen: Angaben eingeben, Vorschläge prüfen, eintragen", I18n.revision)
        onClicked: Assistant.fillForm()
    }
    RibbonSeparator { visible: root.on }
    ToolButton {
        objectName: "aiRibbonSlides"
        visible: root.on
        iconName: "slide_text_sparkle"
        text: I18n.tr(root.labels ? "Präsentation erstellen" : "", I18n.revision)
        tip: I18n.tr("Neue Präsentation aus einem Thema oder aus diesem Dokument", I18n.revision)
        onClicked: Assistant.createPresentation()
    }
    Item { Layout.fillWidth: true }
    PIcon { visible: root.on; name: "shield_checkmark"; size: 14; color: Theme.textTertiary }
    PText {
        visible: root.on && root.level >= 3
        text: I18n.tr("Läuft nur auf diesem PC", I18n.revision)
        textStyle: "caption"
        tone: "tertiary"
    }
    ToolButton {
        objectName: "aiRibbonStop"
        visible: root.on && Assistant.busy
        enabled: true
        iconName: "stop"
        tip: I18n.tr("KI anhalten", I18n.revision)
        onClicked: Assistant.stop()
    }

    PMenu {
        id: toneMenu
        objectName: "aiRibbonToneMenu"
        Repeater {
            model: [
                { key: "formal", label: "Förmlich", icon: "briefcase" }, { key: "friendly", label: "Freundlich", icon: "emoji" },
                { key: "factual", label: "Sachlich", icon: "text_align_left" }, { key: "casual", label: "Locker", icon: "chat" },
                { key: "confident", label: "Überzeugend", icon: "ribbon_star" }
            ]
            PMenuItem {
                required property var modelData
                objectName: "aiRibbonTone_" + modelData.key
                text: I18n.tr(modelData.label, I18n.revision)
                iconName: modelData.icon
                onTriggered: { var key = modelData.key; toneMenu.afterClose = function() { Assistant.editSelection(key) } }
            }
        }
    }
    PMenu {
        id: translateMenu
        objectName: "aiRibbonTranslateMenu"
        PMenuItem {
            objectName: "aiRibbonTranslateSide"
            text: I18n.tr("Ganzes Dokument nebeneinander …", I18n.revision)
            iconName: "layout_column_two"
            onTriggered: translateMenu.afterClose = function() { Assistant.translate() }
        }
        Repeater {
            model: [
                { key: "en", label: "Markierung ins Englische" }, { key: "de", label: "Markierung ins Deutsche" },
                { key: "fr", label: "Markierung ins Französische" }, { key: "es", label: "Markierung ins Spanische" },
                { key: "it", label: "Markierung ins Italienische" }, { key: "nl", label: "Markierung ins Niederländische" },
                { key: "pl", label: "Markierung ins Polnische" }, { key: "pt", label: "Markierung ins Portugiesische" },
                { key: "tr", label: "Markierung ins Türkische" }
            ]
            PMenuItem {
                required property var modelData
                objectName: "aiRibbonTranslate_" + modelData.key
                text: I18n.tr(modelData.label, I18n.revision)
                iconName: "local_language"
                onTriggered: { var key = modelData.key; translateMenu.afterClose = function() { Assistant.translateSelection(key) } }
            }
        }
    }
}
