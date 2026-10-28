"""Verbindung zum Textkern (``kernel.py`` mit LibreOfficeKit) – ohne Oberfläche.

``Engine.start()`` startet den Kern als eigenen Prozess mit dem Python von Novadesk und einem eigenen Profil von
LibreOffice (``%LOCALAPPDATA%\\PDF-Tool-Office\\text``) und verbindet sich über 127.0.0.1 mit einem zufälligen
Schlüssel. ``call(Befehl, **Argumente)`` schickt einen Befehl und wartet auf seine Antwort (auch aus mehreren Threads;
der Kern arbeitet sie nacheinander ab). Ereignisse von LibreOfficeKit (Kacheln ungültig, Schreibmarke, Zustand der
Knöpfe …) gehen an ``on_event(Dokument, Art, Inhalt)`` – im Lese-Thread. Unter Windows liegt der Kern im Job-Objekt
von Novadesk: Endet Novadesk – auch unerwartet –, endet er mit.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from tools.pdf_editor import office
from tools.sheet.engine import PROFILE_SETTINGS

KERNEL_SOURCE = Path(__file__).with_name("kernel.py")
START_TIMEOUT = 120.0  # erster Start mit neuem Profil: LibreOffice richtet sich ein
CALL_TIMEOUT = 180.0  # große Dateien laden oder speichern
TOKEN_VARIABLE = "NOVADESK_TEXT_SCHLUESSEL"

# Wie das Profil der Tabellen, dazu: keine Ecken der Textbegrenzung (die Seiten sehen aus wie gedruckt) und Deutsch als
# Sprache neuer Texte (Rechtschreibprüfung, Silbentrennung)
TEXT_SETTINGS = PROFILE_SETTINGS.replace(
    "</oor:items>",
    '<item oor:path="/org.openoffice.Office.UI/ColorScheme/ColorSchemes/org.openoffice.Office.UI:ColorScheme[\'COLOR_SCHEME_LIBREOFFICE_AUTOMATIC\']/DocBoundaries">'
    '<prop oor:name="IsVisible" oor:op="fuse"><value>false</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Office.Linguistic/General"><prop oor:name="DefaultLocale" oor:op="fuse"><value>de-DE</value></prop></item>\n'
    # Neue Präsentation ohne Vorlagenauswahl und Layout-Dialog: Unter Windows bliebe der Kern sonst unsichtbar an
    # diesem Dialog hängen (seit 5.0 Beta 4)
    '<item oor:path="/org.openoffice.Office.Impress/Misc/NewDoc"><prop oor:name="AutoPilot" oor:op="fuse"><value>false</value></prop>'
    '<prop oor:name="Layout" oor:op="fuse"><value>false</value></prop></item>\n'
    "</oor:items>",
)


class TextError(Exception):
    """Fehler des Textkerns mit einem Text für die Oberfläche."""

    def __init__(self, message: str, code: str = "fehler") -> None:
        super().__init__(message)
        self.code = code


class EngineGone(TextError):
    """Der Textkern läuft nicht (mehr). ``detail``: Exit-Code und Fehlerbericht (für Protokoll und Build-Probe)."""

    def __init__(self, message: str = "Der Textkern läuft nicht mehr.", detail: str = "") -> None:
        super().__init__(message, "kern")
        self.detail = detail


def profile_dir() -> Path:
    """Eigenes Profil des Textkerns – neben denen für Tabellen und das Umwandeln."""
    return office.profile_dir().parent / "text"


def program_dir() -> Path | None:
    found = office.libreoffice()
    return Path(found).resolve().parent if found is not None else None


def python() -> list[str]:
    """Das Python von Novadesk (im Setup ``runtime\\pythonw.exe``) – isoliert, ohne Konsolenfenster."""
    return [sys.executable, "-I", "-X", "utf8"]


def available() -> bool:
    return office.TEST_INSTALLED is None and program_dir() is not None


class _Waiter:
    __slots__ = ("event", "answer", "data")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.answer: dict | None = None
        self.data = b""


class Engine:
    def __init__(self, on_event: Callable[[int, int, str], None] | None = None) -> None:
        self.on_event = on_event
        self._process: subprocess.Popen | None = None
        self._job = None
        self._socket: socket.socket | None = None
        self._stream = None
        self._send_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._waiting: dict[int, _Waiter] = {}
        self._waiting_lock = threading.Lock()
        self._next = 1
        self._work: Path | None = None
        self._reader: threading.Thread | None = None
        self.closed = False
        self.last_exit: int | None = None
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._socket is not None and self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Kern starten und verbinden (blockiert: im Hintergrund aufrufen)."""
        with self._start_lock:
            if self.running:
                return
            if self.closed:
                raise EngineGone("Novadesk wird beendet.")
            self._shutdown_process()
            program = program_dir()
            if program is None:
                raise EngineGone(office.missing_text("word"))
            self._launch(program)

    def _prepare_profile(self) -> Path:
        profile = profile_dir()
        user = profile / "user"
        user.mkdir(parents=True, exist_ok=True)
        settings = user / "registrymodifications.xcu"
        if not settings.is_file() or b"Office.Impress/Misc/NewDoc" not in settings.read_bytes():
            settings.write_text(TEXT_SETTINGS, encoding="utf-8")
        return profile

    def _environment(self) -> dict:
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON")}
        if os.name != "nt":
            environment["SAL_USE_VCLPLUGIN"] = "svp"
        return environment

    def _launch(self, program: Path) -> None:
        profile = self._prepare_profile()
        self._work = Path(tempfile.mkdtemp(prefix="novadesk-text-"))
        port_file = self._work / "port"
        token = secrets.token_hex(24)
        environment = {**self._environment(), TOKEN_VARIABLE: token}
        command = [*python(), str(KERNEL_SOURCE), str(program), str(profile), str(port_file)]
        log = (self._work / "kern.log").open("wb")
        flags = office.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(command, cwd=str(self._work), env=environment, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=log, creationflags=flags)
        log.close()
        if os.name == "nt":
            from assistant import runtime

            self._job = runtime._bind_to_app(self._process)  # noqa: SLF001 - dasselbe Job-Objekt wie die KI
        deadline = time.monotonic() + START_TIMEOUT
        failure = Path(str(port_file) + ".fehler")
        while not port_file.is_file():
            if failure.is_file() or self._process.poll() is not None:
                time.sleep(0.2)
                self._shutdown_process(wait=2.0)
                raise EngineGone("Der Textkern ließ sich nicht starten.", self.detail())
            if time.monotonic() > deadline:
                self._shutdown_process()
                raise EngineGone("Der Textkern hat nicht rechtzeitig geantwortet.", self.detail())
            time.sleep(0.03)
        port = int(port_file.read_text().strip())
        connection = socket.create_connection(("127.0.0.1", port), timeout=30)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._stream = connection.makefile("rb")
        connection.sendall((json.dumps({"token": token}) + "\n").encode("utf-8"))
        hello = self._stream.readline()
        if not hello or not json.loads(hello.decode("utf-8")).get("ok"):
            self._socket = connection
            self._shutdown_process()
            raise EngineGone("Der Textkern hat die Verbindung abgelehnt.", self.detail())
        connection.settimeout(None)
        self._socket = connection
        self._reader = threading.Thread(target=self._read, args=(self._stream,), name="novadesk-text-lesen", daemon=True)
        self._reader.start()

    def _read(self, stream) -> None:
        """Antworten den wartenden Befehlen zuordnen, Ereignisse weitergeben – bis die Verbindung endet."""
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                message = json.loads(line.decode("utf-8"))
                data = b""
                size = int(message.get("bytes") or 0)
                if size:
                    data = stream.read(size)
                    if len(data) != size:
                        break
                if "event" in message:
                    if self.on_event is not None:
                        try:
                            self.on_event(int(message.get("doc") or 0), int(message["event"]), str(message.get("payload") or ""))
                        except Exception:  # noqa: BLE001 - ein Fehler in der Oberfläche beendet das Lesen nicht
                            pass
                    continue
                with self._waiting_lock:
                    waiter = self._waiting.pop(int(message.get("id") or 0), None)
                if waiter is not None:
                    waiter.answer = message
                    waiter.data = data
                    waiter.event.set()
        except (OSError, ValueError):
            pass
        finally:
            with self._waiting_lock:
                waiters, self._waiting = list(self._waiting.values()), {}
            for waiter in waiters:
                waiter.event.set()

    def call(self, command: str, /, timeout: float = CALL_TIMEOUT, **args):
        """Befehl an den Kern; gibt das Ergebnis zurück (Kacheln: ``bytes``) oder wirft ``TextError`` (``EngineGone``,
        wenn er nicht mehr läuft – dann sind auch alle geöffneten Dokumente fort)."""
        if not self.running:
            self._shutdown_process()
            raise EngineGone(detail=self.detail())
        waiter = _Waiter()
        with self._send_lock:
            ident = self._next
            self._next += 1
            with self._waiting_lock:
                self._waiting[ident] = waiter
            try:
                self._socket.sendall((json.dumps({"id": ident, "cmd": command, "args": args}, separators=(",", ":")) + "\n").encode("utf-8"))
            except (OSError, AttributeError) as exc:
                with self._waiting_lock:
                    self._waiting.pop(ident, None)
                self._shutdown_process(wait=2.0)
                raise EngineGone(detail=self.detail()) from exc
        if not waiter.event.wait(timeout):
            with self._waiting_lock:
                self._waiting.pop(ident, None)
            raise TextError("Der Textkern antwortet nicht.", "zeit")
        answer = waiter.answer
        if answer is None:
            self._shutdown_process(wait=2.0)
            raise EngineGone(detail=self.detail())
        if answer.get("ok"):
            return waiter.data if answer.get("bytes") else answer.get("result")
        if answer.get("code") == "intern":
            raise TextError(f"Interner Fehler des Textkerns ({answer.get('error')})", "intern")
        raise TextError(str(answer.get("error") or "Unbekannter Fehler"), str(answer.get("code") or "fehler"))

    def stop(self) -> None:
        """Beenden: Dokumente ohne Speichern schließen, den Kern beenden (spätestens nach einigen Sekunden)."""
        self.closed = True
        if self.running:
            try:
                self.call("quit", timeout=5)
            except TextError:
                pass
        self._shutdown_process(wait=5.0)

    def _shutdown_process(self, wait: float = 0.0) -> None:
        connection, self._socket = self._socket, None
        stream, self._stream = self._stream, None
        # Erst die Verbindung kappen: Das weckt den Lese-Thread. Sonst wartet stream.close() auf ihn, solange ein
        # hängender Kern nichts mehr schickt – und Novadesk (oder die Build-Probe) hinge beim Beenden
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for item in (connection, stream):
            if item is not None:
                try:
                    item.close()
                except OSError:
                    pass
        process, self._process = self._process, None
        if process is not None:
            self.last_exit = None
            try:
                process.wait(timeout=wait) if wait else None
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            self.last_exit = process.poll()
        job, self._job = self._job, None
        if job is not None:
            from assistant import runtime

            runtime._close_handle(job)  # noqa: SLF001
        self._cleanup()

    def detail(self) -> str:
        parts = [f"Exit-Code {self.last_exit}"] if self.last_exit is not None else []
        if self.last_error:
            parts.append(self.last_error)
        return "\n".join(parts)

    def _cleanup(self) -> None:
        work, self._work = self._work, None
        if work is None:
            return
        texts = []
        for name in ("port.fehler", "kern.log"):
            try:
                text = (work / name).read_text(encoding="utf-8", errors="replace").strip() if (work / name).is_file() else ""
            except OSError:
                text = ""
            if text:
                texts.append(f"{name}: {text[-3000:]}")
        if texts:
            self.last_error = "\n".join(texts)
        shutil.rmtree(work, ignore_errors=True)
