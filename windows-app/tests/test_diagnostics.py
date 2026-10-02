"""Diagnose, Support-Paket, Protokoll und Aufräumen (Test 105 der Vorgabe).

* Systeminformationen nennen Version, Kanal, Python, Qt, Betriebssystem, Pfade, Module, Engines.
* Die Datenprüfung meldet beschädigte, fremde oder neuere Dateien – und ändert nichts.
* Das Support-Paket enthält nie Kundendaten, Vertragsinhalte, Passwörter, PDF- oder Excel-Inhalte;
  Pfade zu Dokumenten, Benutzerordner, Benutzer- und Computername und E-Mail-Adressen sind entfernt.
* Das Protokoll rotiert; aufgeräumt werden nur eigene temporäre Dateien.
"""

from __future__ import annotations

import json
import logging
import os
import time
import zipfile
from pathlib import Path

import pytest

from diagnostics import applog, checks, cleanup, info, support
from diagnostics.sanitize import Sanitizer, anonymize_config

PROFILE = r"C:\Users\Max Mustermann"
INSTALL = r"C:\Program Files\PDF Tool"
DATA = r"C:\Users\Max Mustermann\AppData\Roaming\PDF-Tool"


def sanitizer() -> Sanitizer:
    return Sanitizer(install_dir=INSTALL, data_dir=DATA, profile=PROFILE, user="mmustermann", computer="BUERO-PC-07")


def schreibe(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data), encoding="utf-8")
    return path


def test_system_facts_cover_the_essentials() -> None:
    facts = {fact.key: fact for fact in info.system_facts("2.8.0-beta.1", "beta", Path("/daten"), Path("/programm"))}
    assert set(facts) == {"version", "channel", "python", "qt", "os", "arch", "data", "install", "engines", "editor", "modules"}
    assert facts["version"].value == "2.8.0-beta.1" and facts["channel"].value == "Beta"
    assert "PySide6 6." in facts["qt"].value and "Qt 6." in facts["qt"].value
    assert "qpdf" in facts["engines"].value and "PDFium" in facts["engines"].value
    assert "pikepdf" in facts["editor"].value and "PDFium" in facts["editor"].value and "fontTools" in facts["editor"].value
    assert "nicht verfügbar" not in facts["editor"].value
    assert "ReportLab" in facts["modules"].value and "pypdf" in facts["modules"].value
    assert info.system_facts("2.8.0", "stable", Path("/d"), Path("/p"))[1].value == "Stable"


def test_start_log_names_the_system_without_a_slow_query(monkeypatch) -> None:
    import platform
    import sys

    def slow(*_args, **_kwargs):  # unter Windows: WMI-Abfrage vor dem ersten Fenster
        raise AssertionError("beim Start keine WMI-Abfrage")

    for name in ("platform", "uname", "system", "release", "version", "machine", "node", "win32_ver"):
        monkeypatch.setattr(platform, name, slow)
    assert info.os_brief()
    if sys.platform == "win32":
        assert info.os_brief().startswith("Windows 10.0 Build ")


# --- Datenprüfung ------------------------------------------------------------------------------------


def test_checks_on_healthy_and_damaged_data(tmp_path: Path) -> None:
    root = tmp_path / "daten"
    schreibe(root / "gui-config.json", {"theme": "light"})
    schreibe(root / "kundenakten.json", {"schema_version": 2, "customers": [{"id": "a"}, {"id": "b"}]})
    from tools.contract_overview.templates.repository import TemplateStore

    assert TemplateStore(root / "vorlagen").load().create("Vorlage") is not None
    schreibe(root / "contract-history" / "a" / "1.json", {"schema_version": 1, "contracts": []})
    result = {check.key: check for check in checks.run_checks(root, tmp_path / "sicherungen")}
    assert result["config"].status == "ok" and result["customers"].detail == "2 Kundenakten."
    assert result["rules"].status == "info" and result["history"].status == "ok"
    assert result["backups"].status == "ok" and result["temp"].status == "ok" and result["engines"].status == "ok"
    assert checks.summary(list(result.values()))[0] == "ok"
    vorher = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    # Beschädigt, neuer, fremd
    schreibe(root / "gui-config.json", "{ kaputt")
    schreibe(root / "kundenakten.json", {"schema_version": 9, "customers": []})
    schreibe(root / "vorlagen" / "kaputt.json", "nicht json")
    schreibe(root / "regelwerke" / "neu.json", {"schema_version": 5, "id": "r", "name": "x"})
    schreibe(root / "contract-history" / "a" / "2.json", "kaputt")
    blocker = schreibe(tmp_path / "datei", "x")
    result = {check.key: check for check in checks.run_checks(root, blocker / "unter")}
    assert result["config"].status == "error" and "beschädigt" in result["config"].detail
    assert result["customers"].status == "error" and "neueren Version" in result["customers"].detail
    assert result["templates"].status == "warning" and "kaputt.json" in result["templates"].detail
    assert result["rules"].status == "warning" and "neueren Version" in result["rules"].detail
    assert result["history"].status == "warning" and "1 beschädigt" in result["history"].detail
    assert result["backups"].status == "error"
    status, text = checks.summary(list(result.values()))
    assert status == "error" and "Fehler" in text
    # Die Prüfung ändert nichts (nur Proben mit eigenem Präfix, sofort entfernt)
    assert (root / "vorlagen" / "kaputt.json").read_text(encoding="utf-8") == "nicht json"
    assert not [p for p in root.rglob(".~diagnose-*")]
    assert all(p.exists() for p in vorher)


# --- Bereinigen ------------------------------------------------------------------------------------------


def test_redact_removes_personal_paths_names_and_mails() -> None:
    clean = sanitizer()
    log = (
        "2026-10-01 PDF erstellt: C:\\Users\\Max Mustermann\\Documents\\Kunden\\Muster GmbH\\Vertragsuebersicht_Kd10042.pdf\n"
        "Excel: \\\\server\\freigabe\\Muster GmbH\\liste.xlsx\n"
        'Traceback: File "C:\\Program Files\\PDF Tool\\app\\engine.py", line 12, in erstelle_pdf\n'
        "Daten: C:\\Users\\Max Mustermann\\AppData\\Roaming\\PDF-Tool\\vorlagen\\abc.json\n"
        "Empfänger rechnung@muster-gmbh.de, Benutzer mmustermann auf BUERO-PC-07\n"
        "Linux: /home/max/Kunden/Muster GmbH/liste.xlsx\n"
    )
    text = clean.redact(log)
    for secret in ("Muster", "Mustermann", "muster-gmbh", "mmustermann", "BUERO-PC-07", "Kunden", "Documents", "freigabe", "/home/max"):
        assert secret not in text, secret
    assert "<Pfad>.pdf" in text and "<Pfad>.xlsx" in text and "<E-Mail>" in text
    assert '"<Programmordner>\\app\\engine.py", line 12' in text  # Tracebacks bleiben brauchbar
    assert "<Datenordner>\\vorlagen\\abc.json" in text
    assert "<Benutzer>" in text and "<Computer>" in text
    # Angaben wie der Datenordner: nur anonymisiert
    assert clean.anonymize(DATA) == "%USERPROFILE%\\AppData\\Roaming\\PDF-Tool"


def test_anonymized_settings_keep_switches_and_counts_only() -> None:
    cfg = {
        "theme": "dark",
        "animationsprofil": "reduced",
        "kundenakte_verwenden": True,
        "breite": 1180,
        "firma": "Muster GmbH",
        "mail": "rechnung@muster.de",
        "fusszeile": "IBAN DE00 1234",
        "logo": r"C:\Users\Max\Logos\muster.png",
        "regeln": [{"enthaelt": "Hott"}],
        "vorlagen": [{"name": "Muster GmbH"}, {"name": "B"}],
        "fenster": {"x": 1, "y": 2},
        "accent": "info@muster.de",
    }
    result = anonymize_config(cfg)
    assert result["theme"] == "dark" and result["animationsprofil"] == "reduced" and result["kundenakte_verwenden"] is True and result["breite"] == 1180
    assert result["firma"] == result["mail"] == result["fusszeile"] == result["logo"] == "<Text>" and result["accent"] == "<Text>"
    assert result["regeln"] == "<Liste mit 1 Eintrag>" and result["vorlagen"] == "<Liste mit 2 Einträgen>" and result["fenster"] == "<2 Angaben>"
    assert "Muster" not in json.dumps(result)


# --- Support-Paket ----------------------------------------------------------------------------------------


def test_105_support_package_contains_no_customer_or_document_data(tmp_path: Path) -> None:
    root = tmp_path / "daten"
    schreibe(root / "gui-config.json", {"theme": "light", "firma": "Muster GmbH", "kopfzeile": "Geheim"})
    schreibe(root / "kundenakten.json", {"schema_version": 2, "customers": [{"id": "a", "company": "Muster GmbH", "emails": ["rechnung@muster.de"]}]})
    schreibe(root / "contract-history" / "a" / "1.json", {"schema_version": 1, "contracts": [{"nummer": "V-4711", "beschreibung": "Geheimvertrag"}]})
    schreibe(root / "vorlagen" / "t.json", {"schema_version": 1, "id": "t", "name": "Muster GmbH Spezial"})
    schreibe(root / "fehler.log", f"Fehler beim Lesen von {tmp_path}/Kunden/Muster GmbH/liste.xlsx: Passwort falsch\n")
    schreibe(root / "stapel.log", "Stapel: Muster GmbH → /home/max/Muster GmbH/a.pdf\n")
    schreibe(root / "stapel.log.1", "älter: rechnung@muster.de\n")
    (root / "kunde.pdf").write_bytes(b"%PDF-1.4 Geheiminhalt")
    facts = info.system_facts("2.8.0-beta.1", "stable", root, Path("/programm"))
    result = checks.run_checks(root, tmp_path / "sicherungen")
    clean = Sanitizer(install_dir="/programm", data_dir=str(root), profile="/home/max", user="max", computer="BUERO-PC-07")
    path = support.create_package(tmp_path / "ziel", root, "/programm", "2.8.0-beta.1", facts, result, json.loads((root / "gui-config.json").read_text(encoding="utf-8")), ["qrc:/qml/X.qml:3: Warnung"], sanitizer=clean)
    assert path.name.startswith("PDF-Tool-Support_") and path.suffix == ".zip"
    assert not list((tmp_path / "ziel").glob("*.partial"))
    with zipfile.ZipFile(path) as zf:
        names = sorted(zf.namelist())
        everything = "\n".join(zf.read(name).decode("utf-8") for name in names)
        diagnose = json.loads(zf.read("diagnose.json"))
    assert names == ["LIESMICH.txt", "bericht.txt", "diagnose.json", "einstellungen.json", "protokolle/fehler.log", "protokolle/stapel.log", "protokolle/stapel.log.1"]
    for secret in ("Muster", "muster.de", "Geheim", "V-4711", "%PDF", "BUERO-PC-07", "/home/max"):
        assert secret not in everything, secret
    assert "<Pfad>.xlsx" in everything and "<E-Mail>" in everything
    assert diagnose["app_version"] == "2.8.0-beta.1" and diagnose["facts"]["channel"] == "Stable"
    assert {check["key"] for check in diagnose["checks"]} >= {"config", "customers", "templates", "rules", "history"}
    assert diagnose["qml_messages"] == ["qrc:/qml/X.qml:3: Warnung"]


# --- Protokoll und Aufräumen -----------------------------------------------------------------------------------


def test_app_log_rotates_and_keeps_three_old_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(applog, "MAX_BYTES", 2000)
    try:
        applog.setup(tmp_path)
        log = applog.get("test")
        for index in range(400):
            log.info("Eintrag %d %s", index, "x" * 40)
        log.warning("Warnung")
        log.error("Fehler")
    finally:
        applog.close()
    files = sorted(path.name for path in tmp_path.glob("pdf-tool.log*"))
    assert files == ["pdf-tool.log", "pdf-tool.log.1", "pdf-tool.log.2", "pdf-tool.log.3"]
    text = (tmp_path / "pdf-tool.log").read_text(encoding="utf-8")
    assert "WARNING pdftool.test: Warnung" in text and "ERROR   pdftool.test: Fehler" in text
    assert all(path.stat().st_size <= 2200 for path in tmp_path.glob("pdf-tool.log*"))
    assert [p.name for p in applog.log_files(tmp_path)][:1] == ["pdf-tool.log"]


def test_cleanup_removes_only_own_old_temp_files(tmp_path: Path) -> None:
    temp, data, backups = tmp_path / "temp", tmp_path / "daten", tmp_path / "sicherungen"
    old = time.time() - 3 * 24 * 3600

    def anlegen(path: Path, alt: bool, folder: bool = False) -> Path:
        if folder:
            path.mkdir(parents=True)
            (path / "x").write_text("x")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
        if alt:
            os.utime(path, (old, old))
        return path

    own_old = [
        anlegen(temp / "pdf-tool-vorschau-abc", True, folder=True),
        anlegen(temp / "pdf-tool-logo-1.png", True),
        anlegen(data / ".~xyz.tmp", True),
        anlegen(data / ".gui-config-1.tmp", True),
        anlegen(data / "vorlagen" / ".~t.tmp", True),
        anlegen(data / "contract-history" / "a" / ".~h.tmp", True),
        anlegen(backups / ".~sicherung-1.partial", True),
    ]
    keep = [
        anlegen(temp / "pdf-tool-vorschau-neu", False, folder=True),  # jung: evtl. zweite Instanz
        anlegen(temp / "fremd.tmp", True),
        anlegen(temp / "andere-app-vorschau", True, folder=True),
        anlegen(data / "gui-config.json", True),
        anlegen(data / "vorlagen" / "t.json", True),
        anlegen(data / "notiz.tmp", True),
        anlegen(backups / "PDF-Tool-Sicherung_x.pdtbackup", True),
    ]
    removed = cleanup.cleanup_temp(data, backups, temp_dir=temp)
    assert sorted(removed) == sorted(path.name for path in own_old)
    assert not any(path.exists() for path in own_old) and all(path.exists() for path in keep)
