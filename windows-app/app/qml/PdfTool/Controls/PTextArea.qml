import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Mehrzeiliges Eingabefeld (reiner Text, z. B. Notiz) – wächst mit dem Inhalt bis ``maxLines``.
Rectangle {
    id: root
    property alias text: area.text
    property alias area: area
    property string placeholderText: ""
    property int minLines: 3
    property int maxLines: 10
    property bool invalid: false
    property string label: ""
    signal edited()

    readonly property real lineHeight: fontMetrics.height
    implicitWidth: 320
    implicitHeight: Math.min(maxLines, Math.max(minLines, area.lineCount)) * lineHeight + area.topPadding + area.bottomPadding + 2
    radius: Metrics.radiusControl
    color: !enabled ? Theme.controlDisabled : (area.activeFocus ? Theme.inputFocus : (hover.hovered ? Theme.controlHover : Theme.control))
    border.width: 1
    border.color: invalid ? Theme.error : Theme.controlStroke
    Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
    FontMetrics { id: fontMetrics; font: Typography.body }
    HoverHandler { id: hover }

    Flickable {
        id: flick
        anchors.fill: parent
        anchors.margins: 1
        contentWidth: width
        contentHeight: area.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        T.ScrollBar.vertical: PScrollBar {}
        function ensureVisible(rect) {
            if (contentY >= rect.y) contentY = rect.y
            else if (contentY + height <= rect.y + rect.height) contentY = rect.y + rect.height - height
        }
        T.TextArea {
            id: area
            width: flick.width
            leftPadding: 10
            rightPadding: 10
            topPadding: 6
            bottomPadding: 7
            font: Typography.body
            color: root.enabled ? Theme.textPrimary : Theme.disabled
            selectionColor: Theme.accent
            selectedTextColor: Theme.textOnAccent
            placeholderTextColor: Theme.textSecondary
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            textFormat: TextEdit.PlainText
            Accessible.role: Accessible.EditableText
            Accessible.name: root.label !== "" ? root.label : root.placeholderText
            onCursorRectangleChanged: flick.ensureVisible(cursorRectangle)
            onTextChanged: if (activeFocus) root.edited()
            Keys.onTabPressed: (event) => { area.nextItemInFocusChain(true).forceActiveFocus(Qt.TabFocusReason); event.accepted = true }
            Keys.onBacktabPressed: (event) => { area.nextItemInFocusChain(false).forceActiveFocus(Qt.BacktabFocusReason); event.accepted = true }
            Text {
                x: area.leftPadding
                y: area.topPadding
                text: root.placeholderText
                font: area.font
                color: area.placeholderTextColor
                visible: !area.length && !area.preeditText
                Accessible.ignored: true
            }
            TapHandler {
                acceptedButtons: Qt.RightButton
                onTapped: (point) => { area.forceActiveFocus(); menu.popup(area, point.position.x, point.position.y) }
            }
            PTextMenu { id: menu; target: area }
        }
    }
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 1
        anchors.rightMargin: 1
        height: area.activeFocus || root.invalid ? 2 : 1
        color: root.invalid ? Theme.error : (area.activeFocus ? Theme.accent : Theme.inputEdge)
    }
}
