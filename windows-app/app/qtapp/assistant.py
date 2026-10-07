"""KI-Assistent in der Oberfläche (QML: ``Assistant``): einrichten, Modell laden und entfernen (Einstellungen), Fragen
und Zusammenfassungen zum geöffneten PDF (rechte Seitenleiste des Readers).

Standardmäßig aus. Eingeschaltet lädt »Einrichten …« ein Modell aus ``assistant.catalog`` – nur nach ausdrücklicher
Wahl, über HTTPS von Hugging Face (Weiterleitungen nur dorthin), fortsetzbar, mit SHA-256-Prüfung vor der ersten
Nutzung. Der KI-Prozess startet erst mit der ersten Frage, endet nach ``IDLE_MS`` ohne Anfrage und beim Beenden.

Das Gespräch gehört zum jeweiligen Dokument-Tab und lebt nur im Arbeitsspeicher. Dokumenttexte, Fragen und Antworten
werden nie gespeichert oder protokolliert – nur Fehlerarten.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from assistant import catalog, runtime, store
from assistant import text as doctext
from assistant.client import AssistantError, Cancelled, Chat
from assistant.prompts import ANSWER_TOKENS, PART_TOKENS, QUESTION_CHARS, combine_messages, part_messages, plan_summary, question_messages, summary_messages

from .base import Observable, prop
from .models import KeyedListModel

ENABLED_KEY = "ki_assistent"  # gui-config.json: eingeschaltet
MODEL_KEY = "ki_modell"  # gui-config.json: gewähltes Modell
IDLE_MS = 10 * 60 * 1000  # so lange ohne Anfrage bleibt das Modell geladen
STREAM_INTERVAL = 0.08  # Sekunden: gestreamte Antwort höchstens so oft an die Oberfläche
MIN_TEXT = 40  # weniger lesbare Zeichen: das PDF hat praktisch keinen Text (Scan)
MAX_QUESTION = 1000
HF_HOSTS = frozenset({catalog.SOURCE_HOST})
HF_SUFFIXES = (".hf.co", ".huggingface.co")  # Speicher von Hugging Face (Weiterleitungen beim Download)
# Einträge des Gesprächs: question, answer, error oder note; ``rich`` ist die Antwort zum Anzeigen (siehe
# ``assistant.text.rich``), ``pages`` die genannten Seiten (1-basiert)
ENTRY_ROLES = ("key", "kind", "text", "rich", "pending", "note", "pages")


def _gb(value: int) -> str:
    return f"{value / 1024**3:.1f}".replace(".", ",") + " GB"


def _duration(seconds: float) -> str:
    if seconds < 90:
        return "unter 2 Min."
    minutes = int(round(seconds / 60))
    return f"{minutes} Min." if minutes < 90 else f"{minutes // 60} Std. {minutes % 60} Min."


class AssistantController(Observable):
    enabledChanged, enabled = prop(bool, "enabled", False)
    availableChanged, available = prop(bool, "available", False)  # Laufzeit vorhanden (Windows-Setup)
    # off (aus) · setup (eingeschaltet, kein Modell) · download · verify (Prüfsumme) · ready
    stateChanged, state = prop(str, "state", "off")
    modelKeyChanged, modelKey = prop(str, "modelKey", "")
    modelNameChanged, modelName = prop(str, "modelName", "")
    modelSizeChanged, modelSize = prop(str, "modelSize", "")
    progressChanged, progress = prop(float, "progress", 0.0)
    progressTextChanged, progressText = prop(str, "progressText", "")
    statusTextChanged, statusText = prop(str, "statusText", "")
    partialChanged, partial = prop(str, "partial", "")  # unterbrochener Download: Modell-Schlüssel
    busyChanged, busy = prop(bool, "busy", False)  # eine Antwort läuft

    def __init__(self, app, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.reader = None  # ReaderController (nach dem Einrichten der Werkzeuge)
        self._server: runtime.Server | None = None
        self._server_lock = threading.Lock()
        self._chat_obj: Chat | None = None  # laufende Anfrage (abbrechbar)
        self._cancel = threading.Event()
        self._transfer = None
        self._download_model: catalog.Model | None = None
        self._client = None
        self._conversations: dict[str, list[dict]] = {}  # Dokument → Gespräch
        self._serial = 0
        # Gespräch zum aktuellen Dokument; beim Schreiben einer Antwort ändert sich nur deren Zeile
        self.conversation = KeyedListModel(ENTRY_ROLES, key="key", parent=self)
        self._indexes: dict[str, tuple[int, doctext.Index, int]] = {}  # Dokument → (Stand, Index, Zeichen)
        self._answer_owner = ""
        self._download_started = 0.0
        self._download_offset = 0
        self.set_quietly("available", runtime.server_path() is not None and runtime.platform_supported())
        self.set_quietly("enabled", cfg.get(ENABLED_KEY) is True)
        chosen = catalog.get(str(cfg.get(MODEL_KEY) or ""))
        if chosen is None or not store.installed(chosen):
            installed = store.installed_models()
            chosen = installed[0] if installed else None
        self._select(chosen)
        self._refresh_state()
        app.register_config(self.config)
        app.register_work(self.running_work)
        app.at_shutdown(self.shutdown)

    # Einrichtung ------------------------------------------------------------------------------------------------
    def attach_reader(self, reader) -> None:
        self.reader = reader
        reader.currentChanged.connect(self._show_current)
        reader.tabs.countChanged.connect(self._show_current)  # Tab im Hintergrund geschlossen: Gespräch verwerfen

    def config(self) -> dict:
        return {ENABLED_KEY: bool(self.enabled), MODEL_KEY: self.modelKey or None}

    def running_work(self) -> str:
        if self._transfer is not None:
            return "KI-Modell wird geladen"
        return "KI-Assistent antwortet" if self.busy else ""

    def _select(self, model: catalog.Model | None) -> None:
        self.modelKey = model.key if model is not None else ""
        self.modelName = f"{model.name} ({model.description.split(' – ')[0]})" if model is not None else ""
        self.modelSize = _gb(model.size) if model is not None else ""
        partials = [entry.key for entry in catalog.MODELS if store.partial_size(entry) > 0]
        self.partial = partials[0] if partials else ""

    def _model(self) -> catalog.Model | None:
        return catalog.get(self.modelKey)

    def _refresh_state(self) -> None:
        if self._transfer is not None or self.state == "verify":
            return
        model = self._model()
        if model is None or not store.installed(model):
            # gewähltes Modell fehlt: ein anderes eingerichtetes übernehmen (etwa nach dem Einrichten in einem anderen Lauf)
            installed = store.installed_models()
            if installed:
                model = installed[0]
                self._select(model)
        if not self.enabled:
            self.state = "off"
            self.statusText = "Aus – nichts wird geladen, kein Speicherplatz belegt." if model is None else f"Aus – Modell »{model.name}« bleibt gespeichert ({_gb(model.size)})."
        elif model is None or not store.installed(model):
            self.state = "setup"
            self.statusText = "Noch kein Sprachmodell eingerichtet."
        else:
            self.state = "ready"
            self.statusText = f"Bereit – Modell »{model.name}« ({_gb(model.size)}), läuft nur auf diesem PC."

    # Ein- und ausschalten ----------------------------------------------------------------------------------------
    @Slot(bool)
    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if not enabled:
            self.stop()
            self._stop_server()
            if self.reader is not None:
                self.reader.close_right_panel("assistant")
        self._refresh_state()
        self.app.persist()
        self.app.set_status("KI-Assistent eingeschaltet." if enabled else "KI-Assistent ausgeschaltet.", "success")

    # Modell laden -------------------------------------------------------------------------------------------------
    @Slot()
    def setup(self) -> None:
        """Dialog »KI-Assistent einrichten«: Modell wählen (Empfehlung nach Arbeitsspeicher), danach laden."""
        if self._transfer is not None:
            return
        ram = runtime.total_memory()
        recommended = catalog.recommended(ram)
        models = [
            {
                "key": model.key, "name": model.name, "description": model.description, "size": _gb(model.size),
                "memory": _gb(model.memory), "recommended": model is recommended, "installed": store.installed(model),
                "resume": _gb(store.partial_size(model)) if store.partial_size(model) else "", "page": model.page,
            }
            for model in catalog.MODELS
        ]
        data = {"models": models, "ram": _gb(ram) if ram else "", "lowMemory": 0 < ram < catalog.MIN_RAM, "free": _gb(store.free_space()), "choice": recommended.key}
        answer, result = self.app.dialogs.ask("assistant_setup", "KI-Assistent einrichten", "", primary="Herunterladen", close="Abbrechen", data=data, width=560)
        if answer != "primary":
            return
        model = catalog.get(str((result or {}).get("model") or ""))
        if model is not None:
            self.download(model.key)

    @Slot(str)
    def download(self, key: str) -> None:
        model = catalog.get(key)
        if model is None or self._transfer is not None:
            return
        if store.installed(model):
            self._select(model)
            self.enabled = True
            self._refresh_state()
            self.app.persist()
            return
        free = store.free_space()
        if free and free < store.space_needed(model):
            self.app.notify("assistant", "warning", f"Für das Modell »{model.name}« werden {_gb(store.space_needed(model))} freier Speicherplatz gebraucht – frei sind {_gb(free)}.", title="Nicht genug Speicherplatz")
            return
        from updater.transport import HttpClient

        if self._client is None:
            self._client = HttpClient(self._policy(), user_agent="PDF-Tool", parent=self)
        offset = store.partial_size(model)
        self._download_model = model
        self._download_offset = offset
        self._download_started = time.monotonic()
        self.enabled = True
        self.state = "download"
        self.progress = offset / model.size
        self.progressText = "Verbindung wird aufgebaut …"
        self.statusText = f"Modell »{model.name}« wird geladen ({_gb(model.size)})."
        self.app.persist()
        self._transfer = self._client.download(
            model.url, store.partial(model), max_bytes=model.size, expected_size=model.size, offset=offset, keep_partial=True,
            on_done=lambda _path: self._downloaded(model), on_error=lambda error: self._download_failed(model, error),
            on_progress=lambda received, total: self._download_progress(model, received, total),
        )
        if self._transfer is None:  # Adresse nicht erlaubt – bei den festen Adressen ausgeschlossen
            self._download_model = None
            self.state = "setup"

    def _policy(self):
        from updater.policy import UrlPolicy

        return UrlPolicy(HF_HOSTS, HF_SUFFIXES)

    def _download_progress(self, model: catalog.Model, received: int, total: int) -> None:
        total = total or model.size
        self.progress = min(1.0, received / total) if total else 0.0
        elapsed = time.monotonic() - self._download_started
        loaded = received - self._download_offset
        text = f"{_gb(received)} von {_gb(total)}"
        if elapsed > 2 and loaded > 0:
            speed = loaded / elapsed
            text += f" · {speed / 1024**2:.1f} MB/s · noch {_duration((total - received) / speed)}".replace(".", ",", 1)
        self.progressText = text

    def _download_failed(self, model: catalog.Model, error) -> None:
        self._transfer = None
        self._download_model = None
        self._select(self._model() if self._model() is not None and store.installed(self._model()) else None)
        self.partial = model.key if store.partial_size(model) else ""
        self.progress = 0.0
        self.progressText = ""
        kind = getattr(error, "kind", "")
        self.state = "off"  # neu bewerten: Ist ein anderes Modell eingerichtet, bleibt der Assistent bereit
        self._refresh_state()
        if kind == "cancelled":
            if self.state != "ready":
                self.statusText = "Download angehalten – »Download fortsetzen« lädt den Rest." if self.partial else "Download abgebrochen."
            return
        texts = {
            "offline": "Keine Verbindung zum Internet. Der Download lässt sich später fortsetzen.",
            "timeout": "Die Verbindung ist abgebrochen. Der Download lässt sich fortsetzen.",
            "tls": "Die sichere Verbindung zu Hugging Face konnte nicht geprüft werden.",
            "policy": "Der Download wurde an eine unerwartete Adresse umgeleitet und deshalb abgebrochen.",
            "size": "Die Datei hatte nicht die erwartete Größe und wurde verworfen.",
            "io": "Die Datei konnte nicht gespeichert werden (Speicherplatz, Zugriffsrechte).",
        }
        message = texts.get(kind, "Das Modell konnte nicht geladen werden.")
        if self.state != "ready":
            self.statusText = message
        self.app.notify("assistant", "error", message, title="Download nicht möglich", actions=(("Erneut versuchen", lambda: self.download(model.key)),))
        self._log().info("KI-Modell: Download fehlgeschlagen (%s)", kind or type(error).__name__)

    @Slot()
    def cancelDownload(self) -> None:  # noqa: N802
        """Download anhalten – die geladenen Teile bleiben, »Fortsetzen« lädt den Rest."""
        transfer, model = self._transfer, self._download_model
        if transfer is None or model is None:
            return
        transfer.cancel()  # meldet keinen Fehler (eigener Abbruch)
        self._download_failed(model, _Cancelled())

    def _downloaded(self, model: catalog.Model) -> None:
        """Download fertig: SHA-256 im Hintergrund prüfen, erst dann ist das Modell eingerichtet."""
        self._transfer = None
        self._download_model = None
        self.state = "verify"
        self.progress = 1.0
        self.progressText = "Prüfsumme wird geprüft …"
        from updater.verifier import file_sha256

        def check() -> bool:
            return file_sha256(store.partial(model)) == model.sha256

        def done(ok: bool) -> None:
            self.progressText = ""
            self.progress = 0.0
            if not ok:
                store.remove(model)
                self._select(None)
                self.state = "setup"
                self.statusText = "Die geladene Datei war beschädigt und wurde gelöscht. Bitte erneut laden."
                self.app.notify("assistant", "error", self.statusText, title="Prüfsumme stimmt nicht", actions=(("Erneut laden", lambda: self.download(model.key)),))
                self._log().warning("KI-Modell: Prüfsumme stimmt nicht – Datei verworfen")
                return
            store.mark_verified(model)
            self._remove_others(model)
            self._select(model)
            self.state = "off"  # damit _refresh_state neu bewertet
            self._refresh_state()
            self.app.persist()
            self.app.notify("assistant", "success", f"Das Modell »{model.name}« ist eingerichtet. Fragen stellen Sie im Reader in der Seitenleiste »KI-Assistent«.", title="KI-Assistent bereit", auto_hide=8000)

        def failed(exc: BaseException, _details: str) -> None:
            self.state = "setup"
            self.progressText = ""
            self.statusText = "Die geladene Datei konnte nicht geprüft werden."
            self._log().warning("KI-Modell: Prüfung fehlgeschlagen (%s)", type(exc).__name__)

        self.app.worker.run(check, done, failed)

    def _remove_others(self, keep: catalog.Model) -> None:
        """Nach dem Wechsel des Modells: das andere (und Reste unterbrochener Downloads) löschen – Platz sparen."""
        for model in catalog.MODELS:
            if model.key != keep.key:
                store.remove(model)

    @Slot()
    def removeModel(self) -> None:  # noqa: N802
        """Modell (und unterbrochene Downloads) löschen – nach Rückfrage. Der Assistent bleibt eingeschaltet, kann aber
        erst nach erneutem Einrichten antworten."""
        models = [model for model in catalog.MODELS if store.installed(model) or store.partial_size(model)]
        if not models:
            return
        size = sum(model.size if store.installed(model) else store.partial_size(model) for model in models)
        if not self.app.dialogs.confirm("Sprachmodell entfernen?", f"Das Sprachmodell wird von diesem PC gelöscht – {_gb(size)} werden frei. Zum erneuten Einrichten muss es wieder geladen werden.", "Entfernen"):
            return
        self.stop()
        self._stop_server()
        if self._transfer is not None:
            transfer, self._transfer = self._transfer, None
            transfer.cancel()
        freed = sum(store.remove(model) for model in catalog.MODELS)
        self._select(None)
        self.state = "off"
        self._refresh_state()
        self.app.persist()
        self.app.set_status(f"Sprachmodell entfernt – {_gb(freed)} frei.", "success")

    # Fragen und Zusammenfassen ----------------------------------------------------------------------------------
    def _document(self):
        return self.reader.current if self.reader is not None else None

    def _show_current(self) -> None:
        """Anderer Tab: dessen Gespräch zeigen; Gespräche geschlossener Dokumente verfallen."""
        doc = self._document()
        self.conversation.set_items(self._conversations.get(doc.ident, []) if doc is not None else [])
        open_docs = set(self.reader.tabs.keys()) if self.reader is not None else set()
        for ident in [ident for ident in list(self._conversations) + list(self._indexes) if ident not in open_docs]:
            self._conversations.pop(ident, None)
            self._indexes.pop(ident, None)
        if self._answer_owner and self._answer_owner not in open_docs:
            self.stop()

    def _push(self, ident: str, entry: dict) -> int:
        conversation = self._conversations.setdefault(ident, [])
        self._serial += 1
        conversation.append({"key": f"e{self._serial}", "rich": "", "pending": False, "note": "", "pages": [], **entry})
        self._publish(ident)
        return len(conversation) - 1

    def _update(self, ident: str, index: int, **changes) -> None:
        conversation = self._conversations.get(ident)
        if conversation is None or index >= len(conversation):
            return
        conversation[index] = {**conversation[index], **changes}
        self._publish(ident)

    def _publish(self, ident: str) -> None:
        doc = self._document()
        if doc is not None and doc.ident == ident:
            self.conversation.set_items(self._conversations.get(ident, []))

    @Slot(str)
    def ask(self, question: str) -> None:
        question = " ".join(str(question or "").split())[:MAX_QUESTION]
        if question:
            self._start("question", question)

    @Slot()
    def summarize(self) -> None:
        self._start("summary", "")

    def _start(self, kind: str, question: str) -> None:
        doc = self._document()
        model = self._model()
        if doc is None or self.busy or not self.enabled or model is None or not store.installed(model):
            return
        if not self.available:
            self.app.notify("assistant", "warning", "Der KI-Assistent ist in dieser Installation nicht enthalten.", title="KI-Assistent")
            return
        ident = doc.ident
        self._push(ident, {"kind": "question", "text": question if kind == "question" else "Dokument zusammenfassen"})
        index = self._push(ident, {"kind": "answer", "text": "", "pending": True, "note": "Dokument wird gelesen …"})
        self.busy = True
        self._answer_owner = ident
        self._cancel = threading.Event()
        self.app.timers.cancel("assistant:idle")

        def fail(exc: BaseException) -> None:
            self._finish(ident, index, error="Der Text des Dokuments konnte nicht gelesen werden.")
            self._log().info("KI-Assistent: Text nicht lesbar (%s)", type(exc).__name__)

        doc.assistant_texts(lambda texts: self._with_texts(doc, ident, index, kind, question, model, texts), fail)

    def _with_texts(self, doc, ident: str, index: int, kind: str, question: str, model: catalog.Model, texts: list[str]) -> None:
        if self._cancel.is_set():
            self._finish(ident, index, cancelled=True)
            return
        revision = doc.revision
        page_count = len(texts)
        cancel = self._cancel
        worker = self.app.worker

        def work() -> dict:
            cached = self._indexes.get(ident)
            if cached is not None and cached[0] == revision:
                _revision, index_, chars = cached
            else:
                items = doctext.passages(texts)
                index_ = doctext.Index(items)
                chars = sum(len(item.text) for item in items)
                self._indexes[ident] = (revision, index_, chars)
            if chars < MIN_TEXT:
                return {"empty": True}
            endpoint = self._ensure_server(model, cancel, lambda note: worker.post(self._note, ident, index, note))
            stream = _Stream(worker, lambda value: self._update(ident, index, text=value, rich=doctext.rich(value, page_count), note=""))
            if kind == "question":
                excerpts = index_.search(question, QUESTION_CHARS)
                text = self._chat(endpoint, question_messages(question, excerpts), ANSWER_TOKENS, cancel, stream)
                return {"text": text, "scope": ""}
            plan = plan_summary(index_.items)
            if len(plan.parts) == 1:
                text = self._chat(endpoint, summary_messages(plan.parts[0]), ANSWER_TOKENS, cancel, stream)
            else:
                notes = []
                for number, part in enumerate(plan.parts, 1):
                    worker.post(self._note, ident, index, f"Teil {number} von {len(plan.parts)} wird gelesen …")
                    notes.append(self._chat(endpoint, part_messages(part, number, len(plan.parts)), PART_TOKENS, cancel, None))
                worker.post(self._note, ident, index, "Zusammenfassung wird geschrieben …")
                text = self._chat(endpoint, combine_messages(notes, plan.last_page, plan.complete), ANSWER_TOKENS, cancel, stream)
            scope = "" if plan.complete else f"Zusammengefasst wurden die Seiten 1 bis {plan.last_page} von {page_count} – längere Dokumente liest der Assistent nur bis dahin."
            return {"text": text, "scope": scope}

        def done(result: dict) -> None:
            if result.get("empty"):
                self._finish(ident, index, error="Dieses PDF enthält keinen lesbaren Text (vermutlich ein Scan). Erst »Text erkennen (OCR)« ausführen – danach kann der Assistent es lesen.")
                return
            answer = result["text"].strip() or "Der Assistent hat keine Antwort geliefert."
            self._finish(ident, index, text=answer, page_count=page_count, scope=result.get("scope", ""))

        def failed(exc: BaseException, _details: str) -> None:
            if isinstance(exc, Cancelled) or cancel.is_set():
                self._finish(ident, index, cancelled=True)
                return
            message = str(exc) if isinstance(exc, AssistantError) else "Der KI-Assistent konnte nicht antworten."
            if not isinstance(exc, AssistantError):
                self._log().warning("KI-Assistent: Fehler (%s)", type(exc).__name__)
            self._finish(ident, index, error=message)

        worker.run(work, done, failed)

    def _note(self, ident: str, index: int, note: str) -> None:
        self._update(ident, index, note=note)

    def _chat(self, endpoint, messages: list[dict], max_tokens: int, cancel: threading.Event, stream) -> str:
        """Eine Anfrage im Arbeitsthread; ``stream`` bekommt den wachsenden Text (oder ``None``)."""
        if cancel.is_set():
            raise Cancelled()
        chat = Chat(endpoint, messages, max_tokens=max_tokens)
        self._chat_obj = chat
        if cancel.is_set():
            raise Cancelled()
        try:
            result = chat.run(stream.add if stream is not None else None)
        finally:
            self._chat_obj = None
        if stream is not None:
            stream.flush()
        return result.text

    def _ensure_server(self, model: catalog.Model, cancel: threading.Event, note) -> object:
        """KI-Prozess starten, falls er nicht läuft (Arbeitsthread) – Ergebnis: ``Endpoint``."""
        with self._server_lock:
            server = self._server
            if server is not None and server.running and server.endpoint is not None and server.model == store.path(model):
                return server.endpoint
            if server is not None:
                server.stop()
            executable = runtime.server_path()
            if executable is None:
                raise AssistantError("Der KI-Assistent ist in dieser Installation nicht enthalten.")
            note("Sprachmodell wird geladen …")
            server = runtime.Server(executable, store.path(model))
            self._server = server
        endpoint = server.start(cancel)
        note("Antwort wird geschrieben …")
        return endpoint

    def _finish(self, ident: str, index: int, *, text: str = "", page_count: int = 0, scope: str = "", error: str = "", cancelled: bool = False) -> None:
        if error:
            self._update(ident, index, kind="error", text=error, rich="", pending=False, note="")
        elif cancelled:
            conversation = self._conversations.get(ident, [])
            current = conversation[index] if index < len(conversation) else {}
            if current.get("text"):
                self._update(ident, index, pending=False, note="Abgebrochen.")
            else:
                self._update(ident, index, kind="note", text="Abgebrochen.", rich="", pending=False, note="")
        else:
            pages = doctext.cited_pages(text, page_count)
            self._update(ident, index, text=text, rich=doctext.rich(text, page_count), pending=False, note=scope, pages=pages)
        self.busy = False
        self._answer_owner = ""
        self.app.timers.later("assistant:idle", IDLE_MS, self._stop_server)

    @Slot()
    def stop(self) -> None:
        """Laufende Antwort abbrechen (der Prozess hört auf zu rechnen)."""
        self._cancel.set()
        chat = getattr(self, "_chat_obj", None)
        if chat is not None:
            chat.cancel()

    @Slot()
    def clear(self) -> None:
        doc = self._document()
        if doc is None or self.busy:
            return
        self._conversations.pop(doc.ident, None)
        self.conversation.set_items([])

    @Slot(str)
    def copy(self, key: str) -> None:
        entry = self.conversation.item(key)
        if entry and entry.get("text"):
            _copy(entry["text"])
            self.app.set_status("Antwort kopiert.", "success")

    @Slot(int)
    def openPage(self, page: int) -> None:  # noqa: N802
        doc = self._document()
        if doc is not None and 1 <= page <= doc.pageCount:
            doc.goTo(page - 1)

    # Beenden ------------------------------------------------------------------------------------------------------
    def _stop_server(self) -> None:
        with self._server_lock:
            server, self._server = self._server, None
        if server is not None:
            threading.Thread(target=server.stop, name="pdftool-ki-ende", daemon=True).start()

    def shutdown(self) -> None:
        self.stop()
        if self._transfer is not None:
            transfer, self._transfer = self._transfer, None
            transfer.cancel()
        with self._server_lock:
            server, self._server = self._server, None
        if server is not None:
            server.stop()

    @staticmethod
    def _log():
        from diagnostics.applog import UI, get

        return get(UI)

    # Für QML
    _constant = Signal()

    def _conversation_model(self) -> QObject:
        return self.conversation

    conversationModel = Property(QObject, _conversation_model, notify=_constant)  # noqa: N815


class _Stream:
    """Gestreamte Antwort sammeln und höchstens alle ``STREAM_INTERVAL`` Sekunden an die Oberfläche geben."""

    def __init__(self, worker, deliver) -> None:
        self.worker = worker
        self.deliver = deliver
        self.text = ""
        self._last = 0.0

    def add(self, piece: str) -> None:
        self.text += piece
        now = time.monotonic()
        if now - self._last >= STREAM_INTERVAL:
            self._last = now
            self.worker.post(self.deliver, self.text)

    def flush(self) -> None:
        self.worker.post(self.deliver, self.text)


class _Cancelled:
    kind = "cancelled"


def _copy(value: str) -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(value)
