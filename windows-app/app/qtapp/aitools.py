"""KI-Werkzeuge in der Oberfläche (seit 5.0 Beta 8) – Teil von ``AssistantController`` (QML: ``Assistant``).

* Texte und Präsentationen: markierten Text umschreiben, kürzen, ausführlicher, einfache Sprache, Ton ändern, übersetzen;
  Text schreiben lassen (an der Schreibmarke); Grammatik prüfen (Markierung oder ganzer Text, Satz für Satz übernehmen).
* Übersetzung nebeneinander: Original und Übersetzung Absatz für Absatz als neues Text-Dokument (Texte, Präsentationen,
  PDFs).
* Präsentation aus einem Thema oder aus dem geöffneten Dokument – öffnet sich als neue Präsentation.
* Tabellen: die Tabelle um die Auswahl auswerten (Kennzahlen rechnet Novadesk selbst) und ein Diagramm vorschlagen.
* PDF-Formulare: Angaben als freien Text eingeben, Vorschläge prüfen, eintragen.

Jedes Werkzeug schreibt seine Frage und Antwort in das Gespräch des Dokuments (Seitenleiste »KI-Assistent«); Knöpfe
unter der Antwort (``actions``) übernehmen das Ergebnis. Nichts wird ohne Klick in das Dokument geschrieben. Wie beim
übrigen Assistenten werden Texte, Fragen und Antworten nie gespeichert oder protokolliert.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Slot

from assistant import bilingual, formfill, slidegen, tables, writing
from assistant import text as doctext
from assistant.client import AssistantError, Cancelled
from assistant.prompts import LANGUAGES, PART_TOKENS, part_messages, plan_summary, translate_messages, translate_numbered_messages, translation_parts, translation_tokens

# Frage im Gespräch je Art der Bearbeitung
EDIT_QUESTIONS = {
    "rewrite": "Markierten Text umschreiben",
    "shorten": "Markierten Text kürzen",
    "expand": "Markierten Text ausführlicher schreiben",
    "simple": "Markierten Text in einfache Sprache bringen",
    "formal": "Ton ändern: förmlich",
    "friendly": "Ton ändern: freundlich",
    "factual": "Ton ändern: sachlich",
    "casual": "Ton ändern: locker",
    "confident": "Ton ändern: überzeugend",
}
CHART_LABELS = {"column": "Säulendiagramm", "bar": "Balkendiagramm", "line": "Liniendiagramm", "pie": "Kreisdiagramm", "area": "Flächendiagramm"}
ACTIONS = {
    "replace": {"key": "replace", "label": "Ersetzen", "icon": "arrow_swap", "tip": "Den markierten Text durch das Ergebnis ersetzen"},
    "insert": {"key": "insert", "label": "Einfügen", "icon": "text_add", "tip": "An der Schreibmarke einfügen"},
    "chart": {"key": "chart", "label": "Diagramm einfügen", "icon": "data_bar_vertical", "tip": "Das vorgeschlagene Diagramm neben der Tabelle einfügen"},
    "applyAll": {"key": "applyAll", "label": "Alle übernehmen", "icon": "checkmark", "tip": "Alle Korrekturen in den Text übernehmen"},
    "form": {"key": "form", "label": "Vorschläge prüfen …", "icon": "form_sparkle", "tip": "Vorschläge ansehen und ins Formular eintragen"},
}
MAX_SIDE_PARAGRAPHS = bilingual.MAX_PARAGRAPHS
DATA_SUFFIXES = (".txt", ".csv", ".md", ".pdf", ".docx", ".odt", ".rtf")
DATA_FILTER = "Angaben (*.txt *.csv *.md *.pdf *.docx *.odt *.rtf);;Alle Dateien (*.*)"


def _safe_name(title: str, suffix: str, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(title or "")).strip(" .")
    name = " ".join(name.split())[:60].rstrip(" .")
    return (name or fallback) + suffix


class AiTools:
    """Werkzeuge des KI-Assistenten (gemischt in ``AssistantController``)."""

    # Grundlagen ----------------------------------------------------------------------------------------------------
    def _office(self, kinds: tuple[str, ...]):
        doc = self._document()
        return doc if doc is not None and self._kind(doc) in kinds else None

    def _show_panel(self, doc) -> None:
        if self.scopeLabel:
            self.clearScope()
        if self._kind(doc) == "pdf":
            if self.reader is not None:
                self.reader.showRightPanel("assistant")
        elif hasattr(doc, "ai_show_panel"):
            doc.ai_show_panel()

    def _begin(self, doc, question: str, note: str = "Wird vorbereitet …"):
        """Frage und wartende Antwort ins Gespräch des Dokuments – ``(ident, index, model)`` oder ``None``, wenn der
        Assistent nicht antworten kann (dann zeigt die Seitenleiste, was fehlt)."""
        if doc is None or self.busy or not self.enabled:
            return None
        self._show_panel(doc)
        model = self._can_answer()
        if model is None:
            return None
        ident = doc.ident
        self._push(ident, {"kind": "question", "text": question})
        index = self._push(ident, {"kind": "answer", "text": "", "pending": True, "note": note})
        self.busy = True
        self._answer_owner = ident
        self._cancel = threading.Event()
        self.app.timers.cancel("assistant:idle")
        return ident, index, model

    def _entry_key(self, ident: str, index: int) -> str:
        conversation = self._conversations.get(ident) or []
        return conversation[index]["key"] if index < len(conversation) else ""

    def _locate(self, key: str) -> tuple[str, int] | None:
        for ident, conversation in self._conversations.items():
            for index, entry in enumerate(conversation):
                if entry.get("key") == key:
                    return ident, index
        return None

    def _failed(self, ident: str, index: int, cancel: threading.Event, message: str):
        def failed(exc: BaseException, _details: str = "") -> None:
            if isinstance(exc, Cancelled) or cancel.is_set():
                self._finish(ident, index, cancelled=True)
                return
            if isinstance(exc, AssistantError):
                self._finish(ident, index, error=str(exc))
                return
            self._log().warning("KI-Werkzeug: Fehler (%s)", type(exc).__name__)
            self._finish(ident, index, error=message)

        return failed

    def _stream(self, ident: str, index: int):
        from .assistant import _Stream

        return _Stream(self.app.worker, lambda value: self._update(ident, index, text=value, rich=doctext.rich(value, 0), note=""))

    def _endpoint(self, model, cancel: threading.Event, ident: str, index: int):
        worker = self.app.worker
        return self._ensure_server(model, cancel, lambda note: worker.post(self._note, ident, index, note))

    def _hint(self, message: str, title: str) -> None:
        self.app.notify("assistant", "info", message, title=title, auto_hide=8000)

    # Markierten Text bearbeiten ------------------------------------------------------------------------------------
    @Slot(str)
    def editSelection(self, mode: str) -> None:  # noqa: N802
        """Markierung umschreiben, kürzen, ausführlicher, einfache Sprache oder im gewählten Ton."""
        doc = self._office(("text", "praesentation"))
        if doc is None or mode not in writing.MODES or self.busy:
            return

        def got(selected: str) -> None:
            selected = selected.strip("\n")
            if not selected.strip():
                self._hint("Bitte zuerst den Text markieren, den der Assistent bearbeiten soll.", EDIT_QUESTIONS[mode])
                return
            if len(selected) > writing.MAX_EDIT_CHARS:
                self._hint("Die Markierung ist zu lang. Bitte höchstens etwa zehn Seiten auf einmal bearbeiten lassen.", EDIT_QUESTIONS[mode])
                return
            if self._document() is not doc:
                return
            started = self._begin(doc, EDIT_QUESTIONS[mode])
            if started is None:
                return
            ident, index, model = started
            key = self._entry_key(ident, index)
            self._payloads[key] = {"doc": ident, "source": selected, "kind": "edit"}
            cancel = self._cancel
            worker = self.app.worker

            def work() -> str:
                endpoint = self._endpoint(model, cancel, ident, index)
                pieces = writing.parts(selected)
                stream = self._stream(ident, index) if len(pieces) == 1 else None
                out = []
                for number, piece in enumerate(pieces, start=1):
                    if len(pieces) > 1:
                        worker.post(self._note, ident, index, f"Teil {number} von {len(pieces)} wird bearbeitet …")
                    answer = self._chat(endpoint, writing.edit_messages(mode, piece), writing.edit_tokens(mode, piece), cancel, stream,
                                        temperature=writing.TEMPERATURE_EDIT)
                    out.append(writing.plain(writing.clean_output(answer, piece)))
                return "\n\n".join(part for part in out if part)

            def done(result: str) -> None:
                if not result.strip():
                    self._finish(ident, index, error="Der Assistent hat keinen Text geliefert. Bitte erneut versuchen.")
                    return
                self._payloads.setdefault(key, {})["result"] = result
                self._finish(ident, index, text=result, plain=True, actions=[ACTIONS["replace"]])

            worker.run(work, done, self._failed(ident, index, cancel, "Der Text konnte nicht bearbeitet werden."))

        doc.ai_selection(got)

    @Slot(str)
    def translateSelection(self, language: str) -> None:  # noqa: N802
        """Markierten Text übersetzen – das Ergebnis lässt sich an seine Stelle setzen."""
        doc = self._office(("text", "praesentation"))
        if doc is None or language not in LANGUAGES or self.busy:
            return
        self._translate_language = language
        question = f"Markierung ins {LANGUAGES[language][1]} übersetzen"

        def got(selected: str) -> None:
            selected = selected.strip("\n")
            if not selected.strip():
                self._hint("Bitte zuerst den Text markieren, der übersetzt werden soll – oder »Dokument nebeneinander übersetzen« wählen.", "Übersetzen")
                return
            if len(selected) > writing.MAX_EDIT_CHARS:
                self._hint("Die Markierung ist zu lang. Für ganze Dokumente »Dokument nebeneinander übersetzen« wählen.", "Übersetzen")
                return
            if self._document() is not doc:
                return
            started = self._begin(doc, question)
            if started is None:
                return
            ident, index, model = started
            key = self._entry_key(ident, index)
            self._payloads[key] = {"doc": ident, "source": selected, "kind": "edit"}
            cancel = self._cancel
            worker = self.app.worker

            def work() -> str:
                endpoint = self._endpoint(model, cancel, ident, index)
                pieces = translation_parts(selected) or [selected]
                stream = self._stream(ident, index) if len(pieces) == 1 else None
                out = []
                for number, piece in enumerate(pieces, start=1):
                    if len(pieces) > 1:
                        worker.post(self._note, ident, index, f"Teil {number} von {len(pieces)} wird übersetzt …")
                    out.append(writing.clean_output(self._chat(endpoint, translate_messages(piece, language), translation_tokens(piece), cancel, stream), piece))
                return "\n\n".join(part for part in out if part)

            def done(result: str) -> None:
                if not result.strip():
                    self._finish(ident, index, error="Der Assistent hat keine Übersetzung geliefert. Bitte erneut versuchen.")
                    return
                self._payloads.setdefault(key, {})["result"] = result
                self._finish(ident, index, text=result, plain=True, actions=[ACTIONS["replace"]])

            worker.run(work, done, self._failed(ident, index, cancel, "Der Text konnte nicht übersetzt werden."))

        doc.ai_selection(got)

    # Text schreiben lassen -----------------------------------------------------------------------------------------
    @Slot()
    def writeText(self) -> None:  # noqa: N802
        """»Text schreiben lassen«: Auftrag eingeben; der Text passt zu dem, was vor der Schreibmarke steht."""
        doc = self._office(("text", "praesentation"))
        if doc is None or self.busy:
            return
        if self._can_answer() is None:
            self._show_panel(doc)
            return
        answer, result = self.app.dialogs.ask("ai_write", "Text schreiben lassen", "", primary="Schreiben", close="Abbrechen", data={}, width=560)
        instruction = " ".join(str((result or {}).get("instruction") or "").split())
        if answer != "primary" or not instruction or self._document() is not doc:
            return

        def go(context: str) -> None:
            started = self._begin(doc, "Text schreiben lassen")
            if started is None:
                return
            ident, index, model = started
            key = self._entry_key(ident, index)
            self._payloads[key] = {"doc": ident, "kind": "write"}
            cancel = self._cancel

            def work() -> str:
                endpoint = self._endpoint(model, cancel, ident, index)
                text = self._chat(endpoint, writing.write_messages(instruction, context), writing.WRITE_TOKENS, cancel, self._stream(ident, index),
                                  temperature=writing.TEMPERATURE_WRITE)
                return writing.plain(writing.clean_output(text))

            def done(result: str) -> None:
                if not result.strip():
                    self._finish(ident, index, error="Der Assistent hat keinen Text geliefert. Bitte erneut versuchen.")
                    return
                self._payloads.setdefault(key, {})["result"] = result
                self._finish(ident, index, text=result, plain=True, actions=[ACTIONS["insert"]])

            self.app.worker.run(work, done, self._failed(ident, index, cancel, "Der Text konnte nicht geschrieben werden."))

        if self._kind(doc) == "text":
            doc.ai_before_cursor(go)
        else:
            go("")

    # Grammatik -----------------------------------------------------------------------------------------------------
    @Slot()
    def checkGrammar(self) -> None:  # noqa: N802
        """Rechtschreibung und Grammatik prüfen: die Markierung, sonst der ganze Text (bis ``MAX_GRAMMAR_CHARS``)."""
        doc = self._office(("text",))
        if doc is None or self.busy:
            return

        def run(source: str, whole: bool, cut: bool) -> None:
            if not source.strip():
                self._hint("Der Text ist leer – es gibt nichts zu prüfen.", "Grammatik prüfen")
                return
            if self._document() is not doc:
                return
            started = self._begin(doc, "Grammatik im ganzen Text prüfen" if whole else "Markierung auf Grammatik prüfen")
            if started is None:
                return
            ident, index, model = started
            key = self._entry_key(ident, index)
            self._payloads[key] = {"doc": ident, "kind": "grammar"}
            cancel = self._cancel
            worker = self.app.worker

            def work() -> list:
                endpoint = self._endpoint(model, cancel, ident, index)
                pieces = writing.parts(source)
                found: list[writing.Change] = []
                for number, piece in enumerate(pieces, start=1):
                    worker.post(self._note, ident, index, f"Teil {number} von {len(pieces)} wird geprüft …" if len(pieces) > 1 else "Text wird geprüft …")
                    corrected = writing.clean_output(self._chat(endpoint, writing.grammar_messages(piece), writing.grammar_tokens(piece), cancel, None,
                                                                temperature=0.1), piece)
                    found.extend(writing.changes(piece, corrected))
                return found

            def done(found: list) -> None:
                scope = "Geprüft wurde nur der Anfang des Textes (etwa 30.000 Zeichen)." if cut else ""
                if not found:
                    self._finish(ident, index, text="Keine Fehler gefunden.", plain=True, scope=scope)
                    return
                items = [{"index": number, "before": change.before, "after": change.after, "rich": change.rich, "state": ""}
                         for number, change in enumerate(found)]
                count = "1 Korrekturvorschlag" if len(items) == 1 else f"{len(items)} Korrekturvorschläge"
                self._finish(ident, index, text=f"{count} – einzeln oder alle übernehmen.", plain=True, scope=scope, changes=items,
                             actions=[ACTIONS["applyAll"]] if len(items) > 1 else [])

            worker.run(work, done, self._failed(ident, index, cancel, "Der Text konnte nicht geprüft werden."))

        def got(selected: str) -> None:
            if selected.strip():
                run(selected, False, False)
                return
            doc.ai_paragraphs(writing.MAX_GRAMMAR_CHARS, lambda items: run("\n\n".join(items), True, sum(map(len, items)) >= writing.MAX_GRAMMAR_CHARS),
                              lambda _exc: self.app.notify("assistant", "error", "Der Text des Dokuments konnte nicht gelesen werden.", title="Grammatik prüfen"))

        doc.ai_selection(got)

    @Slot(str, int)
    def applyChange(self, key: str, number: int) -> None:  # noqa: N802
        """Eine Korrektur übernehmen: den Satz im Text suchen und ersetzen."""
        self._apply_changes(key, [number])

    def _apply_changes(self, key: str, numbers: list[int]) -> None:
        where = self._locate(key)
        payload = self._payloads.get(key) or {}
        doc = self._document()
        if where is None or doc is None or doc.ident != payload.get("doc") or not hasattr(doc, "ai_replace_once"):
            return
        ident, index = where
        pending = [n for n in numbers if 0 <= n < len(self._conversations[ident][index].get("changes") or [])]

        def step() -> None:
            if not pending:
                changes = self._conversations[ident][index].get("changes") or []
                if all(item.get("state") for item in changes):
                    self._update(ident, index, actions=[])
                return
            number = pending.pop(0)
            changes = self._conversations[ident][index].get("changes") or []
            item = changes[number]
            if item.get("state") == "done":
                step()
                return

            def replaced(ok: bool) -> None:
                current = list(self._conversations.get(ident, [{}] * (index + 1))[index].get("changes") or [])
                if number < len(current):
                    current[number] = {**current[number], "state": "done" if ok else "missing"}
                    self._update(ident, index, changes=current)
                step()

            doc.ai_replace_once(item["before"], item["after"], replaced)

        step()

    # Ergebnis übernehmen -------------------------------------------------------------------------------------------
    @Slot(str, str)
    def act(self, key: str, action: str) -> None:
        """Knopf unter einer Antwort: ersetzen, einfügen, alle Korrekturen übernehmen, Diagramm einfügen, Vorschläge
        für ein Formular prüfen."""
        where = self._locate(key)
        payload = self._payloads.get(key)
        doc = self._document()
        if where is None or payload is None or doc is None or doc.ident != payload.get("doc"):
            return
        ident, index = where
        if action == "applyAll":
            self._apply_changes(key, list(range(len(self._conversations[ident][index].get("changes") or []))))
        elif action == "replace":
            self._replace(doc, ident, index, payload)
        elif action == "insert":
            result = payload.get("result") or ""
            if result:
                doc.ai_insert(result, lambda ok: self._update(ident, index, note="Eingefügt." if ok else "Ließ sich nicht einfügen."))
        elif action == "chart":
            if hasattr(doc, "ai_add_chart"):
                doc.ai_add_chart(int(payload["sheet"]), payload["range"], payload["chart"])
                self._update(ident, index, note="Diagramm eingefügt.", actions=[])
        elif action == "form":
            self._review_form(doc, ident, index, payload)

    def _replace(self, doc, ident: str, index: int, payload: dict) -> None:
        """Ergebnis an die Stelle des Originals setzen – nur, wenn genau dieser Text noch markiert ist."""
        source, result = payload.get("source") or "", payload.get("result") or ""
        if not result:
            return

        def got(selected: str) -> None:
            if " ".join(selected.split()) == " ".join(source.split()) and selected.strip():
                def done(ok: bool) -> None:
                    if ok:
                        payload["done"] = True
                        self._update(ident, index, note="Ersetzt.", actions=[])
                    else:
                        self._update(ident, index, note="Ließ sich nicht ersetzen.")

                doc.ai_insert(result, done)
                return
            self.app.notify("assistant", "info", "Bitte den ursprünglichen Text wieder markieren und dann »Ersetzen« wählen – oder das Ergebnis kopieren.",
                            title="Markierung hat sich geändert", auto_hide=8000)

        doc.ai_selection(got)

    # Übersetzung nebeneinander -------------------------------------------------------------------------------------
    def _translate_side(self, doc, language: str, first: int = 0, last: int = -1) -> None:
        """Original und Übersetzung Absatz für Absatz als neues Text-Dokument öffnen."""
        kind = self._kind(doc)
        label, name = LANGUAGES[language]
        stem = Path(doc.name or "Dokument").stem
        started = self._begin(doc, f"Nebeneinander ins {name} übersetzen", "Dokument wird gelesen …")
        if started is None:
            return
        ident, index, model = started
        cancel = self._cancel
        worker = self.app.worker
        unit = {"praesentation": "Folie", "pdf": "Seite"}.get(kind, "")

        def go(blocks: list[bilingual.Block]) -> None:
            if cancel.is_set():
                self._finish(ident, index, cancelled=True)
                return
            total = 0
            for block in blocks:  # zu lang: kürzen (Hinweis unten)
                block.paragraphs = block.paragraphs[: max(0, MAX_SIDE_PARAGRAPHS - total)]
                total += len(block.paragraphs)
            blocks = [block for block in blocks if block.paragraphs]
            if not blocks:
                self._finish(ident, index, error="Der Text enthält nichts zum Übersetzen." if kind != "pdf" else
                             "Diese Seiten enthalten keinen lesbaren Text (vermutlich ein Scan). Erst »Text erkennen (OCR)« ausführen – danach lässt sich das Dokument übersetzen.")
                return

            def work() -> dict:
                endpoint = self._endpoint(model, cancel, ident, index)
                done_count = 0
                for block in blocks:
                    block.translated = [""] * len(block.paragraphs)
                    for indexes in bilingual.chunks(block.paragraphs):
                        if cancel.is_set():
                            raise Cancelled()
                        worker.post(self._note, ident, index, f"Absatz {done_count + 1} von {total} wird übersetzt …")
                        text = bilingual.numbered(block.paragraphs, indexes)
                        answer = self._chat(endpoint, translate_numbered_messages(text, language), translation_tokens(text), cancel, None)
                        parts = bilingual.split_numbered(answer, len(indexes))
                        for position, paragraph_index in enumerate(indexes):
                            value = parts[position]
                            if value is None:  # Nummer fehlt in der Antwort: diesen Absatz einzeln
                                single = block.paragraphs[paragraph_index]
                                value = writing.clean_output(self._chat(endpoint, translate_messages(single, language), translation_tokens(single), cancel, None), single)
                                value = " ".join(value.split())
                            block.translated[paragraph_index] = value
                        done_count += len(indexes)
                folder = Path(tempfile.mkdtemp(prefix="pdf-tool-ki-"))
                path = bilingual.write_fodt(blocks, folder / "uebersetzung.fodt", title=f"{stem} – {label}", source=doc_name, language=label)
                return {"path": str(path), "folder": str(folder), "paragraphs": total}

            def done(result: dict) -> None:
                target = _safe_name(f"{stem} ({label}, nebeneinander)", ".docx", "Übersetzung")
                folder = result["folder"]

                def opened(_controller) -> None:
                    shutil.rmtree(folder, ignore_errors=True)

                text = f"Übersetzung nebeneinander geöffnet: **{target}** ({result['paragraphs']} Absätze)."
                if total >= MAX_SIDE_PARAGRAPHS:
                    text += f" Übersetzt wurden die ersten {MAX_SIDE_PARAGRAPHS} Absätze."
                self._finish(ident, index, text=text, plain=True)
                if self.reader is not None:
                    self.reader._open_text(result["path"], name=target, untitled=True, then=opened)
                else:
                    shutil.rmtree(folder, ignore_errors=True)

            worker.run(work, done, self._failed(ident, index, cancel, "Die Übersetzung konnte nicht erstellt werden."))

        doc_name = doc.name or "Dokument"
        failed = lambda _exc: self._finish(ident, index, error="Der Text des Dokuments konnte nicht gelesen werden.")  # noqa: E731
        if kind == "text":
            doc.ai_paragraphs(400000, lambda items: go([bilingual.Block("", [" ".join(item.split()) for item in items if item.strip()])]), failed)
            return

        def pages(texts: list[str]) -> None:
            end = len(texts) - 1 if last < 0 else min(last, len(texts) - 1)
            go([bilingual.Block(f"{unit} {number + 1}", bilingual.paragraphs(doctext.clean(texts[number]))) for number in range(max(0, first), end + 1)])

        doc.assistant_texts(pages, failed)

    # Präsentation erstellen ----------------------------------------------------------------------------------------
    @Slot()
    def createPresentation(self) -> None:  # noqa: N802
        """Präsentation aus einem Thema oder aus dem geöffneten Dokument (Dialog), danach als neue Präsentation öffnen."""
        doc = self._document()
        if doc is None or self.busy:
            return
        if self._can_answer() is None:
            self._show_panel(doc)
            return
        kind = self._kind(doc)
        usable = kind in ("pdf", "text", "praesentation")
        data = {"document": doc.name if usable else "", "count": slidegen.DEFAULT_SLIDES, "min": slidegen.MIN_SLIDES, "max": slidegen.MAX_SLIDES,
                "source": "document" if usable and kind != "praesentation" else "topic"}
        answer, result = self.app.dialogs.ask("ai_slides", "Präsentation mit KI erstellen", "", primary="Erstellen", close="Abbrechen", data=data, width=560)
        result = result or {}
        source = str(result.get("source") or "topic")
        topic = " ".join(str(result.get("topic") or "").split())
        count = slidegen.clamp(result.get("count") or slidegen.DEFAULT_SLIDES)
        if answer != "primary" or self._document() is not doc or (source == "topic" and not topic) or (source == "document" and not usable):
            return
        question = f"Präsentation zum Thema »{writing.short(topic, 60)}« erstellen" if source == "topic" else "Präsentation aus diesem Dokument erstellen"
        started = self._begin(doc, question, "Gliederung wird geschrieben …")
        if started is None:
            return
        ident, index, model = started
        cancel = self._cancel
        worker = self.app.worker
        scope = self._scope(doc)
        name = doc.name or ""

        def build(texts: list[str] | None) -> None:
            def work() -> dict:
                endpoint = self._endpoint(model, cancel, ident, index)
                if texts is None:
                    messages = slidegen.topic_messages(topic, count)
                else:
                    items = doctext.passages(texts)
                    if sum(len(item.text) for item in items) < 40:
                        return {"empty": True}
                    plan = plan_summary(items)
                    if len(plan.parts) == 1 and sum(len(item.text) for item in items) <= slidegen.SOURCE_CHARS:
                        material = "\n\n".join(item.text for item in items)
                    else:
                        notes = []
                        for number, part in enumerate(plan.parts, start=1):
                            worker.post(self._note, ident, index, f"Teil {number} von {len(plan.parts)} wird gelesen …")
                            notes.append(self._chat(endpoint, part_messages(part, number, len(plan.parts), scope), PART_TOKENS, cancel, None))
                        material = "\n\n".join(notes)
                    messages = slidegen.document_messages(material, count, name)
                worker.post(self._note, ident, index, "Gliederung wird geschrieben …")
                answer_text = self._chat(endpoint, messages, slidegen.OUTLINE_TOKENS, cancel, None, temperature=slidegen.TEMPERATURE)
                outline = slidegen.parse(answer_text, count)
                if not outline.usable:
                    raise AssistantError("Der Assistent hat keine brauchbare Gliederung geliefert. Bitte erneut versuchen.")
                folder = Path(tempfile.mkdtemp(prefix="pdf-tool-ki-"))
                path = slidegen.write_fodp(outline, folder / "praesentation.fodp")
                return {"path": str(path), "folder": str(folder), "title": outline.title, "slides": len(outline.slides) + 1}

            def done(result: dict) -> None:
                if result.get("empty"):
                    self._finish(ident, index, error="Das Dokument enthält keinen lesbaren Text, aus dem sich Folien machen ließen.")
                    return
                target = _safe_name(result["title"], ".pptx", "Präsentation")
                folder = result["folder"]
                self._finish(ident, index, text=f"Präsentation **{target}** mit {result['slides']} Folien erstellt und geöffnet. Bitte Inhalte prüfen.", plain=True)
                if self.reader is not None:
                    self.reader._open_text(result["path"], name=target, kind="praesentation", untitled=True,
                                           then=lambda _controller: shutil.rmtree(folder, ignore_errors=True))
                else:
                    shutil.rmtree(folder, ignore_errors=True)

            worker.run(work, done, self._failed(ident, index, cancel, "Die Präsentation konnte nicht erstellt werden."))

        if source == "document":
            doc.assistant_texts(build, lambda _exc: self._finish(ident, index, error="Der Text des Dokuments konnte nicht gelesen werden."))
        else:
            build(None)

    # Tabellen ------------------------------------------------------------------------------------------------------
    @Slot()
    def analyzeTable(self) -> None:  # noqa: N802
        self._table("analyze")

    @Slot()
    def suggestChart(self) -> None:  # noqa: N802
        self._table("chart")

    def _table(self, task: str) -> None:
        doc = self._office(("tabelle",))
        if doc is None or self.busy:
            return
        started = self._begin(doc, "Tabelle auswerten" if task == "analyze" else "Diagramm vorschlagen", "Tabelle wird gelesen …")
        if started is None:
            return
        ident, index, model = started
        key = self._entry_key(ident, index)
        cancel = self._cancel
        worker = self.app.worker

        def got(data: dict) -> None:
            rows = [list(map(str, line)) for line in data.get("rows") or []]
            block = list(data.get("range") or [0, 0, 0, 0])
            if sum(1 for line in rows if any(cell.strip() for cell in line)) < 2:
                self._finish(ident, index, error="Hier steht keine Tabelle. Bitte eine Zelle in der Tabelle wählen, die ausgewertet werden soll.")
                return

            def work() -> dict:
                profile = tables.profile(rows, first_row=int(block[0]) + 1)
                endpoint = self._endpoint(model, cancel, ident, index)
                if task == "analyze":
                    text = self._chat(endpoint, tables.analysis_messages(profile, rows, data.get("name", "")), tables.ANALYSIS_TOKENS, cancel,
                                      self._stream(ident, index))
                    facts = [f"- {column.describe()}" for column in profile.columns if column.kind in ("zahl", "datum")]
                    if facts:
                        text = text.strip() + "\n\n**Kennzahlen (von Novadesk berechnet)**\n" + "\n".join(facts)
                    return {"text": text}
                choice = tables.chart_rule(profile)
                if choice is None:
                    return {"error": "Die Tabelle enthält keine Zahlen – dafür passt kein Diagramm."}
                reason = self._chat(endpoint, tables.chart_messages(profile, choice, data.get("name", "")), 200, cancel, None)
                text = f"**Vorschlag: {CHART_LABELS[choice.kind]}**\n{choice.reason}"
                if reason.strip():
                    text += "\n\n" + writing.clean_output(reason)
                return {"text": text, "chart": choice.kind}

            def done(result: dict) -> None:
                if result.get("error"):
                    self._finish(ident, index, error=result["error"])
                    return
                if result.get("chart"):
                    self._payloads[key] = {"doc": ident, "kind": "chart", "chart": result["chart"], "sheet": data.get("sheet", 0), "range": block}
                    self._finish(ident, index, text=result["text"], plain=True, actions=[ACTIONS["chart"]])
                    return
                self._finish(ident, index, text=result["text"].strip(), plain=True)

            worker.run(work, done, self._failed(ident, index, cancel, "Die Tabelle konnte nicht ausgewertet werden."))

        doc.ai_table(got, lambda _exc: self._finish(ident, index, error="Die Tabelle konnte nicht gelesen werden."))

    # Formular ausfüllen --------------------------------------------------------------------------------------------
    @Slot()
    def fillForm(self) -> None:  # noqa: N802
        """PDF-Formular mit KI ausfüllen: Angaben eingeben, Vorschläge prüfen, eintragen."""
        doc = self._office(("pdf",))
        if doc is None or self.busy:
            return
        if self._can_answer() is None:
            self._show_panel(doc)
            return
        if not doc.edit_allowed("fill_forms"):
            return

        def got(fields: list) -> None:
            if self._document() is not doc:
                return
            if not fields:
                self.app.notify("assistant", "info", "Dieses PDF hat keine Formularfelder, die sich ausfüllen lassen.", title="Formular mit KI ausfüllen", auto_hide=8000)
                return
            items = [formfill.Field(entry["key"], entry["name"], entry["kind"], entry.get("label", ""), tuple(tuple(option) for option in entry.get("options") or ()),
                                    int(entry.get("maxLength") or 0), bool(entry.get("multiline")), entry.get("value", "")) for entry in fields]
            titles = [item.title for item in items]
            answer, result = self.app.dialogs.ask("ai_form", "Formular mit KI ausfüllen", "", primary="Vorschläge erstellen", close="Abbrechen",
                                                  data={"count": len(items), "fields": titles[:12], "more": max(0, len(titles) - 12)}, width=600)
            data = str((result or {}).get("data") or "").strip()
            if answer != "primary" or not data or self._document() is not doc:
                return
            started = self._begin(doc, "Formular mit KI ausfüllen", "Angaben werden zugeordnet …")
            if started is None:
                return
            ident, index, model = started
            key = self._entry_key(ident, index)
            cancel = self._cancel

            def work() -> list:
                endpoint = self._endpoint(model, cancel, ident, index)
                text = self._chat(endpoint, formfill.messages(items, data), formfill.FILL_TOKENS, cancel, None, temperature=0.1,
                                  json_schema=formfill.schema(items))
                return formfill.proposals(items, formfill.parse_json(text))

            def done(proposals: list) -> None:
                if not proposals:
                    self._finish(ident, index, text="In den Angaben steht nichts, das zu den Feldern dieses Formulars passt.", plain=True)
                    return
                self._payloads[key] = {"doc": ident, "kind": "form", "proposals": proposals}
                count = "1 Vorschlag" if len(proposals) == 1 else f"{len(proposals)} Vorschläge"
                self._finish(ident, index, text=f"{count} für das Formular – bitte prüfen und eintragen.", plain=True, actions=[ACTIONS["form"]])
                QTimer.singleShot(0, lambda: self.act(key, "form"))

            self.app.worker.run(work, done, self._failed(ident, index, cancel, "Das Formular konnte nicht ausgefüllt werden."))

        doc.run(lambda session: session.ai_fields(), got, refresh=False,
                failed=lambda _exc: self.app.notify("assistant", "error", "Die Formularfelder konnten nicht gelesen werden.", title="Formular mit KI ausfüllen"))

    def _review_form(self, doc, ident: str, index: int, payload: dict) -> None:
        proposals: list[formfill.Proposal] = payload.get("proposals") or []
        if not proposals or payload.get("done"):
            return
        items = [{"key": p.key, "title": p.title, "value": p.display, "current": ("Ja" if p.current is True else "Nein" if p.current is False else str(p.current or "")),
                  "checked": True} for p in proposals]
        answer, result = self.app.dialogs.ask("ai_form_review", "Vorschläge prüfen", "", primary="Eintragen", close="Abbrechen", data={"items": items}, width=640)
        chosen = set((result or {}).get("chosen") or [])
        if answer != "primary" or not chosen or self._document() is not doc:
            return
        values = {p.key: p.value for p in proposals if p.key in chosen}

        def done(failed: list) -> None:
            filled = len(values) - len(failed)
            payload["done"] = True
            note = f"{filled} {'Feld' if filled == 1 else 'Felder'} ausgefüllt" + (f", {len(failed)} ließen sich nicht setzen." if failed else ".")
            self._update(ident, index, note=note, actions=[])
            doc.loadFields()
            self.app.set_status(note, "success" if not failed else "warning")

        doc.run(lambda session: session.set_fields(values), done, busy="Formular wird ausgefüllt …",
                failed=lambda _exc: self.app.notify("assistant", "error", "Das Formular konnte nicht ausgefüllt werden.", title="Formular mit KI ausfüllen"))

    @Slot(result=str)
    def pickDataFile(self) -> str:  # noqa: N802
        """Angaben für ein Formular aus einer Datei (Text, PDF, Word, OpenDocument) – höchstens ``MAX_DATA_CHARS`` Zeichen."""
        from . import files

        start = self.app.initial_dir("assistant", self.reader.source_dir if self.reader is not None else "")
        paths = files.open_files("Angaben aus Datei laden", start, DATA_FILTER)
        if not paths:
            return ""
        try:
            return read_data_file(Path(paths[0]))[: formfill.MAX_DATA_CHARS]
        except (OSError, ValueError) as exc:
            self.app.notify("assistant", "warning", f"Die Datei ließ sich nicht lesen ({type(exc).__name__}).", title="Angaben aus Datei laden")
            return ""


def read_data_file(path: Path) -> str:
    """Text einer Datei mit Angaben: reiner Text, PDF (Textebene), Word (.docx) oder OpenDocument-Text (.odt)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pypdfium2 as pdfium

        from pdfium_lock import PDFIUM_LOCK

        with PDFIUM_LOCK:
            document = pdfium.PdfDocument(str(path))
            try:
                return "\n\n".join(document[i].get_textpage().get_text_range() for i in range(min(len(document), 10)))
            finally:
                document.close()
    if suffix in (".docx", ".odt"):
        import html
        import zipfile

        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml" if suffix == ".docx" else "content.xml").decode("utf-8", "replace")
        xml = re.sub(r"</(?:w:p|text:p|text:h)>", "\n", xml)
        xml = re.sub(r"<(?:w:tab|text:tab)\s*/>", "\t", xml)
        return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()
    if suffix == ".rtf":
        raw = path.read_bytes().decode("cp1252", "replace")
        raw = re.sub(r"\\par[d]?\b", "\n", raw)
        raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), raw)
        return re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]", "", raw).strip()
    data = path.read_bytes()[:400_000]
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")
