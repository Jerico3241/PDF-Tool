import QtQuick
import QtQuick.Layouts
import QtQuick.Templates as T
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls
import PdfTool.Dialogs

// Der einzige Dialog der App: zeigt die aktuelle Anfrage aus Python (``Dialogs.request``).
// Öffnen: Überblenden und leichtes Vergrößern, Schließen rückwärts. Esc = Abbrechen,
// Eingabe = Standard-Schaltfläche. Folgt eine Anfrage direkt der nächsten, wechselt nur der Inhalt.
T.Popup {
    id: popup
    readonly property var request: Dialogs.request
    readonly property string kind: request.kind || ""
    property var content: body.item

    parent: T.Overlay.overlay
    anchors.centerIn: parent
    modal: true
    dim: true
    focus: true
    visible: Dialogs.open
    closePolicy: T.Popup.NoAutoClose
    padding: 0
    implicitWidth: request.width || 460
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset, contentHeight + topPadding + bottomPadding)
    width: Math.min(implicitWidth, parent ? parent.width - 48 : implicitWidth)
    height: Math.min(implicitHeight, parent ? parent.height - 48 : implicitHeight)

    function answer(button) {
        if (!Dialogs.open) return
        var data = content && content.collect ? content.collect() : ({})
        Dialogs.answer(request.id, button, data)
    }
    function defaultButton() {
        var wanted = request["default"] || "primary"
        if (wanted === "primary" && (!request.primary || (content && content.acceptable === false))) return "close"
        return wanted
    }

    T.Overlay.modal: Rectangle {
        color: Theme.smoke
    }

    enter: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.dialog; easing.type: Motion.decelerate }
            NumberAnimation { property: "scale"; from: Motion.dialogScale; to: 1; duration: Motion.dialog; easing.type: Motion.decelerate }
        }
    }
    exit: Transition {
        ParallelAnimation {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.dialog * 0.8; easing.type: Motion.accelerate }
            NumberAnimation { property: "scale"; from: 1; to: Motion.dialogScale; duration: Motion.dialog * 0.8; easing.type: Motion.accelerate }
        }
    }

    onRequestChanged: {
        if (opened && Motion.enabled) swap.restart()
    }
    SequentialAnimation {
        id: swap
        NumberAnimation { target: frame; property: "opacity"; to: 0.3; duration: 60 }
        NumberAnimation { target: frame; property: "opacity"; to: 1; duration: Motion.fade; easing.type: Motion.decelerate }
    }

    background: Rectangle {
        color: Theme.dialog
        border.color: Theme.flyoutStroke
        radius: Metrics.radiusDialog
        PShadow { radius: Metrics.radiusDialog; depth: 4 }
    }

    contentItem: FocusScope {
        id: frame
        implicitHeight: layout.implicitHeight
        focus: true
        Keys.onEscapePressed: popup.answer("close")
        Keys.onReturnPressed: (event) => {
            if (popup.content && popup.content.handlesReturn) { event.accepted = false; return }
            popup.answer(popup.defaultButton())
        }
        Keys.onEnterPressed: popup.answer(popup.defaultButton())
        Accessible.role: Accessible.Dialog
        Accessible.name: popup.request.title || ""

        ColumnLayout {
            id: layout
            anchors.fill: parent
            spacing: 0

            Flickable {
                id: scroller
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: Math.min(bodyColumn.implicitHeight, (popup.parent ? popup.parent.height : 800) - 48 - footer.implicitHeight)
                contentHeight: bodyColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                T.ScrollBar.vertical: PScrollBar {}
                ColumnLayout {
                    id: bodyColumn
                    width: scroller.width
                    spacing: 12
                    PText {
                        text: popup.request.title || ""
                        textStyle: "subtitle"
                        wrap: true
                        Layout.fillWidth: true
                        Layout.topMargin: 24
                        Layout.leftMargin: 24
                        Layout.rightMargin: 24
                        Accessible.role: Accessible.Heading
                    }
                    PText {
                        text: popup.request.message || ""
                        wrap: true
                        visible: text !== ""
                        Layout.fillWidth: true
                        Layout.leftMargin: 24
                        Layout.rightMargin: 24
                        Layout.bottomMargin: body.item ? 0 : 24
                    }
                    Loader {
                        id: body
                        Layout.fillWidth: true
                        Layout.leftMargin: 24
                        Layout.rightMargin: 24
                        Layout.bottomMargin: 24
                        // Ohne Inhalt (z. B. Rückfrage nach einem Dialog mit Inhalt) keine Höhe: ein Loader
                        // behielte sonst die Höhe seines vorigen Inhalts.
                        Layout.preferredHeight: item ? item.implicitHeight : 0
                        visible: item !== null
                        focus: true
                        sourceComponent: {
                            switch (popup.kind) {
                            case "steps": return stepsContent
                            case "about": return aboutContent
                            case "changelog": return changelogContent
                            case "choose_customer": return chooseCustomerContent
                            case "new_customer": return newCustomerContent
                            case "customer_update": return customerUpdateContent
                            case "customer_fields": return customerFieldsContent
                            case "choose_template": return chooseTemplateContent
                            case "update_details": return updateContent
                            case "text_input": return textInputContent
                            case "restore_summary": return restoreSummaryContent
                            case "password": return passwordContent
                            case "reader_properties": return readerPropertiesContent
                            case "ocr": return ocrContent
                            default: return null
                            }
                        }
                        onLoaded: if (item) item.request = Qt.binding(function() { return popup.request })
                    }
                }
            }

            Rectangle {
                id: footer
                Layout.fillWidth: true
                implicitHeight: 80
                color: Theme.dialogFooter
                radius: Metrics.radiusDialog
                // obere Ecken gerade: Abdeckung über dem Rundungsbereich
                Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: Metrics.radiusDialog; color: parent.color }
                Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 1; color: Theme.divider }
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 8
                    Item { Layout.fillWidth: true; visible: buttonsShown < 2 }
                    PButton {
                        id: primaryButton
                        visible: (popup.request.primary || "") !== ""
                        text: popup.request.primary || ""
                        kind: popup.request.danger ? "danger" : "accent"
                        enabled: !popup.content || popup.content.acceptable !== false
                        Layout.fillWidth: popup.buttonsShown >= 2
                        Layout.preferredWidth: popup.buttonsShown >= 2 ? 1 : Math.max(120, implicitWidth)
                        onClicked: popup.answer("primary")
                    }
                    PButton {
                        visible: (popup.request.secondary || "") !== ""
                        text: popup.request.secondary || ""
                        Layout.fillWidth: popup.buttonsShown >= 2
                        Layout.preferredWidth: popup.buttonsShown >= 2 ? 1 : Math.max(120, implicitWidth)
                        onClicked: popup.answer("secondary")
                    }
                    PButton {
                        visible: (popup.request.close || "") !== ""
                        text: popup.request.close || ""
                        kind: (popup.request.primary || "") === "" ? "accent" : "standard"
                        Layout.fillWidth: popup.buttonsShown >= 2
                        Layout.preferredWidth: popup.buttonsShown >= 2 ? 1 : Math.max(120, implicitWidth)
                        onClicked: popup.answer("close")
                    }
                }
            }
        }
    }
    readonly property int buttonsShown: ((request.primary || "") !== "" ? 1 : 0) + ((request.secondary || "") !== "" ? 1 : 0) + ((request.close || "") !== "" ? 1 : 0)

    Component { id: stepsContent; StepsContent {} }
    Component { id: aboutContent; AboutContent {} }
    Component { id: changelogContent; ChangelogContent {} }
    Component { id: chooseCustomerContent; ChooseCustomerContent {} }
    Component { id: newCustomerContent; NewCustomerContent {} }
    Component { id: customerUpdateContent; CustomerUpdateContent {} }
    Component { id: customerFieldsContent; CustomerFieldsContent {} }
    Component { id: chooseTemplateContent; ChooseTemplateContent {} }
    Component { id: updateContent; UpdateContent {} }
    Component { id: textInputContent; TextInputContent {} }
    Component { id: restoreSummaryContent; RestoreSummaryContent {} }
    Component { id: passwordContent; PasswordContent {} }
    Component { id: readerPropertiesContent; ReaderPropertiesContent {} }
    Component { id: ocrContent; OcrContent {} }
}
