"""PDF Editor – Eigenschaften und Metadaten (lesen, ändern, Info und XMP übereinstimmend) sowie
Seiten als Bild exportieren (PNG/JPEG, Auflösung, nie überschreiben, Berechtigungen)."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from PIL import Image

import editorsamples as samples
from tools.pdf_editor import commands, export, metadata, save
from tools.pdf_editor.document import EditorDocument
from tools.pdf_editor.errors import ReadOnlyDocument


def test_properties_report_structure_fonts_and_security(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.structured(tmp_path / "s.pdf"))
    try:
        props = metadata.read(doc)
        assert (props.file_name, props.pages, props.page_size, props.title) == ("s.pdf", 3, "210 × 297 mm (A4)", "Strukturtest")
        assert props.size_bytes > 0 and props.pdf_version.startswith("1.")
        assert ("Helvetica", "Type 1", False) in props.fonts and ("Times-Roman", "Type 1", False) in props.fonts
        assert props.attachments == 1 and props.layers and not props.encrypted and props.restrictions == []
    finally:
        doc.close()
    doc = EditorDocument.open(samples.subset_font(tmp_path / "t.pdf"))
    try:
        assert any(embedded for _name, _kind, embedded in metadata.read(doc).fonts)
    finally:
        doc.close()
    doc = EditorDocument.open(samples.encrypted(tmp_path / "e.pdf", allow_edit=False), password="geheim")
    try:
        props = metadata.read(doc)
        assert props.encrypted and "AES" in props.encryption and "Bearbeiten" in props.restrictions
    finally:
        doc.close()
    doc = EditorDocument.open(samples.form(tmp_path / "f.pdf"))
    try:
        assert metadata.read(doc).form == "AcroForm"
    finally:
        doc.close()


def test_page_size_text() -> None:
    assert metadata.page_size_text(595.28, 841.89) == "210 × 297 mm (A4)"
    assert metadata.page_size_text(841.89, 595.28) == "297 × 210 mm (A4 Querformat)"
    assert metadata.page_size_text(612, 792) == "216 × 279 mm (Letter)"
    assert metadata.page_size_text(300, 300) == "106 × 106 mm"


def test_update_metadata_keeps_info_and_xmp_in_sync_and_undoes(tmp_path: Path) -> None:
    path = samples.structured(tmp_path / "s.pdf")
    doc = EditorDocument.open(path)
    history = commands.History()
    try:
        original = metadata.read(doc)
        metadata.update(doc, history, title="Neuer Titel", author="Erika Muster", keywords="Vertrag, 2026")
        props = metadata.read(doc)
        assert (props.title, props.author, props.keywords) == ("Neuer Titel", "Erika Muster", "Vertrag, 2026")
        with doc.pdf.open_metadata() as meta:
            assert meta.get("dc:title") == "Neuer Titel" and meta.get("pdf:Keywords") == "Vertrag, 2026"
        history.undo(doc)
        assert (metadata.read(doc).title, metadata.read(doc).author) == (original.title, original.author)
        with doc.pdf.open_metadata() as meta:
            assert meta.get("dc:title") == "Strukturtest"  # XMP wie vorher
        history.redo(doc)
        metadata.update(doc, history, author="")
        save.save(doc, path)
    finally:
        doc.close()
    with pikepdf.open(path) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Neuer Titel" and "/Author" not in pdf.docinfo


def test_export_pages_as_png_and_jpeg(tmp_path: Path) -> None:
    doc = EditorDocument.open(samples.rotated(tmp_path / "r.pdf"))
    out = tmp_path / "bilder"
    out.mkdir()
    try:
        calls = []
        written = export.export_pages(doc, [0, 1], out, "Vertrag", fmt="png", dpi=100, progress=lambda done, total: calls.append((done, total)))
        assert [p.name for p in written] == ["Vertrag_Seite1.png", "Vertrag_Seite2.png"] and calls == [(1, 2), (2, 2)]
        first, second = (Image.open(p) for p in written)
        assert abs(first.size[0] - 827) <= 1 and abs(first.size[1] - 1169) <= 1
        assert second.size[0] > second.size[1]  # Seite 2 ist gedreht (Querformat)
        assert round(first.info["dpi"][0]) == 100
        again = export.export_pages(doc, [0], out, "Vertrag", fmt="jpeg", dpi=72, quality=80)
        assert again[0].name == "Vertrag_Seite1.jpg" and Image.open(again[0]).format == "JPEG"
        third = export.export_pages(doc, [0], out, "Vertrag")
        assert third[0].name == "Vertrag_Seite1 (2).png"  # nie überschreiben
        assert not list(out.glob("*.tmp"))
    finally:
        doc.close()


def test_export_respects_permissions(tmp_path: Path) -> None:
    source = samples.standard_text(tmp_path / "offen.pdf")
    locked = tmp_path / "gesperrt.pdf"
    with pikepdf.open(source) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="geheim", owner="besitzer", R=6, allow=pikepdf.Permissions(extract=False)))
    doc = EditorDocument.open(locked, password="geheim")
    try:
        with pytest.raises(ReadOnlyDocument):
            export.export_pages(doc, [0], tmp_path, "x")
        assert not list(tmp_path.glob("x_*"))
    finally:
        doc.close()
