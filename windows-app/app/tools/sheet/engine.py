"""Verbindung zum Rechenkern der Tabellen (``server.py`` in LibreOffice) – ohne Oberfläche.

``Engine.start()`` startet das mitgelieferte LibreOffice ohne Fenster mit einem eigenen Profil
(``%LOCALAPPDATA%\\PDF-Tool-Office\\tabelle``: deutsche Oberfläche und Zahlen, keine Sperrdateien neben den Tabellen
des Nutzers), legt den Kern dort als Skript ab und verbindet sich über 127.0.0.1 mit einem zufälligen Schlüssel.
``call(Befehl, **Argumente)`` schickt einen Befehl und wartet auf die Antwort (nacheinander, auch aus mehreren
Threads). Unter Windows liegt LibreOffice in einem Job-Objekt: Endet Novadesk – auch unerwartet –, endet es mit.
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

from tools.pdf_editor import office

SCRIPT_NAME = "novadesk_tabelle.py"
SCRIPT_URL = f"vnd.sun.star.script:{SCRIPT_NAME}$start?language=Python&location=user"
SERVER_SOURCE = Path(__file__).with_name("server.py")
START_TIMEOUT = 90.0  # erster Start mit neuem Profil unter Windows: LibreOffice richtet sich ein
CALL_TIMEOUT = 180.0  # große Dateien laden oder speichern
RESTART_CODE = 81  # LibreOffice: »bitte neu starten« (nach dem Einrichten eines neuen Profils)
READY_MARKER = ".novadesk-bereit"  # Profil fertig eingerichtet (LibreOffice einmal ohne Kern gestartet)

# Profil: deutsche Oberfläche (Funktionsnamen wie SUMME), deutsche Zahlen und Daten, keine Sperrdateien
# (».~lock.<Name>#« neben der Datei des Nutzers), keine Sicherungskopien, kein automatisches Wiederherstellen
PROFILE_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Setup/L10N"><prop oor:name="ooLocale" oor:op="fuse"><value>de-DE</value></prop></item>
<item oor:path="/org.openoffice.Setup/L10N"><prop oor:name="ooSetupSystemLocale" oor:op="fuse"><value>de-DE</value></prop></item>
<item oor:path="/org.openoffice.Office.Linguistic/General"><prop oor:name="UILocale" oor:op="fuse"><value>de-DE</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="UseLocking" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="CreateBackup" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="AutoSave" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Recovery/AutoSave"><prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Recovery/RecoveryInfo"><prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Formula/Syntax"><prop oor:name="EnglishFunctionName" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""


class CalcError(Exception):
    """Fehler des Rechenkerns mit einem Text für die Oberfläche."""

    def __init__(self, message: str, code: str = "fehler") -> None:
        super().__init__(message)
        self.code = code


class EngineGone(CalcError):
    """Der Rechenkern läuft nicht (mehr) – LibreOffice fehlt, startet nicht oder ist abgestürzt. ``detail``: Exit-Code
    und Fehlerbericht des Kerns (für Protokoll und Build-Probe, nicht für die Oberfläche)."""

    def __init__(self, message: str = "Der Rechenkern für Tabellen läuft nicht mehr.", detail: str = "") -> None:
        super().__init__(message, "kern")
        self.detail = detail


def profile_dir() -> Path:
    """Eigenes Profil des Rechenkerns – neben dem für das Umwandeln (zwei LibreOffice teilen sich kein Profil)."""
    return office.profile_dir().parent / "tabelle"


def soffice() -> Path | None:
    """Das Programm, das gestartet wird: unter Windows ``soffice.bin`` direkt (ein Prozess, sicher im Job-Objekt),
    sonst ``soffice``."""
    found = office.libreoffice()
    if found is None:
        return None
    if os.name == "nt":
        binary = found.with_name("soffice.bin")
        if binary.is_file():
            return binary
    return found


def available() -> bool:
    return office.TEST_INSTALLED is None and soffice() is not None


class Engine:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._job = None
        self._socket: socket.socket | None = None
        self._reader = None
        self._writer = None
        self._lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._next = 1
        self._work: Path | None = None
        self.closed = False
        self.last_exit: int | None = None
        self.last_error = ""

    @property
    def running(self) -> bool:
        return self._socket is not None and self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """LibreOffice mit dem Kern starten und verbinden (blockiert: im Hintergrund aufrufen)."""
        with self._start_lock:
            if self.running:
                return
            if self.closed:
                raise EngineGone("Novadesk wird beendet.")
            self._shutdown_process()
            executable = soffice()
            if executable is None:
                raise EngineGone(office.missing_text("excel"))
            self._warm_up(executable)
            for attempt in range(2):
                code = self._launch(executable)
                if code is None:
                    return
                if code != RESTART_CODE or attempt:
                    raise EngineGone(f"Der Rechenkern für Tabellen ließ sich nicht starten (LibreOffice endete mit Code {code}).",
                                     self.detail())

    def _prepare_profile(self) -> Path:
        profile = profile_dir()
        user = profile / "user"
        scripts = user / "Scripts" / "python"
        scripts.mkdir(parents=True, exist_ok=True)
        source = SERVER_SOURCE.read_bytes()
        target = scripts / SCRIPT_NAME
        if not target.is_file() or target.read_bytes() != source:
            temp = target.with_suffix(".tmp")
            temp.write_bytes(source)
            os.replace(temp, target)
        settings = user / "registrymodifications.xcu"
        if not settings.is_file() or b"UseLocking" not in settings.read_bytes():
            settings.write_text(PROFILE_SETTINGS, encoding="utf-8")
        return profile

    def _command(self, executable: Path, profile: Path) -> list[str]:
        return [str(executable), "--headless", "--invisible", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
                "--nofirststartwizard", f"-env:UserInstallation={profile.as_uri()}"]

    def _environment(self) -> dict:
        environment = dict(os.environ)
        if os.name != "nt":
            environment["SAL_USE_VCLPLUGIN"] = "svp"
        return environment

    def _warm_up(self, executable: Path) -> None:
        """Neues Profil: LibreOffice einmal ohne Kern starten und gleich beenden lassen. Unter Windows endet der erste
        Start mit einem neuen Profil oft mit »bitte neu starten« (Code 81) – auch nachdem der Kern schon lief."""
        profile = self._prepare_profile()
        marker = profile / "user" / READY_MARKER
        if marker.is_file():
            return
        flags = office.CREATE_NO_WINDOW if os.name == "nt" else 0
        for _attempt in range(3):
            try:
                code = subprocess.run([*self._command(executable, profile), "--terminate_after_init"], env=self._environment(),
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=flags, timeout=START_TIMEOUT, check=False).returncode
            except (OSError, subprocess.TimeoutExpired):
                return  # dann richtet sich das Profil beim eigentlichen Start ein
            if code != RESTART_CODE:
                break
        try:
            marker.write_text("1", encoding="utf-8")
        except OSError:
            pass

    def _launch(self, executable: Path) -> int | None:
        """Ein Startversuch: ``None`` = läuft und ist verbunden, sonst der Exit-Code von LibreOffice."""
        profile = self._prepare_profile()
        self._work = Path(tempfile.mkdtemp(prefix="novadesk-tabelle-"))
        port_file = self._work / "port"
        token = secrets.token_hex(24)
        environment = {**self._environment(), "NOVADESK_TABELLE_PORT": str(port_file), "NOVADESK_TABELLE_SCHLUESSEL": token}
        command = [*self._command(executable, profile), SCRIPT_URL]
        log = (self._work / "soffice.log").open("wb")
        flags = office.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(command, cwd=str(self._work), env=environment, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=log, creationflags=flags)
        log.close()
        if os.name == "nt":
            from assistant import runtime

            self._job = runtime._bind_to_app(self._process)  # noqa: SLF001 - dasselbe Job-Objekt wie die KI
        deadline = time.monotonic() + START_TIMEOUT
        while not port_file.is_file():
            code = self._process.poll()
            if code is not None:
                self._shutdown_process()
                return code
            failure = Path(str(port_file) + ".fehler")
            if failure.is_file():
                self._shutdown_process()
                raise EngineGone("Der Rechenkern für Tabellen ließ sich nicht starten.", self.detail())
            if time.monotonic() > deadline:
                self._shutdown_process()
                raise EngineGone("Der Rechenkern für Tabellen hat nicht rechtzeitig geantwortet.")
            time.sleep(0.03)
        port = int(port_file.read_text().strip())
        connection = socket.create_connection(("127.0.0.1", port), timeout=30)
        connection.settimeout(None)
        self._socket = connection
        self._reader = connection.makefile("r", encoding="utf-8", newline="\n")
        self._writer = connection.makefile("w", encoding="utf-8", newline="\n")
        self._writer.write(json.dumps({"token": token}) + "\n")
        self._writer.flush()
        hello = self._reader.readline()
        if not hello or not json.loads(hello).get("ok"):
            self._shutdown_process()
            raise EngineGone("Der Rechenkern für Tabellen hat die Verbindung abgelehnt.")
        return None

    def call(self, command: str, timeout: float = CALL_TIMEOUT, **args):
        """Befehl an den Kern; gibt das Ergebnis zurück oder wirft ``CalcError`` (``EngineGone``, wenn er nicht mehr
        läuft – dann ist auch jedes geöffnete Dokument fort)."""
        if not self.running:
            self._shutdown_process()
            raise EngineGone(detail=self.detail())
        with self._lock:
            ident = self._next
            self._next += 1
            try:
                self._socket.settimeout(timeout)
                self._writer.write(json.dumps({"id": ident, "cmd": command, "args": args}) + "\n")
                self._writer.flush()
                line = self._reader.readline()
            except (OSError, ValueError) as exc:
                self._shutdown_process(wait=2.0)
                raise EngineGone(detail=self.detail()) from exc
            if not line:
                self._shutdown_process(wait=2.0)
                raise EngineGone(detail=self.detail())
            answer = json.loads(line)
        if answer.get("ok"):
            return answer.get("result")
        if answer.get("code") == "intern" and answer.get("trace"):
            raise CalcError(f"Interner Fehler des Rechenkerns ({answer.get('error')})", "intern")
        raise CalcError(str(answer.get("error") or "Unbekannter Fehler"), str(answer.get("code") or "fehler"))

    def stop(self) -> None:
        """Beenden: Dokumente ohne Speichern schließen, LibreOffice beenden (spätestens nach einigen Sekunden)."""
        self.closed = True
        if self.running:
            try:
                self.call("quit", timeout=5)
            except CalcError:
                pass
        self._shutdown_process(wait=5.0)

    def _shutdown_process(self, wait: float = 0.0) -> None:
        for stream in (self._reader, self._writer, self._socket):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._reader = self._writer = self._socket = None
        process, self._process = self._process, None
        if process is not None:
            self.last_exit = None
            try:
                process.wait(timeout=wait) if wait else None
            except subprocess.TimeoutExpired:
                pass
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                                   creationflags=office.CREATE_NO_WINDOW, check=False)
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
        """Exit-Code von LibreOffice und Fehlerbericht des Kerns (nach dem Ende des Prozesses)."""
        parts = [f"LibreOffice-Exit-Code {self.last_exit}"] if self.last_exit is not None else []
        if self.last_error:
            parts.append(self.last_error)
        return "\n".join(parts)

    def _cleanup(self) -> None:
        work, self._work = self._work, None
        if work is not None:
            texts = []
            for name in ("port.fehler", "soffice.log"):
                try:
                    text = (work / name).read_text(encoding="utf-8", errors="replace").strip() if (work / name).is_file() else ""
                except OSError:
                    text = ""
                if text:
                    texts.append(f"{name}: {text[-3000:]}")
            self.last_error = "\n".join(texts)
            shutil.rmtree(work, ignore_errors=True)


def column_name(index: int) -> str:
    """0 → A, 25 → Z, 26 → AA (Spaltenname wie in Excel)."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def cell_name(row: int, col: int) -> str:
    return f"{column_name(col)}{row + 1}"


def parse_cell(text: str) -> tuple[int, int] | None:
    """»D6« → (5, 3); auch »$D$6« und Kleinbuchstaben – sonst ``None``."""
    text = text.strip().replace("$", "").upper()
    letters = ""
    for char in text:
        if "A" <= char <= "Z":
            letters += char
        else:
            break
    digits = text[len(letters):]
    if not letters or not digits.isdigit() or len(letters) > 3:
        return None
    col = 0
    for char in letters:
        col = col * 26 + (ord(char) - 64)
    row = int(digits)
    if row < 1 or col < 1:
        return None
    return row - 1, col - 1


def parse_range(text: str) -> tuple[int, int, int, int] | None:
    """»A1:C3« bzw. »B2« → (Zeile, Spalte, letzte Zeile, letzte Spalte)."""
    parts = text.split(":")
    if len(parts) == 1:
        cell = parse_cell(parts[0])
        return (cell[0], cell[1], cell[0], cell[1]) if cell else None
    if len(parts) != 2:
        return None
    first, last = parse_cell(parts[0]), parse_cell(parts[1])
    if first is None or last is None:
        return None
    return min(first[0], last[0]), min(first[1], last[1]), max(first[0], last[0]), max(first[1], last[1])

