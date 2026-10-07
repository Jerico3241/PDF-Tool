"""Anfragen an den lokalen KI-Prozess (llama-server, OpenAI-kompatible Schnittstelle) – nur ``127.0.0.1``, mit dem
zufälligen Schlüssel aus ``runtime``.

``Chat`` schickt eine Anfrage und liefert die Antwort Stück für Stück (``stream``); ``cancel()`` bricht sie aus jedem
Thread ab – der Prozess hört dann auf zu rechnen. Fehler werden zu ``AssistantError`` mit einer verständlichen Meldung;
Inhalte (Dokument, Frage, Antwort) erscheinen nie in einer Fehlermeldung oder im Protokoll.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
from dataclasses import dataclass, field
from typing import Callable

from .prompts import TEMPERATURE

HOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 600.0  # bis zum nächsten Stück der Antwort (ein langes Dokument lesen dauert auf dem Prozessor)


class AssistantError(Exception):
    """Verständliche Meldung für die Oberfläche (ohne Inhalte)."""


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Endpoint:
    port: int
    key: str

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}


@dataclass
class Result:
    text: str
    finish: str = ""  # stop, length, …
    prompt_tokens: int = 0
    tokens: int = 0
    timings: dict = field(default_factory=dict)


def health(endpoint: Endpoint, timeout: float = 2.0) -> str:
    """»ok« (bereit), »loading« (Modell wird geladen) oder »down« (nicht erreichbar)."""
    try:
        connection = http.client.HTTPConnection(HOST, endpoint.port, timeout=timeout)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return "down"
    if response.status == 200:
        return "ok"
    return "loading" if response.status == 503 else "down"


class Chat:
    """Eine Anfrage an das Modell; ``run()`` blockiert (Arbeitsthread), ``cancel()`` aus jedem Thread."""

    def __init__(self, endpoint: Endpoint, messages: list[dict], *, max_tokens: int, temperature: float = TEMPERATURE) -> None:
        self.endpoint = endpoint
        self.body = {
            "messages": messages,
            "stream": True,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": 0.9,
            "cache_prompt": True,
            # Qwen3.5: ohne »Nachdenken« – sofort die Antwort (schneller, kein Gedankentext)
            "chat_template_kwargs": {"enable_thinking": False},
            "timings_per_token": False,
        }
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._connection: http.client.HTTPConnection | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            connection = self._connection
        if connection is not None and connection.sock is not None:
            try:
                connection.sock.shutdown(socket.SHUT_RDWR)  # weckt ``run`` sofort auf
            except OSError:
                pass

    def run(self, on_text: Callable[[str], None] | None = None) -> Result:
        if self.cancelled:
            raise Cancelled()
        connection = http.client.HTTPConnection(HOST, self.endpoint.port, timeout=CONNECT_TIMEOUT)
        with self._lock:
            self._connection = connection
        try:
            try:
                connection.connect()
                connection.sock.settimeout(READ_TIMEOUT)
                connection.request("POST", "/v1/chat/completions", body=json.dumps(self.body).encode("utf-8"), headers=self.endpoint.headers())
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as exc:
                if self.cancelled:
                    raise Cancelled() from None
                raise AssistantError("Der KI-Assistent antwortet nicht. Bitte erneut versuchen.") from exc
            if response.status != 200:
                raise AssistantError(_http_error(response))
            return self._read_stream(response, on_text)
        finally:
            with self._lock:
                self._connection = None
            connection.close()

    def _read_stream(self, response: http.client.HTTPResponse, on_text: Callable[[str], None] | None) -> Result:
        parts: list[str] = []
        result = Result("")
        while True:
            try:
                line = response.readline()
            except (OSError, http.client.HTTPException) as exc:
                if self.cancelled:
                    raise Cancelled() from None
                raise AssistantError("Die Verbindung zum KI-Assistenten wurde unterbrochen.") from exc
            if self.cancelled:
                raise Cancelled()
            if not line:
                break  # Ende ohne [DONE]: die Antwort gilt bis hierher
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                break
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if "error" in data:
                raise AssistantError(_error_text(data.get("error")))
            for choice in data.get("choices") or []:
                text = (choice.get("delta") or {}).get("content") or ""
                if text:
                    parts.append(text)
                    if on_text is not None:
                        on_text(text)
                if choice.get("finish_reason"):
                    result.finish = str(choice["finish_reason"])
            usage = data.get("usage") or {}
            result.prompt_tokens = int(usage.get("prompt_tokens") or result.prompt_tokens)
            result.tokens = int(usage.get("completion_tokens") or result.tokens)
            if isinstance(data.get("timings"), dict):
                result.timings = data["timings"]
        result.text = "".join(parts)
        return result


def _http_error(response: http.client.HTTPResponse) -> str:
    try:
        data = json.loads(response.read(65536) or b"{}")
    except (ValueError, OSError, http.client.HTTPException):
        data = {}
    if response.status in (401, 403):
        return "Der KI-Assistent hat die Anfrage abgelehnt. Bitte PDF Tool neu starten."
    return _error_text(data.get("error"), response.status)


def _error_text(error, status: int | None = None) -> str:
    message = str((error or {}).get("message") or "") if isinstance(error, dict) else ""
    lowered = message.lower()
    if "context" in lowered and ("exceed" in lowered or "too long" in lowered or "size" in lowered):
        return "Der Text ist zu lang für den KI-Assistenten. Bitte eine kürzere Frage stellen oder weniger Seiten wählen."
    if "loading" in lowered:
        return "Das Sprachmodell wird noch geladen. Bitte einen Moment warten."
    suffix = f" (Fehler {status})" if status else ""
    return f"Der KI-Assistent konnte die Anfrage nicht beantworten{suffix}."
