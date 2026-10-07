"""Attrappe von llama-server (llama.cpp) für Tests des KI-Assistenten – nur die Standardbibliothek, kein Modell.

Versteht dieselben Aufrufparameter und dieselbe Schnittstelle wie das Original, soweit PDF Tool sie nutzt:
``GET /health`` (503, solange das »Modell lädt«, danach 200) und ``POST /v1/chat/completions`` mit gestreamter
Antwort (Server-Sent Events, »data: {…}« je Stück, zuletzt »data: [DONE]«). Der Schlüssel kommt wie beim Original aus
``LLAMA_API_KEY``; ohne passenden »Authorization: Bearer …« antwortet die Attrappe mit 401.

Die Antworten sind fest und nennen die Seiten der Auszüge, die sie bekommen hat (»[Seite N]«) – so lässt sich
prüfen, welche Abschnitte PDF Tool schickt und wie es Seitenangaben verlinkt. Steuerung über die Umgebung:

* ``FAKE_LLAMA_LOAD`` – Sekunden »Modell laden« (Standard 0,3)
* ``FAKE_LLAMA_MODE`` – ``slow`` (lange, langsame Antwort: Abbrechen), ``context`` (Fehler »Kontext zu groß«),
  ``crash`` (Prozess endet beim Start mit Code 3), ``hang`` (lädt nie fertig)
* ``FAKE_LLAMA_LOG`` – Datei, in die jede Anfrage als JSON-Zeile geschrieben wird (nur in Tests, Testordner)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STARTED = time.monotonic()
LOAD = float(os.environ.get("FAKE_LLAMA_LOAD", "0.3"))
MODE = os.environ.get("FAKE_LLAMA_MODE", "")
LOG = os.environ.get("FAKE_LLAMA_LOG", "")
KEY = os.environ.get("LLAMA_API_KEY", "")
_LOG_LOCK = threading.Lock()


def answer_for(messages: list[dict]) -> str:
    """Feste Antwort je Art der Anfrage – mit den Seiten der mitgeschickten Auszüge."""
    content = str((messages[-1] if messages else {}).get("content") or "")
    pages = [int(value) for value in re.findall(r"\[Seite (\d+)\]", content)]
    first = pages[0] if pages else 1
    last = pages[-1] if pages else 1
    if content.startswith("Stichpunkte aus den Teilen"):
        return f"- Gesamtüberblick über das Dokument (S. 1)\n- **Wichtigste Frist:** drei Monate (S. {first})"
    match = re.match(r"Teil (\d+) von (\d+)", content)
    if match:
        return f"- Inhalt von Teil {match.group(1)} (S. {first}–{last})"
    if "Fasse das Dokument" in content:
        return f"## Überblick\n- Vertrag über eine Versicherung (S. {first})\n- Beitrag: 49,90 € im Monat (S. {last})"
    if MODE == "slow":
        return " ".join(["Wort"] * 400)
    return f"Laut Dokument beträgt die Kündigungsfrist drei Monate (S. {first}). Weitere Angaben stehen auf Seite {last}."


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - wie das Original: kein Protokoll
        return

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path != "/health":
            self._json(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})
            return
        if MODE == "hang" or time.monotonic() - STARTED < LOAD:
            self._json(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
            return
        self._json(200, {"status": "ok"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"code": 404, "message": "File Not Found", "type": "not_found_error"}})
            return
        if self.headers.get("Authorization") != f"Bearer {KEY}" or not KEY:
            self._json(401, {"error": {"code": 401, "message": "Invalid API Key", "type": "authentication_error"}})
            return
        if time.monotonic() - STARTED < LOAD:
            self._json(503, {"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
            return
        body = json.loads(raw or b"{}")
        if LOG:
            with _LOG_LOCK, open(LOG, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"messages": body.get("messages"), "max_tokens": body.get("max_tokens"), "stream": body.get("stream"), "options": body.get("chat_template_kwargs")}, ensure_ascii=False) + "\n")
        if MODE == "context":
            self._json(400, {"error": {"code": 400, "message": "the request exceeds the available context size, try increasing it", "type": "exceed_context_size_error"}})
            return
        text = answer_for(body.get("messages") or [])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        pieces = re.findall(r"\S+\s*|\s+", text)
        try:
            for piece in pieces:
                self._event({"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
                time.sleep(0.2 if MODE == "slow" else 0.005)
            self._event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": len(raw) // 4, "completion_tokens": len(pieces)}})
            self._chunk(b"data: [DONE]\n\n")
            self._chunk(b"")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return  # abgebrochen: wie das Original hört die Attrappe auf zu »rechnen«

    def _event(self, data: dict) -> None:
        self._chunk(b"data: " + json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n\n")

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--ctx-size", type=int, default=0)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--no-webui", action="store_true")
    parser.add_argument("--log-disable", action="store_true")
    args = parser.parse_args()
    if MODE == "crash":
        return 3
    if not Path(args.model).is_file():
        return 1
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
