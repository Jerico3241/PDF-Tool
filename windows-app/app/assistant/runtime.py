"""Der lokale KI-Prozess: llama.cpp (``llama-server``, MIT-Lizenz) mit einem Sprachmodell aus ``store``.

* Gebündelt im Installationsordner (``ai\\llama-server.exe`` mit seinen DLLs, siehe ``build.py``), sonst
  ``PDFTOOL_LLAMA_SERVER`` (Pfad zur ausführbaren Datei – Entwicklung und Tests).
* Nur ``127.0.0.1``, ein freier Port, ein zufälliger Schlüssel (über die Umgebung, nicht in der Befehlszeile) – andere
  Programme auf dem PC können ihn nicht nutzen.
* Ohne Weboberfläche und ohne Protokoll; unter Windows ohne Konsolenfenster, mit niedriger Priorität (die Oberfläche
  bleibt flüssig) und in einem Job-Objekt: Endet PDF Tool – auch unerwartet –, endet der Prozess mit.
* ``start`` wartet, bis das Modell geladen ist; ``stop`` beendet den Prozess (die App ruft es nach einer Weile ohne
  Anfrage und beim Beenden auf – der Arbeitsspeicher wird wieder frei).
"""

from __future__ import annotations

import ctypes
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .client import AssistantError, Endpoint, health

INSTALL_DIR = Path(__file__).resolve().parents[2]  # wie appstate.INSTALL_DIR (…\app\assistant\runtime.py)
BUNDLED_DIR = INSTALL_DIR / "ai"
SERVER_VARIABLE = "PDFTOOL_LLAMA_SERVER"
CONTEXT = 8192  # Tokens – reicht für Auszüge, Frage und Antwort
LOAD_TIMEOUT = 300.0  # Modell laden (erster Start: Virenscanner, langsame Festplatte)
POLL = 0.25
STOP_TIMEOUT = 5.0
CREATE_NO_WINDOW = 0x08000000
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
DLL_NOT_FOUND = (0xC0000135, -1073741515)
ILLEGAL_INSTRUCTION = (0xC000001D, -1073741795)


def server_path() -> Path | None:
    """Die ausführbare Datei von llama-server – ``None``, wenn sie fehlt."""
    configured = os.environ.get(SERVER_VARIABLE, "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    bundled = BUNDLED_DIR / name
    return bundled if bundled.is_file() else None


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def total_memory() -> int:
    """Arbeitsspeicher des PCs in Bytes (0: unbekannt)."""
    if os.name == "nt":
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32), ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.ullTotalPhys)
        except (OSError, AttributeError):
            return 0
        return 0
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError, AttributeError):
        return 0


class Server:
    """Ein laufender llama-server – höchstens einer je App."""

    def __init__(self, executable: Path, model: Path) -> None:
        self.executable = Path(executable)
        self.model = Path(model)
        self.endpoint: Endpoint | None = None
        self._process: subprocess.Popen | None = None
        self._job = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self, cancelled: threading.Event | None = None) -> Endpoint:
        """Prozess starten und warten, bis das Modell geladen ist (Arbeitsthread). Wirft ``AssistantError``."""
        if not self.model.is_file():
            raise AssistantError("Das Sprachmodell fehlt. Bitte den KI-Assistenten in den Einstellungen neu einrichten.")
        endpoint = Endpoint(free_port(), secrets.token_urlsafe(24))
        # Attrappe in Tests (``PDFTOOL_LLAMA_SERVER`` zeigt auf ein Python-Skript): mit diesem Python starten
        program = [sys.executable, str(self.executable)] if self.executable.suffix.lower() == ".py" else [str(self.executable)]
        command = [
            *program,
            "--model", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(endpoint.port),
            "--ctx-size", str(CONTEXT),
            "--parallel", "1",
            "--no-webui",
            "--log-disable",
        ]
        environment = dict(os.environ, LLAMA_API_KEY=endpoint.key)
        environment.pop("LLAMA_ARG_API_KEY_FILE", None)
        flags = CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command, cwd=str(self.executable.parent), env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
            )
        except OSError as exc:
            raise AssistantError("Der KI-Assistent konnte nicht gestartet werden.") from exc
        with self._lock:
            self._process = process
            self._job = _bind_to_app(process)
        deadline = time.monotonic() + LOAD_TIMEOUT
        while True:
            code = process.poll()
            if code is not None:
                self.stop()
                raise AssistantError(_exit_text(code))
            if cancelled is not None and cancelled.is_set():
                self.stop()
                raise AssistantError("Abgebrochen.")
            state = health(endpoint, timeout=1.0)
            if state == "ok":
                self.endpoint = endpoint
                return endpoint
            if time.monotonic() >= deadline:
                self.stop()
                raise AssistantError("Das Sprachmodell lädt zu lange. Bitte den PC neu starten oder das kleinere Modell wählen.")
            time.sleep(POLL)

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            job, self._job = self._job, None
            self.endpoint = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    pass
        if job is not None:
            _close_handle(job)


def _exit_text(code: int) -> str:
    if code in DLL_NOT_FOUND:
        return "Dem KI-Assistenten fehlt eine Programmdatei. Bitte PDF Tool neu installieren."
    if code in ILLEGAL_INSTRUCTION:
        return "Der Prozessor dieses PCs unterstützt den KI-Assistenten nicht."
    return f"Der KI-Assistent wurde unerwartet beendet (Code {code}). Vielleicht reicht der Arbeitsspeicher nicht – das kleinere Modell braucht weniger."


def _bind_to_app(process: subprocess.Popen):
    """Windows: Prozess in ein Job-Objekt mit »beim Schließen beenden« – endet PDF Tool, endet er mit. Das Handle des
    Jobs hält ``Server`` bis ``stop``; die App selbst bleibt außerhalb des Jobs."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit), ("IoInfo", ctypes.c_ulonglong * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # JobObjectExtendedLimitInformation
            _close_handle(job)
            return None
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):  # type: ignore[attr-defined]
            _close_handle(job)
            return None
        return job
    except Exception:  # noqa: BLE001 - ohne Job-Objekt beendet ``stop`` den Prozess trotzdem
        return None


def _close_handle(handle) -> None:
    if os.name != "nt" or not handle:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        pass


def platform_supported() -> bool:
    """Gebündelt nur für Windows (64 Bit); andere Systeme nur mit ``PDFTOOL_LLAMA_SERVER`` (Tests, Entwicklung)."""
    return (os.name == "nt" and sys.maxsize > 2**32) or bool(os.environ.get(SERVER_VARIABLE))
