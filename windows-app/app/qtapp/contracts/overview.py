"""Vertragsübersichten – Einzelmodus: Formular, Excel-Prüfung, Bereitschaft, PDF-Erstellung,
Vorlagen, Kopf- und Fußzeile, Textbausteine, Zyklus-Regeln und Verlauf (in QML: ``Contracts``).

Die Fachlogik ist dieselbe wie bis 2.6 (``tools.contract_overview``): Prüfung und PDF über
``engine``, offene Punkte über ``overview``, Vorlagen und Regeln über ``appstate.State``.
Kundenakte, Vorschau, Stapel und Vertragsvergleich haben eigene Controller; sie werden über
das Werkzeug (``tool``) erreicht.

Vorlagen 2.0 (ab 2.8): Die »Darstellung« ist die Arbeitskopie. Eine geladene Vorlage
(``vorlageId``) bleibt verknüpft; weicht die Darstellung von ihrem Stand ab, zeigt die
Oberfläche »Vorlage geändert« (``templateModified``) mit »Vorlage aktualisieren«, »Als neue
Vorlage speichern« und »Änderungen verwerfen«. Das Regelwerk der Übersicht (``ruleSetId``)
gehört zur Darstellung; eine Vorlage kann es festlegen.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from appstate import (
    DEFAULT_DATEINAME,
    DEFAULT_LOGO,
    DEFAULT_LOGO_BREITE,
    DEFAULT_TITEL,
    DEFAULT_UNTERTITEL,
    FOOTER_EXPLICIT,
    FOOTER_FORMAT,
    HEADER_FORMAT,
    baustein_rich,
    default_footer_rich,
    desktop_dir,
    footer_rich_from,
    header_rich_from,
)
from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText
from tools.contract_overview.history.models import records_from
from tools.contract_overview.overview import (
    ExcelAnalysis,
    contract_summary,
    excel_files,
    excel_issues,
    output_issues,
    parse_width,
    pdf_fields,
    template_layout,
    template_rules,
    valid_width,
)
from tools.contract_overview.preview import RENDER_LOCK
from tools.contract_overview.templates.models import ENTRY_RULE_SET

from .. import files
from ..base import Observable, Var, prop
from ..models import KeyedListModel
from .richtext import RichTextDocument

EXCEL_EMPTY = "Excel-Datei wählen oder in das Fenster ziehen – sie wird sofort geprüft."
DROP_EXCEL = "Loslassen, um die Excel-Datei zu übernehmen und zu prüfen."
PLACEHOLDERS = "Platzhalter: {kd}  {kunde}  {firma}  {datum}  {datumkurz} – auch formatiert"
FILENAME_PLACEHOLDERS = "Platzhalter: {kd}  {kunde}  {datum}  {datumkurz}"
# Tastenhinweis in der Statuszeile, solange eine Seite des Werkzeugs sichtbar ist
HINT = "Strg+Enter  PDF erstellen   ·   Strg+O  Excel öffnen   ·   Strg+F  Kunde suchen"
HINT_PLAIN = "Strg+Enter  PDF erstellen   ·   Strg+O  Excel öffnen"  # ohne Kundenakte
# Formularwerte: Property in QML → Schlüssel in gui-config.json (wie bis 2.6)
FORM_KEYS = {
    "firma": "firmenname",
    "kd": "kundennummer",
    "mail": "rechnungsempfaenger",
    "excel": "excel",
    "logo": "logo",
    "ziel": "zielordner",
    "dateiname": "dateiname",
    "format": "format",
    "breite": "logo_breite",
    "titel": "titel",
    "untertitel": "untertitel",
}


def path_caption(path: str, empty: str) -> tuple[str, str]:
    """»Datei.xlsx · Ordner« und der volle Pfad (für den Tooltip)."""
    if not path:
        return empty, ""
    p = Path(path)
    parent = p.parent.name or str(p.parent)
    if p.suffix:
        return f"{p.name}  ·  {parent}", str(p)
    return (p.name or str(p)), str(p)


class ContractOverviewController(Observable):
    """Einzelmodus von »Vertragsübersichten«."""

    # Formular (Namen und Bedeutung wie in 2.0.5)
    firmaChanged, firma = prop(str, "firma", "")
    kdChanged, kd = prop(str, "kd", "")
    mailChanged, mail = prop(str, "mail", "")
    excelChanged, excel = prop(str, "excel", "")
    logoChanged, logo = prop(str, "logo", "")
    zielChanged, ziel = prop(str, "ziel", "")
    dateinameChanged, dateiname = prop(str, "dateiname", DEFAULT_DATEINAME)
    formatChanged, format = prop(str, "format", "hoch")
    breiteChanged, breite = prop(str, "breite", DEFAULT_LOGO_BREITE)
    titelChanged, titel = prop(str, "titel", DEFAULT_TITEL)
    untertitelChanged, untertitel = prop(str, "untertitel", DEFAULT_UNTERTITEL)
    pdfOeffnenChanged, pdfOeffnen = prop(bool, "pdfOeffnen", True)
    bausteinChanged, baustein = prop(str, "baustein", "")
    vorlageChanged, vorlage = prop(str, "vorlage", "")
    # Vorlagen 2.0 und Regelwerk
    vorlageIdChanged, vorlageId = prop(str, "vorlageId", "")
    templateRevisionChanged, templateRevision = prop(int, "templateRevision", 0)  # Auswahlliste neu gefüllt
    templateLabelChanged, templateLabel = prop(str, "templateLabel", "")
    templateModifiedChanged, templateModified = prop(bool, "templateModified", False)
    defaultTemplateChanged, defaultTemplate = prop(str, "defaultTemplate", "")
    ruleSetIdChanged, ruleSetId = prop(str, "ruleSetId", "")
    ruleSetLabelChanged, ruleSetLabel = prop(str, "ruleSetLabel", "")
    ruleSetChoicesChanged, ruleSetChoices = prop(list, "ruleSetChoices", [])
    regelSuchChanged, regelSuch = prop(str, "regelSuch", "")
    regelZykChanged, regelZyk = prop(str, "regelZyk", "")

    # Anzeige
    excelLabelChanged, excelLabel = prop(str, "excelLabel", "Keine Datei gewählt")
    excelPathChanged, excelPath = prop(str, "excelPath", "")
    logoLabelChanged, logoLabel = prop(str, "logoLabel", "Kein Logo gewählt")
    logoPathChanged, logoPath = prop(str, "logoPath", "")
    zielLabelChanged, zielLabel = prop(str, "zielLabel", "Keine Auswahl")
    zielPathChanged, zielPath = prop(str, "zielPath", "")
    mailValueChanged, mailValue = prop(str, "mailValue", "")
    mailChoicesChanged, mailChoices = prop(list, "mailChoices", [])
    factsChanged, facts = prop(list, "facts", [])
    detailsVisibleChanged, detailsVisible = prop(bool, "detailsVisible", False)
    detailsAnimateChanged, detailsAnimate = prop(bool, "detailsAnimate", True)
    readyKindChanged, readyKind = prop(str, "readyKind", "neutral")
    readyTextChanged, readyText = prop(str, "readyText", "")
    busyChanged, busy = prop(bool, "busy", False)
    kdRequiredChanged, kdRequired = prop(bool, "kdRequired", False)
    errorsChanged, errors = prop(dict, "errors", {})
    dropHighlightChanged, dropHighlight = prop(bool, "dropHighlight", False)
    recentChoiceChanged, recentChoice = prop(str, "recentChoice", "")

    focusRequested = Signal(str)  # Feldname (kd, firma, mail, breite, vorlage, regelSuch, regelZyk)

    def __init__(self, app, tool, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.state = app.state
        self.set_quietly("firma", cfg.get("firmenname", ""))
        self.set_quietly("kd", cfg.get("kundennummer", ""))
        self.set_quietly("mail", cfg.get("rechnungsempfaenger", ""))
        self.set_quietly("excel", cfg.get("excel", ""))
        self.set_quietly("logo", cfg.get("logo") or (str(DEFAULT_LOGO) if DEFAULT_LOGO.is_file() else ""))
        self.set_quietly("ziel", cfg.get("zielordner") or str(desktop_dir()))
        self.set_quietly("dateiname", cfg.get("dateiname", DEFAULT_DATEINAME))
        self.set_quietly("format", cfg.get("format", "hoch") if cfg.get("format") in ("hoch", "quer") else "hoch")
        self.set_quietly("breite", str(cfg.get("logo_breite", DEFAULT_LOGO_BREITE)))
        self.set_quietly("titel", cfg.get("titel", DEFAULT_TITEL))
        self.set_quietly("untertitel", cfg.get("untertitel", DEFAULT_UNTERTITEL))
        self.set_quietly("pdfOeffnen", bool(cfg.get("pdf_oeffnen", True)))
        self.set_quietly("baustein", cfg.get("baustein_name", ""))
        self.set_quietly("vorlageId", str(cfg.get("vorlage_aktiv") or ""))
        self.set_quietly("defaultTemplate", str(cfg.get("vorlage_standard") or ""))
        self.set_quietly("ruleSetId", str(cfg.get("regelwerk") or ""))
        # Stand der Darstellung beim Laden/Speichern der Vorlage (Prüfsumme) – »Vorlage geändert«
        self._template_baseline = str(cfg.get("vorlage_stand") or "")
        # Formularwerte mit derselben Schnittstelle wie bisher (get/set/trace_add)
        self.var_firma, self.var_kd, self.var_mail = Var(self, "firma"), Var(self, "kd"), Var(self, "mail")
        self.var_excel, self.var_logo, self.var_ziel = Var(self, "excel"), Var(self, "logo"), Var(self, "ziel")
        self.var_name, self.var_format, self.var_breite = Var(self, "dateiname"), Var(self, "format"), Var(self, "breite")
        self.var_titel, self.var_untertitel = Var(self, "titel"), Var(self, "untertitel")
        self.var_open, self.var_baustein, self.var_vorlage = Var(self, "pdfOeffnen"), Var(self, "baustein"), Var(self, "vorlage")
        self.var_regel_such, self.var_regel_zyk = Var(self, "regelSuch"), Var(self, "regelZyk")
        # Kopf- und Fußzeile samt Formatierung. Ohne bewusst gespeicherte Fußzeile gilt die
        # Standard-Fußzeile (auch nach einem Update), ohne gespeicherte Formatierung das Standardformat.
        self.header = RichTextDocument(HEADER_STYLE, HEADER_ALIGN, header_rich_from(cfg), on_change=self.app.schedule_save, parent=self)
        self.footer = RichTextDocument(FOOTER_STYLE, FOOTER_ALIGN, footer_rich_from(cfg), on_change=self.app.schedule_save, parent=self)
        self.templates = KeyedListModel(("id", "name", "standard"), key="id", parent=self)
        self.textBlocks = KeyedListModel(("name",), key="name", parent=self)
        self.rules = KeyedListModel(("index", "enthaelt", "zyklus"), key="key", parent=self)
        self.recentPdfs = KeyedListModel(("path",), key="label", parent=self)
        self._excel_mails: list[str] = []
        # Ergebnis der Excel-Prüfung für die gewählte Datei (``None``: Prüfung läuft bzw. keine Datei)
        self._analysis: dict | None = None
        self._analysis_path = ""
        self._undo_overview: tuple[str, str, str, str] | None = None
        self._undo_layout: dict | None = None
        self._undo_overview_customer: dict | None = None
        self._drag_saved: tuple | None = None
        self._pdf_by_label: dict[str, str] = {}
        self._undo_customer: tuple[tuple[str, str, str], dict | None] | None = None
        self._initial_check = False
        self._undo_footer_rich: RichText | None = None
        self.pdf_runs = 0

    # Einrichtung -------------------------------------------------------------------------------
    def start(self) -> None:
        """Nach dem Einrichten aller Controller: Beobachter verbinden, Listen füllen, Excel prüfen."""
        for name in ("firma", "kd", "mail", "excel", "logo", "ziel", "dateiname", "format", "breite", "titel", "untertitel", "pdfOeffnen", "baustein"):
            self.observe(name, lambda _value: self.app.schedule_save())
        # »Bereit zum Erstellen« (und die Zeile der aktiven Kundenakte) folgen jeder Änderung.
        for name in ("firma", "kd", "mail", "excel", "logo", "ziel", "breite", "vorlage"):
            self.observe(name, lambda _value: self.update_readiness())
        self.observe("excel", lambda _value: self.refresh_files())
        self.observe("logo", lambda _value: self.refresh_files())
        self.observe("ziel", lambda _value: self.refresh_files())
        self.observe("kd", lambda _value: self._clear_error("kd") if self.kd.strip() else None)
        # »Vorlage geändert« folgt jeder Änderung der Darstellung (gesammelt im nächsten Durchlauf).
        for name in ("logo", "format", "dateiname", "breite", "titel", "untertitel", "ruleSetId"):
            self.observe(name, lambda _value: self.template_state_soon())
        self.reload_pdfs()
        self.reload_rule_sets()
        self.reload_vorlagen()
        self.reload_bausteine()
        self.reload_regeln()
        self.refresh_files()
        self.app.notify("info_excel", "neutral", EXCEL_EMPTY, status=False, animate=False)
        self.update_readiness(now=True)
        # Eine gespeicherte Excel-Liste wird im Hintergrund geprüft; der Hinweis
        # »Excel wird geprüft …« gehört damit schon zum ersten sichtbaren Bild.
        excel = self.excel.strip()
        if excel and Path(excel).is_file():
            self._initial_check = True
            self.inspect_excel(excel)

    def config(self) -> dict:
        """Gespeicherte Werte (Schlüssel wie bisher – alte Einstellungen bleiben gültig)."""
        fuss = self.footer_rich()
        kopf = self.header_rich()
        return {
            "firmenname": self.firma.strip(),
            "kundennummer": self.kd.strip(),
            "rechnungsempfaenger": self.mail.strip(),
            "excel": self.excel.strip(),
            "logo": self.logo.strip(),
            "zielordner": self.ziel.strip(),
            "dateiname": self.dateiname.strip(),
            "format": self.format,
            "logo_breite": self.breite.strip(),
            "titel": self.titel.strip(),
            "untertitel": self.untertitel.strip(),
            "fusszeile": fuss.text,
            FOOTER_FORMAT: fuss.to_dict(),
            FOOTER_EXPLICIT: True,
            "kopfzeile": kopf.text,
            HEADER_FORMAT: kopf.to_dict(),
            "baustein_name": self.baustein.strip(),
            "bausteine": self.state.bausteine,
            "pdfs": self.state.pdfs[:8],
            "regeln": self.state.regeln,
            # Vorlagen liegen ab 2.8 in eigenen Dateien; die bisherige Liste bleibt unverändert stehen.
            **({"vorlagen": self.state.vorlagen} if self.state.templates is None else {}),
            "staende": self.state.staende,
            "pdf_oeffnen": bool(self.pdfOeffnen),
            "vorlage_aktiv": self.vorlageId or None,
            "vorlage_stand": self._template_baseline if self.vorlageId else None,
            "vorlage_standard": self.defaultTemplate or None,
            "regelwerk": self.ruleSetId or None,
        }

    # Hilfen -------------------------------------------------------------------------------------
    def notify(self, *args, **kwargs) -> None:
        self.app.notify(*args, **kwargs)

    def hide_notice(self, area: str, animate: bool = True) -> None:
        self.app.hide_notice(area, animate=animate)

    def set_status(self, text: str, kind: str = "neutral") -> None:
        self.app.set_status(text, kind)

    def _set_error(self, field: str, value: bool = True) -> None:
        errors = dict(self.errors)
        if bool(errors.get(field)) != value:
            errors[field] = value
            self.errors = errors

    def _clear_error(self, field: str) -> None:
        self._set_error(field, False)

    @Slot(str)
    def clearError(self, field: str) -> None:  # noqa: N802
        self._clear_error(field)

    def _focus(self, field: str) -> None:
        self.focusRequested.emit(field)

    # Dateien ------------------------------------------------------------------------------------
    def refresh_files(self) -> None:
        excel, logo, ziel = self.excel.strip(), self.logo.strip(), self.ziel.strip()
        self.excelLabel, self.excelPath = path_caption(excel, "Keine Datei gewählt")
        self.logoLabel, self.logoPath = path_caption(logo, "Kein Logo gewählt")
        if ziel:
            self.zielLabel, self.zielPath = (Path(ziel).name or ziel), ziel
        else:
            self.zielLabel, self.zielPath = "Keine Auswahl", ""

    @Slot()
    def pickExcel(self) -> None:  # noqa: N802
        path = files.open_file("Excel-Liste wählen", self.app.initial_dir("excel", self.excel.strip()), files.EXCEL_FILTER)
        if path:
            self.use_excel(path)

    def pick_excel(self) -> None:
        self.pickExcel()

    def use_excel(self, path: str) -> None:
        self.app.remember_dir("excel", path)
        self.excel = path
        self.refresh_files()
        self.inspect_excel(path)

    @Slot()
    def pickLogo(self) -> None:  # noqa: N802
        current = self.logo.strip()
        try:
            if current and Path(current).resolve().parent == DEFAULT_LOGO.resolve().parent:
                current = ""  # Standardlogo: lieber den zuletzt benutzten eigenen Ordner zeigen
        except OSError:
            pass
        path = files.open_file("Logo wählen", self.app.initial_dir("logo", current), files.IMAGE_FILTER)
        if path:
            self.app.remember_dir("logo", path)
            self.logo = path
            self.refresh_files()
            self.set_status(f"Logo gewählt: {Path(path).name}", "success")

    def pick_logo(self) -> None:
        self.pickLogo()

    @Slot()
    def pickZiel(self) -> None:  # noqa: N802
        path = files.pick_folder("Zielordner für die PDF", self.app.initial_dir("ziel", self.ziel.strip()))
        if path:
            self.ziel = path
            self.refresh_files()
            self.set_status(f"Zielordner: {path}", "success")

    def pick_ziel(self) -> None:
        self.pickZiel()

    def target_folder(self) -> str:
        """Zielordner der PDF (ohne Auswahl: der Desktop)."""
        return self.ziel.strip() or str(desktop_dir())

    @Slot()
    def useDefaultLogo(self) -> None:  # noqa: N802
        if DEFAULT_LOGO.is_file():
            self.logo = str(DEFAULT_LOGO)
            self.refresh_files()
            self.notify("dateien_info", "success", "Das Standardlogo wird verwendet.", auto_hide=4000)
        else:
            self.notify("dateien_info", "warning", "Es ist kein Standardlogo installiert.")

    def use_default_logo(self) -> None:
        self.useDefaultLogo()

    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        ziel = self.ziel.strip()
        if not ziel or not Path(ziel).is_dir():
            self.notify("pdf_info", "warning", "Der Zielordner ist nicht vorhanden.", actions=(("Ordner wählen", self.pick_ziel),))
            return
        try:
            files.open_path(ziel)
        except OSError as exc:
            self.notify("pdf_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    @Slot()
    def copyExcelPath(self) -> None:  # noqa: N802
        self.app.copy_path(self.excel)

    @Slot()
    def copyLogoPath(self) -> None:  # noqa: N802
        self.app.copy_path(self.logo)

    @Slot()
    def copyTargetPath(self) -> None:  # noqa: N802
        self.app.copy_path(self.target_folder())

    # Ziehen und Ablegen ---------------------------------------------------------------------------
    def accepts(self, dropped: list[str]) -> bool:
        return bool(excel_files(dropped))

    def drag_enter(self, accepted: bool) -> None:
        """Datei wird über das Fenster gezogen: Excel-Bereich hervorheben."""
        if not accepted:
            return
        notice = self.app.notices.get("info_excel")
        if self._drag_saved is None:
            self._drag_saved = (notice.severity, notice.message, notice.title)
        self.dropHighlight = True
        notice.show("info", DROP_EXCEL, animate=False)
        if self.app.currentPage != "create":
            self.set_status("Excel-Datei loslassen – sie wird in »Vertragsübersichten« geprüft.", "info")

    def drag_leave(self) -> None:
        self.dropHighlight = False
        saved, self._drag_saved = self._drag_saved, None
        notice = self.app.notices.get("info_excel")
        if saved is not None and notice.message.startswith("Loslassen"):
            severity, message, title = saved
            notice.show(severity, message, title, animate=False)

    def drop(self, dropped: list[str]) -> None:
        self.drag_leave()
        excel = next(iter(excel_files(dropped)), "")
        if not excel:
            self.notify("info_excel", "warning", "Bitte eine Excel-Datei (.xlsx oder .xls) in das Fenster ziehen.")
            return
        if self.app.currentPage != "create":
            self.app.navigate("create")
        self.use_excel(excel)

    # Excel-Prüfung ------------------------------------------------------------------------------
    def inspect_excel(self, path: str) -> None:
        self._analysis = None
        self._analysis_path = path
        self.notify("info_excel", "info", "Excel wird geprüft …", status=False)
        self.set_status("Excel wird geprüft …", "busy")
        self.update_readiness()
        self.tool.preview_dirty()
        regeln = [dict(r) for r in self.state.regeln]

        def work() -> dict:
            from engine import pruefe_excel

            return pruefe_excel(Path(path), regeln)

        def failed(exc, _tb) -> None:
            self._show_check(path, {"ok": False, "text": str(exc), "kunden": [], "mails": [], "firmen": [], "zeilen": []})

        self.app.worker.run(work, lambda result: self._show_check(path, result), failed)

    def _show_check(self, path: str, result: dict) -> None:
        if self.excel.strip() != path:
            return
        # Das Ergebnis der Prüfung beim Start erscheint ohne Ein-/Ausklapp-Animation.
        animate = not self._initial_check
        self._initial_check = False
        self._analysis = result
        self._analysis_path = path
        text = str(result.get("text", ""))
        customers = self.tool.customers
        if not result.get("ok"):
            self.notify("info_excel", "error", text or "Die Datei konnte nicht gelesen werden.", title="Excel-Prüfung fehlgeschlagen", animate=animate)
            self._set_mails([], animate=animate)
            customers.recognize(path, result, animate)
            self.refresh_excel_details(animate)
            self.update_readiness()
            self.tool.preview_dirty()
            self.tool.refresh_comparison()
            return
        mails = [str(mail) for mail in result.get("mails") or []]
        aktiv = int(result.get("aktiv", 0) or 0)
        inaktiv = int(result.get("inaktiv", 0) or 0)
        fehlend = [str(name) for name in result.get("fehlend") or []]
        # Die Statuszeile nennt die Vertragszahlen – darunter stehen sie nicht noch einmal.
        vertraege = contract_summary(aktiv, inaktiv)
        if fehlend:
            spalten = ", ".join(f"»{name}«" for name in fehlend)
            self.notify("info_excel", "error", f"Für die PDF fehlt {'die Spalte' if len(fehlend) == 1 else 'die Spalten'} {spalten}.", title="Spalten fehlen", status=False, animate=animate)
        elif aktiv == 0:
            self.notify("info_excel", "warning", "In der Datei steht kein aktiver Vertrag." + (f" {inaktiv} inaktive wurden ausgeblendet." if inaktiv else ""), title="Keine aktiven Verträge", status=False, animate=animate)
        else:
            self.notify("info_excel", "success", vertraege, title="Excel geprüft", status=False, animate=animate)
        self.set_status(f"Excel geprüft: {text}", "success" if aktiv and not fehlend else "warning")
        self._set_mails(mails, animate=animate)
        # Bekannte Kunden über die Rechnungsempfänger erkennen – vor dem Füllen aus der Datei,
        # damit »automatisch übernehmen« den unveränderten Stand des Formulars sieht.
        customers.recognize(path, result, animate)
        # Nur Werte übernehmen, die tatsächlich in der Datei stehen – nie aus der E-Mail-Adresse raten.
        if not self.kd.strip() and len(result.get("kunden") or []) == 1:
            self.kd = result["kunden"][0]
        if not self.firma.strip() and len(result.get("firmen") or []) == 1:
            self.firma = result["firmen"][0]
        self.refresh_excel_details(animate)
        self.update_readiness()
        self.tool.preview_dirty()
        self.tool.refresh_comparison()  # nur Anzeige – keine neue Vorschau

    def analysis(self) -> dict | None:
        return self._analysis

    def analysis_for_current(self) -> dict | None:
        """Ergebnis der Prüfung, wenn es zur gewählten Excel gehört."""
        return self._analysis if self._analysis_path == self.excel.strip() else None

    def analysis_mails(self) -> list[str]:
        result = self.analysis_for_current()
        if result is None or not result.get("ok"):
            return []
        return [str(mail) for mail in result.get("mails") or []]

    def excel_mails(self) -> list[str]:
        return list(self._excel_mails)

    def _excel_facts(self) -> list[dict]:
        """Angaben unter der Statuszeile – nur, was sie nicht schon nennt und was weiterhilft.

        Keine Vertragszahlen (stehen in der Statuszeile), keine leeren Zeilen und nichts,
        was die Kundendaten ohnehin zeigen. Nie etwas aus der E-Mail-Adresse erraten.
        """
        result = self._analysis
        if result is None or not result.get("ok") or self._analysis_path != self.excel.strip():
            return []
        facts: list[tuple[str, str, str]] = []
        customer = self.tool.customers.customer_fact()
        if customer is not None:
            facts.append(customer)
        kunden = [str(kd) for kd in result.get("kunden") or []]
        if len(kunden) > 1:
            facts.append(("Kundennummer", f"{len(kunden)} verschiedene in der Datei: " + ", ".join(kunden), "caution"))
        elif len(kunden) == 1 and self.tool.customers.active_customer() is None:
            eingetragen = self.kd.strip()
            if eingetragen and eingetragen != kunden[0]:
                facts.append(("Kundennummer", f"{kunden[0]} laut Datei – eingetragen ist {eingetragen}", "caution"))
        firmen = [str(firma) for firma in result.get("firmen") or []]
        if len(firmen) > 1:
            facts.append(("Firmenname", f"{len(firmen)} verschiedene in der Datei: " + ", ".join(firmen), "caution"))
        fett = int(result.get("fett", 0) or 0)
        if fett:
            facts.append(("Fettschrift", f"{fett} {'Zelle' if fett == 1 else 'Zellen'} in der PDF fett", "muted"))
        for hinweis in result.get("hinweise") or []:
            if "Rechnungsempfänger" in str(hinweis):
                continue  # der Empfänger ist optional – ohne Spalte ist das kein Hinweis wert
            facts.append(("Hinweis", str(hinweis), "muted"))
        return [{"label": label, "value": value, "tone": tone} for label, value, tone in facts]

    def refresh_excel_details(self, animate: bool = False) -> None:
        """Zeilen unter der Excel-Prüfung neu bestimmen (nach Prüfung, Übernahme, Lösen …)."""
        facts = self._excel_facts()
        mails = self._excel_mails if self._excel_facts_allowed() else []
        self.facts = facts
        self.detailsAnimate = bool(animate)
        self.detailsVisible = bool(facts or mails)

    def _excel_facts_allowed(self) -> bool:
        result = self._analysis
        return result is not None and bool(result.get("ok")) and self._analysis_path == self.excel.strip()

    def _set_mails(self, mails: list[str], animate: bool = True) -> None:
        """Rechnungsempfänger der Excel: eine Adresse als Wert, mehrere als »3 erkannt« mit Auswahl."""
        self._excel_mails = mails
        if len(mails) > 1:
            self.mailValue = f"{len(mails)} erkannt"
            self.mailChoices = list(mails)
        else:
            self.mailValue = mails[0] if mails else ""
            self.mailChoices = []
        self.refresh_excel_details(animate)

    @Slot(str)
    def pickMail(self, mail: str) -> None:  # noqa: N802
        """Empfänger aus der Excel wählen: übernimmt die Adresse in das Feld Rechnungsempfänger."""
        if mail:
            self.mail = mail
            self.set_status(f"Rechnungsempfänger: {mail}", "success")

    # Bereitschaft ------------------------------------------------------------------------------------
    def readiness(self) -> list[tuple[str, str]]:
        """Offene Punkte vor dem Erstellen als (Bereich, Text); leer = bereit."""
        excel = self.excel.strip()
        analysis = ExcelAnalysis.from_result(self._analysis) if self._analysis_path == excel else None
        issues = excel_issues(excel, analysis)
        issues += output_issues(self.kd, self._excel_mails, self.mail, self.logo, self.breite, self.target_folder())
        return [(issue.area, issue.text) for issue in issues]

    def update_readiness(self, now: bool = False) -> None:
        """Anzeige »Bereit zum Erstellen« aktualisieren – gesammelt im nächsten Durchlauf."""
        if now:
            self._run_readiness()
        else:
            self.app.timers.soon("readiness", self._run_readiness)

    def _run_readiness(self) -> None:
        self.tool.customers.refresh_line()
        issues = self.readiness()
        if not issues:
            self.readyKind, self.readyText = "success", "Bereit zum Erstellen"
        elif issues[0][0] == "busy" and len(issues) == 1:
            self.readyKind, self.readyText = "busy", issues[0][1]
        else:
            texts = [text for area, text in issues if area != "busy"]
            more = len(texts) - 2
            label = " · ".join(texts[:2]) + (f" · {more} weitere" if more > 0 else "")
            kind = "critical" if any(area == "excel" for area, _t in issues) and self.excel.strip() else "caution"
            self.readyKind, self.readyText = kind, label

    @Slot()
    def fixReadiness(self) -> None:  # noqa: N802
        """Zum ersten offenen Punkt springen (Klick auf die Bereitschaftsanzeige)."""
        issues = [issue for issue in self.readiness() if issue[0] != "busy"]
        if not issues:
            return
        area, text = issues[0]
        if area == "excel":
            if self.excel.strip() and Path(self.excel.strip()).is_file():
                self.notify("pdf_info", "warning", text, actions=(("Andere Excel wählen", self.pick_excel),))
            else:
                self.pick_excel()
        elif area == "kd":
            self.kdRequired = True
            self._set_error("kd")
            self._focus("kd")
        elif area == "mail":
            self._focus("mail")
        elif area == "logo":
            self.notify("pdf_info", "warning", text, actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo)))
        elif area == "breite":
            self.app.navigate("layout")
            self.app.timers.later("require:breite", 50, lambda: self._require(False, "Die Logo-Breite muss eine positive Zahl sein (z. B. 62).", "breite", page="layout"))
        elif area == "ziel":
            self.notify("pdf_info", "warning", text, actions=(("Ordner wählen", self.pick_ziel),))

    # Kundendaten ------------------------------------------------------------------------------------
    @Slot()
    def clearCustomer(self) -> None:  # noqa: N802
        """Kundendaten leeren (rückgängig machbar). Eine aktive Kundenakte wird gelöst – nicht gelöscht."""
        previous = (self.firma, self.kd, self.mail)
        customer = self.tool.customers.leave()
        self.firma = ""
        self.kd = ""
        self.mail = ""
        if any(value.strip() for value in previous) or customer:
            self._undo_customer = (previous, customer)
            self.notify("kunde_info", "info", "Kundendaten wurden geleert.", actions=(("Rückgängig", self._undo_clear),), auto_hide=8000)

    def _undo_clear(self) -> None:
        if self._undo_customer:
            (firma, kd, mail), customer = self._undo_customer
            self.firma = firma
            self.kd = kd
            self.mail = mail
            self.tool.customers.return_to(customer)
            self._undo_customer = None
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten wiederhergestellt.", "success")

    # Verlauf »Zuletzt erstellt« -------------------------------------------------------------------------
    @Slot()
    def clearHistory(self) -> None:  # noqa: N802
        """Liste »Zuletzt erstellt« leeren. Kundenakten werden in der Ansicht »Kunden« verwaltet."""
        if not self.app.dialogs.confirm("Verlauf löschen?", "Die Liste »Zuletzt erstellt« wird geleert. Erstellte PDF-Dateien und Kundenakten bleiben erhalten.", "Verlauf löschen"):
            return
        self.state.pdfs = []
        self.reload_pdfs()
        self.app.persist()
        self.notify("daten_info", "success", "Der Verlauf wurde gelöscht.", auto_hide=5000)

    def reload_pdfs(self) -> None:
        self._pdf_by_label = self.state.existing_pdfs()
        self.recentPdfs.set_items([{"label": label, "path": path} for label, path in self._pdf_by_label.items()])
        labels = list(self._pdf_by_label)
        self.recentChoice = labels[0] if labels else ""

    @Slot(str)
    def chooseRecent(self, label: str) -> None:  # noqa: N802
        self.recentChoice = label

    def _remember_pdf(self, path: Path) -> None:
        self.state.remember_pdf(str(path))
        self.reload_pdfs()

    @Slot()
    def openRecentPdf(self) -> None:  # noqa: N802
        pfad = self._pdf_by_label.get(self.recentChoice)
        if not pfad or not Path(pfad).is_file():
            self.notify("pdf_info", "warning", "Keine gespeicherte PDF zum Öffnen.")
            return
        self.app.open_file(Path(pfad), "pdf_info")

    # Kopf- und Fußzeile --------------------------------------------------------------------------------
    def header_rich(self) -> RichText:
        """Aktuelle Kopfzeile mit Formatierung (Inhalt des Editors)."""
        return self.header.rich()

    def footer_rich(self) -> RichText:
        """Aktuelle Fußzeile mit Formatierung – exakt mit allen Zeilenumbrüchen."""
        return self.footer.rich()

    def header_text(self) -> str:
        return self.header_rich().text

    def footer_text(self) -> str:
        return self.footer_rich().text

    def set_header(self, rich: RichText) -> None:
        self.header.set_rich(rich)
        self.tool.preview_dirty()
        self.template_state_soon()

    def set_footer(self, rich: RichText) -> None:
        self.footer.set_rich(rich)
        self.tool.preview_dirty()
        self.template_state_soon()

    @Slot()
    def saveHeader(self) -> None:  # noqa: N802
        """Aktuellen Inhalt samt Formatierung speichern (Einstellungen) – die Vorschau folgt."""
        kopf = self.header_rich()
        self.tool.preview_dirty()
        self.app.persist()
        if not kopf.is_blank():
            self.notify("kopf_info", "success", "Die Kopfzeile wurde gespeichert.", auto_hide=5000)
        else:
            self.notify("kopf_info", "info", "Die Kopfzeile ist leer und erscheint nicht in der PDF.", auto_hide=6000)

    @Slot()
    def saveFooter(self) -> None:  # noqa: N802
        name = self.baustein.strip()
        rich = self.footer_rich()  # aktueller Inhalt des Editors samt Formatierung
        if name:
            self.state.save_baustein(name, rich.text, rich.to_dict())
        self.tool.preview_dirty()
        self.app.persist()
        self.reload_bausteine()
        if name:
            self.notify("fuss_info", "success", f"Die Fußzeile und der Textbaustein „{name}“ wurden gespeichert.", auto_hide=5000)
        else:
            self.notify("fuss_info", "success", "Die Fußzeile wurde gespeichert.", auto_hide=5000)

    @Slot()
    def restoreDefaultFooter(self) -> None:  # noqa: N802
        """Standardtext und Standardformatierung wiederherstellen (rückgängig machbar, daher ohne Rückfrage)."""
        previous = self.footer_rich()
        default = default_footer_rich()
        self.footer.replace_rich(default)
        self.tool.preview_dirty()
        self.app.persist()
        actions = ()
        if previous != default:
            actions = (("Rückgängig", lambda: self._undo_footer(previous)),)
        self.notify("fuss_info", "success", "Standard-Fußzeile wiederhergestellt.", actions=actions, auto_hide=8000)

    def _undo_footer(self, previous: RichText) -> None:
        self.footer.replace_rich(previous)
        self.tool.preview_dirty()
        self.app.persist()
        self.hide_notice("fuss_info")
        self.set_status("Vorherige Fußzeile wiederhergestellt.", "success")

    # Textbausteine ------------------------------------------------------------------------------------
    def reload_bausteine(self) -> None:
        self.textBlocks.set_items([{"name": str(eintrag.get("name", ""))} for eintrag in self.state.bausteine if str(eintrag.get("name", ""))])

    @Slot(str)
    def pickBaustein(self, label: str) -> None:  # noqa: N802
        eintrag = self.state.find_baustein(label)
        if eintrag:
            self._apply_baustein(eintrag)

    def _apply_baustein(self, eintrag: dict) -> None:
        self.baustein = str(eintrag.get("name", ""))
        # Alte Bausteine (nur Text) erhalten die Standardformatierung.
        self.set_footer(baustein_rich(eintrag))
        self.app.schedule_save()
        self.set_status(f"Textbaustein „{eintrag.get('name', '')}“ geladen.", "success")

    @Slot()
    def deleteBaustein(self) -> None:  # noqa: N802
        name = self.baustein.strip()
        if not name:
            self.notify("fuss_info", "warning", "Bitte zuerst einen Textbaustein wählen oder seinen Namen eintragen.")
            return
        if self.state.find_baustein(name) is None:
            self.notify("fuss_info", "warning", f"Kein Textbaustein mit dem Namen „{name}“.")
            return
        if not self.app.dialogs.confirm("Textbaustein löschen?", f"Der Textbaustein „{name}“ wird dauerhaft entfernt.", "Löschen"):
            return
        self.state.delete_baustein(name)
        self.baustein = ""
        self.app.persist()
        self.reload_bausteine()
        self.notify("fuss_info", "success", f"Textbaustein „{name}“ gelöscht.", auto_hide=5000)

    # Vorlagen ------------------------------------------------------------------------------------------------
    def reload_vorlagen(self) -> None:
        """Auswahllisten der Vorlagen (alphabetisch) samt Standard-Kennzeichen neu füllen."""
        store = self.state.templates
        if store is None:
            entries = [{"id": str(e.get("name", "")), "name": str(e.get("name", "")), "standard": False} for e in self.state.vorlagen if str(e.get("name", ""))]
        else:
            if self.defaultTemplate and store.get(self.defaultTemplate) is None:
                self.defaultTemplate = ""
            if self.vorlageId and store.get(self.vorlageId) is None:
                self.vorlageId = ""  # geladene Vorlage wurde gelöscht: die Darstellung bleibt
            entries = [{"id": tpl.id, "name": tpl.name, "standard": tpl.id == self.defaultTemplate} for tpl in store.templates()]
        self.templates.set_items(entries)
        self.templateRevision += 1  # QML: gewählten Eintrag neu bestimmen (Reihenfolge, neue Vorlagen)
        self._refresh_template_label()
        self.refresh_template_state()

    def _refresh_template_label(self) -> None:
        template = self.state.templates.get(self.vorlageId) if self.state.templates is not None else None
        self.templateLabel = template.name if template is not None else ""
        if template is not None:
            self.vorlage = template.name

    def template_entry(self) -> dict | None:
        """Wörterbuch der geladenen Vorlage (oder ``None``)."""
        return self.state.find_vorlage(self.vorlageId) if self.vorlageId else None

    def _work_signature(self) -> str:
        """Prüfsumme der Darstellung – alles, was eine Vorlage festhält."""
        data = {
            "logo": self.logo.strip(),
            "format": self.format,
            "dateiname": self.dateiname.strip(),
            "breite": self.breite.strip(),
            "titel": self.titel.strip(),
            "untertitel": self.untertitel.strip(),
            "kopf": self.header_rich().to_dict(),
            "fuss": self.footer_rich().to_dict(),
            "regeln": self.state.regeln,
            "regelwerk": self.ruleSetId,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]

    def template_state_soon(self) -> None:
        self.app.timers.soon("template-state", self.refresh_template_state)

    def refresh_template_state(self) -> None:
        self.templateModified = bool(self.vorlageId) and self._template_baseline != self._work_signature()

    def _mark_template(self, template_id: str) -> None:
        """Vorlage gilt als geladen und unverändert (nach Anwenden oder Speichern)."""
        self.vorlageId = template_id
        self._refresh_template_label()
        self._template_baseline = self._work_signature()
        self.templateModified = False

    def current_entry(self, name: str) -> dict:
        """Die aktuelle Darstellung als Vorlage (Wörterbuch wie bisher, plus Regelwerk)."""
        kopf = self.header_rich()
        fuss = self.footer_rich()
        return {
            "name": name,
            "logo": self.logo.strip(),
            "format": self.format,
            "dateiname": self.dateiname.strip(),
            "logo_breite": self.breite.strip(),
            "titel": self.titel.strip(),
            "untertitel": self.untertitel.strip(),
            "kopfzeile": kopf.text,
            HEADER_FORMAT: kopf.to_dict(),
            "fusszeile": fuss.text,
            FOOTER_FORMAT: fuss.to_dict(),
            FOOTER_EXPLICIT: True,
            "regeln": [dict(regel) for regel in self.state.regeln],
            ENTRY_RULE_SET: self.ruleSetId,
        }

    @Slot(str)
    def pickVorlage(self, label: str) -> None:  # noqa: N802
        """Vorlage anwenden – per ID (Auswahlliste) oder Name (bis 2.7)."""
        eintrag = self.state.find_vorlage(label)
        if eintrag:
            self.apply_vorlage(eintrag)

    @Slot(str)
    def applyTemplate(self, template_id: str) -> None:  # noqa: N802
        self.pickVorlage(template_id)

    def apply_vorlage(self, eintrag: dict, texts: bool = True, quiet: bool = False) -> None:
        """Vorlage anwenden. ``texts=False`` lässt Kopf- und Fußzeile unverändert (vom Benutzer geändert)."""
        self.vorlage = str(eintrag.get("name", ""))
        # Dieselben Werte übernimmt der Stapel aus einer Vorlage (``overview.template_layout``).
        werte = template_layout(eintrag)
        for key, name in (("logo", "logo"), ("format", "format"), ("dateiname", "dateiname"), ("logo_breite", "breite"), ("titel", "titel"), ("untertitel", "untertitel")):
            if key in werte:
                setattr(self, name, werte[key])
        if "logo" in werte:
            self.refresh_files()
        if texts:
            self.set_header(header_rich_from(eintrag))
            # Vorlage mit eigener Fußzeile: diese (mit Formatierung); alte Vorlage ohne gültigen Wert:
            # Standard. Fehlt die Formatierung (Vorlagen bis 2.1), gilt das Standardformat.
            self.set_footer(footer_rich_from(eintrag))
            # Die Texte stammen jetzt aus der Vorlage, nicht mehr aus einer Kundenakte.
            self.tool.customers.texts_from_template()
        regeln = template_rules(eintrag)
        changed = regeln != self.state.regeln
        self.state.regeln = regeln
        self.reload_regeln()
        # Regelwerk der Vorlage (nur wenn sie eines festlegt; ältere Vorlagen lassen es unverändert)
        missing_rule_set = False
        if isinstance(eintrag.get(ENTRY_RULE_SET), str):
            wanted = eintrag[ENTRY_RULE_SET]
            if wanted and (self.state.rule_sets is None or self.state.rule_sets.get(wanted) is None):
                missing_rule_set, wanted = True, ""
            if wanted != self.ruleSetId:
                self._set_rule_set(wanted, quiet=True)
        if eintrag.get("id"):
            self._mark_template(str(eintrag["id"]))
        self.app.persist()
        if changed:
            self.recheck_excel()  # andere Zyklus-Regeln: Excel neu prüfen (nie eine alte Analyse verwenden)
        if missing_rule_set:
            self.notify("vorlagen_info", "warning", f"Vorlage „{eintrag.get('name', '')}“ geladen. Ihr Regelwerk gibt es nicht mehr – es wird kein Regelwerk verwendet.")
        elif not quiet:
            self.notify("vorlagen_info", "success", f"Vorlage „{eintrag.get('name', '')}“ geladen.", auto_hide=5000)

    @Slot()
    def saveVorlage(self) -> None:  # noqa: N802
        """Darstellung unter dem eingetragenen Namen speichern (gleicher Name: Vorlage aktualisieren)."""
        name = self.vorlage.strip()
        if not name:
            self._set_error("vorlage")
            self._focus("vorlage")
            self.notify("vorlagen_info", "warning", "Bitte zuerst einen Namen für die Vorlage eintragen.")
            return
        self._clear_error("vorlage")
        saved = self.state.save_vorlage(self.current_entry(name))
        if self.state.templates is not None and saved is None:
            self.notify("vorlagen_info", "error", self.state.templates.last_error or "Die Vorlage konnte nicht gespeichert werden.")
            return
        if saved is not None:
            self._mark_template(saved.id)
        self.reload_vorlagen()
        self.app.persist()
        self.tool.templates_changed()
        self.notify("vorlagen_info", "success", f"Die Vorlage „{name}“ wurde gespeichert.", auto_hide=5000)

    @Slot()
    def updateTemplate(self) -> None:  # noqa: N802
        """Geladene Vorlage mit der aktuellen Darstellung aktualisieren (Name, ID und Beschreibung bleiben)."""
        store = self.state.templates
        template = store.get(self.vorlageId) if store is not None else None
        if template is None:
            self.notify("vorlagen_info", "warning", "Es ist keine Vorlage geladen.")
            return
        from tools.contract_overview.templates.models import Template

        entry = {**self.current_entry(template.name), "id": template.id, "beschreibung": template.meta.description}
        saved = store.update(Template.from_entry(entry, template_id=template.id, created_at=template.meta.created_at))
        if saved is None:
            self.notify("vorlagen_info", "error", store.last_error or "Die Vorlage konnte nicht gespeichert werden.")
            return
        self._mark_template(saved.id)
        self.reload_vorlagen()
        self.app.persist()
        self.tool.templates_changed()
        self.notify("vorlagen_info", "success", f"Vorlage „{saved.name}“ aktualisiert.", auto_hide=5000)

    @Slot(str, result=str)
    def templateNameProblem(self, name: str) -> str:  # noqa: N802
        """Prüfung eines neuen Namens: "" = in Ordnung, sonst der Grund."""
        from tools.contract_overview.templates.models import clean_name

        name = clean_name(name)
        if not name:
            return "Bitte einen Namen eintragen."
        if self.state.templates is not None and self.state.templates.name_taken(name):
            return "Eine Vorlage mit diesem Namen gibt es bereits."
        return ""

    @Slot(str, result=bool)
    def saveAsTemplate(self, name: str) -> bool:  # noqa: N802
        """Aktuelle Darstellung als neue Vorlage speichern und laden."""
        problem = self.templateNameProblem(name)
        if problem:
            self.notify("vorlagen_info", "warning", problem)
            return False
        store = self.state.templates
        if store is None:
            self.vorlage = name
            self.saveVorlage()
            return True
        from tools.contract_overview.templates.models import Template

        created = store.update(Template.from_entry(self.current_entry(name)))
        if created is None:
            self.notify("vorlagen_info", "error", store.last_error or "Die Vorlage konnte nicht gespeichert werden.")
            return False
        self._mark_template(created.id)
        self.reload_vorlagen()
        self.app.persist()
        self.tool.templates_changed()
        self.notify("vorlagen_info", "success", f"Neue Vorlage „{created.name}“ gespeichert.", auto_hide=5000)
        return True

    @Slot()
    def discardTemplateChanges(self) -> None:  # noqa: N802
        """Darstellung wieder auf den Stand der geladenen Vorlage setzen."""
        entry = self.template_entry()
        if entry is None:
            return
        self.apply_vorlage(entry, quiet=True)
        self.notify("vorlagen_info", "info", f"Änderungen verworfen – Vorlage „{entry.get('name', '')}“ wieder geladen.", auto_hide=5000)

    @Slot()
    def detachTemplate(self) -> None:  # noqa: N802
        """»Keine Vorlage«: die Darstellung bleibt, die Verknüpfung mit der Vorlage entfällt."""
        self.vorlageId = ""
        self.vorlage = ""
        self.templateLabel = ""
        self.templateModified = False
        self.app.persist()

    @Slot(str)
    def setDefaultTemplate(self, template_id: str) -> None:  # noqa: N802
        """Standardvorlage festlegen ("" = keine). Sie wird für jede neue Übersicht geladen."""
        if template_id and (self.state.templates is None or self.state.templates.get(template_id) is None):
            return
        self.defaultTemplate = template_id
        self.reload_vorlagen()
        self.app.persist()
        self.tool.templates_changed()

    @Slot()
    def deleteVorlage(self) -> None:  # noqa: N802
        """Vorlage mit dem eingetragenen Namen löschen (mit Rückfrage)."""
        name = self.vorlage.strip()
        entry = self.state.find_vorlage(name) if name else None
        if entry is None:
            self.notify("vorlagen_info", "warning", "Bitte zuerst eine gespeicherte Vorlage auswählen.")
            return
        self.tool.delete_template(str(entry.get("id") or name), area="vorlagen_info")

    def template_deleted(self, template_id: str, name: str) -> None:
        """Nach dem Löschen einer Vorlage: Verknüpfungen lösen (die Darstellung bleibt unverändert)."""
        if self.vorlageId == template_id or (not self.vorlageId and self.vorlage == name):
            self.vorlageId = ""
            self.vorlage = ""
            self.templateModified = False
        if self.defaultTemplate == template_id:
            self.defaultTemplate = ""
        self.reload_vorlagen()
        self.app.persist()

    # Regelwerk der Übersicht -------------------------------------------------------------------------------
    def reload_rule_sets(self) -> None:
        store = self.state.rule_sets
        if store is None:
            self.ruleSetChoices = []
            return
        if self.ruleSetId and store.get(self.ruleSetId) is None:
            self.ruleSetId = ""
        self.ruleSetChoices = [{"key": "", "label": "Kein Regelwerk"}] + [
            {"key": rule_set.id, "label": rule_set.name + ("" if rule_set.active else " (inaktiv)")} for rule_set in store.rule_sets()
        ]
        current = store.get(self.ruleSetId)
        self.ruleSetLabel = current.name if current is not None else ""

    def rule_set(self):
        """Regelwerk der Übersicht (``RuleSet``) oder ``None``."""
        store = self.state.rule_sets
        return store.get(self.ruleSetId) if store is not None and self.ruleSetId else None

    def rule_set_dict(self) -> dict | None:
        rule_set = self.rule_set()
        return rule_set.to_dict() if rule_set is not None else None

    @Slot(str)
    def setRuleSet(self, rule_set_id: str) -> None:  # noqa: N802
        self._set_rule_set(rule_set_id)

    def _set_rule_set(self, rule_set_id: str, quiet: bool = False) -> None:
        store = self.state.rule_sets
        if rule_set_id and (store is None or store.get(rule_set_id) is None):
            return
        if rule_set_id == self.ruleSetId:
            return
        self.ruleSetId = rule_set_id
        self.reload_rule_sets()
        self.rule_set_changed()
        if not quiet:
            self.app.persist()
            label = self.ruleSetLabel
            self.set_status(f"Regelwerk: {label}" if label else "Kein Regelwerk", "success")

    def rule_set_changed(self) -> None:
        """Regelwerk gewählt oder geändert: Vorschau, Vergleich, Regelvorschau und Stapel folgen."""
        self.tool.preview_dirty()
        self.tool.refresh_comparison()
        self.tool.rules_changed()
        self.template_state_soon()

    @Slot()
    def resetPdfSettings(self) -> None:  # noqa: N802
        if not self.app.dialogs.confirm("PDF-Einstellungen zurücksetzen?", "Titel, Untertitel, Dateiname, Logo-Breite und Seitenformat erhalten wieder ihre Standardwerte.", "Zurücksetzen"):
            return
        self.titel = DEFAULT_TITEL
        self.untertitel = DEFAULT_UNTERTITEL
        self.dateiname = DEFAULT_DATEINAME
        self.breite = DEFAULT_LOGO_BREITE
        self.format = "hoch"
        self.app.persist()
        self.notify("pdf_settings_info", "success", "Die Standardwerte wurden wiederhergestellt.", auto_hide=5000)

    @Slot(str)
    def setFormat(self, value: str) -> None:  # noqa: N802
        if value in ("hoch", "quer"):
            self.format = value
            self.app.persist()

    # Zyklus-Regeln -------------------------------------------------------------------------------------------
    def reload_regeln(self) -> None:
        self.rules.set_items(
            [{"key": f"{index}:{regel.get('enthaelt', '')}", "index": index, "enthaelt": regel.get("enthaelt", ""), "zyklus": regel.get("zyklus", "")} for index, regel in enumerate(self.state.regeln)]
        )
        self.template_state_soon()

    @Slot(int)
    def editRegel(self, index: int) -> None:  # noqa: N802
        if 0 <= index < len(self.state.regeln):
            regel = self.state.regeln[index]
            self.regelSuch = regel.get("enthaelt", "")
            self.regelZyk = regel.get("zyklus", "")
            self._focus("regelZyk")

    @Slot()
    def addRegel(self) -> None:  # noqa: N802
        nadel = self.regelSuch.strip()
        ziel = self.regelZyk.strip()
        if not nadel or not ziel:
            self._set_error("regelSuch", not nadel)
            self._set_error("regelZyk", not ziel)
            self.notify("regeln_info", "warning", "Bitte Begriff und Zyklus eintragen, zum Beispiel Hott-KI und jährlich.")
            return
        self._set_error("regelSuch", False)
        self._set_error("regelZyk", False)
        self.state.add_regel(nadel, ziel)
        self.regelSuch = ""
        self.regelZyk = ""
        self.reload_regeln()
        self.app.persist()
        self.recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{nadel}“ gespeichert.", auto_hide=5000)

    @Slot(int)
    def deleteRegel(self, index: int) -> None:  # noqa: N802
        if not (0 <= index < len(self.state.regeln)):
            return
        name = self.state.regeln[index]["enthaelt"]
        if not self.app.dialogs.confirm("Regel löschen?", f"Die Zyklus-Regel „{name}“ wird entfernt.", "Löschen"):
            return
        self.state.delete_regel(index)
        self.reload_regeln()
        self.app.persist()
        self.recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{name}“ gelöscht.", auto_hide=5000)

    def recheck_excel(self) -> None:
        excel = self.excel.strip()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)

    # PDF erstellen -----------------------------------------------------------------------------------------------
    def _require(self, ok: bool, message: str, field: str = "", actions=(), page: str = "create") -> bool:
        if ok:
            return True
        if self.app.currentPage != page:
            self.app.navigate(page)
        if field:
            self._set_error(field)
            self._focus(field)
        self.notify("pdf_info" if page == "create" else "pdf_settings_info", "error", message, actions=actions)
        return False

    @Slot()
    def startPdf(self) -> None:  # noqa: N802
        if self.busy:
            return
        excel = self.excel.strip()
        logo = self.logo.strip()
        kd = self.kd.strip()
        if not self._require(bool(excel) and Path(excel).is_file(), "Bitte zuerst die Excel-Liste wählen.", actions=(("Excel wählen", self.pick_excel),)):
            return
        self.kdRequired = True
        if not self._require(bool(kd), "Bitte die Kundennummer eintragen.", "kd"):
            return
        if not self._require(bool(logo) and Path(logo).is_file(), "Bitte eine Logo-Datei wählen.", actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo))):
            return
        breite = parse_width(self.breite)
        if breite is None:
            self.app.navigate("layout")
            self.app.timers.later("require:breite", 50, lambda: self._require(False, "Die Logo-Breite muss eine Zahl sein (z. B. 62).", "breite", page="layout"))
            return
        empfaenger = self.mail.strip()
        if not empfaenger and len(self._excel_mails) > 1:
            self._focus("mail")
            self.notify("pdf_info", "warning", "In der Excel stehen mehrere Rechnungsempfänger. Bitte einen auswählen oder ins Feld eintragen.")
            return
        auftrag = self.pdf_fields(kd, empfaenger, breite)
        auftrag["zielordner"] = Path(self.target_folder())
        # Der Vertragsstand gehört zur Kundenakte, die beim Start aktiv war.
        customer = self.tool.customers.active_customer()
        customer_id, customer_label = (customer.id, customer.label) if customer is not None else (None, "")
        regeln = auftrag.get("regeln")
        regelwerk = auftrag.get("regelwerk")
        self.app.persist()
        self.busy = True
        self.hide_notice("pdf_info")
        self.set_status("PDF wird erstellt …", "busy")
        worker = self.app.worker

        def work():
            from engine import PdfAuftrag, erstelle_pdf

            job = PdfAuftrag(**auftrag, pdf_oeffnen=False, status=lambda msg: worker.post(self.set_status, msg, "busy"))
            # Gemeinsame Sperre mit der Vorschau: die PDF-Erzeugung läuft nie parallel.
            with RENDER_LOCK:
                path = erstelle_pdf(job)
            return path, records_from(job.vertraege, regeln, regelwerk)

        def done(result) -> None:
            path, records = result
            self._done(path)
            self.tool.history_after_export(customer_id, customer_label, records, str(auftrag["excel"]), Path(path))

        worker.run(work, done, self._fail)

    def start_pdf(self) -> None:
        self.startPdf()

    def pdf_fields(self, kd: str, empfaenger: str, breite: float) -> dict:
        """Auftrag für ``engine.erstelle_pdf`` aus dem Formular – gemeinsam für PDF und Vorschau."""
        return pdf_fields(
            excel=self.excel.strip(),
            logo=self.logo.strip(),
            kd=kd,
            firma=self.firma,
            mail=empfaenger,
            dateiname=self.dateiname,
            seitenformat=self.format,
            breite=breite,
            titel=self.titel,
            untertitel=self.untertitel,
            header=self.header_rich(),
            footer=self.footer_rich(),
            regeln=self.state.regeln,
            regelwerk=self.rule_set_dict(),
        )

    def _done(self, path: Path) -> None:
        self.busy = False
        self.pdf_runs += 1
        path = Path(path)
        self._remember_pdf(path)
        self.tool.customers.after_pdf(path)
        self.app.persist()
        self.notify(
            "pdf_info",
            "success",
            path.name,
            title="PDF wurde erfolgreich erstellt.",
            actions=(
                ("Öffnen", lambda: self.app.open_file(path, "pdf_info")),
                ("Ordner öffnen", lambda: self.app.open_folder_of(path, "pdf_info")),
                ("Pfad kopieren", lambda: self.app.copy_path(path)),
                ("Neue Übersicht", self.new_overview),
            ),
            status=False,
        )
        self.set_status(f"PDF gespeichert: {path}", "success")
        if self.pdfOeffnen:
            self.app.open_file(path, "pdf_info")

    @Slot()
    def newOverview(self) -> None:  # noqa: N802
        self.new_overview()

    def new_overview(self) -> None:
        """Kundenspezifische Arbeitsdaten zurücksetzen (Firma, Kundennummer, Empfänger, Excel).

        Logo, Zielordner, Darstellung, Kopf-/Fußzeile und Regeln bleiben – gibt es eine
        Standardvorlage, wird sie geladen (rückgängig machbar). Eine Kundenakte mit »Vorlage
        automatisch verwenden« lädt danach ihre eigene Vorlage (sie hat Vorrang).
        """
        previous = (self.firma, self.kd, self.mail, self.excel)
        layout = self._layout_snapshot()
        customer = self.tool.customers.leave()
        self._undo_overview_customer = customer
        self._reset_work(("", "", "", ""))
        default = self._apply_default_template()
        self._undo_overview = previous if any(value.strip() for value in previous) or customer or default else None
        self._undo_layout = layout if default else None
        self.hide_notice("pdf_info")
        actions = (("Rückgängig", self._undo_new_overview),) if self._undo_overview else ()
        text = "Bereit für eine neue Übersicht: Kundendaten und Excel-Datei wurden zurückgesetzt."
        if default:
            text += f" Standardvorlage „{default}“ geladen."
        self.notify("kunde_info", "info", text, actions=actions, auto_hide=10000)
        self._focus("firma")

    def _apply_default_template(self) -> str:
        """Standardvorlage laden, falls es eine gibt und sie nicht schon unverändert geladen ist."""
        if not self.defaultTemplate:
            return ""
        entry = self.state.find_vorlage(self.defaultTemplate)
        if entry is None or (self.vorlageId == self.defaultTemplate and not self.templateModified):
            return ""
        self.apply_vorlage(entry, quiet=True)
        return str(entry.get("name", ""))

    def _layout_snapshot(self) -> dict:
        return {
            "values": {name: getattr(self, name) for name in ("logo", "format", "dateiname", "breite", "titel", "untertitel", "vorlage", "vorlageId", "ruleSetId")},
            "header": self.header_rich(),
            "footer": self.footer_rich(),
            "regeln": [dict(regel) for regel in self.state.regeln],
            "baseline": self._template_baseline,
        }

    def _restore_layout(self, snapshot: dict) -> None:
        values = snapshot["values"]
        for name in ("logo", "format", "dateiname", "breite", "titel", "untertitel", "vorlage", "vorlageId"):
            setattr(self, name, values[name])
        self.refresh_files()
        self.set_header(snapshot["header"])
        self.set_footer(snapshot["footer"])
        self.state.regeln = snapshot["regeln"]
        self.reload_regeln()
        if values["ruleSetId"] != self.ruleSetId:
            self._set_rule_set(values["ruleSetId"], quiet=True)
        self._template_baseline = snapshot["baseline"]
        self._refresh_template_label()
        self.refresh_template_state()

    def _reset_work(self, values: tuple[str, str, str, str]) -> None:
        firma, kd, mail, excel = values
        self.kdRequired = False
        self._set_error("kd", False)
        self._set_error("firma", False)
        self.firma = firma
        self.kd = kd
        self.mail = mail
        self.excel = excel
        self.refresh_files()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)
        else:
            self._analysis = None
            self._analysis_path = ""
            self._set_mails([])
            self.notify("info_excel", "neutral", EXCEL_EMPTY, status=False)
        self.update_readiness()
        self.tool.refresh_comparison()
        self.app.persist()

    def _undo_new_overview(self) -> None:
        if self._undo_overview is not None:
            values, self._undo_overview = self._undo_overview, None
            customer, self._undo_overview_customer = self._undo_overview_customer, None
            layout, self._undo_layout = self._undo_layout, None
            if layout is not None:
                self._restore_layout(layout)
            self.tool.customers.return_to(customer)
            self._reset_work(values)
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten und Excel-Datei wiederhergestellt.", "success")

    def _fail(self, exc: BaseException, tb: str) -> None:
        self.busy = False
        self.app.write_error_log(tb)
        self.notify("pdf_info", "error", str(exc) or exc.__class__.__name__, title="PDF konnte nicht erstellt werden")

    # Für QML -----------------------------------------------------------------------------------------------------------
    def _texts(self) -> dict:
        return {"placeholders": PLACEHOLDERS, "filenamePlaceholders": FILENAME_PLACEHOLDERS, "excelEmpty": EXCEL_EMPTY}

    _constant = Signal()

    def _header_obj(self) -> QObject:
        return self.header

    def _footer_obj(self) -> QObject:
        return self.footer

    def _templates_obj(self) -> QObject:
        return self.templates

    def _blocks_obj(self) -> QObject:
        return self.textBlocks

    def _rules_obj(self) -> QObject:
        return self.rules

    def _recent_obj(self) -> QObject:
        return self.recentPdfs

    def _views(self) -> list[dict]:
        return self.tool.views()

    texts = Property("QVariantMap", _texts, notify=_constant)
    views = Property(list, _views, notify=_constant)
    headerDocument = Property(QObject, _header_obj, notify=_constant)
    footerDocument = Property(QObject, _footer_obj, notify=_constant)
    templateModel = Property(QObject, _templates_obj, notify=_constant)
    textBlockModel = Property(QObject, _blocks_obj, notify=_constant)
    ruleModel = Property(QObject, _rules_obj, notify=_constant)
    recentModel = Property(QObject, _recent_obj, notify=_constant)

    @Slot(str, result=bool)
    def validWidth(self, value: str) -> bool:  # noqa: N802
        return valid_width(value)
