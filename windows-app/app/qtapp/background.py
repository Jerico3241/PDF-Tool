"""Im Hintergrund bereithalten: Symbol im Infobereich und Start mit Windows.

Der erste Start nach dem Hochfahren ist langsam (Windows lädt Python, Qt und die Oberfläche erst
von der Festplatte). Mit der Einstellung »Im Hintergrund bereithalten« (Standard: an)

- startet PDF Tool bei der Anmeldung unsichtbar (``PDF-Tool.exe --hintergrund``, Eintrag unter
  ``HKCU\\…\\Run``) und baut seine Oberfläche dabei schon auf,
- schließt das Schließen-Kreuz nur das Fenster: Dokumente werden wie beim Beenden geschlossen
  (mit Rückfrage bei ungespeicherten Änderungen), PDF Tool bleibt mit einem Symbol im
  Infobereich der Taskleiste,
- öffnet ein weiterer Start (Startmenü, Doppelklick auf eine PDF) sofort das vorhandene Fenster.

Beenden: Symbol im Infobereich → »Beenden«. Updates, Wiederherstellungen und das Abmelden von
Windows beenden PDF Tool wie bisher ganz. Ist die Einstellung aus, verhält sich PDF Tool wie
früher (kein Symbol, kein Autostart, das Schließen-Kreuz beendet).

Den Autostart-Eintrag setzt nur eine installierte App (``PDF-Tool.exe`` neben dem Ordner ``app``);
die Deinstallation entfernt ihn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject

import winsys
from appstate import APP_NAME, ICON_FILE
from handoff import BACKGROUND_ARGUMENT

SETTING = "hintergrund"  # gui-config.json; fehlt der Schlüssel: an
HINT_SHOWN = "hintergrund_hinweis"  # Hinweis »läuft im Hintergrund weiter« schon einmal gezeigt
ARGUMENT = BACKGROUND_ARGUMENT  # Start bei der Anmeldung: ohne Fenster
RUN_NAME = APP_NAME  # Name des Eintrags unter »Start mit Windows« (so zeigt ihn auch der Task-Manager)
LAUNCHER = "PDF-Tool.exe"
TITLE = "Im Hintergrund bereithalten"
TEXT = (
    "PDF Tool startet mit Windows unsichtbar und bleibt nach dem Schließen des Fensters im Infobereich der "
    "Taskleiste. So öffnet es sich danach sofort – auch beim ersten Mal nach dem Hochfahren."
)
NOTE = "Beenden über das PDF-Tool-Symbol im Infobereich (rechts unten) → »Beenden«. Ausgeschaltet beendet das Schließen-Kreuz PDF Tool wie bisher."
TRAY_RETRIES = 24  # Infobereich noch nicht da (Anmeldung): 2 Minuten lang alle 5 s nachsehen
TRAY_RETRY_MS = 5000
HIDDEN_TITLE = "PDF Tool läuft im Hintergrund weiter"
HIDDEN_TEXT = "So öffnet es sich beim nächsten Mal sofort. Beenden über dieses Symbol – ausschalten unter Einstellungen."


def enabled_in(cfg: dict) -> bool:
    return cfg.get(SETTING, True) is not False


def launcher_path(app_dir: Path | None = None) -> Path | None:
    """``PDF-Tool.exe`` der Installation – ``None`` im Quellbaum (dort gibt es keinen Autostart)."""
    folder = app_dir if app_dir is not None else Path(__file__).resolve().parent.parent
    exe = folder.parent / LAUNCHER
    return exe if exe.is_file() else None


def autostart_command(exe: Path) -> str:
    return f'"{exe}" {ARGUMENT}'


def sync_autostart(enabled: bool, exe: Path | None = None, read: Callable[[str], str | None] = winsys.run_entry, write: Callable[[str, str | None], bool] = winsys.set_run_entry) -> bool:
    """Eintrag unter »Start mit Windows« an die Einstellung angleichen (nur wenn nötig). True bei Erfolg."""
    exe = exe if exe is not None else launcher_path()
    if exe is None:
        return False
    wanted = autostart_command(exe) if enabled else None
    if read(RUN_NAME) == wanted:
        return True
    return bool(write(RUN_NAME, wanted))


class Background(QObject):
    """Einstellung, Symbol im Infobereich und Autostart. Aktiv erst mit ``attach()`` (nur in der
    echten App, nicht in Tests, die eine Laufzeit ohne Hauptschleife aufbauen)."""

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.enabled = enabled_in(cfg)
        self.hint_shown = cfg.get(HINT_SHOWN) is True
        self.tray = None
        self.attached = False
        self._retries = 0
        self._quit: Callable[[], None] = lambda: None
        self._tray_available: Callable[[], bool] = lambda: False
        app.register_config(self.config)

    def config(self) -> dict:
        return {SETTING: self.enabled, HINT_SHOWN: self.hint_shown or None}

    @property
    def active(self) -> bool:
        """Schließen-Kreuz versteckt nur das Fenster (Einstellung an und Infobereich vorhanden)."""
        return self.attached and self.enabled and self.tray is not None

    def attach(self, qt_app, tray_available: Callable[[], bool] | None = None, autostart: bool = True) -> None:
        """In der laufenden App: Symbol und Autostart nach der Einstellung einrichten."""
        from PySide6.QtWidgets import QSystemTrayIcon

        self.attached = True
        self._quit = qt_app.quit
        self._qt_app = qt_app
        self._tray_available = tray_available or QSystemTrayIcon.isSystemTrayAvailable
        self._autostart = autostart
        self.apply()

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        self.apply()

    def apply(self) -> None:
        if not self.attached or self.app.closing:
            return
        if self.enabled and self.tray is None:
            if self._tray_available():
                self.tray = self._create_tray()
            elif self._retries < TRAY_RETRIES:
                # Bei der Anmeldung ist die Taskleiste evtl. noch nicht bereit: später noch einmal versuchen
                from PySide6.QtCore import QTimer

                self._retries += 1
                QTimer.singleShot(TRAY_RETRY_MS, self, self.apply)
        elif not self.enabled and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        # Ohne Symbol im Infobereich gäbe es keinen Weg zurück zum Fenster: dann beendet das Kreuz wie bisher
        self._qt_app.setQuitOnLastWindowClosed(not self.active)
        if self._autostart:
            sync_autostart(self.enabled)

    def _create_tray(self):
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        tray = QSystemTrayIcon(QIcon(str(ICON_FILE)) if ICON_FILE.is_file() else self._qt_app.windowIcon(), self)
        tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction(f"{APP_NAME} öffnen", self.app.present_window)
        menu.addSeparator()
        menu.addAction("Beenden", self.app.quit_app)
        tray.setContextMenu(menu)
        tray._menu = menu  # Menü lebt so lange wie das Symbol
        tray.activated.connect(self._activated)
        tray.show()
        return tray

    def _activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.app.present_window()

    def hidden(self) -> None:
        """Fenster wurde versteckt: beim ersten Mal kurz erklären, wo PDF Tool jetzt ist."""
        if self.hint_shown or self.tray is None:
            return
        self.hint_shown = True
        from PySide6.QtWidgets import QSystemTrayIcon

        self.tray.showMessage(HIDDEN_TITLE, HIDDEN_TEXT, QSystemTrayIcon.MessageIcon.Information, 8000)

    def finished(self) -> None:
        """PDF Tool wurde beendet (Werkzeuge haben aufgeräumt): Symbol entfernen, Hauptschleife verlassen.
        Ohne Symbol endet die App wie bisher mit dem letzten Fenster."""
        if self.tray is not None:
            self.tray.hide()
        if self.active:
            self._quit()
