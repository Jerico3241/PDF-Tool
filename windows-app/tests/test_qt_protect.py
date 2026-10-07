"""Qt-Oberfläche: Schützen und Weitergeben (3.2) – Schwärzen (Bereich, Text, Suchen), Bereinigen, Kennwortschutz,
Reduzieren, Verkleinern, Kopf-/Fußzeile und Wasserzeichen, Stempel und Unterschrift, Links, Lesezeichen und
Zuschneiden.

Bedient wird wie in ``test_qt_reader``: Werkzeuge mit der Maus auf der Seite, Dialoge über ``dialogs.ask``
(ersetzt durch feste Antworten). Nach jedem Test darf die QML-Engine keine Meldung ausgegeben haben.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PySide6.QtCore import Qt

import editorsamples as samples
from conftest import pump, wait_until
from test_qt_reader import click, drag, key, open_pdf, page_point, page_text, reader, right_click, settle, window_point


@pytest.fixture
def reader_app(ui_app):
    ui_app.app.dialogs.shutdown()
    ui_app.navigate("reader", 0.3)
    return ui_app


def answers(monkeypatch, h, replies: dict):
    """``dialogs.ask`` je Art (kind) mit fester Antwort; protokolliert die Anfragen."""
    seen: list[tuple[str, dict]] = []
    original = h.app.dialogs.ask

    def ask(kind, title, message="", **kwargs):
        seen.append((kind, dict(kwargs.get("data") or {})))
        if kind in replies:
            reply = replies[kind]
            return reply(kwargs.get("data") or {}) if callable(reply) else reply
        return original(kind, title, message, **kwargs)

    monkeypatch.setattr(h.app.dialogs, "ask", ask)
    return seen


def center(item):
    return window_point(item, item.width() / 2, item.height() / 2)


def child(item, name: str):
    """Objekt mit ``objectName`` unterhalb eines Elements (Menüs hängen nicht im Elementbaum)."""
    from PySide6.QtCore import QObject

    found = [obj for obj in item.findChildren(QObject) if obj.objectName() == name]
    return found[0] if found else None


# --- Werkzeugleiste ------------------------------------------------------------------------------------------------
def test_toolbar_menus_open_and_tools_switch(reader_app, tmp_path: Path) -> None:
    h = reader_app
    doc = open_pdf(h, samples.standard_text(tmp_path / "Leiste.pdf"))
    toolbar = h.item("readerToolbar")
    for button, name in (("readerProtect", "readerProtectMenu"), ("readerPageDesign", "readerPageDesignMenu"), ("readerSignMenu", "readerSignToolMenu")):
        menu = child(toolbar, name)
        click(h, center(h.item(button)))
        assert wait_until(lambda: menu.property("opened"), 3), name
        key(h, Qt.Key.Key_Escape)
        assert wait_until(lambda: not menu.property("visible"), 3)
    for tool in ("redact", "stamp", "link"):
        doc.setTool(tool)
        pump(0.2)
        assert doc.tool == tool and h.item("readerToolOptionsCard").isVisible()
    assert h.item("readerRedactApply") is not None and h.item("readerProtect").property("checked") is False
    doc.setTool("redact")
    pump(0.1)
    assert h.item("readerProtect").property("checked") is True  # Schwärzen ist aktiv: »Schützen« markiert
    h.item("readerView").forceActiveFocus()
    key(h, Qt.Key.Key_Escape)
    assert doc.tool == "select"


# --- Schwärzen -------------------------------------------------------------------------------------------------------
def test_redact_area_by_mouse_apply_and_undo(reader_app, tmp_path: Path) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "Rechnung.pdf")
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("redact")
    pump(0.1)
    # »Rechnung Nr. 4711 vom …« steht bei v ≈ 70–85 (Anzeige-Punkte), »4711« etwa bei u = 150–185
    drag(h, page_point(h, 0, 145, 66), page_point(h, 0, 190, 86))
    assert doc.redactCount == 1 and h.item("readerRedactMark") is not None
    doc.applyRedaction()  # Rückfrage: »primary«
    settle(h)
    assert doc.redactCount == 0 and doc.undoText == "Schwärzen"
    doc.saveDocument()
    settle(h)
    text = page_text(path)
    assert "4711" not in text and "Rechnung" in text and "vom" in text
    doc.undo()
    settle(h)
    assert doc.dirty


def test_redact_text_selection_and_search(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    lines = ("IBAN DE89 3704 0044 0532 0130 00", "Kontakt: erika.muster@example.org", "Vertrag 4711 vom 01.02.2026")
    path = samples.standard_text(tmp_path / "Daten.pdf", lines=lines)
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("redact")
    doc.setRedactMode("text")
    doc.loadText(0)
    settle(h)
    drag(h, page_point(h, 0, 70, 77), page_point(h, 0, 130, 77))  # »IBAN DE…« in der ersten Zeile
    settle(h)
    assert doc.redactCount >= 1
    doc.clearRedactMarks()
    assert doc.redactCount == 0
    seen = answers(monkeypatch, h, {"redact_search": ("primary", {"kinds": ["iban", "email"], "terms": "Vertrag", "matchCase": False, "scope": "all"})})
    doc.searchRedact()
    settle(h)
    assert seen[0][0] == "redact_search" and doc.redactCount >= 3
    doc.applyRedaction()
    settle(h)
    doc.saveDocument()
    settle(h)
    text = page_text(path)
    assert "3704" not in text and "example.org" not in text and "Vertrag" not in text and "Kontakt:" in text


# --- Bereinigen, Kennwortschutz, Reduzieren, Verkleinern --------------------------------------------------------------
def test_clean_and_password_protection_are_saved(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "Weitergeben.pdf")
    doc = open_pdf(h, path)
    seen = answers(monkeypatch, h, {
        "checklist": lambda data: ("primary", {item["key"]: item["count"] > 0 for item in data["items"]}),
        "protect": ("primary", {"mode": "set", "userPassword": "geheim1", "ownerPassword": "", "print": True, "copy": True, "edit": True, "annotate": True, "fill": True, "assemble": True}),
    })
    doc.cleanDocument()
    settle(h)
    assert seen[-1][0] == "checklist" and any(item["key"] == "metadata" and item["count"] > 0 for item in seen[-1][1]["items"])
    doc.protectDocument()
    settle(h)
    assert doc.undoText == "Kennwortschutz festlegen"
    doc.saveDocument()
    settle(h)
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(path)
    with pikepdf.open(path, password="geheim1") as saved:
        assert saved.is_encrypted and "/Title" not in saved.docinfo and "/Author" not in saved.docinfo


def test_flatten_comments_and_optimize_copy(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files

    h = reader_app
    path = samples.standard_text(tmp_path / "Original.pdf")
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("rect")
    drag(h, page_point(h, 0, 300, 400), page_point(h, 0, 420, 480))
    settle(h)
    assert len(doc.annotations) == 1
    answers(monkeypatch, h, {
        "checklist": lambda data: ("primary", {item["key"]: True for item in data["items"]}),
        "optimize": ("primary", {"level": "klein"}),
    })
    doc.flattenDocument()
    settle(h)
    assert doc.annotations == [] and doc.undoText == "Reduzieren"
    target = tmp_path / "Original_verkleinert.pdf"
    monkeypatch.setattr(files, "RESPONSES", [str(target)])
    before = path.read_bytes()
    doc.optimizeDocument()
    settle(h)
    assert target.is_file() and path.read_bytes() == before  # Kopie – das Original bleibt
    with pikepdf.open(target) as copy:
        assert len(copy.pages) == 1


# --- Kopf-/Fußzeile, Wasserzeichen, Zuschneiden ----------------------------------------------------------------------
def test_header_footer_watermark_and_crop(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "Akte.pdf", pages=3)
    doc = open_pdf(h, path)
    header = {"items": {"bc": "Blatt {seite} von {seiten}", "tr": "{datei}"}, "font": "Helvetica", "size": 9, "color": "#000000", "margin": 28, "start": 1, "pages": "", "replace": True}
    seen = answers(monkeypatch, h, {
        "header_footer": ("primary", header),
        "watermark": ("primary", {"text": "ENTWURF", "font": "Helvetica-Bold", "size": 0, "color": "#BE1E2D", "opacity": 0.25, "angle": 45, "behind": False, "pages": "1", "replace": True}),
        "crop": ("primary", {"margins": [10, 10, 10, 10], "scope": "all", "range": "", "reset": False}),
    })
    doc.headerFooterDocument()
    settle(h)
    doc.watermarkDocument()
    settle(h)
    width_before = doc.pageSizes[0][0]
    doc.cropPages([])
    settle(h)
    assert [kind for kind, _data in seen] == ["header_footer", "watermark", "crop"]
    assert abs(doc.pageSizes[0][0] - (width_before - 2 * 10 * 72 / 25.4)) < 0.1
    doc.saveDocument()
    settle(h)
    assert "Blatt 3 von 3" in page_text(path, 2) and "ENTWURF" in page_text(path, 0) and "ENTWURF" not in page_text(path, 1)
    # Ersetzen statt verdoppeln: ein zweites Mal Kopf-/Fußzeile
    doc.headerFooterDocument()
    settle(h)
    assert seen[-1][1]["existing"] == 3
    doc.saveDocument()
    settle(h)
    assert page_text(path, 0).count("Blatt 1 von 3") == 1


# --- Stempel und Unterschrift ------------------------------------------------------------------------------------------
def test_stamp_and_signature_are_placed_and_selected(reader_app, tmp_path: Path, monkeypatch) -> None:
    from storage import data_root

    h = reader_app
    path = samples.standard_text(tmp_path / "Freigabe.pdf")
    doc = open_pdf(h, path, whole_page=True)
    doc.setTool("stamp")
    doc.setStampPreset("genehmigt")
    doc.setStampSubtitle("{datum}")
    pump(0.1)
    click(h, page_point(h, 0, 400, 300))
    settle(h)
    stamp = next(item for item in doc.annotations if item["subtype"] == "/Stamp")
    assert stamp["label"] == "Stempel" and stamp["contents"].startswith("GENEHMIGT")
    assert doc.tool == "select" and doc.selectedObject.get("key") == stamp["key"] and stamp["resizable"]
    strokes = [[[10 + i * 4, 40 + (6 if i % 2 else -6)] for i in range(30)]]
    seen = answers(monkeypatch, h, {"signature": ("primary", {"mode": "draw", "strokes": strokes, "pen": 2.6, "color": "#162E78", "save": True, "label": "Privat"})})
    doc.setTool("signature")  # noch keine Unterschrift: Dialog »Unterschrift erstellen«
    settle(h)
    assert seen and seen[0][0] == "signature"
    assert wait_until(lambda: len(doc.signatures) == 1, 5) and doc.signatures[0]["label"] == "Privat"
    assert doc.signatures[0]["preview"].startswith("data:image/png;base64,")
    assert (data_root() / "unterschriften.json").is_file()
    click(h, page_point(h, 0, 200, 600))
    settle(h)
    signature = next(item for item in doc.annotations if item["label"] == "Unterschrift")
    assert doc.selectedObject.get("key") == signature["key"]
    doc.saveDocument()
    settle(h)
    with pikepdf.open(path) as saved:
        assert sorted(str(a.Name) for a in saved.pages[0].Annots) == ["/Approved", "/PTSignature"]
    doc.setTool("signature")
    settle(h)
    doc.deleteSignature(doc.signatures[0]["id"])  # Rückfrage: »primary«
    settle(h)
    assert doc.signatures == [] and not (data_root() / "unterschriften.json").exists()


# --- Links, Lesezeichen --------------------------------------------------------------------------------------------------
def test_links_are_created_followed_and_web_addresses_need_a_click(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import files

    h = reader_app
    path = samples.standard_text(tmp_path / "Verweise.pdf", pages=3)
    doc = open_pdf(h, path, whole_page=True)
    answers(monkeypatch, h, {"link": ("primary", {"kind": "page", "page": "3", "uri": ""})})
    doc.setTool("link")
    drag(h, page_point(h, 0, 300, 500), page_point(h, 0, 450, 530))
    settle(h)
    assert wait_until(lambda: len(doc.linkPages.get("0", [])) == 1, 5)
    link = doc.linkPages["0"][0]
    assert link["target"] == 2 and link["ours"]
    # Auswählen: Klick auf den Link springt zur Seite
    doc.setTool("select")
    pump(0.2)
    click(h, page_point(h, 0, 375, 515))
    settle(h)
    assert doc.currentPage == 2
    # Webadresse: erst nach Rückfrage (Test: »primary«) – geöffnet wird über files.open_url
    doc.goTo(0)
    settle(h)
    answers(monkeypatch, h, {"link": ("primary", {"kind": "web", "page": "1", "uri": "www.example.org/hilfe"})})
    doc.editLink(0, link["key"])
    settle(h)
    assert wait_until(lambda: doc.linkPages.get("0", [{}])[0].get("uri") == "https://www.example.org/hilfe", 5)
    doc.followLink(0, doc.linkPages["0"][0]["key"])
    assert files.URLS[-1] == "https://www.example.org/hilfe"
    doc.removeLink(0, doc.linkPages["0"][0]["key"])
    settle(h)
    assert wait_until(lambda: not doc.linkPages.get("0"), 5)


def test_bookmarks_are_added_renamed_and_moved_from_the_panel(reader_app, tmp_path: Path, monkeypatch) -> None:
    h = reader_app
    path = samples.standard_text(tmp_path / "Kapitel.pdf", pages=3)
    doc = open_pdf(h, path)
    titles = iter(["Einleitung", "Anhang", "Schluss"])
    answers(monkeypatch, h, {"text_input": lambda data: ("primary", {"value": next(titles)})})
    doc.addBookmark("", False)
    settle(h)
    assert wait_until(lambda: doc.hasOutline, 5)
    assert reader(h).leftPanel == "outline"
    doc.goTo(2)
    settle(h)
    doc.addBookmark("0", False)
    settle(h)
    assert wait_until(lambda: [entry["title"] for entry in doc.outline.items()] == ["Einleitung", "Anhang"], 5)
    doc.renameBookmark("1")
    settle(h)
    doc.moveBookmark("1", "up")
    settle(h)
    assert wait_until(lambda: [(entry["title"], entry["page"]) for entry in doc.outline.items()] == [("Schluss", 2), ("Einleitung", 0)], 5)
    right_click(h, center(h.item("readerOutline")))  # Kontextmenü eines Eintrags (oder der leeren Fläche) ohne Fehler
    key(h, Qt.Key.Key_Escape)
    doc.saveDocument()
    settle(h)
    with pikepdf.open(path) as saved:
        assert str(saved.Root.Outlines.First.Title) == "Schluss"


# --- Dialoge: jeder neue Inhalt erscheint wirklich (ohne QML-Meldungen) und liefert seine Werte ---------------------
def test_new_dialogs_render_and_collect(reader_app, tmp_path: Path, monkeypatch) -> None:
    from qtapp import dialogs

    h = reader_app
    open_pdf(h, samples.standard_text(tmp_path / "Dialoge.pdf", pages=4))
    monkeypatch.setattr(dialogs, "AUTO_ANSWER", None)  # Dialoge wirklich zeigen (nicht blockierend)
    items = [{"key": "metadata", "label": "Metadaten", "detail": "Titel, Autor", "count": 3, "checked": True}, {"key": "comments", "label": "Kommentare", "detail": "", "count": 0, "checked": True}]
    cases = [
        ("checklist", "checklistContent", {"items": items}, True),
        ("protect", "protectContent", {"protected": False, "restricted": False, "rights": {}, "changeable": True}, False),  # Kennwort fehlt noch
        ("optimize", "optimizeContent", {"size": "1,2 MB", "name": "Dialoge.pdf"}, True),
        ("header_footer", "headerFooterContent", {"pageCount": 4, "existing": 0, "name": "Dialoge"}, True),
        ("watermark", "watermarkContent", {"pageCount": 4, "existing": 2}, True),
        ("redact_search", "redactSearchContent", {"current": 0, "pageCount": 4}, False),
        ("signature", "signatureContent", {"stored": 0, "limit": 6}, False),
        ("link", "linkContent", {"kind": "page", "page": 2, "uri": "", "pageCount": 4}, True),
        ("crop", "cropContent", {"auto": [12.5, 10, 12.5, 20], "selected": 0, "current": 0, "pageCount": 4}, False),
    ]
    for kind, name, data, acceptable in cases:
        h.app.dialogs.show(kind, "Prüfung", data)
        assert wait_until(lambda: h.item(name) is not None and h.item(name).isVisible(), 5), name
        pump(0.2)
        content = h.item(name)
        assert content.property("acceptable") in (acceptable, None), (name, content.property("acceptable"))
        h.app.dialogs.shutdown()
        assert wait_until(lambda: not h.app.dialogs.open, 3)
        pump(0.3)
    # Zuschneiden: »An den Inhalt anpassen« übernimmt die erkannten Ränder
    h.app.dialogs.show("crop", "Zuschneiden", cases[-1][2])
    assert wait_until(lambda: h.item("cropAuto") is not None and h.item("cropAuto").isVisible(), 5)
    click(h, center(h.item("cropAuto")))
    assert h.item("cropBottom").property("text") == "20" and h.item("cropContent").property("acceptable") is True
    h.app.dialogs.shutdown()
    pump(0.3)
