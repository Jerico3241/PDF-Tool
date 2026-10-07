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

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, qmlRegisterSingletonType
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

import winsys
from appstate import APP_NAME, ICON_FILE, VERSION, load_config

from .app import AppController, window_title
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
GC_TIME_LIMIT = "QV4_GC_TIMELIMIT"  # Zeitscheibe der QML-Speicherbereinigung in ms, 0 = in einem Zug
WHEEL_LINE_FACTOR = 4 / 3  # Mausrad: Qt rechnet 24 px je Zeile – wie Edge und Chrome rund 32 px (PWheelScroll)


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
        self.app.settings = self.settings
        self.app.register_config(self.theme.config)
        self.singletons: dict[str, QObject] = {
            "ThemeBackend": self.theme,
            "App": self.app,
            "Settings": self.settings,
            "Dialogs": self.app.dialogs,
            "Notices": self.app.notices,
        }
        self.preview_lookup: Callable[[str], object] = lambda _ident: None
        self.image_providers: dict[str, Callable[[], object]] = {}  # weitere Bildquellen der Werkzeuge (je Engine neu)
        self._build_tools()
        # Updates: Prüfung erst nach dem ersten Bild im Hintergrund – der Start wartet nie auf das Netzwerk
        from .updates import UpdatesController

        self.updates = UpdatesController(self.app, cfg, self)
        self.singletons["Updates"] = self.updates
        # Sicherung & Wiederherstellung, Diagnose (Einstellungen) – Arbeit im Hintergrund nach dem Start
        from .backups import BackupController
        from .diagnose import DiagnoseController

        self.backup = BackupController(self.app, self)
        self.diagnose = DiagnoseController(self.app, self.backup, self.updates, self)
        self.updates.backup = self.backup
        for controller in (self.backup, self.diagnose):
            self.app.register_work(controller.running_work)
        self.singletons["Backup"] = self.backup
        self.singletons["Diagnose"] = self.diagnose
        # KI-Assistent (optional, standardmäßig aus): lädt nichts, bis er eingeschaltet und eingerichtet ist
        from .assistant import AssistantController

        self.assistant = AssistantController(self.app, cfg, self)
        self.assistant.attach_reader(self.singletons["Reader"])
        self.singletons["Assistant"] = self.assistant
        self.app.observe("ready", lambda ready: (self.backup.start(), self.diagnose.start()) if ready else None)
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
    # Anzeigename = Fenstertitel (bei einer Beta »PDF Tool 2.8.0 Beta«): Qt hängt den Anzeigenamen
    # an jeden Fenstertitel an, der nicht auf ihn endet – im Hauptfenster stünde er sonst doppelt.
    app.setApplicationDisplayName(window_title(VERSION))
    app.setApplicationVersion(VERSION)
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
    tune_wheel(app)
    return app


def tune_wheel(app: QApplication) -> None:
    """Strecke je Mausrad-Raste wie in anderen Windows-Programmen: die Zeilenzahl aus den
    Windows-Einstellungen (Standard 3), je Zeile rund 32 px statt Qts 24 px – einmal je Anwendung."""
    if app.property("pdftoolWheel"):
        return
    app.setProperty("pdftoolWheel", True)
    hints = app.styleHints()
    lines = hints.wheelScrollLines()
    if 0 < lines < 100:  # »Eine Bildschirmseite« (sehr großer Wert) bleibt unverändert
        hints.setWheelScrollLines(max(1, round(lines * WHEEL_LINE_FACTOR)))


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
    # Speicherbereinigung der QML-Engine in einem Zug statt in Zeitscheiben (Qt liest die Variable
    # beim Anlegen der Engine). Mit der schrittweisen Bereinigung von Qt 6.11 können Objekte, die
    # beim Laden der Seiten im Hintergrund entstehen, ihre QML-Funktionen verlieren – ein
    # »Connections« stürzt dann beim Fertigstellen ab.
    os.environ.setdefault(GC_TIME_LIMIT, "0")
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
    for name, factory in runtime.image_providers.items():
        engine.addImageProvider(name, factory())
    engine.warnings.connect(_engine_warnings)
    url, import_path = qml_source()
    engine.addImportPath(import_path)
    engine.load(url)
    return engine


def native_windows() -> bool:
    """Echte Windows-Fenster (Plattform »windows«) – nicht »offscreen« in Tests ohne Bildschirm."""
    return QGuiApplication.platformName() == "windows"


def finish_incubation(engine: QQmlEngine | None, timeout: float = 2.0) -> None:
    """Noch entstehende QML-Objekte (z. B. Seiten, die im Hintergrund laden) fertig bauen und zum
    Löschen vorgemerkte (z. B. Tabs der beim Beenden geschlossenen PDFs) löschen, bevor die Engine
    endet – ohne den Abbau mitten in ihrer Entstehung und ohne Objekte, die ihre Engine überleben."""
    controller = engine.incubationController() if engine is not None else None
    if controller is None:
        return
    deadline = time.monotonic() + timeout
    while controller.incubatingObjectCount() > 0 and time.monotonic() < deadline:
        controller.incubateFor(20)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
        from diagnostics.applog import UI
        from diagnostics.applog import get as get_log

        get_log(UI).info("Oberfläche bereit: Fenster %d × %d, Skalierung %d %%", window.width(), window.height(), round(window.devicePixelRatio() * 100))
        app.after_start()

    window.frameSwapped.connect(first_frame, Qt.ConnectionType.QueuedConnection)
    if placement.maximized:
        window.showMaximized()
    else:
        window.show()
    return window


def prepare_data():
    """Vor dem Laden der Einstellungen: eine vorbereitete Wiederherstellung ausführen (oder eine
    unterbrochene zurücknehmen). Das Ergebnis zeigt die App nach dem Start an.

    Den beiseitegelegten bisherigen Stand (bei vielen Vertragsständen tausende Dateien) löscht ein
    Hintergrund-Thread – der Start wartet nicht darauf."""
    import threading

    from backup import restore
    from storage import data_root

    try:
        root = data_root()
        outcome = restore.apply_pending(root)
        if restore.leftovers(root):
            threading.Thread(target=restore.remove_leftovers, args=(root,), name="pdftool-wiederherstellung-reste", daemon=True).start()
        return outcome
    except Exception:  # noqa: BLE001 - der Start darf daran nie scheitern
        traceback.print_exc()
        return None


def start_log() -> None:
    """Protokoll ``pdf-tool.log`` im Datenordner einrichten und den Start vermerken."""
    import platform

    from appstate import VERSION
    from diagnostics import applog, info
    from storage import data_root

    applog.setup(data_root())
    try:
        from PySide6 import __version__ as pyside
        from PySide6.QtCore import qVersion

        qt = f"PySide6 {pyside}, Qt {qVersion()}"
    except Exception:  # noqa: BLE001
        qt = "Qt unbekannt"
    applog.get(applog.UI).info("PDF Tool %s gestartet (Python %s, %s, %s)", VERSION, platform.python_version(), qt, info.os_brief())


def main(argv: list[str] | None = None) -> int:
    winsys.register_app_identity()
    qInstallMessageHandler(_message_handler)
    start_log()
    outcome = prepare_data()
    if outcome is not None:
        from diagnostics.applog import get as get_log

        get_log("sicherung").log(20 if outcome.ok else 40, "Wiederherstellung beim Start: %s", outcome.message)
    cfg = load_config()
    qt_app = create_application(argv)
    # »Öffnen mit«: PDFs aus der Befehlszeile – läuft PDF Tool schon, öffnet die laufende App sie
    from . import instance

    paths = instance.pdf_arguments((argv if argv is not None else sys.argv)[1:])
    if paths:
        winsys.allow_foreground()
        if instance.forward(paths):
            return 0
    runtime = Runtime(cfg)
    if paths:
        # PDF per Doppelklick bzw. »Öffnen mit«: gleich im Reader beginnen – er ist im ersten Bild fertig,
        # ohne Umweg über die Startseite (sie lädt danach im Hintergrund wie die übrigen Seiten)
        runtime.app.navigate("reader")

    def report(kind, value, tb) -> None:
        # Unerwartete Fehler in Rückmeldungen: in fehler.log und in der Statuszeile, die App läuft weiter
        runtime.app.report_exception("".join(traceback.format_exception(kind, value, tb)))

    sys.excepthook = report
    engine = create_engine(runtime)
    window = show_window(runtime, engine)
    reader = runtime.reader.controller

    def open_received(received: list[str]) -> None:
        if window.visibility() == window.Visibility.Minimized:
            window.showNormal()
        window.raise_()
        window.requestActivate()
        reader.open_external(received)

    server = instance.InstanceServer(open_received, runtime)
    runtime.app.at_shutdown(server.close)
    if paths:
        reader.open_external(paths)
    code = qt_app.exec()
    runtime.app.shutdown()
    finish_incubation(engine)
    # Die QML-Engine endet vor den Controllern, an die ihre Bindungen gebunden sind.
    del engine
    sys.excepthook = sys.__excepthook__
    from diagnostics.applog import UI
    from diagnostics.applog import get as get_log

    get_log(UI).info("PDF Tool beendet")
    if getattr(runtime.app, "restart_requested", False):
        restart_app()
    return code


def restart_app() -> None:
    """PDF Tool neu starten (z. B. nach dem Vorbereiten einer Wiederherstellung). Erst wenn diese
    Instanz alles gespeichert hat – die neue liest beim Start den neuen Stand."""
    import subprocess

    args = [sys.executable, *sys.orig_argv[1:]] if getattr(sys, "orig_argv", None) else [sys.executable, *sys.argv]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(args, cwd=os.getcwd(), close_fds=True, creationflags=flags)
    except OSError:
        traceback.print_exc()
