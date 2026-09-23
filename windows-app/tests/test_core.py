"""Tests ohne Oberfläche: PDF-Engine, Einstellungen, Farben, Easing, Mica-Rezept."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import appstate
import engine
from ui import animations, mica, theme


# --- Engine ------------------------------------------------------------------------


def test_pruefe_excel_counts_active_contracts(excel_file: Path) -> None:
    result = engine.pruefe_excel(excel_file, [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}])
    assert result["ok"] is True
    assert result["text"].startswith("3 aktive Verträge")
    assert "1 inaktiv ausgeblendet" in result["text"]
    assert result["kunden"] == ["10042"]
    assert result["firmen"] == ["Muster GmbH"]
    assert result["mails"] == ["rechnung@muster.de"]
    zyklus = {zeile["nr"]: zeile["zyklus"] for zeile in result["zeilen"]}
    assert zyklus["V-1002"] == "jährlich"
    assert zyklus["V-1001"] == "jeden Monat"


def test_pruefe_excel_missing_file(tmp_path: Path) -> None:
    result = engine.pruefe_excel(tmp_path / "fehlt.xlsx")
    assert result["ok"] is False
    assert "nicht gefunden" in result["text"]


def test_erstelle_pdf_with_header_footer(excel_file: Path, tmp_path: Path) -> None:
    pypdf = pytest.importorskip("pypdf")
    auftrag = engine.PdfAuftrag(
        excel=excel_file,
        logo=appstate.DEFAULT_LOGO,
        kundennummer="10042",
        firmenname="Muster GmbH",
        zielordner=tmp_path,
        dateiname="Uebersicht_{kunde}_Kd{kd}.pdf",
        seitenformat="quer",
        kopfzeile="Kopf {kd}",
        fusszeile="Fuß {kunde}",
        regeln=[{"enthaelt": "Hott-KI", "zyklus": "jährlich"}],
    )
    pfad = engine.erstelle_pdf(auftrag)
    assert pfad == tmp_path / "Uebersicht_Muster_GmbH_Kd10042.pdf"
    reader = pypdf.PdfReader(str(pfad))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Kopf 10042" in text
    assert "Fuß Muster_GmbH" in text
    assert "Supportvertrag" in text
    assert "V-0999" not in text  # inaktiv
    assert "Seite 1 von" in text
    width, height = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert width > height  # Querformat


def test_erstelle_pdf_requires_customer_number(excel_file: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        engine.erstelle_pdf(engine.PdfAuftrag(excel=excel_file, logo=appstate.DEFAULT_LOGO, kundennummer="", zielordner=tmp_path))


# --- Einstellungen (kompatibel zu 2.0.5) ---------------------------------------------------


def test_config_roundtrip_is_atomic(tmp_path: Path) -> None:
    target = tmp_path / "gui-config.json"
    assert appstate.save_config({"a": 1, "ä": "ö"}, target)
    assert appstate.load_config(target) == {"a": 1, "ä": "ö"}
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_config_corrupt_returns_empty(tmp_path: Path) -> None:
    target = tmp_path / "gui-config.json"
    target.write_text("{kaputt", encoding="utf-8")
    assert appstate.load_config(target) == {}


def test_state_reads_205_config() -> None:
    cfg = {
        "firmenname": "Alt GmbH",
        "kunden": [{"firmenname": "A", "kundennummer": "1"}, "müll"],
        "bausteine": [{"name": "B1", "text": "T"}, {"text": "ohne Name"}],
        "regeln": [{"enthaelt": "X", "zyklus": "Y"}, {"enthaelt": ""}],
        "pdfs": ["/nicht/da.pdf", 3],
        "vorlagen": [{"name": "V1"}],
        "staende": {"k": 1},
        "gesehen": "2.0.5",
        "theme": "dark",
        "accent": "#c42b1e",
    }
    state = appstate.State(cfg)
    assert state.kunden == [{"firmenname": "A", "kundennummer": "1"}]
    assert [b["name"] for b in state.bausteine] == ["B1"]
    assert state.regeln == [{"enthaelt": "X", "zyklus": "Y"}]
    assert state.pdfs == ["/nicht/da.pdf"]
    assert state.staende == {"k": 1}
    assert appstate.major_minor(state.gesehen) != appstate.major_minor(appstate.VERSION)


def test_state_default_rules_when_missing() -> None:
    assert appstate.State({}).regeln == [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]
    assert appstate.State({"regeln": []}).regeln == []


def test_customer_history_upsert_and_limit() -> None:
    state = appstate.State({})
    for number in range(15):
        state.remember_customer(f"Firma {number}", str(number), "", "", "", "", "")
    assert len(state.kunden) == appstate.MAX_KUNDEN
    state.remember_customer("firma 3", "3", "neu@x.de", "", "", "", "", pdf="/tmp/x.pdf")
    assert state.kunden[0]["rechnungsempfaenger"] == "neu@x.de"
    assert sum(1 for k in state.kunden if k["kundennummer"] == "3") == 1
    assert not state.remember_customer("", "", "", "", "", "", "")


def test_templates_blocks_rules() -> None:
    state = appstate.State({})
    state.save_vorlage({"name": "A", "titel": "1"})
    state.save_vorlage({"name": "B"})
    state.save_vorlage({"name": "A", "titel": "2"})
    assert [v["name"] for v in state.vorlagen] == ["A", "B"]
    assert state.find_vorlage("A")["titel"] == "2"
    assert state.delete_vorlage("A") and not state.delete_vorlage("A")
    state.save_baustein("F", "Text")
    assert state.find_baustein("F")["text"] == "Text"
    assert state.delete_baustein("F")
    state.add_regel("hott-ki", "halbjährlich")
    assert state.regeln == [{"enthaelt": "hott-ki", "zyklus": "halbjährlich"}]
    assert state.delete_regel(0)["enthaelt"] == "hott-ki"
    assert state.delete_regel(5) is None


def test_versions_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    iss = (root / "installer" / "Uebersichten-Ersteller.iss").read_text(encoding="utf-8-sig")
    readme = (root / "README.txt").read_text(encoding="utf-8")
    assert appstate.VERSION == version == "2.1.0"
    # Das Setup liest die Version aus derselben Datei, statt sie zu wiederholen.
    assert r'FileOpen(AddBackslash(SourcePath) + "..\VERSION")' in iss
    assert "2.0.5" not in iss.split("[Setup]")[1].split("[Languages]")[0]
    assert f"Version {version}" in readme
    assert not (root / "installer" / "main.go").exists()
    assert not (root / "installer" / "go.mod").exists()


# --- Farben und Bewegung -------------------------------------------------------------------


@pytest.mark.parametrize("name,value", theme.ACCENTS)
def test_accent_contrast(name: str, value: str) -> None:
    accent = theme.derive_accent(value)
    light = theme.build_palette(False, accent)
    dark = theme.build_palette(True, accent)
    assert theme.contrast(light.accent, light.on_accent) >= 4.5, name
    assert theme.contrast(dark.accent, dark.on_accent) >= 4.5, name


def test_palettes_text_contrast() -> None:
    accent = theme.derive_accent(theme.DEFAULT_ACCENT)
    for dark in (False, True):
        pal = theme.build_palette(dark, accent)
        assert theme.contrast(pal.text, pal.card) >= 7
        assert theme.contrast(pal.text2, pal.card) >= 4.5
        assert pal.card != pal.layer != pal.mica


def test_easing_bounds_and_monotonic() -> None:
    for ease in (animations.DECELERATE, animations.EASE_OUT, animations.POINT_TO_POINT, animations.EASE_IN_OUT):
        values = [ease(i / 50) for i in range(51)]
        assert abs(values[0]) < 1e-6 and abs(values[-1] - 1) < 1e-6
        assert all(b >= a - 1e-6 for a, b in zip(values, values[1:]))


def test_mica_tint_is_subtle() -> None:
    for pixel in ((0, 90, 200), (220, 30, 30), (255, 255, 255), (0, 0, 0)):
        light = mica.tint_pixel(pixel, dark=False)
        dark = mica.tint_pixel(pixel, dark=True)
        assert all(abs(c - 243) <= 14 for c in light), (pixel, light)
        assert all(abs(c - 32) <= 18 for c in dark), (pixel, dark)


def test_config_file_json_is_valid(tmp_path: Path) -> None:
    target = tmp_path / "c.json"
    appstate.save_config({"liste": [1, 2]}, target)
    assert json.loads(target.read_text(encoding="utf-8")) == {"liste": [1, 2]}
