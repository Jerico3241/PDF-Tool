import QtQuick
import PdfTool.Style

// Kontextmenü für Eingabefelder: Ausschneiden, Kopieren, Einfügen, Alles auswählen.
// ``pasteHandler``: eigene Einfügefunktion (z. B. nur reiner Text in Kopf-/Fußzeile).
PMenu {
    id: menu
    property Item target: null
    property var pasteHandler: null
    // Passwortfelder: nichts ausschneiden oder kopieren
    readonly property bool hidden: target !== null && target.echoMode !== undefined && target.echoMode !== TextInput.Normal
    PMenuItem {
        text: "Ausschneiden"
        iconName: ""
        enabled: menu.target && !menu.target.readOnly && menu.target.selectedText !== "" && !menu.hidden
        onTriggered: menu.target.cut()
    }
    PMenuItem {
        text: "Kopieren"
        enabled: menu.target && menu.target.selectedText !== "" && !menu.hidden
        onTriggered: menu.target.copy()
    }
    PMenuItem {
        text: "Einfügen"
        enabled: menu.target && !menu.target.readOnly && (menu.target.canPaste === undefined || menu.target.canPaste)
        onTriggered: {
            if (menu.pasteHandler) menu.pasteHandler()
            else menu.target.paste()
        }
    }
    PMenuItem {
        text: "Alles auswählen"
        enabled: menu.target && menu.target.length > 0
        onTriggered: menu.target.selectAll()
    }
}
