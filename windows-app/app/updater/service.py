"""Ablauf des Updaters: prüfen → herunterladen → verifizieren → bereit → Installation vorbereiten.

Der ``UpdateService`` hält den zentralen Zustand (``UpdateState``) und das aktuelle Angebot.
Er kennt keine Oberflächentexte – die bestimmt ``qtapp.updates`` aus Zustand und Fehlerart.

* **Prüfen** – eine Anfrage an die GitHub-API. Eine *automatische* Prüfung läuft unsichtbar
  im Hintergrund: Der Zustand ändert sich erst, wenn sie etwas Neues findet; ein Fehler (z. B.
  offline) bleibt still. Eine *manuelle* Prüfung zeigt ``CHECKING`` und meldet Fehler.
  Ergebnis und Zeitpunkt einer erfolgreichen Prüfung werden gespeichert (24-Stunden-Regel,
  Angebot auch nach einem Neustart).
* **Herunterladen** – erst die veröffentlichte Prüfsumme, dann das Setup als ``.part``-Datei
  im Update-Ordner; Fortschritt gedrosselt; abbrechbar (die Teil-Datei wird entfernt); nie
  zwei Downloads gleichzeitig. Ist das Setup schon vollständig geladen, wird es nur geprüft.
* **Verifizieren** – SHA-256 im Hintergrund-Thread; nur bei Übereinstimmung wird aus der
  Teil-Datei das Setup und der Zustand ``READY``. Sonst wird die Datei gelöscht (``ERROR``).
* **Installation vorbereiten** – Datei und Prüfsumme unmittelbar vorher erneut prüfen; den
  Start des Setups übernimmt der Aufrufer (``installer``) erst danach.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from . import github, schedule
from .models import Channel, ErrorKind, Release, UpdateState
from .semver import Version
from .state import StateMachine
from .store import UpdateStore
from .transport import HttpClient, Transfer, TransferError
from .verifier import ChecksumError, file_sha256, parse_checksum, same_digest

S = UpdateState
Background = Callable[[Callable[[], object], Callable[[object], None], Callable[[BaseException, str], None]], None]


class UpdateService(QObject):
    """Zustand und Ablauf. Signale: ``changed`` (Zustand, Angebot, Fehler), ``progressChanged``."""

    changed = Signal()
    progressChanged = Signal()
    checked = Signal()  # eine Prüfung ist erfolgreich abgeschlossen (Zeitpunkt speichern)

    def __init__(
        self,
        installed: Version,
        client: HttpClient,
        store: UpdateStore,
        background: Background,
        releases_url: str = github.RELEASES_URL,
        site: str = github.SITE,
        clock: Callable[[], datetime] = schedule.now_utc,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.installed = installed
        self.client = client
        self.store = store
        self.background = background
        self.releases_url = releases_url
        self.site = site
        self.clock = clock
        self.machine = StateMachine()
        self.channel = Channel.STABLE
        self.releases: list[Release] | None = None  # letzte erfolgreiche Prüfung (bzw. Zwischenspeicher)
        self.offer: Release | None = None
        self.error: ErrorKind | None = None
        self.error_detail = ""
        self.last_check: datetime | None = None  # letzte erfolgreiche Prüfung
        self.auto_failed = False  # letzte automatische Prüfung ohne Ergebnis (z. B. offline)
        self.received = 0
        self.total = 0
        self.checks = 0  # gestartete Anfragen an GitHub (Tests: 24-Stunden-Regel)
        self.downloads = 0  # gestartete Setup-Downloads (Tests: keine Doppeldownloads)
        self.closed = False
        self._check: Transfer | None = None
        self._check_manual = False
        self._transfer: Transfer | None = None
        self._expected = ""  # veröffentlichte Prüfsumme des laufenden Downloads
        self._token = 0  # erhöht sich bei Abbruch – verspätete Ergebnisse verfallen

    # Zustand ---------------------------------------------------------------------------------------------
    @property
    def state(self) -> UpdateState:
        return self.machine.state

    @property
    def busy(self) -> bool:
        """Läuft ein Download, eine Prüfung der Datei oder die Vorbereitung der Installation?"""
        return self.state in (S.DOWNLOADING, S.VERIFYING, S.INSTALLING)

    @property
    def checking(self) -> bool:
        return self._check is not None

    def _go(self, state: UpdateState) -> None:
        if state != self.state:
            self.machine.go(state)
        self.changed.emit()

    def _set_error(self, kind: ErrorKind | None, detail: str = "") -> None:
        self.error = kind
        self.error_detail = detail

    # Start ---------------------------------------------------------------------------------------------------
    def restore(self, channel: Channel, last_check: datetime | None) -> None:
        """Beim Start: Kanal, Zeitpunkt und Ergebnis der letzten Prüfung übernehmen (ohne Netzwerk).
        Ein bereits geladenes Setup wird im Hintergrund geprüft und ist danach wieder bereit."""
        self.channel = channel
        self.last_check = last_check
        releases, checked = self.store.load_releases()
        if checked is not None:
            self.releases = releases
        self._evaluate(fresh=False)
        keep = self.offer
        self.background(lambda: self.store.cleanup(keep), lambda _result: None, lambda _exc, _text: None)

    # Prüfen ---------------------------------------------------------------------------------------------------
    def check(self, manual: bool) -> bool:
        """Nach Updates suchen. Automatisch: unsichtbar und still; manuell: sichtbar mit Fehlermeldung."""
        if self.closed or self.state in (S.DOWNLOADING, S.VERIFYING, S.INSTALLING):
            return False
        if self._check is not None:
            if manual and not self._check_manual:
                self._check_manual = True  # laufende automatische Prüfung wird sichtbar
                self._set_error(None)
                self._go(S.CHECKING)
            return manual
        if not manual and self.state is S.READY:
            return False  # ein Update liegt bereit – kein unbemerkter Wechsel des Angebots
        self._check_manual = manual
        if manual:
            self._set_error(None)
            self._go(S.CHECKING)
        self.checks += 1
        self._check = self.client.fetch(
            self.releases_url,
            headers=github.API_HEADERS,
            max_bytes=github.MAX_FEED_SIZE,
            on_done=self._checked,
            on_error=self._check_failed,
        )
        return True

    def _checked(self, data: bytes) -> None:
        manual = self._check_manual
        self._check = None
        try:
            releases = github.parse_releases(data, self.site)
        except github.FeedError as exc:
            self._check_failed(TransferError("invalid", str(exc)), manual=manual)
            return
        self.releases = releases
        self.last_check = self.clock()
        self.auto_failed = False
        self.store.save_releases(releases, self.last_check)
        self.checked.emit()
        self._evaluate(fresh=manual)

    def _check_failed(self, error: TransferError, manual: bool | None = None) -> None:
        manual = self._check_manual if manual is None else manual
        self._check = None
        if not manual:
            self.auto_failed = True  # automatisch: still – der bisherige Zustand bleibt
            self.changed.emit()
            return
        kind = ErrorKind.RATE_LIMITED if error.rate_limited else ErrorKind.CHECK_FAILED
        self._set_error(kind, f"{error.kind}: {error}")
        self._go(S.ERROR)

    def _evaluate(self, fresh: bool) -> None:
        """Angebot aus den bekannten Releases bestimmen. ``fresh``: Ergebnis einer manuellen Prüfung."""
        if self.state in (S.DOWNLOADING, S.VERIFYING, S.INSTALLING):
            self.changed.emit()
            return  # ein laufender Download bzw. eine Installation wird nicht unterbrochen
        if self.releases is None:
            if self.state in (S.CHECKING, S.ERROR, S.CANCELLED):
                self._go(S.IDLE)
            return
        offer = github.choose(self.releases, self.installed, self.channel)
        previous = self.offer
        same = offer is not None and previous is not None and offer.version == previous.version
        self.offer = offer
        if offer is None:
            self._set_error(None)
            self._go(S.UP_TO_DATE)
            return
        if same and self.state in (S.READY, S.AVAILABLE):
            self.changed.emit()
            return  # unverändert (kein erneuter Hinweis, kein Flackern)
        if same and not fresh and self.state in (S.CANCELLED, S.ERROR):
            self.changed.emit()
            return  # Abbruch bzw. Fehler bleibt sichtbar
        self._set_error(None)
        self._go(S.AVAILABLE)
        self._verify_cached()

    # Kanal ------------------------------------------------------------------------------------------------------
    def set_channel(self, channel: Channel) -> None:
        """Kanal sofort wechseln (ohne Neustart): Angebot aus der letzten Prüfung neu bestimmen."""
        if channel is self.channel:
            return
        self.channel = channel
        if self.state is S.INSTALLING or self._check is not None:
            return  # die laufende Prüfung verwendet beim Ergebnis den neuen Kanal
        if self.state in (S.DOWNLOADING, S.VERIFYING):
            offer = github.choose(self.releases or [], self.installed, channel)
            if offer is not None and self.offer is not None and offer.version == self.offer.version:
                return  # dasselbe Update – weiter laden
            self._abort_download()
            self._go(S.IDLE)
        self._evaluate(fresh=False)

    # Herunterladen ------------------------------------------------------------------------------------------------
    def download(self) -> bool:
        """Setup des Angebots laden (bzw. ein bereits geladenes nur prüfen). Nie zwei Downloads gleichzeitig."""
        offer = self.offer
        if self.closed or offer is None or not offer.complete or self.state not in (S.AVAILABLE, S.CANCELLED, S.ERROR):
            return False
        if self._check is not None and self._check_manual:
            return False
        self._set_error(None)
        if self._verify_cached():
            return True
        self.received, self.total = 0, offer.installer.size
        self.downloads += 1
        self._token += 1
        token = self._token
        self._go(S.DOWNLOADING)
        self.progressChanged.emit()
        self._transfer = self.client.fetch(
            offer.checksum.url,
            max_bytes=github.MAX_CHECKSUM_SIZE,
            on_done=lambda data: self._checksum_loaded(token, offer, data),
            on_error=lambda error: self._download_failed(token, error, checksum=True),
        )
        return True

    def _checksum_loaded(self, token: int, offer: Release, data: bytes) -> None:
        if token != self._token:
            return
        try:
            expected = parse_checksum(data, offer.installer.name)
        except ChecksumError as exc:
            self._verification_failed(offer, f"Prüfsummendatei: {exc}")
            return
        if offer.installer.digest and not same_digest(offer.installer.digest, expected):
            self._verification_failed(offer, "Prüfsummendatei widerspricht der Angabe von GitHub")
            return
        self._expected = expected
        self.store.ensure()
        self._transfer = self.client.download(
            offer.installer.url,
            self.store.partial(offer),
            max_bytes=github.MAX_INSTALLER_SIZE,
            expected_size=offer.installer.size,
            on_progress=lambda received, total: self._progress(token, received, total),
            on_done=lambda path: self._downloaded(token, offer, path),
            on_error=lambda error: self._download_failed(token, error),
        )

    def _progress(self, token: int, received: int, total: int) -> None:
        if token != self._token:
            return
        self.received = received
        self.total = total or self.total
        self.progressChanged.emit()

    def _downloaded(self, token: int, offer: Release, path: Path) -> None:
        if token != self._token:
            return
        self._transfer = None
        self._verify(token, offer, path, self._expected, partial=True)

    def _download_failed(self, token: int, error: TransferError, checksum: bool = False) -> None:
        if token != self._token:
            return
        self._transfer = None
        if checksum and error.kind == "http" and error.status == 404 and self.offer is not None:
            self._verification_failed(self.offer, "Prüfsummendatei fehlt")
            return
        self._set_error(ErrorKind.DOWNLOAD_FAILED, f"{error.kind}: {error}")
        self._go(S.ERROR)

    def cancel(self) -> None:
        """Download bzw. Prüfung abbrechen – eine Teil-Datei wird entfernt, nichts wird verwendet."""
        if self.state not in (S.DOWNLOADING, S.VERIFYING):
            return
        self._abort_download()
        self._go(S.CANCELLED)

    def _abort_download(self) -> None:
        self._token += 1
        transfer, self._transfer = self._transfer, None
        if transfer is not None:
            transfer.cancel()
        if self.offer is not None:
            partial = self.store.partial(self.offer)
            try:
                partial.unlink()
            except OSError:
                pass
        self.received = 0

    # Verifizieren -----------------------------------------------------------------------------------------------------
    def _verify_cached(self) -> bool:
        """Liegt das Setup des Angebots schon vollständig vor, nur prüfen (kein erneuter Download)."""
        offer = self.offer
        if offer is None or not offer.complete:
            return False
        path = self.store.cached(offer)
        expected = self.store.read_checksum(offer)
        if path is None or not expected:
            return False
        if offer.installer.digest and not same_digest(offer.installer.digest, expected):
            self.store.remove(offer)
            return False
        self._token += 1
        self._expected = expected
        self.received = self.total = offer.installer.size
        self._verify(self._token, offer, path, expected, partial=False)
        return True

    def _verify(self, token: int, offer: Release, path: Path, expected: str, partial: bool) -> None:
        self._go(S.VERIFYING)

        def work() -> bool:
            if not same_digest(file_sha256(path, cancelled=lambda: token != self._token), expected):
                return False
            if partial:
                os.replace(path, self.store.installer(offer))
                self.store.write_checksum(offer, expected)
            return True

        def done(ok: object) -> None:
            if token != self._token or self.closed:
                return
            if not ok:
                self._verification_failed(offer, "SHA-256 stimmt nicht überein")
                return
            self._go(S.READY)
            keep = offer
            self.background(lambda: self.store.cleanup(keep), lambda _result: None, lambda _exc, _text: None)

        def failed(exc: BaseException, _text: str) -> None:
            if token != self._token or self.closed:
                return
            if isinstance(exc, InterruptedError):
                return
            self.store.remove(offer)
            self._set_error(ErrorKind.DOWNLOAD_FAILED if isinstance(exc, OSError) else ErrorKind.VERIFY_FAILED, str(exc))
            self._go(S.ERROR)

        self.background(work, done, failed)

    def _verification_failed(self, offer: Release, detail: str) -> None:
        """Ohne gültige Prüfsumme keine Installation: Dateien löschen, Fehler melden."""
        self._token += 1
        self._transfer = None
        self.store.remove(offer)
        self._set_error(ErrorKind.VERIFY_FAILED, detail)
        self._go(S.ERROR)

    # Installation --------------------------------------------------------------------------------------------------------
    def installer_path(self) -> Path | None:
        return self.store.installer(self.offer) if self.offer is not None else None

    def begin_install(self, ready: Callable[[Path, str], None]) -> bool:
        """``READY`` → ``INSTALLING``: Datei und Prüfsumme unmittelbar vor dem Start erneut prüfen;
        bei Erfolg ``ready(Pfad, SHA-256)`` aufrufen (startet das Setup), sonst ``ERROR``."""
        offer = self.offer
        if self.closed or offer is None or self.state is not S.READY:
            return False
        path = self.store.installer(offer)
        expected = self._expected or self.store.read_checksum(offer)
        self._token += 1
        token = self._token
        self._go(S.INSTALLING)

        def work() -> bool:
            return path.is_file() and same_digest(file_sha256(path), expected)

        def done(ok: object) -> None:
            if token != self._token or self.closed:
                return
            if not ok:
                self.store.remove(offer)
                self._set_error(ErrorKind.VERIFY_FAILED, "Setup fehlt oder wurde verändert")
                self._go(S.ERROR)
                return
            ready(path, expected)

        def failed(exc: BaseException, _text: str) -> None:
            if token != self._token or self.closed:
                return
            self.store.remove(offer)
            self._set_error(ErrorKind.VERIFY_FAILED, f"Setup fehlt oder ist nicht lesbar: {exc}")
            self._go(S.ERROR)

        self.background(work, done, failed)
        return True

    def install_aborted(self) -> None:
        """Start abgelehnt (z. B. Beenden abgebrochen): das Update bleibt bereit."""
        if self.state is S.INSTALLING:
            self._go(S.READY)

    def install_failed(self, detail: str) -> None:
        if self.state is S.INSTALLING:
            self._set_error(ErrorKind.INSTALL_FAILED, detail)
            self._go(S.ERROR)

    # Beenden ---------------------------------------------------------------------------------------------------------------
    def shutdown(self) -> None:
        """Beim Beenden: laufende Abrufe abbrechen (Teil-Dateien werden entfernt)."""
        self.closed = True
        self._token += 1
        for transfer in (self._check, self._transfer):
            if transfer is not None:
                transfer.cancel()
        self._check = self._transfer = None
        if self.offer is not None and self.state in (S.DOWNLOADING, S.VERIFYING):
            try:
                self.store.partial(self.offer).unlink()
            except OSError:
                pass
