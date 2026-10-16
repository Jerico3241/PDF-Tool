"""»Öffnen mit«: PDFs aus dem Explorer in der bereits laufenden App öffnen.

Startet Windows PDF Tool mit einer PDF (``start.py "C:\\…\\datei.pdf"``) und läuft die App schon,
reicht der neue Prozess die Pfade über eine lokale Verbindung (Named Pipe, nur für diesen
Benutzer) an die laufende App weiter und endet – die PDF öffnet sich dort als neuer Tab. Läuft
keine App, startet PDF Tool normal und öffnet die PDF selbst. Ein weiterer Start ohne Pfade (z. B. über das
Startmenü, während PDF Tool im Hintergrund bereitsteht) zeigt das Fenster der laufenden App.

Übertragen werden nur Dateipfade (keine Inhalte); die laufende App prüft jeden Pfad (vorhandene
Datei, höchstens ``MAX_PATHS``) und öffnet PDFs nur zum Lesen – geändert wird nichts ohne den
Benutzer. Der Name der Verbindung enthält keine Benutzerdaten (Prüfsumme).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject

from handoff import MAX_PATHS, PREFIX, message, pdf_arguments, server_name  # noqa: F401 - auch für Aufrufer

MAX_BYTES = 256 * 1024
TIMEOUT_MS = 2000


def forward(paths: list[str], name: str | None = None, show: bool = True) -> bool:
    """Pfade an eine laufende App senden. ``True``: angenommen – dieser Prozess kann enden.

    Ohne Pfade: ``show=True`` – die laufende App zeigt ihr Fenster (weiterer Start über das Startmenü);
    ``show=False`` – nur prüfen, ob PDF Tool schon läuft (Start mit Windows)."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(TIMEOUT_MS):
        return False
    try:
        socket.write(message(paths, show))
        socket.flush()
        # (liefert False, wenn schon alles geschrieben ist – entscheidend ist die Bestätigung)
        if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(TIMEOUT_MS):
            return False
        # Erst nach der Bestätigung enden – sonst ginge die Anfrage bei einem Absturz verloren
        # Die laufende App trennt gleich nach ihrem »ok«. Unter Windows meldet waitForReadyRead dann mitunter False,
        # obwohl die Antwort schon gelesen im Puffer liegt – entscheidend ist, was ankam.
        if not socket.waitForReadyRead(TIMEOUT_MS) and socket.bytesAvailable() == 0:
            return False
        return bytes(socket.readAll().data()).startswith(b"ok")
    finally:
        socket.disconnectFromServer()


def received_paths(data: bytes) -> list[str]:
    """Nachricht einer zweiten Instanz prüfen: nur vorhandene Dateien, begrenzte Anzahl."""
    return received(data)[0]


def received(data: bytes) -> tuple[list[str], bool]:
    """Nachricht einer zweiten Instanz: (geprüfte Pfade, Fenster zeigen)."""
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], False
    if not isinstance(message, dict):
        return [], False
    items = message.get("open")
    paths = [str(item) for item in items[:MAX_PATHS] if isinstance(item, str) and len(item) < 4096 and Path(item).is_file()] if isinstance(items, list) else []
    return paths, message.get("show") is True


class InstanceServer(QObject):
    """Nimmt Pfade weiterer Starts an (``on_paths(pfade)`` im GUI-Thread). Ein weiterer Start ohne Pfade ruft
    ``on_paths([])`` – die App zeigt dann ihr Fenster."""

    def __init__(self, on_paths: Callable[[list[str]], None], parent: QObject | None = None, name: str | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtNetwork import QLocalServer

        self._on_paths = on_paths
        self._buffers: dict = {}
        self.name = name or server_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            # Unix: Rest eines abgestürzten Laufs entfernen (unter Windows verschwindet die Pipe mit dem Prozess)
            QLocalServer.removeServer(self.name)
            self.server.listen(self.name)
        self.server.newConnection.connect(self._accept)

    @property
    def listening(self) -> bool:
        return self.server.isListening()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._buffers[socket] = b""
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._drop(s))
            if socket.bytesAvailable() > 0:  # Daten kamen schon vor dem Verbinden der Signale an
                self._read(socket)

    def _read(self, socket) -> None:
        if socket not in self._buffers:
            return
        data = self._buffers.get(socket, b"") + bytes(socket.readAll().data())
        if len(data) > MAX_BYTES:
            socket.abort()
            self._drop(socket)
            return
        self._buffers[socket] = data
        if b"\n" not in data:
            return
        paths, show = received(data.split(b"\n", 1)[0])
        self._buffers[socket] = b""
        socket.write(b"ok\n")
        socket.flush()
        # Trennen übernimmt der weitere Start, sobald er das »ok« gelesen hat (sonst könnte es unter Windows verloren gehen)
        if paths or show:
            self._on_paths(paths)

    def _drop(self, socket) -> None:
        if self._buffers.pop(socket, None) is None:
            return
        try:
            socket.deleteLater()
        except RuntimeError:  # beim Beenden schon mit dem Server gelöscht
            pass

    def close(self) -> None:
        self.server.close()
