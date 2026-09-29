"""Werkzeug »Vertragsübersichten«: Excel-Liste prüfen, Kundendaten, Vorlagen,
Kopf- und Fußzeile, Zyklus-Regeln und PDF-Erstellung.

Kundenakten (Wiedererkennung, Übernahme, Verwaltung) stehen in ``customer_flow``,
die Live-Vorschau in ``preview``.

Die Logik ist ein Baustein (Mixin) des Hauptfensters: Formularwerte und Methoden
bleiben unter ``app.…`` erreichbar. Vom Hauptfenster nutzt das Werkzeug nur die
gemeinsame Infrastruktur (``ui``, ``nav``, ``worker``, ``ctx``, ``notify``,
``set_status``, ``persist``, Dateidialog-Ordner, Öffnen und Kopieren von Pfaden) –
auf andere Werkzeuge greift es nicht zu.
"""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from appstate import (
    DEFAULT_DATEINAME,
    DEFAULT_LOGO,
    DEFAULT_LOGO_BREITE,
    DEFAULT_TITEL,
    DEFAULT_UNTERTITEL,
    FOOTER_EXPLICIT,
    FOOTER_FORMAT,
    HEADER_FORMAT,
    ICON_FILE,
    baustein_rich,
    default_footer_rich,
    desktop_dir,
    footer_rich_from,
    header_rich_from,
)
from richtext import RichText
from ui import dialogs, windows

from . import page_layout
from .customer_flow import CustomerFlow
from .preview import RENDER_LOCK, PreviewFlow

# Tastenhinweis in der Statuszeile, solange eine Seite des Werkzeugs sichtbar ist
HINT = "Strg+Enter  PDF erstellen   ·   Strg+O  Excel öffnen   ·   Strg+F  Kunde suchen"


class ContractOverviewTool(CustomerFlow, PreviewFlow):
    """Vertragsübersichten als Werkzeug von PDF Tool."""

    # Einrichtung --------------------------------------------------------------------
    def _init_contract_overview(self, cfg: dict) -> None:
        """Formularwerte (Namen und Bedeutung wie in 2.0.5) und Zustand des Werkzeugs."""
        self.var_firma = tk.StringVar(self, cfg.get("firmenname", ""))
        self.var_kd = tk.StringVar(self, cfg.get("kundennummer", ""))
        self.var_mail = tk.StringVar(self, cfg.get("rechnungsempfaenger", ""))
        self.var_excel = tk.StringVar(self, cfg.get("excel", ""))
        self.var_logo = tk.StringVar(self, cfg.get("logo") or (str(DEFAULT_LOGO) if DEFAULT_LOGO.is_file() else ""))
        self.var_ziel = tk.StringVar(self, cfg.get("zielordner") or str(desktop_dir()))
        self.var_name = tk.StringVar(self, cfg.get("dateiname", DEFAULT_DATEINAME))
        self.var_format = tk.StringVar(self, cfg.get("format", "hoch") if cfg.get("format") in ("hoch", "quer") else "hoch")
        self.var_breite = tk.StringVar(self, str(cfg.get("logo_breite", DEFAULT_LOGO_BREITE)))
        self.var_titel = tk.StringVar(self, cfg.get("titel", DEFAULT_TITEL))
        self.var_untertitel = tk.StringVar(self, cfg.get("untertitel", DEFAULT_UNTERTITEL))
        self.var_open = tk.BooleanVar(self, bool(cfg.get("pdf_oeffnen", True)))
        self.var_baustein = tk.StringVar(self, cfg.get("baustein_name", ""))
        self.var_vorlage = tk.StringVar(self, "")
        self.var_regel_such = tk.StringVar(self, "")
        self.var_regel_zyk = tk.StringVar(self, "")
        # Kopf- und Fußzeile samt Formatierung. Ohne bewusst gespeicherte Fußzeile gilt die
        # Standard-Fußzeile (auch nach einem Update), ohne gespeicherte Formatierung das Standardformat.
        self._fuss_start: RichText = footer_rich_from(cfg)
        self._kopf_start: RichText = header_rich_from(cfg)
        self._excel_mails: list[str] = []
        # Ergebnis der Excel-Prüfung für die gewählte Datei (``None``: Prüfung läuft bzw. keine Datei)
        self._analysis: dict | None = None
        self._analysis_path = ""
        self._undo_overview: tuple[str, str, str, str] | None = None
        self._undo_overview_customer: dict | None = None
        self._drag_saved: tuple | None = None
        self._ready_job = None
        self._pdf_by_label: dict[str, str] = {}
        self._undo_customer: tuple[tuple[str, str, str], dict | None] | None = None
        self.busy = False
        self.kd_required = False
        self._initial_check = False
        self._init_customers(cfg)
        self._init_preview()

    def _start_contract_overview(self) -> None:
        """Nach dem Aufbau der Seiten: automatisches Speichern und Bereitschaft verbinden."""
        self._start_customers()
        # Eingaben automatisch speichern – verzögert, nicht bei jedem Tastendruck.
        for var in (
            self.var_firma, self.var_kd, self.var_mail, self.var_excel, self.var_logo, self.var_ziel,
            self.var_name, self.var_format, self.var_breite, self.var_titel, self.var_untertitel,
            self.var_open, self.var_baustein,
        ):
            var.trace_add("write", lambda *_a: self.schedule_save())
        # »Bereit zum Erstellen« (und die Zeile der aktiven Kundenakte) folgen jeder Änderung.
        for var in (self.var_firma, self.var_kd, self.var_mail, self.var_excel, self.var_logo, self.var_ziel, self.var_breite, self.var_vorlage):
            var.trace_add("write", lambda *_a: self.update_readiness())
        self.update_readiness(now=True)
        # Eine gespeicherte Excel-Liste wird im Hintergrund geprüft; der Hinweis
        # »Excel wird geprüft …« gehört damit schon zum ersten sichtbaren Bild.
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self._initial_check = True
            self.inspect_excel(excel)

    def contract_config(self) -> dict:
        """Gespeicherte Werte des Werkzeugs (Schlüssel wie bisher – alte Einstellungen bleiben gültig)."""
        fuss = self.footer_rich()
        kopf = self.header_rich()
        return {
            "firmenname": self.var_firma.get().strip(),
            "kundennummer": self.var_kd.get().strip(),
            "rechnungsempfaenger": self.var_mail.get().strip(),
            "excel": self.var_excel.get().strip(),
            "logo": self.var_logo.get().strip(),
            "zielordner": self.var_ziel.get().strip(),
            "dateiname": self.var_name.get().strip(),
            "format": self.var_format.get(),
            "logo_breite": self.var_breite.get().strip(),
            "titel": self.var_titel.get().strip(),
            "untertitel": self.var_untertitel.get().strip(),
            "fusszeile": fuss.text,
            FOOTER_FORMAT: fuss.to_dict(),
            FOOTER_EXPLICIT: True,
            "kopfzeile": kopf.text,
            HEADER_FORMAT: kopf.to_dict(),
            "baustein_name": self.var_baustein.get().strip(),
            "bausteine": self.state.bausteine,
            "pdfs": self.state.pdfs[:8],
            "regeln": self.state.regeln,
            "vorlagen": self.state.vorlagen,
            "staende": self.state.staende,
            "pdf_oeffnen": bool(self.var_open.get()),
            **self.customer_config(),
        }

    def _contract_autosave(self) -> None:
        self._fuss_start = self.footer_rich()
        self._kopf_start = self.header_rich()
        self.refresh_customer_line()

    def _contract_close(self) -> None:
        # Kundenakten werden nie automatisch angelegt – nur eine offene Eingabe in »Kunden« sichern.
        if self.customer_page is not None:
            self.customer_page.flush()
        self._close_preview()

    def _contract_changed(self) -> None:
        """Eine Eingabe hat sich geändert (über das verzögerte Speichern gemeldet)."""
        self.mark_preview_dirty()

    def contract_accepts(self, files: list[str]) -> bool:
        return bool(_excel_in(files))

    def refresh_files(self) -> None:
        from ui.components import path_caption

        rows = (
            ("row_excel", self.var_excel.get().strip(), "Keine Datei gewählt"),
            ("row_logo", self.var_logo.get().strip(), "Kein Logo gewählt"),
            ("row_ziel", self.var_ziel.get().strip(), "Keine Auswahl"),
        )
        for attr, value, empty in rows:
            row = getattr(self.ui, attr, None)
            if row is None:
                continue
            if attr == "row_ziel" and value:
                text, full = (Path(value).name or value), value
            else:
                text, full = path_caption(value, empty)
            row.set_value(text, full)

    def pick_excel(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Excel-Liste wählen",
            initialdir=self._initial_dir("excel", self.var_excel.get().strip()),
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Alle Dateien", "*.*")],
        )
        if path:
            self.use_excel(path)

    def use_excel(self, path: str) -> None:
        self._remember_dir("excel", path)
        self.var_excel.set(path)
        self.refresh_files()
        self.inspect_excel(path)

    def pick_logo(self) -> None:
        current = self.var_logo.get().strip()
        if current and Path(current).resolve().parent == DEFAULT_LOGO.resolve().parent:
            current = ""  # Standardlogo: lieber den zuletzt benutzten eigenen Ordner zeigen
        path = filedialog.askopenfilename(
            parent=self,
            title="Logo wählen",
            initialdir=self._initial_dir("logo", current),
            filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")],
        )
        if path:
            self._remember_dir("logo", path)
            self.var_logo.set(path)
            self.refresh_files()
            self.set_status(f"Logo gewählt: {Path(path).name}", "success")

    def pick_ziel(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Zielordner für die PDF", initialdir=self._initial_dir("ziel", self.var_ziel.get().strip()))
        if path:
            self.var_ziel.set(path)
            self.refresh_files()
            self.set_status(f"Zielordner: {path}", "success")

    def target_folder(self) -> str:
        """Zielordner der PDF (ohne Auswahl: der Desktop)."""
        return self.var_ziel.get().strip() or str(desktop_dir())

    def use_default_logo(self) -> None:
        if DEFAULT_LOGO.is_file():
            self.var_logo.set(str(DEFAULT_LOGO))
            self.refresh_files()
            self.notify("dateien_info", "success", "Das Standardlogo wird verwendet.", auto_hide=4000)
        else:
            self.notify("dateien_info", "warning", "Es ist kein Standardlogo installiert.")

    def open_folder(self) -> None:
        ziel = self.var_ziel.get().strip()
        if not ziel or not Path(ziel).is_dir():
            self.notify("pdf_info", "warning", "Der Zielordner ist nicht vorhanden.", actions=(("Ordner wählen", self.pick_ziel),))
            return
        try:
            windows.open_path(ziel)
        except OSError as exc:
            self.notify("pdf_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    def _contract_drag_enter(self, accepted: bool) -> None:
        """Datei wird über das Fenster gezogen: Excel-Bereich hervorheben."""
        if not accepted:
            return
        card = getattr(self.ui, "dateien_card", None)
        bar = getattr(self.ui, "info_excel", None)
        if self._drag_saved is None and bar is not None:
            self._drag_saved = (bar.severity, bar.message, bar.title)
        if card is not None:
            card.set_fill("card", stroke="accent")
        if bar is not None:
            bar.show("info", "Loslassen, um die Excel-Datei zu übernehmen und zu prüfen.", animate=False)
        if self.nav.current != "create":
            self.set_status("Excel-Datei loslassen – sie wird in »Vertragsübersichten« geprüft.", "info")

    def _contract_drag_leave(self) -> None:
        card = getattr(self.ui, "dateien_card", None)
        if card is not None:
            card.set_fill("card", stroke="card_stroke")
        saved, self._drag_saved = self._drag_saved, None
        bar = getattr(self.ui, "info_excel", None)
        if saved is not None and bar is not None and bar.message.startswith("Loslassen"):
            severity, message, title = saved
            bar.show(severity, message, title, animate=False)

    def _contract_drop(self, dateien: list[str]) -> None:
        self._drag_leave()
        excel = next(iter(_excel_in(dateien)), "")
        if not excel:
            self.notify("info_excel", "warning", "Bitte eine Excel-Datei (.xlsx oder .xls) in das Fenster ziehen.")
            return
        if self.nav.current != "create":
            self.nav.navigate("create")
        self.use_excel(excel)

    def inspect_excel(self, path: str) -> None:
        self._analysis = None
        self._analysis_path = path
        self.notify("info_excel", "info", "Excel wird geprüft …", status=False)
        self.set_status("Excel wird geprüft …", "busy")
        self.update_readiness()
        self.mark_preview_dirty()
        regeln = [dict(r) for r in self.state.regeln]

        def work() -> dict:
            from engine import pruefe_excel

            return pruefe_excel(Path(path), regeln)

        def failed(exc, _tb) -> None:
            self._show_check(path, {"ok": False, "text": str(exc), "kunden": [], "mails": [], "firmen": [], "zeilen": []})

        self.worker.run(work, lambda result: self._show_check(path, result), failed)

    def _show_check(self, path: str, result: dict) -> None:
        if self.var_excel.get().strip() != path:
            return
        # Das Ergebnis der Prüfung beim Start erscheint ohne Ein-/Ausklapp-Animation.
        animate = not self._initial_check
        self._initial_check = False
        self._analysis = result
        self._analysis_path = path
        text = str(result.get("text", ""))
        if not result.get("ok"):
            self.notify("info_excel", "error", text or "Die Datei konnte nicht gelesen werden.", title="Excel-Prüfung fehlgeschlagen", animate=animate)
            self._set_mails([], animate=animate)
            self._show_facts([], animate)
            self._recognize_customer(path, result, animate)
            self.update_readiness()
            self.mark_preview_dirty()
            return
        mails = [str(mail) for mail in result.get("mails") or []]
        aktiv = int(result.get("aktiv", 0) or 0)
        inaktiv = int(result.get("inaktiv", 0) or 0)
        fehlend = [str(name) for name in result.get("fehlend") or []]
        vertraege = "1 aktiver Vertrag" if aktiv == 1 else f"{aktiv} aktive Verträge"
        if inaktiv:
            vertraege += f" · {inaktiv} inaktiv ausgeblendet"
        if fehlend:
            spalten = ", ".join(f"»{name}«" for name in fehlend)
            self.notify("info_excel", "error", f"Für die PDF fehlt {'die Spalte' if len(fehlend) == 1 else 'die Spalten'} {spalten}.", title="Spalten fehlen", status=False, animate=animate)
        elif aktiv == 0:
            self.notify("info_excel", "warning", "In der Datei steht kein aktiver Vertrag." + (f" {inaktiv} inaktive wurden ausgeblendet." if inaktiv else ""), title="Keine aktiven Verträge", status=False, animate=animate)
        else:
            self.notify("info_excel", "success", vertraege, title="Excel geprüft", status=False, animate=animate)
        self.set_status(f"Excel geprüft: {text}", "success" if aktiv and not fehlend else "warning")
        self._show_facts(self._facts_for(result), animate)
        self._set_mails(mails, animate=animate)
        # Bekannte Kunden über die Rechnungsempfänger erkennen – vor dem Füllen aus der Datei,
        # damit »automatisch übernehmen« den unveränderten Stand des Formulars sieht.
        self._recognize_customer(path, result, animate)
        # Nur Werte übernehmen, die tatsächlich in der Datei stehen – nie aus der E-Mail-Adresse raten.
        if not self.var_kd.get().strip() and len(result.get("kunden") or []) == 1:
            self.var_kd.set(result["kunden"][0])
        if not self.var_firma.get().strip() and len(result.get("firmen") or []) == 1:
            self.var_firma.set(result["firmen"][0])
        self.update_readiness()
        self.mark_preview_dirty()

    @staticmethod
    def _facts_for(result: dict) -> list[tuple[str, str, str]]:
        """Übersicht der Excel-Prüfung: nur Angaben, die tatsächlich in der Datei stehen."""
        facts: list[tuple[str, str, str]] = []
        aktiv = int(result.get("aktiv", 0) or 0)
        inaktiv = int(result.get("inaktiv", 0) or 0)
        facts.append(("Aktive Verträge", str(aktiv), "" if aktiv else "caution"))
        facts.append(("Ausgeblendet (inaktiv)", str(inaktiv), "muted"))
        mails = [str(mail) for mail in result.get("mails") or []]
        if len(mails) == 1:
            facts.append(("Rechnungsempfänger", mails[0], ""))
        elif len(mails) > 1:
            facts.append(("Rechnungsempfänger", f"{len(mails)} verschiedene – bitte bei den Kundendaten auswählen: " + ", ".join(mails), "caution"))
        else:
            facts.append(("Rechnungsempfänger", "keine Angabe in der Datei", "muted"))
        kunden = [str(kd) for kd in result.get("kunden") or []]
        if len(kunden) == 1:
            facts.append(("Kundennummer", f"{kunden[0]} (aus der Datei)", ""))
        elif len(kunden) > 1:
            facts.append(("Kundennummer", f"{len(kunden)} verschiedene in der Datei: " + ", ".join(kunden), "caution"))
        firmen = [str(firma) for firma in result.get("firmen") or []]
        if len(firmen) == 1:
            facts.append(("Firmenname", f"{firmen[0]} (aus der Datei)", ""))
        elif len(firmen) > 1:
            facts.append(("Firmenname", f"{len(firmen)} verschiedene in der Datei: " + ", ".join(firmen), "caution"))
        fett = int(result.get("fett", 0) or 0)
        if fett:
            facts.append(("Fettschrift", f"{fett} {'Zelle wird' if fett == 1 else 'Zellen werden'} fett in die PDF übernommen", "muted"))
        fehlend = [str(name) for name in result.get("fehlend") or []]
        if fehlend:
            facts.append(("Fehlende Spalten", ", ".join(fehlend), "critical"))
        for hinweis in result.get("hinweise") or []:
            facts.append(("Hinweis", str(hinweis), "muted"))
        return facts

    def _show_facts(self, facts: list[tuple[str, str, str]], animate: bool = True) -> None:
        details = getattr(self.ui, "excel_details", None)
        facts_list = getattr(self.ui, "excel_facts", None)
        if details is None or facts_list is None:
            return
        facts_list.set(facts)
        if facts:
            details.expand(animate=animate)
        else:
            details.collapse(animate=animate)

    def _set_mails(self, mails: list[str], animate: bool = True) -> None:
        self._excel_mails = mails
        combo = getattr(self.ui, "mail_combo", None)
        area = getattr(self.ui, "mail_area", None)
        if combo is None or area is None:
            return
        if len(mails) > 1:
            combo.set_values(mails, keep=True)
            current = self.var_mail.get().strip()
            if current in mails:
                combo.set(current)
            area.expand(animate=animate)
        else:
            combo.set_values([], keep=False)
            area.collapse(animate=animate)

    def on_mail_pick(self, mail: str) -> None:
        """Empfänger aus der Excel wählen: übernimmt die Adresse in das Feld Rechnungsempfänger."""
        if mail:
            self.var_mail.set(mail)
            self.set_status(f"Rechnungsempfänger: {mail}", "success")

    def readiness(self) -> list[tuple[str, str]]:
        """Offene Punkte vor dem Erstellen als (Bereich, Text); leer = bereit.

        Bereich ``busy`` bedeutet: Die Excel-Prüfung läuft noch.
        """
        issues: list[tuple[str, str]] = []
        excel = self.var_excel.get().strip()
        if not excel:
            issues.append(("excel", "Excel-Datei fehlt"))
        elif not Path(excel).is_file():
            issues.append(("excel", "Excel-Datei nicht gefunden"))
        elif self._analysis_path != excel or self._analysis is None:
            issues.append(("busy", "Excel wird geprüft …"))
        elif not self._analysis.get("ok"):
            issues.append(("excel", "Excel-Datei konnte nicht gelesen werden"))
        elif self._analysis.get("fehlend"):
            fehlend = list(self._analysis.get("fehlend") or [])
            issues.append(("excel", f"Spalte »{fehlend[0]}« fehlt in der Excel" if len(fehlend) == 1 else f"{len(fehlend)} Spalten fehlen in der Excel"))
        elif not int(self._analysis.get("aktiv", 0) or 0):
            issues.append(("excel", "Keine aktiven Verträge in der Excel"))
        if not self.var_kd.get().strip():
            issues.append(("kd", "Kundennummer fehlt"))
        if len(self._excel_mails) > 1 and not self.var_mail.get().strip():
            issues.append(("mail", "Bitte Rechnungsempfänger auswählen"))
        logo = self.var_logo.get().strip()
        if not logo:
            issues.append(("logo", "Logo fehlt"))
        elif not Path(logo).is_file():
            issues.append(("logo", "Logo-Datei nicht gefunden"))
        if not _valid_width(self.var_breite.get()):
            issues.append(("breite", "Logo-Breite ungültig"))
        if not _target_reachable(self.target_folder()):
            issues.append(("ziel", "Zielordner nicht erreichbar"))
        return issues

    def update_readiness(self, now: bool = False) -> None:
        """Anzeige »Bereit zum Erstellen« aktualisieren – gesammelt im Leerlauf."""
        if now:
            self._run_readiness()
        elif self._ready_job is None:
            try:
                self._ready_job = self.after_idle(self._run_readiness)
            except tk.TclError:
                self._ready_job = None

    def _run_readiness(self) -> None:
        self._ready_job = None
        self.refresh_customer_line()
        line = getattr(self.ui, "ready", None)
        if line is None:
            return
        issues = self.readiness()
        if not issues:
            line.set("success", "Bereit zum Erstellen")
        elif issues[0][0] == "busy" and len(issues) == 1:
            line.set("busy", issues[0][1])
        else:
            texts = [text for area, text in issues if area != "busy"]
            more = len(texts) - 2
            label = " · ".join(texts[:2]) + (f" · {more} weitere" if more > 0 else "")
            kind = "critical" if any(area == "excel" for area, _t in issues) and self.var_excel.get().strip() else "caution"
            line.set(kind, label)

    def fix_readiness(self) -> None:
        """Zum ersten offenen Punkt springen (Klick auf die Bereitschaftsanzeige)."""
        issues = [issue for issue in self.readiness() if issue[0] != "busy"]
        if not issues:
            return
        area, text = issues[0]
        if area == "excel":
            if self.var_excel.get().strip() and Path(self.var_excel.get().strip()).is_file():
                self.notify("pdf_info", "warning", text, actions=(("Andere Excel wählen", self.pick_excel),))
            else:
                self.pick_excel()
        elif area == "kd":
            self.kd_required = True
            field = getattr(self.ui, "field_kd", None)
            if field is not None:
                field.set_error(True)
                field.focus()
        elif area == "mail":
            combo = getattr(self.ui, "mail_combo", None)
            if combo is not None:
                combo.focus_set()
                combo.open_popup()
        elif area == "logo":
            self.notify("pdf_info", "warning", text, actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo)))
        elif area == "breite":
            self.nav.navigate("layout")
            self.after(50, lambda: self._require(False, "Die Logo-Breite muss eine positive Zahl sein (z. B. 62).", getattr(self.ui, "field_breite", None), page="layout"))
        elif area == "ziel":
            self.notify("pdf_info", "warning", text, actions=(("Ordner wählen", self.pick_ziel),))

    def clear_customer(self) -> None:
        """Kundendaten leeren (rückgängig machbar). Eine aktive Kundenakte wird gelöst – nicht gelöscht."""
        previous = (self.var_firma.get(), self.var_kd.get(), self.var_mail.get())
        customer = self._leave_customer()
        self.var_firma.set("")
        self.var_kd.set("")
        self.var_mail.set("")
        if any(value.strip() for value in previous) or customer:
            self._undo_customer = (previous, customer)
            self.notify("kunde_info", "info", "Kundendaten wurden geleert.", actions=(("Rückgängig", self._undo_clear),), auto_hide=8000)

    def _undo_clear(self) -> None:
        if self._undo_customer:
            (firma, kd, mail), customer = self._undo_customer
            self.var_firma.set(firma)
            self.var_kd.set(kd)
            self.var_mail.set(mail)
            self._return_to_customer(customer)
            self._undo_customer = None
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten wiederhergestellt.", "success")

    def clear_history(self) -> None:
        """Liste »Zuletzt erstellt« leeren. Kundenakten werden in der Ansicht »Kunden« verwaltet."""
        if not dialogs.confirm(self, "Verlauf löschen?", "Die Liste »Zuletzt erstellt« wird geleert. Erstellte PDF-Dateien und Kundenakten bleiben erhalten.", "Verlauf löschen", icon=ICON_FILE):
            return
        self.state.pdfs = []
        self.reload_pdfs()
        self.persist()
        self.notify("daten_info", "success", "Der Verlauf wurde gelöscht.", auto_hide=5000)

    def reload_pdfs(self) -> None:
        self._pdf_by_label = self.state.existing_pdfs()
        combo = getattr(self.ui, "pdf_combo", None)
        if combo is None:
            return
        labels = list(self._pdf_by_label)
        combo.set_values(labels, keep=False)
        if labels:
            combo.set(labels[0])
        combo.set_placeholder("Noch keine PDF erstellt")

    def _remember_pdf(self, path: Path) -> None:
        self.state.remember_pdf(str(path))
        self.reload_pdfs()

    def open_recent_pdf(self) -> None:
        combo = getattr(self.ui, "pdf_combo", None)
        pfad = self._pdf_by_label.get(combo.get()) if combo is not None else None
        if not pfad or not Path(pfad).is_file():
            self.notify("pdf_info", "warning", "Keine gespeicherte PDF zum Öffnen.")
            return
        self._open_pdf(Path(pfad))

    def _open_pdf(self, path: Path) -> None:
        self.open_file(path, "pdf_info")

    def _open_folder_of(self, path: Path) -> None:
        self.open_folder_of(path, "pdf_info")

    def header_rich(self) -> RichText:
        """Aktuelle Kopfzeile mit Formatierung (Inhalt des Editors; vorher der geladene Wert)."""
        widget = getattr(self.ui, "txt_kopf", None)
        if widget is None:
            return self._kopf_start
        return widget.get_rich()

    def footer_rich(self) -> RichText:
        """Aktuelle Fußzeile mit Formatierung – exakt mit allen Zeilenumbrüchen."""
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is None:
            return self._fuss_start
        return widget.get_rich()

    def header_text(self) -> str:
        return self.header_rich().text

    def footer_text(self) -> str:
        """Aktuelle Fußzeile als reiner Text: immer der Inhalt des Editors, exakt.

        Nur bevor der Editor existiert, gilt der geladene Startwert.
        """
        return self.footer_rich().text

    def _set_rich(self, widget_name: str, start_name: str, rich: RichText) -> None:
        setattr(self, start_name, rich)
        widget = getattr(self.ui, widget_name, None)
        if widget is not None:
            widget.set_rich(rich)
        self.mark_preview_dirty()

    def save_header(self) -> None:
        self._kopf_start = self.header_rich()
        self.persist()
        if not self._kopf_start.is_blank():
            self.notify("kopf_info", "success", "Die Kopfzeile wurde gespeichert.", auto_hide=5000)
        else:
            self.notify("kopf_info", "info", "Die Kopfzeile ist leer und erscheint nicht in der PDF.", auto_hide=6000)

    def save_footer(self) -> None:
        name = self.var_baustein.get().strip()
        rich = self.footer_rich()  # aktueller Inhalt des Editors samt Formatierung
        self._fuss_start = rich
        if name:
            self.state.save_baustein(name, rich.text, rich.to_dict())
        self.persist()
        self.reload_bausteine()
        if name:
            self.notify("fuss_info", "success", f"Die Fußzeile und der Textbaustein „{name}“ wurden gespeichert.", auto_hide=5000)
        else:
            self.notify("fuss_info", "success", "Die Fußzeile wurde gespeichert.", auto_hide=5000)

    def restore_default_footer(self) -> None:
        """Standardtext und Standardformatierung wiederherstellen (rückgängig machbar, daher ohne Rückfrage)."""
        previous = self.footer_rich()
        default = default_footer_rich()
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is not None:
            widget.replace_rich(default)
        self._fuss_start = default
        self.persist()
        actions = ()
        if previous != default:
            actions = (("Rückgängig", lambda: self._undo_footer(previous)),)
        self.notify("fuss_info", "success", "Standard-Fußzeile wiederhergestellt.", actions=actions, auto_hide=8000)

    def _undo_footer(self, previous: RichText) -> None:
        widget = getattr(self.ui, "txt_fuss", None)
        if widget is not None:
            widget.replace_rich(previous)
        self._fuss_start = previous
        self.persist()
        self.hide_notice("fuss_info")
        self.set_status("Vorherige Fußzeile wiederhergestellt.", "success")

    def reload_bausteine(self) -> None:
        combo = getattr(self.ui, "baustein_combo", None)
        if combo is None:
            return
        labels = [str(eintrag.get("name", "")) for eintrag in self.state.bausteine]
        combo.set_values(labels, keep=False)
        current = self.var_baustein.get().strip()
        combo.set(current if current in labels else None)
        combo.set_placeholder("Textbaustein wählen" if labels else "Noch kein Textbaustein")

    def on_baustein_pick(self, label: str) -> None:
        eintrag = self.state.find_baustein(label)
        if eintrag:
            self._apply_baustein(eintrag)

    def _apply_baustein(self, eintrag: dict) -> None:
        self.var_baustein.set(str(eintrag.get("name", "")))
        # Alte Bausteine (nur Text) erhalten die Standardformatierung.
        self._set_rich("txt_fuss", "_fuss_start", baustein_rich(eintrag))
        self.schedule_save()
        self.set_status(f"Textbaustein „{eintrag.get('name', '')}“ geladen.", "success")

    def delete_baustein(self) -> None:
        name = self.var_baustein.get().strip()
        if not name:
            self.notify("fuss_info", "warning", "Bitte zuerst einen Textbaustein wählen oder seinen Namen eintragen.")
            return
        if self.state.find_baustein(name) is None:
            self.notify("fuss_info", "warning", f"Kein Textbaustein mit dem Namen „{name}“.")
            return
        if not dialogs.confirm(self, "Textbaustein löschen?", f"Der Textbaustein „{name}“ wird dauerhaft entfernt.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_baustein(name)
        self.var_baustein.set("")
        self.persist()
        self.reload_bausteine()
        self.notify("fuss_info", "success", f"Textbaustein „{name}“ gelöscht.", auto_hide=5000)

    def reload_vorlagen(self) -> None:
        combo = getattr(self.ui, "vorlage_combo", None)
        if combo is None:
            return
        labels = [str(eintrag.get("name", "")) for eintrag in self.state.vorlagen]
        combo.set_values(labels, keep=False)
        current = self.var_vorlage.get().strip()
        combo.set(current if current in labels else None)
        combo.set_placeholder("Vorlage wählen" if labels else "Noch keine Vorlage")

    def on_vorlage_pick(self, label: str) -> None:
        eintrag = self.state.find_vorlage(label)
        if eintrag:
            self._apply_vorlage(eintrag)

    def _apply_vorlage(self, eintrag: dict, texts: bool = True, quiet: bool = False) -> None:
        """Vorlage anwenden. ``texts=False`` lässt Kopf- und Fußzeile unverändert (vom Benutzer geändert)."""
        self.var_vorlage.set(str(eintrag.get("name", "")))
        logo = str(eintrag.get("logo") or "").strip()
        if logo and Path(logo).is_file():
            self.var_logo.set(logo)
            self.refresh_files()
        if eintrag.get("format") in ("hoch", "quer"):
            self.var_format.set(str(eintrag.get("format")))
        if eintrag.get("dateiname"):
            self.var_name.set(str(eintrag.get("dateiname")))
        if eintrag.get("logo_breite"):
            self.var_breite.set(str(eintrag.get("logo_breite")))
        if eintrag.get("titel"):
            self.var_titel.set(str(eintrag.get("titel")))
        if eintrag.get("untertitel"):
            self.var_untertitel.set(str(eintrag.get("untertitel")))
        if texts:
            self._set_rich("txt_kopf", "_kopf_start", header_rich_from(eintrag))
            # Vorlage mit eigener Fußzeile: diese (mit Formatierung); alte Vorlage ohne gültigen Wert:
            # Standard. Fehlt die Formatierung (Vorlagen bis 2.1), gilt das Standardformat.
            self._set_rich("txt_fuss", "_fuss_start", footer_rich_from(eintrag))
            # Die Texte stammen jetzt aus der Vorlage, nicht mehr aus einer Kundenakte.
            self._customer_texts = False
            self._base_texts = None
            self._mark_text_baseline()
        from appstate import normalize_regeln

        regeln = normalize_regeln(eintrag.get("regeln") or [])
        changed = regeln != self.state.regeln
        self.state.regeln = regeln
        self.reload_regeln()
        self.persist()
        if changed:
            self._recheck_excel()  # andere Zyklus-Regeln: Excel neu prüfen (nie eine alte Analyse verwenden)
        if not quiet:
            self.notify("vorlagen_info", "success", f"Vorlage „{eintrag.get('name', '')}“ geladen.", auto_hide=5000)

    def save_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        field = getattr(self.ui, "field_vorlage", None)
        if not name:
            if field is not None:
                field.set_error(True)
                field.focus()
            self.notify("vorlagen_info", "warning", "Bitte zuerst einen Namen für die Vorlage eintragen.")
            return
        if field is not None:
            field.set_error(False)
        kopf = self.header_rich()
        fuss = self.footer_rich()
        self.state.save_vorlage(
            {
                "name": name,
                "logo": self.var_logo.get().strip(),
                "format": self.var_format.get(),
                "dateiname": self.var_name.get().strip(),
                "logo_breite": self.var_breite.get().strip(),
                "titel": self.var_titel.get().strip(),
                "untertitel": self.var_untertitel.get().strip(),
                "kopfzeile": kopf.text,
                HEADER_FORMAT: kopf.to_dict(),
                "fusszeile": fuss.text,
                FOOTER_FORMAT: fuss.to_dict(),
                FOOTER_EXPLICIT: True,
                "regeln": [dict(regel) for regel in self.state.regeln],
            }
        )
        self.reload_vorlagen()
        self.persist()
        self.notify("vorlagen_info", "success", f"Die Vorlage „{name}“ wurde gespeichert.", auto_hide=5000)

    def delete_vorlage(self) -> None:
        name = self.var_vorlage.get().strip()
        if not name or self.state.find_vorlage(name) is None:
            self.notify("vorlagen_info", "warning", "Bitte zuerst eine gespeicherte Vorlage auswählen.")
            return
        if not dialogs.confirm(self, "Vorlage löschen?", f"Die Vorlage „{name}“ wird dauerhaft entfernt. Die aktuellen Einstellungen bleiben unverändert.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_vorlage(name)
        self.var_vorlage.set("")
        self.reload_vorlagen()
        self.persist()
        self.notify("vorlagen_info", "success", f"Vorlage „{name}“ gelöscht.", auto_hide=5000)

    def reset_pdf_settings(self) -> None:
        if not dialogs.confirm(self, "PDF-Einstellungen zurücksetzen?", "Titel, Untertitel, Dateiname, Logo-Breite und Seitenformat erhalten wieder ihre Standardwerte.", "Zurücksetzen", icon=ICON_FILE):
            return
        self.var_titel.set(DEFAULT_TITEL)
        self.var_untertitel.set(DEFAULT_UNTERTITEL)
        self.var_name.set(DEFAULT_DATEINAME)
        self.var_breite.set(DEFAULT_LOGO_BREITE)
        self.var_format.set("hoch")
        self.persist()
        self.notify("pdf_settings_info", "success", "Die Standardwerte wurden wiederhergestellt.", auto_hide=5000)

    def reload_regeln(self) -> None:
        page_layout.render_rules(self)

    def edit_regel(self, regel: dict) -> None:
        self.var_regel_such.set(regel.get("enthaelt", ""))
        self.var_regel_zyk.set(regel.get("zyklus", ""))
        field = getattr(self.ui, "field_regel_zyk", None)
        if field is not None:
            field.focus()

    def add_regel(self) -> None:
        nadel = self.var_regel_such.get().strip()
        ziel = self.var_regel_zyk.get().strip()
        such_field = getattr(self.ui, "field_regel_such", None)
        zyk_field = getattr(self.ui, "field_regel_zyk", None)
        if not nadel or not ziel:
            if such_field is not None:
                such_field.set_error(not nadel)
            if zyk_field is not None:
                zyk_field.set_error(not ziel)
            self.notify("regeln_info", "warning", "Bitte Begriff und Zyklus eintragen, zum Beispiel Hott-KI und jährlich.")
            return
        for field in (such_field, zyk_field):
            if field is not None:
                field.set_error(False)
        self.state.add_regel(nadel, ziel)
        self.var_regel_such.set("")
        self.var_regel_zyk.set("")
        self.reload_regeln()
        self.persist()
        self._recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{nadel}“ gespeichert.", auto_hide=5000)

    def delete_regel(self, index: int) -> None:
        if not (0 <= index < len(self.state.regeln)):
            return
        name = self.state.regeln[index]["enthaelt"]
        if not dialogs.confirm(self, "Regel löschen?", f"Die Zyklus-Regel „{name}“ wird entfernt.", "Löschen", icon=ICON_FILE):
            return
        self.state.delete_regel(index)
        self.reload_regeln()
        self.persist()
        self._recheck_excel()
        self.notify("regeln_info", "success", f"Regel „{name}“ gelöscht.", auto_hide=5000)

    def _recheck_excel(self) -> None:
        excel = self.var_excel.get().strip()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)

    def show_contract_help(self) -> None:
        schritte = (
            "Die Excel-Datei wählen (Strg+O) oder in das Fenster ziehen – sie wird sofort geprüft.",
            "Ist der Rechnungsempfänger als Kunde bekannt, bietet PDF Tool die Kundenakte an: »Übernehmen«.",
            "Sonst Firmenname und Kundennummer eintragen oder »Bekannten Kunden auswählen« (Strg+F).",
            "Optional Logo, Zielordner sowie Kopf- und Fußzeile in der Ansicht »Darstellung« setzen; die »Vorschau« zeigt das Ergebnis.",
            "Auf »PDF erstellen« klicken oder Strg+Enter drücken.",
        )
        hinweise = (
            "Kundenakten entstehen nur bewusst: »Als Kundenakte speichern« – auf Wunsch mit »Zuordnung merken« für die E-Mail-Adresse.",
            "Kundenakten verwalten, bearbeiten, zusammenführen oder löschen: Ansicht »Kunden«. Alle Daten bleiben lokal auf diesem PC.",
            "Stehen mehrere Rechnungsempfänger in der Excel, bitte einen auswählen.",
            "Zyklus-Regeln und Vorlagen stehen in der Ansicht »Darstellung«. Hott-KI wird standardmäßig jährlich ausgegeben.",
            "Hotline-Zeilen werden als Supportvertrag ausgegeben. Nur Netto, kein Brutto.",
        )
        self.show_steps("Kurzanleitung – Vertragsübersichten", schritte, hinweise)

    def _require(self, ok: bool, message: str, field=None, actions=(), page: str = "create") -> bool:
        if ok:
            return True
        if self.nav.current != page:
            self.nav.navigate(page)
        if field is not None:
            try:
                field.set_error(True)
                field.focus()
            except (tk.TclError, AttributeError):
                pass
        self.notify("pdf_info" if page == "create" else "pdf_settings_info", "error", message, actions=actions)
        return False

    def start_pdf(self) -> None:
        if self.busy:
            return
        excel = self.var_excel.get().strip()
        logo = self.var_logo.get().strip()
        kd = self.var_kd.get().strip()
        if not self._require(bool(excel) and Path(excel).is_file(), "Bitte zuerst die Excel-Liste wählen.", actions=(("Excel wählen", self.pick_excel),)):
            return
        self.kd_required = True
        if not self._require(bool(kd), "Bitte die Kundennummer eintragen.", getattr(self.ui, "field_kd", None)):
            return
        if not self._require(bool(logo) and Path(logo).is_file(), "Bitte eine Logo-Datei wählen.", actions=(("Logo wählen", self.pick_logo), ("Standardlogo", self.use_default_logo))):
            return
        try:
            breite = float(self.var_breite.get().replace(",", "."))
            if breite <= 0:
                raise ValueError
        except ValueError:
            self.nav.navigate("layout")
            self.after(50, lambda: self._require(False, "Die Logo-Breite muss eine Zahl sein (z. B. 62).", getattr(self.ui, "field_breite", None), page="layout"))
            return
        empfaenger = self.var_mail.get().strip()
        if not empfaenger and len(self._excel_mails) > 1:
            combo = getattr(self.ui, "mail_combo", None)
            wahl = combo.get().strip() if combo is not None else ""
            if wahl not in self._excel_mails:
                if combo is not None:
                    combo.focus_set()
                self.notify("pdf_info", "warning", "In der Excel stehen mehrere Rechnungsempfänger. Bitte einen auswählen oder ins Feld eintragen.")
                return
            empfaenger = wahl
        auftrag = self._pdf_fields(kd, empfaenger, breite)
        auftrag["zielordner"] = Path(self.target_folder())
        self.persist()
        self.busy = True
        self.hide_notice("pdf_info")
        button = getattr(self.ui, "btn_pdf", None)
        if button is not None:
            button.set_busy(True, "PDF wird erstellt …")
        self.set_status("PDF wird erstellt …", "busy")

        def work():
            from engine import PdfAuftrag, erstelle_pdf

            # Gemeinsame Sperre mit der Vorschau: die PDF-Erzeugung läuft nie parallel.
            with RENDER_LOCK:
                return erstelle_pdf(PdfAuftrag(**auftrag, pdf_oeffnen=False, status=lambda msg: self.worker.post(self.set_status, msg, "busy")))

        self.worker.run(work, self._done, self._fail)

    def _pdf_fields(self, kd: str, empfaenger: str, breite: float) -> dict:
        """Auftrag für ``engine.erstelle_pdf`` aus dem Formular – gemeinsam für PDF und Vorschau."""
        fuss = self.footer_rich()
        kopf = self.header_rich()
        return dict(
            excel=Path(self.var_excel.get().strip()),
            logo=Path(self.var_logo.get().strip()),
            kundennummer=kd,
            firmenname=self.var_firma.get().strip(),
            rechnungsempfaenger=empfaenger,
            dateiname=self.var_name.get().strip(),
            seitenformat=self.var_format.get(),
            logo_breite=breite,
            titel=self.var_titel.get().strip() or DEFAULT_TITEL,
            untertitel=self.var_untertitel.get().strip() or DEFAULT_UNTERTITEL,
            fusszeile=fuss.text,
            fusszeile_format=fuss.to_dict(),
            kopfzeile=kopf.text,
            kopfzeile_format=kopf.to_dict(),
            regeln=[dict(eintrag) for eintrag in self.state.regeln],
        )

    def _finish_busy(self) -> None:
        self.busy = False
        button = getattr(self.ui, "btn_pdf", None)
        if button is not None:
            button.set_busy(False)

    def _done(self, path: Path) -> None:
        self._finish_busy()
        path = Path(path)
        self._remember_pdf(path)
        self._customer_after_pdf(path)
        self.persist()
        self.notify(
            "pdf_info",
            "success",
            path.name,
            title="PDF wurde erfolgreich erstellt.",
            actions=(
                ("Öffnen", lambda: self._open_pdf(path)),
                ("Ordner öffnen", lambda: self._open_folder_of(path)),
                ("Pfad kopieren", lambda: self.copy_path(path)),
                ("Neue Übersicht", self.new_overview),
            ),
            status=False,
        )
        self.set_status(f"PDF gespeichert: {path}", "success")
        if self.var_open.get():
            self._open_pdf(path)

    def new_overview(self) -> None:
        """Nur die kundenspezifischen Arbeitsdaten zurücksetzen (Firma, Kundennummer, Empfänger, Excel).

        Logo, Zielordner, Darstellung, Vorlage, Kopf-/Fußzeile, Design und Regeln bleiben.
        """
        previous = (self.var_firma.get(), self.var_kd.get(), self.var_mail.get(), self.var_excel.get())
        customer = self._leave_customer()
        self._undo_overview = previous if any(value.strip() for value in previous) or customer else None
        self._undo_overview_customer = customer
        self._reset_work(("", "", "", ""))
        self.hide_notice("pdf_info")
        actions = (("Rückgängig", self._undo_new_overview),) if self._undo_overview else ()
        self.notify("kunde_info", "info", "Bereit für eine neue Übersicht: Kundendaten und Excel-Datei wurden zurückgesetzt.", actions=actions, auto_hide=10000)
        field = getattr(self.ui, "field_firma", None)
        if field is not None:
            try:
                field.focus()
            except tk.TclError:
                pass

    def _reset_work(self, values: tuple[str, str, str, str]) -> None:
        firma, kd, mail, excel = values
        self.kd_required = False
        for name in ("field_kd", "field_firma"):
            field = getattr(self.ui, name, None)
            if field is not None:
                field.set_error(False)
        self.var_firma.set(firma)
        self.var_kd.set(kd)
        self.var_mail.set(mail)
        self.var_excel.set(excel)
        self.refresh_files()
        if excel and Path(excel).is_file():
            self.inspect_excel(excel)
        else:
            self._analysis = None
            self._analysis_path = ""
            self._set_mails([])
            self._show_facts([])
            bar = getattr(self.ui, "info_excel", None)
            if bar is not None:
                from .page_create import EXCEL_EMPTY

                bar.show("neutral", EXCEL_EMPTY)
        self.update_readiness()
        self.persist()

    def _undo_new_overview(self) -> None:
        if self._undo_overview is not None:
            values, self._undo_overview = self._undo_overview, None
            customer, self._undo_overview_customer = self._undo_overview_customer, None
            self._return_to_customer(customer)
            self._reset_work(values)
            self.hide_notice("kunde_info")
            self.set_status("Kundendaten und Excel-Datei wiederhergestellt.", "success")

    def _fail(self, exc: BaseException, tb: str) -> None:
        self._finish_busy()
        self.write_error_log(tb)
        self.notify("pdf_info", "error", str(exc) or exc.__class__.__name__, title="PDF konnte nicht erstellt werden")


def _valid_width(value: str) -> bool:
    try:
        width = float(str(value).replace(",", "."))
    except ValueError:
        return False
    return 0 < width <= 400


def _excel_in(files: list[str]) -> list[str]:
    return [path for path in files if str(path).lower().endswith((".xlsx", ".xlsm", ".xls"))]


def _target_reachable(path: str) -> bool:
    """Zielordner vorhanden und beschreibbar – oder anlegbar (nächster vorhandener Ordner beschreibbar)."""
    folder = Path(path)
    if folder.is_dir():
        return os.access(folder, os.W_OK)
    if folder.exists():
        return False
    parent = folder.parent
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    return parent.is_dir() and os.access(parent, os.W_OK)

