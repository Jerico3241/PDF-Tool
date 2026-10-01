"""Lokaler Testserver, der sich wie GitHub verhält – für Updater-Tests ohne Internet.

* ``/repositories/1382108244/releases`` – Release-Liste wie die GitHub-API
* ``/Jerico3241/PDF-Tool/releases/download/<Tag>/<Datei>`` – leitet wie GitHub auf
  ``/storage/<Datei>`` weiter (Speicher für Release-Dateien)

Einstellbar je Test: langsame Übertragung, Statuscodes (404, 500, Anfragelimit), Weiterleitung
zu einem fremden Ziel, abgebrochene Übertragung, ungültiges JSON, keine Antwort. Jede Anfrage
wird protokolliert (``requests``). Nur ``127.0.0.1`` – nie ein echtes Netzwerk.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

REPO_PATH = "/Jerico3241/PDF-Tool"
RELEASES_PATH = "/repositories/1382108244/releases"


class UpdateServer:
    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}  # Pfad → Inhalt
        self.redirects: dict[str, str] = {}  # Pfad → Ziel (Location)
        self.status: dict[str, int] = {}  # Pfad → Statuscode statt Inhalt
        self.headers: dict[str, dict[str, str]] = {}  # Pfad → zusätzliche Kopfzeilen
        self.truncate: dict[str, int] = {}  # Pfad → nach so vielen Bytes Verbindung trennen
        self.raw_releases: bytes | None = None  # ungültige Antwort statt der Liste
        self.silent: set[str] = set()  # Pfade, auf die nie geantwortet wird (Zeitüberschreitung)
        self.chunk = 64 * 1024
        self.delay = 0.0  # Pause je Block (langsames Netz)
        self.requests: list[str] = []
        self._stop = threading.Event()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def releases_url(self) -> str:
        return self.base + RELEASES_PATH + "?per_page=30"

    def stop(self) -> None:
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()

    def count(self, part: str) -> int:
        return sum(1 for path in self.requests if part in path)

    # Releases veröffentlichen ------------------------------------------------------------------------------
    def download_path(self, tag: str, name: str) -> str:
        return f"{REPO_PATH}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}"

    def publish(
        self,
        version: str,
        setup: bytes | None = None,
        *,
        checksum: str | bytes | None = "auto",
        prerelease: bool | None = None,
        draft: bool = False,
        notes: str = "## Neu\n\n- Verbesserungen",
        digest: str | None = "auto",
        published: str = "2026-10-01T08:43:37Z",
    ) -> bytes:
        """Release ``v<version>`` mit Setup (Standard: Testinhalt) und Prüfsummendatei anlegen."""
        tag = "v" + version
        name = f"PDF-Tool-Setup-{version}.exe"
        data = setup if setup is not None else b"MZ" + (f"PDF Tool {version} Setup ".encode() * 20000)
        actual = hashlib.sha256(data).hexdigest()
        assets = [self._asset(tag, name, data, actual if digest == "auto" else digest)]
        if checksum is not None:
            content = f"{actual}  {name}\n".encode() if checksum == "auto" else (checksum.encode() if isinstance(checksum, str) else checksum)
            assets.append(self._asset(tag, name + ".sha256", content, None))
        self.releases.insert(
            0,
            {
                "tag_name": tag,
                "name": f"PDF Tool {version}",
                "body": notes,
                "draft": draft,
                "prerelease": ("-" in version) if prerelease is None else prerelease,
                "published_at": published,
                "html_url": f"{self.base}{REPO_PATH}/releases/tag/{quote(tag, safe='')}",
                "assets": assets,
            },
        )
        return data

    def _asset(self, tag: str, name: str, content: bytes, digest: str | None) -> dict:
        path = self.download_path(tag, name)
        storage = f"/storage/{quote(tag, safe='')}/{quote(name, safe='')}"
        self.files[storage] = content
        self.redirects[path] = self.base + storage + "?sig=test"
        entry = {"name": name, "size": len(content), "state": "uploaded", "browser_download_url": self.base + path}
        if digest:
            entry["digest"] = f"sha256:{digest}"
        return entry

    def storage(self, version: str, suffix: str = "") -> str:
        tag = "v" + version
        return f"/storage/{quote(tag, safe='')}/{quote(f'PDF-Tool-Setup-{version}.exe{suffix}', safe='')}"

    # HTTP --------------------------------------------------------------------------------------------------------
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                pass

            def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None, path: str = "") -> None:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                for key, value in server.headers.get(path, {}).items():
                    self.send_header(key, value)
                self.end_headers()
                cut = server.truncate.get(path)
                sent = 0
                for start in range(0, len(body), server.chunk):
                    if server._stop.is_set():
                        return
                    piece = body[start : start + server.chunk]
                    if cut is not None and sent + len(piece) > cut:
                        self.wfile.write(piece[: max(0, cut - sent)])
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    try:
                        self.wfile.write(piece)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    sent += len(piece)
                    if server.delay:
                        time.sleep(server.delay)

            def do_GET(self) -> None:  # noqa: N802 - http.server
                path = unquote(urlsplit(self.path).path)
                raw_path = urlsplit(self.path).path
                server.requests.append(path)
                if raw_path in server.silent or path in server.silent:
                    server._stop.wait(30)
                    return
                status = server.status.get(raw_path) or server.status.get(path)
                if status:
                    self._send(status, b'{"message": "Fehler"}', {"Content-Type": "application/json"}, raw_path)
                    return
                if path == RELEASES_PATH:
                    if self.headers.get("User-Agent", "").find("PDF-Tool") < 0:
                        self._send(403, b'{"message": "User-Agent fehlt"}')
                        return
                    body = server.raw_releases if server.raw_releases is not None else json.dumps(server.releases).encode()
                    self._send(200, body, {"Content-Type": "application/json"}, raw_path)
                    return
                if raw_path in server.redirects:
                    self.send_response(302)
                    self.send_header("Location", server.redirects[raw_path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if raw_path in server.files:
                    self._send(200, server.files[raw_path], {"Content-Type": "application/octet-stream"}, raw_path)
                    return
                self._send(404, b'{"message": "Not Found"}', {"Content-Type": "application/json"}, raw_path)

        return Handler
