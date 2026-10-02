"""PDF Reader/Editor – Kern ohne Oberfläche: Öffnen, Darstellung, Text, Suche, Gliederung,
Rückgängig/Wiederholen, Speichern (atomar, geprüft) und Sitzungssicherung."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pikepdf
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, outline, recovery, render, save, textlayer
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import DamagedDocument, ExternalChange, NotAPdf, PasswordRequired, ReadOnlyDocument, SaveFailed
from tools.pdf_editor.geometry import PageGeometry


# --- Öffnen --------------------------------------------------------------------------------------
def test_open_reads_pages_sizes_and_does_not_keep_the_file_open(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "a.pdf", pages=3)
    doc = EditorDocument.open(path)
    try:
        assert doc.page_count == 3 and doc.name == "a.pdf" and not doc.dirty and not doc.read_only
        geo = doc.geometry(0)
        assert (round(geo.width), round(geo.height)) == (595, 842)
        # nichts hält die Datei offen: sie lässt sich ersetzen und löschen
        os.replace(samples.standard_text(tmp_path / "b.pdf"), path)
        path.unlink()
    finally:
        doc.close()


def test_password_is_required_wrong_password_is_reported_and_right_one_opens(tmp_path: Path) -> None:
    path = samples.encrypted(tmp_path / "geheim.pdf")
    with pytest.raises(PasswordRequired) as missing:
        EditorDocument.open(path)
    assert not missing.value.wrong
    with pytest.raises(PasswordRequired) as wrong:
        EditorDocument.open(path, password="falsch")
    assert wrong.value.wrong
    doc = EditorDocument.open(path, password="geheim")
    try:
        assert doc.encrypted and doc.page_count == 1
    finally:
        doc.close()


def test_restrictions_of_the_file_are_respected(tmp_path: Path) -> None:
    path = samples.encrypted(tmp_path / "gesperrt.pdf", allow_edit=False)
    doc = EditorDocument.open(path, password="geheim")
    try:
        assert doc.read_only and "nicht erlaubt" in doc.read_only_reason
        with pytest.raises(ReadOnlyDocument):
            doc.ensure_editable()
    finally:
        doc.close()
    owner = EditorDocument.open(path, password="besitzer")  # mit Besitzerpasswort: alles erlaubt
    try:
        assert not owner.read_only
    finally:
        owner.close()


def test_damaged_and_foreign_files_are_reported(tmp_path: Path) -> None:
    with pytest.raises(DamagedDocument):
        EditorDocument.open(samples.damaged(tmp_path / "kaputt.pdf"))
    (tmp_path / "text.pdf").write_text("kein PDF", encoding="utf-8")
    with pytest.raises(NotAPdf):
        EditorDocument.open(tmp_path / "text.pdf")


def test_signatures_javascript_and_structure_are_detected(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.signed(tmp_path / "signiert.pdf"))
    try:
        assert doc.report.signed == 1
    finally:
        doc.close()


# --- Geometrie und Darstellung ---------------------------------------------------------------------
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_geometry_matches_pdfium(rotation: int) -> None:
    import ctypes

    import pypdfium2 as pdfium
    import pypdfium2.raw as r

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(400, 600))
    pdf.pages[0].Rotate = rotation
    pdf.pages[0].CropBox = pikepdf.Array([20, 30, 380, 570])
    buf = io.BytesIO()
    pdf.save(buf)
    view = pdfium.PdfDocument(buf.getvalue())
    page = view[0]
    w, h = page.get_size()
    geo = PageGeometry((20.0, 30.0, 380.0, 570.0), rotation)
    assert (round(geo.width), round(geo.height)) == (round(w), round(h))
    for x, y in ((25.0, 40.0), (300.0, 500.0), (200.0, 300.0)):
        dx, dy = ctypes.c_int(), ctypes.c_int()
        r.FPDF_PageToDevice(page.raw, 0, 0, round(w), round(h), 0, x, y, dx, dy)
        u, v = geo.to_view(x, y)
        assert abs(u - dx.value) <= 1 and abs(v - dy.value) <= 1
        assert all(abs(a - b) < 1e-6 for a, b in zip(geo.to_page(u, v), (x, y)))
    page.close()
    view.close()


def test_render_page_and_region_respect_limits(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.rotated(tmp_path / "gedreht.pdf"))
    try:
        upright = render.render_page(doc, 0, 300)
        assert upright.width == 300 and abs(upright.height - 300 * 842 / 595) <= 1
        landscape = render.render_page(doc, 1, 300)  # 90° gedreht → quer
        assert landscape.width > landscape.height
        huge = render.render_page(doc, 0, 100_000)
        assert huge.width * huge.height <= render.MAX_PIXELS * 1.01
        region = render.render_region(doc, 0, (0, 0, 100, 50), 4.0)
        assert (region.width, region.height) == (400, 200)
        image = render.to_pil(render.render_page(doc, 0, 200))
        assert image.getpixel((5, 5)) == (255, 255, 255)
    finally:
        doc.close()


# --- Text, Suche, Gliederung ------------------------------------------------------------------------
def test_text_selection_copy_word_and_search(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "t.pdf", pages=2))
    try:
        full = textlayer.text(doc, 0)
        assert "Rechnung Nr. 4711" in full and "\r" not in full
        index = textlayer.index_at(doc, 0, 80, 765)
        assert index >= 0
        start, count = textlayer.word_at(doc, 0, index)
        assert textlayer.text(doc, 0, start, count) == "Rechnung"
        sel = textlayer.selection(doc, 0, index, index + 11)
        assert textlayer.text(doc, 0, *sel).startswith("Rechnung Nr")
        assert textlayer.rects(doc, 0, *sel)
        hits = textlayer.search(doc, 0, "rechnung")
        assert len(hits) == 1 and hits[0].rects
        assert textlayer.search(doc, 0, "rechnung", match_case=True) == []
        assert len(textlayer.search(doc, 0, "Nr", whole_word=True)) == 1
        assert textlayer.search(doc, 0, "Nr.", whole_word=False)
    finally:
        doc.close()


def test_outline_lists_bookmarks_with_targets(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    try:
        entries = outline.read_outline(doc)
        assert [(e.level, e.title, e.page) for e in entries] == [(0, "Kapitel 1", 0), (1, "Abschnitt 1.1", 1), (0, "Kapitel 2", 2)]
    finally:
        doc.close()


def test_search_over_many_pages_is_fast_enough(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.big(tmp_path / "gross.pdf", pages=500))
    try:
        start = time.perf_counter()
        hits = [hit for page in range(doc.page_count) for hit in textlayer.search(doc, page, "SuchwortTreffer")]
        took = time.perf_counter() - start
        assert [hit.page for hit in hits] == [7 + 50 * n for n in range(10)]
        assert took < 30, f"Suche über 500 Seiten dauerte {took:.1f} s"
        assert len(doc._textpages) <= 24  # begrenzter Zwischenspeicher
    finally:
        doc.close()


# --- Rückgängig/Wiederholen ------------------------------------------------------------------------
def test_commands_restore_page_entries_and_order(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "c.pdf", pages=3))
    history = commands.History()
    try:
        before = [p.obj.objgen for p in doc.pdf.pages]
        with commands.record(doc, history, "Seite drehen", pages=(1,)) as rec:
            obj = rec.page(1)
            obj.Rotate = 90
        assert doc.geometry(1).rotation == 90 and doc.dirty
        with commands.record(doc, history, "Seiten sortieren") as rec:
            rec.page_order()
            first = doc.pdf.pages[0].obj
            del doc.pdf.pages[0]
            doc.pdf.pages.append(pikepdf.Page(first))
        assert [p.obj.objgen for p in doc.pdf.pages] == before[1:] + before[:1]
        assert history.undo_title == "Seiten sortieren"
        history.undo(doc)
        assert [p.obj.objgen for p in doc.pdf.pages] == before
        history.undo(doc)
        assert doc.geometry(1).rotation == 0 and int(doc.pdf.pages[1].obj.get("/Rotate", 0)) == 0
        history.redo(doc)
        assert doc.geometry(1).rotation == 90
        assert history.can_redo and history.redo_title == "Seiten sortieren"
    finally:
        doc.close()


def test_failed_command_is_rolled_back_and_not_recorded(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.standard_text(tmp_path / "f.pdf"))
    history = commands.History()
    try:
        with pytest.raises(RuntimeError):
            with commands.record(doc, history, "Fehler") as rec:
                obj = rec.page(0)
                obj.Rotate = 180
                raise RuntimeError("abbrechen")
        assert doc.geometry(0).rotation == 0 and not history.can_undo
    finally:
        doc.close()


def test_history_is_limited() -> None:
    history = commands.History(limit=3)
    for n in range(5):
        history.push(commands.Command(str(n), commands.Snapshot(), commands.Snapshot()))
    assert history.undo_title == "4" and len(history._done) == 3


# --- Speichern -------------------------------------------------------------------------------------
def test_save_overwrites_atomically_keeps_structure_and_backs_up(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "struktur.pdf")
    original = path.read_bytes()
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        with commands.record(doc, history, "drehen") as rec:
            rec.page(0).Rotate = 90
        result = save.save(doc, path, backup_dir=tmp_path / "sicherung")
        assert result.path == path and not doc.dirty and result.checked_pages == 3
        assert result.backup is not None and result.backup.read_bytes() == original
        again = pikepdf.open(path)
        assert int(again.pages[0].Rotate) == 90
        assert save.structure_of(again).differences(save.structure_of(pikepdf.open(io.BytesIO(original)))) == []
        again.close()
        assert not list(tmp_path.glob(".*.tmp"))
    finally:
        doc.close()


def test_save_refuses_when_the_file_changed_outside(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "x.pdf")
    doc = EditorDocument.open(path)
    try:
        time.sleep(0.01)
        samples.standard_text(path, pages=2)  # anderes Programm schreibt die Datei
        with pytest.raises(ExternalChange):
            save.save(doc, path)
        assert pikepdf.open(path).pages.__len__() == 2  # nicht überschrieben
        save.save(doc, tmp_path / "kopie.pdf")  # »Speichern unter« geht
    finally:
        doc.close()


def test_failed_validation_leaves_the_original_untouched(tmp_path: Path, monkeypatch) -> None:
    path = samples.standard_text(tmp_path / "o.pdf")
    original = path.read_bytes()
    doc = EditorDocument.open(path)
    try:
        def broken(*_args, **_kwargs):
            raise SaveFailed("Prüfung fehlgeschlagen")

        monkeypatch.setattr(save, "validate", broken)
        with pytest.raises(SaveFailed):
            save.save(doc, path)
        assert path.read_bytes() == original and not list(tmp_path.glob(".*.tmp"))
    finally:
        doc.close()


def test_failed_write_leaves_the_original_untouched(tmp_path: Path, monkeypatch) -> None:
    path = samples.standard_text(tmp_path / "w.pdf")
    original = path.read_bytes()
    doc = EditorDocument.open(path)
    try:
        def no_replace(*_args, **_kwargs):
            raise PermissionError(13, "Zugriff verweigert")

        monkeypatch.setattr(save, "_replace", no_replace)
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
        # Art genau bestimmt (test_editor_save.py): unter Windows entscheidet die Probe mit Löschrecht
        assert error.value.kind in ("FILE_LOCKED", "DIRECTORY_NOT_WRITABLE") and error.value.save_as and error.value.phase == "replace"
        assert path.read_bytes() == original and not list(tmp_path.glob(".*.tmp")) and doc.dirty is False
    finally:
        doc.close()


def test_encryption_is_kept_on_save(tmp_path: Path) -> None:
    path = samples.encrypted(tmp_path / "e.pdf")
    doc = EditorDocument.open(path, password="geheim")
    try:
        save.save(doc, tmp_path / "e2.pdf")
    finally:
        doc.close()
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(tmp_path / "e2.pdf")
    reopened = pikepdf.open(tmp_path / "e2.pdf", password="besitzer")  # Besitzerpasswort unverändert
    assert reopened.is_encrypted
    reopened.close()


def test_backup_of_an_old_file_is_kept_after_startup_cleanup(tmp_path: Path) -> None:
    """Die Sicherung zählt ab dem Zeitpunkt der Sicherung – nicht ab dem Alter der Originaldatei
    (eine seit Monaten unveränderte PDF darf ihre Sicherung beim nächsten Start nicht verlieren)."""
    path = samples.standard_text(tmp_path / "alt.pdf")
    old = time.time() - 90 * 24 * 3600
    os.utime(path, (old, old))
    folder = tmp_path / "sicherungen"
    doc = EditorDocument.open(path)
    result = save.save(doc, path, backup_dir=folder)
    doc.close()
    assert result.backup is not None and result.backup.exists()
    assert save.cleanup_backups(folder) == 0
    assert result.backup.exists()


def test_backups_are_limited_and_cleaned(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "b.pdf")
    folder = tmp_path / "sicherung"
    for _ in range(5):
        doc = EditorDocument.open(path)
        save.save(doc, path, backup_dir=folder)
        doc.close()
        time.sleep(1.01)  # Sekunden im Namen
    assert len(list(folder.glob("*.pdf"))) == save.BACKUPS_PER_FILE
    assert save.cleanup_backups(folder, now=time.time() + save.BACKUP_MAX_AGE + 10) == save.BACKUPS_PER_FILE


# --- Sitzungssicherung -------------------------------------------------------------------------------
def test_recovery_session_survives_a_crash_and_is_cleaned_after_close(tmp_path: Path) -> None:
    root = tmp_path / "editor"
    session = recovery.RecoverySession("a.pdf", tmp_path / "a.pdf", encrypted=False, root=root)
    session.write(b"%PDF-1.7 stand 1")
    assert recovery.orphaned_sessions(root) == []  # Sitzung lebt (Sperre gehalten)
    session._lock.release()  # wie ein Absturz: Sperre frei, Ordner bleibt
    found = recovery.orphaned_sessions(root)
    assert [info.name for info in found] == ["a.pdf"] and recovery.read_session(found[0]) == b"%PDF-1.7 stand 1"
    recovery.discard_session(found[0])
    assert recovery.orphaned_sessions(root) == []
    second = recovery.RecoverySession("b.pdf", None, encrypted=False, root=root)
    second.write(b"%PDF-1.7")
    second.discard()
    assert not (root / recovery.SESSIONS).exists() or not any((root / recovery.SESSIONS).iterdir())
