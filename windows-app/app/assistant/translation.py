"""Übersetzung als neues PDF (seit 4.0 Beta 6): je Seite des Originals eine Seite (oder mehr) mit dem übersetzten Text.

Das Layout des Originals wird nicht nachgebaut – die Übersetzung ist ein gut lesbarer Fließtext mit dem Hinweis, aus
welcher Datei und Seite er stammt, damit man im Original nachsehen kann. Schrift: Arial bzw. Segoe UI aus Windows
(alle Zeichen europäischer Sprachen), sonst Helvetica.
"""

from __future__ import annotations

import html
import os
import secrets
from pathlib import Path

MAX_PAGES = 300


def write_pdf(pages: list[str], target: str | os.PathLike, *, source_name: str, language: str) -> Path:
    """Übersetzte Seiten (``pages[i]`` gehört zur Seite ``i + 1``) als PDF nach ``target`` (neue Datei)."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    import pdffonts

    family = next((name for name in ("Arial", "Segoe UI", "Calibri") if pdffonts.system_font_files(name) is not None), "Helvetica")
    regular, bold = pdffonts.pdf_variants(family)[:2]
    body = ParagraphStyle("body", fontName=regular, fontSize=10.5, leading=14.5, spaceAfter=7)
    marker = ParagraphStyle("marker", fontName=bold, fontSize=8.5, leading=11, textColor=HexColor("#6B6B6B"), spaceAfter=6)
    empty = ParagraphStyle("empty", parent=body, textColor=HexColor("#8A8A8A"))
    story = []
    for number, text in enumerate(pages, start=1):
        if number > 1:
            story.append(PageBreak())
        story.append(Paragraph(html.escape(f"{source_name} · Seite {number} · Übersetzung ({language})"), marker))
        story.append(Spacer(1, 2 * mm))
        paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
        if not paragraphs:
            story.append(Paragraph("(Diese Seite enthält keinen Text.)", empty))
        for paragraph in paragraphs:
            story.append(Paragraph(html.escape(paragraph).replace("\n", "<br/>"), body))
    target = Path(target)
    temp = target.parent / f".{target.stem[:40]}.pdftool-{secrets.token_hex(4)}.tmp"
    try:
        document = SimpleDocTemplate(str(temp), pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
                                     title=f"{Path(source_name).stem} ({language})", author="Novadesk", creator="Novadesk")
        document.build(story)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target
