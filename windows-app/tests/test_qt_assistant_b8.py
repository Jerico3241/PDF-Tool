"""KI-Werkzeuge von 5.0 Beta 8: Reiter »KI« im Menüband (PDF, Text, Präsentation, Tabelle), Schreibhilfe (umschreiben,
kürzen, Ton, schreiben lassen), Grammatik mit Übernehmen, Übersetzen (Markierung und nebeneinander), Präsentation aus
einem Thema, Tabellen auswerten und Diagramm vorschlagen, PDF-Formular ausfüllen. Attrappe statt llama-server wie in
``test_qt_assistant``; nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent

from conftest import pump, wait_until
from test_qt_assistant import a, answers, app_ki, click_item, contract_pdf, install, ki, requests, shown, wait_answer  # noqa: F401 - Fixtures
from test_qt_reader import open_pdf, reader
from test_qt_signing import answer

from qtapp import dialogs


def _office_available() -> bool:
    from tools.text import engine

    return engine.available()


needs_office = pytest.mark.skipif(not _office_available(), reason="LibreOffice fehlt – Text und Tabelle nicht prüfbar")


def ready(h) -> None:
    install(ki_model(h))
    a(h).setEnabled(True)
    h.navigate("reader", 0.3)


def ki_model(h):
    from assistant import catalog

    return catalog.COMPACT


def form_pdf(path: Path) -> Path:
    """Formular mit Beschriftungen links neben den Feldern, ein Feld nur mit Tooltip, ein Kontrollkästchen."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(72, 742, "Vorname:")
    c.acroForm.textfield(name="Text1", x=170, y=736, width=200, height=20)
    c.drawString(72, 702, "Nachname:")
    c.acroForm.textfield(name="Text2", x=170, y=696, width=200, height=20)
    c.acroForm.textfield(name="Feld3", tooltip="Wohnort", x=170, y=656, width=200, height=20)
    c.drawString(72, 622, "AGB akzeptiert")
    c.acroForm.checkbox(name="Haken", x=200, y=616, size=16)
    c.showPage()
    c.save()
    return path


def last_answer(h) -> dict:
    return answers(h)[-1]


def tool(h, action, timeout: float = 60) -> dict:
    """Werkzeug starten und warten, bis seine Antwort fertig ist (es beginnt erst, wenn das Dokument geantwortet hat)."""
    before = len(answers(h))
    action()
    assert wait_until(lambda: len(answers(h)) >= before + 2 and not answers(h)[-1]["pending"] and not a(h).busy, timeout), answers(h)[before:]
    pump(0.2)
    return answers(h)[-1]


# --- Oberfläche --------------------------------------------------------------------------------------------------
def test_views_with_the_ai_tab_load_without_messages(ui_app) -> None:
    """Text, Präsentation und Tabelle laden mit dem neuen Reiter ohne Meldungen (auch ohne Dokument)."""
    from qtapp.application import QML_DIR

    h = ui_app
    for name, bar in (("TextView", "textRibbonBar_ai"), ("SlidesView", "slidesRibbonBar_ai"), ("SheetView", "sheetRibbonBar_ai")):
        component = QQmlComponent(h.engine, QUrl.fromLocalFile(str(QML_DIR / "PdfTool" / "Reader" / f"{name}.qml")))
        assert component.isReady(), component.errorString()
        view = component.create()
        assert view is not None, name
        view.setParentItem(h.window.contentItem())
        pump(0.3)
        assert view.findChild(QObject, bar) is not None, bar
        view.deleteLater()
        pump(0.2)


def test_pdf_ai_tab_switches_the_assistant_on_and_offers_the_pdf_tools(app_ki, ki, tmp_path: Path) -> None:
    """Ausgeschaltet zeigt der Reiter »KI« nur den Hinweis mit »Einschalten«; danach die Werkzeuge für PDFs (keine
    Schreibhilfe) und die Seitenleiste."""
    h = app_ki
    install(ki.compact)
    h.navigate("reader", 0.3)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    click_item(h, h.item("readerRibbon_ai"))
    assert h.item("aiRibbonOff").isVisible() and not h.item("aiRibbonSummarize").isVisible()
    click_item(h, h.item("aiRibbonEnable"))
    assert a(h).enabled
    assert wait_until(lambda: h.item("readerAssistantPanel") is not None and h.item("readerAssistantPanel").isVisible(), 5)
    for name in ("aiRibbonPanel", "aiRibbonSummarize", "aiRibbonTranslate", "aiRibbonForm", "aiRibbonSlides"):
        assert h.item(name).isVisible(), name
    for name in ("aiRibbonWrite", "aiRibbonGrammar", "aiRibbonAnalyze", "aiRibbonOff"):
        assert not h.item(name).isVisible(), name
    assert h.item("aiRibbonPanel").property("checked") is True
    click_item(h, h.item("aiRibbonPanel"))
    assert reader(h).rightPanel != "assistant"


# --- PDF-Formular -------------------------------------------------------------------------------------------------
def test_fill_a_pdf_form_from_free_text_after_review(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Angaben als Text: Das Modell bekommt die Beschriftungen (Text links daneben, Tooltip) und antwortet als JSON
    (Schema); Novadesk zeigt die Vorschläge, nur angekreuzte werden eingetragen – das Kontrollkästchen wird gesetzt."""
    h = app_ki
    ready(h)
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    doc = open_pdf(h, form_pdf(tmp_path / "antrag.pdf"))
    seen: dict = {}
    answer(h, "ai_form", {"data": "Vorname: Anna\nNachname: Berger\nWohnort: Köln\nAGB akzeptiert: ja"}, seen)
    review: dict = {}

    def choose(h) -> dict:
        items = h.app.dialogs.request["data"]["items"]
        assert h.item("aiFormReview_0") is not None and h.item("aiFormReview_0").property("checked") is True
        return {"chosen": [item["key"] for item in items if item["title"] != "Wohnort"]}

    answer(h, "ai_form_review", choose, review)
    a(h).fillForm()
    assert wait_until(lambda: not a(h).busy and review, 30), "Vorschläge kamen nicht"
    assert seen["count"] == 4 and seen["fields"] == ["Vorname", "Nachname", "Wohnort", "AGB akzeptiert"]
    titles = {item["title"]: item["value"] for item in review["items"]}
    assert titles == {"Vorname": "Anna", "Nachname": "Berger", "Wohnort": "Köln", "AGB akzeptiert": "Ja"}
    sent = requests(ki)[-1]
    assert sent["format"]["type"] == "json_object" and set(sent["format"]["schema"]["properties"]) == {"1", "2", "3", "4"}
    assert "1: Vorname [Feldname Text1] (Textfeld, höchstens 100 Zeichen)" in sent["messages"][-1]["content"]
    assert wait_until(lambda: {f["name"]: f["value"] for f in doc.fields}.get("Text1") == "Anna", 10)
    values = {f["name"]: f["value"] for f in doc.fields}
    assert values["Text2"] == "Berger" and values["Feld3"] == "" and values["Haken"] is True
    entry = last_answer(h)
    assert entry["note"] == "3 Felder ausgefüllt." and entry["actions"] == []
    assert doc.undoText == "Formular mit KI ausfüllen"  # ein Schritt für alle Felder
    doc.undo()
    doc.loadFields()
    assert wait_until(lambda: {f["name"]: f["value"] for f in doc.fields}.get("Text1") == "", 10)
    assert {f["name"]: f["value"] for f in doc.fields}["Haken"] is False


def test_a_pdf_without_fields_says_so(app_ki, ki, tmp_path: Path) -> None:
    h = app_ki
    ready(h)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    a(h).fillForm()
    notice = h.app.notices.area("assistant")
    assert wait_until(lambda: "keine Formularfelder" in notice.message, 5)
    assert requests(ki) == []


# --- Texte ------------------------------------------------------------------------------------------------------------
@needs_office
def test_rewrite_grammar_write_and_translate_in_a_text(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Text: Markierung kürzen → »Ersetzen« setzt das Ergebnis an ihre Stelle; Grammatik findet zwei Sätze, einer wird
    übernommen; »Schreiben lassen« fügt an der Schreibmarke ein; die Markierung übersetzen."""
    from test_qt_text import _new_text as new

    h = app_ki
    ready(h)
    doc = new(h)
    done: list = []
    doc.ai_insert("Das ist ein fehler im Text. Er gehen heute heim.", lambda ok: done.append(ok))
    assert wait_until(lambda: done, 20)
    pump(0.5)
    # Grammatik (ganzer Text, nichts markiert)
    entry = tool(h, lambda: a(h).checkGrammar())
    assert entry["kind"] == "answer" and len(entry["changes"]) == 2, entry
    assert [c["after"] for c in entry["changes"]] == ["Das ist ein Fehler im Text.", "Er geht heute heim."]
    assert "<s>" in entry["changes"][0]["rich"] and "<b>Fehler</b>" in entry["changes"][0]["rich"]
    assert h.item("textAssistantPanel") is not None and h.item("textAssistantPanel").isVisible()
    click_item(h, shown(h, "readerAssistantChangeApply"))
    assert wait_until(lambda: last_answer(h)["changes"][0]["state"] == "done", 20)
    texts: list = []
    doc.ai_paragraphs(10000, texts.append, lambda exc: texts.append(exc))
    assert wait_until(lambda: texts, 20)
    assert "Das ist ein Fehler im Text." in " ".join(texts[0]) and "Er gehen" in " ".join(texts[0])
    a(h).act(last_answer(h)["key"], "applyAll")
    assert wait_until(lambda: all(c["state"] == "done" for c in last_answer(h)["changes"]), 20)
    # Markierung kürzen und ersetzen
    doc.selectAll()
    assert wait_until(lambda: doc.selection, 10)
    entry = tool(h, lambda: a(h).editSelection("shorten"))
    assert entry["text"].startswith("[NEU] Das ist ein Fehler") and [x["key"] for x in entry["actions"]] == ["replace"]
    assert not entry["text"].startswith("Hier ist")  # Einleitung des Modells entfernt
    a(h).act(entry["key"], "replace")
    texts.clear()
    assert wait_until(lambda: (doc.ai_paragraphs(10000, texts.append, texts.append) or True) and texts and "[NEU]" in " ".join(texts[-1]), 20)
    # Schreiben lassen
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    answer(h, "ai_write", {"instruction": "Antwort auf eine Anfrage"})
    entry = tool(h, lambda: a(h).writeText())
    assert entry["text"].startswith("Sehr geehrte Damen und Herren") and [x["key"] for x in entry["actions"]] == ["insert"]
    sent = requests(ki)[-1]["messages"]
    assert "Auftrag: Antwort auf eine Anfrage" in sent[-1]["content"] and "[NEU]" in sent[-1]["content"]  # Text vor der Schreibmarke
    # Markierung übersetzen
    doc.selectAll()
    assert wait_until(lambda: doc.selection, 10)
    entry = tool(h, lambda: a(h).translateSelection("en"))
    assert entry["text"].startswith("[EN]") and entry["actions"][0]["key"] == "replace"
    assert answers(h)[-2]["text"] == "Markierung ins Englische übersetzen"


@needs_office
def test_without_selection_the_writing_tools_explain_what_to_do(app_ki, ki) -> None:
    from test_qt_text import _new_text as new

    h = app_ki
    ready(h)
    new(h)
    a(h).editSelection("rewrite")
    pump(0.5)
    assert answers(h) == [] and requests(ki) == []


@needs_office
def test_translate_a_text_side_by_side(app_ki, ki, monkeypatch) -> None:
    """»Dokument übersetzen« bei Texten: immer nebeneinander – ein neues Dokument mit Original und Übersetzung je Absatz."""
    from test_qt_text import _new_text as new

    h = app_ki
    ready(h)
    doc = new(h)
    done: list = []
    doc.ai_insert("Erster Absatz.\nZweiter Absatz.", lambda ok: done.append(ok))
    assert wait_until(lambda: done, 20)
    seen: dict = {}
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    answer(h, "assistant_translate", {"language": "en", "first": 0, "last": 0, "mode": "side"}, seen)
    a(h).translate()
    assert wait_until(lambda: not a(h).busy and reader(h).current is not doc and getattr(reader(h).current, "ready", False), 90)
    assert seen["kind"] == "text"
    result = a(h)._conversations[doc.ident][-1]
    assert "nebeneinander" in result["text"] and "2 Absätze" in result["text"]
    new_doc = reader(h).current
    assert new_doc.kind == "text" and new_doc.name.endswith("(Englisch, nebeneinander).docx")
    texts: list = []
    new_doc.ai_paragraphs(20000, texts.append, texts.append)
    assert wait_until(lambda: texts, 20)
    joined = " | ".join(texts[0])
    assert "Erster Absatz." in joined and "[EN] Erster Absatz." in joined and "[EN] Zweiter Absatz." in joined


# --- Präsentation --------------------------------------------------------------------------------------------------
@needs_office
def test_create_a_presentation_from_a_topic(app_ki, ki, tmp_path: Path, monkeypatch) -> None:
    """Thema und Anzahl: Gliederung vom Modell, daraus eine neue Präsentation (Titelfolie plus Inhaltsfolien)."""
    h = app_ki
    ready(h)
    open_pdf(h, contract_pdf(tmp_path / "vertrag.pdf"))
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)
    seen: dict = {}
    answer(h, "ai_slides", {"source": "topic", "topic": "Neue Urlaubsplanung", "count": 4}, seen)
    a(h).createPresentation()
    assert wait_until(lambda: not a(h).busy and getattr(reader(h).current, "kind", "") == "praesentation" and reader(h).current.ready, 120)
    slides = reader(h).current
    assert wait_until(lambda: slides.slideCount == 5, 20), slides.slideCount
    assert seen["document"] == "vertrag.pdf" and seen["source"] == "document"
    assert "Genau 4 Inhaltsfolien" in requests(ki)[-1]["messages"][-1]["content"]


# --- Tabellen ----------------------------------------------------------------------------------------------------------
def _workbook(path: Path) -> Path:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Umsatz"
    sheet.append(["Monat", "Umsatz", "Kosten"])
    for month, revenue, cost in (("Januar", 1200, 800), ("Februar", 1350, 820), ("März", 1100, 790), ("April", 1600, 900)):
        sheet.append([month, revenue, cost])
    sheet["E1"] = datetime.date(2026, 1, 1)
    book.save(path)
    return path


@needs_office
def test_analyze_a_table_and_insert_the_suggested_chart(app_ki, ki, tmp_path: Path) -> None:
    """Auswerten: Kennzahlen rechnet Novadesk selbst (Summe 5.250), das Modell erklärt sie; »Diagramm vorschlagen«
    wählt nach einer Regel (Monate → Linie) und fügt es auf Klick ein."""
    from test_qt_sheet import _open

    h = app_ki
    ready(h)
    sheet = _open(h, _workbook(tmp_path / "umsatz.xlsx"))
    sheet.select(1, 1, False)
    pump(0.3)
    entry = tool(h, lambda: a(h).analyzeTable())
    assert "Summe von »Umsatz« beträgt 5.250" in entry["text"], entry
    assert h.item("sheetAssistantPanel").isVisible()
    user = requests(ki)[-1]["messages"][-1]["content"]
    assert "Blatt »Umsatz«" in user and "Januar" in user
    entry = tool(h, lambda: a(h).suggestChart())
    assert "Liniendiagramm" in entry["text"] and entry["actions"][0]["key"] == "chart"
    before = len(sheet.objects)
    button = shown(h, "readerAssistantAction_chart")
    click_item(h, button)
    assert wait_until(lambda: last_answer(h)["note"] == "Diagramm eingefügt.", 5), last_answer(h)
    assert wait_until(lambda: len(sheet.objects) == before + 1, 30), (sheet.objects, h.app.notices.area("sheet").message if hasattr(h.app.notices, "area") else "")


@needs_office
def test_questions_to_a_table_name_the_sheet(app_ki, ki, tmp_path: Path) -> None:
    from test_qt_sheet import _open

    h = app_ki
    ready(h)
    _open(h, _workbook(tmp_path / "umsatz.xlsx"))
    entry = tool(h, lambda: a(h).ask("Wie hoch war der Umsatz im Februar?"))
    assert entry["kind"] == "answer" and entry["pages"] == []
    user = requests(ki)[-1]["messages"][-1]["content"]
    assert "Blatt »Umsatz«" in user and "Zeile 3: Monat: Februar; Umsatz: 1350" in user
