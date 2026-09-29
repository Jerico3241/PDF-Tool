"""Rich Text für Kopf- und Fußzeile (Version 2.2): Datenmodell, Speicherung, Schriften und PDF."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

import appstate
import engine
import pdffonts
import richtext
from richtext import FOOTER_STYLE, HEADER_STYLE, CharStyle, RichText

pypdf = pytest.importorskip("pypdf")

ROT = "#B51F1F"
BLAU = "#1F5AA6"


def formatiert(text: str, bereiche: list[tuple[int, int, dict]], default: CharStyle = FOOTER_STYLE, aligns: list[str] | None = None, align: str = "center") -> RichText:
    styles = [default] * len(text)
    for start, end, changes in bereiche:
        for index in range(start, end):
            styles[index] = styles[index].with_(**changes)
    return RichText(text, styles, aligns, default, align)


# --- Datenmodell ------------------------------------------------------------------------------


def test_json_roundtrip_is_stable_and_plain_json() -> None:
    rich = formatiert("Kundennummer: {kd}\nZweite Zeile", [(14, 18, {"bold": True, "color": ROT})], aligns=["left", "right"])
    data = rich.to_dict()
    assert json.loads(json.dumps(data)) == data  # reines JSON, kein HTML/ReportLab-Markup
    assert data["version"] == 1 and data["text"] == rich.text
    assert data["paragraphs"] == [{"start": 0, "end": 18, "alignment": "left"}, {"start": 19, "end": 31, "alignment": "right"}]
    fett = [span for span in data["spans"] if span["bold"]]
    assert fett == [{"start": 14, "end": 18, "font": "Helvetica", "size": 8, "color": ROT, "bold": True, "italic": False, "underline": False, "strike": False}]
    assert RichText.from_dict(data, FOOTER_STYLE, "center", text=rich.text) == rich


def test_format_must_match_text_otherwise_plain_default() -> None:
    rich = formatiert("Alt", [(0, 3, {"bold": True})])
    data = rich.to_dict()
    # Text wurde z. B. mit einer älteren Version geändert: Formatierung passt nicht mehr
    assert RichText.from_dict(data, FOOTER_STYLE, "center", text="Neu") is None
    geladen = RichText.from_storage("Neu", data, FOOTER_STYLE, "center")
    assert geladen.text == "Neu" and geladen.styles == [FOOTER_STYLE] * 3 and geladen.aligns == ["center"]


@pytest.mark.parametrize("kaputt", [None, "x", 3, {"text": 5}, {"spans": []}])
def test_invalid_format_falls_back_without_losing_text(kaputt) -> None:
    geladen = RichText.from_storage("Text bleibt", kaputt, FOOTER_STYLE, "center")
    assert geladen.text == "Text bleibt"
    assert set(geladen.styles) == {FOOTER_STYLE}


def test_invalid_values_are_sanitized() -> None:
    data = {
        "text": "abcdef",
        "spans": [
            {"start": 0, "end": 2, "size": 500, "color": "rot", "font": "", "bold": "ja"},
            {"start": 2, "end": 99, "size": "12", "color": "#00ff00", "italic": True},
            {"start": 5, "end": 3},
            "müll",
        ],
        "paragraphs": [{"start": 0, "end": 6, "alignment": "blocksatz"}],
    }
    rich = RichText.from_dict(data, FOOTER_STYLE, "center")
    assert rich.styles[0] == FOOTER_STYLE  # ungültige Größe/Farbe/Schrift → Standard, "ja" ist nicht True
    assert rich.styles[3].size == 12 and rich.styles[3].color == "#00FF00" and rich.styles[3].italic
    assert rich.aligns == ["center"]


def test_placeholders_keep_their_formatting() -> None:
    rich = formatiert("Kundennummer: {kd}", [(14, 18, {"bold": True, "color": ROT})], align="left")
    ersetzt = rich.with_placeholders({"kd": "123456"})
    assert ersetzt.text == "Kundennummer: 123456"
    runs = [(ersetzt.text[s:e], st.bold, st.color) for s, e, st in ersetzt.runs()]
    assert runs == [("Kundennummer: ", False, richtext.TEXT_COLOR), ("123456", True, ROT)]


def test_placeholders_unknown_and_multiple() -> None:
    rich = formatiert("{firma} · {kd} · {unbekannt} · {datumkurz}", [(0, 7, {"italic": True})])
    ersetzt = rich.with_placeholders({"firma": "Müller & Söhne", "kd": "7", "datumkurz": "01.02.2026"})
    assert ersetzt.text == "Müller & Söhne · 7 · {unbekannt} · 01.02.2026"
    assert all(style.italic for style in ersetzt.styles[: len("Müller & Söhne")])
    assert not any(style.italic for style in ersetzt.styles[len("Müller & Söhne") :])
    # Werte mit Zeilenumbruch verändern die Absätze nicht
    assert RichText.plain("{kd}").with_placeholders({"kd": "a\nb"}).text == "a b"


def test_markup_escapes_user_text() -> None:
    rich = RichText.plain('<b>fett?</b> & <font name="x">', FOOTER_STYLE)
    markup = richtext.paragraph_markup(rich, 0, len(rich.text), pdffonts.pdf_font)
    assert "&lt;b&gt;fett?&lt;/b&gt; &amp; &lt;font" in markup
    assert markup.count("<font ") == 1  # nur das eigene Tag der App


def test_markup_uses_real_font_variants() -> None:
    rich = formatiert("abcd", [(1, 2, {"bold": True}), (2, 3, {"italic": True}), (3, 4, {"bold": True, "italic": True, "underline": True, "strike": True})])
    markup = richtext.paragraph_markup(rich, 0, 4, pdffonts.pdf_font)
    assert 'name="Helvetica"' in markup and 'name="Helvetica-Bold"' in markup
    assert 'name="Helvetica-Oblique"' in markup and 'name="Helvetica-BoldOblique"' in markup
    assert "<u><strike>d</strike></u>" in markup
    assert "<b>" not in markup  # keine künstliche Fettschrift


def test_stripped_like_plain_text() -> None:
    rich = formatiert("  Einzug\n\n  \n", [(2, 8, {"bold": True})], aligns=["right", "left", "center", "center"])
    kurz = rich.stripped()
    assert kurz.text == "  Einzug" and kurz.aligns == ["right"]
    assert RichText.plain(" \n ").stripped().text == ""


# --- Speicherung und Migration ------------------------------------------------------------------


def test_old_config_plain_texts_get_default_formatting() -> None:
    alt = {"kopfzeile": "Alte Kopfzeile", "fusszeile": "Alte Fußzeile"}
    kopf = appstate.header_rich_from(alt)
    fuss = appstate.footer_rich_from(alt)
    assert kopf.text == "Alte Kopfzeile" and set(kopf.styles) == {HEADER_STYLE} and kopf.aligns == ["left"]
    assert fuss.text == "Alte Fußzeile" and set(fuss.styles) == {FOOTER_STYLE} and fuss.aligns == ["center"]


def test_default_footer_formatting() -> None:
    fuss = appstate.default_footer_rich()
    assert fuss.text == appstate.DEFAULT_FOOTER
    assert set(fuss.styles) == {CharStyle(font="Helvetica", size=8, color="#333333")}
    assert set(fuss.aligns) == {"center"}
    # frische Konfiguration und alte leere Stände: Standardtext mit Standardformat
    for entry in ({}, {"fusszeile": ""}, {"fusszeile": None, "fusszeile_format": {"text": "", "spans": []}}):
        assert appstate.footer_rich_from(entry) == fuss


def test_saved_format_is_loaded_for_matching_text() -> None:
    rich = formatiert("Eigene Fußzeile", [(0, 6, {"bold": True, "font": "Times", "size": 10})])
    entry = {"fusszeile": rich.text, "fusszeile_format": rich.to_dict(), "fusszeile_explizit": True}
    assert appstate.footer_rich_from(entry) == rich


def test_text_blocks_old_and_new() -> None:
    state = appstate.State({"bausteine": [{"name": "Alt", "text": "Nur Text"}]})
    assert appstate.baustein_rich(state.find_baustein("Alt")) == RichText.plain("Nur Text", FOOTER_STYLE, "center")
    rich = formatiert("Gruß\nTeam", [(0, 4, {"italic": True})], aligns=["left", "right"])
    state.save_baustein("Neu", rich.text, rich.to_dict())
    assert appstate.baustein_rich(state.find_baustein("Neu")) == rich


def test_customer_record_keeps_formatting() -> None:
    from tools.contract_overview.customer_flow import footer_of, header_of
    from tools.contract_overview.customers.migration import customer_from_legacy

    fuss = formatiert("Kunde A", [(0, 5, {"color": BLAU})])
    kopf = formatiert("Kopf A", [(0, 4, {"bold": True})], default=HEADER_STYLE, align="left")
    eintrag = {"firmenname": "A GmbH", "kundennummer": "1", "fusszeile": fuss.text, "fusszeile_format": fuss.to_dict(), "kopfzeile": kopf.text, "kopfzeile_format": kopf.to_dict()}
    kunde = customer_from_legacy(eintrag, "")
    assert footer_of(kunde) == fuss and header_of(kunde) == kopf
    # alte Einträge: leere Fußzeile ersetzt die aktuelle nicht; Kopfzeile ohne Format → Standard
    assert footer_of(customer_from_legacy({"firmenname": "A", "fusszeile": ""}, "")) is None
    assert header_of(customer_from_legacy({"firmenname": "A", "kopfzeile": "K"}, "")) == RichText.plain("K", HEADER_STYLE, "left")
    assert header_of(customer_from_legacy({"firmenname": "A"}, "")) is None


# --- Schriften ------------------------------------------------------------------------------------


@pytest.fixture
def windows_fonts(tmp_path: Path, monkeypatch):
    """Windows-Schriften: unter Windows die echten, sonst Liberation Sans unter dem Namen Arial."""
    if sys.platform != "win32":
        quelle = Path("/usr/share/fonts/truetype/liberation")
        dateien = {"arial.ttf": "LiberationSans-Regular.ttf", "arialbd.ttf": "LiberationSans-Bold.ttf", "ariali.ttf": "LiberationSans-Italic.ttf", "arialbi.ttf": "LiberationSans-BoldItalic.ttf"}
        if not all((quelle / name).is_file() for name in dateien.values()):
            pytest.skip("keine TrueType-Testschrift vorhanden")
        ordner = tmp_path / "fonts"
        ordner.mkdir()
        for ziel, name in dateien.items():
            shutil.copy(quelle / name, ordner / ziel)
        monkeypatch.setenv("UE_FONT_DIR", str(ordner))
        monkeypatch.delenv("WINDIR", raising=False)
        monkeypatch.delenv("SystemRoot", raising=False)
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    pdffonts.reset_cache()
    yield
    pdffonts.reset_cache()


def test_base_fonts_always_available() -> None:
    families = pdffonts.available_families()
    assert families[0] == "Helvetica" and "Times" in families and "Courier" in families
    assert pdffonts.pdf_font("Times", bold=True, italic=True) == "Times-BoldItalic"
    assert pdffonts.pdf_font("Courier", italic=True) == "Courier-Oblique"


def test_missing_windows_font_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UE_FONT_DIR", str(tmp_path))
    for name in ("WINDIR", "SystemRoot", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    pdffonts.reset_cache()
    try:
        assert "Calibri" not in pdffonts.available_families()
        assert pdffonts.pdf_font("Calibri", bold=True) == "Helvetica-Bold"
        assert pdffonts.pdf_font("Times New Roman", italic=True) == "Times-Italic"
        assert pdffonts.pdf_font("Unbekannte Schrift") == "Helvetica"
    finally:
        pdffonts.reset_cache()


def test_windows_font_is_embedded_with_real_variants(windows_fonts, excel_file: Path, tmp_path: Path) -> None:
    assert "Arial" in pdffonts.available_families()
    rich = formatiert("Arial normal fett", [(0, 17, {"font": "Arial"}), (13, 17, {"bold": True})])
    pfad = engine.erstelle_pdf(engine.PdfAuftrag(excel=excel_file, logo=appstate.DEFAULT_LOGO, kundennummer="1", zielordner=tmp_path, fusszeile=rich.text, fusszeile_format=rich.to_dict()))
    fonts = {text: font for text, font, *_rest in textstuecke(pfad)}
    normal, fett = fonts["Arial normal"], fonts["fett"]
    assert normal != fett and "Helvetica" not in normal + fett
    assert "Bold" in fett and "Bold" not in normal


# --- PDF-Ausgabe ----------------------------------------------------------------------------------


def textstuecke(pfad: Path, seite: int = 0) -> list[tuple[str, str, float, float, float, str]]:
    """(Text, Schrift, Größe, x, y, Füllfarbe) aller Textstücke einer Seite.

    Die Füllfarbe wird am Textoperator (Tj) selbst abgelesen: pypdf meldet den Text
    teils erst nach dem folgenden Farbwechsel.
    """
    stuecke = []
    farbe = ["#000000"]
    farben: list[tuple[str, str]] = []

    def before(operator, operands, _cm, _tm):
        if operator == b"rg" and len(operands) == 3:
            farbe[0] = "#" + "".join(f"{round(float(v) * 255):02X}" for v in operands)
        elif operator == b"g" and len(operands) == 1:
            value = round(float(operands[0]) * 255)
            farbe[0] = f"#{value:02X}{value:02X}{value:02X}"
        elif operator == b"Tj" and operands:
            farben.append((" ".join(str(operands[0]).split()), farbe[0]))

    def visit(text, cm, tm, font, size):
        text = " ".join(str(text).split())
        if text and font:
            index = next((i for i, (t, _f) in enumerate(farben) if t == text), None)
            color = farben.pop(index)[1] if index is not None else farbe[0]
            stuecke.append((text, str(font.get("/BaseFont", "")).lstrip("/"), round(size, 2), round(tm[4] * cm[0] + cm[4], 1), round(tm[5] * cm[3] + cm[5], 1), color))

    pypdf.PdfReader(str(pfad)).pages[seite].extract_text(visitor_text=visit, visitor_operand_before=before)
    return stuecke


def linien(pfad: Path) -> list[tuple[float, float, float]]:
    """Waagerechte Linien (x1, x2, y) aus dem Seiteninhalt (Unterstreichen, Durchstreichen, Trennlinien)."""
    result = []
    punkt = [None]

    def before(operator, operands, cm, _tm):
        if operator == b"m" and len(operands) == 2:
            punkt[0] = (float(operands[0]) * cm[0] + cm[4], float(operands[1]) * cm[3] + cm[5])
        elif operator == b"l" and len(operands) == 2 and punkt[0] is not None:
            x2, y2 = float(operands[0]) * cm[0] + cm[4], float(operands[1]) * cm[3] + cm[5]
            if abs(y2 - punkt[0][1]) < 0.01:
                result.append((round(min(punkt[0][0], x2), 1), round(max(punkt[0][0], x2), 1), round(y2, 1)))

    pypdf.PdfReader(str(pfad)).pages[0].extract_text(visitor_operand_before=before)
    return result


def erstelle(excel_file: Path, tmp_path: Path, fuss: RichText | None = None, kopf: RichText | None = None, **kwargs) -> Path:
    return engine.erstelle_pdf(
        engine.PdfAuftrag(
            excel=excel_file,
            logo=appstate.DEFAULT_LOGO,
            kundennummer="10042",
            firmenname="Müller & Söhne",
            zielordner=tmp_path,
            fusszeile=fuss.text if fuss else "",
            fusszeile_format=fuss.to_dict() if fuss else None,
            kopfzeile=kopf.text if kopf else "",
            kopfzeile_format=kopf.to_dict() if kopf else None,
            **kwargs,
        )
    )


def finde(stuecke, text: str):
    treffer = [s for s in stuecke if s[0] == text]
    assert treffer, f"{text!r} fehlt in {[s[0] for s in stuecke]}"
    return treffer[0]


def test_pdf_bold_italic_underline_size_color_font(excel_file: Path, tmp_path: Path) -> None:
    text = "Normal Fett Kursiv Unter Groß Rot Times Durch"
    bereiche = [
        (7, 11, {"bold": True}),
        (12, 18, {"italic": True}),
        (19, 24, {"underline": True}),
        (25, 29, {"size": 14}),
        (30, 33, {"color": ROT}),
        (34, 39, {"font": "Times"}),
        (40, 45, {"strike": True}),
    ]
    rich = formatiert(text, bereiche, align="left")
    pfad = erstelle(excel_file, tmp_path, fuss=rich)
    stuecke = textstuecke(pfad)
    assert finde(stuecke, "Normal")[1] == "Helvetica"
    assert finde(stuecke, "Fett")[1] == "Helvetica-Bold"
    assert finde(stuecke, "Kursiv")[1] == "Helvetica-Oblique"
    assert finde(stuecke, "Groß")[2] == 14 and finde(stuecke, "Normal")[2] == 8
    assert finde(stuecke, "Rot")[5] == ROT and finde(stuecke, "Normal")[5] == "#333333"
    assert finde(stuecke, "Times")[1] == "Times-Roman"
    # Unterstreichen: Linie so lang wie »Unter« knapp unter der Grundlinie; Durchstreichen: Linie über »Durch«
    from reportlab.pdfbase.pdfmetrics import stringWidth

    striche = linien(pfad)
    _t, _f, _s, _x, y, _c = finde(stuecke, "Unter")
    breite = stringWidth("Unter", "Helvetica", 8)
    assert any(abs((x2 - x1) - breite) < 0.5 and 0.5 < y - ly < 3 for x1, x2, ly in striche), "Unterstrich fehlt"
    _t, _f, _s, _x, y, _c = finde(stuecke, "Durch")
    breite = stringWidth("Durch", "Helvetica", 8)
    assert any(abs((x2 - x1) - breite) < 0.5 and 0.5 < ly - y < 5 for x1, x2, ly in striche), "Durchstreichung fehlt"
    # nur diese beiden Wörter sind unter- bzw. durchgestrichen
    kurze = [(x1, x2, ly) for x1, x2, ly in striche if x2 - x1 < 100]
    assert len(kurze) == 2


def test_pdf_alignment_per_paragraph(excel_file: Path, tmp_path: Path) -> None:
    from reportlab.lib.units import mm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    rich = RichText.plain("Links\nMitte\nRechts", FOOTER_STYLE, "center")
    rich.aligns = ["left", "center", "right"]
    pfad = erstelle(excel_file, tmp_path, fuss=rich)
    stuecke = textstuecke(pfad)
    links, breite = 14 * mm, 182 * mm
    assert finde(stuecke, "Links")[3] == pytest.approx(links, abs=0.5)
    mitte = finde(stuecke, "Mitte")[3] + stringWidth("Mitte", "Helvetica", 8) / 2
    assert mitte == pytest.approx(links + breite / 2, abs=0.5)
    rechts = finde(stuecke, "Rechts")[3] + stringWidth("Rechts", "Helvetica", 8)
    assert rechts == pytest.approx(links + breite, abs=0.5)
    y = {name: finde(stuecke, name)[4] for name in ("Links", "Mitte", "Rechts")}
    assert y["Links"] - y["Mitte"] == pytest.approx(10, abs=0.6) and y["Mitte"] - y["Rechts"] == pytest.approx(10, abs=0.6)


def test_pdf_placeholder_keeps_bold_red(excel_file: Path, tmp_path: Path) -> None:
    rich = formatiert("Kundennummer: {kd}", [(14, 18, {"bold": True, "color": ROT})], default=HEADER_STYLE, align="left")
    pfad = erstelle(excel_file, tmp_path, kopf=rich)
    stuecke = textstuecke(pfad)
    _t, font, _s, _x, _y, farbe = finde(stuecke, "10042")
    kopf_y = max(s[4] for s in stuecke)
    kopf = [s for s in stuecke if s[4] == kopf_y]
    assert [s[0] for s in kopf] == ["Kundennummer:", "10042"]
    assert kopf[1][1] == "Helvetica-Bold" and kopf[1][5] == ROT
    assert kopf[0][1] == "Helvetica" and kopf[0][5] == "#333333"
    assert font and farbe


def test_pdf_unicode_and_company_placeholder(excel_file: Path, tmp_path: Path) -> None:
    rich = RichText.plain("Grüße aus Köln – {firma} · 12 € · Straße", FOOTER_STYLE, "center")
    pfad = erstelle(excel_file, tmp_path, fuss=rich)
    text = " ".join(pypdf.PdfReader(str(pfad)).pages[0].extract_text().split())
    assert "Grüße aus Köln – Müller & Söhne · 12 € · Straße" in text


def test_pdf_header_and_footer_height_follow_content(excel_file: Path, tmp_path: Path) -> None:
    gross = RichText.plain("Groß 1\nGroß 2\nGroß 3\nGroß 4", FOOTER_STYLE.with_(size=18), "center")
    kopf = RichText.plain("Kopf groß\nzweite Zeile", HEADER_STYLE.with_(size=16), "left")
    pfad = erstelle(excel_file, tmp_path, fuss=gross, kopf=kopf, seitenformat="quer")
    stuecke = textstuecke(pfad)
    fuss_oben = max(finde(stuecke, f"Groß {n}")[4] for n in range(1, 5)) + 18
    tabelle = [finde(stuecke, nr)[4] for nr in ("V-1001", "V-1002", "V-1003")]
    assert min(tabelle) > fuss_oben + 5  # Tabelle endet oberhalb der Fußzeile
    kopf_unten = finde(stuecke, "zweite Zeile")[4]
    logo_titel = finde(stuecke, "Vertragsübersicht")[4]
    assert logo_titel < kopf_unten - 10  # Inhalt beginnt unterhalb der Kopfzeile
    assert "Seite 1 von 1" in [s[0] for s in stuecke]  # Seitenzahl bleibt


def test_pdf_rejects_header_footer_that_cannot_fit(excel_file: Path, tmp_path: Path) -> None:
    riesig = RichText.plain("\n".join(f"Zeile {n}" for n in range(40)), FOOTER_STYLE.with_(size=18), "center")
    with pytest.raises(ValueError, match="zu hoch"):
        erstelle(excel_file, tmp_path, fuss=riesig)


def test_pdf_without_format_keeps_established_look(excel_file: Path, tmp_path: Path) -> None:
    """Nur Text (z. B. aus 2.1): Helvetica 8 pt, dunkelgrau, Fußzeile zentriert, Kopfzeile links."""
    from reportlab.lib.units import mm

    pfad = engine.erstelle_pdf(engine.PdfAuftrag(excel=excel_file, logo=appstate.DEFAULT_LOGO, kundennummer="10042", zielordner=tmp_path, kopfzeile="Kopf", fusszeile="Fuß"))
    stuecke = textstuecke(pfad)
    kopf, fuss = finde(stuecke, "Kopf"), finde(stuecke, "Fuß")
    assert kopf[1] == fuss[1] == "Helvetica" and kopf[2] == fuss[2] == 8 and kopf[5] == fuss[5] == "#333333"
    assert kopf[3] == pytest.approx(14 * mm, abs=0.5)
    assert fuss[3] > 80 * mm
