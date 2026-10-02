"""»Öffnen mit«: PDFs aus dem Explorer in der bereits laufenden App öffnen.

Startet Windows PDF Tool mit einer PDF (``start.py "C:\\…\\datei.pdf"``) und läuft die App schon,
reicht der neue Prozess die Pfade über eine lokale Verbindung (Named Pipe, nur für diesen
Benutzer) an die laufende App weiter und endet – die PDF öffnet sich dort als neuer Tab. Läuft
keine App, startet PDF Tool normal und öffnet die PDF selbst. Ohne Pfade startet PDF Tool wie
bisher (auch mehrfach).

Übertragen werden nur Dateipfade (keine Inhalte); die laufende App prüft jeden Pfad (vorhandene
Datei, höchstens ``MAX_PATHS``) und öffnet PDFs nur zum Lesen – geändert wird nichts ohne den
Benutzer. Der Name der Verbindung enthält keine Benutzerdaten (Prüfsumme).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject

PREFIX = "PDFTool-Oeffnen-"
MAX_PATHS = 50
MAX_BYTES = 256 * 1024
TIMEOUT_MS = 2000


def server_name() -> str:
    """Name der Verbindung – je Benutzer verschieden, ohne Benutzernamen im Klartext."""
    ident = "|".join((os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", ""), str(Path.home())))
    return PREFIX + hashlib.sha256(ident.encode("utf-8", "replace")).hexdigest()[:20]


def pdf_arguments(argv: list[str]) -> list[str]:
    """Dateipfade aus der Befehlszeile (Optionen wie ``-OO`` sind schon entfernt)."""
    paths = []
    for arg in argv:
        if not arg or arg.startswith("-"):
            continue
        path = Path(arg)
        if path.suffix.lower() == ".pdf" or path.is_file():
            paths.append(str(path.resolve()) if path.exists() else str(path))
    return paths[:MAX_PATHS]


def forward(paths: list[str], name: str | None = None) -> bool:
    """Pfade an eine laufende App senden. ``True``: angenommen – dieser Prozess kann enden."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(TIMEOUT_MS):
        return False
    try:
        socket.write(json.dumps({"open": paths[:MAX_PATHS]}).encode("utf-8") + b"\n")
        socket.flush()
        # (liefert False, wenn schon alles geschrieben ist – entscheidend ist die Bestätigung)
        if socket.bytesToWrite() > 0 and not socket.waitForBytesWritten(TIMEOUT_MS):
            return False
        # Erst nach der Bestätigung enden – sonst ginge die Anfrage bei einem Absturz verloren
        if not socket.waitForReadyRead(TIMEOUT_MS):
            return False
        return bytes(socket.readAll().data()).startswith(b"ok")
    finally:
        socket.disconnectFromServer()


def received_paths(data: bytes) -> list[str]:
    """Nachricht einer zweiten Instanz prüfen: nur vorhandene Dateien, begrenzte Anzahl."""
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    items = message.get("open") if isinstance(message, dict) else None
    if not isinstance(items, list):
        return []
    return [str(item) for item in items[:MAX_PATHS] if isinstance(item, str) and len(item) < 4096 and Path(item).is_file()]


class InstanceServer(QObject):
    """Nimmt Pfade weiterer Starts an (``on_paths(pfade)`` im GUI-Thread)."""

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
        paths = received_paths(data.split(b"\n", 1)[0])
        self._buffers[socket] = b""
        socket.write(b"ok\n")
        socket.flush()
        socket.disconnectFromServer()
        if paths:
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
