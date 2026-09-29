"""Übernahme der Kundenhistorie (bis Version 2.3, Schlüssel ``kunden`` in gui-config.json).

Ablauf beim ersten Start mit Version 2.4:

1. Sicherung: die aktuelle gui-config.json byte-genau nach ``sicherungen/`` kopieren
   und vergleichen. Ohne gültige Sicherung wird nichts verändert.
2. Jeder Eintrag der Historie wird eine Kundenakte mit neuer, stabiler ID.
   Rechnungsempfänger werden zu E-Mail-Zuordnungen; eine leere Fußzeile aus älteren
   Versionen wird nicht übernommen (die gültige Fußzeile bleibt), ebenso eine leere Kopfzeile.
3. ``kundenakten.json`` atomar schreiben und zur Kontrolle neu lesen.

Danach entfernt die App den alten Schlüssel aus der Konfiguration (die Sicherung behält
ihn). Steht er trotzdem wieder dort – etwa nach einem Wechsel zurück auf 2.3 –, werden nur
Einträge ergänzt, die es als Kundenakte noch nicht gibt; gelöschte Kundenakten kehren so
nicht zurück, und nichts wird doppelt angelegt.

Schlägt ein Schritt fehl, bleibt die alte Historie unverändert in der Konfiguration
und die Übernahme wird beim nächsten Start erneut versucht.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .matching import split_emails
from .models import Customer, TextBlock, new_id, now_iso
from .repository import FILE_NAME, CustomerStore

LEGACY_KEY = "kunden"
BACKUP_DIR = "sicherungen"
ORIGIN = "kundenhistorie"


@dataclass
class MigrationReport:
    migrated: int = 0
    skipped: int = 0
    backup: Path | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def customer_from_legacy(entry: dict, stamp: str) -> Customer | None:
    """Ein Eintrag der alten Kundenhistorie als Kundenakte (``None`` ohne Firma und Kundennummer)."""
    if not isinstance(entry, dict):
        return None
    company = _text(entry.get("firmenname")).strip()
    number = _text(entry.get("kundennummer")).strip() if not isinstance(entry.get("kundennummer"), (int, float)) else str(entry.get("kundennummer"))
    if not company and not number:
        return None
    recipient = _text(entry.get("rechnungsempfaenger")).strip()
    emails = split_emails(recipient)
    note = ""
    if recipient and not emails:
        note = f"Rechnungsempfänger aus der bisherigen Kundenhistorie: {recipient}"
    header = None
    kopf = entry.get("kopfzeile")
    if isinstance(kopf, str) and kopf.strip():
        fmt = entry.get("kopfzeile_format")
        header = TextBlock(kopf, fmt if isinstance(fmt, dict) else None)
    footer = None
    fuss = entry.get("fusszeile")
    if isinstance(fuss, str) and fuss.strip():  # leere Altwerte löschen nie die gültige Fußzeile
        fmt = entry.get("fusszeile_format")
        footer = TextBlock(fuss, fmt if isinstance(fmt, dict) else None)
    return Customer(
        id=new_id(),
        company=company,
        number=number,
        emails=emails,
        note=note,
        logo=_text(entry.get("logo")).strip(),
        header=header,
        footer=footer,
        last_excel=_text(entry.get("excel")).strip(),
        last_pdf=_text(entry.get("pdf")).strip(),
        created_at=stamp,
        origin=ORIGIN,
    )


def customers_from_legacy(entries) -> tuple[list[Customer], int]:
    stamp = now_iso()
    customers: list[Customer] = []
    skipped = 0
    for entry in entries if isinstance(entries, list) else []:
        customer = customer_from_legacy(entry, stamp)
        if customer is None:
            skipped += 1
        else:
            customers.append(customer)
    return customers, skipped


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup_config(config: dict, config_file: Path | None, folder: Path) -> Path:
    """Sicherung vor der Übernahme: byte-genaue Kopie der Konfiguration (geprüft)."""
    target_dir = folder / BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"gui-config-vor-kundenakte-{time.strftime('%Y%m%d-%H%M%S')}.json"
    if config_file is not None and Path(config_file).is_file():
        shutil.copy2(config_file, target)
        if _digest(target) != _digest(Path(config_file)):
            raise OSError("Die Sicherung weicht vom Original ab.")
    else:
        target.write_text(json.dumps({LEGACY_KEY: config.get(LEGACY_KEY)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _identity(customer: Customer) -> tuple[str, str]:
    """Firmenname und Kundennummer – wie die Kundenhistorie bis 2.3 ihre Einträge unterschied."""
    return (" ".join(customer.company.split()).casefold(), customer.number.strip().casefold())


def _verified(path: Path, customers: list[Customer]) -> CustomerStore:
    """Schreiben und zur Kontrolle neu lesen."""
    if not CustomerStore(path, customers).save():
        raise OSError("kundenakten.json konnte nicht geschrieben werden.")
    check = CustomerStore.load(path)
    if sorted(c.id for c in check.all()) != sorted(c.id for c in customers):
        raise OSError("Die gespeicherten Kundenakten weichen von der Übernahme ab.")
    return check


def open_store(folder: Path, config: dict, config_file: Path | None = None) -> tuple[CustomerStore, MigrationReport | None]:
    """Kundenakten laden – beim ersten Start mit Version 2.4 aus der alten Historie übernehmen.

    Rückgabe: Speicher und Bericht (``None``, wenn nichts zu übernehmen war). Nur wenn der
    Bericht einen Fehler meldet, muss die alte Historie in der Konfiguration bleiben.
    """
    folder = Path(folder)
    path = folder / FILE_NAME
    store = CustomerStore.load(path)
    legacy = config.get(LEGACY_KEY)
    if not isinstance(legacy, list) or not legacy:
        return store, None
    if store.exists():
        return _import_leftovers(store, legacy, config, config_file, folder)
    report = MigrationReport()
    try:
        report.backup = backup_config(config, config_file, folder)
        customers, report.skipped = customers_from_legacy(legacy)
        check = _verified(path, customers)
    except OSError as exc:
        report.error = str(exc) or exc.__class__.__name__
        for leftover in (path, path.with_name(path.name + ".bak")):
            try:
                leftover.unlink()
            except OSError:
                pass
        # Ohne Datei: diese Sitzung arbeitet ohne gespeicherte Kundenakten; die Historie bleibt.
        return CustomerStore(None), report
    report.migrated = len(customers)
    return check, report


def _import_leftovers(store: CustomerStore, legacy: list, config: dict, config_file: Path | None, folder: Path) -> tuple[CustomerStore, MigrationReport | None]:
    """Historie neben vorhandenen Kundenakten: nur Fehlendes ergänzen, nichts doppelt anlegen.

    Bekannte Kunden (gleicher Firmenname und gleiche Kundennummer) erhalten höchstens
    Adressen, die noch keiner Kundenakte gehören – bestehende Zuordnungen bleiben unberührt.
    """
    customers, skipped = customers_from_legacy(legacy)
    known = {_identity(customer): customer for customer in store.all()}
    new: list[Customer] = []
    extra: dict[str, list[str]] = {}
    for customer in customers:
        existing = known.get(_identity(customer))
        if existing is None:
            new.append(customer)
            known[_identity(customer)] = customer
            continue
        if existing in new:
            continue
        for email in customer.emails:
            if email not in existing.emails and not store.owner_ids(email) and email not in extra.get(existing.id, []):
                extra.setdefault(existing.id, []).append(email)
    if not new and not extra:
        return store, None
    report = MigrationReport(skipped=skipped)
    try:
        report.backup = backup_config(config, config_file, folder)
        merged = [replace(c, emails=c.emails + extra.get(c.id, [])) for c in store.all()] + new
        check = _verified(store.path, merged)  # type: ignore[arg-type]
    except OSError as exc:
        report.error = str(exc) or exc.__class__.__name__
        return store, report
    report.migrated = len(new)
    return check, report
