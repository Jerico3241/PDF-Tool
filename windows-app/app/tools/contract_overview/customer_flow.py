"""Kundenakte 2.0 in »Vertragsübersichten«: Wiedererkennung, Übernahme und Arbeitskopie.

Grundsätze:

* Kundenakte (``self.customers``) und Formular (Arbeitskopie) sind getrennt. Übernehmen
  füllt das Formular; Änderungen im Formular ändern die Kundenakte nie still. Nur
  »Als Kundenakte speichern« und »Kundenakte aktualisieren« schreiben bewusst zurück.
* Automatisch fortgeschrieben werden nur: zuletzt verwendet, letzte Excel, letzte PDF.
* Wiedererkannt wird ausschließlich über lokal gespeicherte E-Mail-Zuordnungen. Neue
  Zuordnungen entstehen nur nach einer bewussten Entscheidung (»Zuordnung merken«).
* Die Wiedererkennung blockiert nie die PDF-Erstellung – ein unbekannter Kunde ist normal.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import appstate
from appstate import DEFAULT_LOGO, FOOTER_EXPLICIT, FOOTER_FORMAT, HEADER_FORMAT, default_footer_rich, desktop_dir, footer_rich_from, header_rich_from
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

from . import customer_widgets
from .customers.matching import MatchKind, MatchResult, is_valid_email, normalize_email
from .customers.migration import LEGACY_KEY, open_store
from .customers.models import Customer, TextBlock
from .customers.repository import ORDER_RECENT, ORDERS, EmailConflict

CONFIG_ORDER = "kunden_sortierung"
CONFIG_AUTO = "kunden_auto_uebernehmen"
CONFIG_ACTIVE = "kunde_aktiv"
CONFIG_BASE_TEXTS = "kunde_texte_vorher"  # gültige Kopf-/Fußzeile vor den Texten der aktiven Kundenakte
# Formularwerte, die das Übernehmen einer Kundenakte (samt Vorlage) ändern kann
WORK_VARS = ("var_firma", "var_kd", "var_mail", "var_logo", "var_ziel", "var_name", "var_format", "var_breite", "var_titel", "var_untertitel", "var_vorlage")
CHANGE_LABELS = {
    "company": "Firmenname",
    "number": "Kundennummer",
    "emails": "E-Mail-Zuordnung",
    "logo": "Logo",
    "target_dir": "Zielordner",
    "template": "Vorlage",
    "header": "Kopfzeile",
    "footer": "Fußzeile",
}


def _same_path(a: str, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return str(a) == str(b)


def _key(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def header_of(customer: Customer) -> RichText | None:
    if customer.header is None:
        return None
    return RichText.from_storage(customer.header.text, customer.header.format, HEADER_STYLE, HEADER_ALIGN)


def footer_of(customer: Customer) -> RichText | None:
    """Eigene Fußzeile der Kundenakte – ``None`` ohne eigene (nie eine leere)."""
    if customer.footer is None or not customer.footer.text.strip():
        return None
    return RichText.from_storage(customer.footer.text, customer.footer.format, FOOTER_STYLE, FOOTER_ALIGN)


def _block(rich: RichText) -> TextBlock:
    return TextBlock(rich.text, rich.to_dict())


class CustomerFlow:
    """Kundenakten im Werkzeug »Vertragsübersichten« (Baustein des Hauptfensters)."""

    # Einrichtung ----------------------------------------------------------------------------
    def _init_customers(self, cfg: dict) -> None:
        folder = Path(appstate.CONFIG_FILE).parent
        had_legacy = LEGACY_KEY in cfg
        self.customers, self._customer_report = open_store(folder, cfg, Path(appstate.CONFIG_FILE))
        report = self._customer_report
        # Die alte Kundenhistorie bleibt nur in der Konfiguration, solange die Übernahme nicht gelang.
        self._legacy_dropped = had_legacy and (report is None or report.ok)
        if self._legacy_dropped:
            cfg.pop(LEGACY_KEY, None)
        order = cfg.get(CONFIG_ORDER)
        self.customer_order = order if order in ORDERS else ORDER_RECENT
        self.var_auto_customer = tk.BooleanVar(self, cfg.get(CONFIG_AUTO) is True)
        active = cfg.get(CONFIG_ACTIVE)
        self._active_customer_id: str | None = active if isinstance(active, str) and self.customers.get(active) else None
        self._match: MatchResult | None = None
        self._match_path = ""
        self._match_ignored: set[tuple[str, tuple[str, ...]]] = set()
        self._declined_emails: set[tuple[str, str]] = set()
        self._declined_save: set[tuple[str, str]] = set()
        # Kopf-/Fußzeile: Stand nach dem letzten Setzen durch die App (Vorlage, Kundenakte, Start).
        # Weicht der Editor davon ab, hat der Benutzer die Texte geändert – dann nie still überschreiben.
        self._text_baseline: tuple[RichText, RichText] | None = None
        self._customer_texts = False  # aktuelle Texte stammen aus der aktiven Kundenakte
        self._base_texts: tuple[RichText, RichText] | None = None  # gültige Texte davor
        base = cfg.get(CONFIG_BASE_TEXTS)
        if self._active_customer_id and isinstance(base, dict):
            self._customer_texts = True
            self._base_texts = (header_rich_from(base), footer_rich_from(base))
        self._undo_apply: dict | None = None
        self._undo_detach: str | None = None
        self._deleted_customer: Customer | None = None
        self._store_warned = False
        self.customer_page = None

    def _start_customers(self) -> None:
        """Nach dem Aufbau der Seiten: Ergebnis der Übernahme melden, Anzeige herstellen."""
        report = self._customer_report
        if self._legacy_dropped:
            self.persist()  # alte Historie aus gui-config.json entfernen (die Sicherung behält sie)
        if report is not None and report.ok and report.migrated:
            count = "1 Kunde wurde" if report.migrated == 1 else f"{report.migrated} Kunden wurden"
            backup = f" Eine Sicherung der bisherigen Einstellungen liegt unter »{report.backup.parent.name}\\{report.backup.name}«." if report.backup else ""
            self.notify("kunden_info", "success", f"{count} aus der bisherigen Kundenhistorie als Kundenakte übernommen.{backup}", title="Kundenakte 2.0", status=False)
        elif report is not None and not report.ok:
            self.notify(
                "kunden_info",
                "error",
                f"Die bisherige Kundenhistorie konnte nicht übernommen werden ({report.error}). Sie bleibt unverändert erhalten; beim nächsten Start wird es erneut versucht.",
                title="Übernahme nicht möglich",
                status=False,
            )
        if self.customers.load_error:
            self.notify("kunden_info", "warning", self.customers.load_error, title="Kundenakten", status=False)
        self._mark_text_baseline()
        self.refresh_customer_line()

    def customer_config(self) -> dict:
        data = {
            CONFIG_ORDER: self.customer_order,
            CONFIG_AUTO: bool(self.var_auto_customer.get()),
            CONFIG_ACTIVE: self._active_customer_id or "",
            CONFIG_BASE_TEXTS: None,
        }
        if self._active_customer_id and self._customer_texts and self._base_texts is not None:
            kopf, fuss = self._base_texts
            data[CONFIG_BASE_TEXTS] = {
                "kopfzeile": kopf.text,
                HEADER_FORMAT: kopf.to_dict(),
                "fusszeile": fuss.text,
                FOOTER_FORMAT: fuss.to_dict(),
                FOOTER_EXPLICIT: True,
            }
        return data

    # Zustand ----------------------------------------------------------------------------------
    def active_customer(self) -> Customer | None:
        return self.customers.get(self._active_customer_id)

    def _store_customers(self) -> bool:
        """Kundenakten speichern; ein Fehler wird einmal deutlich gemeldet (die Arbeit geht weiter)."""
        if self.customers.path is None:
            if not self._store_warned:
                self._store_warned = True
                self.notify("kunden_info", "warning", "Kundenakten können in dieser Sitzung nicht dauerhaft gespeichert werden. Änderungen gelten bis zum Beenden.", title="Kundenakten", status=False)
            return False
        if self.customers.save():
            self._store_warned = False
            return True
        if not self._store_warned:
            self._store_warned = True
            self.notify("kunde_info", "error", "Die Kundenakten konnten nicht gespeichert werden. Bitte prüfen, ob der Datenordner beschreibbar ist.", title="Speichern fehlgeschlagen")
        return False

    def customers_changed(self, detail: bool = True) -> None:
        """Nach jeder bewussten Änderung an Kundenakten: speichern und alle Anzeigen aktualisieren."""
        self._store_customers()
        if self._active_customer_id and self.customers.get(self._active_customer_id) is None:
            self._active_customer_id = None
            self._customer_texts = False
            self._base_texts = None
        page = self.customer_page
        if page is not None:
            if detail:
                page.refresh()
            else:
                page.refresh_list()
        self.refresh_customer_line()
        self._rematch()

    def _current_emails(self) -> list[str]:
        """Rechnungsempfänger der aktuellen Übersicht: eingetragene Adresse und Adressen der geprüften Excel."""
        found: list[str] = []
        for raw in [self.var_mail.get(), *self._analysis_mails()]:
            email = normalize_email(raw)
            if is_valid_email(email) and email not in found:
                found.append(email)
        return found

    def _analysis_mails(self) -> list[str]:
        excel = self.var_excel.get().strip()
        if self._analysis is None or self._analysis_path != excel or not self._analysis.get("ok"):
            return []
        return [str(mail) for mail in self._analysis.get("mails") or []]

    def _unknown_emails(self, customer: Customer) -> list[str]:
        """Adressen der Übersicht, die noch keiner Kundenakte gehören (und nicht abgelehnt wurden)."""
        return [email for email in self._current_emails() if not self.customers.owner_ids(email) and (customer.id, email) not in self._declined_emails]

    # Wiedererkennung ---------------------------------------------------------------------------------
    def _recognize_customer(self, path: str, result: dict, animate: bool = True) -> None:
        """Nach der Excel-Prüfung: bekannte Rechnungsempfänger suchen. Nie eine alte Analyse verwenden."""
        mails = [str(mail) for mail in result.get("mails") or []] if result.get("ok") else []
        self._match = self.customers.match(mails)
        self._match_path = path
        self._show_match(animate=animate, automatic=True)

    def _rematch(self) -> None:
        """Nach Änderungen an Zuordnungen: aktuelle Excel erneut gegen die Kundenakten prüfen."""
        excel = self.var_excel.get().strip()
        if self._match is None or self._match_path != excel:
            return
        self._match = self.customers.match(self._analysis_mails())
        self._show_match(animate=False, automatic=False)

    def _show_match(self, animate: bool = True, automatic: bool = False) -> None:
        match = self._match
        if match is None or self._match_path != self.var_excel.get().strip():
            self.hide_notice("kunde_match")
            return
        active = self.active_customer()
        ignored = (self._match_path, match.customer_ids) in self._match_ignored
        if match.kind is MatchKind.NONE:
            if active is None or ignored:
                self.hide_notice("kunde_match")
                return
            other = self._file_number_mismatch(active)
            if other:
                self._warn_number_mismatch(active, other, animate)
                return
            unknown = self._unknown_emails(active)
            if unknown:
                self._offer_emails(active, unknown, animate=animate, question=True)
            else:
                self.hide_notice("kunde_match")
            return
        if ignored:
            self.hide_notice("kunde_match")
            return
        if match.kind is MatchKind.SINGLE:
            customer = self.customers.get(match.customer_id)
            if customer is None:
                self.hide_notice("kunde_match")
                return
            if active is not None and active.id == customer.id:
                unknown = self._unknown_emails(customer)
                if unknown:
                    self._offer_emails(customer, unknown, animate=animate)
                else:
                    self.hide_notice("kunde_match")
                return
            if automatic and active is None and self.var_auto_customer.get() and not self._conflicting_values(customer):
                self.apply_customer(customer.id, automatic=True)
                return
            via = ", ".join(match.emails_of(customer.id))
            self.notify(
                "kunde_match",
                "info",
                f"{customer.label} – erkannt an {via}.",
                title="Bekannter Kunde gefunden",
                actions=(
                    ("Übernehmen", lambda: self.apply_customer(customer.id)),
                    ("Kundenakte", lambda: self.open_customer_record(customer.id)),
                    ("Ignorieren", self.ignore_match),
                ),
                status=False,
                animate=animate,
            )
            return
        candidates = [c for c in (self.customers.get(ident) for ident in match.customer_ids) if c is not None]
        names = ", ".join(f"„{c.label}“" for c in candidates[:3]) + (f" und {len(candidates) - 3} weitere" if len(candidates) > 3 else "")
        if match.kind is MatchKind.CONFLICT:
            message = f"Die Excel enthält Rechnungsempfänger, die verschiedenen bekannten Kunden zugeordnet sind. Betroffen: {names} – bitte den passenden Kunden auswählen."
            title = "Mehrere bekannte Kunden"
        else:
            message = f"Eine E-Mail-Adresse der Excel ist mehreren Kundenakten zugeordnet: {names}. Bitte den richtigen Kunden auswählen und die Kundenakten bei Gelegenheit zusammenführen."
            title = "Zuordnung nicht eindeutig"
        self.notify(
            "kunde_match",
            "warning",
            message,
            title=title,
            actions=(("Kunden auswählen …", lambda: self.pick_customer(match.customer_ids)), ("Ignorieren", self.ignore_match)),
            status=False,
            animate=animate,
        )

    def _warn_number_mismatch(self, customer: Customer, other: str, animate: bool = True) -> None:
        """Die Excel gehört offenbar zu einem anderen Kunden – nie still mit der aktiven Akte weiter."""
        self.notify(
            "kunde_match",
            "warning",
            f"In der Excel steht die Kundennummer {other}, die aktive Kundenakte ist „{customer.label}“. Für einen anderen Kunden die Kundenakte lösen oder »Neue Übersicht« wählen.",
            title="Excel passt nicht zur aktiven Kundenakte",
            actions=(("Kundenakte lösen", self.detach_customer), ("Ignorieren", self.ignore_match)),
            status=False,
            animate=animate,
        )

    def _file_number_mismatch(self, customer: Customer) -> str:
        """Kundennummer der geprüften Excel, wenn sie eindeutig ist und nicht zur Kundenakte passt."""
        excel = self.var_excel.get().strip()
        if self._analysis is None or self._analysis_path != excel or not customer.number:
            return ""
        numbers = [str(number) for number in self._analysis.get("kunden") or []]
        if len(numbers) == 1 and _key(numbers[0]) != _key(customer.number):
            return numbers[0]
        return ""

    def _conflicting_values(self, customer: Customer) -> bool:
        """Stehen im Formular bereits andere Kundendaten? Dann nie automatisch übernehmen."""
        firma, kd = self.var_firma.get().strip(), self.var_kd.get().strip()
        return bool(firma and _key(firma) != _key(customer.company)) or bool(kd and _key(kd) != _key(customer.number))

    def ignore_match(self) -> None:
        if self._match is not None:
            self._match_ignored.add((self._match_path, self._match.customer_ids))
        self.hide_notice("kunde_match")

    def _offer_emails(self, customer: Customer, emails: list[str], area: str = "kunde_match", animate: bool = True, question: bool = False) -> None:
        """Lernen nur nach bewusster Entscheidung: »Diese E-Mail künftig diesem Kunden zuordnen?«"""
        single = len(emails) == 1
        title = "Diese E-Mail künftig diesem Kunden zuordnen?" if single else "Diese E-Mail-Adressen künftig diesem Kunden zuordnen?"
        listed = ", ".join(emails)
        if question:
            message = f"Kein bekannter Kunde in der Excel. Gehört {listed} zur aktiven Kundenakte „{customer.label}“?"
        else:
            message = f"{listed} → „{customer.label}“. PDF Tool erkennt den Kunden dann in der nächsten Excel-Liste wieder."
        self.notify(
            area,
            "info",
            message,
            title=title,
            actions=(("Zuordnung merken", lambda: self.assign_emails(customer.id, emails)), ("Nicht zuordnen", lambda: self._decline_emails(customer.id, emails, area))),
            status=False,
            animate=animate,
        )

    def _decline_emails(self, customer_id: str, emails: list[str], area: str = "kunde_match") -> None:
        self._declined_emails.update((customer_id, email) for email in emails)
        self.hide_notice(area)

    def assign_emails(self, customer_id: str, emails: list[str], quiet: bool = False) -> list[str]:
        """Adressen künftig diesem Kunden zuordnen. Gehört eine schon einem anderen: der Benutzer entscheidet."""
        customer = self.customers.get(customer_id)
        if customer is None:
            return []
        added: list[str] = []
        for raw in emails:
            email = normalize_email(raw)
            if not is_valid_email(email) or email in customer.emails:
                continue
            try:
                self.customers.add_email(customer.id, email)
            except EmailConflict as conflict:
                answer = customer_widgets.ask_email_conflict(self, email, conflict.owners, customer.label)
                if answer == "cancel":
                    break
                if answer == "keep":
                    self._declined_emails.add((customer.id, email))
                    continue
                self.customers.add_email(customer.id, email, move=True)
            added.append(email)
        self.hide_notice("kunde_match")
        if added:
            self.customers_changed()
            if not quiet:
                self.notify("kunde_info", "success", f"{', '.join(added)} {'wird' if len(added) == 1 else 'werden'} künftig als Rechnungsempfänger von „{customer.label}“ erkannt.", title="Zuordnung gemerkt", auto_hide=8000)
        return added

    # Auswählen und Übernehmen -----------------------------------------------------------------------
    def pick_customer(self, candidates=None) -> None:
        """»Bekannten Kunden auswählen«: Suchdialog über alle (bzw. die angebotenen) Kundenakten."""
        if not len(self.customers):
            has_values = bool(self.var_firma.get().strip() or self.var_kd.get().strip())
            actions = (("Als Kundenakte speichern", self.save_as_customer),) if has_values else ()
            self.notify("kunde_info", "info", "Noch keine Kundenakten gespeichert. Eingetragene Kundendaten lassen sich als Kundenakte speichern – danach erkennt PDF Tool den Kunden wieder.", actions=actions, auto_hide=10000)
            return
        message = None
        if candidates:
            message = "Die Rechnungsempfänger der Excel gehören zu mehreren Kundenakten. Welcher Kunde ist gemeint?"
        chosen = customer_widgets.choose_customer(self, self.customers, candidates=list(candidates) if candidates else None, message=message)
        if chosen:
            self.apply_customer(chosen)

    def apply_customer(self, customer_id: str, automatic: bool = False) -> None:
        """Kundenakte in die Arbeitskopie übernehmen (rückgängig machbar). Die Kundenakte bleibt unverändert."""
        customer = self.customers.get(customer_id)
        if customer is None:
            return
        undo = self._working_snapshot()
        previous = self.active_customer()
        switching = previous is not None and previous.id != customer.id
        fresh = self._texts_fresh()
        # Stand der Excel-Prüfung vorher festhalten: Eine Vorlage mit anderen Regeln prüft neu.
        excel_mails = self._analysis_mails()
        unknown = self._unknown_emails(customer)
        excel = self._matching_excel(customer.id)
        hints: list[str] = []
        actions: list[tuple] = []
        # 1. Texte einer zuvor aktiven Kundenakte zurücknehmen, solange sie unverändert sind
        if fresh and self._customer_texts and self._base_texts is not None:
            self._set_texts(*self._base_texts)
        self._customer_texts = False
        self._base_texts = None
        # 2. Bevorzugte Vorlage (zuerst: die Angaben der Kundenakte haben Vorrang)
        if customer.template:
            entry = self.state.find_vorlage(customer.template)
            if entry is None:
                hints.append(f"Die bevorzugte Vorlage „{customer.template}“ gibt es nicht mehr.")
            elif customer.template_auto:
                self._apply_vorlage(entry, texts=fresh, quiet=True)
            elif self.var_vorlage.get().strip() != customer.template:
                actions.append((f"Vorlage „{customer.template}“ anwenden", lambda e=entry: self._apply_vorlage(e)))
        # 3. Stammdaten und Rechnungsempfänger
        for var, value in ((self.var_firma, customer.company), (self.var_kd, customer.number)):
            if value or switching:
                var.set(value)
        self._apply_customer_mail(customer, previous, excel_mails)
        # 4. Logo und Zielordner – nur wenn vorhanden, sonst bleibt der aktuelle Wert
        if customer.logo:
            if Path(customer.logo).is_file():
                self.var_logo.set(customer.logo)
            else:
                hints.append("Gespeichertes Logo wurde nicht gefunden – das aktuelle bleibt.")
        if customer.target_dir:
            if Path(customer.target_dir).is_dir():
                self.var_ziel.set(customer.target_dir)
            else:
                hints.append("Gespeicherter Zielordner ist nicht verfügbar – der aktuelle bleibt.")
        self.refresh_files()
        # 5. Kopf- und Fußzeile der Kundenakte: bei frischer Arbeit übernehmen, sonst nur anbieten
        own = customer.header is not None or footer_of(customer) is not None
        if own:
            if fresh:
                self._apply_own_texts(customer)
            else:
                hints.append("Kopf- und Fußzeile wurden in dieser Übersicht bereits geändert und bleiben.")
                actions.append(("Texte der Kundenakte verwenden", lambda: self.apply_customer_texts(customer.id)))
        if fresh:
            self._mark_text_baseline()
        self._active_customer_id = customer.id
        self._undo_apply = undo
        self.customers.touch(customer.id, excel=excel)
        self._store_customers()
        self.hide_notice("kunde_match")
        self.kd_required = False
        field = getattr(self.ui, "field_kd", None)
        if field is not None:
            field.set_error(False)
        self.refresh_customer_line()
        if self.customer_page is not None:
            self.customer_page.refresh()
        self.update_readiness()
        self.schedule_save()
        if not self.var_excel.get().strip() and customer.last_excel and Path(customer.last_excel).is_file():
            actions.append(("Letzte Excel verwenden", lambda path=customer.last_excel: self.use_excel(path)))
        actions.insert(0, ("Rückgängig", self.undo_apply_customer))
        message = customer.label + ("" if not hints else " · " + " ".join(hints))
        title = "Bekannter Kunde übernommen" if automatic else "Kundenakte übernommen"
        self.notify("kunde_info", "warning" if hints else "success", message, title=title, actions=tuple(actions), auto_hide=None if (hints or len(actions) > 1) else 10000)
        if not automatic:
            other = self._file_number_mismatch(customer)
            if other:
                self._warn_number_mismatch(customer, other)
            elif unknown:
                self._offer_emails(customer, unknown)

    def _apply_customer_mail(self, customer: Customer, previous: Customer | None, excel_mails: list[str]) -> None:
        """Rechnungsempfänger passend zur Excel: eindeutige eigene Adresse wählen, nie raten."""
        current = normalize_email(self.var_mail.get())
        stale = previous is not None and current in previous.emails  # Adresse des vorigen Kunden
        if len(excel_mails) > 1:
            own = [mail for mail in excel_mails if normalize_email(mail) in customer.emails]
            if len(own) == 1:
                self.var_mail.set(own[0])
            elif stale:
                self.var_mail.set("")
        elif excel_mails:
            if stale:
                self.var_mail.set("")  # die Adresse aus der Excel gilt
        elif customer.primary_email and (not current or stale):
            self.var_mail.set(customer.primary_email)
        elif stale:
            self.var_mail.set("")

    def _matching_excel(self, customer_id: str) -> str | None:
        """Die aktuelle Excel nur als »letzte Excel« merken, wenn sie diesem Kunden zugeordnet ist."""
        excel = self.var_excel.get().strip()
        match = self._match
        if match is None or self._match_path != excel or customer_id not in match.customer_ids or not Path(excel).is_file():
            return None
        return excel

    def apply_customer_texts(self, customer_id: str) -> None:
        """Kopf- und Fußzeile der Kundenakte bewusst übernehmen (auch nach eigenen Änderungen)."""
        customer = self.customers.get(customer_id)
        if customer is None:
            return
        before = (self.header_rich(), self.footer_rich())
        if not self._customer_texts:
            self._base_texts = before
        self._apply_own_texts(customer)
        self._mark_text_baseline()
        self.schedule_save()
        self.notify("kunde_info", "success", f"Kopf- und Fußzeile von „{customer.label}“ übernommen.", actions=(("Rückgängig", lambda: self._undo_texts(before)),), auto_hide=8000)

    def _undo_texts(self, texts: tuple[RichText, RichText]) -> None:
        self._set_texts(*texts)
        self._customer_texts = False
        self._base_texts = None
        self._mark_text_baseline()
        self.schedule_save()
        self.hide_notice("kunde_info")

    def _apply_own_texts(self, customer: Customer) -> None:
        header, footer = header_of(customer), footer_of(customer)
        if header is None and footer is None:
            return
        if self._base_texts is None:
            self._base_texts = (self.header_rich(), self.footer_rich())
        self._set_texts(header, footer)
        self._customer_texts = True

    def _set_texts(self, header: RichText | None, footer: RichText | None) -> None:
        # Eine leere Fußzeile ersetzt nie die gültige (Standard-Fußzeile bleibt erhalten).
        if header is not None:
            self._set_rich("txt_kopf", "_kopf_start", header)
        if footer is not None and not footer.is_blank():
            self._set_rich("txt_fuss", "_fuss_start", footer)

    def _mark_text_baseline(self) -> None:
        self._text_baseline = (self.header_rich(), self.footer_rich())

    def _texts_fresh(self) -> bool:
        """Kopf- und Fußzeile seit dem letzten Setzen durch die App unverändert?"""
        if self._text_baseline is None:
            return True
        return self.header_rich() == self._text_baseline[0] and self.footer_rich() == self._text_baseline[1]

    def _working_snapshot(self) -> dict:
        return {
            "vars": {name: getattr(self, name).get() for name in WORK_VARS},
            "texts": (self.header_rich(), self.footer_rich()),
            "regeln": [dict(regel) for regel in self.state.regeln],
            "active": self._active_customer_id,
            "baseline": self._text_baseline,
            "customer_texts": self._customer_texts,
            "base_texts": self._base_texts,
        }

    def _restore_snapshot(self, snapshot: dict) -> None:
        for name, value in snapshot["vars"].items():
            getattr(self, name).set(value)
        kopf, fuss = snapshot["texts"]
        if self.header_rich() != kopf:
            self._set_rich("txt_kopf", "_kopf_start", kopf)
        if self.footer_rich() != fuss:
            self._set_rich("txt_fuss", "_fuss_start", fuss)
        if snapshot["regeln"] != self.state.regeln:
            self.state.regeln = [dict(regel) for regel in snapshot["regeln"]]
            self.reload_regeln()
            self._recheck_excel()
        active = snapshot["active"]
        self._active_customer_id = active if self.customers.get(active) else None
        self._text_baseline = snapshot["baseline"]
        self._customer_texts = snapshot["customer_texts"]
        self._base_texts = snapshot["base_texts"]
        self.refresh_files()
        self.refresh_customer_line()
        self.update_readiness()
        self.persist()

    def undo_apply_customer(self) -> None:
        if self._undo_apply is None:
            return
        snapshot, self._undo_apply = self._undo_apply, None
        self._restore_snapshot(snapshot)
        self.hide_notice("kunde_info")
        self._show_match(animate=True, automatic=False)
        self.set_status("Übernahme der Kundenakte rückgängig gemacht.", "success")

    # Aktive Kundenakte ----------------------------------------------------------------------------------
    def detach_customer(self) -> None:
        """Kundenakte lösen: Die eingetragenen Angaben bleiben für diese Übersicht erhalten."""
        customer = self.active_customer()
        if customer is None:
            return
        self._active_customer_id = None
        self._customer_texts = False
        self._base_texts = None
        self._undo_detach = customer.id
        self.refresh_customer_line()
        self.schedule_save()
        self.notify("kunde_info", "info", f"„{customer.label}“ ist nicht mehr aktiv. Die eingetragenen Angaben bleiben für diese Übersicht erhalten.", actions=(("Rückgängig", self._undo_detach_customer),), auto_hide=8000)

    def _undo_detach_customer(self) -> None:
        ident, self._undo_detach = self._undo_detach, None
        if ident and self.customers.get(ident):
            self._active_customer_id = ident
            self.refresh_customer_line()
            self.schedule_save()
        self.hide_notice("kunde_info")

    def _leave_customer(self) -> dict | None:
        """Kundenakte verlassen (»Neue Übersicht«, »Kundendaten leeren«).

        Unveränderte Kopf-/Fußzeilen der Kundenakte werden durch die vorher gültigen ersetzt –
        sonst stünde der Text eines Kunden in der Übersicht des nächsten. Rückgabe: Zustand
        für »Rückgängig« (``None``, wenn nichts zu tun war).
        """
        state = {
            "active": self._active_customer_id,
            "texts": (self.header_rich(), self.footer_rich()),
            "baseline": self._text_baseline,
            "customer_texts": self._customer_texts,
            "base_texts": self._base_texts,
        }
        restored = False
        if self._customer_texts and self._base_texts is not None and self._texts_fresh():
            self._set_texts(*self._base_texts)
            restored = True
        self._active_customer_id = None
        self._customer_texts = False
        self._base_texts = None
        if restored:
            self._mark_text_baseline()
        self.hide_notice("kunde_match")
        self.refresh_customer_line()
        return state if (state["active"] or restored) else None

    def _return_to_customer(self, state: dict | None) -> None:
        if not state:
            return
        kopf, fuss = state["texts"]
        if self.header_rich() != kopf:
            self._set_rich("txt_kopf", "_kopf_start", kopf)
        if self.footer_rich() != fuss:
            self._set_rich("txt_fuss", "_fuss_start", fuss)
        active = state["active"]
        self._active_customer_id = active if self.customers.get(active) else None
        self._text_baseline = state["baseline"]
        self._customer_texts = state["customer_texts"]
        self._base_texts = state["base_texts"]
        self.refresh_customer_line()

    def open_customer_record(self, customer_id: str | None = None) -> None:
        """Kundenakte in der Ansicht »Kunden« öffnen."""
        ident = customer_id or self._active_customer_id
        if not ident or self.customers.get(ident) is None:
            return
        self.nav.navigate("customers")
        if self.customer_page is not None:
            self.customer_page.show_detail(ident)

    def open_active_customer(self) -> None:
        self.open_customer_record(self._active_customer_id)

    # Bewusst speichern ------------------------------------------------------------------------------------
    def save_or_update_customer(self) -> None:
        if self.active_customer() is not None:
            self.update_active_customer()
        else:
            self.save_as_customer()

    def _record_fields(self) -> dict:
        """Einstellungen der Arbeitskopie für eine neue Kundenakte (Standardwerte werden nicht gespeichert)."""
        logo = self.var_logo.get().strip()
        if not logo or not Path(logo).is_file() or _same_path(logo, DEFAULT_LOGO):
            logo = ""
        target = self.var_ziel.get().strip()
        if not target or _same_path(target, desktop_dir()):
            target = ""
        template = self.var_vorlage.get().strip()
        if not template or self.state.find_vorlage(template) is None:
            template = ""
        kopf, fuss = self.header_rich(), self.footer_rich()
        header = _block(kopf) if not kopf.is_blank() else None
        footer = _block(fuss) if not fuss.is_blank() and fuss != default_footer_rich() else None
        return {"logo": logo, "target_dir": target, "template": template, "header": header, "footer": footer}

    def save_as_customer(self) -> None:
        """Arbeitskopie als neue Kundenakte speichern – mit Rückfrage, ob die E-Mail gemerkt werden soll."""
        company, number = self.var_firma.get().strip(), self.var_kd.get().strip()
        if not company and not number:
            field = getattr(self.ui, "field_firma", None)
            if field is not None:
                field.focus()
            self.notify("kunde_info", "warning", "Bitte zuerst Firmenname oder Kundennummer eintragen.")
            return
        emails = self._current_emails()
        hints = []
        for other, reasons in self.customers.duplicates(company, number, emails)[:3]:
            why = ", ".join({"number": "gleiche Kundennummer", "company": "gleicher Firmenname", "email": "gleiche E-Mail"}[r] for r in reasons)
            hints.append(f"Mögliche Doppelung: „{other.label}“ ({why}). Später lassen sich Kundenakten zusammenführen.")
        ok, remember = customer_widgets.ask_new_customer(self, company, number, ", ".join(emails), hints)
        if not ok:
            return
        customer = self.customers.create(company, number, (), **self._record_fields())
        self._active_customer_id = customer.id
        self.customers.touch(customer.id, excel=self._current_excel())
        if remember and emails:
            self.assign_emails(customer.id, emails, quiet=True)
        self._declined_save.add((_key(company), _key(number)))
        self.customers_changed()
        self.schedule_save()
        self.notify("kunde_info", "success", f"„{customer.label}“ ist jetzt eine Kundenakte.", title="Kundenakte gespeichert", actions=(("Kundenakte öffnen", lambda: self.open_customer_record(customer.id)),), auto_hide=10000)

    def _current_excel(self) -> str | None:
        """Die geprüfte Excel der Übersicht (``None`` ohne gültige Prüfung)."""
        excel = self.var_excel.get().strip()
        checked = self._analysis is not None and self._analysis_path == excel and bool(self._analysis.get("ok"))
        return excel if checked and Path(excel).is_file() else None

    def _customer_differences(self, customer: Customer) -> list[tuple[str, str, str]]:
        """Abweichungen der Arbeitskopie von der Kundenakte als (Feld, bisher, neu)."""
        changes: list[tuple[str, str, str]] = []
        firma, kd = self.var_firma.get().strip(), self.var_kd.get().strip()
        if firma and firma != customer.company:
            changes.append(("company", customer.company or "–", firma))
        if kd and kd != customer.number:
            changes.append(("number", customer.number or "–", kd))
        unknown = self._unknown_emails(customer)
        if unknown:
            changes.append(("emails", ", ".join(customer.emails) or "keine", "+ " + ", ".join(unknown)))
        fields = self._record_fields()
        logo = self.var_logo.get().strip()
        if fields["logo"] and not _same_path(fields["logo"], customer.logo or ""):
            changes.append(("logo", Path(customer.logo).name if customer.logo else "keines", Path(logo).name))
        target = fields["target_dir"]
        if target and not _same_path(target, customer.target_dir or ""):
            changes.append(("target_dir", customer.target_dir or "keiner", target))
        if fields["template"] and fields["template"] != customer.template:
            changes.append(("template", customer.template or "keine", fields["template"]))
        kopf, fuss = self.header_rich(), self.footer_rich()
        stored_header = header_of(customer)
        if (stored_header is None and not kopf.is_blank()) or (stored_header is not None and stored_header != kopf):
            changes.append(("header", "eigene" if stored_header is not None else "keine eigene", "aktuelle Kopfzeile" if not kopf.is_blank() else "keine Kopfzeile"))
        stored_footer = footer_of(customer)
        if not fuss.is_blank():
            if (stored_footer is None and fuss != default_footer_rich()) or (stored_footer is not None and stored_footer != fuss):
                changes.append(("footer", "eigene" if stored_footer is not None else "keine eigene", "aktuelle Fußzeile"))
        return changes

    def update_active_customer(self) -> None:
        """»Kundenakte aktualisieren«: gewählte Abweichungen der Arbeitskopie bewusst zurückschreiben."""
        customer = self.active_customer()
        if customer is None:
            self.save_as_customer()
            return
        changes = self._customer_differences(customer)
        if not changes:
            self.notify("kunde_info", "info", f"„{customer.label}“ entspricht bereits den Angaben dieser Übersicht.", auto_hide=6000)
            return
        chosen = customer_widgets.ask_customer_update(self, customer.label, [(key, CHANGE_LABELS[key], old, new) for key, old, new in changes])
        if not chosen:
            return
        fields: dict = {}
        record = self._record_fields()
        kopf, fuss = self.header_rich(), self.footer_rich()
        for key in chosen:
            if key == "company":
                fields["company"] = self.var_firma.get().strip()
            elif key == "number":
                fields["number"] = self.var_kd.get().strip()
            elif key in ("logo", "target_dir", "template"):
                fields[key] = record[key]
            elif key == "header":
                fields["header"] = _block(kopf)
            elif key == "footer":
                fields["footer"] = _block(fuss)
        if fields:
            self.customers.update(customer.id, **fields)
        if "emails" in chosen:
            self.assign_emails(customer.id, self._unknown_emails(customer), quiet=True)
        if "header" in chosen or "footer" in chosen:
            # Die Texte gehören jetzt zur Kundenakte; die zuvor gültigen bleiben für den Wechsel gemerkt.
            if not self._customer_texts:
                self._base_texts = self._text_baseline
            self._customer_texts = True
            self._mark_text_baseline()
        self.customers_changed()
        self.schedule_save()
        names = ", ".join(CHANGE_LABELS[key] for key in chosen)
        self.notify("kunde_info", "success", f"„{customer.label}“: {names} gespeichert.", title="Kundenakte aktualisiert", auto_hide=8000)

    def create_customer_manually(self) -> None:
        """»Neue Kundenakte« in der Ansicht »Kunden« – unabhängig von der aktuellen Übersicht."""
        answer = customer_widgets.ask_customer_fields(self)
        if answer is None:
            return
        company, number, email = answer
        if not company and not number:
            self.notify("kunden_info", "warning", "Bitte Firmenname oder Kundennummer eintragen – eine leere Kundenakte wird nicht angelegt.", status=False)
            return
        email = normalize_email(email)
        if email and not is_valid_email(email):
            self.notify("kunden_info", "warning", f"„{email}“ ist keine gültige E-Mail-Adresse. Die Kundenakte wurde nicht angelegt.", status=False)
            return
        customer = self.customers.create(company, number, ())
        if email:
            self.assign_emails(customer.id, [email], quiet=True)
        self.customers_changed()
        if self.customer_page is not None:
            self.customer_page.show_detail(customer.id)
        self.notify("kunde_detail_info", "success", f"Kundenakte „{customer.label}“ angelegt.", auto_hide=6000, status=False)

    # Nach dem Erstellen ------------------------------------------------------------------------------------
    def _customer_after_pdf(self, path: Path) -> None:
        """Nur Metadaten fortschreiben; alles Weitere wird angeboten, nie still gespeichert."""
        customer = self.active_customer()
        if customer is not None:
            self.customers.touch(customer.id, excel=self.var_excel.get().strip() or None, pdf=str(path))
            self._store_customers()
            if self.customer_page is not None:
                self.customer_page.refresh()
            self.hide_notice("kunde_match")
            unknown = self._unknown_emails(customer)
            if unknown:
                self._offer_emails(customer, unknown, area="kunde_info")
                return
            changes = [key for key, _old, _new in self._customer_differences(customer)]
            if changes:
                names = ", ".join(CHANGE_LABELS[key] for key in changes)
                self.notify(
                    "kunde_info",
                    "info",
                    f"Diese Übersicht weicht von „{customer.label}“ ab: {names}.",
                    title="Kundenakte aktualisieren?",
                    actions=(("Kundenakte aktualisieren", self.update_active_customer), ("Nicht jetzt", lambda: self.hide_notice("kunde_info"))),
                    status=False,
                )
            return
        company, number = self.var_firma.get().strip(), self.var_kd.get().strip()
        key = (_key(company), _key(number))
        if (company or number) and key not in self._declined_save:
            self.notify(
                "kunde_info",
                "info",
                f"„{company or number}“ ist noch keine Kundenakte. Gespeichert erkennt PDF Tool den Kunden künftig an der Rechnungsempfänger-E-Mail wieder.",
                title="Als Kundenakte speichern?",
                actions=(("Als Kundenakte speichern", self.save_as_customer), ("Nicht jetzt", lambda: self._decline_save(key))),
                status=False,
            )

    def _decline_save(self, key: tuple[str, str]) -> None:
        self._declined_save.add(key)
        self.hide_notice("kunde_info")

    # Verwalten (Ansicht »Kunden«) ------------------------------------------------------------------------------
    def merge_customers(self, target_id: str, source_id: str) -> None:
        source = self.customers.get(source_id)
        if source is None or self.customers.get(target_id) is None:
            return
        label = source.label
        target = self.customers.merge(target_id, source_id)
        if self._active_customer_id == source_id:
            self._active_customer_id = target_id
        self.customers_changed()
        self.notify("kunde_detail_info", "success", f"„{label}“ wurde in „{target.label}“ übernommen. E-Mail-Adressen und Aktivität sind vereint.", title="Zusammengeführt", auto_hide=8000)

    def delete_customer(self, customer_id: str) -> None:
        """Löscht nur die Kundenakte und ihre Zuordnungen – nie PDF- oder Excel-Dateien."""
        customer = self.customers.delete(customer_id)
        if customer is None:
            return
        self._deleted_customer = customer
        if self._active_customer_id == customer_id:
            self._active_customer_id = None
            self._customer_texts = False
            self._base_texts = None
        if self.customer_page is not None:
            self.customer_page.show_list()
        self.customers_changed()
        self.schedule_save()
        self.notify("kunden_info", "success", f"Kundenakte „{customer.label}“ gelöscht. Erstellte PDF-Dateien und Excel-Listen bleiben erhalten.", actions=(("Rückgängig", self._undo_delete),), auto_hide=10000)

    def _undo_delete(self) -> None:
        customer, self._deleted_customer = self._deleted_customer, None
        if customer is None:
            return
        self.customers.restore(customer)
        self.customers_changed()
        self.hide_notice("kunden_info")
        self.set_status(f"Kundenakte „{customer.label}“ wiederhergestellt.", "success")

    # Anzeige in »Übersicht erstellen« ------------------------------------------------------------------------------
    def refresh_customer_line(self) -> None:
        ui = self.ui
        customer = self.active_customer()
        picker = getattr(ui, "kunde_picker", None)
        if picker is not None:
            picker.show_label(customer.label if customer else None)
            picker.set_placeholder("Firma, Kundennummer oder E-Mail suchen" if len(self.customers) else "Noch keine Kundenakten")
        area = getattr(ui, "kunde_active_area", None)
        if area is not None:
            if customer is None:
                area.collapse(animate=False)
            else:
                ui.kunde_active_title.configure(text=f"Kunde: {customer.label}")
                changes = [CHANGE_LABELS[key] for key, _o, _n in self._customer_differences(customer)]
                if changes:
                    ui.kunde_active_caption.configure(text="Geändert gegenüber der Kundenakte: " + ", ".join(changes))
                    ui.kunde_active_caption.set_color("caution")
                else:
                    ui.kunde_active_caption.configure(text="Kundenakte aktiv – Änderungen hier gelten nur für diese Übersicht.")
                    ui.kunde_active_caption.set_color("text2")
                area.expand(animate=False)
        button = getattr(ui, "btn_kunde_save", None)
        if button is not None:
            text = "Kundenakte aktualisieren" if customer is not None else "Als Kundenakte speichern"
            if button.text() != text:
                button.set_text(text)
            enabled = customer is not None or bool(self.var_firma.get().strip() or self.var_kd.get().strip())
            if button.enabled() != enabled:
                button.set_enabled(enabled)

    def find_customer(self) -> None:
        """Strg+F: in »Kunden« die Suche, sonst »Bekannten Kunden auswählen«."""
        if self.nav.current == "customers" and self.customer_page is not None:
            self.customer_page.focus_search()
        else:
            self.pick_customer()
