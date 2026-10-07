import QtQuick
import QtQuick.Templates as T
import PdfTool.Style

// Auswahlliste im Stil von Windows 11: Aufklappliste mit weicher Einblendung (Deckkraft + leichte
// Bewegung), Markierung des gewählten Eintrags, Tastatur (↑ ↓ Pos1 Ende, Eingabe, Esc, Tippen).
T.ComboBox {
    id: control
    property string placeholder: ""
    property string tip: ""
    property string label: ""
    property int preferredWidth: 200

    implicitWidth: preferredWidth
    implicitHeight: Metrics.controlHeight
    leftPadding: 11
    rightPadding: 34
    font: Typography.body
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.ComboBox
    Accessible.name: label !== "" ? label : (tip !== "" ? tip : placeholder)
    Accessible.description: displayText

    delegate: T.ItemDelegate {
        id: item
        required property int index
        required property var modelData
        readonly property string itemText: control.textRole !== "" && modelData !== undefined && modelData !== null && typeof modelData === "object" ? String(modelData[control.textRole]) : String(modelData)
        width: ListView.view ? ListView.view.width : implicitWidth
        implicitHeight: 36
        leftPadding: 16
        rightPadding: 12
        hoverEnabled: true
        highlighted: control.highlightedIndex === index
        font: control.font
        Accessible.role: Accessible.ListItem
        Accessible.name: itemText
        contentItem: Text {
            text: item.itemText
            font: item.font
            color: Theme.textPrimary
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            textFormat: Text.PlainText
        }
        background: Rectangle {
            anchors.fill: parent
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            anchors.topMargin: 2
            anchors.bottomMargin: 2
            radius: Metrics.radiusControl
            color: item.pressed ? Theme.subtlePressed : (item.highlighted || item.hovered || control.currentIndex === item.index ? Theme.subtleHover : "transparent")
            Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
            Rectangle {
                visible: control.currentIndex === item.index
                width: 3
                height: 16
                radius: 1.5
                color: Theme.accent
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    indicator: PIcon {
        x: control.width - width - 12
        anchors.verticalCenter: control.verticalCenter
        name: "chevron_down"
        size: 12
        color: control.enabled ? Theme.textSecondary : Theme.disabled
        rotation: control.popup.visible && Motion.moves ? 180 : 0
        Behavior on rotation { enabled: Motion.moves; NumberAnimation { duration: Motion.menu; easing.type: Motion.decelerate } }
    }

    contentItem: Text {
        text: control.currentIndex >= 0 ? control.displayText : control.placeholder
        font: control.font
        color: !control.enabled ? Theme.disabled : (control.currentIndex >= 0 ? Theme.textPrimary : Theme.textSecondary)
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }

    background: Rectangle {
        implicitWidth: control.preferredWidth
        implicitHeight: Metrics.controlHeight
        radius: Metrics.radiusControl
        color: !control.enabled ? Theme.controlDisabled : (control.pressed ? Theme.controlPressed : (control.hovered ? Theme.controlHover : Theme.control))
        border.width: 1
        border.color: Theme.controlStroke
        Behavior on color { enabled: Motion.enabled; ColorAnimation { duration: Motion.fast } }
        Rectangle {
            visible: control.enabled
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: Metrics.radiusControl
            anchors.rightMargin: Metrics.radiusControl
            height: 1
            color: Theme.controlEdge
            opacity: 0.8
        }
        PFocusRing { visible: control.visualFocus }
    }

    popup: T.Popup {
        id: pop
        y: control.height + 4
        width: Math.max(control.width, 160)
        implicitHeight: Math.min(list.contentHeight + topPadding + bottomPadding, 360)
        topPadding: 4
        bottomPadding: 4
        margins: 8
        transformOrigin: Item.Top
        contentItem: ListView {
            id: list
            PWheelScroll { flickable: list }  // Mausrad: gleiche Strecke je Raste, Rasten addieren sich
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            highlightMoveDuration: 0
            boundsBehavior: Flickable.StopAtBounds
            T.ScrollBar.vertical: PScrollBar {}
        }
        background: Rectangle {
            color: Theme.flyout
            border.color: Theme.flyoutStroke
            radius: Metrics.radiusOverlay
            PShadow { radius: Metrics.radiusOverlay }
        }
        enter: Transition {
            ParallelAnimation {
                NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Motion.menu; easing.type: Motion.decelerate }
                NumberAnimation { property: "y"; from: control.height + 4 - Motion.menuShift; to: control.height + 4; duration: Motion.menu; easing.type: Motion.decelerate }
            }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Motion.enabled ? 83 : 0; easing.type: Motion.accelerate }
        }
    }

    PToolTip {
        text: control.tip
        visible: control.tip !== "" && control.hovered && !control.popup.visible
    }
}
