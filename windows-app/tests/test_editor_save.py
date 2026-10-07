"""Speichern im PDF Editor: sicher, nachvollziehbar – und ohne lxml.

Ursache des Fehlers »Das Dokument konnte nicht geschrieben werden.« in 3.0.0-beta.1: pikepdf trägt
beim Schreiben standardmäßig die PDF-Version in die XMP-Metadaten ein und braucht dafür lxml – das
die Laufzeit der App nicht mitliefert. Im installierten Programm ließ sich deshalb kein PDF mit
XMP-Metadaten speichern (die meisten echten PDFs haben welche); die Sitzungssicherung scheiterte
still, »Eigenschaften« meldete beschädigtes XMP. Alle Tests hier laufen ohne lxml (Fixture).

Außerdem: jede Fehlerart mit verständlichem Text und »Speichern unter«, das Original bleibt
unverändert, keine temporären Dateien, das Dokument bleibt ungespeichert (Rückgängig möglich), die
gespeicherte Datei wird nachgeprüft.
"""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pikepdf
import pypdfium2
import pytest

import editorsamples as samples
from tools.pdf_editor import commands, errors, metadata, pages, save, textedit, xmp
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import DamagedDocument, SaveFailed

APP_DIR = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def no_lxml(monkeypatch):
    """Wie die Laufzeit der App: lxml ist nicht vorhanden."""
    monkeypatch.setitem(sys.modules, "lxml", None)
    monkeypatch.setitem(sys.modules, "lxml.etree", None)


def edited(path: Path) -> tuple[EditorDocument, commands.History]:
    """Öffnen und die Rechnungsnummer direkt im PDF ändern (wie »Text bearbeiten«)."""
    doc = EditorDocument.open(path)
    history = commands.History()
    block = next(b for b in textedit.analyze(doc, 0) if "4711" in b.text)
    textedit.edit_block(doc, history, block, block.text.replace("4711", "4712"))
    assert doc.dirty
    return doc, history


def page_text(path: Path, index: int = 0) -> str:
    view = pypdfium2.PdfDocument(str(path))
    try:
        return view[index].get_textpage().get_text_range()
    finally:
        view.close()


def temp_files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def assert_untouched(doc: EditorDocument, history: commands.History, path: Path, original: bytes) -> None:
    """Fehlgeschlagenes Speichern: Original gleich, keine temporäre Datei, weiter ungespeichert,
    Rückgängig unverändert möglich."""
    assert path.read_bytes() == original
    assert temp_files(path.parent) == []
    assert doc.dirty and history.undo_title


# --- Ursache: XMP-Metadaten ohne lxml ---------------------------------------------------------------------------
def test_pdf_with_xmp_saves_edits_metadata_recovery_and_extract_without_lxml(tmp_path: Path) -> None:
    path = samples.with_xmp(tmp_path / "Rechnung mit XMP.pdf")
    doc, history = edited(path)
    try:
        result = save.save(doc, path, backup_dir=tmp_path / "sicherungen")  # Strg+S: Original ersetzen
        assert result.backup is not None and not doc.dirty
        assert doc.serialize(keep_encryption=True)  # Sitzungssicherung
        metadata.update(doc, history, title="Neuer Titel", author="Erika Muster", subject="", keywords="Rechnung")
        save.save(doc, path, backup_dir=tmp_path / "sicherungen")
        pages.extract(doc, [0], tmp_path / "Auszug.pdf")
    finally:
        doc.close()
    assert "lxml" not in [name for name, module in sys.modules.items() if module is not None and name.startswith("lxml")]
    text = page_text(path)
    assert "4712" in text and "4711" not in text
    with pikepdf.open(path) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Neuer Titel" and len(pdf.pages) == 1
        packet = pdf.Root.Metadata.read_bytes()
    assert xmp.read(packet) == {"title": "Neuer Titel", "author": "Erika Muster", "keywords": "Rechnung"}
    assert b"Textverarbeitung 365" in packet  # übrige XMP-Eigenschaften bleiben
    assert (tmp_path / "Auszug.pdf").is_file()


def test_installed_runtime_conditions_in_a_fresh_process(tmp_path: Path) -> None:
    """Eigener Prozess, in dem lxml nie geladen werden kann – wie die installierte App."""
    path = samples.with_xmp(tmp_path / "Rechnung.pdf")
    code = textwrap.dedent("""
        import sys
        sys.modules["lxml"] = None
        sys.path.insert(0, sys.argv[1])
        from pathlib import Path
        from tools.pdf_editor import commands, save, textedit
        from tools.pdf_editor.document import EditorDocument
        doc = EditorDocument.open(sys.argv[2])
        block = next(b for b in textedit.analyze(doc, 0) if "4711" in b.text)
        textedit.edit_block(doc, commands.History(), block, block.text.replace("4711", "4712"))
        save.save(doc, Path(sys.argv[2]), backup_dir=Path(sys.argv[3]))
        doc.close()
        print("gespeichert")
    """)
    run = subprocess.run([sys.executable, "-c", code, str(APP_DIR), str(path), str(tmp_path / "sicherungen")], capture_output=True, text=True, timeout=180)
    assert run.returncode == 0 and run.stdout.split() == ["gespeichert"], run.stderr[-3000:]
    assert "4712" in page_text(path)


def test_no_app_code_uses_pikepdf_metadata_that_needs_lxml() -> None:
    """``open_metadata`` braucht lxml; jedes Schreiben des Editors setzt ``fix_metadata_version=False``."""
    found = []
    for file in sorted(APP_DIR.rglob("*.py")):
        for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "open_metadata(" in code:
                found.append(f"{file.relative_to(APP_DIR)}:{number}")
    assert found == []
    editor = APP_DIR / "tools" / "pdf_editor"
    writes = [line for file in ("document.py", "pages.py") for line in (editor / file).read_text(encoding="utf-8").splitlines() if ".save(buffer" in line]
    assert len(writes) == 4 and all("fix_metadata_version=False" in line for line in writes)


def test_xmp_sync_keeps_the_packet_and_refuses_unsafe_or_broken_xmp() -> None:
    from datetime import datetime, timezone

    packet = samples.XMP_PACKET.encode("utf-8")
    now = datetime(2026, 10, 2, 9, 30, tzinfo=timezone.utc)
    out = xmp.sync(packet, {"title": "T", "author": "", "subject": "S", "keywords": None}, now)
    assert out.startswith(b"<?xpacket begin=") and out.rstrip().endswith(b'<?xpacket end="w"?>')
    assert xmp.read(out) == {"title": "T", "subject": "S"}
    assert b'xmp:ModifyDate="2026-10-02T09:30:00+00:00"' in out and b"<xmp:MetadataDate>2026-10-02T09:30:00+00:00</xmp:MetadataDate>" in out
    assert b"pdf:Producer=\"Textverarbeitung 365\"" in out and b"<dc:format>application/pdf</dc:format>" in out
    for bad in (b"<x:xmpmeta", b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', b"<x/>"):
        with pytest.raises(xmp.XmpError):
            xmp.sync(bad, {"title": "x"}, now)


def test_broken_xmp_keeps_metadata_unchanged_and_saving_still_works(tmp_path: Path) -> None:
    path = samples.standard_text(tmp_path / "kaputt-xmp.pdf")
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        pdf.Root.Metadata = pdf.make_stream(b"<x:xmpmeta kaputt")
        pdf.save(path, fix_metadata_version=False)
    doc, history = edited(path)
    try:
        with pytest.raises(errors.EditorError, match="XMP"):
            metadata.update(doc, history, title="Neu")
        assert history.undo_title != "Eigenschaften ändern"  # nichts halb geändert
        save.save(doc, path)
    finally:
        doc.close()
    assert "4712" in page_text(path)


# --- D: Original bleibt bei jedem Fehler unverändert ------------------------------------------------------------
@pytest.mark.parametrize("phase", ["serialize", "validate", "temp_write", "temp_verify", "backup", "replace"])
def test_any_failing_step_keeps_the_original_and_the_unsaved_state(tmp_path: Path, monkeypatch, phase: str) -> None:
    path = samples.with_xmp(tmp_path / "o.pdf")
    original = path.read_bytes()
    doc, history = edited(path)
    try:
        def fail(*_args, **_kwargs):
            raise {
                "serialize": pikepdf.PdfError("qpdf: kaputt"),
                "temp_write": OSError(errno.ENOSPC, "Kein Speicherplatz"),
                "temp_verify": OSError(errno.EIO, "Lesefehler"),
                "backup": OSError(errno.EIO, "Lesefehler"),
                "replace": OSError(errno.EIO, "Ein-/Ausgabefehler"),
            }.get(phase) or SaveFailed("Prüfung fehlgeschlagen. Die Originaldatei ist unverändert.", kind=errors.VALIDATION_FAILED, phase="validate")

        target = {"serialize": (doc, "serialize"), "validate": (save, "validate"), "temp_write": (os, "fsync"), "temp_verify": (Path, "read_bytes"), "backup": (save.shutil, "copyfile"), "replace": (save, "_replace")}[phase]
        with monkeypatch.context() as patch:  # nur dieser Fehler – »ohne lxml« bleibt bestehen
            patch.setattr(*target, fail)
            with pytest.raises(SaveFailed) as error:
                save.save(doc, path, backup_dir=tmp_path / "sicherungen")
        expected = {"serialize": errors.SERIALIZE_FAILED, "validate": errors.VALIDATION_FAILED, "temp_write": errors.TEMP_WRITE_FAILED, "temp_verify": errors.TEMP_WRITE_FAILED, "backup": errors.BACKUP_FAILED, "replace": errors.REPLACE_FAILED}[phase]
        assert error.value.kind == expected and error.value.phase.startswith(phase.split("_")[0])
        assert "unverändert" in str(error.value)
        assert_untouched(doc, history, path, original)
        if phase == "temp_write":
            assert "Speicherplatz" in str(error.value) and error.value.errno == errno.ENOSPC
        # Danach klappt es (Ursache behoben) – nichts ist hängen geblieben
        save.save(doc, path, backup_dir=tmp_path / "sicherungen")
        assert not doc.dirty and "4712" in page_text(path)
    finally:
        doc.close()


def test_log_text_has_kind_step_component_and_codes_but_no_path(tmp_path: Path) -> None:
    secret = tmp_path / "Kunde Mustermann GmbH"
    secret.mkdir()
    path = samples.with_xmp(secret / "Vertrag Mustermann.pdf")
    os.chmod(path, stat.S_IREAD)
    doc, _history = edited(path)
    try:
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
    finally:
        doc.close()
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    line = error.value.log_text()
    assert "Art=TARGET_READ_ONLY" in line and "Schritt=preflight" in line and "Komponente=Dateisystem" in line
    assert "Mustermann" not in line and str(tmp_path) not in line


# --- E: schreibgeschützte Datei ---------------------------------------------------------------------------------
def test_read_only_file_is_reported_and_save_as_works(tmp_path: Path) -> None:
    path = samples.with_xmp(tmp_path / "schreibgeschützt.pdf")
    os.chmod(path, stat.S_IREAD)
    original = path.read_bytes()
    doc, history = edited(path)
    try:
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
        assert error.value.kind == errors.TARGET_READ_ONLY and error.value.save_as
        assert str(error.value) == "Die Datei ist schreibgeschützt. Verwenden Sie »Speichern unter«, um eine bearbeitete Kopie zu erstellen."
        assert_untouched(doc, history, path, original)
        copy = tmp_path / "Kopie.pdf"
        save.save(doc, copy)  # »Speichern unter« ist vom Original unabhängig
        assert not doc.dirty and doc.path == copy and "4712" in page_text(copy)
    finally:
        doc.close()
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert path.read_bytes() == original


# --- F: Ordner ohne Schreibberechtigung -------------------------------------------------------------------------
def test_folder_without_write_permission_is_reported_before_any_work(tmp_path: Path, monkeypatch) -> None:
    path = samples.with_xmp(tmp_path / "ordner.pdf")
    original = path.read_bytes()
    doc, history = edited(path)
    serialized = []
    monkeypatch.setattr(doc, "serialize", lambda **kwargs: serialized.append(kwargs) or b"")

    def denied(file, mode="r", *args, **kwargs):
        if str(file).endswith(".tmp") and "x" in mode:
            raise PermissionError(errno.EACCES, "Zugriff verweigert")
        return open(file, mode, *args, **kwargs)

    monkeypatch.setattr(save, "open", denied, raising=False)
    try:
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
        assert error.value.kind == errors.DIRECTORY_NOT_WRITABLE and error.value.phase == "temp_create" and error.value.save_as
        assert str(error.value).startswith("PDF Tool hat keine Schreibberechtigung für diesen Speicherort.")
        assert serialized == []  # sofort gemeldet – ohne erst zu serialisieren
        assert_untouched(doc, history, path, original)
    finally:
        doc.close()


@pytest.mark.skipif(sys.platform != "win32", reason="echte Zugriffsrechte (ACL) nur unter Windows")
def test_folder_without_write_permission_on_windows(tmp_path: Path) -> None:
    folder = tmp_path / "gesperrt"
    folder.mkdir()
    path = samples.with_xmp(folder / "acl.pdf")
    original = path.read_bytes()
    doc, history = edited(path)
    # Nur Schreiben im Ordner verweigern: Dateien und Unterordner anlegen, darin löschen – lesen und auflisten
    # bleiben erlaubt (»W« enthielte auch SYNCHRONIZE und sperrte damit sogar das Auflisten)
    deny = subprocess.run(["icacls", str(folder), "/deny", "*S-1-1-0:(WD,AD,DC)"], capture_output=True, text=True)
    try:
        if deny.returncode != 0:
            pytest.skip(f"icacls: {deny.stdout} {deny.stderr}")
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
        assert error.value.kind == errors.DIRECTORY_NOT_WRITABLE and error.value.save_as
        assert_untouched(doc, history, path, original)
    finally:
        subprocess.run(["icacls", str(folder), "/remove:d", "*S-1-1-0"], capture_output=True)
        doc.close()


# --- G: von einem anderen Programm gesperrte Datei --------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "win32", reason="Dateisperren durch offene Handles gibt es nur unter Windows")
def test_file_opened_by_another_program_is_reported_as_locked_on_windows(tmp_path: Path) -> None:
    import winsys

    path = samples.with_xmp(tmp_path / "gesperrt.pdf")
    original = path.read_bytes()
    doc, history = edited(path)
    other = open(path, "rb")  # wie ein anderes Programm: offen ohne Freigabe zum Löschen
    try:
        assert winsys.replace_access(path) == "in_use"
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path)
        assert error.value.kind == errors.FILE_LOCKED and error.value.save_as
        assert str(error.value).startswith("Die Datei wird möglicherweise von einem anderen Programm verwendet.")
        assert error.value.winerror in (5, 32)
        other.close()
        assert_untouched(doc, history, path, original)
        assert winsys.replace_access(path) == "ok"
        save.save(doc, path)  # nach dem Schließen im anderen Programm: speichern geht
        assert not doc.dirty
    finally:
        other.close()
        doc.close()


def test_replace_problems_are_classified_not_guessed(tmp_path: Path, monkeypatch) -> None:
    path = samples.standard_text(tmp_path / "k.pdf")

    def error(code: int, winerror: int | None = None) -> OSError:
        exc = PermissionError(code, "Zugriff verweigert") if code in (errno.EACCES, errno.EPERM) else OSError(code, "Fehler")
        if winerror is not None:
            exc.winerror = winerror  # wie unter Windows (unter Linux nachgebildet)
        return exc

    assert save.replace_problem(error(errno.EACCES, 32), path) == errors.FILE_LOCKED  # Freigabeverletzung
    assert save.replace_problem(error(errno.EACCES, 33), path) == errors.FILE_LOCKED  # Sperrverletzung
    assert save.replace_problem(error(errno.EIO), path) == errors.REPLACE_FAILED
    assert save.replace_problem(error(errno.EROFS), path) == errors.DIRECTORY_NOT_WRITABLE
    os.chmod(path, stat.S_IREAD)
    try:
        assert save.replace_problem(error(errno.EACCES, 5), path) == errors.TARGET_READ_ONLY
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    # »Zugriff verweigert« unter Windows: die Probe mit Löschrecht entscheidet
    import winsys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(winsys, "replace_access", lambda _path: "in_use")
    assert save.replace_problem(error(errno.EACCES, 5), path) == errors.FILE_LOCKED
    monkeypatch.setattr(winsys, "replace_access", lambda _path: "denied")
    assert save.replace_problem(error(errno.EACCES, 5), path) == errors.DIRECTORY_NOT_WRITABLE


# --- Nachprüfung der gespeicherten Datei ------------------------------------------------------------------------
def test_saved_file_is_reopened_like_a_normal_open(tmp_path: Path, monkeypatch) -> None:
    path = samples.with_xmp(tmp_path / "nachpruefen.pdf", pages=3)
    doc, _history = edited(path)
    reopened = []
    real = EditorDocument.from_bytes

    def spy(data, **kwargs):
        reopened.append(kwargs.get("path"))
        return real(data, **kwargs)

    monkeypatch.setattr(EditorDocument, "from_bytes", staticmethod(spy))
    try:
        save.save(doc, path)
    finally:
        doc.close()
    assert reopened == [path]
    with pikepdf.open(path) as pdf:
        assert len(pdf.pages) == 3
    view = pypdfium2.PdfDocument(str(path))
    try:
        bitmap = view[0].render(scale=0.5)
        assert bitmap.to_pil().getextrema() != ((255, 255), (255, 255), (255, 255))  # bearbeitete Seite zeichnet
    finally:
        view.close()


def test_failed_reopen_keeps_the_document_unsaved_and_names_the_backup(tmp_path: Path, monkeypatch) -> None:
    path = samples.with_xmp(tmp_path / "wieder.pdf")
    doc, history = edited(path)

    def broken(_data, **_kwargs):
        raise DamagedDocument("qpdf: kaputt")

    monkeypatch.setattr(EditorDocument, "from_bytes", staticmethod(broken))
    try:
        with pytest.raises(SaveFailed) as error:
            save.save(doc, path, backup_dir=tmp_path / "sicherungen")
        assert error.value.kind == errors.REOPEN_FAILED and error.value.save_as
        backups = list((tmp_path / "sicherungen").glob("*.pdf"))
        assert len(backups) == 1 and str(backups[0]) in str(error.value)
        assert doc.dirty and history.undo_title and temp_files(tmp_path) == []
    finally:
        doc.close()


def test_temporary_file_lives_next_to_the_target(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "Ordner"
    folder.mkdir()
    path = samples.with_xmp(folder / "Dokument.pdf")
    doc, _history = edited(path)
    seen = []
    real = save._replace  # noqa: SLF001

    def spy(source, target):
        seen.append((Path(source).parent, Path(source).name))
        real(source, target)

    monkeypatch.setattr(save, "_replace", spy)
    try:
        save.save(doc, path)
    finally:
        doc.close()
    assert seen and seen[0][0] == path.parent and seen[0][1].startswith(".Dokument.pdftool-") and seen[0][1].endswith(".tmp")
    assert temp_files(path.parent) == []
