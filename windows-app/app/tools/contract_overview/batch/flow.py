"""Ablauf der Stapelverarbeitung im Hauptfenster (Baustein der App, Teil von »Vertragsübersichten«).

Grundsätze:

* Der Stapel ist eine eigene Arbeitsweise neben »Übersicht erstellen« – der Einzelmodus bleibt
  unverändert. Es gibt keine zweite Fachlogik: Prüfung, Kundenerkennung, Validierung und PDF
  kommen aus ``overview``, ``customers`` und ``engine``.
* Die Modelle (``BatchItem``) werden nur im Thread der Oberfläche verändert. Prüfung und
  PDF-Erstellung laufen im Hintergrund; ihre Ergebnisse kommen gebündelt zurück.
* Die Oberfläche wird gesammelt aktualisiert (``_batch_changed``) – nie Zeile für Zeile.
* Kundenakten werden nach einer Erstellung nur in »zuletzt verwendet«, letzter Excel und
  letzter PDF fortgeschrieben. Neue E-Mail-Zuordnungen entstehen nur mit »Zuordnung merken«.
* Gesichert werden nur Pfade, Zuordnungen und eigene Angaben (``stapel.json``) – keine Kopien
  von Excel- oder PDF-Dateien.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog

import appstate
from appstate import DATA_DIR, DEFAULT_LOGO, ICON_FILE, desktop_dir
from ui import dialogs, windows

from .. import customer_widgets
from ..overview import excel_files, is_excel
from . import processor, resolver
from .analyzer import AnalysisCache, Analyzer
from .models import CREATED, DONE, WAITING, BatchItem, BatchSettings, CustomerMode, ItemStatus, RunSummary, path_key
from .processor import BatchLog, BatchRunner, Job, JobResult, identity_of, redact

QUEUE_FILE = "stapel.json"
QUEUE_VERSION = 1
FILTERS = ("all", "ready", "needs_input", "failed", "done")
FILTER_STATUSES = {
    "all": None,
    "ready": {ItemStatus.READY},
    "needs_input": {ItemStatus.NEEDS_INPUT},
    "failed": {ItemStatus.FAILED},
    "done": set(DONE),
}
SAVE_DELAY = 700


class BatchFlow:
    """Stapelverarbeitung (Baustein des Hauptfensters)."""

    # Einrichtung --------------------------------------------------------------------------
    def _init_batch(self, cfg: dict) -> None:
        default_target = cfg.get("zielordner") if isinstance(cfg.get("zielordner"), str) and cfg.get("zielordner") else str(desktop_dir())
        self.batch_settings = BatchSettings.from_config(cfg, default_target=default_target)
        self.batch_items: list[BatchItem] = []
        self.batch_by_id: dict[str, BatchItem] = {}
        self.batch_cache = AnalysisCache()
        self.batch_analyzer: Analyzer | None = None
        self.batch_runner: BatchRunner | None = None
        self.batch_filter = "all"
        self.batch_summary: RunSummary | None = None  # Ergebnis des letzten Durchlaufs
        self.batch_resolutions: dict[str, resolver.Resolution] = {}
        self.batch_log = BatchLog(DATA_DIR)
        self.batch_page = None
        self._batch_touched: dict[str, str] = {}  # Eintrag → Kundenakte der laufenden Erstellung
        self._batch_cancelled: set[str] = set()  # beim Abbruch sauber beendete Einträge (»nicht verarbeitet«)
        self._batch_retry_after_check: set[str] = set()  # nach der erneuten Prüfung direkt erstellen
        self._batch_removed: list[tuple[int, BatchItem]] | None = None
        self._batch_restore = self._batch_load_queue()

    def _start_batch(self) -> None:
        self.batch_analyzer = Analyzer(self.batch_cache, lambda func: self.worker.run(func), self.worker.post, self._batch_analyzed)
        restored, self._batch_restore = self._batch_restore, []
        if restored:
            self._batch_insert(restored)

    def batch_config(self) -> dict:
        return self.batch_settings.to_config()

    @property
    def batch_running(self) -> bool:
        return self.batch_runner is not None and not self.batch_runner.finished

    # Hinzufügen ------------------------------------------------------------------------------
    def pick_batch_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Excel-Dateien für den Stapel wählen",
            initialdir=self._initial_dir("excel", ""),
            filetypes=[("Excel", "*.xlsx *.xlsm *.xls"), ("Alle Dateien", "*.*")],
        )
        if paths:
            self._remember_dir("excel", paths[0])
            self.batch_add(list(paths))

    def pick_batch_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Ordner mit Excel-Dateien wählen", initialdir=self._initial_dir("excel", ""))
        if folder:
            self.batch_add([folder])

    def batch_add(self, paths: list[str]) -> tuple[int, int, int]:
        """Dateien und Ordner (nicht rekursiv) hinzufügen. Rückgabe: (neu, doppelt, ignoriert)."""
        files: list[str] = []
        ignored = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                try:
                    found = sorted((str(child) for child in path.iterdir() if child.is_file() and is_excel(child) and not child.name.startswith("~$")), key=str.casefold)
                except OSError:
                    found = []
                files += found
            elif is_excel(path):
                files.append(str(path))
            else:
                ignored += 1
        known = {item.key for item in self.batch_items}
        fresh: list[BatchItem] = []
        duplicates = 0
        for path in files:
            key = path_key(path)
            if key in known:
                duplicates += 1
                continue
            known.add(key)
            fresh.append(BatchItem(os.path.abspath(path)))
        self._batch_insert(fresh)
        parts = []
        if fresh:
            parts.append("1 Excel-Datei hinzugefügt" if len(fresh) == 1 else f"{len(fresh)} Excel-Dateien hinzugefügt")
        if duplicates:
            parts.append("1 war schon im Stapel" if duplicates == 1 else f"{duplicates} waren schon im Stapel")
        if ignored:
            parts.append("1 Datei ist keine Excel-Datei und wurde nicht übernommen" if ignored == 1 else f"{ignored} Dateien sind keine Excel-Dateien und wurden nicht übernommen")
        if not files and not ignored:
            parts.append("Keine Excel-Dateien gefunden")
        if parts:
            severity = "success" if fresh and not ignored else ("warning" if ignored or not fresh else "info")
            self.notify("batch_info", severity, " · ".join(parts) + ".", auto_hide=8000 if severity == "success" else None)
        return len(fresh), duplicates, ignored

    def batch_drop(self, files: list[str]) -> None:
        """Mehrere Dateien auf die Ansicht »Stapel« gezogen: alle Excel-Dateien (und Ordner) übernehmen."""
        if not any(is_excel(path) or Path(path).is_dir() for path in files):
            self.notify("batch_info", "warning", "Bitte Excel-Dateien (.xlsx oder .xls) oder einen Ordner mit Excel-Dateien in das Fenster ziehen.")
            return
        self.batch_add(files)

    def _batch_insert(self, items: list[BatchItem]) -> None:
        if not items:
            return
        for item in items:
            self.batch_items.append(item)
            self.batch_by_id[item.id] = item
        waiting = []
        for item in items:
            if item.status in DONE:
                continue  # schon erstellt (aus der Sicherung): nicht erneut prüfen, bis er geändert wird
            item.status = ItemStatus.ANALYZING
            waiting.append((item.id, item.path))
        self.batch_summary = None
        self._batch_changed(structure=True)
        self._batch_save_soon()
        if waiting and self.batch_analyzer is not None:
            # Erst die neuen Zeilen zeichnen, dann prüfen: So konkurriert die Prüfung nicht mit dem Aufbau der Liste.
            self.after_idle(lambda: self._batch_submit(waiting))

    def _batch_submit(self, entries: list[tuple[str, str]]) -> None:
        entries = [(item_id, path) for item_id, path in entries if item_id in self.batch_by_id]
        if entries and self.batch_analyzer is not None:
            self.batch_analyzer.submit(entries)

    # Prüfung ------------------------------------------------------------------------------------
    def _batch_analyzed(self, results) -> None:
        """Ergebnisse der Voranalyse (gebündelt, im Thread der Oberfläche)."""
        for item_id, analysis, stamp in results:
            item = self.batch_by_id.get(item_id)
            if item is None:
                continue  # inzwischen entfernt
            item.analysis, item.stamp = analysis, stamp
            if item.status is ItemStatus.ANALYZING:
                item.status = ItemStatus.PENDING
            self._batch_update(item)
        self._batch_changed()
        self._batch_retry_checked()

    def _batch_retry_checked(self) -> None:
        """Nach »erneut versuchen« neu geprüfte Dateien: bereite direkt erstellen."""
        waiting = self._batch_retry_after_check
        if not waiting or self.batch_running:
            return
        pending = [i for i in waiting if i in self.batch_by_id and self.batch_by_id[i].status in WAITING]
        if pending:
            return  # erst, wenn alle geprüft sind
        ready = [i for i in waiting if i in self.batch_by_id and self.batch_by_id[i].status is ItemStatus.READY]
        self._batch_retry_after_check = set()
        if ready:
            self.batch_start([item.id for item in self.batch_items if item.id in set(ready)], label="Erneuter Versuch")

    def batch_recheck(self, item: BatchItem) -> None:
        """Eine Datei erneut prüfen (z. B. »erneut versuchen« nach einem Datei-Problem)."""
        self.batch_cache.forget(item.path)
        item.analysis, item.stamp = None, None
        item.status = ItemStatus.ANALYZING
        if self.batch_analyzer is not None:
            self.batch_analyzer.submit([(item.id, item.path)])

    # Werte und Status -----------------------------------------------------------------------------
    def batch_defaults(self) -> resolver.Defaults:
        """Globaler Standard aus »Darstellung« – ohne Texte einer gerade aktiven Kundenakte."""
        header, footer = self.header_rich(), self.footer_rich()
        if getattr(self, "_customer_texts", False) and getattr(self, "_base_texts", None) is not None:
            header, footer = self._base_texts
        return resolver.Defaults(
            dateiname=self.var_name.get().strip(),
            seitenformat=self.var_format.get(),
            logo_breite=self.var_breite.get().strip(),
            titel=self.var_titel.get().strip(),
            untertitel=self.var_untertitel.get().strip(),
            header=header,
            footer=footer,
            regeln=tuple(dict(regel) for regel in self.state.regeln),
            logo=str(DEFAULT_LOGO),
        )

    def batch_resolve(self, item: BatchItem, for_preview: bool = False) -> resolver.Resolution:
        return resolver.resolve(item, self.customers, self.state.find_vorlage, self.batch_settings, self.batch_defaults(), for_preview=for_preview)

    def _batch_update(self, item: BatchItem) -> resolver.Resolution:
        """Werte und Status eines Eintrags neu bestimmen (ein erstelltes Ergebnis bleibt)."""
        res = self.batch_resolve(item)
        self.batch_resolutions[item.id] = res
        item.issues = tuple(res.issues)
        if item.status in DONE or item.status is ItemStatus.PROCESSING:
            return res
        if item.status is ItemStatus.FAILED and item.error:
            return res  # Fehler der Erstellung bleibt sichtbar bis »erneut versuchen« oder Änderung
        item.notes = tuple(res.notes) + tuple(note for note in item.notes if note.startswith("Die Excel wurde"))
        if item.status is ItemStatus.ANALYZING or (item.analysis is None and item.status is ItemStatus.PENDING):
            return res
        item.status = resolver.status_for(res.issues)
        return res

    def batch_refresh_all(self) -> None:
        """Nach Änderungen an Kundenakten, Vorlagen, Darstellung oder Stapel-Einstellungen."""
        for item in self.batch_items:
            self._batch_update(item)
        self._batch_changed()

    def batch_customers_changed(self) -> None:
        for item in self.batch_items:
            if item.customer_mode is CustomerMode.MANUAL and self.customers.get(item.customer_id) is None:
                item.customer_mode, item.customer_id = CustomerMode.AUTO, None  # gelöschte Kundenakte
        self.batch_refresh_all()

    def batch_inherited(self, item_id: str) -> dict[str, str]:
        """Werte, die ohne eigene Angabe gälten (Kundenakte bzw. Excel) – für »zurück auf übernommen«."""
        item = self.batch_by_id.get(item_id)
        if item is None:
            return {}
        probe = replace(item, overrides=replace(item.overrides, company=None, number=None, email=None))
        res = self.batch_resolve(probe)
        return {"company": res.company, "number": res.number, "email": res.email if not res.emails else ""}

    def batch_mark_stale(self) -> None:
        """Darstellung, Vorlagen o. Ä. geändert: Werte der Einträge neu bestimmen – gesammelt."""
        if not self.batch_items:
            return
        self.ctx.anim.later("batch:stale", 300, self.batch_refresh_all)

    def batch_resolution(self, item_id: str) -> resolver.Resolution | None:
        item = self.batch_by_id.get(item_id)
        if item is None:
            return None
        res = self.batch_resolutions.get(item_id)
        return res if res is not None else self._batch_update(item)

    def batch_counts(self) -> dict[str, int]:
        counts = {key: 0 for key in FILTERS}
        for item in self.batch_items:
            counts["all"] += 1
            for key, statuses in FILTER_STATUSES.items():
                if statuses is not None and item.status in statuses:
                    counts[key] += 1
        return counts

    def batch_visible(self) -> list[BatchItem]:
        statuses = FILTER_STATUSES.get(self.batch_filter)
        if statuses is None:
            return list(self.batch_items)
        return [item for item in self.batch_items if item.status in statuses]

    def set_batch_filter(self, key: str) -> None:
        if key in FILTERS and key != self.batch_filter:
            self.batch_filter = key
            self._batch_changed(structure=True)

    # Bearbeiten --------------------------------------------------------------------------------------
    def batch_edit(self, item_id: str, **overrides) -> None:
        """Eigene Angaben im Eintrag setzen (``None`` = wieder übernehmen)."""
        item = self.batch_by_id.get(item_id)
        if item is None or item.status is ItemStatus.PROCESSING:
            return
        changed = False
        for key, value in overrides.items():
            if getattr(item.overrides, key) != value:
                setattr(item.overrides, key, value)
                changed = True
        if changed:
            self._batch_modified(item)

    def _batch_modified(self, item: BatchItem) -> None:
        """Ein Eintrag wurde geändert: ein früheres Ergebnis verfällt, der Status wird neu bestimmt."""
        if not self.batch_running:
            self.batch_summary = None  # das Ergebnis beschreibt den letzten Lauf, nicht mehr den Stapel
        if item.done or (item.status is ItemStatus.FAILED and item.error):
            item.reset_result()
        if item.analysis is None and item.status is not ItemStatus.ANALYZING:
            self.batch_recheck(item)  # z. B. aus der Sicherung wiederhergestellt: erst prüfen
        self._batch_update(item)
        self._batch_changed(item_ids=(item.id,))
        self._batch_save_soon()
        if getattr(self, "_preview_item", None) == item.id:
            self.mark_preview_dirty()

    def batch_choose_customer(self, item_id: str) -> None:
        item = self.batch_by_id.get(item_id)
        if item is None:
            return
        if not len(self.customers):
            self.notify("batch_detail_info", "info", "Noch keine Kundenakten gespeichert. Kundenakten entstehen in »Übersicht erstellen« oder in der Ansicht »Kunden«.", auto_hide=10000, status=False)
            return
        res = self.batch_resolution(item_id)
        candidates = None
        message = None
        if res is not None and res.match is not None and res.match.kind.value in ("conflicting_matches", "ambiguous_match"):
            candidates = list(res.match.customer_ids)
            message = "Die Rechnungsempfänger dieser Excel gehören zu mehreren Kundenakten. Welcher Kunde ist gemeint?"
        chosen = customer_widgets.choose_customer(self, self.customers, candidates=candidates, message=message)
        if chosen:
            self.batch_set_customer(item_id, CustomerMode.MANUAL, chosen)

    def batch_set_customer(self, item_id: str, mode: CustomerMode, customer_id: str | None = None) -> None:
        item = self.batch_by_id.get(item_id)
        if item is None or item.status is ItemStatus.PROCESSING:
            return
        item.customer_mode = mode
        item.customer_id = customer_id if mode is CustomerMode.MANUAL else None
        self._batch_modified(item)

    def batch_remember_emails(self, item_id: str) -> None:
        """»Zuordnung merken«: unbekannte Adressen dieser Excel künftig dem Kunden des Eintrags zuordnen."""
        res = self.batch_resolution(item_id)
        if res is None or res.customer is None or not res.unknown_emails:
            return
        self.assign_emails(res.customer.id, list(res.unknown_emails))  # dieselbe Logik wie im Einzelmodus (mit Konfliktdialog)

    def batch_decline_emails(self, item_id: str) -> None:
        res = self.batch_resolution(item_id)
        if res is None or res.customer is None:
            return
        self._declined_emails.update((res.customer.id, email) for email in res.unknown_emails)
        self._batch_changed(item_ids=(item_id,))

    def batch_offer_emails(self, item_id: str) -> tuple[str, ...]:
        """Adressen, deren Zuordnung zum Kunden des Eintrags angeboten wird (nicht abgelehnte)."""
        res = self.batch_resolution(item_id)
        if res is None or res.customer is None:
            return ()
        return tuple(email for email in res.unknown_emails if (res.customer.id, email) not in self._declined_emails)

    # Auswahl und Massenaktionen ----------------------------------------------------------------------------
    def batch_select(self, item_id: str, selected: bool) -> None:
        item = self.batch_by_id.get(item_id)
        if item is not None and item.selected != selected:
            item.selected = selected
            self._batch_changed(item_ids=(item_id,))

    def batch_select_all(self, selected: bool) -> None:
        for item in self.batch_visible():
            item.selected = selected
        self._batch_changed()

    def batch_selected(self) -> list[BatchItem]:
        return [item for item in self.batch_items if item.selected]

    def batch_remove(self, item_ids: list[str]) -> None:
        """Einträge aus dem Stapel nehmen (rückgängig machbar). Dateien bleiben unberührt."""
        if self.batch_running:
            return
        removed = [(index, item) for index, item in enumerate(self.batch_items) if item.id in set(item_ids)]
        if not removed:
            return
        for _index, item in removed:
            self.batch_items.remove(item)
            self.batch_by_id.pop(item.id, None)
            self.batch_resolutions.pop(item.id, None)
        self._batch_removed = removed
        self.batch_summary = None
        self._batch_changed(structure=True)
        self._batch_save_soon()
        text = f"„{removed[0][1].name}“ aus dem Stapel entfernt." if len(removed) == 1 else f"{len(removed)} Einträge aus dem Stapel entfernt."
        self.notify("batch_info", "info", text + " Die Dateien selbst bleiben unverändert.", actions=(("Rückgängig", self._batch_undo_remove),), auto_hide=10000)

    def batch_remove_selected(self) -> None:
        self.batch_remove([item.id for item in self.batch_selected()])

    def _batch_undo_remove(self) -> None:
        removed, self._batch_removed = self._batch_removed, None
        if not removed:
            return
        for index, item in removed:
            if item.id not in self.batch_by_id:
                self.batch_items.insert(min(index, len(self.batch_items)), item)
                self.batch_by_id[item.id] = item
                self._batch_update(item)
        self.hide_notice("batch_info")
        self._batch_changed(structure=True)
        self._batch_save_soon()

    def batch_apply_template(self, name: str | None, item_ids: list[str] | None = None) -> int:
        """Vorlage für mehrere Einträge setzen (``None`` = wieder automatisch, ``""`` = keine Vorlage)."""
        targets = [self.batch_by_id[i] for i in item_ids if i in self.batch_by_id] if item_ids is not None else self.batch_selected()
        count = 0
        for item in targets:
            if item.status is ItemStatus.PROCESSING or item.overrides.template == name:
                continue
            item.overrides.template = name
            if item.done or (item.status is ItemStatus.FAILED and item.error):
                item.reset_result()
            if item.analysis is None and item.status is not ItemStatus.ANALYZING:
                self.batch_recheck(item)
            self._batch_update(item)
            count += 1
        if count:
            self._batch_changed()
            self._batch_save_soon()
        return count

    def batch_template_names(self) -> list[str]:
        return [str(entry.get("name", "")) for entry in self.state.vorlagen if entry.get("name")]

    # Einstellungen des Stapels -------------------------------------------------------------------------------------
    def batch_update_settings(self, **values) -> None:
        changed = False
        for key, value in values.items():
            if getattr(self.batch_settings, key) != value:
                setattr(self.batch_settings, key, value)
                changed = True
        if changed:
            self.schedule_save()
            self.batch_refresh_all()

    def pick_batch_target(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Zielordner für den Stapel", initialdir=self._initial_dir("ziel", self.batch_settings.target_dir))
        if path:
            self.batch_update_settings(target_dir=path)

    def pick_batch_logo(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Standardlogo für den Stapel", initialdir=self._initial_dir("logo", self.batch_settings.logo), filetypes=[("Bilder", "*.png *.jpg *.jpeg *.webp"), ("Alle Dateien", "*.*")])
        if path:
            self._remember_dir("logo", path)
            self.batch_update_settings(logo=path)

    # Verarbeitung -------------------------------------------------------------------------------------------------------
    def batch_ready_ids(self) -> list[str]:
        return [item.id for item in self.batch_items if item.status is ItemStatus.READY]

    def batch_start(self, item_ids: list[str] | None = None, label: str = "Stapel") -> None:
        """»Bereite Übersichten erstellen«: nur bereite Einträge, nacheinander, im Hintergrund."""
        if self.batch_running:
            return
        ids = item_ids if item_ids is not None else self.batch_ready_ids()
        if not ids:
            self.notify("batch_info", "info", "Kein Eintrag ist bereit. Einträge mit »Angaben erforderlich« zuerst vervollständigen.", auto_hide=8000)
            return
        self.persist()
        self._batch_touched = {}
        self._batch_cancelled = set()
        self.batch_summary = None
        # Nicht bereite Einträge gehören zum Ergebnis: »übersprungen« (Angaben fehlen) bzw. »fehlgeschlagen«.
        others = [item.id for item in self.batch_items if item.id not in set(ids)] if item_ids is None else []
        self.batch_log.write([f"{label} gestartet: {len(ids)} {'Eintrag' if len(ids) == 1 else 'Einträge'}"])
        self.batch_runner = BatchRunner(
            ids,
            self._batch_prepare,
            lambda func, on_done, on_error: self.worker.run(func, on_done, on_error),
            self._batch_item_started,
            self._batch_item_done,
            lambda summary, remaining: self._batch_finished(summary, remaining, list(ids), others),
            run=lambda job, cancelled: processor.run_job(job, cancelled),
        )
        self._batch_changed()
        self.batch_runner.start()

    def batch_cancel(self) -> None:
        if self.batch_running:
            self.batch_runner.cancel()
            self._batch_changed()

    def batch_retry_failed(self) -> None:
        """»Fehlgeschlagene erneut versuchen«: nur fehlgeschlagene Einträge; Datei-Probleme werden neu geprüft."""
        if self.batch_running:
            return
        failed = [item for item in self.batch_items if item.status is ItemStatus.FAILED]
        if not failed:
            return
        rerun: list[str] = []
        recheck: set[str] = set()
        for item in failed:
            file_problem = not item.error or any(issue.code in ("file_missing", "unreadable", "columns_missing", "no_active") for issue in item.issues)
            item.error = ""
            if file_problem:
                self.batch_recheck(item)  # Datei-Problem: erst neu prüfen, dann (wenn bereit) erstellen
                recheck.add(item.id)
            else:
                item.status = ItemStatus.PENDING
                self._batch_update(item)
                if item.status is ItemStatus.READY:
                    rerun.append(item.id)
        self._batch_retry_after_check = recheck
        self._batch_changed()
        if rerun:
            self.batch_start(rerun, label="Erneuter Versuch")
        elif recheck:
            self.set_status("Fehlgeschlagene Dateien werden neu geprüft …", "busy")

    def _batch_prepare(self, item_id: str, created: frozenset[str]) -> Job | None:
        """Unmittelbar vor der Erstellung: aktuelle Werte (Kundenakte, Vorlage, Einstellungen) laden."""
        item = self.batch_by_id.get(item_id)
        if item is None or item.status is not ItemStatus.READY:
            return None
        res = self._batch_update(item)
        if not res.ready or item.status is not ItemStatus.READY:
            return None
        item.status = ItemStatus.PROCESSING
        item.notes = ()
        if res.customer is not None:
            self._batch_touched[item.id] = res.customer.id
        label = res.company or res.number or item.name
        return Job(item.id, label, item.path, item.stamp, identity_of(item.analysis), res.fields, res.folder, self.batch_settings.conflict, created)

    def _batch_item_started(self, item_id: str, job: Job) -> None:
        self._batch_changed(item_ids=(item_id,))

    def _batch_item_done(self, result: JobResult) -> None:
        item = self.batch_by_id.get(result.item_id)
        customer_id = self._batch_touched.pop(result.item_id, None)
        if item is None:
            return
        if result.cancelled:
            self._batch_cancelled.add(item.id)
            item.status = ItemStatus.PENDING
            self._batch_update(item)
        elif result.changed:
            item.analysis, item.stamp = result.analysis, result.stamp
            if result.analysis is not None and result.analysis.ok:
                self.batch_cache.put(item.path, result.stamp, result.analysis)
            item.status = ItemStatus.PENDING
            item.notes = (result.error,)
            self._batch_update(item)
        elif result.status in CREATED or result.status is ItemStatus.SKIPPED:
            item.status = result.status
            item.output = result.output
            item.notes = result.notes
            item.error = ""
            if result.status in CREATED and customer_id and self.customers.get(customer_id) is not None:
                # nur Metadaten: zuletzt verwendet, letzte Excel, letzte PDF – nie Darstellungswerte
                self.customers.touch(customer_id, excel=item.path, pdf=result.output)
        else:
            item.status = ItemStatus.FAILED
            item.error = result.error or "Unbekannter Fehler"
            item.output = ""
            paths = [item.path, str(Path(item.path).parent)]
            self.batch_log.write([redact(f"Fehler: {item.name}: {item.error}", paths)] + [redact(line, paths) for line in result.trace])
        self._batch_changed(item_ids=(item.id,))
        self._batch_save_soon()

    def _batch_finished(self, summary: RunSummary, remaining: list[str], run_ids: list[str] | None = None, others: list[str] | None = None) -> None:
        for item_id in remaining:
            item = self.batch_by_id.get(item_id)
            if item is not None and item.status is ItemStatus.PROCESSING:
                item.status = ItemStatus.PENDING
                self._batch_update(item)
        # Das Ergebnis zählt nach dem tatsächlichen Status der Einträge – so passt es zur Liste
        # (z. B. eine kurz vor ihrer Verarbeitung gelöschte Datei ist »fehlgeschlagen«).
        not_processed = set(remaining) | self._batch_cancelled
        created = failed = skipped = 0
        for item_id in [*(run_ids or []), *(others or [])]:
            item = self.batch_by_id.get(item_id)
            if item is None or item_id in not_processed:
                continue
            if item_id in (others or []) and item.status in DONE:
                continue  # schon früher erstellt – gehört nicht zu diesem Durchlauf
            if item.status in CREATED:
                created += 1
            elif item.status is ItemStatus.FAILED:
                failed += 1
            elif item.status in (ItemStatus.SKIPPED, ItemStatus.NEEDS_INPUT) or item_id in (run_ids or []):
                skipped += 1
        if run_ids is not None:
            summary.created, summary.failed, summary.skipped = created, failed, skipped
        self.batch_summary = summary
        self._store_customers()
        if self.customer_page is not None:
            self.customer_page.refresh()
        state = "abgebrochen" if summary.aborted else "beendet"
        self.batch_log.write([f"Stapel {state}: {summary.created} erstellt, {summary.skipped} übersprungen, {summary.failed} fehlgeschlagen" + (f", {summary.cancelled} nicht verarbeitet" if summary.cancelled else "")])
        self._batch_changed(structure=True)
        self._batch_save_soon()
        self.set_status(self.batch_summary_text(summary), "warning" if summary.failed or summary.aborted else "success")
        self._batch_retry_checked()

    def batch_summary_text(self, summary: RunSummary) -> str:
        parts = ["1 Übersicht erstellt" if summary.created == 1 else f"{summary.created} Übersichten erstellt"]
        if summary.skipped:
            parts.append(f"{summary.skipped} übersprungen")
        if summary.failed:
            parts.append(f"{summary.failed} fehlgeschlagen")
        if summary.cancelled:
            parts.append(f"{summary.cancelled} nicht verarbeitet")
        return ("Stapel abgebrochen: " if summary.aborted else "Stapel abgeschlossen: ") + " · ".join(parts)

    # Nach dem Durchlauf ----------------------------------------------------------------------------------------------------
    def batch_output_folders(self) -> list[str]:
        folders: list[str] = []
        for item in self.batch_items:
            if item.status in CREATED and item.output:
                folder = str(Path(item.output).parent)
                if folder not in folders:
                    folders.append(folder)
        return folders

    def batch_open_output(self) -> None:
        """»Ausgabeordner öffnen«: der gemeinsame Ordner (bzw. der Zielordner des Stapels)."""
        folders = self.batch_output_folders()
        target = folders[0] if len(folders) == 1 else self.batch_settings.target_dir
        if len(folders) > 1:
            common = os.path.commonpath(folders) if all(Path(f).drive == Path(folders[0]).drive for f in folders) else ""
            target = common or self.batch_settings.target_dir
        if not target or not Path(target).is_dir():
            self.notify("batch_info", "warning", "Der Ausgabeordner ist nicht vorhanden.")
            return
        try:
            windows.open_path(target)
        except OSError as exc:
            self.notify("batch_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    def batch_show_errors(self) -> None:
        self.set_batch_filter("failed")

    def batch_new(self) -> None:
        """»Neuer Stapel«: Warteschlange leeren. Kundenakten, Vorlagen, Darstellung und Einstellungen bleiben."""
        if self.batch_running:
            return
        open_items = [item for item in self.batch_items if item.status not in DONE]
        if open_items and not dialogs.confirm(
            self,
            "Neuen Stapel beginnen?",
            f"{len(open_items)} {'Eintrag wurde' if len(open_items) == 1 else 'Einträge wurden'} noch nicht erstellt. Die Liste wird geleert – Excel-Dateien, erstellte PDFs, Kundenakten, Vorlagen und Einstellungen bleiben unverändert.",
            "Neuer Stapel",
            danger=False,
            icon=ICON_FILE,
        ):
            return
        if self.batch_analyzer is not None:
            self.batch_analyzer.clear()
        self.batch_items.clear()
        self.batch_by_id.clear()
        self.batch_resolutions.clear()
        self.batch_summary = None
        self.batch_filter = "all"
        self._batch_removed = None
        self.hide_notice("batch_info")
        self._batch_changed(structure=True)
        self._batch_save_now()

    # Vorschau und Einzelmodus ----------------------------------------------------------------------------------------------------
    def batch_preview(self, item_id: str) -> None:
        """Vorschau genau dieses Eintrags – dieselbe Vorschau-Pipeline wie im Einzelmodus."""
        if item_id not in self.batch_by_id:
            return
        self._preview_item = item_id
        self.nav.navigate("preview")

    def batch_preview_fields(self, item_id: str) -> tuple[dict | None, str]:
        item = self.batch_by_id.get(item_id)
        if item is None:
            return None, "Der Eintrag ist nicht mehr im Stapel."
        res = self.batch_resolve(item, for_preview=True)
        if res.fields is None:
            blocking = [issue for issue in res.issues if issue.code in resolver.PREVIEW_BLOCKING]
            return None, (blocking[0].text if blocking else "Vorschau nicht möglich")
        return res.fields, ""

    def batch_edit_single(self, item_id: str) -> None:
        """»Einzeln bearbeiten«: Eintrag in »Übersicht erstellen« übernehmen (rückgängig machbar)."""
        item = self.batch_by_id.get(item_id)
        if item is None:
            return
        res = self.batch_resolve(item)
        previous = (self.var_firma.get(), self.var_kd.get(), self.var_mail.get(), self.var_excel.get())
        customer_state = self._leave_customer()
        self._undo_overview = previous if any(value.strip() for value in previous) or customer_state else None
        self._undo_overview_customer = customer_state
        self._reset_work(("", "", "", item.path))
        if res.customer is not None:
            self.apply_customer(res.customer.id)
        ov = item.overrides
        if ov.template is not None:
            entry = self.state.find_vorlage(ov.template) if ov.template else None
            if entry is not None:
                self._apply_vorlage(entry, texts=self._texts_fresh(), quiet=True)
        for var, value in ((self.var_firma, res.company), (self.var_kd, res.number)):
            if value and var.get().strip() != value:
                var.set(value)
        if len(res.emails) > 1 and res.email:
            self.var_mail.set(res.email)
        elif ov.email:
            self.var_mail.set(ov.email)
        if ov.logo and Path(ov.logo).is_file():
            self.var_logo.set(ov.logo)
        if ov.target_dir:
            self.var_ziel.set(ov.target_dir)
        self.refresh_files()
        self.nav.navigate("create")
        actions = (("Rückgängig", self._undo_new_overview),) if self._undo_overview else ()
        self.notify("kunde_info", "info", f"„{item.name}“ aus dem Stapel übernommen. Der Stapel-Eintrag bleibt unverändert.", actions=actions, auto_hide=10000)

    # Sicherung der Warteschlange ----------------------------------------------------------------------------------------------
    def _batch_queue_path(self) -> Path:
        return Path(appstate.CONFIG_FILE).parent / QUEUE_FILE

    def _batch_load_queue(self) -> list[BatchItem]:
        path = self._batch_queue_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, dict) or not isinstance(data.get("eintraege"), list):
            return []
        items: list[BatchItem] = []
        seen: set[str] = set()
        for raw in data["eintraege"]:
            item = BatchItem.from_dict(raw)
            if item is not None and item.key not in seen:
                seen.add(item.key)
                items.append(item)
        return items

    def _batch_save_soon(self) -> None:
        if getattr(self, "_closing", False):
            return
        self.ctx.anim.later("batch:save", SAVE_DELAY, self._batch_save_now)

    def _batch_save_now(self) -> None:
        """Stapel sichern (nur Pfade, Zuordnungen, eigene Angaben, Ergebnisse) – atomar."""
        self.ctx.anim.cancel_later("batch:save")
        path = self._batch_queue_path()
        if not self.batch_items:
            try:
                path.unlink()
            except OSError:
                pass
            return
        data = {"version": QUEUE_VERSION, "eintraege": [item.to_dict() for item in self.batch_items]}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp = tempfile.mkstemp(prefix=".stapel-", suffix=".tmp", dir=str(path.parent))
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as stream:
                    json.dump(data, stream, ensure_ascii=False, indent=1)
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.remove(temp)
        except OSError:
            pass

    def batch_confirm_close(self) -> bool:
        """Beenden während der Erstellung: nachfragen. Fertige PDFs bleiben erhalten."""
        if not self.batch_running:
            return True
        return dialogs.confirm(
            self,
            "Stapel wird gerade erstellt",
            "Beenden bricht den Stapel ab. Bereits erstellte PDFs bleiben erhalten, die laufende wird sauber verworfen.",
            "Abbrechen und beenden",
            icon=ICON_FILE,
        )

    def _batch_close(self) -> None:
        """Beim Beenden: laufende Erstellung abbrechen und kurz auf ihr sauberes Ende warten."""
        import time

        runner = self.batch_runner
        if runner is not None and not runner.finished:
            runner.cancel()
            deadline = time.monotonic() + 8.0
            while not runner.finished and time.monotonic() < deadline:
                try:
                    self.update()
                except Exception:  # noqa: BLE001 - beim Beenden zählt nur, dass nichts halb bleibt
                    break
                time.sleep(0.02)
        if self.batch_analyzer is not None:
            self.batch_analyzer.clear()
        self._batch_save_now()

    # Anzeige -------------------------------------------------------------------------------------------------------------------------
    def _batch_changed(self, item_ids: tuple[str, ...] | None = None, structure: bool = False) -> None:
        """Oberfläche gesammelt aktualisieren (höchstens einmal je Leerlauf)."""
        page = self.batch_page
        if page is None:
            return
        page.invalidate(item_ids, structure)

    def batch_accepts(self, files: list[str]) -> bool:
        return bool(excel_files(files)) or any(Path(path).is_dir() for path in files)
