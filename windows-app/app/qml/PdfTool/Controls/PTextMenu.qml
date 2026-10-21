import QtQuick
import PdfTool.Style
import PdfTool.Backend

// Kontextmenü für Eingabefelder: Ausschneiden, Kopieren, Einfügen, Alles auswählen.
// ``pasteHandler``: eigene Einfügefunktion (z. B. nur reiner Text in Kopf-/Fußzeile).
PMenu {
    id: menu
    property Item target: null
    property var pasteHandler: null
    // Passwortfelder: nichts ausschneiden oder kopieren
    readonly property bool hidden: target !== null && target.echoMode !== undefined && target.echoMode !== TextInput.Normal
    PMenuItem {
        text: I18n.tr("Ausschneiden", I18n.revision)
        iconName: ""
        enabled: menu.target && !menu.target.readOnly && menu.target.selectedText !== "" && !menu.hidden
        onTriggered: menu.target.cut()
    }
    PMenuItem {
        text: I18n.tr("Kopieren", I18n.revision)
        enabled: menu.target && menu.target.selectedText !== "" && !menu.hidden
        onTriggered: menu.target.copy()
    }
    PMenuItem {
        text: I18n.tr("Einfügen", I18n.revision)
        enabled: menu.target && !menu.target.readOnly && (menu.target.canPaste === undefined || menu.target.canPaste)
        onTriggered: {
            if (menu.pasteHandler) menu.pasteHandler()
            else menu.target.paste()
        }
    }
    PMenuItem {
        text: I18n.tr("Alles auswählen", I18n.revision)
        enabled: menu.target && menu.target.length > 0
        onTriggered: menu.target.selectAll()
    }
}
