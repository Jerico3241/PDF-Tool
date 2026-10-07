"""Qt-Oberfläche: KI-Assistent (optional, ab 3.2) – Einstellungen, Einrichten mit Modellwahl, Download (Fortschritt,
Anhalten, Fortsetzen, Prüfsumme, fremde Weiterleitung), Entfernen und die Seitenleiste »KI-Assistent« im Reader:
Fragen mit Seitenverweisen, Zusammenfassen langer Dokumente in Teilen, Abbrechen, Gespräche je Tab, Ausschalten.

Statt Hugging Face liefert ein lokaler Testserver kleine »Modelle« (Weiterleitung auf einen Speicher, ``Range``
zum Fortsetzen); statt llama-server läuft die Attrappe ``fixtures/fake_llama_server.py``. Kein Internet, kein echtes
Modell. Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from conftest import pump, wait_until
from test_qt_reader import open_pdf, reader, window_point

from assistant import catalog, prompts, runtime, store
from qtapp import assistant as assistant_module
from qtapp import dialogs
from updater.policy import UrlPolicy

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_llama_server.py"
LEFT = Qt.MouseButton.LeftButton
NO_MOD = Qt.KeyboardModifier.NoModifier
QUESTION = "Wie lang ist die Kuendigungsfrist?"  # getippt (QTest tippt nur ASCII) – die Suche schreibt Umlaute ebenso aus
CONTRACT = (
    ("Versicherungsschein Gewerbe Kompakt", "Versicherungsnehmer: Muster GmbH, Musterstadt"),
    ("Beitrag", "Der Jahresbeitrag beträgt 1.284,60 Euro und wird vierteljährlich abgebucht."),
    ("Kündigung", "Der Vertrag kann mit einer Kündigungsfrist von drei Monaten zum Ablauf gekündigt werden."),
)


# --- Testserver für Modelle (wie Hugging Face) ---------------------------------------------------------------------
class ModelServer:
    """``/modelle/<Datei>`` leitet wie Hugging Face auf ``/speicher/<Datei>`` weiter; der Speicher beantwortet
    ``Range: bytes=N-`` mit 206 (abschaltbar). Langsam einstellbar; jede Anfrage wird mit ihrem ``Range`` notiert."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.ranges = True
        self.delay = 0.0  # Pause je Block
        self.chunk = 16 * 1024
        self.redirect = ""  # anderes Ziel der Weiterleitung
        self.requests: list[tuple[str, str]] = []
        self._stop = threading.Event()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                path = unquote(urlsplit(self.path).path)
                server.requests.append((path, self.headers.get("Range") or ""))
                name = path.rsplit("/", 1)[-1]
                if path.startswith("/modelle/"):
                    self.send_response(302)
                    self.send_header("Location", server.redirect or f"{server.base}/speicher/{name}?sig=test")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = server.files.get(name)
                if data is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start = 0
                wanted = self.headers.get("Range") or ""
                if server.ranges and wanted.startswith("bytes=") and wanted.endswith("-"):
                    start = int(wanted[6:-1])
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    self.send_response(200)
                body = data[start:]
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                for offset in range(0, len(body), server.chunk):
                    if server._stop.is_set():
                        return
                    try:
                        self.wfile.write(body[offset : offset + server.chunk])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    if server.delay:
                        time.sleep(server.delay)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._stop.set()
        self._server.shutdown()
        self._server.server_close()


@dataclasses.dataclass(frozen=True)
class LocalModel(catalog.Model):
    base: str = ""

    @property
    def url(self) -> str:
        return f"{self.base}/modelle/{self.file}"


def content(size: int, seed: str) -> bytes:
    block = hashlib.sha256(seed.encode()).digest() * 2048
    return (b"GGUF" + block * (size // len(block) + 1))[:size]


@pytest.fixture
def ki(monkeypatch, tmp_path: Path):
    """Testserver mit zwei kleinen Modellen statt Hugging Face, Attrappe statt llama-server, 8 GB Arbeitsspeicher
    (Empfehlung: »Kompakt«). Muss vor dem Start der App eingerichtet sein."""
    server = ModelServer()
    data = {"standard": content(600_000, "genau"), "kompakt": content(300_000, "kompakt")}
    models = {}
    for original in (catalog.STANDARD, catalog.COMPACT):
        payload = data[original.key]
        fields = {field.name: getattr(original, field.name) for field in dataclasses.fields(catalog.Model)}
        fields.update(file=f"{original.key}-test.gguf", size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        models[original.key] = LocalModel(**fields, base=server.base)
        server.files[models[original.key].file] = payload
    standard, compact = models["standard"], models["kompakt"]
    monkeypatch.setattr(catalog, "STANDARD", standard)
    monkeypatch.setattr(catalog, "COMPACT", compact)
    monkeypatch.setattr(catalog, "MODELS", (standard, compact))
    monkeypatch.setattr(catalog, "BY_KEY", {"standard": standard, "kompakt": compact})
    monkeypatch.setattr(store, "MODELS", (standard, compact))
    monkeypatch.setattr(store, "SPACE_RESERVE", 0)
    monkeypatch.setattr(runtime, "total_memory", lambda: 8 * catalog.GB)
    monkeypatch.setattr(assistant_module.AssistantController, "_policy", lambda self: UrlPolicy.loopback(server.port))
    monkeypatch.setenv(runtime.SERVER_VARIABLE, str(FAKE_SERVER))
    monkeypatch.setenv("FAKE_LLAMA_LOAD", "0.2")
    monkeypatch.setenv("FAKE_LLAMA_LOG", str(tmp_path / "anfragen.jsonl"))
    monkeypatch.delenv("FAKE_LLAMA_MODE", raising=False)
    yield SimpleNamespace(server=server, standard=standard, compact=compact, data=data, log=tmp_path / "anfragen.jsonl")
    server.stop()


def install(model) -> None:
    """Modell wie nach einem geprüften Download ablegen."""
    store.models_dir().mkdir(parents=True, exist_ok=True)
    store.partial(model).write_bytes(content(model.size, "genau" if model.key == "standard" else "kompakt"))
    store.mark_verified(model)


@pytest.fixture
def app_ki(request, ki):
    """App (Standardprofil) mit den Testmodellen – gestartet erst nach ``ki``."""
    harness = request.getfixturevalue("ui_app")
    harness.app.dialogs.shutdown()  # »Neu in Version« schließen
    return harness


def a(h):
    return h.runtime.assistant


def requests(ki) -> list[dict]:
    return [json.loads(line) for line in ki.log.read_text(encoding="utf-8").splitlines()] if ki.log.exists() else []


def contract_pdf(path: Path, pages=CONTRACT) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 760
        for line in lines:
            c.setFont("Helvetica", 12)
            c.drawString(72, y, line)
            y -= 24
        c.showPage()
    c.save()
    return path


def scan_pdf(path: Path) -> Path:
    """Eine Seite ohne Text (wie ein Scan ohne Texterkennung)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.rect(72, 400, 300, 200, fill=1)
    c.showPage()
    c.save()
    return path


def click_item(h, item) -> None:
    assert item is not None and item.isVisible(), "Element nicht sichtbar"
    QTest.mouseClick(h.window, LEFT, NO_MOD, window_point(item, item.width() / 2, item.height() / 2))
    pump(0.15)


def switch(h, toggle) -> None:
    """Umschalter oder Schaltfläche mit der Tastatur betätigen (Fokus, Leertaste) – auch außerhalb des sichtbaren
    Bereichs der Seite."""
    assert toggle is not None and toggle.isVisible(), "Element nicht sichtbar"
    toggle.forceActiveFocus()
    QTest.keyClick(h.window, Qt.Key.Key_Space)
    pump(0.2)


def shown(h, name: str):
    """Das sichtbare Element mit diesem Namen – jede Zeile des Gesprächs hat alle Teile, nur die passenden sichtbar."""
    found = [item for item in h.items(name) if item.isVisible()]
    assert found, f"{name} ist nicht sichtbar"
    return found[0]


def answers(h) -> list[dict]:
    return a(h).conversation.items()


def wait_answer(h, timeout: float = 30) -> dict:
    assert wait_until(lambda: not a(h).busy, timeout), "Antwort wurde nicht fertig"
    pump(0.2)
    return answers(h)[-1]


def show_panel(h) -> None:
    """Seitenleiste »KI-Assistent« über den Streifen am rechten Rand öffnen."""
    click_item(h, h.item("readerRailAssistant"))
    assert wait_until(lambda: h.item("readerAssistantPanel") is not None and h.item("readerAssistantPanel").isVisible(), 5)
    pump(0.3)


def ask(h, question: str) -> None:
    """Frage eintippen und mit der Eingabetaste senden."""
    click_item(h, h.item("readerAssistantInput"))
    for char in question:
        QTest.keyClick(h.window, char)
    pump(0.1)
    QTest.keyClick(h.window, Qt.Key.Key_Return)
    pump(0.1)


# --- Aus, bis eingeschaltet ---------------------------------------------------------------------------------------
def test_off_by_default_nothing_loaded_and_nothing_shown(ui_app, tmp_path: Path) -> None:
    """Standard: aus. Ohne gebündelten KI-Prozess lässt er sich nicht einschalten; im Reader gibt es weder Streifen-
    noch Kopf-Schalter, und auf dem PC wird nichts angelegt."""
    h = ui_app
    h.app.dialogs.shutdown()
    assistant = a(h)
    assert not assistant.enabled and assistant.state == "off" and not assistant.available
    assert assistant.config() == {"ki_assistent": False, "ki_modell": None}
    h.navigate("settings")
    toggle = h.item("assistantToggle")
    assert toggle is not None and not toggle.property("checked") and not toggle.property("enabled")
    assert h.item("assistantStatus").property("text") == "In dieser Installation nicht enthalten."
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    assert h.item("readerRailAssistant") is None
    reader(h).showRightPanel("comments")
    pump(0.3)
    assert h.item("readerTabComments") is not None and h.item("readerTabAssistant") is None
    assert not store.models_dir().exists() and not any(store.root().iterdir())  # nichts angelegt


# --- Einrichten, Download, Prüfsumme ------------------------------------------------------------------------------
def test_switching_on_offers_the_models_and_downloads_the_chosen_one(app_ki, ki, monkeypatch) -> None:
    """Einschalten öffnet »KI-Assistent einrichten« mit beiden Modellen (Empfehlung nach Arbeitsspeicher); erst
    »Herunterladen« lädt – über die Weiterleitung wie bei Hugging Face –, prüft die SHA-256 und meldet »bereit«."""
    h = app_ki
    assistant = a(h)
    assert assistant.available and assistant.state == "off"
    h.navigate("settings")
    assert "nichts wird geladen" in h.item("assistantStatus").property("text")
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    seen: dict = {}

    def in_dialog() -> None:
        seen["standard"] = h.item("assistantModel_standard") is not None
        seen["kompakt"] = h.item("assistantModel_kompakt") is not None
        content_item = h.item("assistantSetupContent")
        seen["choice"] = content_item.property("choice") if content_item is not None else None
        seen["system"] = h.item("assistantSetupSystem").property("text")
        click_item(h, h.item("dialogPrimaryButton"))

    QTimer.singleShot(600, in_dialog)
    switch(h, h.item("assistantToggle"))
    assert seen == {"standard": True, "kompakt": True, "choice": "kompakt", "system": seen["system"]}
    assert "Arbeitsspeicher dieses PCs: 8,0 GB" in seen["system"]
    assert assistant.enabled and assistant.state in ("download", "verify", "ready")
    assert wait_until(lambda: assistant.state == "ready", 20), assistant.statusText
    pump(0.2)
    assert store.installed(ki.compact) and not store.installed(ki.standard)
    assert store.path(ki.compact).read_bytes() == ki.data["kompakt"] and not store.partial(ki.compact).exists()
    assert [path for path, _range in ki.server.requests] == ["/modelle/kompakt-test.gguf", "/speicher/kompakt-test.gguf"]
    assert assistant.modelKey == "kompakt" and "Bereit" in h.item("assistantStatus").property("text")
    assert h.item("assistantChange").isVisible() and h.item("assistantRemove").isVisible() and not h.item("assistantSetup").isVisible()
    assert assistant.config() == {"ki_assistent": True, "ki_modell": "kompakt"}


def test_a_paused_download_resumes_where_it_stopped(app_ki, ki) -> None:
    """»Anhalten« behält die geladenen Teile; »Download fortsetzen« fragt mit ``Range`` nur den Rest an."""
    h = app_ki
    assistant = a(h)
    ki.server.delay = 0.05
    h.navigate("settings")
    assistant.download("standard")
    assert assistant.state == "download"
    assert wait_until(lambda: store.partial(ki.standard).exists() and store.partial(ki.standard).stat().st_size >= 64 * 1024, 20)
    pump(0.1)
    assert h.item("assistantProgress").isVisible() and h.item("assistantCancel").isVisible()
    switch(h, h.item("assistantCancel"))
    assert assistant.state == "setup" and assistant.partial == "standard"
    kept = store.partial_size(ki.standard)
    assert 0 < kept < ki.standard.size
    assert "angehalten" in assistant.statusText
    resume = h.item("assistantResume")
    assert resume.isVisible() and not h.item("assistantSetup").isVisible()
    ki.server.delay = 0.0
    switch(h, resume)
    assert wait_until(lambda: assistant.state == "ready", 20), assistant.statusText
    assert store.path(ki.standard).read_bytes() == ki.data["standard"]
    ranges = [wanted for path, wanted in ki.server.requests if path.startswith("/speicher/")]
    assert ranges[0] == "" and ranges[-1] == f"bytes={kept}-"


def test_a_server_without_ranges_restarts_and_a_wrong_checksum_is_discarded(app_ki, ki, monkeypatch) -> None:
    """Liefert der Server die Datei beim Fortsetzen von vorn, beginnt der Download neu (nie doppelt angehängt). Stimmt
    die Prüfsumme nicht, wird die Datei gelöscht – nie verwendet."""
    h = app_ki
    assistant = a(h)
    store.models_dir().mkdir(parents=True)
    store.partial(ki.compact).write_bytes(ki.data["kompakt"][:1000])
    ki.server.ranges = False
    assistant.setEnabled(True)
    assistant.download("kompakt")
    assert wait_until(lambda: assistant.state == "ready", 20), assistant.statusText
    assert store.path(ki.compact).read_bytes() == ki.data["kompakt"]
    store.remove(ki.compact)
    # falsche Prüfsumme
    wrong = dataclasses.replace(ki.compact, sha256="0" * 64)
    monkeypatch.setattr(catalog, "BY_KEY", {"standard": ki.standard, "kompakt": wrong})
    monkeypatch.setattr(catalog, "MODELS", (ki.standard, wrong))
    monkeypatch.setattr(store, "MODELS", (ki.standard, wrong))
    assistant.download("kompakt")
    assert wait_until(lambda: assistant.state == "setup" and "beschädigt" in assistant.statusText, 20), assistant.statusText
    assert not store.path(wrong).exists() and not store.partial(wrong).exists() and not store.installed(wrong)
    notice = h.app.notices.area("assistant")
    assert notice.shown and notice.severity == "error" and notice.title == "Prüfsumme stimmt nicht"


def test_redirects_to_other_addresses_are_refused(app_ki, ki) -> None:
    """Nur Hugging Face und sein Speicher: Eine Weiterleitung anderswohin bricht ab, nichts bleibt liegen."""
    h = app_ki
    assistant = a(h)
    ki.server.redirect = "http://127.0.0.1:1/speicher/kompakt-test.gguf"
    assistant.setEnabled(True)
    assistant.download("kompakt")
    assert wait_until(lambda: assistant.state == "setup" and assistant.statusText != "", 20)
    pump(0.2)
    assert "unerwartete Adresse" in assistant.statusText
    assert not store.partial(ki.compact).exists() and not store.installed(ki.compact)


def test_the_app_downloads_only_from_hugging_face_over_https() -> None:
    """Regel der App (ohne Testserver): HTTPS zu huggingface.co und seinem Speicher (*.hf.co, *.huggingface.co)."""
    policy = assistant_module.AssistantController._policy(None)
    assert policy.allows(catalog.STANDARD.url) and policy.allows(catalog.COMPACT.url)
    assert policy.allows("https://cas-bridge.xethub.hf.co/xet-bridge-us/abc?X-Amz-Signature=1")
    assert policy.allows_redirect(catalog.COMPACT.url, "https://cdn-lfs.huggingface.co/repos/x/y")
    for refused in ("http://huggingface.co/x", "https://huggingface.co.example.com/x", "https://evilhf.co/x", "https://example.com/x", "https://user:pw@huggingface.co/x"):
        assert not policy.allows(refused), refused


def test_too_little_space_is_reported_before_downloading(app_ki, ki, monkeypatch) -> None:
    h = app_ki
    assistant = a(h)
    monkeypatch.setattr(store, "free_space", lambda: 1000)
    assistant.setEnabled(True)
    assistant.download("standard")
    pump(0.2)
    assert assistant.state == "setup" and not ki.server.requests
    notice = h.app.notices.area("assistant")
    assert notice.shown and notice.title == "Nicht genug Speicherplatz"


def test_removing_the_model_frees_the_space(app_ki, ki, tmp_path: Path) -> None:
    """»Modell entfernen …« löscht nach Rückfrage Modell und Reste – erst nachdem der KI-Prozess beendet ist (Windows
    sperrt eine geladene Datei); der Assistent ist danach nicht mehr bereit."""
    h = app_ki
    assistant = a(h)
    install(ki.compact)
    store.partial(ki.standard).write_bytes(b"x" * 1000)
    assistant.setEnabled(True)
    assistant.download("kompakt")  # schon eingerichtet: nur auswählen
    assert assistant.state == "ready" and assistant.modelKey == "kompakt"
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    assistant.ask(QUESTION)
    wait_answer(h)
    process = assistant._server._process
    assert process.poll() is None
    h.navigate("settings")
    switch(h, h.item("assistantRemove"))
    assert wait_until(lambda: not store.root().exists(), 15)
    pump(0.2)
    assert process.poll() is not None and assistant._server is None
    assert assistant.state == "setup" and assistant.modelKey == "" and assistant.partial == ""
    assert h.item("assistantSetup").isVisible() and not h.item("assistantRemove").isVisible()
    assert "Sprachmodell entfernt" in h.app.statusText


# --- Fragen im Reader -----------------------------------------------------------------------------------------------
def test_questions_get_answers_with_page_links_from_the_matching_pages(app_ki, ki, tmp_path: Path) -> None:
    """Frage eintippen, Eingabetaste: Der Assistent schickt nur die passenden Abschnitte (hier Seite 3), die Antwort
    erscheint Stück für Stück, nennt die Seite als Verweis – ein Klick darauf springt dorthin. Kopieren übernimmt den
    Text der Antwort."""
    h = app_ki
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    show_panel(h)
    assert h.item("readerAssistantIntro").isVisible()
    ask(h, QUESTION)
    entry = wait_answer(h)
    question, answer = answers(h)
    assert question["kind"] == "question" and question["text"] == QUESTION
    assert answer["kind"] == "answer" and not answer["pending"] and answer["pages"] == [3]
    assert answer["text"] == "Laut Dokument beträgt die Kündigungsfrist drei Monate (S. 3). Weitere Angaben stehen auf Seite 3."
    assert answer["rich"].count('<a href="page:3">3</a>') == 2
    assert entry == answer
    sent = requests(ki)
    assert len(sent) == 1
    user = sent[0]["messages"][-1]["content"]
    assert "[Seite 3]" in user and "[Seite 1]" not in user and "[Seite 2]" not in user and user.endswith("Frage: " + QUESTION)
    assert h.item("readerAssistantInput").property("text") == ""
    # Verweis auf die Seite
    doc = reader(h).current
    doc.goTo(0)
    pump(0.3)
    click_item(h, shown(h, "readerAssistantPage"))
    assert wait_until(lambda: doc.currentPage == 2, 5)
    click_item(h, shown(h, "readerAssistantCopy"))
    assert QGuiApplication.clipboard().text() == answer["text"]


def test_long_documents_are_summarized_in_parts(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Zu lang für einen Durchgang: Teile nacheinander, danach eine Zusammenfassung daraus; reicht sie nicht über das
    ganze Dokument, steht dabei, bis zu welcher Seite."""
    h = app_ki
    monkeypatch.setattr(prompts, "SUMMARY_PART_CHARS", 60)
    monkeypatch.setattr(prompts, "SUMMARY_MAX_PARTS", 2)
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    show_panel(h)
    click_item(h, h.item("readerAssistantSummarize"))
    answer = wait_answer(h)
    assert answers(h)[0]["text"] == "Dokument zusammenfassen"
    assert answer["kind"] == "answer" and answer["text"].startswith("- Gesamtüberblick")
    assert "<ul><li>" in answer["rich"] and "<b>Wichtigste Frist:</b>" in answer["rich"]
    assert answer["note"] == "Zusammengefasst wurden die Seiten 1 bis 2 von 3 – längere Dokumente liest der Assistent nur bis dahin."
    sent = requests(ki)
    assert [request["messages"][-1]["content"].split("\n")[0] for request in sent] == ["Teil 1 von 2 des Dokuments:", "Teil 2 von 2 des Dokuments:", "Stichpunkte aus den Teilen eines Dokuments (mit Seitenangaben):"]
    assert [request["max_tokens"] for request in sent] == [prompts.PART_TOKENS, prompts.PART_TOKENS, prompts.ANSWER_TOKENS]


def test_an_answer_can_be_stopped(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    h = app_ki
    monkeypatch.setenv("FAKE_LLAMA_MODE", "slow")
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    show_panel(h)
    ask(h, QUESTION)
    assert wait_until(lambda: len(answers(h)) == 2 and answers(h)[1]["text"].startswith("Wort"), 20)
    pump(0.2)
    assert h.item("readerAssistantStop").isVisible() and not h.item("readerAssistantSend").isVisible()
    click_item(h, h.item("readerAssistantStop"))
    answer = wait_answer(h, 5)
    assert not answer["pending"] and answer["note"] == "Abgebrochen." and answer["text"].startswith("Wort")
    assert len(answer["text"].split()) < 400
    assert h.item("readerAssistantSend").isVisible()


def test_scans_without_text_explain_what_to_do(app_ki, ki, tmp_path: Path) -> None:
    h = app_ki
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, scan_pdf(tmp_path / "scan.pdf"))
    show_panel(h)
    ask(h, "Worum geht es?")
    answer = wait_answer(h)
    assert answer["kind"] == "error" and "keinen lesbaren Text" in answer["text"] and "Text erkennen (OCR)" in answer["text"]
    assert not requests(ki) and a(h)._server is None  # ohne Text startet der KI-Prozess gar nicht
    assert shown(h, "readerAssistantError").height() > 20


def test_each_tab_has_its_own_conversation_and_switching_off_closes_the_panel(app_ki, ki, tmp_path: Path) -> None:
    """Gespräche gehören zum Tab und verfallen mit ihm. Ausschalten schließt die Seitenleiste in allen Tabs und beendet
    den KI-Prozess."""
    h = app_ki
    install(ki.compact)
    assistant = a(h)
    assistant.setEnabled(True)
    h.navigate("reader", 0.3)
    r = reader(h)
    open_pdf(h, contract_pdf(tmp_path / "a.pdf"))
    first = r.current.ident
    show_panel(h)
    ask(h, QUESTION)
    wait_answer(h)
    open_pdf(h, contract_pdf(tmp_path / "b.pdf"))
    second = r.current.ident
    assert r.rightPanel == "assistant"  # neuer Tab: Seitenleisten wie im bisherigen
    assert assistant.conversation.count == 0
    r.activate(first)
    pump(0.2)
    assert assistant.conversation.count == 2
    process = assistant._server._process
    assert process.poll() is None
    # Ausschalten (Einstellungen): Seitenleiste überall zu, KI-Prozess beendet
    h.navigate("settings")
    switch(h, h.item("assistantToggle"))
    assert not assistant.enabled and r.rightPanel == ""
    assert r._docs[second].panels["right"] == ""
    assert wait_until(lambda: process.poll() is not None, 10)
    h.navigate("reader", 0.3)
    assert h.item("readerRailAssistant") is None
    # Tab schließen: sein Gespräch verfällt
    r.closeTab(first)
    pump(0.3)
    assert first not in assistant._conversations


def test_the_ai_process_ends_after_a_while_without_questions_and_with_the_app(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    h = app_ki
    monkeypatch.setattr(assistant_module, "IDLE_MS", 300)
    install(ki.compact)
    assistant = a(h)
    assistant.setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    show_panel(h)
    ask(h, QUESTION)
    wait_answer(h)
    process = assistant._server._process
    assert wait_until(lambda: process.poll() is not None and assistant._server is None, 10)
    ask(h, "Wie hoch ist der Jahresbeitrag?")  # startet bei Bedarf neu
    assert wait_answer(h)["pages"] == [2]
    process = assistant._server._process
    assert process.poll() is None
    h.app.shutdown()
    assert process.poll() is not None


def test_questions_and_document_text_never_reach_the_logs(app_ki, ki, tmp_path: Path) -> None:
    h = app_ki
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    show_panel(h)
    ask(h, "Geheimfrage Zebra 4711?")
    wait_answer(h)
    import appstate

    logs = list(Path(appstate.DATA_DIR).rglob("*.log"))
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in logs)
    assert "Zebra" not in text and "Kündigungsfrist" not in text and "Jahresbeitrag" not in text
