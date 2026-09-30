import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// Vertragsübersichten – »Vorschau«: die PDF so, wie »PDF erstellen« sie erzeugt. Seiten blättern
// (Bild ↑/↓, Pos1/Ende), zoomen (+/−), an Breite oder ganze Seite anpassen; breite Seiten lassen
// sich verschieben. Der Platz der Seite ist reserviert – beim Erscheinen springt nichts.
PPage {
    id: page
    objectName: "previewPage"
    title: "Vertragsübersichten"
    subtitle: "Vorschau: die PDF so, wie sie erstellt wird – aktualisiert sich bei jeder Änderung."

    // Verfügbare Fläche für »An Breite« bzw. »Ganze Seite« an Python melden
    function reportViewport() {
        if (!visible || viewArea.width <= 0) return
        var top = viewArea.mapToItem(page.flickable.contentItem, 0, 0).y
        var height = page.flickable.height - top - Metrics.pagePaddingBottom
        Preview.setViewport(viewArea.width, Math.max(240, height), Screen.devicePixelRatio)
    }
    Timer { id: viewportTimer; interval: 0; onTriggered: page.reportViewport() }
    // Wie bis 2.6: beim Blättern steht die neue Seite oben im Blick
    Connections {
        target: Preview
        function onPageChanged() { if (page.visible) page.reveal(viewArea) }
    }
    onWidthChanged: viewportTimer.restart()
    onHeightChanged: viewportTimer.restart()
    onVisibleChanged: if (visible) viewportTimer.restart()
    Component.onCompleted: viewportTimer.restart()

    ContractViews {}

    // Aus dem Stapel geöffnet: welcher Eintrag gezeigt wird
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("preview_source"); closable: false; topMargin: 0 }

    Flow {
        Layout.fillWidth: true
        Layout.topMargin: 4
        spacing: 6
        Row {
            spacing: 4
            PIconButton { iconName: "chevron_left"; tip: "Vorherige Seite (Bild ↑)"; enabled: Preview.canPrev; onClicked: Preview.step(-1) }
            PText {
                width: pageMetrics.advanceWidth + 16
                height: 32
                horizontalAlignment: Text.AlignHCenter
                text: Preview.pages > 0 ? "Seite " + (Preview.page + 1) + " von " + Preview.pages : "Seite –"
                TextMetrics { id: pageMetrics; font: Typography.body; text: "Seite 88 von 88" }
            }
            PIconButton { iconName: "chevron_right"; tip: "Nächste Seite (Bild ↓)"; enabled: Preview.canNext; onClicked: Preview.step(1) }
        }
        Row {
            spacing: 4
            leftPadding: 12
            PIconButton { iconName: "zoom_out"; tip: "Verkleinern (−)"; enabled: Preview.pages > 0; onClicked: Preview.zoomOut() }
            PText {
                width: zoomMetrics.advanceWidth + 16
                height: 32
                horizontalAlignment: Text.AlignHCenter
                text: Preview.zoomText
                TextMetrics { id: zoomMetrics; font: Typography.body; text: "Ganze Seite" }
            }
            PIconButton { iconName: "zoom_in"; tip: "Vergrößern (+)"; enabled: Preview.pages > 0; onClicked: Preview.zoomIn() }
        }
        PButton { kind: "subtle"; iconName: "arrow_autofit_width"; text: "An Breite anpassen"; tip: "Seite an die Breite der Ansicht anpassen (0)"; enabled: Preview.fit !== "width"; onClicked: Preview.fitWidth() }
        PButton { kind: "subtle"; iconName: "page_fit"; text: "Ganze Seite"; tip: "Ganze Seite in die Ansicht einpassen"; enabled: Preview.fit !== "page"; onClicked: Preview.fitPage() }
        PButton { iconName: "arrow_clockwise"; text: "Aktualisieren"; tip: "Vorschau neu erzeugen (z. B. nach Änderungen an der Excel-Datei)"; onClicked: Preview.refreshNow() }
    }

    // Zustand in eigener Zeile: Sein Text wechselt in der Länge und bricht die Leiste nicht um
    PCollapse {
        Layout.fillWidth: true
        expanded: Preview.state !== "empty"
        RowLayout {
            width: parent.width
            height: 32
            spacing: 8
            y: 4
            Item {
                implicitWidth: 16
                implicitHeight: 16
                PProgressRing { anchors.centerIn: parent; size: 16; visible: Preview.state === "busy" || Preview.state === "stale"; running: visible }
                PIcon {
                    anchors.centerIn: parent
                    visible: Preview.state === "current" || Preview.state === "error"
                    name: Preview.state === "error" ? "error_circle_filled" : "checkmark_circle_filled"
                    color: Preview.state === "error" ? Theme.error : Theme.success
                }
            }
            PCrossfadeText {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: Preview.stateText
                font: Typography.caption
                color: Theme.textSecondary
            }
        }
    }
    PInfoBar { Layout.fillWidth: true; notice: Notices.area("preview_info") }

    PStateStack {
        Layout.fillWidth: true
        Layout.topMargin: 8
        currentIndex: Preview.state === "empty" || (Preview.state === "error" && Preview.pageWidth <= 0) ? 0 : 1

        PState {
            Rectangle {
                width: parent.width
                implicitHeight: emptyColumn.implicitHeight + 56
                height: implicitHeight
                radius: Metrics.radiusCard
                color: Theme.surface
                border.color: Theme.border
                ColumnLayout {
                    id: emptyColumn
                    x: 24
                    y: 28
                    width: parent.width - 48
                    spacing: 4
                    PIcon { name: "eye"; size: Metrics.iconSizeLarge; color: Theme.textSecondary }
                    PText { text: Preview.texts.emptyTitle; textStyle: "bodyStrong"; Layout.topMargin: 6 }
                    PText { text: Preview.problem; tone: "warning"; wrap: true; visible: text !== ""; Layout.fillWidth: true }
                    PText { text: Preview.texts.emptyHint; tone: "secondary"; wrap: true; Layout.fillWidth: true; Layout.topMargin: 2 }
                    PButton { kind: "accent"; iconName: "document"; text: "Zu »Übersicht erstellen«"; Layout.topMargin: 10; onClicked: App.navigate("create") }
                }
            }
        }
        PState {
            Item {
                id: viewArea
                objectName: "previewArea"
                width: parent.width
                readonly property real margin: 16
                implicitHeight: Math.max(120, Preview.pageHeight + 2 * margin)
                height: implicitHeight
                onWidthChanged: viewportTimer.restart()
                activeFocusOnTab: true
                Accessible.role: Accessible.Graphic
                Accessible.name: Preview.pages > 0 ? "Vorschau, Seite " + (Preview.page + 1) + " von " + Preview.pages : "Vorschau"
                Keys.onPressed: (event) => {
                    switch (event.key) {
                    case Qt.Key_PageUp: Preview.step(-1); break
                    case Qt.Key_PageDown: Preview.step(1); break
                    case Qt.Key_Home: Preview.goTo(0); break
                    case Qt.Key_End: Preview.goTo(1000000); break
                    case Qt.Key_Plus: Preview.zoomIn(); break
                    case Qt.Key_Minus: Preview.zoomOut(); break
                    case Qt.Key_0: Preview.fitWidth(); break
                    case Qt.Key_Left: pan.contentX = Math.max(0, pan.contentX - 60); break
                    case Qt.Key_Right: pan.contentX = Math.min(Math.max(0, pan.contentWidth - pan.width), pan.contentX + 60); break
                    default: return
                    }
                    event.accepted = true
                }
                Rectangle {
                    anchors.fill: parent
                    radius: Metrics.radiusCard
                    color: Theme.surfaceSecondary
                    border.color: viewArea.activeFocus ? Theme.accent : Theme.border
                }
                Flickable {
                    id: pan
                    anchors.fill: parent
                    anchors.margins: 1
                    clip: true
                    contentWidth: Math.max(width, Preview.pageWidth + 2 * viewArea.margin)
                    contentHeight: height
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    interactive: contentWidth > width
                    T.ScrollBar.horizontal: PScrollBar {}
                    Rectangle {
                        id: sheet
                        x: Math.max(viewArea.margin, (pan.contentWidth - width) / 2)
                        y: viewArea.margin - 1
                        width: Preview.pageWidth
                        height: Preview.pageHeight
                        color: "#FFFFFF"
                        border.color: Theme.border
                        PShadow { radius: 0; depth: 2; strength: 0.7 }
                        Image {
                            id: image
                            anchors.fill: parent
                            source: Preview.imageSource
                            fillMode: Image.Stretch
                            smooth: true
                            mipmap: false
                            cache: false
                            asynchronous: false
                            opacity: status === Image.Ready ? 1 : 0
                            Behavior on opacity { enabled: Motion.enabled; NumberAnimation { duration: Motion.fade } }
                        }
                    }
                }
                TapHandler { onTapped: viewArea.forceActiveFocus() }
            }
        }
    }
}
