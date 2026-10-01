"""Support-Paket: eine ZIP-Datei, die der Benutzer bei Bedarf selbst weitergibt.

Inhalt (alles anonymisiert bzw. bereinigt, siehe ``sanitize``):

* ``bericht.txt`` – Systeminformationen und Ergebnis der Datenprüfung, lesbar;
* ``diagnose.json`` – dasselbe maschinenlesbar, dazu Meldungen der Oberfläche (QML);
* ``einstellungen.json`` – Einstellungen ohne persönliche Inhalte (Schalter, Zahlen, Anzahl);
* ``protokolle/…`` – Protokolle der App, bereinigt (Pfade zu Dokumenten, Benutzerordner,
  Benutzer- und Computername, E-Mail-Adressen entfernt), höchstens 2 MB je Datei;
* ``LIESMICH.txt`` – was enthalten ist und was nie.

Nie enthalten: Kundenakten und Vertragsstände, Vertragsinhalte, Vorlagen- oder Regelwerkstexte,
Kopf- und Fußzeilen, Passwörter, PDF- oder Excel-Dateien und -Inhalte, Logos. Nichts wird
gesendet – das Paket bleibt auf diesem PC, bis der Benutzer es selbst weitergibt.
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .applog import log_files
from .checks import Check, summary
from .info import Fact
from .sanitize import Sanitizer, anonymize_config, sensitive_terms

PREFIX = "PDF-Tool-Support"
MAX_LOG = 2 * 1024 * 1024
README = """Support-Paket von PDF Tool
==========================

Dieses Paket hilft bei der Fehlersuche. Es wurde auf diesem PC erstellt und wird nicht
automatisch versendet – geben Sie es nur selbst und nur bei Bedarf weiter.

Enthalten:
* bericht.txt – Version, Windows, Module und Ergebnis der Datenprüfung
* diagnose.json – dieselben Angaben maschinenlesbar
* einstellungen.json – Einstellungen ohne persönliche Inhalte (nur Schalter, Zahlen und Anzahlen)
* protokolle/ – Protokolle der App, bereinigt

Bereinigt bzw. nie enthalten:
* Pfade zu Dokumenten (als <Pfad>), Benutzerordner (%USERPROFILE%), Benutzer- und Computername,
  E-Mail-Adressen
* Kundenakten, Vertragsstände und Vertragsinhalte
* Texte von Vorlagen, Regelwerken, Kopf- und Fußzeilen
* Passwörter
* PDF- und Excel-Dateien und deren Inhalte, Logos
"""


def _tail(path: Path, limit: int = MAX_LOG) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            data = handle.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if size > limit:
        text = "[… gekürzt – nur das Ende der Datei …]\n" + text.split("\n", 1)[-1]
    return text


def report_text(app_version: str, facts: list[Fact], checks: list[Check], qml: list[str], created: str) -> str:
    status, verdict = summary(checks)
    lines = [f"PDF Tool – Diagnosebericht ({created})", "", "Systeminformationen", "-------------------"]
    lines += [f"{fact.label}: {fact.value}" for fact in facts]
    lines += ["", f"Datenprüfung: {verdict}", "------------"]
    marks = {"ok": "OK     ", "info": "Info   ", "warning": "Hinweis", "error": "FEHLER "}
    lines += [f"[{marks.get(check.status, check.status)}] {check.label}: {check.detail}" for check in checks]
    lines += ["", f"Meldungen der Oberfläche (QML): {len(qml)}"]
    lines += [f"  {message}" for message in qml[:50]]
    return "\n".join(lines) + "\n"


def create_package(
    target_folder: str | os.PathLike,
    data_dir: str | os.PathLike,
    install_dir: str | os.PathLike,
    app_version: str,
    facts: list[Fact],
    checks: list[Check],
    cfg: dict,
    qml_messages: list[str] | None = None,
    extra_logs: list[Path] | None = None,
    sanitizer: Sanitizer | None = None,
    now: datetime | None = None,
) -> Path:
    """Support-Paket schreiben (atomar). Rückgabe: Pfad der ZIP-Datei. Fehler: ``OSError``."""
    folder = Path(target_folder)
    when = (now or datetime.now()).astimezone()
    clean = sanitizer or Sanitizer(install_dir=install_dir, data_dir=data_dir)
    clean.add_terms(sensitive_terms(data_dir))
    created = when.isoformat(timespec="seconds")
    safe_facts = [Fact(fact.key, fact.label, clean.anonymize(fact.value)) for fact in facts]
    safe_checks = [Check(check.key, check.label, check.status, clean.redact(check.detail)) for check in checks]
    qml = [clean.redact(message) for message in (qml_messages or [])][:200]
    diagnose = {
        "app_version": app_version,
        "created_at": created,
        "facts": {fact.key: fact.value for fact in safe_facts},
        "checks": [asdict(check) for check in safe_checks],
        "qml_messages": qml,
    }
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{PREFIX}_{when.strftime('%Y-%m-%d_%H-%M-%S')}.zip"
    number = 2
    while target.exists():
        target = folder / f"{PREFIX}_{when.strftime('%Y-%m-%d_%H-%M-%S')}_{number}.zip"
        number += 1
    handle, temp = tempfile.mkstemp(prefix=".~support-", suffix=".partial", dir=str(folder))
    try:
        with os.fdopen(handle, "w+b") as stream:
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("LIESMICH.txt", README)
                archive.writestr("bericht.txt", report_text(app_version, safe_facts, safe_checks, qml, created))
                archive.writestr("diagnose.json", json.dumps(diagnose, ensure_ascii=False, indent=1))
                archive.writestr("einstellungen.json", json.dumps(anonymize_config(cfg), ensure_ascii=False, indent=1))
                for path in [*log_files(data_dir), *(extra_logs or [])]:
                    if path.is_file():
                        archive.writestr(f"protokolle/{path.name}", clean.redact(_tail(path)))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    return target
