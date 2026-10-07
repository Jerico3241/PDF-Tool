"""Kundenakte in »Vertragsübersichten«: Wiedererkennung, Übernahme, Arbeitskopie und die Ansicht
»Kunden« (in QML: ``Customers``).

Die Kundenakte ist ein optionales Modul (Einstellungen → Vertragsübersichten → »Kundenakte
verwenden«, Standard: aus – auch nach einem Update). Ausgeschaltet gilt:

* Die Kundenakten werden nicht geladen: ``customers`` ist dann ein leerer Speicher ohne
  Datei, der nie gelesen und nie geschrieben wird. Die Datei bleibt unangetastet.
* Kein Abgleich der Rechnungsempfänger, keine Übernahme, kein automatisches Fortschreiben,
  keine Ansicht »Kunden« und keine Kunden-Elemente in »Übersicht erstellen« und im Stapel.
* Einschalten lädt das Modul ohne Neustart, Ausschalten blendet alles sofort aus –
  vorhandene Daten bleiben immer erhalten.

Grundsätze bei eingeschalteter Kundenakte (unverändert seit 2.4):

* Kundenakte und Formular (Arbeitskopie) sind getrennt. Übernehmen füllt das Formular;
  Änderungen im Formular ändern die Kundenakte nie still. Nur »Als Kundenakte speichern« und
  »Kundenakte aktualisieren« schreiben bewusst zurück.
* Automatisch fortgeschrieben werden nur: zuletzt verwendet, letzte Excel, letzte PDF.
* Wiedererkannt wird ausschließlich über lokal gespeicherte E-Mail-Zuordnungen. Neue
  Zuordnungen entstehen nur nach einer bewussten Entscheidung (»Zuordnung merken«).
* Die Wiedererkennung blockiert nie die PDF-Erstellung – ein unbekannter Kunde ist normal.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Property, QObject, Signal, Slot

import appstate
from appstate import DEFAULT_LOGO, FOOTER_EXPLICIT, FOOTER_FORMAT, HEADER_FORMAT, default_footer_rich, desktop_dir, footer_rich_from, header_rich_from
from richtext import RichText
from tools.contract_overview.customers.matching import MatchKind, MatchResult, is_valid_email, normalize_email
from tools.contract_overview.customers.migration import LEGACY_KEY, open_store
from tools.contract_overview.customers.models import Customer, TextBlock, parse_time
from tools.contract_overview.customers.texts import footer_of, header_of
from tools.contract_overview.customers.repository import FILE_NAME, ORDER_COMPANY, ORDER_NUMBER, ORDER_RECENT, ORDERS, CustomerStore, EmailConflict

from .. import dialogs as dialog_service
from .. import files
from ..base import Observable, Var, prop
from ..models import KeyedListModel

CONFIG_ORDER = "kunden_sortierung"
CONFIG_AUTO = "kunden_auto_uebernehmen"
CONFIG_ACTIVE = "kunde_aktiv"
CONFIG_BASE_TEXTS = "kunde_texte_vorher"  # gültige Kopf-/Fußzeile vor den Texten der aktiven Kundenakte
CONFIG_ENABLED = "kundenakte_verwenden"  # Opt-in: Standard aus (neue Installation und Update)
CONFIG_HINT = "kundenakte_hinweis_gezeigt"  # einmaliger Hinweis für bisherige Nutzer der Kundenakte
OPTIONAL_HINT = "Die Kundenakte ist jetzt optional und kann in den Einstellungen aktiviert werden. Ihre gespeicherten Kundendaten bleiben erhalten."
# Hinweisbereiche mit Kundenbezug – beim Ausschalten werden sie geleert
CUSTOMER_AREAS = ("kunde_match", "kunde_info", "kunden_info", "kunde_detail_info", "kunde_mail_info", "batch_mail_info")
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
SORT_LABELS = {ORDER_RECENT: "Zuletzt verwendet", ORDER_COMPANY: "Firma A–Z", ORDER_NUMBER: "Kundennummer"}
PRIVACY = "Kundendaten und E-Mail-Zuordnungen werden ausschließlich lokal auf diesem PC gespeichert."
EMPTY_TITLE = "Noch keine Kunden gespeichert"
EMPTY_TEXT = "PDF Tool kann bekannte Rechnungsempfänger später automatisch wiedererkennen. Kundenakten entstehen, wenn Sie Kundendaten bewusst speichern – nach dem Erstellen einer Übersicht oder mit »Als Kundenakte speichern«."
NO_TEMPLATE = "Keine Vorlage"


def template_label(ref: str) -> str:
    """»„Name“ « für Verweise per Name (bis 2.7); eine ID allein sagt dem Benutzer nichts."""
    from tools.contract_overview.batch.resolver import ref_label

    return ref_label(ref)
SEARCH_DELAY = 200
SAVE_DELAY = 600
PICKER_DELAY = 180
MAX_ROWS = 200  # mehr Treffer: »Suche verfeinern«
REASONS = {"number": "gleiche Kundennummer", "company": "gleicher Firmenname", "email": "gleiche E-Mail"}


def _same_path(a: str, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return str(a) == str(b)


def _key(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def _block(rich: RichText) -> TextBlock:
    return TextBlock(rich.text, rich.to_dict())


def has_customer_data(folder: Path, cfg: dict) -> bool:
    """Gibt es gespeicherte Kundendaten? Nur Dateiprüfung – die Kundenakten werden dafür nicht gelesen."""
    legacy = cfg.get(LEGACY_KEY)
    if isinstance(legacy, list) and legacy:
        return True
    try:
        return (folder / FILE_NAME).is_file()
    except OSError:
        return False


def format_when(value: str, empty: str = "–") -> str:
    """ISO-Zeitstempel für die Oberfläche: »Heute, 15:32«, »Gestern, 09:10« oder »28.09.2026«."""
    moment = parse_time(value)
    if moment is None:
        return empty
    local = moment.astimezone()
    today = datetime.now().astimezone().date()
    if local.date() == today:
        return f"Heute, {local:%H:%M}"
    if local.date() == today - timedelta(days=1):
        return f"Gestern, {local:%H:%M}"
    return f"{local:%d.%m.%Y}"


def email_summary(customer: Customer) -> str:
    if not customer.emails:
        return "keine E-Mail zugeordnet"
    more = len(customer.emails) - 1
    return customer.emails[0] + (f" (+{more} weitere)" if more > 0 else "")


def _first_line(text: str, limit: int = 80) -> str:
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


def customer_row(customer: Customer, active_id: str | None = None) -> dict:
    return {
        "id": customer.id,
        "company": customer.company or "Ohne Namen",
        "subtitle": f"Kd.-Nr. {customer.number or '–'}  ·  {email_summary(customer)}",
        "when": format_when(customer.last_used_at, ""),
        "active": customer.id == active_id,
    }


class CustomerController(Observable):
    """Kundenakten (optional) – Wiedererkennung, Übernahme und Verwaltung."""

    enabledChanged, enabled = prop(bool, "enabled", False)
    autoApplyChanged, autoApply = prop(bool, "autoApply", False)
    # Liste
    searchChanged, search = prop(str, "search", "")
    orderChanged, order = prop(str, "order", ORDER_RECENT)
    totalChanged, total = prop(int, "total", 0)
    countTextChanged, countText = prop(str, "countText", "")
    listShownChanged, listShown = prop(bool, "listShown", False)
    # Detailansicht
    detailIdChanged, detailId = prop(str, "detailId", "")
    companyChanged, company = prop(str, "company", "")
    numberChanged, number = prop(str, "number", "")
    noteChanged, note = prop(str, "note", "")
    newEmailChanged, newEmail = prop(str, "newEmail", "")
    detailTitleChanged, detailTitle = prop(str, "detailTitle", "")
    detailCaptionChanged, detailCaption = prop(str, "detailCaption", "")
    companyErrorChanged, companyError = prop(bool, "companyError", False)
    emailErrorChanged, emailError = prop(bool, "emailError", False)
    logoTextChanged, logoText = prop(str, "logoText", "")
    logoPathChanged, logoPath = prop(str, "logoPath", "")
    targetTextChanged, targetText = prop(str, "targetText", "")
    targetPathChanged, targetPath = prop(str, "targetPath", "")
    templateChoicesChanged, templateChoices = prop(list, "templateChoices", [])
    templateValueChanged, templateValue = prop(str, "templateValue", NO_TEMPLATE)
    templateAutoChanged, templateAuto = prop(bool, "templateAuto", False)
    textFactsChanged, textFacts = prop(list, "textFacts", [])
    excelTextChanged, excelText = prop(str, "excelText", "")
    excelPathChanged, excelPath = prop(str, "excelPath", "")
    excelAvailableChanged, excelAvailable = prop(bool, "excelAvailable", False)
    pdfTextChanged, pdfText = prop(str, "pdfText", "")
    pdfPathChanged, pdfPath = prop(str, "pdfPath", "")
    pdfAvailableChanged, pdfAvailable = prop(bool, "pdfAvailable", False)
    activityChanged, activity = prop(list, "activity", [])
    # Übersicht erstellen: aktive Kundenakte
    activeIdChanged, activeId = prop(str, "activeId", "")
    activeTitleChanged, activeTitle = prop(str, "activeTitle", "")
    activeCaptionChanged, activeCaption = prop(str, "activeCaption", "")
    activeCaptionToneChanged, activeCaptionTone = prop(str, "activeCaptionTone", "secondary")
    pickerPlaceholderChanged, pickerPlaceholder = prop(str, "pickerPlaceholder", "Noch keine Kundenakten")
    saveTextChanged, saveText = prop(str, "saveText", "Als Kundenakte speichern")
    saveEnabledChanged, saveEnabled = prop(bool, "saveEnabled", False)
    # Auswahldialog
    pickerSearchChanged, pickerSearch = prop(str, "pickerSearch", "")
    pickerCountChanged, pickerCount = prop(str, "pickerCount", "")

    focusRequested = Signal(str)  # search, company, email

    def __init__(self, app, tool, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.c = None  # ContractOverviewController (nach dem Einrichten)
        self.cfg = cfg
        self.state = app.state
        self._store: CustomerStore | None = None
        self._empty = CustomerStore(None)
        folder = Path(appstate.CONFIG_FILE).parent
        self.set_quietly("enabled", cfg.get(CONFIG_ENABLED) is True)
        self._loaded = False
        self._report = None
        self._legacy_dropped = False
        if self.enabled:
            self._load(cfg)
        # Einmaliger Hinweis für bisherige Nutzer: Die Kundenakte ist jetzt optional (Daten bleiben).
        self._hint_done = cfg.get(CONFIG_HINT) is True
        self._hint_due = not self.enabled and not self._hint_done and has_customer_data(folder, cfg)
        order = cfg.get(CONFIG_ORDER)
        self.set_quietly("order", order if order in ORDERS else ORDER_RECENT)
        self.set_quietly("autoApply", cfg.get(CONFIG_AUTO) is True)
        self.var_auto_customer = Var(self, "autoApply")
        active = cfg.get(CONFIG_ACTIVE)
        # Ausgeschaltet gibt es keine aktive Kundenakte – die Angaben im Formular bleiben als Arbeitskopie.
        self._active_id: str | None = active if self.enabled and isinstance(active, str) and self.customers.get(active) else None
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
        # Ausgeschaltet bleiben die vorher gültigen Texte gemerkt: »Neue Übersicht« stellt sie
        # wieder her (die Standard-Fußzeile geht nie verloren, auch nicht nach einem Update).
        if isinstance(base, dict) and (self._active_id or not self.enabled):
            self._customer_texts = True
            self._base_texts = (header_rich_from(base), footer_rich_from(base))
        self._undo_apply: dict | None = None
        self._undo_detach: str | None = None
        self._deleted: Customer | None = None
        self._store_warned = False
        self._detail_loading = False
        self._picker_pool: list[Customer] = []
        self.model = KeyedListModel(("company", "subtitle", "when", "active"), key="id", parent=self)
        self.emails = KeyedListModel(("primary", "ambiguous"), key="email", parent=self)
        self.picker = KeyedListModel(("company", "subtitle", "when", "active"), key="id", parent=self)
        self.observe("search", lambda _v: self.app.timers.later("customers:search", SEARCH_DELAY, self.refresh_list))
        self.observe("pickerSearch", lambda _v: self.app.timers.later("customers:picker", PICKER_DELAY, self._refresh_picker))
        for name in ("company", "number", "note"):
            self.observe(name, lambda _v: self._schedule_detail_save())
        self.observe("autoApply", lambda _v: self.app.persist())
        self.detail_runs = 0

    # Speicher --------------------------------------------------------------------------------
    @property
    def customers(self) -> CustomerStore:
        """Kundenakten – nur bei eingeschaltetem Modul; sonst ein leerer Speicher ohne Datei."""
        if self._store is None or not self.enabled:
            return self._empty
        return self._store

    def customer_records_enabled(self) -> bool:
        return bool(self.enabled)

    def _load(self, cfg: dict) -> None:
        """Kundenakten laden – beim ersten Mal mit Übernahme der Historie aus Version 2.3."""
        folder = Path(appstate.CONFIG_FILE).parent
        had_legacy = LEGACY_KEY in cfg
        self._store, self._report = open_store(folder, cfg, Path(appstate.CONFIG_FILE))
        report = self._report
        # Die alte Kundenhistorie bleibt nur in der Konfiguration, solange die Übernahme nicht gelang.
        self._legacy_dropped = had_legacy and (report is None or report.ok)
        if self._legacy_dropped:
            cfg.pop(LEGACY_KEY, None)
            self.app.cfg.pop(LEGACY_KEY, None)
        self._loaded = True

    def attach(self, overview) -> None:
        self.c = overview

    def start(self) -> None:
        """Nach dem Einrichten: Ergebnis der Übernahme melden, Anzeige herstellen, einmaliger Hinweis."""
        # Wie bis 2.6: Schließen (×) des Kundenangebots heißt »Ignorieren« – für diese Excel nicht mehr anbieten.
        self.app.notices.on_close("kunde_match", self.ignore_match)
        if self.enabled:
            self._report_load()
        self._mark_text_baseline()
        self._apply_visibility()
        self.refresh_line()
        self.refresh_list()
        if self._hint_due:
            self._hint_due = False
            self._hint_done = True
            self.app.notify(
                "kunde_info",
                "info",
                OPTIONAL_HINT,
                title="Kundenakte",
                actions=(("Einstellungen öffnen", lambda: self.app.navigate("settings")),),
                status=False,
                animate=False,
            )
            # Gleich merken, nicht erst beim Beenden – auch nach einem Absturz höchstens einmal.
            self.app.schedule_save()

    def _report_load(self) -> None:
        report = self._report
        if self._legacy_dropped:
            self._legacy_dropped = False
            self.app.persist()  # alte Historie aus gui-config.json entfernen (die Sicherung behält sie)
        if report is not None and report.ok and report.migrated:
            count = "1 Kunde wurde" if report.migrated == 1 else f"{report.migrated} Kunden wurden"
            backup = f" Eine Sicherung der bisherigen Einstellungen liegt unter »{report.backup.parent.name}\\{report.backup.name}«." if report.backup else ""
            self.app.notify("kunden_info", "success", f"{count} aus der bisherigen Kundenhistorie als Kundenakte übernommen.{backup}", title="Kundenakte 2.0", status=False)
        elif report is not None and not report.ok:
            self.app.notify(
                "kunden_info",
                "error",
                f"Die bisherige Kundenhistorie konnte nicht übernommen werden ({report.error}). Sie bleibt unverändert erhalten; beim nächsten Start wird es erneut versucht.",
                title="Übernahme nicht möglich",
                status=False,
            )
        if self.customers.load_error:
            self.app.notify("kunden_info", "warning", self.customers.load_error, title="Kundenakten", status=False)

    # Ein- und Ausschalten (Einstellungen) ----------------------------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        """Schalter »Kundenakte verwenden« – wirkt sofort, ohne Neustart."""
        if enabled != self.enabled:
            if enabled:
                self._enable()
            else:
                self._disable()
        self.app.persist()

    def _enable(self) -> None:
        self.enabled = True
        if not self._loaded:
            self._load(self.app.cfg)
            self._report_load()
        self._apply_visibility()
        self.refresh_list()
        if self.detailId:
            self._fill_detail(reset_fields=False)
        # Wiedererkennung für die geprüfte Excel nachholen – angeboten, nie still übernommen.
        excel = self.c.excel.strip()
        analysis = self.c.analysis()
        if analysis is not None and self.c._analysis_path == excel and analysis.get("ok"):
            self._match = self.customers.match([str(mail) for mail in analysis.get("mails") or []])
            self._match_path = excel
            self._show_match(animate=False, automatic=False)
        self.refresh_line()
        self.tool.batch_customers_changed()
        self.app.set_status("Kundenakte eingeschaltet.", "success")

    def _disable(self) -> None:
        if self.app.currentPage in ("customers", "comparison"):
            self.app.navigate("create")
        self.flush()  # eine offene Eingabe in »Kunden« noch sichern
        self.enabled = False
        # Keine aktive Kundenakte mehr – die Angaben im Formular bleiben als Arbeitskopie. Stammen
        # Kopf- und Fußzeile aus der Kundenakte, bleiben die vorher gültigen Texte gemerkt.
        self._active_id = None
        self._undo_apply = None
        self._undo_detach = None
        self._match = None
        self._match_path = ""
        for area in CUSTOMER_AREAS:
            self.app.hide_notice(area)
        self._apply_visibility()
        self.refresh_line()
        self.tool.batch_customers_changed()
        self.app.set_status("Kundenakte ausgeschaltet – gespeicherte Kundendaten bleiben erhalten.", "success")

    def _apply_visibility(self) -> None:
        """Ansichten »Kunden« und »Vergleich« nur mit eingeschalteter Kundenakte."""
        self.app.set_available("customers", self.enabled)
        self.app.set_available("comparison", self.enabled)
        self.app.refresh_hint()

    def config(self) -> dict:
        data = {
            CONFIG_ENABLED: bool(self.enabled),
            CONFIG_HINT: self._hint_done,
            CONFIG_ORDER: self.order,
            CONFIG_AUTO: bool(self.autoApply),
            CONFIG_ACTIVE: self._active_id or "",
            CONFIG_BASE_TEXTS: None,
        }
        if self._customer_texts and self._base_texts is not None:
            kopf, fuss = self._base_texts
            data[CONFIG_BASE_TEXTS] = {
                "kopfzeile": kopf.text,
                HEADER_FORMAT: kopf.to_dict(),
                "fusszeile": fuss.text,
                FOOTER_FORMAT: fuss.to_dict(),
                FOOTER_EXPLICIT: True,
            }
        return data

    # Zustand ------------------------------------------------------------------------------------------
    def active_customer(self) -> Customer | None:
        if not self.enabled:
            return None
        return self.customers.get(self._active_id)

    @property
    def active_id(self) -> str | None:
        return self._active_id

    def _store_customers(self) -> bool:
        """Kundenakten speichern; ein Fehler wird einmal deutlich gemeldet (die Arbeit geht weiter)."""
        if not self.enabled:
            return False  # ausgeschaltet: nichts zu speichern – die Datei bleibt unangetastet
        if self.customers.path is None:
            if not self._store_warned:
                self._store_warned = True
                self.app.notify("kunden_info", "warning", "Kundenakten können in dieser Sitzung nicht dauerhaft gespeichert werden. Änderungen gelten bis zum Beenden.", title="Kundenakten", status=False)
            return False
        if self.customers.save():
            self._store_warned = False
            return True
        if not self._store_warned:
            self._store_warned = True
            self.app.notify("kunde_info", "error", "Die Kundenakten konnten nicht gespeichert werden. Bitte prüfen, ob der Datenordner beschreibbar ist.", title="Speichern fehlgeschlagen")
        return False

    def customers_changed(self, detail: bool = True) -> None:
        """Nach jeder bewussten Änderung an Kundenakten: speichern und alle Anzeigen aktualisieren."""
        if not self.enabled:
            return
        self._store_customers()
        if self._active_id and self.customers.get(self._active_id) is None:
            self._active_id = None
            self._customer_texts = False
            self._base_texts = None
        if detail:
            self.refresh()
        else:
            self.refresh_list()
        self.refresh_line()
        self._rematch()
        # Der Stapel erkennt Kunden mit denselben Zuordnungen – geänderte Akten gelten sofort.
        self.tool.batch_customers_changed()

    def _current_emails(self) -> list[str]:
        """Rechnungsempfänger der aktuellen Übersicht: eingetragene Adresse und Adressen der geprüften Excel."""
        found: list[str] = []
        for raw in [self.c.mail, *self.c.analysis_mails()]:
            email = normalize_email(raw)
            if is_valid_email(email) and email not in found:
                found.append(email)
        return found

    def _unknown_emails(self, customer: Customer) -> list[str]:
        """Adressen der Übersicht, die noch keiner Kundenakte gehören (und nicht abgelehnt wurden)."""
        return [email for email in self._current_emails() if not self.customers.owner_ids(email) and (customer.id, email) not in self._declined_emails]

    # Wiedererkennung ------------------------------------------------------------------------------------
    def recognize(self, path: str, result: dict, animate: bool = True) -> None:
        """Nach der Excel-Prüfung: bekannte Rechnungsempfänger suchen. Nie eine alte Analyse verwenden."""
        if not self.enabled:
            # Ohne Kundenakte kein Abgleich – auch nicht im Hintergrund.
            self._match = None
            self._match_path = ""
            return
        mails = [str(mail) for mail in result.get("mails") or []] if result.get("ok") else []
        self._match = self.customers.match(mails)
        self._match_path = path
        self._show_match(animate=animate, automatic=True)

    def _rematch(self) -> None:
        """Nach Änderungen an Zuordnungen: aktuelle Excel erneut gegen die Kundenakten prüfen."""
        excel = self.c.excel.strip()
        if not self.enabled or self._match is None or self._match_path != excel:
            return
        self._match = self.customers.match(self.c.analysis_mails())
        self._show_match(animate=False, automatic=False)

    def _show_match(self, animate: bool = True, automatic: bool = False) -> None:
        match = self._match
        if not self.enabled or match is None or self._match_path != self.c.excel.strip():
            self.app.hide_notice("kunde_match")
            return
        active = self.active_customer()
        ignored = (self._match_path, match.customer_ids) in self._match_ignored
        if match.kind is MatchKind.NONE:
            if active is None or ignored:
                self.app.hide_notice("kunde_match")
                return
            other = self._file_number_mismatch(active)
            if other:
                self._warn_number_mismatch(active, other, animate)
                return
            unknown = self._unknown_emails(active)
            if unknown:
                self._offer_emails(active, unknown, animate=animate, question=True)
            else:
                self.app.hide_notice("kunde_match")
            return
        if ignored:
            self.app.hide_notice("kunde_match")
            return
        if match.kind is MatchKind.SINGLE:
            customer = self.customers.get(match.customer_id)
            if customer is None:
                self.app.hide_notice("kunde_match")
                return
            if active is not None and active.id == customer.id:
                unknown = self._unknown_emails(customer)
                if unknown:
                    self._offer_emails(customer, unknown, animate=animate)
                else:
                    self.app.hide_notice("kunde_match")
                return
            if automatic and active is None and self.autoApply and not self._conflicting_values(customer):
                self.apply_customer(customer.id, automatic=True)
                return
            via = ", ".join(match.emails_of(customer.id))
            # Steht genau eine Adresse in der Excel, zeigt die Zeile »Rechnungsempfänger« sie schon.
            known = "erkannt am Rechnungsempfänger der Excel" if len(self.c.excel_mails()) == 1 else f"erkannt an {via}"
            self.app.notify(
                "kunde_match",
                "info",
                f"{customer.label} – {known}.",
                title="Bekannter Kunde gefunden",
                actions=(
                    ("Übernehmen", lambda: self.apply_customer(customer.id)),
                    ("Kundenakte", lambda: self.open_record(customer.id)),
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
        self.app.notify(
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
        self.app.notify(
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
        result = self.c.analysis_for_current()
        if result is None or not customer.number:
            return ""
        numbers = [str(number) for number in result.get("kunden") or []]
        if len(numbers) == 1 and _key(numbers[0]) != _key(customer.number):
            return numbers[0]
        return ""

    def _conflicting_values(self, customer: Customer) -> bool:
        """Stehen im Formular bereits andere Kundendaten? Dann nie automatisch übernehmen."""
        firma, kd = self.c.firma.strip(), self.c.kd.strip()
        return bool(firma and _key(firma) != _key(customer.company)) or bool(kd and _key(kd) != _key(customer.number))

    @Slot()
    def ignoreMatch(self) -> None:  # noqa: N802
        self.ignore_match()

    def ignore_match(self) -> None:
        if self._match is not None:
            self._match_ignored.add((self._match_path, self._match.customer_ids))
        self.app.hide_notice("kunde_match")

    def _offer_emails(self, customer: Customer, emails: list[str], area: str = "kunde_match", animate: bool = True, question: bool = False) -> None:
        """Lernen nur nach bewusster Entscheidung: »Diese E-Mail künftig diesem Kunden zuordnen?«"""
        single = len(emails) == 1
        title = "Diese E-Mail künftig diesem Kunden zuordnen?" if single else "Diese E-Mail-Adressen künftig diesem Kunden zuordnen?"
        listed = ", ".join(emails)
        if question:
            message = f"Kein bekannter Kunde in der Excel. Gehört {listed} zur aktiven Kundenakte „{customer.label}“?"
        else:
            message = f"{listed} → „{customer.label}“. PDF Tool erkennt den Kunden dann in der nächsten Excel-Liste wieder."
        self.app.notify(
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
        self.app.hide_notice(area)

    def assign_emails(self, customer_id: str, emails: list[str], quiet: bool = False) -> list[str]:
        """Adressen künftig diesem Kunden zuordnen. Gehört eine schon einem anderen: der Benutzer entscheidet."""
        if not self.enabled:
            return []
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
                answer = self.ask_email_conflict(email, conflict.owners, customer.label)
                if answer == "cancel":
                    break
                if answer == "keep":
                    self._declined_emails.add((customer.id, email))
                    continue
                self.customers.add_email(customer.id, email, move=True)
            added.append(email)
        self.app.hide_notice("kunde_match")
        if added:
            self.customers_changed()
            if not quiet:
                self.app.notify("kunde_info", "success", f"{', '.join(added)} {'wird' if len(added) == 1 else 'werden'} künftig als Rechnungsempfänger von „{customer.label}“ erkannt.", title="Zuordnung gemerkt", auto_hide=8000)
        return added

    # Auswählen und Übernehmen ---------------------------------------------------------------------------------
    @Slot()
    def pickCustomer(self) -> None:  # noqa: N802
        self.pick_customer()

    def pick_customer(self, candidates=None) -> None:
        """»Bekannten Kunden auswählen«: Suchdialog über alle (bzw. die angebotenen) Kundenakten."""
        if not self.enabled:
            return
        if not len(self.customers):
            has_values = bool(self.c.firma.strip() or self.c.kd.strip())
            actions = (("Als Kundenakte speichern", self.save_as_customer),) if has_values else ()
            self.app.notify("kunde_info", "info", "Noch keine Kundenakten gespeichert. Eingetragene Kundendaten lassen sich als Kundenakte speichern – danach erkennt PDF Tool den Kunden wieder.", actions=actions, auto_hide=10000)
            return
        message = None
        if candidates:
            message = "Die Rechnungsempfänger der Excel gehören zu mehreren Kundenakten. Welcher Kunde ist gemeint?"
        chosen = self.choose_customer(candidates=list(candidates) if candidates else None, message=message)
        if chosen:
            self.apply_customer(chosen)

    @Slot(str)
    def applyCustomer(self, customer_id: str) -> None:  # noqa: N802
        self.apply_customer(customer_id)

    def apply_customer(self, customer_id: str, automatic: bool = False) -> None:
        """Kundenakte in die Arbeitskopie übernehmen (rückgängig machbar). Die Kundenakte bleibt unverändert."""
        if not self.enabled:
            return
        customer = self.customers.get(customer_id)
        if customer is None:
            return
        c = self.c
        undo = self._working_snapshot()
        previous = self.active_customer()
        switching = previous is not None and previous.id != customer.id
        fresh = self._texts_fresh()
        # Stand der Excel-Prüfung vorher festhalten: Eine Vorlage mit anderen Regeln prüft neu.
        excel_mails = c.analysis_mails()
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
                hints.append(f"Die bevorzugte Vorlage {template_label(customer.template)}gibt es nicht mehr.")
            elif customer.template_auto:
                c.apply_vorlage(entry, texts=fresh, quiet=True)
            elif c.vorlageId != entry.get("id") or c.templateModified:
                actions.append((f"Vorlage „{entry.get('name', '')}“ anwenden", lambda e=entry: c.apply_vorlage(e)))
        # 3. Stammdaten und Rechnungsempfänger
        for var, value in ((c.var_firma, customer.company), (c.var_kd, customer.number)):
            if value or switching:
                var.set(value)
        self._apply_customer_mail(customer, previous, excel_mails)
        # 4. Logo und Zielordner – nur wenn vorhanden, sonst bleibt der aktuelle Wert
        if customer.logo:
            if Path(customer.logo).is_file():
                c.logo = customer.logo
            else:
                hints.append("Gespeichertes Logo wurde nicht gefunden – das aktuelle bleibt.")
        if customer.target_dir:
            if Path(customer.target_dir).is_dir():
                c.ziel = customer.target_dir
            else:
                hints.append("Gespeicherter Zielordner ist nicht verfügbar – der aktuelle bleibt.")
        c.refresh_files()
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
        self._active_id = customer.id
        self._undo_apply = undo
        self.customers.touch(customer.id, excel=excel)
        self._store_customers()
        self.app.hide_notice("kunde_match")
        c.kdRequired = False
        c.clearError("kd")
        self.refresh_line()
        self.refresh()
        c.update_readiness()
        self.app.schedule_save()
        if not c.excel.strip() and customer.last_excel and Path(customer.last_excel).is_file():
            actions.append(("Letzte Excel verwenden", lambda path=customer.last_excel: c.use_excel(path)))
        actions.insert(0, ("Rückgängig", self.undo_apply_customer))
        message = customer.label + ("" if not hints else " · " + " ".join(hints))
        title = "Bekannter Kunde übernommen" if automatic else "Kundenakte übernommen"
        self.app.notify("kunde_info", "warning" if hints else "success", message, title=title, actions=tuple(actions), auto_hide=None if (hints or len(actions) > 1) else 10000)
        if not automatic:
            other = self._file_number_mismatch(customer)
            if other:
                self._warn_number_mismatch(customer, other)
            elif unknown:
                self._offer_emails(customer, unknown)

    def _apply_customer_mail(self, customer: Customer, previous: Customer | None, excel_mails: list[str]) -> None:
        """Rechnungsempfänger passend zur Excel: eindeutige eigene Adresse wählen, nie raten."""
        c = self.c
        current = normalize_email(c.mail)
        stale = previous is not None and current in previous.emails  # Adresse des vorigen Kunden
        if len(excel_mails) > 1:
            own = [mail for mail in excel_mails if normalize_email(mail) in customer.emails]
            if len(own) == 1:
                c.mail = own[0]
            elif stale:
                c.mail = ""
        elif excel_mails:
            if stale:
                c.mail = ""  # die Adresse aus der Excel gilt
        elif customer.primary_email and (not current or stale):
            c.mail = customer.primary_email
        elif stale:
            c.mail = ""

    def _matching_excel(self, customer_id: str) -> str | None:
        """Die aktuelle Excel nur als »letzte Excel« merken, wenn sie diesem Kunden zugeordnet ist."""
        excel = self.c.excel.strip()
        match = self._match
        if match is None or self._match_path != excel or customer_id not in match.customer_ids or not Path(excel).is_file():
            return None
        return excel

    def apply_customer_texts(self, customer_id: str) -> None:
        """Kopf- und Fußzeile der Kundenakte bewusst übernehmen (auch nach eigenen Änderungen)."""
        customer = self.customers.get(customer_id)
        if customer is None:
            return
        before = (self.c.header_rich(), self.c.footer_rich())
        if not self._customer_texts:
            self._base_texts = before
        self._apply_own_texts(customer)
        self._mark_text_baseline()
        self.app.schedule_save()
        self.app.notify("kunde_info", "success", f"Kopf- und Fußzeile von „{customer.label}“ übernommen.", actions=(("Rückgängig", lambda: self._undo_texts(before)),), auto_hide=8000)

    def _undo_texts(self, texts: tuple[RichText, RichText]) -> None:
        self._set_texts(*texts)
        self._customer_texts = False
        self._base_texts = None
        self._mark_text_baseline()
        self.app.schedule_save()
        self.app.hide_notice("kunde_info")

    def _apply_own_texts(self, customer: Customer) -> None:
        header, footer = header_of(customer), footer_of(customer)
        if header is None and footer is None:
            return
        if self._base_texts is None:
            self._base_texts = (self.c.header_rich(), self.c.footer_rich())
        self._set_texts(header, footer)
        self._customer_texts = True

    def _set_texts(self, header: RichText | None, footer: RichText | None) -> None:
        # Eine leere Fußzeile ersetzt nie die gültige (Standard-Fußzeile bleibt erhalten).
        if header is not None:
            self.c.set_header(header)
        if footer is not None and not footer.is_blank():
            self.c.set_footer(footer)

    def _mark_text_baseline(self) -> None:
        self._text_baseline = (self.c.header_rich(), self.c.footer_rich())

    def texts_from_template(self) -> None:
        """Eine Vorlage hat Kopf- und Fußzeile gesetzt – sie stammen nicht mehr aus einer Kundenakte."""
        self._customer_texts = False
        self._base_texts = None
        self._mark_text_baseline()

    def _texts_fresh(self) -> bool:
        """Kopf- und Fußzeile seit dem letzten Setzen durch die App unverändert?"""
        if self._text_baseline is None:
            return True
        return self.c.header_rich() == self._text_baseline[0] and self.c.footer_rich() == self._text_baseline[1]

    def _working_snapshot(self) -> dict:
        return {
            "vars": {name: getattr(self.c, name).get() for name in WORK_VARS},
            "texts": (self.c.header_rich(), self.c.footer_rich()),
            "regeln": [dict(regel) for regel in self.state.regeln],
            "active": self._active_id,
            "baseline": self._text_baseline,
            "customer_texts": self._customer_texts,
            "base_texts": self._base_texts,
        }

    def _restore_snapshot(self, snapshot: dict) -> None:
        c = self.c
        for name, value in snapshot["vars"].items():
            getattr(c, name).set(value)
        kopf, fuss = snapshot["texts"]
        if c.header_rich() != kopf:
            c.set_header(kopf)
        if c.footer_rich() != fuss:
            c.set_footer(fuss)
        if snapshot["regeln"] != self.state.regeln:
            self.state.regeln = [dict(regel) for regel in snapshot["regeln"]]
            c.reload_regeln()
            c.recheck_excel()
        active = snapshot["active"]
        self._active_id = active if self.customers.get(active) else None
        self._text_baseline = snapshot["baseline"]
        self._customer_texts = snapshot["customer_texts"]
        self._base_texts = snapshot["base_texts"]
        c.refresh_files()
        self.refresh_line()
        c.update_readiness()
        self.app.persist()

    def undo_apply_customer(self) -> None:
        if self._undo_apply is None:
            return
        snapshot, self._undo_apply = self._undo_apply, None
        self._restore_snapshot(snapshot)
        self.app.hide_notice("kunde_info")
        self._show_match(animate=True, automatic=False)
        self.app.set_status("Übernahme der Kundenakte rückgängig gemacht.", "success")

    # Aktive Kundenakte -------------------------------------------------------------------------------------
    @Slot()
    def detach(self) -> None:
        self.detach_customer()

    def detach_customer(self) -> None:
        """Kundenakte lösen: Die eingetragenen Angaben bleiben für diese Übersicht erhalten."""
        customer = self.active_customer()
        if customer is None:
            return
        self._active_id = None
        self._customer_texts = False
        self._base_texts = None
        self._undo_detach = customer.id
        self.refresh_line()
        self.app.schedule_save()
        self.app.notify("kunde_info", "info", f"„{customer.label}“ ist nicht mehr aktiv. Die eingetragenen Angaben bleiben für diese Übersicht erhalten.", actions=(("Rückgängig", self._undo_detach_customer),), auto_hide=8000)

    def _undo_detach_customer(self) -> None:
        ident, self._undo_detach = self._undo_detach, None
        if ident and self.customers.get(ident):
            self._active_id = ident
            self.refresh_line()
            self.app.schedule_save()
        self.app.hide_notice("kunde_info")

    def leave(self) -> dict | None:
        """Kundenakte verlassen (»Neue Übersicht«, »Kundendaten leeren«).

        Unveränderte Kopf-/Fußzeilen der Kundenakte werden durch die vorher gültigen ersetzt –
        sonst stünde der Text eines Kunden in der Übersicht des nächsten. Rückgabe: Zustand
        für »Rückgängig« (``None``, wenn nichts zu tun war).
        """
        state = {
            "active": self._active_id,
            "texts": (self.c.header_rich(), self.c.footer_rich()),
            "baseline": self._text_baseline,
            "customer_texts": self._customer_texts,
            "base_texts": self._base_texts,
        }
        restored = False
        if self._customer_texts and self._base_texts is not None and self._texts_fresh():
            self._set_texts(*self._base_texts)
            restored = True
        self._active_id = None
        self._customer_texts = False
        self._base_texts = None
        if restored:
            self._mark_text_baseline()
        self.app.hide_notice("kunde_match")
        self.refresh_line()
        return state if (state["active"] or restored) else None

    def return_to(self, state: dict | None) -> None:
        if not state:
            return
        kopf, fuss = state["texts"]
        if self.c.header_rich() != kopf:
            self.c.set_header(kopf)
        if self.c.footer_rich() != fuss:
            self.c.set_footer(fuss)
        active = state["active"]
        self._active_id = active if self.customers.get(active) else None
        self._text_baseline = state["baseline"]
        self._customer_texts = state["customer_texts"]
        self._base_texts = state["base_texts"]
        self.refresh_line()

    @Slot(str)
    def openRecord(self, customer_id: str) -> None:  # noqa: N802
        self.open_record(customer_id)

    def open_record(self, customer_id: str | None = None) -> None:
        """Kundenakte in der Ansicht »Kunden« öffnen."""
        if not self.enabled:
            return
        ident = customer_id or self._active_id
        if not ident or self.customers.get(ident) is None:
            return
        self.app.navigate("customers")
        self.show_detail(ident)

    @Slot()
    def openActive(self) -> None:  # noqa: N802
        self.open_record(self._active_id)

    # Bewusst speichern ---------------------------------------------------------------------------------------
    @Slot()
    def saveOrUpdate(self) -> None:  # noqa: N802
        if not self.enabled:
            return
        if self.active_customer() is not None:
            self.update_active_customer()
        else:
            self.save_as_customer()

    def _record_fields(self) -> dict:
        """Einstellungen der Arbeitskopie für eine neue Kundenakte (Standardwerte werden nicht gespeichert)."""
        c = self.c
        logo = c.logo.strip()
        if not logo or not Path(logo).is_file() or _same_path(logo, DEFAULT_LOGO):
            logo = ""
        target = c.ziel.strip()
        if not target or _same_path(target, desktop_dir()):
            target = ""
        # Ab 2.8 per ID: Umbenennen der Vorlage trennt die Kundenakte nicht von ihr.
        template = c.vorlageId if c.vorlageId and self.state.find_vorlage(c.vorlageId) is not None else ""
        kopf, fuss = c.header_rich(), c.footer_rich()
        header = _block(kopf) if not kopf.is_blank() else None
        footer = _block(fuss) if not fuss.is_blank() and fuss != default_footer_rich() else None
        return {"logo": logo, "target_dir": target, "template": template, "header": header, "footer": footer}

    def save_as_customer(self) -> None:
        """Arbeitskopie als neue Kundenakte speichern – mit Rückfrage, ob die E-Mail gemerkt werden soll."""
        if not self.enabled:
            return
        company, number = self.c.firma.strip(), self.c.kd.strip()
        if not company and not number:
            self.c.focusRequested.emit("firma")
            self.app.notify("kunde_info", "warning", "Bitte zuerst Firmenname oder Kundennummer eintragen.")
            return
        emails = self._current_emails()
        hints = []
        for other, reasons in self.customers.duplicates(company, number, emails)[:3]:
            why = ", ".join({"number": "gleiche Kundennummer", "company": "gleicher Firmenname", "email": "gleiche E-Mail"}[r] for r in reasons)
            hints.append(f"Mögliche Doppelung: „{other.label}“ ({why}). Später lassen sich Kundenakten zusammenführen.")
        ok, remember = self.ask_new_customer(company, number, ", ".join(emails), hints)
        if not ok:
            return
        customer = self.customers.create(company, number, (), **self._record_fields())
        self._active_id = customer.id
        self.customers.touch(customer.id, excel=self._current_excel())
        if remember and emails:
            self.assign_emails(customer.id, emails, quiet=True)
        self._declined_save.add((_key(company), _key(number)))
        self.customers_changed()
        self.app.schedule_save()
        self.app.notify("kunde_info", "success", f"„{customer.label}“ ist jetzt eine Kundenakte.", title="Kundenakte gespeichert", actions=(("Kundenakte öffnen", lambda: self.open_record(customer.id)),), auto_hide=10000)

    def _current_excel(self) -> str | None:
        """Die geprüfte Excel der Übersicht (``None`` ohne gültige Prüfung)."""
        excel = self.c.excel.strip()
        result = self.c.analysis_for_current()
        checked = result is not None and bool(result.get("ok"))
        return excel if checked and Path(excel).is_file() else None

    def _customer_differences(self, customer: Customer) -> list[tuple[str, str, str]]:
        """Abweichungen der Arbeitskopie von der Kundenakte als (Feld, bisher, neu)."""
        c = self.c
        changes: list[tuple[str, str, str]] = []
        firma, kd = c.firma.strip(), c.kd.strip()
        if firma and firma != customer.company:
            changes.append(("company", customer.company or "–", firma))
        if kd and kd != customer.number:
            changes.append(("number", customer.number or "–", kd))
        unknown = self._unknown_emails(customer)
        if unknown:
            changes.append(("emails", ", ".join(customer.emails) or "keine", "+ " + ", ".join(unknown)))
        fields = self._record_fields()
        logo = c.logo.strip()
        if fields["logo"] and not _same_path(fields["logo"], customer.logo or ""):
            changes.append(("logo", Path(customer.logo).name if customer.logo else "keines", Path(logo).name))
        target = fields["target_dir"]
        if target and not _same_path(target, customer.target_dir or ""):
            changes.append(("target_dir", customer.target_dir or "keiner", target))
        if fields["template"] and fields["template"] != self._template_id(customer.template):
            changes.append(("template", self._template_name(customer.template) or "keine", self._template_name(fields["template"])))
        kopf, fuss = c.header_rich(), c.footer_rich()
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
        if not self.enabled:
            return
        customer = self.active_customer()
        if customer is None:
            self.save_as_customer()
            return
        changes = self._customer_differences(customer)
        if not changes:
            self.app.notify("kunde_info", "info", f"„{customer.label}“ entspricht bereits den Angaben dieser Übersicht.", auto_hide=6000)
            return
        chosen = self.ask_customer_update(customer.label, [(key, CHANGE_LABELS[key], old, new) for key, old, new in changes])
        if not chosen:
            return
        c = self.c
        fields: dict = {}
        record = self._record_fields()
        kopf, fuss = c.header_rich(), c.footer_rich()
        for key in chosen:
            if key == "company":
                fields["company"] = c.firma.strip()
            elif key == "number":
                fields["number"] = c.kd.strip()
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
        self.app.schedule_save()
        names = ", ".join(CHANGE_LABELS[key] for key in chosen)
        self.app.notify("kunde_info", "success", f"„{customer.label}“: {names} gespeichert.", title="Kundenakte aktualisiert", auto_hide=8000)

    @Slot()
    def newCustomer(self) -> None:  # noqa: N802
        """»Neue Kundenakte« in der Ansicht »Kunden« – unabhängig von der aktuellen Übersicht."""
        if not self.enabled:
            return
        answer = self.ask_customer_fields()
        if answer is None:
            return
        company, number, email = answer
        if not company and not number:
            self.app.notify("kunden_info", "warning", "Bitte Firmenname oder Kundennummer eintragen – eine leere Kundenakte wird nicht angelegt.", status=False)
            return
        email = normalize_email(email)
        if email and not is_valid_email(email):
            self.app.notify("kunden_info", "warning", f"„{email}“ ist keine gültige E-Mail-Adresse. Die Kundenakte wurde nicht angelegt.", status=False)
            return
        customer = self.customers.create(company, number, ())
        if email:
            self.assign_emails(customer.id, [email], quiet=True)
        self.customers_changed()
        self.show_detail(customer.id)
        self.app.notify("kunde_detail_info", "success", f"Kundenakte „{customer.label}“ angelegt.", auto_hide=6000, status=False)

    # Nach dem Erstellen ---------------------------------------------------------------------------------------
    def after_pdf(self, path: Path) -> None:
        """Nur Metadaten fortschreiben; alles Weitere wird angeboten, nie still gespeichert.

        Ohne Kundenakte wird nichts gespeichert und nichts angeboten."""
        if not self.enabled:
            return
        customer = self.active_customer()
        if customer is not None:
            self.customers.touch(customer.id, excel=self.c.excel.strip() or None, pdf=str(path))
            self._store_customers()
            self.refresh()
            self.app.hide_notice("kunde_match")
            unknown = self._unknown_emails(customer)
            if unknown:
                self._offer_emails(customer, unknown, area="kunde_info")
                return
            changes = [key for key, _old, _new in self._customer_differences(customer)]
            if changes:
                names = ", ".join(CHANGE_LABELS[key] for key in changes)
                self.app.notify(
                    "kunde_info",
                    "info",
                    f"Diese Übersicht weicht von „{customer.label}“ ab: {names}.",
                    title="Kundenakte aktualisieren?",
                    actions=(("Kundenakte aktualisieren", self.update_active_customer), ("Nicht jetzt", lambda: self.app.hide_notice("kunde_info"))),
                    status=False,
                )
            return
        company, number = self.c.firma.strip(), self.c.kd.strip()
        key = (_key(company), _key(number))
        if (company or number) and key not in self._declined_save:
            self.app.notify(
                "kunde_info",
                "info",
                f"„{company or number}“ ist noch keine Kundenakte. Gespeichert erkennt PDF Tool den Kunden künftig an der Rechnungsempfänger-E-Mail wieder.",
                title="Als Kundenakte speichern?",
                actions=(("Als Kundenakte speichern", self.save_as_customer), ("Nicht jetzt", lambda: self._decline_save(key))),
                status=False,
            )

    def _decline_save(self, key: tuple[str, str]) -> None:
        self._declined_save.add(key)
        self.app.hide_notice("kunde_info")

    # Verwalten ---------------------------------------------------------------------------------------------------
    def merge_customers(self, target_id: str, source_id: str) -> None:
        if not self.enabled:
            return
        source = self.customers.get(source_id)
        if source is None or self.customers.get(target_id) is None:
            return
        label = source.label
        target = self.customers.merge(target_id, source_id)
        if self._active_id == source_id:
            self._active_id = target_id
        self.tool.merge_history(target_id, source_id)
        self.customers_changed()
        self.app.notify("kunde_detail_info", "success", f"„{label}“ wurde in „{target.label}“ übernommen. E-Mail-Adressen und Aktivität sind vereint.", title="Zusammengeführt", auto_hide=8000)

    def delete_customer(self, customer_id: str) -> None:
        """Löscht nur die Kundenakte und ihre Zuordnungen – nie PDF- oder Excel-Dateien."""
        if not self.enabled:
            return
        customer = self.customers.delete(customer_id)
        if customer is None:
            return
        self._deleted = customer
        if self._active_id == customer_id:
            self._active_id = None
            self._customer_texts = False
            self._base_texts = None
        self.show_list()
        self.customers_changed()
        self.app.schedule_save()
        self.app.notify("kunden_info", "success", f"Kundenakte „{customer.label}“ gelöscht. Erstellte PDF-Dateien und Excel-Listen bleiben erhalten.", actions=(("Rückgängig", self._undo_delete),), auto_hide=10000)

    def _undo_delete(self) -> None:
        customer, self._deleted = self._deleted, None
        if customer is None:
            return
        self.customers.restore(customer)
        self.customers_changed()
        self.app.hide_notice("kunden_info")
        self.app.set_status(f"Kundenakte „{customer.label}“ wiederhergestellt.", "success")

    # Anzeige in »Übersicht erstellen« ------------------------------------------------------------------------------
    def refresh_line(self) -> None:
        customer = self.active_customer()
        self.activeId = customer.id if customer is not None else ""
        # Kennzeichen »aktiv« in den Listen folgt der aktiven Kundenakte (nur geänderte Zeilen)
        for model in (self.model, self.picker):
            for item in model.items():
                active = item.get("id") == self.activeId
                if item.get("active") != active:
                    model.update_item(item.get("id"), active=active)
        if customer is not None:
            self.pickerPlaceholder = "Anderen Kunden auswählen …"
            self.activeTitle = f"Kunde: {customer.label}"
            changes = [CHANGE_LABELS[key] for key, _o, _n in self._customer_differences(customer)]
            if changes:
                self.activeCaption = "Geändert gegenüber der Kundenakte: " + ", ".join(changes)
                self.activeCaptionTone = "warning"
            else:
                self.activeCaption = "Kundenakte aktiv – Änderungen hier gelten nur für diese Übersicht."
                self.activeCaptionTone = "secondary"
        else:
            self.pickerPlaceholder = "Firma, Kundennummer oder E-Mail suchen" if len(self.customers) else "Noch keine Kundenakten"
        self.saveText = "Kundenakte aktualisieren" if customer is not None else "Als Kundenakte speichern"
        self.saveEnabled = customer is not None or bool(self.c.firma.strip() or self.c.kd.strip())
        # »Kunde · Nicht zugeordnet« unter der Excel-Prüfung folgt der aktiven Kundenakte.
        self.c.refresh_excel_details()
        # Der Vertragsvergleich gilt immer der aktiven Kundenakte.
        self.tool.refresh_comparison()

    def customer_fact(self) -> tuple[str, str, str] | None:
        """»Kunde · Nicht zugeordnet« – nur, wenn es weiterhilft."""
        match = self._match
        if match is None or self._match_path != self.c.excel.strip() or self.active_customer() is not None:
            return None
        if match.kind is MatchKind.NONE and match.emails and len(self.customers):
            return ("Kunde", "Nicht zugeordnet", "muted")
        return None

    def find(self, page: str) -> None:
        """Strg+F: in »Kunden« die Suche, sonst »Bekannten Kunden auswählen«."""
        if not self.enabled:
            return
        if page == "customers":
            if self.detailId:
                self.show_list()
            self.focusRequested.emit("search")
        else:
            self.pick_customer()

    # Ansicht »Kunden«: Liste -------------------------------------------------------------------------------------------
    def _orders(self) -> list[dict]:
        return [{"value": key, "label": SORT_LABELS[key]} for key in ORDERS]

    def _texts(self) -> dict:
        return {"privacy": PRIVACY, "emptyTitle": EMPTY_TITLE, "emptyText": EMPTY_TEXT, "noTemplate": NO_TEMPLATE}

    _constant = Signal()
    orders = Property(list, _orders, notify=_constant)
    texts = Property("QVariantMap", _texts, notify=_constant)

    def _model_obj(self) -> QObject:
        return self.model

    def _emails_obj(self) -> QObject:
        return self.emails

    def _picker_obj(self) -> QObject:
        return self.picker

    listModel = Property(QObject, _model_obj, notify=_constant)
    emailModel = Property(QObject, _emails_obj, notify=_constant)
    pickerModel = Property(QObject, _picker_obj, notify=_constant)

    @Slot(str)
    def setOrder(self, order: str) -> None:  # noqa: N802
        if order in ORDERS and order != self.order:
            self.order = order
            self.app.schedule_save()
            self.refresh_list()

    def refresh(self) -> None:
        """Nach Änderungen an den Kundenakten: Liste und ggf. Detailansicht aktualisieren."""
        if self.detailId:
            if self.customers.get(self.detailId) is None:
                self.show_list()
                return
            self._fill_detail(reset_fields=False)
        self.refresh_list()

    def refresh_list(self) -> None:
        store = self.customers
        total = len(store)
        self.total = total
        if total == 0:
            self.model.clear()
            self.countText = ""
            self.listShown = False
            return
        query = self.search.strip()
        items = store.search(query, store.ordered(self.order))
        shown = items[:MAX_ROWS]
        self.model.set_items([customer_row(customer, self._active_id) for customer in shown])
        self.listShown = bool(items)
        if not items:
            self.countText = f"Keine Kundenakte passt zu „{query}“."
            return
        if query:
            text = f"{len(items)} von {total} Kundenakten"
        else:
            text = "1 Kundenakte" if total == 1 else f"{total} Kundenakten"
        if len(shown) < len(items):
            text += f" – {len(shown)} angezeigt, bitte Suche verfeinern"
        ambiguous = store.ambiguous_emails()
        if ambiguous:
            text += f" · {len(ambiguous)} {'E-Mail-Adresse ist' if len(ambiguous) == 1 else 'E-Mail-Adressen sind'} mehreren Kundenakten zugeordnet – bitte zusammenführen oder Zuordnung verschieben"
        self.countText = text

    # Ansicht »Kunden«: Detail -----------------------------------------------------------------------------------------
    @Slot()
    def showList(self) -> None:  # noqa: N802
        self.show_list()

    def show_list(self) -> None:
        self.flush()
        self.detailId = ""
        self.refresh()

    @Slot(str)
    def showDetail(self, customer_id: str) -> None:  # noqa: N802
        self.show_detail(customer_id)

    def show_detail(self, customer_id: str) -> None:
        customer = self.customers.get(customer_id)
        if customer is None:
            self.show_list()
            return
        self.flush()
        self.detailId = customer_id
        self.app.hide_notice("kunde_detail_info")
        self.app.hide_notice("kunde_mail_info")
        self._fill_detail(reset_fields=True)
        self.focusRequested.emit("company")

    def current(self) -> Customer | None:
        return self.customers.get(self.detailId) if self.detailId else None

    def _fill_detail(self, reset_fields: bool) -> None:
        customer = self.current()
        if customer is None:
            return
        self.detail_runs += 1
        self._detail_loading = True
        try:
            if reset_fields:
                self.company = customer.company
                self.number = customer.number
                self.note = customer.note
                self.newEmail = ""
                self.companyError = False
                self.emailError = False
            self.templateAuto = customer.template_auto
        finally:
            self._detail_loading = False
        self.detailTitle = customer.company or "Ohne Namen"
        active = self._active_id == customer.id
        caption = f"Kundennummer {customer.number or '–'} · angelegt {format_when(customer.created_at)}"
        if customer.origin == "kundenhistorie":
            caption += " · aus der bisherigen Kundenhistorie übernommen"
        if active:
            caption += " · aktiv in »Übersicht erstellen«"
        self.detailCaption = caption
        ambiguous = self.customers.ambiguous_emails()
        self.emails.set_items([{"email": email, "primary": index == 0, "ambiguous": email in ambiguous} for index, email in enumerate(customer.emails)])
        # Einstellungen
        if customer.logo:
            name, full = _caption(customer.logo)
            self.logoText, self.logoPath = name + ("" if Path(customer.logo).is_file() else " – nicht gefunden"), full
        else:
            self.logoText, self.logoPath = "Keines – das aktuelle Logo wird verwendet", ""
        if customer.target_dir:
            available = Path(customer.target_dir).is_dir()
            self.targetText, self.targetPath = (Path(customer.target_dir).name or customer.target_dir) + ("" if available else " – nicht verfügbar"), customer.target_dir
        else:
            self.targetText, self.targetPath = "Keiner – der aktuelle Zielordner wird verwendet", ""
        templates = sorted((str(entry.get("name", "")) for entry in self.state.vorlagen), key=str.casefold)
        values = [NO_TEMPLATE] + templates
        current = self._template_name(customer.template)
        if customer.template and current not in templates:
            values.append(current)
        self.templateChoices = values
        self.templateValue = current or NO_TEMPLATE
        # Kopf- und Fußzeile
        texts = []
        if customer.header is None:
            texts.append({"label": "Kopfzeile", "value": "keine eigene – die gültige bleibt", "tone": "muted"})
        else:
            texts.append({"label": "Kopfzeile", "value": _first_line(customer.header.text) or "eigene, leer (keine Kopfzeile)", "tone": ""})
        if customer.footer is None:
            texts.append({"label": "Fußzeile", "value": "keine eigene – die gültige bleibt", "tone": "muted"})
        else:
            texts.append({"label": "Fußzeile", "value": _first_line(customer.footer.text), "tone": ""})
        self.textFacts = texts
        # Aktivität
        excel_ok = bool(customer.last_excel) and Path(customer.last_excel).is_file()
        pdf_ok = bool(customer.last_pdf) and Path(customer.last_pdf).is_file()
        if customer.last_excel:
            name, full = _caption(customer.last_excel)
            self.excelText, self.excelPath = (name if excel_ok else f"{name} – nicht verfügbar"), full
        else:
            self.excelText, self.excelPath = "Noch keine", ""
        if customer.last_pdf:
            name, full = _caption(customer.last_pdf)
            self.pdfText, self.pdfPath = (name if pdf_ok else f"{name} – nicht verfügbar"), full
        else:
            self.pdfText, self.pdfPath = "Noch keine", ""
        self.excelAvailable = excel_ok
        self.pdfAvailable = pdf_ok
        self.activity = [
            {"label": "Zuletzt verwendet", "value": format_when(customer.last_used_at, "noch nicht"), "tone": ""},
            {"label": "Angelegt", "value": format_when(customer.created_at), "tone": "muted"},
            {"label": "Zuletzt geändert", "value": format_when(customer.updated_at), "tone": "muted"},
        ]
        self._show_duplicates(customer)

    def _show_duplicates(self, customer: Customer) -> None:
        hints = self.customers.duplicates(company=customer.company, number=customer.number, emails=customer.emails, exclude=customer.id)
        if not hints:
            self.app.hide_notice("kunde_detail_info")
            return
        other, reasons = hints[0]
        text = f"„{other.label}“ ({', '.join(REASONS[r] for r in reasons)})"
        if len(hints) > 1:
            text += f" und {len(hints) - 1} weitere"
        self.app.notify(
            "kunde_detail_info",
            "warning",
            f"Mögliche Doppelung: {text}. Gleiche Firma oder Nummer bedeutet nicht zwingend denselben Kunden.",
            title="Hinweis",
            actions=(("Zusammenführen …", self.merge),),
            status=False,
        )

    # Detail speichern (kurz nach der Eingabe) ----------------------------------------------------------------------
    def _schedule_detail_save(self) -> None:
        if self._detail_loading or not self.detailId:
            return
        self.app.timers.later("customers:save", SAVE_DELAY, self._save_fields)

    def flush(self) -> None:
        """Offene Eingaben der Detailansicht sofort speichern (z. B. beim Beenden)."""
        if self.app.timers.pending("customers:save"):
            self.app.timers.cancel("customers:save")
            self._save_fields()

    def _save_fields(self) -> None:
        customer = self.current()
        if customer is None:
            return
        company, number, note = self.company.strip(), self.number.strip(), self.note
        if not company and not number:
            self.companyError = True
            self.app.notify("kunde_detail_info", "warning", "Bitte Firmenname oder Kundennummer eintragen – leere Angaben werden nicht gespeichert.", status=False)
            return
        self.companyError = False
        if (company, number, note) == (customer.company, customer.number, customer.note):
            return
        self.customers.update(customer.id, company=company, number=number, note=note)
        self.customers_changed(detail=False)
        self.detailTitle = company or "Ohne Namen"
        self._show_duplicates(customer)

    def _update(self, message: str = "", **fields) -> None:
        customer = self.current()
        if customer is None:
            return
        self.customers.update(customer.id, **fields)
        self.customers_changed()
        if message:
            self.app.notify("kunde_detail_info", "success", message, auto_hide=5000, status=False)

    # Detail: Aktionen ------------------------------------------------------------------------------------------------
    @Slot()
    def addEmail(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None:
            return
        raw = self.newEmail
        email = normalize_email(raw)
        if not email:
            self.emailError = True
            self.app.notify("kunde_mail_info", "warning", "Bitte eine E-Mail-Adresse eintragen.", status=False)
            return
        if not is_valid_email(email):
            self.emailError = True
            self.app.notify("kunde_mail_info", "warning", f"„{raw.strip()}“ ist keine gültige E-Mail-Adresse.", status=False)
            return
        self.emailError = False
        if email in customer.emails:
            self.app.notify("kunde_mail_info", "info", f"{email} ist dieser Kundenakte bereits zugeordnet.", auto_hide=5000, status=False)
            return
        try:
            self.customers.add_email(customer.id, email)
        except EmailConflict as conflict:
            answer = self.ask_email_conflict(email, conflict.owners, customer.label)
            if answer != "move":
                self.app.notify("kunde_mail_info", "info", f"{email} bleibt bei {', '.join(o.label for o in conflict.owners)}.", auto_hide=6000, status=False)
                return
            self.customers.add_email(customer.id, email, move=True)
        self.newEmail = ""
        self.customers_changed()
        self.app.notify("kunde_mail_info", "success", f"{email} wird künftig als Rechnungsempfänger dieses Kunden erkannt.", auto_hide=6000, status=False)

    @Slot(str)
    def removeEmail(self, email: str) -> None:  # noqa: N802
        customer = self.current()
        if customer is None or not self.customers.remove_email(customer.id, email):
            return
        self.customers_changed()
        self.app.notify("kunde_mail_info", "info", f"{email} entfernt.", actions=(("Rückgängig", lambda: self._restore_email(customer.id, email)),), auto_hide=8000, status=False)

    def _restore_email(self, customer_id: str, email: str) -> None:
        try:
            self.customers.add_email(customer_id, email)
        except (EmailConflict, KeyError, ValueError):
            return
        self.customers_changed()
        self.app.hide_notice("kunde_mail_info")

    @Slot(str)
    def makePrimary(self, email: str) -> None:  # noqa: N802
        customer = self.current()
        if customer is not None:
            self.customers.make_primary(customer.id, email)
            self.customers_changed()

    @Slot()
    def pickLogo(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None:
            return
        start = str(Path(customer.logo).parent) if customer.logo else self.app.initial_dir("logo", self.c.logo.strip())
        path = files.open_file("Bevorzugtes Logo wählen", start, files.IMAGE_FILTER)
        if path:
            self._update(logo=path, message="Bevorzugtes Logo gespeichert.")

    @Slot()
    def clearLogo(self) -> None:  # noqa: N802
        self._update(logo="")

    @Slot()
    def pickTarget(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None:
            return
        start = customer.target_dir if customer.target_dir and Path(customer.target_dir).is_dir() else str(desktop_dir())
        path = files.pick_folder("Bevorzugter Zielordner", start)
        if path:
            self._update(target_dir=path, message="Bevorzugter Zielordner gespeichert.")

    @Slot()
    def clearTarget(self) -> None:  # noqa: N802
        self._update(target_dir="")

    @Slot(str)
    def setTemplate(self, label: str) -> None:  # noqa: N802
        """Bevorzugte Vorlage (Anzeige: Name; gespeichert wird ab 2.8 die ID der Vorlage)."""
        if label == NO_TEMPLATE:
            self._update(template="")
            return
        entry = self.state.find_vorlage(label)
        self._update(template=str(entry.get("id") or label) if entry else label)

    def _template_id(self, ref: str) -> str:
        entry = self.state.find_vorlage(ref) if ref else None
        return str(entry.get("id") or ref) if entry else ref

    def _template_name(self, ref: str) -> str:
        """Anzeige eines Verweises: Name der Vorlage; eine fehlende Vorlage per ID: »gelöschte Vorlage«."""
        if not ref:
            return ""
        entry = self.state.find_vorlage(ref)
        if entry is not None:
            return str(entry.get("name", ""))
        return "gelöschte Vorlage" if not template_label(ref) else ref

    def template_refs(self, template_id: str, name: str) -> list[str]:
        """IDs der Kundenakten, die diese Vorlage verwenden (per ID oder per Name aus 2.7)."""
        return [customer.id for customer in self.customers.all() if customer.template and customer.template in (template_id, name)]

    def retarget_template(self, template_id: str, old_name: str, new_ref: str) -> int:
        """Verweise auf eine Vorlage ändern: ``new_ref`` = ID (nach Umbenennen) oder "" (gelöscht)."""
        ids = self.template_refs(template_id, old_name)
        for customer_id in ids:
            if new_ref:
                self.customers.update(customer_id, template=new_ref)
            else:
                self.customers.update(customer_id, template="", template_auto=False)
        if ids:
            self.customers_changed()  # speichert und aktualisiert alle Anzeigen
        return len(ids)

    @Slot(bool)
    def setTemplateAuto(self, value: bool) -> None:  # noqa: N802
        self._update(template_auto=bool(value))

    @Slot()
    def takeTexts(self) -> None:  # noqa: N802
        kopf, fuss = self.c.header_rich(), self.c.footer_rich()
        footer = TextBlock(fuss.text, fuss.to_dict()) if fuss.text.strip() else None
        self._update(header=TextBlock(kopf.text, kopf.to_dict()), footer=footer, message="Kopf- und Fußzeile (mit Formatierung) in der Kundenakte gespeichert.")

    @Slot()
    def clearTexts(self) -> None:  # noqa: N802
        self._update(header=None, footer=None, message="Die Kundenakte verwendet keine eigene Kopf- und Fußzeile mehr.")

    @Slot()
    def applyDetail(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None:
            return
        self.flush()
        self.apply_customer(customer.id)
        self.app.navigate("create")

    @Slot()
    def useLastExcel(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None or not customer.last_excel or not Path(customer.last_excel).is_file():
            return
        self.flush()
        self.apply_customer(customer.id)
        self.app.navigate("create")
        self.c.use_excel(customer.last_excel)  # neu prüfen – nie eine alte Analyse verwenden

    @Slot()
    def openLastExcel(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is not None and customer.last_excel:
            self.app.open_file(customer.last_excel, "kunde_detail_info")

    @Slot()
    def openLastPdf(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is not None and customer.last_pdf:
            self.app.open_file(customer.last_pdf, "kunde_detail_info")

    @Slot()
    def openLastPdfFolder(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is not None and customer.last_pdf:
            self.app.open_folder_of(customer.last_pdf, "kunde_detail_info")

    @Slot()
    def merge(self) -> None:
        customer = self.current()
        if customer is None:
            return
        self.flush()
        duplicates = [other.id for other, _reasons in self.customers.duplicates(company=customer.company, number=customer.number, emails=customer.emails, exclude=customer.id)]
        others = duplicates + [c.id for c in self.customers.ordered(ORDER_RECENT) if c.id != customer.id and c.id not in duplicates]
        if not others:
            self.app.notify("kunde_detail_info", "info", "Es gibt keine weitere Kundenakte zum Zusammenführen.", auto_hide=5000, status=False)
            return
        chosen = self.choose_customer(
            candidates=others,
            title="Kundenakten zusammenführen",
            message=f"Welche Kundenakte soll in „{customer.label}“ aufgehen? E-Mail-Adressen werden vereint, neuere Einstellungen bevorzugt. PDF- und Excel-Dateien bleiben unberührt.",
        )
        other = self.customers.get(chosen)
        if other is None:
            return
        if not self.app.dialogs.confirm(
            "Kundenakten zusammenführen?",
            f"„{other.label}“ wird in „{customer.label}“ übernommen und danach entfernt. Firmenname und Kundennummer von „{customer.label}“ bleiben.",
            "Zusammenführen",
            danger=False,
        ):
            return
        self.merge_customers(customer.id, other.id)

    @Slot()
    def deleteRecord(self) -> None:  # noqa: N802
        customer = self.current()
        if customer is None:
            return
        if not self.app.dialogs.confirm(
            "Kundenakte löschen?",
            f"„{customer.label}“ und die E-Mail-Zuordnungen werden entfernt. Erstellte PDF-Dateien und Excel-Listen bleiben unverändert erhalten.",
            "Löschen",
        ):
            return
        self.delete_customer(customer.id)

    # Dialoge ------------------------------------------------------------------------------------------------------------
    def choose_customer(self, candidates: Sequence[str] | None = None, title: str = "Bekannten Kunden auswählen", message: str | None = None, exclude: str | None = None) -> str | None:
        """Dialog mit Suche: gibt die ID der gewählten Kundenakte zurück (oder ``None``)."""
        pool = [self.customers.get(ident) for ident in candidates] if candidates else self.customers.ordered(ORDER_RECENT)
        pool = [customer for customer in pool if customer is not None and customer.id != exclude]
        self._picker_pool = pool
        self.set_quietly("pickerSearch", "")
        self._refresh_picker()
        answer, result = self.app.dialogs.ask(
            "choose_customer",
            title,
            message or "",
            primary="Übernehmen",
            close="Abbrechen",
            data={"search": not candidates},
            width=560,
        )
        chosen = str(result.get("id") or "")
        if answer != dialog_service.PRIMARY:
            return None
        if not chosen and dialog_service.AUTO_ANSWER is not None:  # Tests: erster Treffer
            return pool[0].id if pool else None
        return chosen or None

    def _refresh_picker(self) -> None:
        items = self.customers.search(self.pickerSearch, self._picker_pool)
        shown = items[:MAX_ROWS]
        self.picker.set_items([customer_row(customer, self._active_id) for customer in shown])
        if not items:
            self.pickerCount = "Keine Treffer"
        elif len(shown) == len(items):
            self.pickerCount = f"{len(items)} Kundenakten" if len(items) != 1 else "1 Kundenakte"
        else:
            self.pickerCount = f"{len(shown)} von {len(items)} – Suche verfeinern"

    def ask_new_customer(self, company: str, number: str, email: str, hints: Sequence[str] = ()) -> tuple[bool, bool]:
        """Kundenakte anlegen? Rückgabe (anlegen, E-Mail-Zuordnung merken)."""
        answer, result = self.app.dialogs.ask(
            "new_customer",
            "Als Kundenakte speichern",
            "Firmenname, Kundennummer, Logo, Zielordner, Vorlage sowie Kopf- und Fußzeile werden als Kundenakte gespeichert.",
            primary="Speichern",
            close="Abbrechen",
            data={"summary": f"{company or 'Ohne Namen'} · Kundennummer {number or '–'}", "email": email, "hints": list(hints), "remember": bool(email)},
            width=520,
        )
        remember = bool(result.get("remember", bool(email)))
        return answer == dialog_service.PRIMARY, remember and bool(email)

    def ask_email_conflict(self, email: str, owners: Sequence[Customer], target_label: str) -> str:
        """Konflikt: Adresse gehört schon einer anderen Kundenakte. Rückgabe »move«, »keep« oder »cancel«."""
        names = ", ".join(f"„{owner.label}“" for owner in owners)
        answer, _result = self.app.dialogs.ask(
            "confirm",
            "E-Mail bereits zugeordnet",
            f"Diese E-Mail ist bereits der Kundenakte {names} zugeordnet:\n{email}\n\n"
            f"»Zuordnung verschieben« ordnet sie „{target_label}“ zu. »Bestehende Zuordnung verwenden« lässt sie bei {names}.",
            primary="Zuordnung verschieben",
            secondary="Bestehende Zuordnung verwenden",
            close="Abbrechen",
            default=dialog_service.CLOSE,
            width=540,
        )
        return {dialog_service.PRIMARY: "move", dialog_service.SECONDARY: "keep"}.get(answer, "cancel")

    def ask_customer_update(self, label: str, changes: Sequence[tuple[str, str, str, str]]) -> list[str]:
        """»Kundenakte aktualisieren«: Abweichungen einzeln wählbar. Rückgabe: gewählte Schlüssel."""
        answer, result = self.app.dialogs.ask(
            "customer_update",
            "Kundenakte aktualisieren",
            f"Diese Angaben der aktuellen Übersicht in „{label}“ übernehmen:",
            primary="Speichern",
            close="Abbrechen",
            data={"changes": [{"key": key, "name": name, "old": old, "new": new} for key, name, old, new in changes]},
            width=540,
        )
        if answer != dialog_service.PRIMARY:
            return []
        chosen = result.get("chosen")
        if chosen is None:  # Tests ohne Oberfläche: alle gewählt (Standard des Dialogs)
            return [key for key, _name, _old, _new in changes]
        return [key for key, _name, _old, _new in changes if key in set(chosen)]

    def ask_customer_fields(self) -> tuple[str, str, str] | None:
        """»Neue Kundenakte«: Firmenname, Kundennummer und optional eine E-Mail-Adresse."""
        answer, result = self.app.dialogs.ask("customer_fields", "Neue Kundenakte", "", primary="Anlegen", close="Abbrechen", data={}, width=500)
        if answer != dialog_service.PRIMARY:
            return None
        return str(result.get("company", "")).strip(), str(result.get("number", "")).strip(), str(result.get("email", "")).strip()


def _caption(path: str) -> tuple[str, str]:
    p = Path(path)
    parent = p.parent.name or str(p.parent)
    if p.suffix:
        return f"{p.name}  ·  {parent}", str(p)
    return (p.name or str(p)), str(p)
