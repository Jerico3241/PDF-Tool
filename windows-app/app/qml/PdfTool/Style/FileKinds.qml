pragma Singleton
import QtQuick

// Dateiarten von Novadesk (seit 5.0): Farbe und Symbol je Art – überall gleich (Tabs, Startseite, zuletzt verwendet)
// und wie im Explorer (assets/datei-*.ico). Die Symbole erzeugt windows-app/scripts/make_icons.py aus den SVG-Vorlagen.
QtObject {
    readonly property var colors: ({
        "pdf": "#D7263D",
        "text": "#1565E8",
        "tabelle": "#16A34A",
        "praesentation": "#F07A12",
        "csv": "#0F9488"
    })
    readonly property var labels: ({
        "pdf": "PDF",
        "text": "Text",
        "tabelle": "Tabelle",
        "praesentation": "Präsentation",
        "csv": "CSV"
    })

    // Zweite, dunklere Farbe für den Verlauf der Kachel (Tab-Dock, Entwurf 7)
    function deep(kind) { return Qt.darker(color(kind), 1.35) }
    function known(kind) { return colors[kind] !== undefined }
    function color(kind) { return known(kind) ? colors[kind] : Theme.accent }
    // Symbol in 16, 24, 32 oder 48 px (dazu @2x für hohe Auflösung – Qt wählt selbst)
    function image(kind, size) { return known(kind) ? Qt.resolvedUrl("../../images/" + kind + "-" + size + ".png") : "" }
    // Weiße Silhouette für die farbige Kachel im Tab-Dock (seit 5.0 Beta 10)
    function whiteImage(kind) { return known(kind) ? Qt.resolvedUrl("../../images/" + kind + "-white-16.png") : "" }
    // Dateiart aus dem Dateinamen (wie office.symbol in Python)
    function of(name) {
        var match = /\.([A-Za-z0-9]+)$/.exec(String(name || ""))
        var ext = match ? match[1].toLowerCase() : ""
        if (ext === "pdf") return "pdf"
        if (ext === "csv") return "csv"
        if (["doc", "docx", "docm", "odt", "rtf"].indexOf(ext) >= 0) return "text"
        if (["xls", "xlsx", "xlsm", "ods"].indexOf(ext) >= 0) return "tabelle"
        if (["ppt", "pptx", "pptm", "odp"].indexOf(ext) >= 0) return "praesentation"
        return ""
    }
    // Dateiname ohne bekannte Endung (das Symbol zeigt die Art)
    function stem(name) { return String(name || "").replace(/\.(pdf|docx?|docm|odt|rtf|xlsx?|xlsm|ods|csv|pptx?|pptm|odp)$/i, "") || String(name || "") }
}
