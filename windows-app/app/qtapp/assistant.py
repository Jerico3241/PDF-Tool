"""KI-Assistent in der Oberfläche (QML: ``Assistant``): einrichten, Modell laden und entfernen (Einstellungen), Fragen
und Zusammenfassungen zum geöffneten PDF (rechte Seitenleiste des Readers). Seit 4.0 Beta 6 auch: Fragen über mehrere
PDFs oder einen Ordner (Scans über die Texterkennung) und »Dokument übersetzen« als neues PDF.

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
from assistant import library as pdflibrary
from assistant import text as doctext
from assistant.client import AssistantError, Cancelled, Chat
from assistant.prompts import (ANSWER_TOKENS, LANGUAGES, PART_TOKENS, QUESTION_CHARS, combine_messages, library_messages, part_messages, plan_summary, question_messages,
                               summary_messages, translate_messages, translation_parts, translation_tokens)

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
# ``assistant.text.rich``), ``pages`` die genannten Seiten (1-basiert), ``sources`` bei mehreren PDFs die genannten
# Stellen ({label, file, page})
ENTRY_ROLES = ("key", "kind", "text", "rich", "pending", "note", "pages", "sources", "own")
LIBRARY = "__mehrere__"  # Gespräch über mehrere PDFs (statt eines Dokument-Tabs)


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
    # Fragen an mehrere PDFs: Bezeichnung (»12 PDFs aus »Verträge««, leer = das geöffnete Dokument)
    scopeLabelChanged, scopeLabel = prop(str, "scopeLabel", "")

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
        self._library: pdflibrary.Library | None = None
        self._library_index: doctext.Index | None = None
        self._translate_language = "en"
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
            self.cancelDownload()  # aus heißt: nichts wird geladen (der Teil bleibt zum Fortsetzen)
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
        # vorgewählt: die Empfehlung – ist sie schon eingerichtet (»Anderes Modell …«), das andere Modell
        missing = [model for model in catalog.MODELS if not store.installed(model)]
        choice = recommended if recommended in missing or not missing else missing[0]
        data = {"models": models, "ram": _gb(ram) if ram else "", "lowMemory": 0 < ram < catalog.MIN_RAM, "free": _gb(store.free_space()), "choice": choice.key}
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
            if self.state == "setup":
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
        """Download fertig: SHA-256 im Hintergrund prüfen, erst dann ist das Modell eingerichtet. Ein anderes Modell
        wird danach gelöscht (Platz sparen) – vorher endet der KI-Prozess, der es geladen haben kann (Windows sperrt
        eine geladene Datei)."""
        self._transfer = None
        self._download_model = None
        self.state = "verify"
        self.progress = 1.0
        self.progressText = "Prüfsumme wird geprüft …"
        from updater.verifier import file_sha256

        def check() -> bool:
            if file_sha256(store.partial(model)) != model.sha256:
                store.remove(model)
                return False
            self._end_server()
            store.mark_verified(model)
            for other in catalog.MODELS:
                if other.key != model.key:
                    store.remove(other)  # auch Reste unterbrochener Downloads
            return True

        def done(ok: bool) -> None:
            self.progressText = ""
            self.progress = 0.0
            if not ok:
                self._select(None)
                self.state = "off"
                self._refresh_state()
                self.statusText = "Die geladene Datei war beschädigt und wurde gelöscht. Bitte erneut laden."
                self.app.notify("assistant", "error", self.statusText, title="Prüfsumme stimmt nicht", actions=(("Erneut laden", lambda: self.download(model.key)),))
                self._log().warning("KI-Modell: Prüfsumme stimmt nicht – Datei verworfen")
                return
            self._select(model)
            self.state = "off"  # damit _refresh_state neu bewertet
            self._refresh_state()
            self.app.persist()
            self.app.notify("assistant", "success", f"Das Modell »{model.name}« ist eingerichtet. Fragen stellen Sie im Reader in der Seitenleiste »KI-Assistent«.", title="KI-Assistent bereit", auto_hide=8000)

        def failed(exc: BaseException, _details: str) -> None:
            self.progressText = ""
            self.progress = 0.0
            self._select(self._model() if self._model() is not None and store.installed(self._model()) else None)
            self.state = "off"
            self._refresh_state()
            if self.state != "ready":
                self.statusText = "Die geladene Datei konnte nicht geprüft oder übernommen werden (Speicherplatz, Zugriffsrechte)."
            self._log().warning("KI-Modell: Prüfung fehlgeschlagen (%s)", type(exc).__name__)

        self.app.worker.run(check, done, failed)

    @Slot()
    def removeModel(self) -> None:  # noqa: N802
        """Modell (und unterbrochene Downloads) löschen – nach Rückfrage. Der Assistent bleibt eingeschaltet, kann aber
        erst nach erneutem Einrichten antworten. Gelöscht wird im Hintergrund, nachdem der KI-Prozess beendet ist."""
        models = [model for model in catalog.MODELS if store.installed(model) or store.partial_size(model)]
        if not models or self.state == "verify":
            return
        size = sum(model.size if store.installed(model) else store.partial_size(model) for model in models)
        if not self.app.dialogs.confirm("Sprachmodell entfernen?", f"Das Sprachmodell wird von diesem PC gelöscht – {_gb(size)} werden frei. Zum erneuten Einrichten muss es wieder geladen werden.", "Entfernen"):
            return
        self.stop()
        if self._transfer is not None:
            transfer, self._transfer = self._transfer, None
            self._download_model = None
            transfer.cancel()

        def work() -> int:
            self._end_server()
            return sum(store.remove(model) for model in catalog.MODELS)

        def done(freed: int) -> None:
            self._select(None)
            self.state = "off"
            self._refresh_state()
            self.app.persist()
            left = [model for model in catalog.MODELS if store.path(model).exists() or store.partial(model).exists()]
            if left:
                self.app.notify("assistant", "warning", "Das Sprachmodell ließ sich nicht vollständig löschen – vielleicht ist die Datei gerade geöffnet. Bitte später erneut versuchen.", title="Nicht vollständig entfernt")
            else:
                self.app.set_status(f"Sprachmodell entfernt – {_gb(freed)} frei.", "success")

        def failed(exc: BaseException, _details: str) -> None:
            self._log().warning("KI-Modell: Entfernen fehlgeschlagen (%s)", type(exc).__name__)
            done(0)

        self.app.worker.run(work, done, failed)

    def _end_server(self) -> None:
        """KI-Prozess beenden und warten, bis er weg ist (Arbeitsthread) – danach lässt sich das Modell löschen."""
        with self._server_lock:
            server, self._server = self._server, None
        if server is not None:
            server.stop()

    # Fragen und Zusammenfassen ----------------------------------------------------------------------------------
    def _document(self):
        return self.reader.current if self.reader is not None else None

    def _current_key(self) -> str:
        """Gespräch, das die Seitenleiste zeigt: mehrere PDFs oder das aktive Dokument."""
        if self.scopeLabel:
            return LIBRARY
        doc = self._document()
        return doc.ident if doc is not None else ""

    def _show_current(self) -> None:
        """Anderer Tab: dessen Gespräch zeigen; Gespräche geschlossener Dokumente verfallen."""
        key = self._current_key()
        self.conversation.set_items(self._conversations.get(key, []) if key else [])
        open_docs = set(self.reader.tabs.keys()) if self.reader is not None else set()
        open_docs.add(LIBRARY)
        for ident in [ident for ident in list(self._conversations) + list(self._indexes) if ident not in open_docs]:
            self._conversations.pop(ident, None)
            self._indexes.pop(ident, None)
        if self._answer_owner and self._answer_owner not in open_docs:
            self.stop()

    def _push(self, ident: str, entry: dict) -> int:
        conversation = self._conversations.setdefault(ident, [])
        self._serial += 1
        conversation.append({"key": f"e{self._serial}", "rich": "", "pending": False, "note": "", "pages": [], "sources": [], "own": False, **entry})
        self._publish(ident)
        return len(conversation) - 1

    def _update(self, ident: str, index: int, **changes) -> None:
        conversation = self._conversations.get(ident)
        if conversation is None or index >= len(conversation):
            return
        conversation[index] = {**conversation[index], **changes}
        self._publish(ident)

    def _publish(self, ident: str) -> None:
        if ident and ident == self._current_key():
            self.conversation.set_items(self._conversations.get(ident, []))

    @Slot(str)
    def ask(self, question: str) -> None:
        question = " ".join(str(question or "").split())[:MAX_QUESTION]
        if question and self.scopeLabel:
            self._ask_library(question)
        elif question:
            self._start("question", question)

    @Slot()
    def summarize(self) -> None:
        self._start("summary", "")

    def _can_answer(self) -> catalog.Model | None:
        model = self._model()
        if self.busy or not self.enabled or model is None or not store.installed(model):
            return None
        if not self.available:
            self.app.notify("assistant", "warning", "Der KI-Assistent ist in dieser Installation nicht enthalten.", title="KI-Assistent")
            return None
        return model

    def _start(self, kind: str, question: str) -> None:
        doc = self._document()
        if doc is None or self.scopeLabel:
            return
        model = self._can_answer()
        if model is None:
            return
        ident = doc.ident
        self._push(ident, {"kind": "question", "text": question if kind == "question" else "Dokument zusammenfassen", "own": kind == "question"})
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

    def _finish(self, ident: str, index: int, *, text: str = "", page_count: int = 0, scope: str = "", error: str = "", cancelled: bool = False, plain: bool = False) -> None:
        if error:
            self._update(ident, index, kind="error", text=error, rich="", pending=False, note="")
        elif cancelled:
            conversation = self._conversations.get(ident, [])
            current = conversation[index] if index < len(conversation) else {}
            if current.get("text"):
                self._update(ident, index, pending=False, note="Abgebrochen.")
            else:
                self._update(ident, index, kind="note", text="Abgebrochen.", rich="", pending=False, note="")
        elif ident == LIBRARY and self._library is not None and not plain:
            names, counts = self._library_names(), self._library.page_counts
            sources = [{"label": f"{names[file]} · S. {page}", "file": file, "page": page} for file, page in doctext.cited_sources(text, counts)[:12]]
            self._update(ident, index, text=text, rich=doctext.rich(text, 0, names, counts), pending=False, note=scope, sources=sources)
        else:
            pages = doctext.cited_pages(text, page_count) if not plain else []
            self._update(ident, index, text=text, rich=doctext.rich(text, page_count), pending=False, note=scope, pages=pages)
        self.busy = False
        self._answer_owner = ""
        self.app.timers.later("assistant:idle", IDLE_MS, self._stop_server)

    # Mehrere PDFs -------------------------------------------------------------------------------------------------
    def _library_names(self) -> list[str]:
        return [path.name for path in self._library.files] if self._library is not None else []

    def _ocr(self, cancel: threading.Event):
        """Texterkennung für Scans, wenn der Reader sie gefunden hat – sonst ``None``."""
        engine = getattr(self.reader, "_ocr_engine", None) if self.reader is not None else None
        if engine is None:
            return None
        languages = [code for code in ("deu", "eng") if code in engine.languages] or list(engine.languages[:1])
        return pdflibrary.tesseract_text(engine, languages, cancel) if languages else None

    @Slot()
    def chooseFiles(self) -> None:  # noqa: N802
        from . import files

        if self.busy:
            return
        start = self.app.initial_dir("assistant", self.reader.source_dir if self.reader is not None else "")
        paths = files.open_files("Mehrere PDFs fragen – PDFs wählen", start, files.PDF_FILTER)
        if paths:
            self._load_library(paths)

    @Slot()
    def chooseFolder(self) -> None:  # noqa: N802
        from . import files

        if self.busy:
            return
        start = self.app.initial_dir("assistant", self.reader.source_dir if self.reader is not None else "")
        folder = files.pick_folder("Mehrere PDFs fragen – Ordner wählen", start)
        if folder:
            self._load_library([folder])

    @Slot()
    def clearScope(self) -> None:  # noqa: N802
        """Zurück zu Fragen an das geöffnete Dokument."""
        if self.busy:
            self.stop()
        self._library = None
        self._library_index = None
        self._conversations.pop(LIBRARY, None)
        self.scopeLabel = ""
        self._show_current()

    def _load_library(self, paths: list[str]) -> None:
        """PDFs lesen (im Hintergrund, mit Fortschritt im Gespräch) – danach gehen Fragen an alle."""
        model = self._can_answer()
        if model is None:
            return
        self._conversations[LIBRARY] = []
        self._library = None
        self._library_index = None
        self.scopeLabel = "PDFs werden gelesen …"
        self._show_current()
        index = self._push(LIBRARY, {"kind": "answer", "text": "", "pending": True, "note": "PDFs werden gesucht …"})
        self.busy = True
        self._answer_owner = LIBRARY
        self._cancel = threading.Event()
        cancel = self._cancel
        worker = self.app.worker
        ocr = self._ocr(cancel)

        def work() -> pdflibrary.Library:
            found = pdflibrary.collect(paths)
            if not found:
                return pdflibrary.Library([], [], [])
            note = lambda done, total, name: worker.post(self._note, LIBRARY, index, f"Datei {done + 1} von {total}: {name}")  # noqa: E731
            return pdflibrary.read(found, ocr=ocr, cancel=cancel, progress=note)

        def done(result: pdflibrary.Library) -> None:
            if not result.files:
                self.scopeLabel = ""
                self._conversations.pop(LIBRARY, None)
                self.busy = False
                self._answer_owner = ""
                self._show_current()
                message = f"Keine lesbare PDF gefunden{' (' + ', '.join(result.unreadable[:3]) + ')' if result.unreadable else ''}."
                self.app.notify("assistant", "warning", message, title="Mehrere PDFs fragen")
                return
            self._library = result
            self._library_index = doctext.Index(result.items)
            self.scopeLabel = result.label
            pages = sum(result.page_counts)
            parts = [f"{len(result.files)} {'PDF' if len(result.files) == 1 else 'PDFs'} mit {pages} {'Seite' if pages == 1 else 'Seiten'} gelesen. Fragen gehen jetzt an alle; die Antwort nennt Datei und Seite."]
            if result.recognized:
                parts.append(f"{result.recognized} {'Scan-Seite' if result.recognized == 1 else 'Scan-Seiten'} per Texterkennung gelesen.")
            if result.scans:
                parts.append(f"Ohne lesbaren Text: {', '.join(result.scans[:4])}{' …' if len(result.scans) > 4 else ''}" + ("" if ocr is not None else " – für Scans die Texterkennung einrichten (»Text erkennen (OCR)«)."))
            if result.unreadable:
                parts.append(f"Nicht lesbar (beschädigt oder mit Kennwort): {', '.join(result.unreadable[:4])}{' …' if len(result.unreadable) > 4 else ''}.")
            if result.truncated:
                parts.append(f"Gelesen wurden höchstens {pdflibrary.MAX_FILES} Dateien bzw. etwa {pdflibrary.MAX_CHARS // 1_000_000} Millionen Zeichen.")
            self._update(LIBRARY, index, kind="note", text=" ".join(parts), pending=False, note="")
            self.busy = False
            self._answer_owner = ""

        def failed(exc: BaseException, _details: str) -> None:
            self.busy = False
            self._answer_owner = ""
            self._library = None
            self.scopeLabel = ""
            self._conversations.pop(LIBRARY, None)
            self._show_current()
            if not (isinstance(exc, Cancelled) or cancel.is_set()):
                self._log().warning("KI-Assistent: PDFs nicht lesbar (%s)", type(exc).__name__)
                self.app.notify("assistant", "error", "Die PDFs konnten nicht gelesen werden.", title="Mehrere PDFs fragen")

        worker.run(work, done, failed)

    def _ask_library(self, question: str) -> None:
        model = self._can_answer()
        if model is None or self._library is None or self._library_index is None:
            return
        self._push(LIBRARY, {"kind": "question", "text": question, "own": True})
        index = self._push(LIBRARY, {"kind": "answer", "text": "", "pending": True, "note": "Passende Stellen werden gesucht …"})
        self.busy = True
        self._answer_owner = LIBRARY
        self._cancel = threading.Event()
        cancel = self._cancel
        worker = self.app.worker
        names, counts, search = self._library_names(), list(self._library.page_counts), self._library_index
        self.app.timers.cancel("assistant:idle")

        def work() -> str:
            if sum(len(item.text) for item in search.items) < MIN_TEXT:
                return ""
            excerpts = search.search(question, QUESTION_CHARS)
            endpoint = self._ensure_server(model, cancel, lambda note: worker.post(self._note, LIBRARY, index, note))
            stream = _Stream(worker, lambda value: self._update(LIBRARY, index, text=value, rich=doctext.rich(value, 0, names, counts), note=""))
            return self._chat(endpoint, library_messages(question, excerpts, names), ANSWER_TOKENS, cancel, stream)

        def done(text: str) -> None:
            if not text and sum(len(item.text) for item in search.items) < MIN_TEXT:
                self._finish(LIBRARY, index, error="Die gewählten PDFs enthalten keinen lesbaren Text (vermutlich Scans).")
                return
            self._finish(LIBRARY, index, text=text.strip() or "Der Assistent hat keine Antwort geliefert.")

        def failed(exc: BaseException, _details: str) -> None:
            if isinstance(exc, Cancelled) or cancel.is_set():
                self._finish(LIBRARY, index, cancelled=True)
                return
            self._finish(LIBRARY, index, error=str(exc) if isinstance(exc, AssistantError) else "Der KI-Assistent konnte nicht antworten.")

        worker.run(work, done, failed)

    @Slot(int, int)
    def openSource(self, file: int, page: int) -> None:  # noqa: N802
        """Stelle aus einer Antwort über mehrere PDFs: Datei im Reader öffnen und zur Seite springen."""
        if self._library is None or self.reader is None or not 0 <= file < len(self._library.files):
            return
        path = str(self._library.files[file])

        def show(doc) -> None:
            if doc is not None and 1 <= page <= doc.pageCount:
                doc.goTo(page - 1)

        self.reader.open_paths([path], then=show)

    # Übersetzen ---------------------------------------------------------------------------------------------------
    @Slot()
    def translate(self) -> None:
        """»Dokument übersetzen«: Sprache und Seiten wählen, Ziel bestimmen, Seite für Seite übersetzen, als neues PDF
        speichern und öffnen. Abbrechen verwirft die Übersetzung."""
        doc = self._document()
        if doc is None or self.scopeLabel or self._can_answer() is None:
            return
        data = {"languages": [{"key": key, "label": value[0]} for key, value in LANGUAGES.items()], "pageCount": doc.pageCount, "language": self._translate_language}
        answer, result = self.app.dialogs.ask("assistant_translate", "Dokument übersetzen", "", primary="Übersetzen …", close="Abbrechen", data=data, width=560)
        result = result or {}
        language = str(result.get("language") or "")
        if answer != "primary" or language not in LANGUAGES:
            return
        self._translate_language = language
        first = max(0, min(doc.pageCount - 1, int(result.get("first") or 0)))
        last = max(first, min(doc.pageCount - 1, int(result.get("last", doc.pageCount - 1))))
        label = LANGUAGES[language][0]
        stem = doc.name[:-4] if doc.name.lower().endswith(".pdf") else doc.name
        target = self.reader.pick_save_pdf(f"{stem} ({label}).pdf", "Übersetzung speichern")
        if not target:
            return
        import os

        if doc.path and os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(doc.path)):
            self.app.notify("assistant", "warning", "Die Übersetzung braucht einen eigenen Dateinamen – das Original bleibt unverändert.", title="Nicht übersetzt")
            return
        model = self._can_answer()
        if model is None or self._document() is not doc:
            return
        ident = doc.ident
        name = LANGUAGES[language][1]
        asked = f"Seite {first + 1} ins {name} übersetzen" if first == last else f"Seiten {first + 1}–{last + 1} ins {name} übersetzen"
        self._push(ident, {"kind": "question", "text": asked})
        index = self._push(ident, {"kind": "answer", "text": "", "pending": True, "note": "Dokument wird gelesen …"})
        self.busy = True
        self._answer_owner = ident
        self._cancel = threading.Event()
        self.app.timers.cancel("assistant:idle")

        def fail(exc: BaseException) -> None:
            self._finish(ident, index, error="Der Text des Dokuments konnte nicht gelesen werden.")

        doc.assistant_texts(lambda texts: self._translate_texts(doc, ident, index, model, texts, first, last, language, target), fail)

    def _translate_texts(self, doc, ident: str, index: int, model: catalog.Model, texts: list[str], first: int, last: int, language: str, target: str) -> None:
        cancel = self._cancel
        if cancel.is_set():
            self._finish(ident, index, cancelled=True)
            return
        worker = self.app.worker
        label = LANGUAGES[language][0]
        source = doc.path if doc.path and not doc.dirty else ""
        ocr = self._ocr(cancel) if source else None
        name = doc.name

        def work() -> dict:
            from assistant import translation

            pages: list[str] = []
            endpoint = None
            empty = 0
            total = last - first + 1
            for number, page in enumerate(range(first, last + 1), start=1):
                if cancel.is_set():
                    raise Cancelled()
                text = doctext.clean(texts[page] if page < len(texts) else "")
                if len(text) < pdflibrary.MIN_PAGE_TEXT and ocr is not None:
                    worker.post(self._note, ident, index, f"Seite {number} von {total}: Text wird erkannt …")
                    text = doctext.clean(_recognize_page(source, page, ocr))
                if len(text) < pdflibrary.MIN_PAGE_TEXT:
                    pages.append("")
                    empty += 1
                    continue
                if endpoint is None:
                    endpoint = self._ensure_server(model, cancel, lambda note: worker.post(self._note, ident, index, note))
                done_parts = []
                parts = translation_parts(text)
                for part_number, part in enumerate(parts, start=1):
                    step = f" (Teil {part_number} von {len(parts)})" if len(parts) > 1 else ""
                    worker.post(self._note, ident, index, f"Seite {number} von {total} wird übersetzt{step} …")
                    done_parts.append(self._chat(endpoint, translate_messages(part, language), translation_tokens(part), cancel, None).strip())
                pages.append("\n\n".join(done_parts))
            if cancel.is_set():
                raise Cancelled()
            if empty == total:
                return {"empty": True}
            path = translation.write_pdf(pages, target, source_name=name, language=label)
            return {"path": str(path), "pages": total, "empty": empty}

        def done(result: dict) -> None:
            if result.get("empty"):
                self._finish(ident, index, error="Diese Seiten enthalten keinen lesbaren Text (vermutlich ein Scan). Erst »Text erkennen (OCR)« ausführen – danach lässt sich das Dokument übersetzen.")
                return
            path = result["path"]
            import os

            count = "1 Seite" if result["pages"] == 1 else f"{result['pages']} Seiten"
            text = f"Übersetzung ins {LANGUAGES[language][1]} gespeichert: **{os.path.basename(path)}** ({count})."
            if result["empty"]:
                text += " 1 Seite ohne Text blieb leer." if result["empty"] == 1 else f" {result['empty']} Seiten ohne Text blieben leer."
            self._finish(ident, index, text=text, plain=True)
            if self.reader is not None:
                self.reader.open_paths([path])

        def failed(exc: BaseException, _details: str) -> None:
            if isinstance(exc, Cancelled) or cancel.is_set():
                self._finish(ident, index, cancelled=True)
                return
            message = str(exc) if isinstance(exc, AssistantError) else "Die Übersetzung konnte nicht gespeichert werden."
            if not isinstance(exc, AssistantError):
                self._log().warning("KI-Assistent: Übersetzung fehlgeschlagen (%s)", type(exc).__name__)
            self._finish(ident, index, error=message)

        worker.run(work, done, failed)

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


def _recognize_page(path: str, page: int, ocr) -> str:
    """Eine Seite der gespeicherten Datei als Bild erkennen (Übersetzen eines Scans)."""
    import io

    import pypdfium2 as pdfium

    from pdfium_lock import PDFIUM_LOCK

    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(path)
        try:
            image = document[page].render(scale=pdflibrary.OCR_DPI / 72).to_pil()
        finally:
            document.close()
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return ocr(buffer.getvalue(), pdflibrary.OCR_DPI)


def _copy(value: str) -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(value)
