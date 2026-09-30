pragma Singleton
import QtQuick
import PdfTool.Backend

// Schriftstufen nach Windows 11: Segoe UI Variable (Text/Display), sonst Segoe UI bzw. Systemschrift.
QtObject {
    readonly property string family: ThemeBackend.fontFamily || Qt.application.font.family
    readonly property string displayFamily: ThemeBackend.displayFamily || family

    readonly property font caption: Qt.font({ family: family, pixelSize: 12 })
    readonly property font body: Qt.font({ family: family, pixelSize: 14 })
    readonly property font bodyStrong: Qt.font({ family: family, pixelSize: 14, weight: Font.DemiBold })
    readonly property font bodyLarge: Qt.font({ family: family, pixelSize: 18 })
    readonly property font subtitle: Qt.font({ family: displayFamily, pixelSize: 20, weight: Font.DemiBold })
    readonly property font title: Qt.font({ family: displayFamily, pixelSize: 28, weight: Font.DemiBold })
    readonly property font display: Qt.font({ family: displayFamily, pixelSize: 40, weight: Font.DemiBold })

    readonly property int lineCaption: 16
    readonly property int lineBody: 20
    readonly property int lineBodyLarge: 24
    readonly property int lineSubtitle: 28
    readonly property int lineTitle: 36
}
