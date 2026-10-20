"""KI-Assistent, Ausbau in 4.0 Beta 6: »Dokument übersetzen« als neues PDF und »Mehrere PDFs fragen« (gewählte PDFs oder
ein Ordner, Scans über die Texterkennung) mit Datei und Seite in der Antwort. Attrappe statt llama-server wie in
``test_qt_assistant``; die Texterkennung ist eine Attrappe."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from conftest import pump, wait_until
from test_qt_assistant import a, answers, app_ki, ask, click_item, contract_pdf, install, ki, requests, scan_pdf, show_panel, shown, wait_answer  # noqa: F401 - Fixtures
from test_qt_reader import open_pdf, reader
from test_qt_signing import answer

from qtapp import dialogs


def pdf_text(path: Path) -> list[str]:
    document = pdfium.PdfDocument(str(path))
    try:
        return [document[i].get_textpage().get_text_range() for i in range(len(document))]
    finally:
        document.close()


def test_translate_document_into_a_new_pdf(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Sprache und Seiten wählen, Ziel bestätigen: Seite für Seite übersetzt, als neues PDF gespeichert und geöffnet."""
    h = app_ki
    install(ki.compact)
    a(h).setEnabled(True)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    h.navigate("reader", 0.3)
    source = contract_pdf(tmp_path / "vertrag.pdf")
    open_pdf(h, source)
    show_panel(h)
    target = tmp_path / "vertrag (Englisch).pdf"
    names: list = []
    monkeypatch.setattr(type(reader(h)), "pick_save_pdf", lambda self, name, title: names.append(name) or str(target))
    seen: dict = {}

    def choose(h) -> dict:
        assert h.item("translateLanguage_en").property("checked") is True
        return {"language": "en", "first": 1, "last": 2}

    answer(h, "assistant_translate", choose, seen)
    original = reader(h).current.ident
    click_item(h, h.item("readerAssistantTranslate"))
    assert wait_until(lambda: not a(h).busy and target.is_file(), 60), "Übersetzung wurde nicht fertig"
    assert seen["pageCount"] == 3 and names == ["vertrag (Englisch).pdf"]
    # Die Übersetzung öffnet sich in einem neuen Tab; das Gespräch bleibt beim Original
    assert wait_until(lambda: Path(reader(h).current.path or "") == target, 20)
    question, result = a(h)._conversations[original]
    assert question["text"] == "Seiten 2–3 ins Englische übersetzen"
    assert result["kind"] == "answer" and "vertrag (Englisch).pdf" in result["text"] and "2 Seiten" in result["text"] and not result["pending"]
    pages = pdf_text(target)
    assert len(pages) == 2 and "Seite 1 · Übersetzung (Englisch)" in pages[0]
    assert "[EN] Beitrag" in pages[0] and "1.284,60 Euro" in pages[0] and "[EN] Kündigung" in pages[1]
    sent = [entry["messages"] for entry in requests(ki)]
    assert len(sent) == 2 and all(messages[0]["content"].startswith("Du bist ein Übersetzer") and "Englische" in messages[0]["content"] for messages in sent)
    assert source.read_bytes()[:5] == b"%PDF-"


def test_questions_to_several_pdfs_name_file_and_page(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Ordner wählen (mit Unterordner): Text aller PDFs, ein Scan per Texterkennung, eine beschädigte Datei wird genannt.
    Die Antwort nennt Datei und Seite; ein Klick öffnet die Datei an der Stelle. × fragt wieder nur das geöffnete PDF."""
    from assistant import library
    from qtapp import files

    h = app_ki
    install(ki.compact)
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)
    folder = tmp_path / "Verträge"
    (folder / "Alt").mkdir(parents=True)
    contract_pdf(folder / "A-Vertrag.pdf")
    contract_pdf(folder / "Alt" / "B-Vertrag.pdf", pages=(("Altvertrag", "Kündigungsfrist sechs Wochen zum Quartalsende."),))
    scan_pdf(folder / "C-Scan.pdf")
    (folder / "D-kaputt.pdf").write_bytes(b"%PDF-1.7 kaputt")
    open_pdf(h, contract_pdf(tmp_path / "offen.pdf"))
    show_panel(h)
    # Texterkennung (Attrappe): der Scan liefert Text
    recognized: list = []
    monkeypatch.setattr(reader(h), "_ocr_engine", type("Engine", (), {"languages": ["deu", "eng"]})(), raising=False)
    monkeypatch.setattr(library, "tesseract_text", lambda engine, languages, cancel=None: lambda png, dpi: recognized.append((languages, dpi)) or "Gescannte Kündigung vom 3. Mai 2026")
    monkeypatch.setattr(files, "RESPONSES", [str(folder)])
    a(h).chooseFolder()
    note = wait_answer(h, 60)
    assert a(h).scopeLabel == "3 PDFs" and shown(h, "readerAssistantScope").property("text") == "Fragen an: 3 PDFs"
    assert note["kind"] == "note" and "3 PDFs mit 5 Seiten gelesen" in note["text"] and "1 Scan-Seite per Texterkennung" in note["text"] and "D-kaputt.pdf" in note["text"]
    assert recognized == [(["deu", "eng"], library.OCR_DPI)]
    assert not h.item("readerAssistantSummarizeMore").isVisible()  # Zusammenfassen gilt nur für ein Dokument
    ask(h, "Kuendigungsfrist")
    reply = wait_answer(h)
    assert reply["kind"] == "answer" and reply["sources"], reply
    user = requests(ki)[-1]["messages"][-1]["content"]
    assert "»B-Vertrag.pdf«, Seite 1]" in user and "[Datei 1 »A-Vertrag.pdf«, Seite 3]" in user
    assert 'href="src:' in reply["rich"] and "A-Vertrag.pdf, S. " in reply["rich"]
    first = reply["sources"][0]
    assert first["label"].endswith(f" · S. {first['page']}")
    click_item(h, shown(h, "readerAssistantSource"))
    expected = Path(a(h)._library.files[first["file"]])
    assert wait_until(lambda: reader(h).current is not None and Path(reader(h).current.path or "") == expected and reader(h).current.currentPage == first["page"] - 1, 20)
    pump(0.3)
    # Zurück zum geöffneten Dokument: dessen (leeres) Gespräch
    click_item(h, h.item("readerAssistantScopeClear"))
    assert a(h).scopeLabel == "" and answers(h) == [] and h.item("readerAssistantIntro").isVisible()
