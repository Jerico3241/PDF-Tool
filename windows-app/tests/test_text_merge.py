"""Serienbrief und Kommentar-/Änderungslisten der Texte (seit 5.0 Beta 5) – ohne LibreOffice prüfbar."""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from qtapp.text import merge, review

CONTENT = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content xmlns:office="o" xmlns:text="t" xmlns:style="s" '
           'xmlns:fo="f"><office:automatic-styles><style:style style:name="T1" style:family="text"/></office:automatic-styles>'
           '<office:body><office:text><text:sequence-decls><text:sequence-decl text:name="Table"/></text:sequence-decls>'
           '<text:p>Sehr geehrte Frau «Name»,</text:p><text:p>Ihr Ort: <text:span text:style-name="T1">«Or</text:span>t»'
           ' &amp; «Unbekannt»</text:p></office:text></office:body></office:document-content>')


def _template(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        out.writestr("content.xml", CONTENT)
        out.writestr("styles.xml", "<x/>")
    return path


def test_read_table_csv_and_excel(tmp_path: Path) -> None:
    """CSV (Semikolon, Windows-Zeichensatz) und Excel: erste Zeile = Felder, leere Zeilen fallen weg, doppelte und
    leere Spaltennamen bekommen eigene Namen, Datum und Zahlen deutsch."""
    csv_file = tmp_path / "Empfänger.csv"
    csv_file.write_bytes("Name;Ort;Name\nMüller;Köln;X\n\n;;\nSchmidt;Bonn;Y\n".encode("cp1252"))
    columns, records = merge.read_table(str(csv_file))
    assert columns == ["Name", "Ort", "Name 2"]
    assert records == [{"Name": "Müller", "Ort": "Köln", "Name 2": "X"}, {"Name": "Schmidt", "Ort": "Bonn", "Name 2": "Y"}]

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name", None, "Betrag", "Seit"])
    sheet.append(["Weber", "a", 12.5, datetime(2026, 10, 1)])
    sheet.append(["Wolf", "b", 3.0, None])
    book.save(tmp_path / "Liste.xlsx")
    columns, records = merge.read_table(str(tmp_path / "Liste.xlsx"))
    assert columns == ["Name", "Spalte 2", "Betrag", "Seit"]
    assert records[0] == {"Name": "Weber", "Spalte 2": "a", "Betrag": "12,5", "Seit": "01.10.2026"}
    assert records[1]["Betrag"] == "3" and records[1]["Seit"] == ""


def test_read_table_errors(tmp_path: Path) -> None:
    (tmp_path / "leer.csv").write_text("\n\n", encoding="utf-8")
    with pytest.raises(merge.MergeError, match="leer"):
        merge.read_table(str(tmp_path / "leer.csv"))
    (tmp_path / "kopf.csv").write_text("Name;Ort\n", encoding="utf-8")
    with pytest.raises(merge.MergeError, match="keine Empfänger"):
        merge.read_table(str(tmp_path / "kopf.csv"))
    (tmp_path / "kaputt.xlsx").write_bytes(b"kein Excel")
    with pytest.raises(merge.MergeError, match="nicht lesen"):
        merge.read_table(str(tmp_path / "kaputt.xlsx"))


def test_merge_odt_one_letter_per_recipient(tmp_path: Path) -> None:
    """Ein Brief je Empfänger, ab dem zweiten mit Seitenumbruch; Felder auch dann ersetzt, wenn LibreOffice sie in
    Abschnitte geteilt hat; Sonderzeichen maskiert; Vorspann (Deklarationen) nur einmal; mimetype zuerst."""
    template = _template(tmp_path / "vorlage.odt")
    columns = ["Name", "Ort"]
    assert merge.fields_in(CONTENT, columns + ["Fehlt"]) == ["Name", "Ort"]
    records = [{"Name": "Müller", "Ort": "Köln"}, {"Name": "A & B <C>", "Ort": "Bonn"}]
    target = tmp_path / "serienbrief.odt"
    assert merge.merge_odt(str(template), records, columns, str(target)) == 2
    with zipfile.ZipFile(target) as result:
        assert result.namelist()[0] == "mimetype" and result.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        xml = result.read("content.xml").decode("utf-8")
    assert "Sehr geehrte Frau Müller," in xml and "Sehr geehrte Frau A &amp; B &lt;C&gt;," in xml
    assert 'Köln</text:span>' in xml and 'Bonn</text:span>' in xml and "«" + "Unbekannt»" in xml
    assert xml.count("<text:sequence-decls>") == 1
    assert xml.count(f'<text:p text:style-name="{merge.BREAK_STYLE}"/>') == 1
    assert f'style:name="{merge.BREAK_STYLE}"' in xml and 'fo:break-before="page"' in xml


def test_review_lists() -> None:
    """Kommentare nach Stelle mit Antworten darunter; Änderungen mit deutscher Art und dem geänderten Text."""
    data = {"comments": [
        {"id": "2", "parentId": "0", "author": "B", "text": "zweiter", "dateTime": "2026-10-28T10:49:58", "anchorPos": "100, 900, 10, 200",
         "textRange": "100, 900, 50, 200", "resolved": "false"},
        {"id": "1", "parentId": "0", "author": "A", "text": "erster", "dateTime": "2026-10-28T09:05:00", "anchorPos": "100, 300, 10, 200",
         "textRange": "100, 300, 50, 200", "resolved": "true"},
        {"id": "3", "parentId": "1", "author": "C", "text": "Antwort", "dateTime": "2026-10-28T11:00:00", "anchorPos": "100, 300, 10, 200"},
    ]}
    entries = review.comments(data)
    assert [entry["id"] for entry in entries] == ["1", "3", "2"]
    assert entries[0]["resolved"] and entries[1]["reply"] and not entries[2]["reply"]
    assert entries[0]["date"] == "28.10.2026, 09:05"
    changes = review.changes({"redlines": [
        {"index": "5", "type": "Delete", "author": "A", "dateTime": "2026-10-28T10:00:00", "description": "„jährliche“ löschen",
         "comment": "", "textRange": "200, 500, 40, 200"},
        {"index": "4", "type": "Insert", "author": "A", "dateTime": "2026-10-28T10:00:00", "description": "„halb“ einfügen",
         "comment": "", "textRange": "100, 500, 40, 200"},
    ]})
    assert [(change["index"], change["kind"], change["text"]) for change in changes] == [(4, "Eingefügt", "halb"), (5, "Gelöscht", "jährliche")]
    assert review.comments(None) == [] and review.changes({}) == []
