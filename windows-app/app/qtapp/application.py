"""Start der Qt-Anwendung.

Reihenfolge (ohne weißes oder halb aufgebautes Fenster):

1. Konfiguration lesen
2. Qt-Anwendung anlegen (nötig für Systemfarben, Schriften und Bildschirme)
3. Design bestimmen (Hell/Dunkel, Akzentfarbe, Animationsprofil)
4. Kern-Dienste und Controller anlegen (Kundenakten nur, wenn eingeschaltet)
5. QML-Singletons und Bildquellen registrieren, QML laden – die Oberfläche entsteht
   vollständig, das Fenster bleibt verborgen
6. Fensterlage und Titelleiste setzen, Fenster verdeckt (DWM-Cloaking) zeigen, Startseite
7. Nach dem ersten fertig gezeichneten Bild aufdecken; weitere Seiten laden danach im Hintergrund
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, qmlRegisterSingletonType
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

import winsys
from appstate import APP_NAME, ICON_FILE, VERSION, load_config

from .app import AppController
from .geometry import WindowState, initial_placement
from .images import AppIconProvider, IconProvider, MicaProvider, PreviewProvider
from .settings import SettingsController
from .theme import ThemeController

QML_DIR = Path(__file__).resolve().parent.parent / "qml"
BACKEND_URI = "PdfTool.Backend"

# Meldungen der QML-Engine (Warnungen, Fehler) – Tests prüfen, dass keine auftreten.
MESSAGES: list[str] = []
# QML-Singletons (»App«, »Contracts« …): je Name einmal registriert; jede Engine erhält die
# Controller ihrer eigenen Laufzeit (in der App gibt es genau eine, in Tests nacheinander mehrere).
_REGISTERED: dict[str, type] = {}
_ENGINES: dict[int, dict[str, QObject]] = {}  # Kennung der Engine → Controller ihrer Laufzeit
_ENGINE_KEY = "pdftoolRuntime"
_engine_ids = iter(range(1, 1 << 30))


def _message_handler(mode, context, message) -> None:
    if mode == QtMsgType.QtDebugMsg:
        return
    text = str(message)
    if "qml" in text.lower() or (context is not None and context.file and str(context.file).endswith(".qml")) or mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        location = f"{context.file}:{context.line}: " if context is not None and context.file else ""
        MESSAGES.append(location + text)
        del MESSAGES[:-200]
    if os.environ.get("PDFTOOL_QML_DEBUG"):
        print(text, file=sys.stderr)


def qml_source() -> tuple[QUrl, str]:
    """Hauptdatei und Importpfad: aus den eingebauten Ressourcen (Setup), sonst aus dem Ordner ``qml``."""
    try:
        import qml_rc  # noqa: F401 - registriert die Ressourcen (erzeugt vom Build)
    except ImportError:
        return QUrl.fromLocalFile(str(QML_DIR / "Main.qml")), str(QML_DIR)
    return QUrl("qrc:/qml/Main.qml"), "qrc:/qml"


class Runtime(QObject):
    """Alle Controller der laufenden App. Sie leben länger als die QML-Engine."""

    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.cfg = cfg
        self.theme = ThemeController(cfg, self)
        self.app = AppController(cfg, self)
        self.app.theme = self.theme
        self.settings = SettingsController(self.app, self.theme, self)
        self.app.register_config(self.theme.config)
        self.singletons: dict[str, QObject] = {
            "ThemeBackend": self.theme,
            "App": self.app,
            "Settings": self.settings,
            "Dialogs": self.app.dialogs,
            "Notices": self.app.notices,
        }
        self.preview_lookup: Callable[[str], object] = lambda _ident: None
        self._build_tools()
        # Updates: Prüfung erst nach dem ersten Bild im Hintergrund – der Start wartet nie auf das Netzwerk
        from .updates import UpdatesController

        self.updates = UpdatesController(self.app, cfg, self)
        self.singletons["Updates"] = self.updates
        # Windows-Einstellungen (Design, Akzentfarbe, Animationseffekte) sofort übernehmen
        from . import system

        self.system_watcher = system.watch(self.app, self.theme)
        self.app.at_shutdown(lambda: system.unwatch(self.system_watcher))
        # Nach dem Start zeigt PDF Tool die Startseite mit allen Werkzeugen (fertig im ersten Bild).
        self.app.navigate("home")

    def _build_tools(self) -> None:
        """Werkzeuge einrichten (jedes mit eigenen Controllern)."""
        from .tools import build_tools

        build_tools(self)


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        QQuickStyle.setStyle("Basic")
        app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
    return app


def _provider(name: str) -> Callable[[QQmlEngine], QObject]:
    def provide(engine: QQmlEngine) -> QObject | None:
        singletons = _ENGINES.get(engine.property(_ENGINE_KEY) or 0)
        instance = singletons.get(name) if singletons else None
        if instance is not None:
            # Die Controller gehören der Laufzeit, nicht der Engine (die sie sonst beim Beenden löschte).
            QQmlEngine.setObjectOwnership(instance, QQmlEngine.ObjectOwnership.CppOwnership)
        return instance

    return provide


def register_backend(singletons: dict[str, QObject]) -> None:
    for name, instance in singletons.items():
        registered = _REGISTERED.get(name)
        if registered is None:
            qmlRegisterSingletonType(type(instance), BACKEND_URI, 1, 0, name, _provider(name))
            _REGISTERED[name] = type(instance)
        elif registered is not type(instance):
            raise TypeError(f"QML-Singleton {name}: {type(instance).__name__} statt {registered.__name__}")


def release_engine(engine: QQmlEngine) -> None:
    """Engine endet: ihre Singleton-Zuordnung entfernen (geschieht auch beim Löschen der Engine)."""
    _ENGINES.pop(engine.property(_ENGINE_KEY) or 0, None)


def _engine_warnings(errors) -> None:
    MESSAGES.extend(error.toString() for error in errors)
    del MESSAGES[:-200]


def create_engine(runtime: Runtime) -> QQmlApplicationEngine:
    register_backend(runtime.singletons)
    engine = QQmlApplicationEngine()
    key = next(_engine_ids)
    engine.setProperty(_ENGINE_KEY, key)
    _ENGINES[key] = dict(runtime.singletons)
    # Erst mit der Engine selbst endet die Zuordnung – auch Seiten, die sie noch im Hintergrund
    # lädt, erhalten bis dahin ihre Controller.
    engine.destroyed.connect(lambda _obj=None, key=key: _ENGINES.pop(key, None))
    engine.addImageProvider("icons", IconProvider())
    engine.addImageProvider("appicon", AppIconProvider(ICON_FILE))
    engine.addImageProvider("mica", MicaProvider(runtime.theme.mica))
    engine.addImageProvider("preview", PreviewProvider(lambda ident: runtime.preview_lookup(ident)))
    engine.warnings.connect(_engine_warnings)
    url, import_path = qml_source()
    engine.addImportPath(import_path)
    engine.load(url)
    return engine


def native_windows() -> bool:
    """Echte Windows-Fenster (Plattform »windows«) – nicht »offscreen« in Tests ohne Bildschirm."""
    return QGuiApplication.platformName() == "windows"


def finish_incubation(engine: QQmlEngine | None, timeout: float = 2.0) -> None:
    """Noch entstehende QML-Objekte (z. B. Seiten, die im Hintergrund laden) fertig bauen, bevor
    die Engine endet – ohne den Abbau mitten in ihrer Entstehung."""
    controller = engine.incubationController() if engine is not None else None
    if controller is None:
        return
    deadline = time.monotonic() + timeout
    while controller.incubatingObjectCount() > 0 and time.monotonic() < deadline:
        controller.incubateFor(20)


def show_window(runtime: Runtime, engine: QQmlApplicationEngine) -> QQuickWindow:
    """Fenster verdeckt zeigen und nach dem ersten fertigen Bild aufdecken."""
    roots = engine.rootObjects()
    if not roots:
        raise RuntimeError("Die Oberfläche konnte nicht geladen werden:\n" + "\n".join(MESSAGES[-10:]))
    window: QQuickWindow = roots[0]
    app = runtime.app
    app.window = window
    placement = initial_placement(runtime.cfg)
    state = WindowState(window, placement)
    state.apply()
    app.geometry = state
    hwnd = int(window.winId())  # natives Fenster anlegen (noch unsichtbar)
    app.apply_chrome()
    runtime.theme.darkChanged.connect(app.apply_chrome)
    runtime.theme.revisionChanged.connect(app.apply_chrome)
    cloaked = native_windows() and winsys.can_cloak() and winsys.set_cloak(hwnd, True)

    shown = False

    def first_frame() -> None:
        # Mehrere Bilder können schon eingereiht sein (QueuedConnection) – nur das erste zählt.
        nonlocal shown
        if shown:
            return
        shown = True
        window.frameSwapped.disconnect(first_frame)
        if cloaked:
            winsys.set_cloak(hwnd, False)
        app.after_start()

    window.frameSwapped.connect(first_frame, Qt.ConnectionType.QueuedConnection)
    if placement.maximized:
        window.showMaximized()
    else:
        window.show()
    return window


def main(argv: list[str] | None = None) -> int:
    winsys.register_app_identity()
    qInstallMessageHandler(_message_handler)
    cfg = load_config()
    qt_app = create_application(argv)
    runtime = Runtime(cfg)

    def report(kind, value, tb) -> None:
        # Unerwartete Fehler in Rückmeldungen: in fehler.log und in der Statuszeile, die App läuft weiter
        runtime.app.report_exception("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = report
    engine = create_engine(runtime)
    show_window(runtime, engine)
    code = qt_app.exec()
    runtime.app.shutdown()
    finish_incubation(engine)
    # Die QML-Engine endet vor den Controllern, an die ihre Bindungen gebunden sind.
    del engine
    sys.excepthook = sys.__excepthook__
    return code
