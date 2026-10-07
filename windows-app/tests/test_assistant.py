"""KI-Assistent ohne Oberfläche: Modellkatalog, Ablage der Modelle, Abschnitte und Suche im Dokumenttext,
Seitenangaben in Antworten, Anweisungen an das Modell, der lokale KI-Prozess und die Anfragen an ihn – gestreamt,
abbrechbar, mit verständlichen Fehlermeldungen.

Statt llama-server läuft die Attrappe ``fixtures/fake_llama_server.py`` (gleiche Aufrufparameter, gleiche
Schnittstelle, feste Antworten). Es wird nie ein Modell geladen und nie ins Internet gegangen.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from assistant import catalog, prompts, runtime, store
from assistant import text as doctext
from assistant.client import AssistantError, Cancelled, Chat, Endpoint, health

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_llama_server.py"


def tiny_model(content: bytes = b"GGUF-Testmodell" * 100) -> catalog.Model:
    return dataclasses.replace(catalog.COMPACT, key="test", file="test-modell.gguf", size=len(content), sha256=hashlib.sha256(content).hexdigest())


# --- Katalog -----------------------------------------------------------------------------------------------------
def test_models_have_a_fixed_source_revision_and_checksum() -> None:
    """Jedes Modell: HTTPS-Adresse bei Hugging Face mit festem Commit, SHA-256, Größe und Apache-Lizenz – ein Modell
    wird nur verwendet, wenn die Datei genau dieser Prüfsumme entspricht."""
    assert len({model.key for model in catalog.MODELS}) == len(catalog.MODELS) == 2
    for model in catalog.MODELS:
        assert model.url == f"https://huggingface.co/{model.repo}/resolve/{model.revision}/{model.file}"
        assert len(model.revision) == 40 and all(char in "0123456789abcdef" for char in model.revision)
        assert len(model.sha256) == 64 and model.sha256 == model.sha256.lower()
        assert model.file.endswith(".gguf") and model.size > 10**9
        assert model.license == "Apache-2.0"
        assert catalog.get(model.key) is model
    assert catalog.get("") is None and catalog.get("unbekannt") is None
    # Empfehlung nach Arbeitsspeicher: »Genau« ab 12 GB, sonst (auch unbekannt) »Kompakt«
    assert catalog.recommended(16 * catalog.GB) is catalog.STANDARD
    assert catalog.recommended(12 * catalog.GB) is catalog.STANDARD
    assert catalog.recommended(8 * catalog.GB) is catalog.COMPACT
    assert catalog.recommended(0) is catalog.COMPACT
    assert catalog.COMPACT.size < catalog.STANDARD.size and catalog.COMPACT.memory < catalog.STANDARD.memory


# --- Ablage ------------------------------------------------------------------------------------------------------
def test_models_live_in_their_own_folder_outside_the_data_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PDFTOOL_AI_DIR")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert store.root() == tmp_path / "local" / "PDF-Tool-KI"
    assert store.models_dir() == tmp_path / "local" / "PDF-Tool-KI" / "modelle"
    monkeypatch.setenv("PDFTOOL_AI_DIR", str(tmp_path / "test"))
    assert store.root() == tmp_path / "test"


def test_a_model_counts_as_installed_only_with_size_and_verified_checksum() -> None:
    content = b"GGUF-Testmodell" * 100
    model = tiny_model(content)
    assert not store.installed(model) and store.partial_size(model) == 0
    store.models_dir().mkdir(parents=True)
    # unterbrochener Download: wird fortgesetzt, zählt noch nicht
    store.partial(model).write_bytes(content[:500])
    assert store.partial_size(model) == 500 and not store.installed(model)
    assert store.space_needed(model) == model.size - 500 + store.SPACE_RESERVE
    store.partial(model).write_bytes(content)
    assert store.partial_size(model) == 0  # vollständig: nichts mehr fortzusetzen
    target = store.mark_verified(model)
    assert target == store.path(model) and target.read_bytes() == content and not store.partial(model).exists()
    assert store.installed(model) and store.used_bytes() == 0  # ``used_bytes`` zählt nur Modelle des Katalogs
    # Vermerk fehlt oder passt nicht, Datei hat eine andere Größe: nicht eingerichtet
    marker = store.models_dir() / (model.file + store.VERIFIED_SUFFIX)
    marker.write_text("0" * 64, encoding="ascii")
    assert not store.installed(model)
    marker.write_text(model.sha256 + "\n", encoding="ascii")
    assert store.installed(model)
    target.write_bytes(content + b"x")
    assert not store.installed(model)
    # Entfernen: Datei, Vermerk und leere Ordner
    freed = store.remove(model)
    assert freed == len(content) + 1 + len(model.sha256) + 1
    assert not store.models_dir().exists() and not store.root().exists()


# --- Text, Suche, Seitenangaben -----------------------------------------------------------------------------------
def test_page_text_is_cleaned_and_split_into_passages_per_page() -> None:
    assert doctext.clean("Kündi-\ngungsfrist  beträgt\r\n\r\n\r\ndrei   Monate") == "Kündigungsfrist beträgt\n\ndrei Monate"
    assert doctext.clean("Telefon-\nNummer") == "Telefon-\nNummer"  # Großbuchstabe: echter Bindestrich
    long_paragraph = " ".join(f"Satz {number} über die Versicherung." for number in range(200))
    pages = ["Erster Absatz.\n\nZweiter Absatz.", "", long_paragraph]
    items = doctext.passages(pages, size=300)
    assert items[0] == doctext.Passage(0, "Erster Absatz.\nZweiter Absatz.")
    assert {item.page for item in items} == {0, 2}  # leere Seite: kein Abschnitt
    assert all(len(item.text) <= 300 for item in items)
    assert "".join(item.text.replace("\n", " ") + " " for item in items if item.page == 2).split() == long_paragraph.split()


def test_search_terms_ignore_case_umlauts_stop_words_and_match_word_beginnings() -> None:
    assert doctext.tokens("Die Kündigungsfrist für den Vertrag") == ["kuendigungsfrist", "~kuend", "vertrag", "~vertr"]
    assert doctext.tokens("Wie hoch ist die KÜNDIGUNG?") == ["hoch", "kuendigung", "~kuend"]
    assert doctext.tokens("Seite 3 von 12") == ["3", "12"]


def test_index_finds_the_passages_that_answer_a_question() -> None:
    pages = [
        "Versicherungsschein Gewerbe Kompakt. Versicherungsnehmer: Muster GmbH, Hauptstraße 1, Musterstadt.",
        "Beitrag: Der Jahresbeitrag beträgt 1.284,60 Euro und wird vierteljährlich abgebucht.",
        "Kündigung: Der Vertrag kann mit einer Frist von drei Monaten zum Ablauf gekündigt werden.",
        "Glasbruch: Die Selbstbeteiligung beträgt 150 Euro je Versicherungsfall.",
    ]
    index = doctext.Index(doctext.passages(pages))
    assert [item.page for item in index.search("Wann kann ich kündigen? Welche Kündigungsfrist gilt?", 9000)] == [2]
    assert [item.page for item in index.search("Wie hoch ist der Jahresbeitrag?", 9000)] == [1]
    # mehrere Treffer: in der Reihenfolge des Dokuments, zusammen höchstens ``budget`` Zeichen
    found = index.search("Beitrag Selbstbeteiligung Euro", 9000)
    assert [item.page for item in found] == [1, 3]
    assert sum(len(item.text) for item in index.search("Beitrag Selbstbeteiligung Euro", 100)) <= 100
    # nichts passt: der Anfang des Dokuments, ohne Lücken
    assert [item.page for item in index.search("Raumfahrt", 200)] == [0, 1]
    assert [item.page for item in index.search("Raumfahrt", 120)] == [0]
    assert index.search("Raumfahrt", 40) == [doctext.Passage(0, pages[0][:40])]  # zu lang: gekürzt


def test_cited_pages_are_found_and_linked_only_if_the_page_exists() -> None:
    answer = "Die Frist beträgt drei Monate (S. 3). Beiträge: Seiten 4 bis 6, siehe auch S. 2, 9 und 40."
    assert doctext.cited_pages(answer, 10) == [3, 4, 5, 6, 2, 9]
    rich = doctext.rich(answer, 10)
    for page in (3, 4, 6, 2, 9):
        assert f'<a href="page:{page}">{page}</a>' in rich
    assert 'href="page:40"' not in rich and "40" in rich  # keine Seite des Dokuments: bleibt Text


def test_answers_are_shown_escaped_with_only_bold_bullets_and_page_links() -> None:
    """Inhalte einer Antwort stammen zum Teil aus dem PDF: Auszeichnungen, Bilder und fremde Verweise werden nie
    übernommen – nur fett, Überschriften, Stichpunkte und Seitenverweise, die PDF Tool selbst erzeugt."""
    answer = (
        "## Überblick\n"
        "Der Vertrag läuft **24 Monate** (S. 2).\n\n"
        "- Beitrag: 49,90 € <img src=\"https://example.com/x.png?d=geheim\"> & mehr\n"
        "* <a href=\"https://example.com\">Link</a> (S. 1)\n"
        "1. Oktober 2026 ist der Stichtag."
    )
    rich = doctext.rich(answer, 3)
    assert rich.startswith("<b>Überblick</b><br>Der Vertrag läuft <b>24 Monate</b> (S. <a href=\"page:2\">2</a>).")
    assert "<img" not in rich and "&lt;img src=" in rich and "&amp; mehr" in rich
    assert '<a href="https' not in rich and "&lt;a href=" in rich  # fremder Verweis: nur als Text
    assert "<ul><li>Beitrag: 49,90 € " in rich and "</li></ul>" in rich
    assert rich.endswith("1. Oktober 2026 ist der Stichtag.")  # nummerierte Zeile: Zahl bleibt genau so stehen
    assert rich.count("<a ") == 2
    assert doctext.rich("", 3) == "" and doctext.rich("Ohne Seite", 0) == "Ohne Seite"


# --- Anweisungen an das Modell -----------------------------------------------------------------------------------
def test_questions_send_only_the_excerpts_with_their_pages() -> None:
    excerpts = [doctext.Passage(1, "Der Jahresbeitrag beträgt 1.284,60 Euro.")]
    messages = prompts.question_messages("  Wie hoch ist der Beitrag? ", excerpts)
    assert messages[0]["role"] == "system" and "(S. 3)" in messages[0]["content"] and "erfinde nichts" in messages[0]["content"]
    assert messages[1]["content"] == "Auszüge aus dem Dokument:\n<<<\n[Seite 2]\nDer Jahresbeitrag beträgt 1.284,60 Euro.\n>>>\n\nFrage: Wie hoch ist der Beitrag?"


def test_long_documents_are_summarized_in_parts(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "SUMMARY_PART_CHARS", 250)
    monkeypatch.setattr(prompts, "SUMMARY_MAX_PARTS", 3)
    items = [doctext.Passage(page, f"Seite {page + 1}: " + "Inhalt " * 15) for page in range(10)]
    plan = prompts.plan_summary(items)
    assert [len(part) for part in plan.parts] == [2, 2, 2] and not plan.complete and plan.last_page == 6
    short = prompts.plan_summary(items[:2])
    assert len(short.parts) == 1 and short.complete and short.last_page == 2
    assert "Teil 2 von 3" in prompts.part_messages(plan.parts[1], 2, 3)[1]["content"]
    combined = prompts.combine_messages(["- a (S. 1)", "- b (S. 3)"], plan.last_page, plan.complete)[1]["content"]
    assert "Teil 1:\n- a (S. 1)" in combined and "bis Seite 6; das Dokument ist länger" in combined


# --- Der lokale KI-Prozess (Attrappe) ----------------------------------------------------------------------------
@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    path = tmp_path / "modell.gguf"
    path.write_bytes(b"GGUF")
    return path


@pytest.fixture
def server(model_file, monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FAKE_LLAMA_LOG", str(tmp_path / "anfragen.jsonl"))
    started = runtime.Server(FAKE_SERVER, model_file)
    yield started
    started.stop()


def requests(tmp_path: Path) -> list[dict]:
    log = tmp_path / "anfragen.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def test_server_listens_only_locally_with_a_random_key_and_streams_answers(server, tmp_path: Path) -> None:
    endpoint = server.start()
    assert server.running and health(endpoint) == "ok"
    command = server._process.args
    assert command[:2] == [sys.executable, str(FAKE_SERVER)]
    assert command[command.index("--host") + 1] == "127.0.0.1" and command[command.index("--port") + 1] == str(endpoint.port)
    assert command[command.index("--ctx-size") + 1] == str(runtime.CONTEXT) and "--no-webui" in command and "--log-disable" in command
    assert endpoint.key not in " ".join(command) and len(endpoint.key) >= 24  # Schlüssel nur über die Umgebung
    pieces: list[str] = []
    messages = prompts.question_messages("Kündigungsfrist?", [doctext.Passage(2, "Frist drei Monate")])
    result = Chat(endpoint, messages, max_tokens=prompts.ANSWER_TOKENS).run(pieces.append)
    assert result.text == "".join(pieces) == "Laut Dokument beträgt die Kündigungsfrist drei Monate (S. 3). Weitere Angaben stehen auf Seite 3."
    assert len(pieces) > 5 and result.finish == "stop" and result.tokens == len(pieces)
    sent = requests(tmp_path)[-1]
    assert sent["stream"] is True and sent["max_tokens"] == prompts.ANSWER_TOKENS and sent["options"] == {"enable_thinking": False}
    port = endpoint.port
    server.stop()
    assert not server.running and server.endpoint is None and not port_open(port)


def test_wrong_key_and_too_long_requests_give_understandable_errors(server, monkeypatch) -> None:
    endpoint = server.start()
    with pytest.raises(AssistantError, match="abgelehnt"):
        Chat(Endpoint(endpoint.port, "falsch"), [{"role": "user", "content": "x"}], max_tokens=10).run()
    server.stop()
    monkeypatch.setenv("FAKE_LLAMA_MODE", "context")
    endpoint = server.start()
    with pytest.raises(AssistantError, match="zu lang"):
        Chat(endpoint, [{"role": "user", "content": "x"}], max_tokens=10).run()
    server.stop()
    with pytest.raises(AssistantError, match="antwortet nicht"):
        Chat(endpoint, [{"role": "user", "content": "x"}], max_tokens=10).run()


def test_an_answer_can_be_cancelled_from_another_thread(server, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_LLAMA_MODE", "slow")
    endpoint = server.start()
    chat = Chat(endpoint, [{"role": "user", "content": "Frage"}], max_tokens=500)
    first = threading.Event()
    outcome: dict = {}

    def run() -> None:
        try:
            chat.run(lambda piece: first.set())
        except BaseException as exc:  # noqa: BLE001
            outcome["error"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    assert first.wait(10)
    started = time.monotonic()
    chat.cancel()
    worker.join(5)
    assert not worker.is_alive() and isinstance(outcome.get("error"), Cancelled)
    assert time.monotonic() - started < 2
    # danach antwortet der Prozess wieder
    monkeypatch.delenv("FAKE_LLAMA_MODE")
    assert health(endpoint) == "ok"


def test_start_reports_a_crash_a_missing_model_and_can_be_cancelled(model_file, monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(AssistantError, match="fehlt"):
        runtime.Server(FAKE_SERVER, tmp_path / "fehlt.gguf").start()
    monkeypatch.setenv("FAKE_LLAMA_MODE", "crash")
    with pytest.raises(AssistantError, match=r"unerwartet beendet \(Code 3\)"):
        runtime.Server(FAKE_SERVER, model_file).start()
    monkeypatch.setenv("FAKE_LLAMA_MODE", "hang")  # lädt nie fertig
    server = runtime.Server(FAKE_SERVER, model_file)
    cancelled = threading.Event()
    threading.Timer(0.5, cancelled.set).start()
    started = time.monotonic()
    with pytest.raises(AssistantError, match="Abgebrochen"):
        server.start(cancelled)
    assert time.monotonic() - started < runtime.STOP_TIMEOUT + 3 and not server.running


def test_exit_codes_of_windows_are_explained() -> None:
    assert "Programmdatei" in runtime._exit_text(0xC0000135)
    assert "Prozessor" in runtime._exit_text(-1073741795)
    assert "Arbeitsspeicher" in runtime._exit_text(1)


def test_server_path_comes_from_the_installation_or_the_test_variable(monkeypatch, tmp_path: Path) -> None:
    assert runtime.server_path() is None  # Quellstand: kein gebündeltes llama-server
    monkeypatch.setenv(runtime.SERVER_VARIABLE, str(tmp_path / "fehlt.exe"))
    assert runtime.server_path() is None
    monkeypatch.setenv(runtime.SERVER_VARIABLE, str(FAKE_SERVER))
    assert runtime.server_path() == FAKE_SERVER and runtime.platform_supported()
    assert runtime.total_memory() > 0


# --- Paket: KI-Laufzeit im Setup -------------------------------------------------------------------------------
def test_release_check_finds_an_incomplete_ai_runtime(tmp_path: Path) -> None:
    """``release_check.check_ai``: llama-server.exe (64 Bit), Rechenwerke ggml-cpu-*.dll, jede geladene DLL vorhanden,
    keine überzählige DLL, kein weiteres Programm, Lizenztexte – mit kleinen, selbst gebauten PE-Dateien."""
    import importlib.util

    from test_editor_ocr import fake_pe

    spec = importlib.util.spec_from_file_location("release_check_ai", Path(__file__).resolve().parents[1] / "release_check.py")
    release_check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_check)
    folder = tmp_path / "payload" / "ai"
    folder.mkdir(parents=True)
    fake_pe(folder / "llama-server.exe", ["llama-server-impl.dll", "KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll"])
    fake_pe(folder / "llama-server-impl.dll", ["llama.dll", "MSVCP140.dll", "WS2_32.dll"])
    fake_pe(folder / "llama.dll", ["ggml.dll", "VCRUNTIME140.dll"])
    fake_pe(folder / "ggml.dll", ["ggml-base.dll"])
    fake_pe(folder / "ggml-base.dll", ["KERNEL32.dll"])
    fake_pe(folder / "ggml-cpu-haswell.dll", ["ggml-base.dll", "libomp.dll"])
    fake_pe(folder / "ggml-cpu-x64.dll", ["ggml-base.dll", "libomp.dll"])
    fake_pe(folder / "libomp.dll", ["KERNEL32.dll"])
    fake_pe(folder / "msvcp140.dll", ["VCRUNTIME140.dll"])
    fake_pe(folder / "vcruntime140.dll", ["KERNEL32.dll"])
    (folder / "LICENSES.txt").write_text("License for llama.cpp\n===\n\nMIT License\n", encoding="utf-8")
    assert release_check.check_ai(tmp_path / "payload") == []
    fake_pe(folder / "ggml-rpc.dll", ["ggml-base.dll"])  # RPC-Backend: nie mitliefern
    fake_pe(folder / "llama-cli.exe", ["llama.dll"])
    (folder / "libomp.dll").unlink()
    (folder / "LICENSES.txt").unlink()
    assert release_check.check_ai(tmp_path / "payload") == [
        "Für die KI-Laufzeit fehlen DLLs in ai/: libomp.dll",
        "Nicht benötigte DLLs in ai/: ggml-rpc.dll",
        "Weitere Programme in ai/: llama-cli.exe",
        "Im Paket fehlen die Lizenzen der KI-Laufzeit: ai/LICENSES.txt",
    ]
    for backend in folder.glob("ggml-cpu-*.dll"):
        backend.unlink()
    assert "Keine Rechenwerke in ai/ (ggml-cpu-*.dll)" in release_check.check_ai(tmp_path / "payload")
    assert release_check.check_ai(tmp_path / "leer") == ["KI-Laufzeit fehlt im Paket: ai/llama-server.exe"]
