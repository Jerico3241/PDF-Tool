import QtQuick
import QtQuick.Layouts
import PdfTool.Backend
import PdfTool.Style
import PdfTool.Controls

// »Backup-Center« (seit 5.0 Beta 7): oben die Einstellungen der Sicherung, darunter links die Dokumente mit
// Fassungen, rechts die Fassungen des gewählten Dokuments mit Öffnen, Wiederherstellen und Löschen.
PPage {
    id: page
    objectName: "versionsPage"
    title: I18n.tr("Backup-Center", I18n.revision)
    subtitle: I18n.tr("Frühere Fassungen Ihrer Dokumente – vor jedem Speichern und automatisch während der Arbeit gesichert.", I18n.revision)

    function indexOfKey(list, key) {
        for (var i = 0; i < list.length; ++i)
            if (list[i].key === key) return i
        return -1
    }

    PInfoBar { Layout.fillWidth: true; notice: Notices.area("versions_info"); topMargin: 0 }

    PSettingsCard {
        objectName: "versionsSettings"
        Layout.fillWidth: true
        iconName: "history"
        title: I18n.tr("Fassungen sichern", I18n.revision)
        description: I18n.tr(Versions.lastAuto !== "" ? "Zuletzt automatisch gesichert: " + Versions.lastAuto + " Uhr" : "Vor jedem Speichern und alle paar Minuten, solange ein Dokument ungespeicherte Änderungen hat.", I18n.revision)
        expandable: true
        expanded: true
        PToggle {
            objectName: "versionsEnabled"
            label: I18n.tr("Fassungen sichern", I18n.revision)
            checked: Versions.enabled
            onToggled: Versions.setEnabled(checked)
        }
        extra: Flow {
            width: parent ? parent.width - 68 : 300
            spacing: 16
            PComboBox {
                objectName: "versionsMinutes"
                label: I18n.tr("Automatisch sichern", I18n.revision)
                preferredWidth: 200
                enabled: Versions.enabled
                model: Versions.intervalChoices()
                textRole: "label"
                valueRole: "key"
                currentIndex: page.indexOfKey(model, Versions.minutes)
                onActivated: (index) => Versions.setMinutes(model[index].key)
            }
            PComboBox {
                objectName: "versionsKeep"
                label: I18n.tr("Höchstens", I18n.revision)
                preferredWidth: 260
                enabled: Versions.enabled
                model: Versions.keepChoices()
                textRole: "label"
                valueRole: "key"
                currentIndex: page.indexOfKey(model, Versions.keep)
                onActivated: (index) => Versions.setKeep(model[index].key)
            }
            PComboBox {
                objectName: "versionsDays"
                label: I18n.tr("Aufbewahren", I18n.revision)
                preferredWidth: 160
                enabled: Versions.enabled
                model: Versions.dayChoices()
                textRole: "label"
                valueRole: "key"
                currentIndex: page.indexOfKey(model, Versions.days)
                onActivated: (index) => Versions.setDays(model[index].key)
            }
        }
    }

    PEmptyState {
        objectName: "versionsEmpty"
        Layout.fillWidth: true
        Layout.preferredHeight: 260
        visible: Versions.documents.length === 0 && !Versions.loading
        iconName: "history"
        title: I18n.tr("Noch keine Fassungen", I18n.revision)
        text: I18n.tr("Sobald Sie ein Dokument in Novadesk speichern, erscheint hier sein vorheriger Stand.", I18n.revision)
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: 12
        visible: Versions.documents.length > 0
        columns: page.columns
        columnSpacing: 12
        rowSpacing: 12

        PCard {
            objectName: "versionsDocuments"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            title: I18n.tr("Dokumente", I18n.revision)
            subtitle: I18n.tr(Versions.totalText, I18n.revision)
            iconName: "document_multiple"
            headerRight: [
                PButton { objectName: "versionsOpenStore"; kind: "subtle"; iconName: "folder_open"; text: I18n.tr("Ablage öffnen", I18n.revision); onClicked: Versions.openFolder() }
            ]
            Repeater {
                model: Versions.documents
                Item {
                    required property var modelData
                    required property int index
                    objectName: "versionsDocument_" + index
                    Layout.fillWidth: true
                    implicitHeight: docRow.implicitHeight + 12
                    PListItem {
                        anchors.fill: parent
                        hovered: docMouse.containsMouse
                        pressed: docMouse.pressed
                        selected: modelData.key === Versions.selected
                    }
                    RowLayout {
                        id: docRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 12
                        anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Image {
                            Layout.alignment: Qt.AlignTop
                            Layout.topMargin: 2
                            source: FileKinds.image(FileKinds.of(modelData.name), 16)
                            sourceSize: Qt.size(32, 32)
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            PText { Layout.fillWidth: true; text: I18n.tr(modelData.name, I18n.revision); elide: Text.ElideMiddle }
                            PText {
                                Layout.fillWidth: true
                                text: I18n.tr(modelData.exists ? modelData.countText + " · " + modelData.sizeText + " · " + modelData.folder : modelData.countText + " · Original nicht mehr vorhanden", I18n.revision)
                                textStyle: "caption"
                                tone: "secondary"
                                elide: Text.ElideMiddle
                            }
                        }
                    }
                    MouseArea {
                        id: docMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Versions.select(modelData.key)
                    }
                }
            }
        }

        PCard {
            objectName: "versionsList"
            Layout.fillWidth: true
            Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            title: I18n.tr("Fassungen", I18n.revision)
            subtitle: I18n.tr("Neueste zuerst. »Öffnen« zeigt eine Kopie – die Fassung selbst bleibt unverändert.", I18n.revision)
            iconName: "history"
            headerRight: [
                PIconButton { objectName: "versionsOriginalFolder"; iconName: "folder_open"; tip: I18n.tr("Ordner des Originals öffnen", I18n.revision); onClicked: Versions.openOriginalFolder() },
                PIconButton { objectName: "versionsDeleteAll"; iconName: "delete"; tip: I18n.tr("Alle Fassungen dieses Dokuments löschen", I18n.revision); onClicked: Versions.deleteDocument() }
            ]
            Repeater {
                model: Versions.versionList
                RowLayout {
                    required property var modelData
                    required property int index
                    objectName: "versionsVersion_" + index
                    Layout.topMargin: index > 0 ? 6 : 0
                    Layout.fillWidth: true
                    spacing: 8
                    PIcon { name: modelData.kind === "auto" ? "clock" : "save"; size: 16; color: Theme.textSecondary; Layout.alignment: Qt.AlignTop; Layout.topMargin: 4 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PText { Layout.fillWidth: true; text: I18n.tr(modelData.stamp, I18n.revision); elide: Text.ElideRight }
                        PText { Layout.fillWidth: true; text: I18n.tr(modelData.kindText + " · " + modelData.sizeText, I18n.revision); textStyle: "caption"; tone: "secondary"; elide: Text.ElideRight }
                    }
                    PBadge { text: I18n.tr("Neueste", I18n.revision); tone: "accent"; visible: modelData.newest }
                    PIconButton { iconName: "open"; tip: I18n.tr("Öffnen (als Kopie)", I18n.revision); onClicked: Versions.openVersion(modelData.path) }
                    PIconButton { iconName: "document_copy"; tip: I18n.tr("Als Kopie neben dem Original wiederherstellen", I18n.revision); onClicked: Versions.restoreCopy(modelData.path) }
                    PIconButton { iconName: "arrow_undo"; tip: I18n.tr("Original durch diese Fassung ersetzen", I18n.revision); onClicked: Versions.restoreReplace(modelData.path) }
                    PIconButton { iconName: "dismiss"; tip: I18n.tr("Diese Fassung löschen", I18n.revision); onClicked: Versions.deleteVersion(modelData.path) }
                }
            }
        }
    }
}
