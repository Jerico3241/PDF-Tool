"""»Dateien reparieren« (5.0 Beta 7) für Office-Dateien, Bilder und Text/CSV – ohne Oberfläche.

LibreOffice wird ausgeschaltet (``office.available`` → ``False``), damit die Tests überall gleich laufen: Office-Dateien
werden dann nur neu verpackt; die Fälle mit LibreOffice prüft ``test_repair_with_libreoffice`` (übersprungen ohne).
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from tools.file_repair import engine
from tools.pdf_repair.models import Condition, Method, RepairMode, RepairStatus

DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    + "".join(f"<w:p><w:r><w:t>Absatz {n} mit Inhalt</w:t></w:r></w:p>" for n in range(1, 41))
    + "</w:body></w:document>"
)
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)


@pytest.fixture(autouse=True)
def without_office(monkeypatch):
    monkeypatch.setattr(engine, "_office_available", lambda: False)


def docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", CONTENT_TYPES)
        out.writestr("_rels/.rels", RELS)
        out.writestr("word/document.xml", DOCUMENT)
    return path


def repaired(path: Path, tmp_path: Path, mode: RepairMode = RepairMode.AUTO):
    analysis = engine.analyze(path)
    result = engine.repair(path, tmp_path / "arbeit", None, mode, analysis.sha256)
    return analysis, result


def test_handles_only_other_file_types() -> None:
    assert engine.handles("a.DOCX") and engine.handles("b.csv") and engine.handles("c.jpeg")
    assert not engine.handles("d.pdf") and not engine.handles("e.heic")


def test_healthy_docx_and_rebuild(tmp_path: Path) -> None:
    path = docx(tmp_path / "Brief.docx")
    analysis, result = repaired(path, tmp_path, RepairMode.REBUILD)
    assert analysis.condition is Condition.HEALTHY and analysis.repairable
    assert result.status is RepairStatus.REPAIRED and result.method is Method.ZIP_REBUILD
    with zipfile.ZipFile(result.output_path) as out:
        assert out.namelist()[0] == "[Content_Types].xml" and out.read("word/document.xml").decode() == DOCUMENT


def test_truncated_docx_keeps_readable_paragraphs(tmp_path: Path) -> None:
    path = docx(tmp_path / "Brief.docx")
    data = path.read_bytes()
    # Ohne Inhaltsverzeichnis und mitten im Dokument abgeschnitten
    cut = data.find(b"PK\x01\x02")
    path.write_bytes(data[: cut - 40])
    analysis, result = repaired(path, tmp_path)
    assert analysis.condition in (Condition.REPAIRABLE, Condition.DAMAGED)
    assert any("Inhaltsverzeichnis" in finding for finding in analysis.structural_errors)
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.output_path
    with zipfile.ZipFile(result.output_path) as out:
        assert out.testzip() is None
        text = out.read("word/document.xml").decode()
    assert "Absatz 1 mit Inhalt" in text and text.endswith("</w:body></w:document>")
    assert result.warnings


def test_broken_central_directory_only(tmp_path: Path) -> None:
    path = docx(tmp_path / "Liste.docx")
    data = bytearray(path.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    data[end:end + 4] = b"XXXX"  # Ende des Inhaltsverzeichnisses zerstört, alle Teile heil
    path.write_bytes(bytes(data))
    analysis, result = repaired(path, tmp_path)
    assert analysis.condition is Condition.REPAIRABLE
    assert result.status is RepairStatus.REPAIRED
    with zipfile.ZipFile(result.output_path) as out:
        assert out.read("word/document.xml").decode() == DOCUMENT


def test_odf_mimetype_stays_first_and_stored(tmp_path: Path) -> None:
    path = tmp_path / "Notiz.odt"
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        out.writestr("content.xml", "<office:document-content xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'><office:body/></office:document-content>", compress_type=zipfile.ZIP_DEFLATED)
    data = path.read_bytes()
    path.write_bytes(data[: data.find(b"PK\x01\x02")])  # Inhaltsverzeichnis fehlt
    _analysis, result = repaired(path, tmp_path)
    with zipfile.ZipFile(result.output_path) as out:
        first = out.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED


def test_garbage_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "Kaputt.xlsx"
    path.write_bytes(b"\x00" * 2000)
    analysis = engine.analyze(path)
    assert analysis.condition is Condition.UNREADABLE and not analysis.repairable and analysis.error
    empty = tmp_path / "Leer.pptx"
    empty.write_bytes(b"")
    assert engine.analyze(empty).condition is Condition.UNREADABLE


def test_truncated_jpeg_and_wrong_extension(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 160), (30, 120, 200)).save(buffer, "JPEG", quality=90)
    path = tmp_path / "Foto.jpg"
    path.write_bytes(buffer.getvalue()[: len(buffer.getvalue()) * 2 // 3])
    analysis, result = repaired(path, tmp_path)
    assert analysis.condition is Condition.DAMAGED
    assert result.status is RepairStatus.PARTIALLY_RECOVERED and result.method is Method.IMAGE_RESAVE
    with Image.open(result.output_path) as image:
        image.load()
        assert image.size == (200, 160) and image.format == "JPEG"
    png = tmp_path / "Logo.png"
    Image.new("RGB", (20, 20), (255, 0, 0)).save(png, "JPEG")  # eigentlich JPEG
    analysis, result = repaired(png, tmp_path)
    assert analysis.condition is Condition.REPAIRABLE and analysis.warnings
    with Image.open(result.output_path) as image:
        assert image.format == "PNG"
    healthy = tmp_path / "Gut.webp"
    Image.new("RGB", (20, 20)).save(healthy, "WEBP")
    assert engine.analyze(healthy).condition is Condition.HEALTHY
    (tmp_path / "Text.gif").write_bytes(b"kein Bild")
    assert engine.analyze(tmp_path / "Text.gif").condition is Condition.UNREADABLE


def test_text_and_csv_cleanup(tmp_path: Path) -> None:
    path = tmp_path / "Kunden.csv"
    path.write_bytes("Name;Ort\r\nMüller;Köln\r\n".encode("utf-8") + "Weiß;Straße\n".encode("cp1252") + b"Ende\x00\x00;X\r\n")
    analysis, result = repaired(path, tmp_path)
    assert analysis.condition is Condition.REPAIRABLE and len(analysis.structural_errors) == 2
    assert result.status is RepairStatus.REPAIRED and result.method is Method.TEXT_CLEANUP
    data = Path(result.output_path).read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")  # Excel erkennt UTF-8
    assert data[3:].decode("utf-8") == "Name;Ort\r\nMüller;Köln\r\nWeiß;Straße\r\nEnde;X\r\n"
    good = tmp_path / "Notiz.txt"
    good.write_text("Hallo\nWelt\n", encoding="utf-8")
    assert engine.analyze(good).condition is Condition.HEALTHY
    wide = tmp_path / "Export.txt"
    wide.write_bytes("Zeile äöü\r\n".encode("utf-16-le") * 5)  # UTF-16 ohne Kennung
    analysis, result = repaired(wide, tmp_path)
    assert analysis.condition is Condition.REPAIRABLE
    assert Path(result.output_path).read_bytes().decode("utf-8") == "Zeile äöü\r\n" * 5


def test_changed_since_analysis_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("eins", encoding="utf-8")
    analysis = engine.analyze(path)
    path.write_text("zwei", encoding="utf-8")
    result = engine.repair(path, tmp_path / "arbeit", None, RepairMode.AUTO, analysis.sha256)
    assert result.status is RepairStatus.FAILED and "verändert" in result.error


def test_legacy_without_office(tmp_path: Path) -> None:
    path = tmp_path / "Alt.doc"
    path.write_bytes(engine.OLE_MAGIC + b"\x00" * 600)
    analysis = engine.analyze(path)
    assert analysis.condition is Condition.HEALTHY and analysis.error == engine.NO_OFFICE
    result = engine.repair(path, tmp_path / "arbeit")
    assert result.status is RepairStatus.FAILED and result.error == engine.NO_OFFICE


def _office() -> bool:
    from tools.pdf_editor import office

    return office.libreoffice() is not None


@pytest.mark.skipif(not _office(), reason="LibreOffice fehlt")
def test_repair_with_libreoffice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(engine, "_office_available", _office)
    path = docx(tmp_path / "Brief.docx")
    data = path.read_bytes()
    path.write_bytes(data[: data.find(b"PK\x01\x02") - 40])
    _analysis, result = repaired(path, tmp_path)
    assert result.method is Method.OFFICE_RESAVE and result.status is RepairStatus.PARTIALLY_RECOVERED
    with zipfile.ZipFile(result.output_path) as out:
        assert "Absatz 1 mit Inhalt" in out.read("word/document.xml").decode()


def test_batch_knows_the_same_file_types() -> None:
    from tools.pdf_repair import batch

    assert set(batch.SUPPORTED) == {".pdf", *engine.SUFFIXES}
    assert batch.numbered("Brief_repariert", 1, ".docx") == "Brief_repariert (1).docx"
    assert batch.strip_pdf("Brief.docx", ".docx") == "Brief" and batch.output_suffix(Path("A.JPG")) == ".jpg"
