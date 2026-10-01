"""HTTPS-Abrufe des Updaters mit Qt Network – asynchron, die Oberfläche blockiert nie.

Qt Network arbeitet unter Windows mit Schannel: Zertifikate prüft Windows selbst (inklusive
nachgeladener Stammzertifikate), Proxy-Einstellungen des Systems (auch PAC) gelten. Die
eigentliche Übertragung läuft in einem Netzwerk-Thread von Qt; hier kommen nur die Daten an.

Jeder Abruf

* prüft die Adresse vor dem Start und jede Weiterleitung gegen die ``UrlPolicy``
  (nur HTTPS, nur GitHub, höchstens fünf Weiterleitungen),
* hat Zeitlimits: bis die Antwort beginnt (Verbindung, TLS, Kopfzeilen) und ohne neue Daten
  während der Übertragung – keine endlos hängenden Anfragen,
* begrenzt die Datenmenge (``max_bytes``) und prüft die erwartete Größe,
* lässt sich jederzeit abbrechen; ein abgebrochener Download hinterlässt keine Datei,
* meldet Fortschritt gedrosselt (höchstens etwa zehnmal pro Sekunde).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import BinaryIO, Callable

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkProxyFactory, QNetworkReply, QNetworkRequest

from .policy import UrlPolicy

CONNECT_TIMEOUT_MS = 20_000  # bis die Antwort beginnt
READ_TIMEOUT_MS = 30_000  # ohne neue Daten
PROGRESS_INTERVAL = 0.1  # Sekunden zwischen zwei Fortschrittsmeldungen

_OFFLINE = {
    QNetworkReply.NetworkError.ConnectionRefusedError,
    QNetworkReply.NetworkError.RemoteHostClosedError,
    QNetworkReply.NetworkError.HostNotFoundError,
    QNetworkReply.NetworkError.TemporaryNetworkFailureError,
    QNetworkReply.NetworkError.NetworkSessionFailedError,
    QNetworkReply.NetworkError.UnknownNetworkError,
    QNetworkReply.NetworkError.ProxyConnectionRefusedError,
    QNetworkReply.NetworkError.ProxyConnectionClosedError,
    QNetworkReply.NetworkError.ProxyNotFoundError,
    QNetworkReply.NetworkError.ProxyTimeoutError,
    QNetworkReply.NetworkError.ProxyAuthenticationRequiredError,
    QNetworkReply.NetworkError.UnknownProxyError,
}


def _guarded(method):
    """Ein unerwarteter Fehler in einer Rückmeldung von Qt beendet den Abruf als Fehler – er hängt nie."""

    def wrapper(self, *args):
        try:
            return method(self, *args)
        except Exception as exc:  # noqa: BLE001 - jeder Fehler wird zum Fehlschlag dieses Abrufs
            self._fail(TransferError("internal", f"{type(exc).__name__}: {exc}"))
            return None

    wrapper.__name__ = method.__name__
    wrapper.__doc__ = method.__doc__
    return wrapper


class TransferError(Exception):
    """Ein Abruf ist gescheitert. ``kind``: offline, timeout, http, policy, too_large, size, tls, io, cancelled."""

    def __init__(self, kind: str, message: str, status: int | None = None, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.rate_limited = rate_limited


def use_system_proxy() -> None:
    """Proxy-Einstellungen des Systems verwenden (Windows: auch automatische Konfiguration)."""
    QNetworkProxyFactory.setUseSystemConfiguration(True)


class Transfer(QObject):
    """Eine laufende Anfrage. ``cancel()`` bricht sie ab; danach kommt keine Rückmeldung mehr."""

    def __init__(
        self,
        client: "HttpClient",
        url: str,
        headers: dict[str, str],
        max_bytes: int,
        on_done: Callable[[object], None],
        on_error: Callable[[TransferError], None],
        target: Path | None = None,
        expected_size: int | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__(client)
        self.client = client
        self.url = url
        self.max_bytes = int(max_bytes)
        self.target = target
        self.expected_size = expected_size
        self.received = 0
        self.redirects = 0
        self.finished = False
        self.cancelled = False
        self._on_done = on_done
        self._on_error = on_error
        self._on_progress = on_progress
        self._buffer = bytearray()
        self._file: BinaryIO | None = None
        self._failure: TransferError | None = None
        self._last_progress = 0.0
        self._started = False
        request = QNetworkRequest(QUrl(url))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.UserVerifiedRedirectPolicy)
        request.setMaximumRedirectsAllowed(client.policy.max_redirects)
        request.setTransferTimeout(client.read_timeout_ms)
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, client.user_agent)
        for name, value in headers.items():
            request.setRawHeader(name.encode("ascii"), value.encode("ascii"))
        if target is not None:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(target, "wb")
            except OSError as exc:
                self._failure = TransferError("io", f"Datei kann nicht angelegt werden: {exc}")
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self._connect_timeout)
        self.reply: QNetworkReply | None = None
        if self._failure is not None:
            QTimer.singleShot(0, self, self._report_failure)
            return
        self.reply = client.manager.get(request)
        self.reply.redirected.connect(self._redirected)
        self.reply.metaDataChanged.connect(self._meta)
        self.reply.readyRead.connect(self._read)
        self.reply.downloadProgress.connect(self._progress)
        self.reply.finished.connect(self._finished)
        self._connect_timer.start(client.connect_timeout_ms)

    # Abbrechen -------------------------------------------------------------------------------------------
    def cancel(self) -> None:
        if self.finished:
            return
        self.cancelled = True
        self._fail(TransferError("cancelled", "Abgebrochen"), report=False)

    def _fail(self, error: TransferError, report: bool = True) -> None:
        if self.finished or self._failure is not None:
            return
        self._failure = error
        self._connect_timer.stop()
        if self.reply is not None and self.reply.isRunning():
            self.reply.abort()  # löst ``finished`` aus (wird dort übergangen)
        self._close(remove=True)
        self.finished = True
        if self.reply is not None:
            self.reply.deleteLater()
        self.client._forget(self)
        if report and not self.cancelled:
            self._on_error(error)

    def _report_failure(self) -> None:
        error, self._failure = self._failure, None
        if error is not None:
            self._fail(error)

    # Ablauf ---------------------------------------------------------------------------------------------------
    @_guarded
    def _connect_timeout(self) -> None:
        if not self._started:
            self._fail(TransferError("timeout", "Zeitüberschreitung beim Verbindungsaufbau"))

    @_guarded
    def _redirected(self, url: QUrl) -> None:
        target = url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
        if self.redirects >= self.client.policy.max_redirects or not self.client.policy.allows_redirect(self.url, target):
            self._fail(TransferError("policy", f"Weiterleitung nicht erlaubt: {QUrl(target).host() or target[:80]}"))
            return
        self.redirects += 1
        self.url = target
        if self.reply is not None:
            self.reply.redirectAllowed.emit()

    def _status(self) -> int | None:
        if self.reply is None:
            return None
        value = self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @_guarded
    def _meta(self) -> None:
        status = self._status()
        if status is None or 300 <= status < 400:
            return  # Weiterleitung – die eigentliche Antwort kommt noch
        self._started = True
        self._connect_timer.stop()
        if status >= 400:
            return  # Auswertung in ``_finished``
        length = self.reply.header(QNetworkRequest.KnownHeaders.ContentLengthHeader) if self.reply is not None else None
        try:
            length = int(length) if length is not None else None
        except (TypeError, ValueError):
            length = None
        if length is not None and length > self.max_bytes:
            self._fail(TransferError("too_large", f"Antwort zu groß ({length} Bytes)"))
        elif length is not None and self.expected_size is not None and length != self.expected_size:
            self._fail(TransferError("size", f"Unerwartete Größe ({length} statt {self.expected_size} Bytes)"))

    @_guarded
    def _read(self) -> None:
        if self.finished or self.reply is None:
            return
        status = self._status()
        if status is not None and (status >= 400 or 300 <= status < 400):
            self.reply.readAll()  # Fehlerseite bzw. Weiterleitung: Inhalt verwerfen
            return
        self._started = True
        self._connect_timer.stop()
        data = bytes(self.reply.readAll().data())
        if not data:
            return
        self.received += len(data)
        if self.received > self.max_bytes:
            self._fail(TransferError("too_large", "Antwort zu groß"))
            return
        if self._file is not None:
            try:
                self._file.write(data)
            except OSError as exc:
                self._fail(TransferError("io", f"Datei kann nicht geschrieben werden: {exc}"))
        else:
            self._buffer.extend(data)

    @_guarded
    def _progress(self, received: int, total: int) -> None:
        if self.finished or self._on_progress is None:
            return
        status = self._status()
        if status is not None and 300 <= status < 400:
            return
        now = time.monotonic()
        complete = total > 0 and received >= total
        if not complete and now - self._last_progress < PROGRESS_INTERVAL:
            return
        self._last_progress = now
        self._on_progress(int(received), int(total if total > 0 else (self.expected_size or 0)))

    @_guarded
    def _finished(self) -> None:
        if self.finished or self._failure is not None:
            return  # selbst abgebrochen (``_fail``)
        reply = self.reply
        self._connect_timer.stop()
        if reply is None:
            return
        error = reply.error()
        status = self._status()
        if error == QNetworkReply.NetworkError.NoError or (status is not None and status >= 400):
            if status is None or not 200 <= status < 300:
                remaining = bytes(reply.rawHeader("X-RateLimit-Remaining").data() or b"").strip()
                limited = status in (403, 429) and remaining == b"0"
                self._fail(TransferError("http", f"HTTP {status}", status=status, rate_limited=limited))
                return
        elif error == QNetworkReply.NetworkError.OperationCanceledError:
            self._fail(TransferError("timeout", "Zeitüberschreitung (keine Daten)"))
            return
        elif error in (QNetworkReply.NetworkError.SslHandshakeFailedError,):
            self._fail(TransferError("tls", reply.errorString()))
            return
        elif error in (QNetworkReply.NetworkError.TimeoutError,):
            self._fail(TransferError("timeout", reply.errorString()))
            return
        elif error in (
            QNetworkReply.NetworkError.InsecureRedirectError,
            QNetworkReply.NetworkError.TooManyRedirectsError,
            QNetworkReply.NetworkError.ProtocolUnknownError,
            QNetworkReply.NetworkError.ProtocolInvalidOperationError,
        ):
            self._fail(TransferError("policy", reply.errorString()))  # z. B. Weiterleitung auf file:
            return
        else:
            self._fail(TransferError("offline" if error in _OFFLINE else "http", reply.errorString(), status=status))
            return
        final = reply.url().toString(QUrl.ComponentFormattingOption.FullyEncoded)
        if not self.client.policy.allows(final):
            self._fail(TransferError("policy", "Unerwartete Adresse"))
            return
        self._read()  # restliche Daten
        if self.finished:
            return
        if self.expected_size is not None and self.received != self.expected_size:
            self._fail(TransferError("size", f"Unvollständig ({self.received} von {self.expected_size} Bytes)"))
            return
        if self._file is not None:
            try:
                self._file.flush()
                self._close(remove=False)
            except OSError as exc:
                self._fail(TransferError("io", f"Datei kann nicht geschrieben werden: {exc}"))
                return
        if self._on_progress is not None:
            self._on_progress(self.received, self.expected_size or self.received)
        self.finished = True
        reply.deleteLater()
        self.client._forget(self)
        self._on_done(self.target if self.target is not None else bytes(self._buffer))

    def _close(self, remove: bool) -> None:
        handle, self._file = self._file, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        if remove and self.target is not None:
            try:
                self.target.unlink()
            except OSError:
                pass


class HttpClient(QObject):
    """Abrufe unter einer ``UrlPolicy``. Mehrere Abrufe gleichzeitig sind möglich."""

    def __init__(
        self,
        policy: UrlPolicy,
        user_agent: str = "PDF-Tool",
        *,
        system_proxy: bool = True,
        connect_timeout_ms: int = CONNECT_TIMEOUT_MS,
        read_timeout_ms: int = READ_TIMEOUT_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.policy = policy
        self.user_agent = user_agent
        self.connect_timeout_ms = int(connect_timeout_ms)
        self.read_timeout_ms = int(read_timeout_ms)
        self.manager = QNetworkAccessManager(self)
        if system_proxy:
            use_system_proxy()
        else:
            self.manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self._active: list[Transfer] = []

    def _start(self, url: str, on_error: Callable[[TransferError], None], **kwargs) -> Transfer | None:
        if not self.policy.allows(url):
            error = TransferError("policy", "Adresse nicht erlaubt")
            QTimer.singleShot(0, self, lambda: on_error(error))
            return None
        transfer = Transfer(self, url, on_error=on_error, **kwargs)
        self._active.append(transfer)
        return transfer

    def fetch(self, url: str, *, max_bytes: int, on_done: Callable[[bytes], None], on_error: Callable[[TransferError], None], headers: dict[str, str] | None = None) -> Transfer | None:
        """Kleine Antwort (z. B. Release-Liste, Prüfsumme) in den Speicher laden."""
        return self._start(url, on_error, headers=dict(headers or {}), max_bytes=max_bytes, on_done=on_done)

    def download(
        self,
        url: str,
        target: Path,
        *,
        max_bytes: int,
        on_done: Callable[[Path], None],
        on_error: Callable[[TransferError], None],
        on_progress: Callable[[int, int], None] | None = None,
        expected_size: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> Transfer | None:
        """Datei nach ``target`` laden; bei Fehler oder Abbruch wird ``target`` entfernt."""
        return self._start(
            url,
            on_error,
            headers=dict(headers or {"Accept": "application/octet-stream"}),
            max_bytes=max_bytes,
            on_done=on_done,
            target=Path(target),
            expected_size=expected_size,
            on_progress=on_progress,
        )

    def _forget(self, transfer: Transfer) -> None:
        if transfer in self._active:
            self._active.remove(transfer)
        transfer.deleteLater()

    def active(self) -> int:
        return len(self._active)

    def cancel_all(self) -> None:
        for transfer in list(self._active):
            transfer.cancel()
