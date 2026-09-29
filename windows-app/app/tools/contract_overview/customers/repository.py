"""Lokaler Speicher der Kundenakten – ``kundenakten.json`` im Datenordner.

Aufbau: ``{"schema_version": 2, "customers": [...]}``. Geschrieben wird atomar
(temporäre Datei, dann Ersetzen); der vorige Stand bleibt als ``.bak`` erhalten
und wird gelesen, falls die Hauptdatei fehlt oder beschädigt ist. Eine unlesbare
Datei wird vor dem nächsten Schreiben beiseitegelegt, nie überschrieben.

Die Klasse kennt keine Oberfläche. Eine spätere Datenbank könnte dieselbe
Schnittstelle bedienen.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .matching import MatchResult, is_valid_email, match_emails, normalize_email
from .models import SCHEMA_VERSION, Customer, TextBlock, new_id, now_iso, parse_time

FILE_NAME = "kundenakten.json"
ORDER_RECENT = "recent"
ORDER_COMPANY = "company"
ORDER_NUMBER = "number"
ORDERS = (ORDER_RECENT, ORDER_COMPANY, ORDER_NUMBER)
EDITABLE = {"company", "number", "note", "logo", "target_dir", "template", "template_auto", "header", "footer"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class EmailConflict(Exception):
    """Die Adresse gehört bereits einer anderen Kundenakte – der Benutzer entscheidet."""

    def __init__(self, email: str, owners: list[Customer]) -> None:
        self.email = email
        self.owners = owners
        names = ", ".join(f"„{owner.label}“" for owner in owners)
        super().__init__(f"{email} ist bereits {names} zugeordnet.")


def _key(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def _natural(text: str) -> tuple:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", text or "") if part)


def _moment(customer: Customer) -> datetime:
    return parse_time(customer.last_used_at) or parse_time(customer.created_at) or _EPOCH


def _settings_moment(customer: Customer) -> datetime:
    return parse_time(customer.updated_at) or parse_time(customer.last_used_at) or parse_time(customer.created_at) or _EPOCH


class CustomerStore:
    def __init__(self, path: Path | None = None, customers: Iterable[Customer] = ()) -> None:
        self.path = Path(path) if path else None
        self._customers: dict[str, Customer] = {}
        self._owners: dict[str, list[str]] = {}
        self.load_error = ""
        self.persisted = False  # Datei gelesen oder erfolgreich geschrieben
        for customer in customers:
            self._customers[customer.id] = customer
        self._reindex()

    # Laden und Speichern ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "CustomerStore":
        path = Path(path)
        backup = path.with_name(path.name + ".bak")
        errors: list[str] = []
        for candidate in (path, backup):
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("customers"), list):
                    raise ValueError("unbekanntes Format")
            except (OSError, ValueError) as exc:
                errors.append(f"{candidate.name}: {exc}")
                continue
            customers = [c for c in (Customer.from_dict(raw) for raw in data["customers"]) if c is not None]
            unique: dict[str, Customer] = {}
            for customer in customers:
                unique.setdefault(customer.id, customer)
            store = cls(path, unique.values())
            store.persisted = True
            if candidate is backup:
                store.load_error = "Die Kundenakten wurden aus der Sicherung (kundenakten.json.bak) geladen."
            if errors:
                store._set_aside(path)
            return store
        store = cls(path)
        if errors:
            store.load_error = "Die Kundenakten konnten nicht gelesen werden: " + "; ".join(errors)
            store._set_aside(path)
        return store

    def _set_aside(self, path: Path) -> None:
        """Unlesbare Datei aufbewahren, bevor ein neuer Stand geschrieben wird."""
        if not path.is_file():
            return
        target = path.with_name(f"{path.stem}.defekt-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
        try:
            shutil.copy2(path, target)
        except OSError:
            pass

    def exists(self) -> bool:
        return bool(self.path) and (self.path.is_file() or self.path.with_name(self.path.name + ".bak").is_file())  # type: ignore[union-attr]

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "customers": [customer.to_dict() for customer in self._customers.values()]}

    def save(self) -> bool:
        """Atomar schreiben. Rückgabe ``False`` bei Schreibfehlern (der Speicher bleibt unverändert)."""
        if self.path is None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix=".kundenakten-", suffix=".tmp", dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                if self.path.is_file():
                    try:
                        shutil.copy2(self.path, self.path.with_name(self.path.name + ".bak"))
                    except OSError:
                        pass
                os.replace(temp, self.path)
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        except OSError:
            return False
        self.persisted = True
        return True

    # Lesen -------------------------------------------------------------------------------
    def _reindex(self) -> None:
        owners: dict[str, list[str]] = {}
        for customer in self._customers.values():
            for email in customer.emails:
                owners.setdefault(email, []).append(customer.id)
        self._owners = owners

    def __len__(self) -> int:
        return len(self._customers)

    def all(self) -> list[Customer]:
        return list(self._customers.values())

    def get(self, customer_id: str | None) -> Customer | None:
        return self._customers.get(customer_id or "")

    def owner_ids(self, email: str) -> list[str]:
        return list(self._owners.get(normalize_email(email), ()))

    def owners(self, email: str) -> list[Customer]:
        return [self._customers[ident] for ident in self.owner_ids(email)]

    def match(self, emails: Iterable[str]) -> MatchResult:
        return match_emails(emails, self.owner_ids)

    def ambiguous_emails(self) -> dict[str, list[str]]:
        """Adressen, die mehreren Kundenakten zugeordnet sind (nur aus übernommenen Altdaten möglich)."""
        return {email: list(ids) for email, ids in self._owners.items() if len(ids) > 1}

    def search(self, query: str, customers: Iterable[Customer] | None = None) -> list[Customer]:
        """Alle Suchbegriffe müssen in Firmenname, Kundennummer oder einer E-Mail vorkommen."""
        items = list(self._customers.values()) if customers is None else list(customers)
        terms = _key(query).split()
        if not terms:
            return items
        found = []
        for customer in items:
            haystack = " ".join([_key(customer.company), _key(customer.number), *customer.emails])
            if all(term in haystack for term in terms):
                found.append(customer)
        return found

    def ordered(self, order: str = ORDER_RECENT, customers: Iterable[Customer] | None = None) -> list[Customer]:
        items = list(self._customers.values()) if customers is None else list(customers)
        if order == ORDER_COMPANY:
            return sorted(items, key=lambda c: (_key(c.company) or "￿", _natural(c.number)))
        if order == ORDER_NUMBER:
            return sorted(items, key=lambda c: (_natural(c.number) or ("￿",), _key(c.company)))
        # Zuletzt verwendet; ohne Zeitstempel (Altdaten) bleibt die gespeicherte Reihenfolge.
        return sorted(items, key=_moment, reverse=True)

    def duplicates(self, company: str = "", number: str = "", emails: Iterable[str] = (), exclude: str | None = None) -> list[tuple[Customer, list[str]]]:
        """Mögliche Doppelungen als Hinweis – gleiche Kundennummer, gleicher Firmenname oder E-Mail."""
        wanted_number = _key(number)
        wanted_company = _key(company)
        wanted_emails = {normalize_email(email) for email in emails if normalize_email(email)}
        found: list[tuple[Customer, list[str]]] = []
        for customer in self._customers.values():
            if customer.id == exclude:
                continue
            reasons = []
            if wanted_number and _key(customer.number) == wanted_number:
                reasons.append("number")
            if wanted_company and _key(customer.company) == wanted_company:
                reasons.append("company")
            if wanted_emails & set(customer.emails):
                reasons.append("email")
            if reasons:
                found.append((customer, reasons))
        return found

    # Ändern ------------------------------------------------------------------------------
    def _conflicts(self, email: str, customer_id: str | None) -> list[Customer]:
        return [owner for owner in self.owners(email) if owner.id != customer_id]

    def create(self, company: str = "", number: str = "", emails: Iterable[str] = (), **fields) -> Customer:
        """Neue Kundenakte. Adressen anderer Kundenakten lösen ``EmailConflict`` aus (nichts wird angelegt)."""
        checked: list[str] = []
        for raw in emails:
            email = normalize_email(raw)
            if not is_valid_email(email):
                raise ValueError(f"Keine gültige E-Mail-Adresse: {raw}")
            owners = self._conflicts(email, None)
            if owners:
                raise EmailConflict(email, owners)
            if email not in checked:
                checked.append(email)
        stamp = now_iso()
        customer = Customer(id=new_id(), company=company.strip(), number=number.strip(), emails=checked, created_at=stamp, updated_at=stamp)
        self._apply(customer, fields)
        self._customers[customer.id] = customer
        self._reindex()
        return customer

    def _apply(self, customer: Customer, fields: dict) -> None:
        for name, value in fields.items():
            if name not in EDITABLE:
                raise KeyError(name)
            if name in ("header", "footer"):
                if value is not None and not isinstance(value, TextBlock):
                    raise TypeError(name)
                if name == "footer" and value is not None and not value.text.strip():
                    value = None  # leere Fußzeile ersetzt nie die gültige
                setattr(customer, name, value)
            elif name == "template_auto":
                customer.template_auto = bool(value)
            else:
                setattr(customer, name, str(value or "").strip() if name != "note" else str(value or ""))

    def update(self, customer_id: str, **fields) -> Customer:
        customer = self._customers[customer_id]
        self._apply(customer, fields)
        customer.updated_at = now_iso()
        return customer

    def delete(self, customer_id: str) -> Customer | None:
        """Entfernt nur die Kundenakte und ihre Zuordnungen – keine Dateien."""
        customer = self._customers.pop(customer_id, None)
        self._reindex()
        return customer

    def restore(self, customer: Customer) -> Customer:
        """Gelöschte Kundenakte zurückholen (»Rückgängig«). Adressen, die inzwischen einer
        anderen Kundenakte gehören, bleiben dort."""
        if customer.id in self._customers:
            return self._customers[customer.id]
        customer.emails = [email for email in customer.emails if not self._owners.get(email)]
        self._customers[customer.id] = customer
        self._reindex()
        return customer

    def add_email(self, customer_id: str, email: str, move: bool = False) -> bool:
        """Adresse zuordnen. Gehört sie einer anderen Kundenakte: ``EmailConflict`` oder – mit
        ``move`` – verschieben. Rückgabe ``False``, wenn die Adresse schon zugeordnet war."""
        customer = self._customers[customer_id]
        email = normalize_email(email)
        if not is_valid_email(email):
            raise ValueError(f"Keine gültige E-Mail-Adresse: {email}")
        owners = self._conflicts(email, customer_id)
        if owners and not move:
            raise EmailConflict(email, owners)
        for owner in owners:
            owner.emails = [known for known in owner.emails if known != email]
            owner.updated_at = now_iso()
        if email in customer.emails:
            self._reindex()
            return bool(owners)
        customer.emails.append(email)
        customer.updated_at = now_iso()
        self._reindex()
        return True

    def remove_email(self, customer_id: str, email: str) -> bool:
        customer = self._customers[customer_id]
        email = normalize_email(email)
        if email not in customer.emails:
            return False
        customer.emails = [known for known in customer.emails if known != email]
        customer.updated_at = now_iso()
        self._reindex()
        return True

    def make_primary(self, customer_id: str, email: str) -> None:
        customer = self._customers[customer_id]
        email = normalize_email(email)
        if email in customer.emails:
            customer.emails = [email] + [known for known in customer.emails if known != email]
            customer.updated_at = now_iso()

    def touch(self, customer_id: str, excel: str | None = None, pdf: str | None = None) -> None:
        """Automatische Metadaten: zuletzt verwendet, letzte Excel, letzte PDF (nur Pfade)."""
        customer = self._customers.get(customer_id)
        if customer is None:
            return
        customer.last_used_at = now_iso()
        if excel:
            customer.last_excel = str(excel)
        if pdf:
            customer.last_pdf = str(pdf)

    def merge(self, target_id: str, source_id: str) -> Customer:
        """``source`` in ``target`` überführen: Adressen vereinen, neuere gültige Einstellungen
        bevorzugen, jüngste Aktivität behalten. Danach gibt es nur noch ``target``."""
        if target_id == source_id:
            raise ValueError("Eine Kundenakte kann nicht mit sich selbst zusammengeführt werden.")
        target = self._customers[target_id]
        source = self._customers[source_id]
        before = replace(target)  # Werte vor dem Zusammenführen (target wird schrittweise geändert)
        target.emails = target.emails + [email for email in source.emails if email not in target.emails]
        target.company = target.company or source.company
        target.number = target.number or source.number
        if source.note.strip() and source.note.strip() not in target.note:
            target.note = "\n".join(part for part in (target.note.strip(), source.note.strip()) if part)
        newer, older = (source, before) if _settings_moment(source) > _settings_moment(before) else (before, source)
        for name in ("logo", "target_dir", "template"):
            setattr(target, name, getattr(newer, name) or getattr(older, name))
        target.template_auto = newer.template_auto if newer.template else older.template_auto
        target.header = newer.header if newer.header is not None else older.header
        target.footer = newer.footer if newer.footer is not None else older.footer
        recent, other = (source, before) if _moment(source) > _moment(before) else (before, source)
        target.last_excel = recent.last_excel or other.last_excel
        target.last_pdf = recent.last_pdf or other.last_pdf
        target.last_used_at = recent.last_used_at or other.last_used_at
        created = [moment for moment in (parse_time(before.created_at), parse_time(source.created_at)) if moment]
        if created:
            target.created_at = min(created).isoformat(timespec="microseconds")
        target.updated_at = now_iso()
        del self._customers[source_id]
        self._reindex()
        return target
