"""Updates in der Oberfläche (QML: ``Updates``): Einstellungen, Details, Installation.

Die Logik steckt im ``updater``-Paket (``UpdateService``); hier entstehen nur Texte, die
sichtbaren Aktionen und die Verbindung zur App:

* Einstellungen → Updates: Version, Schalter »Beta-Versionen erhalten« (aus: Kanal Stable, an:
  Beta – gespeichert wie bisher als ``update_kanal``), automatische Prüfung und Installation, letzte
  Prüfung. Ein Knopf je Zustand: »Nach Updates suchen«, nach einem Fund »Jetzt installieren« (lädt,
  prüft und installiert in einem Schritt), während des Downloads »Abbrechen«. Die Release Notes stehen
  direkt in der Karte (seit 4.0 Beta 7; die Hinweisleiste über den Seiten gibt es nicht mehr).
* Automatische Prüfung: bei jedem Start im Hintergrund (danach höchstens alle 24 Stunden, solange die
  App offen bleibt) – der Programmstart wartet nie auf das Netzwerk; offline passiert still nichts.
* Automatische Installation (Standard, seit 4.0 Beta 7): ein gefundenes Update wird im Hintergrund
  geladen und installiert, Novadesk startet danach neu und öffnet die PDFs wieder. Gewartet wird, solange
  eine Verarbeitung läuft oder ein Dokument ungespeicherte Änderungen hat – nie geht etwas verloren.
* »Jetzt installieren«: nicht während einer Verarbeitung (Hinweis statt Abbruch). Sonst: Setup
  erneut prüfen, Hilfsprozess starten, App beenden wie über das Schließen-Kreuz (Einstellungen
  werden gespeichert) – das Setup läuft danach still (nur ein Fortschrittsfenster) und Novadesk
  startet neu.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from appstate import VERSION
from diagnostics.applog import INSTALLER
from diagnostics.applog import get as get_log
from updater import github, notes, schedule
from updater import store as store_module
from updater.installer import Launcher
from updater.models import Channel, ErrorKind, UpdateState
from updater.policy import UrlPolicy
from updater.semver import Version
from updater.service import UpdateService
from updater.store import UpdateStore
from updater.transport import HttpClient

from . import files
from .base import Observable, prop

S = UpdateState
START_DELAY_MS = 4000  # automatische Prüfung erst einige Sekunden nach dem ersten Bild
PERIODIC_MS = 60 * 60 * 1000  # stündlich nachsehen, ob 24 Stunden vergangen sind (App bleibt lange offen)
AUTO_DOWNLOAD = True  # gefundenes Update bei eingeschalteter automatischer Prüfung gleich laden (Tests: aus)
AUTO_INSTALL_RETRY_MS = 30_000  # automatische Installation wartet (Verarbeitung, ungespeichert): erneut versuchen
AUTO_INSTALL_START_MS = 2_000  # … oder bis die App fertig gestartet ist und alle PDFs geöffnet sind (zählt nicht als Versuch)
AUTO_INSTALL_TRIES = 20  # höchstens so oft je Sitzung – sonst beim nächsten Start (das Update ist dann schon geladen)

BETA_TITLE = "Beta-Versionen verwenden?"
BETA_TEXT = "Beta-Versionen enthalten Funktionen und Änderungen, die noch getestet werden. Sie können instabiler sein als Stable-Versionen."
BETA_CONFIRM = "Beta verwenden"
BETA_NEWER = "Sie verwenden derzeit eine neuere Beta-Version. Ein Wechsel auf den Stable-Kanal wirkt sich erst aus, sobald eine neuere Stable-Version verfügbar ist."
WORK_RUNNING = "Es läuft noch eine Verarbeitung. Bitte warten Sie, bis diese abgeschlossen ist, oder brechen Sie sie ab."
CHECKING = "Nach Updates wird gesucht …"
UP_TO_DATE = "Novadesk ist aktuell."
VERIFYING = "Update wird überprüft …"
READY = "Update ist bereit zur Installation."
INSTALLING = "Novadesk wird aktualisiert und startet danach neu …"
CANCELLED = "Download abgebrochen."
WAITING_UNSAVED = "Das Update wird installiert, sobald alle Dokumente gespeichert sind."
ERRORS = {
    ErrorKind.CHECK_FAILED: ("Updates konnten derzeit nicht geprüft werden.", "Bitte die Internetverbindung prüfen und später erneut versuchen."),
    ErrorKind.RATE_LIMITED: ("Updates konnten derzeit nicht geprüft werden.", "GitHub hat gerade zu viele Anfragen aus diesem Netzwerk erhalten. Bitte später erneut versuchen."),
    ErrorKind.DOWNLOAD_FAILED: ("Das Update konnte nicht vollständig heruntergeladen werden.", "Es wurde nichts installiert."),
    ErrorKind.VERIFY_FAILED: ("Das heruntergeladene Update konnte nicht verifiziert werden und wurde daher nicht installiert.", "Die Datei wurde gelöscht."),
    ErrorKind.INSTALL_FAILED: ("Das Setup konnte nicht gestartet werden.", "Novadesk bleibt geöffnet."),
}
OFFER_ERRORS = (ErrorKind.DOWNLOAD_FAILED, ErrorKind.VERIFY_FAILED, ErrorKind.INSTALL_FAILED)


# --- Fabriken (Tests ersetzen sie: kein Netzwerk, kein echter Hilfsprozess) ------------------------------------------


def create_service(app, installed: Version) -> UpdateService:
    """Der Updater der App: nur HTTPS zu GitHub, Downloads in ``%LOCALAPPDATA%\\PDF-Tool-Updates``."""
    client = HttpClient(UrlPolicy.github(), user_agent=f"PDF-Tool/{VERSION} (Windows)")
    return UpdateService(installed, client, UpdateStore(store_module.default_dir()), app.worker.run)


def create_launcher() -> Launcher:
    return Launcher()


# --- Anzeige ---------------------------------------------------------------------------------------------------------


def size_text(size: int) -> str:
    """Wie im Rest der App: »54,7 MB«."""
    value = float(max(0, size))
    for unit in ("Byte", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} Byte" if unit == "Byte" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{size} Byte"


def progress_text(received: int, total: int) -> str:
    if total <= 0:
        return size_text(received)
    percent = int(min(100, max(0, received * 100 // total)))
    return f"{size_text(received)} von {size_text(total)} · {percent} %"


def date_text(moment: datetime | None) -> str:
    return moment.astimezone().strftime("%d.%m.%Y") if moment else ""


def when_text(moment: datetime | None, now: datetime | None = None) -> str:
    """»Heute, 11:30«, »Gestern, 18:02«, sonst »28.09.2026, 08:15« (Ortszeit)."""
    if moment is None:
        return "Noch nie"
    local = moment.astimezone()
    today = (now or schedule.now_utc()).astimezone().date()
    clock = local.strftime("%H:%M")
    if local.date() == today:
        return f"Heute, {clock}"
    if local.date() == today - timedelta(days=1):
        return f"Gestern, {clock}"
    return f"{local.strftime('%d.%m.%Y')}, {clock}"


class UpdatesController(Observable):
    """In QML: ``Updates``."""

    stateChanged, state = prop(str, "state", "idle")
    channelChanged, channel = prop(str, "channel", "stable")
    automaticChanged, automatic = prop(bool, "automatic", True)
    lastCheckChanged, lastCheck = prop(str, "lastCheck", "Noch nie")
    statusTitleChanged, statusTitle = prop(str, "statusTitle", "")
    statusTextChanged, statusText = prop(str, "statusText", "")
    statusKindChanged, statusKind = prop(str, "statusKind", "neutral")  # neutral, busy, success, info, warning, error
    hasOfferChanged, hasOffer = prop(bool, "hasOffer", False)
    offerTitleChanged, offerTitle = prop(str, "offerTitle", "")  # »Novadesk 1.2.3-beta.2«
    offerLabelChanged, offerLabel = prop(str, "offerLabel", "")  # »1.2.3 Beta 2«
    offerBetaChanged, offerBeta = prop(bool, "offerBeta", False)
    offerDateChanged, offerDate = prop(str, "offerDate", "")
    offerSizeChanged, offerSize = prop(str, "offerSize", "")
    progressChanged, progress = prop(float, "progress", 0.0)
    progressTextChanged, progressText = prop(str, "progressText", "")
    canCheckChanged, canCheck = prop(bool, "canCheck", True)
    canDownloadChanged, canDownload = prop(bool, "canDownload", False)
    canCancelChanged, canCancel = prop(bool, "canCancel", False)
    canInstallChanged, canInstall = prop(bool, "canInstall", False)
    hintChanged, hint = prop(str, "hint", "")  # Beta → Stable
    workHintChanged, workHint = prop(str, "workHint", "")  # laufende Verarbeitung
    autoInstallChanged, autoInstall = prop(bool, "autoInstall", True)  # gefundenes Update selbst installieren
    actionChanged, action = prop(str, "action", "check")  # Knopf der Karte: check, install, cancel
    notesChanged, notes = prop(list, "notes", [])  # Release Notes des Angebots (geprüfte Blöcke, ``updater.notes``)

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.installed = Version.coerce(VERSION)
        self._beta_confirmed = cfg.get("update_beta_bestaetigt") is True
        self._helper = None
        self._fetched = ""  # Version, die in dieser Sitzung schon automatisch geladen wurde
        self._install_wanted = False  # »Jetzt installieren« vor dem Download: nach dem Laden gleich installieren
        self._auto_wanted = False  # automatisch gefunden und geladen: ohne Klick installieren
        self._auto_tries = 0
        self._auto_installing = False  # die laufende Installation kam ohne Klick: nach dem Neustart die PDFs wieder öffnen
        self.backup = None  # BackupController: Sicherung vor der Installation
        self.reader = None  # ReaderController: ungespeicherte Dokumente, PDFs nach dem Neustart wieder öffnen
        self.set_quietly("channel", Channel.from_config(cfg.get("update_kanal")).value)
        self.set_quietly("automatic", cfg.get("update_automatisch") is not False)
        self.set_quietly("autoInstall", cfg.get("update_auto_installieren") is not False)
        self.service = create_service(app, self.installed)
        self.service.setParent(self)
        self.service.changed.connect(self._sync)
        self.service.progressChanged.connect(self._sync_progress)
        self.service.checked.connect(self._checked)
        self.service.restore(Channel(self.channel), schedule.parse_time(cfg.get("update_letzte_pruefung")))
        self._periodic = QTimer(self)
        self._periodic.setInterval(PERIODIC_MS)
        self._periodic.timeout.connect(self._auto_check)
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._try_auto_install)
        app.register_config(self.config)
        app.at_shutdown(self.shutdown)
        app.observe("ready", self._app_ready)
        self._sync()

    # Konstante Angaben ------------------------------------------------------------------------------------------
    def _current_version(self) -> str:
        return str(self.installed)

    def _current_beta(self) -> bool:
        return self.installed.is_prerelease

    _constant = Signal()
    currentVersion = Property(str, _current_version, notify=_constant)
    currentBeta = Property(bool, _current_beta, notify=_constant)

    # Schalter »Beta-Versionen erhalten«: an = Kanal Beta (folgt ``channel``)
    def _beta(self) -> bool:
        return self.channel == Channel.BETA.value

    beta = Property(bool, _beta, notify=channelChanged)

    # Speichern ----------------------------------------------------------------------------------------------------
    def config(self) -> dict:
        last = self.service.last_check
        return {
            "update_kanal": self.channel,
            "update_automatisch": bool(self.automatic),
            "update_auto_installieren": None if self.autoInstall else False,
            "update_letzte_pruefung": schedule.format_time(last) if last else None,
            "update_beta_bestaetigt": True if self._beta_confirmed else None,
        }

    # Automatische Prüfung -------------------------------------------------------------------------------------------
    def _app_ready(self, ready: bool) -> None:
        if not ready:
            return
        self._periodic.start()
        self.app.timers.later("update-auto", START_DELAY_MS, self._start_check)

    def _start_check(self) -> None:
        """Bei jedem Start (seit 4.0 Beta 7): nachsehen – ein schon geladenes Update wird gleich installiert."""
        if not self.automatic:
            return
        if self.service.state is S.READY:
            self._auto_wanted = True
            self._sync()
            return
        self.service.check(manual=False)

    def _auto_check(self) -> None:
        """Solange die App offen bleibt: höchstens alle 24 Stunden – gezählt ab der letzten erfolgreichen Prüfung."""
        if self.automatic and schedule.due(self.service.last_check):
            self.service.check(manual=False)

    def _checked(self) -> None:
        self.lastCheck = when_text(self.service.last_check)
        self.app.persist()

    # Aktionen (QML) -------------------------------------------------------------------------------------------------
    @Slot()
    def checkNow(self) -> None:  # noqa: N802 - QML-Schreibweise
        """»Nach Updates suchen«: immer sofort (ohne 24-Stunden-Sperre)."""
        self.workHint = ""
        self.service.check(manual=True)

    @Slot(bool)
    def setBeta(self, enabled: bool) -> None:  # noqa: N802
        """Schalter »Beta-Versionen erhalten«: an → Kanal Beta (beim ersten Mal mit Rückfrage), aus → Stable."""
        self.setChannel(Channel.BETA.value if enabled else Channel.STABLE.value)

    @Slot(str)
    def setChannel(self, value: str) -> None:  # noqa: N802
        if value not in ("stable", "beta") or value == self.channel:
            return
        channel = Channel(value)
        if channel is Channel.BETA and not self._beta_confirmed:
            if not self.app.dialogs.confirm(BETA_TITLE, BETA_TEXT, BETA_CONFIRM, danger=False):
                self.channelChanged.emit()  # Schalter in QML wieder auf den gespeicherten Kanal
                return
            self._beta_confirmed = True
        self.channel = channel.value
        self.service.set_channel(channel)
        self.app.persist()
        self.app.set_status("Beta-Versionen erhalten: " + ("eingeschaltet (Kanal Beta)" if channel is Channel.BETA else "ausgeschaltet (Kanal Stable)"), "success")
        if channel is Channel.BETA and self.automatic:
            self.service.check(manual=True)  # gleich nachsehen, ob es eine Beta gibt
        self._sync()

    @Slot(bool)
    def setAutomatic(self, enabled: bool) -> None:  # noqa: N802
        if bool(enabled) == self.automatic:
            return
        self.automatic = bool(enabled)
        self.app.persist()
        self.app.set_status("Automatische Update-Prüfung " + ("eingeschaltet" if enabled else "ausgeschaltet"), "success")
        if enabled:
            self.app.timers.later("update-auto", 1500, self._auto_check)
        self._sync()

    @Slot(bool)
    def setAutoInstall(self, enabled: bool) -> None:  # noqa: N802
        if bool(enabled) == self.autoInstall:
            return
        self.autoInstall = bool(enabled)
        if not enabled:
            self._auto_wanted = False
            self._auto_timer.stop()
        self.app.persist()
        self.app.set_status("Updates automatisch installieren: " + ("eingeschaltet" if enabled else "ausgeschaltet"), "success")
        self._sync()

    @Slot()
    def download(self) -> None:
        self.workHint = ""
        self.service.download()

    @Slot()
    def cancel(self) -> None:
        self._install_wanted = self._auto_wanted = False
        self._auto_timer.stop()
        self.service.cancel()

    @Slot()
    def act(self) -> None:
        """Der Knopf der Update-Karte: suchen, installieren (auch ohne vorherigen Download) oder abbrechen."""
        if self.action == "cancel":
            self.cancel()
        elif self.action == "install":
            self.installNow()
        else:
            self.checkNow()

    @Slot()
    def showDetails(self) -> None:  # noqa: N802
        offer = self.service.offer
        if offer is None:
            return
        state = self.service.state
        primary = "Jetzt installieren" if self.canDownload or state is S.READY else ""
        data = {
            "version": str(offer.version),
            "label": offer.version.label(),
            "beta": offer.is_beta,
            "channel": "Beta" if self.channel == "beta" else "Stable",
            "installed": str(self.installed),
            "date": date_text(offer.published),
            "size": size_text(offer.installer.size) if offer.installer else "",
            "blocks": notes.render(offer.notes),
            "page": offer.page if notes.safe_link(offer.page) else "",
        }
        answer, _result = self.app.dialogs.ask("update_details", f"Novadesk {offer.version}", primary=primary, close="Später", data=data, width=600)
        if answer != "primary":
            return
        if primary == "Jetzt installieren":
            self.installNow()

    @Slot(str)
    def openLink(self, url: str) -> None:  # noqa: N802
        """Link aus den Release Notes – nur nach einem Klick, nur https, im Standardbrowser."""
        if not notes.safe_link(url):
            self.app.set_status("Dieser Link wird aus Sicherheitsgründen nicht geöffnet.", "warning")
            return
        if files.open_url(url):
            self.app.set_status("Link im Browser geöffnet.", "success")
        else:
            self.app.set_status("Der Link konnte nicht geöffnet werden.", "error")

    # Installation -------------------------------------------------------------------------------------------------------
    def _running_work(self) -> list[str]:
        return list(self.app.running_work())

    def _block_for_work(self, work: list[str]) -> None:
        self._auto_installing = False
        self.workHint = f"{WORK_RUNNING} ({', '.join(work)})" if work else WORK_RUNNING
        self.app.set_status(self.workHint, "warning")
        self._sync()

    @Slot()
    def installNow(self) -> None:  # noqa: N802
        """»Jetzt installieren«: noch nicht geladen → laden und prüfen, danach gleich installieren."""
        # Der Klick ersetzt eine wartende automatische Installation (sonst liefe sie während der Sicherung ein zweites Mal)
        self._auto_wanted = False
        self._auto_timer.stop()
        self._install(automatic=False)

    def _install(self, automatic: bool) -> None:
        self._auto_installing = automatic
        if self.service.state is not S.READY:
            if self.canDownload:
                self._install_wanted = True
                self.download()
            return
        self._install_wanted = False
        work = self._running_work()
        if work:
            self._block_for_work(work)
            return
        self.workHint = ""
        if self.backup is not None:
            # Vor jedem Update: aktueller Stand als Sicherung (im Hintergrund), dann die Installation
            self.app.set_status("Sicherung vor dem Update …", "busy")
            if not self.backup.backup_before_update(self._install_after_backup):
                self._block_for_work(["Sicherung"])
            return
        self.service.begin_install(self._launch)

    def _install_after_backup(self) -> None:
        if self.service.state is not S.READY:
            return
        work = self._running_work()
        if work:
            self._block_for_work(work)
            return
        self.service.begin_install(self._launch)

    def _try_auto_install(self) -> None:
        """Automatische Installation: nur ohne laufende Verarbeitung und ohne ungespeicherte Änderungen – sonst später
        noch einmal (höchstens ``AUTO_INSTALL_TRIES``-mal, danach beim nächsten Start)."""
        if not (self._auto_wanted and self.autoInstall and self.automatic) or self.service.state is not S.READY or self.app.closing:
            return
        reader = self.reader
        if not self.app.ready or (reader is not None and reader.still_opening()):
            # Ein schon geladenes Update ist beim Start sofort bereit: erst fertig starten und die PDFs öffnen (auch eine
            # per Doppelklick übergebene), sonst gingen sie beim Beenden für das Setup verloren
            self._auto_timer.start(AUTO_INSTALL_START_MS)
            return
        unsaved = self.reader.unsaved() if self.reader is not None else []
        work = self._running_work()
        if unsaved or work:
            self._auto_tries += 1
            self.workHint = WAITING_UNSAVED if unsaved and not work else (f"{WORK_RUNNING} ({', '.join(work)})" if work else WORK_RUNNING)
            if self._auto_tries < AUTO_INSTALL_TRIES:
                self._auto_timer.start(AUTO_INSTALL_RETRY_MS)
            else:
                self._auto_wanted = False  # nicht mehr in dieser Sitzung: »Jetzt installieren« bleibt, der nächste Start installiert
            self._sync()
            return
        self._auto_wanted = False
        get_log(INSTALLER).info("Automatische Installation von %s", self.offerTitle)
        self._install(automatic=True)

    def _launch(self, path, digest: str) -> None:
        """Setup geprüft: Hilfsprozess starten, dann die App beenden (das Setup startet danach)."""
        work = self._running_work()
        if work:
            self.service.install_aborted()
            self._block_for_work(work)
            return
        try:
            self._helper = create_launcher().start(path, digest, os.getpid(), path.parent / "update-start.log")
        except OSError as exc:
            get_log(INSTALLER).warning("Setup %s nicht gestartet: Hilfsprozess %s", path.name, type(exc).__name__)
            self.service.install_failed(str(exc))
            return
        get_log(INSTALLER).info("Installation von %s: Novadesk wird beendet, danach startet das Setup", path.name)
        if self.reader is not None and self._auto_installing:
            # erst jetzt, unmittelbar vor dem Beenden: Scheitert die Installation vorher, bleibt die Einstellung maßgeblich
            self.reader.restore_after_update = True
        if self._quit_app():
            return
        self._auto_installing = False
        if self.reader is not None:
            self.reader.restore_after_update = False
        # Beenden wurde abgelehnt (z. B. Rückfrage eines Werkzeugs): kein Setup, das Update bleibt bereit
        get_log(INSTALLER).info("Installation abgebrochen: Novadesk wurde nicht beendet – Hilfsprozess beendet, das Update bleibt bereit")
        helper, self._helper = self._helper, None
        try:
            helper.terminate()
        except (OSError, AttributeError):
            pass
        self.service.install_aborted()
        self.app.set_status("Installation abgebrochen – Novadesk bleibt geöffnet. Das Update bleibt bereit.", "info")

    def _quit_app(self) -> bool:
        """Wie über das Schließen-Kreuz: Werkzeuge räumen auf, Einstellungen werden gespeichert."""
        # Ganz beenden – auch wenn das Schließen-Kreuz Novadesk sonst im Hintergrund hält
        self.app.quit_wanted = True
        window = self.app.window
        if window is not None:
            window.close()
            closed = bool(self.app.closing)
        else:
            closed = self.app.requestClose()
        if not closed:
            self.app.quit_wanted = False
        return closed

    def shutdown(self) -> None:
        self._periodic.stop()
        self._auto_timer.stop()
        self.service.shutdown()

    # Anzeige ----------------------------------------------------------------------------------------------------------
    def _sync_progress(self) -> None:
        service = self.service
        total = service.total or (service.offer.installer.size if service.offer and service.offer.installer else 0)
        self.progress = min(1.0, service.received / total) if total else 0.0
        self.progressText = progress_text(service.received, total)
        if service.state is S.DOWNLOADING:
            self.statusText = self.progressText

    def _sync(self) -> None:
        service = self.service
        state = service.state
        offer = service.offer
        if AUTO_DOWNLOAD and state is S.AVAILABLE and offer is not None and self.automatic and self._fetched != str(offer.version):
            self._fetched = str(offer.version)  # einmal je Version: nach »Abbrechen« lädt nichts von selbst neu
            if service.download():
                self._auto_wanted = self.autoInstall  # fertig geladen: ohne Klick installieren
                self._auto_tries = 0  # eine neue Version bekommt wieder alle Versuche
                return  # der Download meldet sich mit seinem eigenen Zustand
        self.state = state.value
        self.lastCheck = when_text(service.last_check)
        self.hasOffer = offer is not None
        if offer is not None:
            self.offerTitle = f"Novadesk {offer.version}"
            self.offerLabel = offer.version.label()
            self.offerBeta = offer.is_beta
            self.offerDate = date_text(offer.published)
            self.offerSize = size_text(offer.installer.size) if offer.installer else ""
        else:
            self.offerTitle = self.offerLabel = self.offerDate = self.offerSize = ""
            self.offerBeta = False
        self.canCheck = state not in (S.CHECKING, S.DOWNLOADING, S.VERIFYING, S.INSTALLING)
        self.canDownload = offer is not None and (state in (S.AVAILABLE, S.CANCELLED) or (state is S.ERROR and service.error in OFFER_ERRORS))
        self.canCancel = state in (S.DOWNLOADING, S.VERIFYING)
        self.canInstall = state is S.READY
        self.hint = BETA_NEWER if self.installed.is_prerelease and self.channel == "stable" and offer is None else ""
        if state is not S.READY:
            self.workHint = ""  # der Hinweis gilt nur für »Jetzt installieren«
        if state in (S.CANCELLED, S.ERROR, S.UP_TO_DATE) or offer is None:
            self._install_wanted = self._auto_wanted = False
        self.notes = notes.render(offer.notes) if offer is not None else []
        if self.canCancel:
            self.action = "cancel"
        elif offer is not None and (self.canDownload or self.canInstall or state is S.INSTALLING):
            self.action = "install"
        else:
            self.action = "check"
        self._sync_progress()
        title, text, kind = self._status(state)
        self.statusTitle, self.statusText, self.statusKind = title, text, kind
        if state is S.READY and self._install_wanted:
            # erst nach dieser Meldung (Signale laufen noch) installieren
            self.app.timers.later("update-install", 0, self.installNow)
        elif state is S.READY and self._auto_wanted and not self._auto_tries:
            # automatische Installation: der erste Versuch gleich, weitere über den Zeitgeber
            self.app.timers.later("update-install", 0, self._try_auto_install)

    def _offer_line(self) -> str:
        parts = []  # »Beta« zeigt ein eigenes Etikett
        if self.offerDate:
            parts.append(f"Veröffentlicht am {self.offerDate}")
        if self.offerSize:
            parts.append(self.offerSize)
        return " · ".join(parts)

    def _status(self, state: UpdateState) -> tuple[str, str, str]:
        service = self.service
        if state is S.CHECKING:
            return CHECKING, "", "busy"
        if state is S.UP_TO_DATE:
            return UP_TO_DATE, f"Installierte Version: {self.installed}", "success"
        if state is S.AVAILABLE:
            return f"Novadesk {self.offerLabel} ist verfügbar.", self._offer_line(), "info"
        if state is S.DOWNLOADING:
            return f"Novadesk {self.offerLabel} wird heruntergeladen", self.progressText, "busy"
        if state is S.VERIFYING:
            return VERIFYING, "SHA-256-Prüfsumme wird mit dem Release verglichen.", "busy"
        if state is S.READY:
            return READY, f"Novadesk {self.offerLabel} · Prüfsumme bestätigt (SHA-256)", "success"
        if state is S.INSTALLING:
            return INSTALLING, "", "busy"
        if state is S.CANCELLED:
            return CANCELLED, "Das Update bleibt verfügbar.", "neutral"
        if state is S.ERROR:
            title, text = ERRORS.get(service.error, ("Unbekannter Fehler.", ""))
            return title, text, "error"
        # IDLE
        if service.auto_failed:
            return "Noch keine Update-Prüfung möglich.", "Die automatische Prüfung war ohne Internetverbindung nicht möglich.", "neutral"
        if not self.automatic:
            return "Automatische Prüfung ist ausgeschaltet.", "Mit »Nach Updates suchen« jederzeit selbst prüfen.", "neutral"
        return "Noch nicht nach Updates gesucht.", "Die erste Prüfung erfolgt kurz nach dem Start im Hintergrund.", "neutral"
