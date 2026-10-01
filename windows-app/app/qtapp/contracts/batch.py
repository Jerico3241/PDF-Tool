"""Stapelverarbeitung in »Vertragsübersichten« (in QML: ``Batch``).

Grundsätze (unverändert seit 2.5):

* Der Stapel ist eine eigene Arbeitsweise neben »Übersicht erstellen«. Es gibt keine zweite
  Fachlogik: Prüfung, Kundenerkennung, Validierung und PDF kommen aus ``overview``,
  ``customers``, ``batch.resolver``/``processor`` und ``engine``.
* Die Modelle (``BatchItem``) werden nur im GUI-Thread verändert. Prüfung und PDF-Erstellung
  laufen im Hintergrund; ihre Ergebnisse kommen gebündelt zurück.
* Die Oberfläche wird gesammelt aktualisiert – die Liste ist ein Listenmodell, das nur
  geänderte Zeilen meldet (ListView erzeugt nur die sichtbaren Zeilen).
* Kundenakten werden nach einer Erstellung nur in »zuletzt verwendet«, letzter Excel und letzter
  PDF fortgeschrieben. Neue E-Mail-Zuordnungen entstehen nur mit »Zuordnung merken«.
* Gesichert werden nur Pfade, Zuordnungen und eigene Angaben (``stapel.json``) – keine Kopien
  von Excel- oder PDF-Dateien.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Property, QCoreApplication, QObject, Signal, Slot

import appstate
from appstate import DATA_DIR, DEFAULT_LOGO, desktop_dir
from tools.contract_overview.batch import processor, resolver
from tools.contract_overview.batch.analyzer import AnalysisCache, Analyzer
from tools.contract_overview.batch.models import CREATED, DONE, WAITING, BatchItem, BatchSettings, ConflictMode, CustomerMode, ItemStatus, RunSummary, path_key
from tools.contract_overview.batch.processor import BatchLog, BatchRunner, Job, JobResult, identity_of, redact
from tools.contract_overview.history import report
from tools.contract_overview.overview import contract_summary, excel_files, is_excel

from .. import dialogs as dialog_service
from .. import files
from ..base import Observable, prop
from ..models import KeyedListModel
from .comparison import AFTER_EXPORT, NO_CUSTOMER, ComparisonView, snapshot_facts

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
EDIT_DELAY = 450
SUBTITLE = "Mehrere Excel-Listen prüfen und gesammelt als PDF erstellen."
EMPTY_TITLE = "Noch keine Excel-Dateien hinzugefügt."
EMPTY_TEXT = "Füge mehrere Excel-Dateien hinzu, um Vertragsübersichten gesammelt zu erstellen."
EMPTY_HINT = "Excel-Dateien oder einen Ordner auch einfach in das Fenster ziehen. Jede Datei wird sofort geprüft; bekannte Kunden werden an der Rechnungsempfänger-E-Mail erkannt."
EMPTY_HINT_PLAIN = "Excel-Dateien oder einen Ordner auch einfach in das Fenster ziehen. Jede Datei wird sofort geprüft."
SETTINGS_TEXT = "Gilt für alle Einträge. Angaben einer Kundenakte oder eines Eintrags haben Vorrang."
SETTINGS_TEXT_PLAIN = "Gilt für alle Einträge. Angaben eines Eintrags haben Vorrang."
OUTPUT_TEXT = "Eigene Angaben gelten nur für diesen Eintrag; »Zurücksetzen« übernimmt wieder Kundenakte bzw. Stapel."
OUTPUT_TEXT_PLAIN = "Eigene Angaben gelten nur für diesen Eintrag; »Zurücksetzen« übernimmt wieder die Angaben des Stapels."
PRIVACY = "Alles geschieht lokal auf diesem PC – keine Cloud, keine Uploads."
RUN_TEXT = "Bereite Übersichten erstellen"
FILTER_LABELS = {"all": "Alle", "ready": "Bereit", "needs_input": "Angaben erforderlich", "failed": "Fehler", "done": "Fertig"}
FILTER_EMPTY = {
    "ready": "Kein Eintrag ist bereit.",
    "needs_input": "Kein Eintrag braucht weitere Angaben.",
    "failed": "Keine Fehler.",
    "done": "Noch nichts erstellt.",
}
CONFLICT_LABELS = {ConflictMode.NUMBER: "Automatisch nummerieren", ConflictMode.SKIP: "Überspringen", ConflictMode.OVERWRITE: "Überschreiben"}
TEMPLATE_AUTO = "Automatisch"
TEMPLATE_NONE = "Keine Vorlage"
STATUS = {
    ItemStatus.PENDING: ("Wartet auf Prüfung", "neutral"),
    ItemStatus.ANALYZING: ("Wird geprüft …", "neutral"),
    ItemStatus.READY: ("Bereit", "success"),
    ItemStatus.NEEDS_INPUT: ("Angaben erforderlich", "caution"),
    ItemStatus.PROCESSING: ("Wird erstellt …", "accent"),
    ItemStatus.SUCCESS: ("Erstellt", "success"),
    ItemStatus.WARNING: ("Erstellt mit Hinweis", "caution"),
    ItemStatus.FAILED: ("Fehler", "critical"),
    ItemStatus.SKIPPED: ("Übersprungen", "neutral"),
}
FAILED_LABELS = {"file_missing": "Datei nicht gefunden", "no_active": "Keine aktiven Verträge", "unreadable": "Excel nicht lesbar", "columns_missing": "Spalten fehlen"}
SOURCE_TEXT = {
    resolver.SOURCE_ITEM: "eigene Angabe",
    resolver.SOURCE_CUSTOMER: "aus der Kundenakte",
    resolver.SOURCE_EXCEL: "aus der Excel",
    resolver.SOURCE_BATCH: "Stapel-Einstellung",
    resolver.SOURCE_DEFAULT: "Standard",
    resolver.SOURCE_DEFAULT_TEMPLATE: "Standardvorlage",
}
RULE_SET_AUTO = "Automatisch"
RULE_SET_NONE = "Kein Regelwerk"
HINT = "Strg+Enter  Bereite Übersichten erstellen   ·   Strg+O  Excel-Dateien hinzufügen   ·   Leertaste  auswählen"
HELP_STEPS = (
    "Excel-Dateien hinzufügen (Strg+O), einen Ordner hinzufügen oder mehrere Dateien in das Fenster ziehen – jede Datei wird sofort geprüft.",
    "Bekannte Kunden werden am Rechnungsempfänger erkannt. Bei »Angaben erforderlich« den Eintrag öffnen und Firmenname und Kundennummer eintragen oder einen Kunden auswählen.",
    "Zielordner, Vorlage des Stapels und den Umgang mit vorhandenen PDFs unter »Ausgabe und Standards« festlegen.",
    "Auf »Bereite Übersichten erstellen« klicken oder Strg+Enter drücken – erstellt werden nur bereite Einträge.",
    "Im Ergebnis den Ausgabeordner öffnen; fehlgeschlagene Einträge lassen sich erneut versuchen.",
)
HELP_NOTES = (
    "Vorrang für Vorlage und Logo: im Eintrag gewählt → Kundenakte → Standard des Stapels → globaler Standard.",
    "Vorhandene PDFs werden standardmäßig nicht überschrieben, sondern nummeriert (…_2.pdf).",
    "Neue E-Mail-Zuordnungen entstehen nur mit »Zuordnung merken«.",
    "»Stapel abbrechen« beendet die laufende PDF sauber; fertige PDFs bleiben erhalten.",
    "Alles bleibt lokal auf diesem PC. Gespeichert werden nur Pfade und Ihre Angaben, keine Kopien der Excel-Dateien.",
)
# Ohne Kundenakte: Angaben kommen aus der Excel bzw. werden im Eintrag eingetragen
HELP_STEPS_PLAIN = (
    HELP_STEPS[0],
    "Bei »Angaben erforderlich« den Eintrag öffnen und Firmenname und Kundennummer eintragen (sofern nicht in der Excel).",
    *HELP_STEPS[2:],
)
HELP_NOTES_PLAIN = (
    "Vorrang für Vorlage und Logo: im Eintrag gewählt → Standard des Stapels → globaler Standard.",
    HELP_NOTES[1],
    HELP_NOTES[3],
    HELP_NOTES[4],
    "Kundenakten (Wiedererkennung bekannter Rechnungsempfänger) lassen sich unter »Einstellungen« → »Vertragsübersichten« einschalten.",
)


def status_label(item: BatchItem) -> tuple[str, str]:
    label, tone = STATUS[item.status]
    if item.status is ItemStatus.FAILED and not item.error:
        code = next((issue.code for issue in item.issues if issue.code in FAILED_LABELS), "")
        label = FAILED_LABELS.get(code, label)
    return label, tone


def facts_line(item: BatchItem, changes: str = "") -> str:
    """Kompakt und ohne Doppelungen: »5 aktive · 3 inaktiv ausgeblendet · rechnung@kunde.de«."""
    analysis = item.analysis
    if analysis is None or not analysis.ok:
        return ""
    if analysis.active:
        parts = [contract_summary(analysis.active, analysis.inactive, short=True)]
    else:
        parts = [f"{analysis.inactive} inaktiv ausgeblendet"] if analysis.inactive else []  # »Keine aktiven Verträge« steht als Status
    if len(analysis.emails) == 1:
        parts.append(analysis.emails[0])
    elif len(analysis.emails) > 1:
        parts.append(f"{len(analysis.emails)} Rechnungsempfänger")
    if changes:
        parts.append(changes)
    return " · ".join(parts)


def short_error(text: str) -> str:
    """Für die Liste: ohne technische Einzelheiten in Klammern (vollständig im Eintrag)."""
    head = text.split(" (", 1)[0].strip()
    return head if head.endswith(".") or not head else head + "."


def detail_line(item: BatchItem, res) -> tuple[str, str]:
    status = item.status
    if status is ItemStatus.PROCESSING:
        return "Wird erstellt …", "accent"
    if status in CREATED:
        text = f"Erstellt: {Path(item.output).name}"
        if status is ItemStatus.WARNING and item.notes:
            return f"{text} · {item.notes[0]}", "caution"
        return text, "success"
    if status is ItemStatus.SKIPPED:
        return (item.notes[0] if item.notes else "Übersprungen"), "muted"
    if status is ItemStatus.FAILED:
        if item.error:
            return item.error, "critical"
        code = next((issue.code for issue in item.issues if issue.code in FAILED_LABELS), "")
        if code in ("no_active", "file_missing"):
            return "", "muted"  # steht schon als Status
        if item.analysis is not None and not item.analysis.ok and item.analysis.error:
            return short_error(item.analysis.error), "critical"
        return (item.issues[0].text if item.issues else "Fehler"), "critical"
    if res is None or status in (ItemStatus.PENDING, ItemStatus.ANALYZING):
        return "", "muted"
    if status is ItemStatus.NEEDS_INPUT:
        missing = [issue.text for issue in res.issues if issue.area != "kunde"]
        return " · ".join([res.customer_line, *missing]), "caution"
    note = f" · {item.notes[0]}" if item.notes else ""
    return res.customer_line + note, "muted"


def _caption(path: str, empty: str) -> tuple[str, str]:
    if not path:
        return empty, ""
    p = Path(path)
    parent = p.parent.name or str(p.parent)
    if p.suffix:
        return f"{p.name}  ·  {parent}", str(p)
    return (p.name or str(p)), str(p)


class BatchController(Observable):
    """Stapel: Liste, Filter, Auswahl, Erstellung, Ergebnis und Detailansicht eines Eintrags."""

    # Liste
    hasItemsChanged, hasItems = prop(bool, "hasItems", False)
    filterChanged, filter = prop(str, "filter", "all")
    countsChanged, counts = prop(dict, "counts", {})
    summaryKindChanged, summaryKind = prop(str, "summaryKind", "neutral")
    summaryTextChanged, summaryText = prop(str, "summaryText", "")
    runningChanged, running = prop(bool, "running", False)
    progressChanged, progress = prop(float, "progress", 0.0)
    progressErrorChanged, progressError = prop(bool, "progressError", False)
    progressTextChanged, progressText = prop(str, "progressText", "")
    currentTextChanged, currentText = prop(str, "currentText", "")
    canCancelChanged, canCancel = prop(bool, "canCancel", False)
    canRunChanged, canRun = prop(bool, "canRun", False)
    canRetryChanged, canRetry = prop(bool, "canRetry", False)
    resultChanged, result = prop(dict, "result", {})
    newVisibleChanged, newVisible = prop(bool, "newVisible", False)
    checkAllChanged, checkAll = prop(int, "checkAll", 0)  # 0 keiner, 1 teilweise, 2 alle
    selectedTextChanged, selectedText = prop(str, "selectedText", "")
    selectionChanged, selection = prop(int, "selection", 0)
    visibleCountChanged, visibleCount = prop(int, "visibleCount", 0)
    filterEmptyChanged, filterEmpty = prop(str, "filterEmpty", "")
    customerPartsChanged, customerParts = prop(bool, "customerParts", False)
    # Ausgabe und Standards
    targetTextChanged, targetText = prop(str, "targetText", "")
    targetPathChanged, targetPath = prop(str, "targetPath", "")
    logoTextChanged, logoText = prop(str, "logoText", "")
    logoPathChanged, logoPath = prop(str, "logoPath", "")
    templateChoicesChanged, templateChoices = prop(list, "templateChoices", [])
    templateValueChanged, templateValue = prop(str, "templateValue", TEMPLATE_NONE)
    conflictValueChanged, conflictValue = prop(str, "conflictValue", "")
    subfoldersChanged, subfolders = prop(bool, "subfolders", False)
    customerTargetChanged, customerTarget = prop(bool, "customerTarget", False)
    # Detailansicht
    detailIdChanged, detailId = prop(str, "detailId", "")
    positionChanged, position = prop(str, "position", "")
    canPrevChanged, canPrev = prop(bool, "canPrev", False)
    canNextChanged, canNext = prop(bool, "canNext", False)
    detailTitleChanged, detailTitle = prop(str, "detailTitle", "")
    detailFolderChanged, detailFolder = prop(str, "detailFolder", "")
    detailKindChanged, detailKind = prop(str, "detailKind", "neutral")
    detailTextChanged, detailText = prop(str, "detailText", "")
    excelFactsChanged, excelFacts = prop(list, "excelFacts", [])
    mailValueChanged, mailValue = prop(str, "mailValue", "")
    mailChoicesChanged, mailChoices = prop(list, "mailChoices", [])
    mailChoiceChanged, mailChoice = prop(str, "mailChoice", "")
    mailFieldChanged, mailField = prop(bool, "mailField", False)
    companyChanged, company = prop(str, "company", "")
    numberChanged, number = prop(str, "number", "")
    emailChanged, email = prop(str, "email", "")
    companyErrorChanged, companyError = prop(bool, "companyError", False)
    numberErrorChanged, numberError = prop(bool, "numberError", False)
    valueSourceChanged, valueSource = prop(str, "valueSource", "")
    customerTitleChanged, customerTitle = prop(str, "customerTitle", "")
    customerNoteChanged, customerNote = prop(str, "customerNote", "")
    customerModeChanged, customerMode = prop(str, "customerMode", "auto")
    itemRunningChanged, itemRunning = prop(bool, "itemRunning", False)
    itemTemplateChoicesChanged, itemTemplateChoices = prop(list, "itemTemplateChoices", [])
    itemRuleSetChoicesChanged, itemRuleSetChoices = prop(list, "itemRuleSetChoices", [])
    itemRuleSetChanged, itemRuleSet = prop(str, "itemRuleSet", RULE_SET_AUTO)
    itemTemplateChanged, itemTemplate = prop(str, "itemTemplate", TEMPLATE_AUTO)
    templateNoteChanged, templateNote = prop(str, "templateNote", "")
    itemLogoTextChanged, itemLogoText = prop(str, "itemLogoText", "")
    itemLogoPathChanged, itemLogoPath = prop(str, "itemLogoPath", "")
    itemLogoResetChanged, itemLogoReset = prop(bool, "itemLogoReset", False)
    itemTargetTextChanged, itemTargetText = prop(str, "itemTargetText", "")
    itemTargetPathChanged, itemTargetPath = prop(str, "itemTargetPath", "")
    itemTargetResetChanged, itemTargetReset = prop(bool, "itemTargetReset", False)
    outputTextChanged, outputText = prop(str, "outputText", "")
    canPreviewChanged, canPreview = prop(bool, "canPreview", False)
    hasOutputChanged, hasOutput = prop(bool, "hasOutput", False)

    focusRequested = Signal(str)

    def __init__(self, app, tool, cfg: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.c = None
        default_target = cfg.get("zielordner") if isinstance(cfg.get("zielordner"), str) and cfg.get("zielordner") else str(desktop_dir())
        self.settings = BatchSettings.from_config(cfg, default_target=default_target)
        self.items: list[BatchItem] = []
        self.by_id: dict[str, BatchItem] = {}
        self.cache = AnalysisCache()
        self.analyzer: Analyzer | None = None
        self.runner: BatchRunner | None = None
        self.summary: RunSummary | None = None  # Ergebnis des letzten Durchlaufs
        self.resolutions: dict[str, resolver.Resolution] = {}
        self.log = BatchLog(DATA_DIR)
        self._touched: dict[str, str] = {}  # Eintrag → Kundenakte der laufenden Erstellung
        self._cancelled: set[str] = set()  # beim Abbruch sauber beendete Einträge
        self._retry_after_check: set[str] = set()
        self._removed: list[tuple[int, BatchItem]] | None = None
        self._restore = self._load_queue()
        self._loading = False
        self._closing = False
        self._focused: set[str] = set()  # Eingabefelder der Detailansicht mit Tastaturfokus
        self.model = KeyedListModel(("name", "facts", "detail", "detailTone", "status", "statusTone", "statusKey", "selected"), key="id", parent=self)
        self.detail = ComparisonView(lambda snapshot_id: self._choose_baseline(snapshot_id), self._copy_comparison, self)
        for name in ("company", "number", "email"):
            self.observe(name, lambda _v: self._schedule_edit())

    def attach(self, overview) -> None:
        self.c = overview

    def start(self) -> None:
        self.analyzer = Analyzer(self.cache, lambda func: self.app.worker.run(func), self.app.worker.post, self._analyzed)
        restored, self._restore = self._restore, []
        self.customerParts = self.tool.customers.enabled
        if restored:
            self._insert(restored)
        self._changed(structure=True)

    def config(self) -> dict:
        return self.settings.to_config()

    @property
    def running_now(self) -> bool:
        return self.runner is not None and not self.runner.finished

    def item(self, item_id: str | None) -> BatchItem | None:
        return self.by_id.get(item_id) if item_id else None

    # Für QML ---------------------------------------------------------------------------------
    def _filters(self) -> list[dict]:
        return [{"key": key, "label": FILTER_LABELS[key]} for key in FILTERS]

    def _conflicts(self) -> list[dict]:
        return [{"value": mode.value, "label": CONFLICT_LABELS[mode]} for mode in ConflictMode]

    def _texts(self) -> dict:
        return {
            "subtitle": SUBTITLE,
            "emptyTitle": EMPTY_TITLE,
            "emptyText": EMPTY_TEXT,
            "emptyHint": EMPTY_HINT,
            "emptyHintPlain": EMPTY_HINT_PLAIN,
            "settingsText": SETTINGS_TEXT,
            "settingsTextPlain": SETTINGS_TEXT_PLAIN,
            "outputText": OUTPUT_TEXT,
            "outputTextPlain": OUTPUT_TEXT_PLAIN,
            "privacy": PRIVACY,
            "run": RUN_TEXT,
        }

    def _model_obj(self) -> QObject:
        return self.model

    def _detail_obj(self) -> QObject:
        return self.detail

    _constant = Signal()
    filters = Property(list, _filters, notify=_constant)
    conflictChoices = Property(list, _conflicts, notify=_constant)
    texts = Property("QVariantMap", _texts, notify=_constant)
    listModel = Property(QObject, _model_obj, notify=_constant)
    comparison = Property(QObject, _detail_obj, notify=_constant)

    # Hinzufügen -------------------------------------------------------------------------------
    @Slot()
    def pickFiles(self) -> None:  # noqa: N802
        paths = files.open_files("Excel-Dateien für den Stapel wählen", self.app.initial_dir("excel", ""), files.EXCEL_FILTER)
        if paths:
            self.app.remember_dir("excel", paths[0])
            self.add(list(paths))

    @Slot()
    def pickFolder(self) -> None:  # noqa: N802
        folder = files.pick_folder("Ordner mit Excel-Dateien wählen", self.app.initial_dir("excel", ""))
        if folder:
            self.add([folder])

    def add(self, paths: list[str]) -> tuple[int, int, int]:
        """Dateien und Ordner (nicht rekursiv) hinzufügen. Rückgabe: (neu, doppelt, ignoriert)."""
        found_files: list[str] = []
        ignored = 0
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                try:
                    found = sorted((str(child) for child in path.iterdir() if child.is_file() and is_excel(child) and not child.name.startswith("~$")), key=str.casefold)
                except OSError:
                    found = []
                found_files += found
            elif is_excel(path):
                found_files.append(str(path))
            else:
                ignored += 1
        known = {item.key for item in self.items}
        fresh: list[BatchItem] = []
        duplicates = 0
        for path in found_files:
            key = path_key(path)
            if key in known:
                duplicates += 1
                continue
            known.add(key)
            fresh.append(BatchItem(os.path.abspath(path)))
        self._insert(fresh)
        parts = []
        if fresh:
            parts.append("1 Excel-Datei hinzugefügt" if len(fresh) == 1 else f"{len(fresh)} Excel-Dateien hinzugefügt")
        if duplicates:
            parts.append("1 war schon im Stapel" if duplicates == 1 else f"{duplicates} waren schon im Stapel")
        if ignored:
            parts.append("1 Datei ist keine Excel-Datei und wurde nicht übernommen" if ignored == 1 else f"{ignored} Dateien sind keine Excel-Dateien und wurden nicht übernommen")
        if not found_files and not ignored:
            parts.append("Keine Excel-Dateien gefunden")
        if parts:
            severity = "success" if fresh and not ignored else ("warning" if ignored or not fresh else "info")
            self.app.notify("batch_info", severity, " · ".join(parts) + ".", auto_hide=8000 if severity == "success" else None)
        return len(fresh), duplicates, ignored

    def accepts(self, dropped: list[str]) -> bool:
        return bool(excel_files(dropped)) or any(Path(path).is_dir() for path in dropped)

    def drag_enter(self, accepted: bool) -> None:
        if accepted:
            self.app.notify("batch_info", "info", "Loslassen, um die Excel-Dateien zum Stapel hinzuzufügen.", status=False, animate=False)

    def drag_leave(self) -> None:
        notice = self.app.notices.get("batch_info")
        if notice.message.startswith("Loslassen"):
            self.app.hide_notice("batch_info")

    def drop(self, dropped: list[str]) -> None:
        """Mehrere Dateien auf die Ansicht »Stapel« gezogen: alle Excel-Dateien (und Ordner) übernehmen."""
        self.drag_leave()
        if not any(is_excel(path) or Path(path).is_dir() for path in dropped):
            self.app.notify("batch_info", "warning", "Bitte Excel-Dateien (.xlsx oder .xls) oder einen Ordner mit Excel-Dateien in das Fenster ziehen.")
            return
        self.add(dropped)

    def _insert(self, items: list[BatchItem]) -> None:
        if not items:
            return
        for item in items:
            self.items.append(item)
            self.by_id[item.id] = item
        waiting = []
        for item in items:
            if item.status in DONE:
                continue  # schon erstellt (aus der Sicherung): nicht erneut prüfen, bis er geändert wird
            item.status = ItemStatus.ANALYZING
            waiting.append((item.id, item.path))
        self.summary = None
        self._changed(structure=True)
        self._save_soon()
        if waiting and self.analyzer is not None:
            # Erst die neuen Zeilen zeigen, dann prüfen: So konkurriert die Prüfung nicht mit dem Aufbau der Liste.
            self.app.timers.later(f"batch:submit:{id(items)}", 0, lambda: self._submit(waiting))

    def _submit(self, entries: list[tuple[str, str]]) -> None:
        entries = [(item_id, path) for item_id, path in entries if item_id in self.by_id]
        if entries and self.analyzer is not None:
            self.analyzer.submit(entries)

    # Prüfung ---------------------------------------------------------------------------------------
    def _analyzed(self, results) -> None:
        """Ergebnisse der Voranalyse (gebündelt, im GUI-Thread)."""
        for item_id, analysis, stamp in results:
            item = self.by_id.get(item_id)
            if item is None:
                continue  # inzwischen entfernt
            item.analysis, item.stamp = analysis, stamp
            if item.status is ItemStatus.ANALYZING:
                item.status = ItemStatus.PENDING
            self._update(item)
        self._changed()
        self._retry_checked()

    def _retry_checked(self) -> None:
        """Nach »erneut versuchen« neu geprüfte Dateien: bereite direkt erstellen."""
        waiting = self._retry_after_check
        if not waiting or self.running_now:
            return
        pending = [i for i in waiting if i in self.by_id and self.by_id[i].status in WAITING]
        if pending:
            return  # erst, wenn alle geprüft sind
        ready = [i for i in waiting if i in self.by_id and self.by_id[i].status is ItemStatus.READY]
        self._retry_after_check = set()
        if ready:
            self.start_run([item.id for item in self.items if item.id in set(ready)], label="Erneuter Versuch")

    def recheck(self, item: BatchItem) -> None:
        """Eine Datei erneut prüfen (z. B. »erneut versuchen« nach einem Datei-Problem)."""
        self.cache.forget(item.path)
        item.analysis, item.stamp = None, None
        item.status = ItemStatus.ANALYZING
        if self.analyzer is not None:
            self.analyzer.submit([(item.id, item.path)])

    # Werte und Status --------------------------------------------------------------------------------
    def defaults(self) -> resolver.Defaults:
        """Globaler Standard aus »Darstellung« – ohne Texte einer gerade aktiven Kundenakte."""
        c = self.c
        header, footer = c.header_rich(), c.footer_rich()
        customers = self.tool.customers
        if customers._customer_texts and customers._base_texts is not None:
            header, footer = customers._base_texts
        return resolver.Defaults(
            dateiname=c.dateiname.strip(),
            seitenformat=c.format,
            logo_breite=c.breite.strip(),
            titel=c.titel.strip(),
            untertitel=c.untertitel.strip(),
            header=header,
            footer=footer,
            regeln=tuple(dict(regel) for regel in self.app.state.regeln),
            logo=str(DEFAULT_LOGO),
            regelwerk=c.rule_set_dict(),
            regelwerk_name=c.ruleSetLabel,
            vorlage_standard=c.defaultTemplate,
        )

    def resolve(self, item: BatchItem, for_preview: bool = False) -> resolver.Resolution:
        customers = self.tool.customers.customers if self.tool.customers.enabled else None
        return resolver.resolve(item, customers, self.app.state.find_vorlage, self.settings, self.defaults(), for_preview=for_preview, find_rule_set=self.find_rule_set)

    def find_rule_set(self, ref: str) -> dict | None:
        store = self.app.state.rule_sets
        rule_set = store.get(ref) if store is not None else None
        if rule_set is None and store is not None:
            rule_set = store.by_name(ref)
        return rule_set.to_dict() if rule_set is not None else None

    def _update(self, item: BatchItem) -> resolver.Resolution:
        """Werte und Status eines Eintrags neu bestimmen (ein erstelltes Ergebnis bleibt)."""
        res = self.resolve(item)
        self.resolutions[item.id] = res
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

    def refresh_all(self) -> None:
        """Nach Änderungen an Kundenakten, Vorlagen, Darstellung oder Stapel-Einstellungen."""
        for item in self.items:
            self._update(item)
        self._changed()

    def customers_changed(self) -> None:
        customers = self.tool.customers
        self.customerParts = customers.enabled
        if customers.enabled:
            for item in self.items:
                if item.customer_mode is CustomerMode.MANUAL and customers.customers.get(item.customer_id) is None:
                    item.customer_mode, item.customer_id = CustomerMode.AUTO, None  # gelöschte Kundenakte
        self.refresh_all()

    def inherited(self, item_id: str) -> dict[str, str]:
        """Werte, die ohne eigene Angabe gälten (Kundenakte bzw. Excel) – für »zurück auf übernommen«."""
        item = self.by_id.get(item_id)
        if item is None:
            return {}
        probe = replace(item, overrides=replace(item.overrides, company=None, number=None, email=None))
        res = self.resolve(probe)
        return {"company": res.company, "number": res.number, "email": res.email if not res.emails else ""}

    def mark_stale(self) -> None:
        """Darstellung, Vorlagen o. Ä. geändert: Werte der Einträge neu bestimmen – gesammelt."""
        if not self.items:
            return
        self.app.timers.later("batch:stale", 300, self.refresh_all)

    def resolution(self, item_id: str) -> resolver.Resolution | None:
        item = self.by_id.get(item_id)
        if item is None:
            return None
        res = self.resolutions.get(item_id)
        return res if res is not None else self._update(item)

    def count_items(self) -> dict[str, int]:
        counts = {key: 0 for key in FILTERS}
        for item in self.items:
            counts["all"] += 1
            for key, statuses in FILTER_STATUSES.items():
                if statuses is not None and item.status in statuses:
                    counts[key] += 1
        return counts

    def visible_items(self) -> list[BatchItem]:
        statuses = FILTER_STATUSES.get(self.filter)
        if statuses is None:
            return list(self.items)
        return [item for item in self.items if item.status in statuses]

    @Slot(str)
    def setFilter(self, key: str) -> None:  # noqa: N802
        if key in FILTERS and key != self.filter:
            self.filter = key
            self._changed(structure=True)

    # Bearbeiten --------------------------------------------------------------------------------------------
    def edit(self, item_id: str, **overrides) -> None:
        """Eigene Angaben im Eintrag setzen (``None`` = wieder übernehmen)."""
        item = self.by_id.get(item_id)
        if item is None or item.status is ItemStatus.PROCESSING:
            return
        changed = False
        for key, value in overrides.items():
            if getattr(item.overrides, key) != value:
                setattr(item.overrides, key, value)
                changed = True
        if changed:
            self._modified(item)

    def _modified(self, item: BatchItem) -> None:
        """Ein Eintrag wurde geändert: ein früheres Ergebnis verfällt, der Status wird neu bestimmt."""
        if not self.running_now:
            self.summary = None  # das Ergebnis beschreibt den letzten Lauf, nicht mehr den Stapel
        if item.done or (item.status is ItemStatus.FAILED and item.error):
            item.reset_result()
        if item.analysis is None and item.status is not ItemStatus.ANALYZING:
            self.recheck(item)  # z. B. aus der Sicherung wiederhergestellt: erst prüfen
        self._update(item)
        self._changed(item_ids=(item.id,))
        self._save_soon()
        preview = self.tool.preview
        if preview is not None and preview._item == item.id:
            preview.mark_dirty()

    @Slot()
    def chooseCustomer(self) -> None:  # noqa: N802
        if self.detailId:
            self.choose_customer(self.detailId)

    def choose_customer(self, item_id: str) -> None:
        customers = self.tool.customers
        item = self.by_id.get(item_id)
        if item is None or not customers.enabled:
            return
        if not len(customers.customers):
            self.app.notify("batch_detail_info", "info", "Noch keine Kundenakten gespeichert. Kundenakten entstehen in »Übersicht erstellen« oder in der Ansicht »Kunden«.", auto_hide=10000, status=False)
            return
        res = self.resolution(item_id)
        candidates = None
        message = None
        if res is not None and res.match is not None and res.match.kind.value in ("conflicting_matches", "ambiguous_match"):
            candidates = list(res.match.customer_ids)
            message = "Die Rechnungsempfänger dieser Excel gehören zu mehreren Kundenakten. Welcher Kunde ist gemeint?"
        chosen = customers.choose_customer(candidates=candidates, message=message)
        if chosen:
            self.set_customer(item_id, CustomerMode.MANUAL, chosen)

    @Slot(str)
    def setCustomerMode(self, mode: str) -> None:  # noqa: N802
        if self.detailId and mode in ("auto", "none"):
            self.set_customer(self.detailId, CustomerMode.AUTO if mode == "auto" else CustomerMode.NONE)

    def set_customer(self, item_id: str, mode: CustomerMode, customer_id: str | None = None) -> None:
        item = self.by_id.get(item_id)
        if item is None or item.status is ItemStatus.PROCESSING:
            return
        item.customer_mode = mode
        item.customer_id = customer_id if mode is CustomerMode.MANUAL else None
        self._modified(item)

    def remember_emails(self, item_id: str) -> None:
        """»Zuordnung merken«: unbekannte Adressen dieser Excel künftig dem Kunden des Eintrags zuordnen."""
        res = self.resolution(item_id)
        if res is None or res.customer is None or not res.unknown_emails:
            return
        self.tool.customers.assign_emails(res.customer.id, list(res.unknown_emails))  # dieselbe Logik wie im Einzelmodus

    def decline_emails(self, item_id: str) -> None:
        res = self.resolution(item_id)
        if res is None or res.customer is None:
            return
        self.tool.customers._declined_emails.update((res.customer.id, email) for email in res.unknown_emails)
        self._changed(item_ids=(item_id,))

    def offer_emails(self, item_id: str) -> tuple[str, ...]:
        """Adressen, deren Zuordnung zum Kunden des Eintrags angeboten wird (nicht abgelehnte)."""
        res = self.resolution(item_id)
        if res is None or res.customer is None:
            return ()
        declined = self.tool.customers._declined_emails
        return tuple(email for email in res.unknown_emails if (res.customer.id, email) not in declined)

    # Auswahl und Massenaktionen ---------------------------------------------------------------------------------
    @Slot(str, bool)
    def select(self, item_id: str, selected: bool) -> None:
        item = self.by_id.get(item_id)
        if item is not None and item.selected != bool(selected):
            item.selected = bool(selected)
            self._changed(item_ids=(item_id,))

    @Slot(str)
    def toggleSelected(self, item_id: str) -> None:  # noqa: N802
        item = self.by_id.get(item_id)
        if item is not None:
            self.select(item_id, not item.selected)

    @Slot()
    def toggleAll(self) -> None:  # noqa: N802
        visible = self.visible_items()
        self.select_all(not (visible and all(item.selected for item in visible)))

    def select_all(self, selected: bool) -> None:
        for item in self.visible_items():
            item.selected = selected
        self._changed()

    def selected_items(self) -> list[BatchItem]:
        return [item for item in self.items if item.selected]

    def remove(self, item_ids: list[str]) -> None:
        """Einträge aus dem Stapel nehmen (rückgängig machbar). Dateien bleiben unberührt."""
        if self.running_now:
            return
        wanted = set(item_ids)
        removed = [(index, item) for index, item in enumerate(self.items) if item.id in wanted]
        if not removed:
            return
        for _index, item in removed:
            self.items.remove(item)
            self.by_id.pop(item.id, None)
            self.resolutions.pop(item.id, None)
        self._removed = removed
        self.summary = None
        self._changed(structure=True)
        self._save_soon()
        text = f"„{removed[0][1].name}“ aus dem Stapel entfernt." if len(removed) == 1 else f"{len(removed)} Einträge aus dem Stapel entfernt."
        self.app.notify("batch_info", "info", text + " Die Dateien selbst bleiben unverändert.", actions=(("Rückgängig", self._undo_remove),), auto_hide=10000)

    @Slot()
    def removeSelected(self) -> None:  # noqa: N802
        self.remove([item.id for item in self.selected_items()])

    def _undo_remove(self) -> None:
        removed, self._removed = self._removed, None
        if not removed:
            return
        for index, item in removed:
            if item.id not in self.by_id:
                self.items.insert(min(index, len(self.items)), item)
                self.by_id[item.id] = item
                self._update(item)
        self.app.hide_notice("batch_info")
        self._changed(structure=True)
        self._save_soon()

    def apply_template(self, name: str | None, item_ids: list[str] | None = None) -> int:
        """Vorlage für mehrere Einträge setzen (``None`` = wieder automatisch, ``""`` = keine Vorlage)."""
        targets = [self.by_id[i] for i in item_ids if i in self.by_id] if item_ids is not None else self.selected_items()
        count = 0
        for item in targets:
            if item.status is ItemStatus.PROCESSING or item.overrides.template == name:
                continue
            item.overrides.template = name
            if item.done or (item.status is ItemStatus.FAILED and item.error):
                item.reset_result()
            if item.analysis is None and item.status is not ItemStatus.ANALYZING:
                self.recheck(item)
            self._update(item)
            count += 1
        if count:
            self._changed()
            self._save_soon()
        return count

    @Slot()
    def applyTemplateToSelection(self) -> None:  # noqa: N802
        selected = self.selected_items()
        if not selected:
            return
        names = self.template_names()
        options = [TEMPLATE_AUTO, TEMPLATE_NONE, *names]
        count = len(selected)
        answer, result = self.app.dialogs.ask(
            "choose_template",
            "Vorlage anwenden",
            f"Vorlage für {count} ausgewählte {'Eintrag' if count == 1 else 'Einträge'}:",
            primary="Anwenden",
            close="Abbrechen",
            data={"options": options, "value": names[0] if names else TEMPLATE_AUTO},
            width=480,
        )
        if answer != dialog_service.PRIMARY:
            return
        value = str(result.get("value") or (names[0] if names else TEMPLATE_AUTO))
        choice = None if value == TEMPLATE_AUTO else ("" if value == TEMPLATE_NONE else self.template_ref(value))
        applied = self.apply_template(choice)
        label = "automatisch (Kundenakte, Stapel bzw. Standardvorlage)" if choice is None else ("keine Vorlage" if choice == "" else f"„{value}“")
        self.app.notify("batch_info", "success", f"Vorlage {label} für {applied} {'Eintrag' if applied == 1 else 'Einträge'} gesetzt.", auto_hide=6000)

    def template_names(self) -> list[str]:
        return sorted((str(entry.get("name", "")) for entry in self.app.state.vorlagen if entry.get("name")), key=str.casefold)

    def template_ref(self, label: str) -> str:
        """Anzeige (Name) → gespeicherter Verweis (ab 2.8 die ID der Vorlage)."""
        entry = self.app.state.find_vorlage(label)
        return str(entry.get("id") or label) if entry else label

    def template_name(self, ref: str | None) -> str:
        if not ref:
            return ""
        entry = self.app.state.find_vorlage(ref)
        return str(entry.get("name", "")) if entry else ("gelöschte Vorlage" if not resolver.ref_label(ref) else ref)

    def template_refs(self, template_id: str, name: str) -> int:
        """Wie oft der Stapel diese Vorlage verwendet (Vorlage des Stapels, Einträge)."""
        refs = (template_id, name)
        return int(self.settings.template in refs) + sum(1 for item in self.items if item.overrides.template in refs)

    def retarget_template(self, template_id: str, name: str, new_ref: str | None) -> None:
        """Verweise ändern: ``new_ref`` = ID (nach Umbenennen) oder ``None`` (gelöscht: automatisch)."""
        refs = (template_id, name)
        changed = False
        if self.settings.template in refs:
            self.settings.template = new_ref or ""
            changed = True
        for item in self.items:
            if item.overrides.template in refs and item.overrides.template != new_ref:
                item.overrides.template = new_ref
                changed = True
        if changed:
            self.app.schedule_save()
            self._save_soon()

    def rule_set_refs(self, rule_set_id: str) -> int:
        """Wie viele Einträge dieses Regelwerk bewusst gewählt haben."""
        return sum(1 for item in self.items if rule_set_id and item.overrides.rule_set == rule_set_id)

    def retarget_rule_set(self, rule_set_id: str) -> None:
        """Gelöschtes Regelwerk: Einträge, die es bewusst gewählt hatten, wieder »automatisch«."""
        changed = False
        for item in self.items:
            if item.overrides.rule_set == rule_set_id:
                item.overrides.rule_set = None
                changed = True
        if changed:
            self._save_soon()
            self.mark_stale()

    def templates_changed(self) -> None:
        """Vorlagen oder Standardvorlage geändert: Auswahllisten und Werte der Einträge neu bestimmen."""
        self._refresh_settings()
        if self.detailId and self.detailId in self.by_id:
            self.refresh_detail(load_fields=False)
        self.mark_stale()

    def rule_set_names(self) -> list[tuple[str, str]]:
        store = self.app.state.rule_sets
        return [(rule_set.id, rule_set.name) for rule_set in store.rule_sets()] if store is not None else []

    def apply_rule_set(self, ref: str | None, item_ids: list[str]) -> int:
        """Regelwerk für Einträge setzen (``None`` = automatisch, ``""`` = keines)."""
        count = 0
        for item in (self.by_id[i] for i in item_ids if i in self.by_id):
            if item.status is ItemStatus.PROCESSING or item.overrides.rule_set == ref:
                continue
            item.overrides.rule_set = ref
            if item.done or (item.status is ItemStatus.FAILED and item.error):
                item.reset_result()
            self._update(item)
            count += 1
        if count:
            self._changed()
            self._save_soon()
        return count

    # Einstellungen des Stapels ---------------------------------------------------------------------------------------
    def update_settings(self, **values) -> None:
        changed = False
        for key, value in values.items():
            if getattr(self.settings, key) != value:
                setattr(self.settings, key, value)
                changed = True
        if changed:
            self.app.schedule_save()
            self.refresh_all()

    @Slot()
    def pickTarget(self) -> None:  # noqa: N802
        path = files.pick_folder("Zielordner für den Stapel", self.app.initial_dir("ziel", self.settings.target_dir))
        if path:
            self.update_settings(target_dir=path)

    @Slot()
    def pickLogo(self) -> None:  # noqa: N802
        path = files.open_file("Standardlogo für den Stapel", self.app.initial_dir("logo", self.settings.logo), files.IMAGE_FILTER)
        if path:
            self.app.remember_dir("logo", path)
            self.update_settings(logo=path)

    @Slot()
    def resetLogo(self) -> None:  # noqa: N802
        self.update_settings(logo="")

    @Slot(str)
    def setDefaultTemplate(self, label: str) -> None:  # noqa: N802
        self.update_settings(template="" if label == TEMPLATE_NONE else self.template_ref(label))

    @Slot(str)
    def setConflict(self, value: str) -> None:  # noqa: N802
        mode = next((mode for mode in ConflictMode if mode.value == value), ConflictMode.NUMBER)
        self.update_settings(conflict=mode)

    @Slot(bool)
    def setSubfolders(self, value: bool) -> None:  # noqa: N802
        self.update_settings(subfolders=bool(value))

    @Slot(bool)
    def setCustomerTarget(self, value: bool) -> None:  # noqa: N802
        self.update_settings(customer_target=bool(value))

    # Verarbeitung ----------------------------------------------------------------------------------------------------------
    def ready_ids(self) -> list[str]:
        return [item.id for item in self.items if item.status is ItemStatus.READY]

    @Slot()
    def run(self) -> None:
        self.start_run()

    def start_run(self, item_ids: list[str] | None = None, label: str = "Stapel") -> None:
        """»Bereite Übersichten erstellen«: nur bereite Einträge, nacheinander, im Hintergrund."""
        if self.running_now:
            return
        ids = item_ids if item_ids is not None else self.ready_ids()
        if not ids:
            self.app.notify("batch_info", "info", "Kein Eintrag ist bereit. Einträge mit »Angaben erforderlich« zuerst vervollständigen.", auto_hide=8000)
            return
        self.flush()
        self.app.persist()
        self._touched = {}
        self._cancelled = set()
        self.summary = None
        # Nicht bereite Einträge gehören zum Ergebnis: »übersprungen« (Angaben fehlen) bzw. »fehlgeschlagen«.
        others = [item.id for item in self.items if item.id not in set(ids)] if item_ids is None else []
        self.log.write([f"{label} gestartet: {len(ids)} {'Eintrag' if len(ids) == 1 else 'Einträge'}"])
        run_ids = list(ids)
        self.runner = BatchRunner(
            ids,
            self._prepare,
            lambda func, on_done, on_error: self.app.worker.run(func, on_done, on_error),
            self._item_started,
            self._item_done,
            lambda summary, remaining: self._finished(summary, remaining, run_ids, others),
            run=lambda job, cancelled: processor.run_job(job, cancelled),
        )
        self._changed()
        self.runner.start()

    @Slot()
    def cancel(self) -> None:
        if self.running_now:
            self.runner.cancel()
            self._changed()

    @Slot()
    def retryFailed(self) -> None:  # noqa: N802
        """»Fehlgeschlagene erneut versuchen«: nur fehlgeschlagene Einträge; Datei-Probleme werden neu geprüft."""
        if self.running_now:
            return
        failed = [item for item in self.items if item.status is ItemStatus.FAILED]
        if not failed:
            return
        rerun: list[str] = []
        recheck: set[str] = set()
        for item in failed:
            file_problem = not item.error or any(issue.code in ("file_missing", "unreadable", "columns_missing", "no_active") for issue in item.issues)
            item.error = ""
            if file_problem:
                self.recheck(item)  # Datei-Problem: erst neu prüfen, dann (wenn bereit) erstellen
                recheck.add(item.id)
            else:
                item.status = ItemStatus.PENDING
                self._update(item)
                if item.status is ItemStatus.READY:
                    rerun.append(item.id)
        self._retry_after_check = recheck
        self._changed()
        if rerun:
            self.start_run(rerun, label="Erneuter Versuch")
        elif recheck:
            self.app.set_status("Fehlgeschlagene Dateien werden neu geprüft …", "busy")

    def _prepare(self, item_id: str, created: frozenset[str]) -> Job | None:
        """Unmittelbar vor der Erstellung: aktuelle Werte (Kundenakte, Vorlage, Einstellungen) laden."""
        item = self.by_id.get(item_id)
        if item is None or item.status is not ItemStatus.READY:
            return None
        res = self._update(item)
        if not res.ready or item.status is not ItemStatus.READY:
            return None
        item.status = ItemStatus.PROCESSING
        item.notes = ()
        if res.customer is not None:
            self._touched[item.id] = res.customer.id
        label = res.company or res.number or item.name
        return Job(item.id, label, item.path, item.stamp, identity_of(item.analysis), res.fields, res.folder, self.settings.conflict, created)

    def _item_started(self, item_id: str, job: Job) -> None:
        self._changed(item_ids=(item_id,))

    def _item_done(self, result: JobResult) -> None:
        item = self.by_id.get(result.item_id)
        customer_id = self._touched.pop(result.item_id, None)
        if item is None:
            return
        customers = self.tool.customers
        if result.cancelled:
            self._cancelled.add(item.id)
            item.status = ItemStatus.PENDING
            self._update(item)
        elif result.changed:
            item.analysis, item.stamp = result.analysis, result.stamp
            if result.analysis is not None and result.analysis.ok:
                self.cache.put(item.path, result.stamp, result.analysis)
            item.status = ItemStatus.PENDING
            item.notes = (result.error,)
            self._update(item)
        elif result.status in CREATED or result.status is ItemStatus.SKIPPED:
            item.status = result.status
            item.output = result.output
            item.notes = result.notes
            item.error = ""
            if result.status in CREATED and customer_id and customers.customers.get(customer_id) is not None:
                # nur Metadaten: zuletzt verwendet, letzte Excel, letzte PDF – nie Darstellungswerte
                customers.customers.touch(customer_id, excel=item.path, pdf=result.output)
                # Vertragsstand dieser PDF für den Vertragsvergleich (nur erfolgreich erstellte Einträge)
                customer = customers.customers.get(customer_id)
                self.tool.comparison.batch_after_item(item, customer_id, customer.label if customer is not None else "", result.contracts)
        else:
            item.status = ItemStatus.FAILED
            item.error = result.error or "Unbekannter Fehler"
            item.output = ""
            paths = [item.path, str(Path(item.path).parent)]
            self.log.write([redact(f"Fehler: {item.name}: {item.error}", paths)] + [redact(line, paths) for line in result.trace])
        self._changed(item_ids=(item.id,))
        self._save_soon()

    def _finished(self, summary: RunSummary, remaining: list[str], run_ids: list[str] | None = None, others: list[str] | None = None) -> None:
        for item_id in remaining:
            item = self.by_id.get(item_id)
            if item is not None and item.status is ItemStatus.PROCESSING:
                item.status = ItemStatus.PENDING
                self._update(item)
        # Das Ergebnis zählt nach dem tatsächlichen Status der Einträge – so passt es zur Liste.
        not_processed = set(remaining) | self._cancelled
        created = failed = skipped = 0
        for item_id in [*(run_ids or []), *(others or [])]:
            item = self.by_id.get(item_id)
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
        self.summary = summary
        self.tool.customers._store_customers()
        self.tool.customers.refresh()
        state = "abgebrochen" if summary.aborted else "beendet"
        self.log.write([f"Stapel {state}: {summary.created} erstellt, {summary.skipped} übersprungen, {summary.failed} fehlgeschlagen" + (f", {summary.cancelled} nicht verarbeitet" if summary.cancelled else "")])
        self._changed(structure=True)
        self._save_soon()
        self.app.set_status(self.summary_text(summary), "warning" if summary.failed or summary.aborted else "success")
        self._retry_checked()

    def summary_text(self, summary: RunSummary) -> str:
        parts = ["1 Übersicht erstellt" if summary.created == 1 else f"{summary.created} Übersichten erstellt"]
        if summary.skipped:
            parts.append(f"{summary.skipped} übersprungen")
        if summary.failed:
            parts.append(f"{summary.failed} fehlgeschlagen")
        if summary.cancelled:
            parts.append(f"{summary.cancelled} nicht verarbeitet")
        return ("Stapel abgebrochen: " if summary.aborted else "Stapel abgeschlossen: ") + " · ".join(parts)

    # Nach dem Durchlauf ----------------------------------------------------------------------------------------------------
    def output_folders(self) -> list[str]:
        folders: list[str] = []
        for item in self.items:
            if item.status in CREATED and item.output:
                folder = str(Path(item.output).parent)
                if folder not in folders:
                    folders.append(folder)
        return folders

    @Slot()
    def openOutput(self) -> None:  # noqa: N802
        """»Ausgabeordner öffnen«: der gemeinsame Ordner (bzw. der Zielordner des Stapels)."""
        folders = self.output_folders()
        target = folders[0] if len(folders) == 1 else self.settings.target_dir
        if len(folders) > 1:
            common = os.path.commonpath(folders) if all(Path(f).drive == Path(folders[0]).drive for f in folders) else ""
            target = common or self.settings.target_dir
        if not target or not Path(target).is_dir():
            self.app.notify("batch_info", "warning", "Der Ausgabeordner ist nicht vorhanden.")
            return
        try:
            files.open_path(target)
        except OSError as exc:
            self.app.notify("batch_info", "error", str(exc), title="Ordner konnte nicht geöffnet werden")

    @Slot()
    def showErrors(self) -> None:  # noqa: N802
        self.setFilter("failed")

    @Slot()
    def newBatch(self) -> None:  # noqa: N802
        """»Neuer Stapel«: Warteschlange leeren. Kundenakten, Vorlagen, Darstellung und Einstellungen bleiben."""
        if self.running_now:
            return
        open_items = [item for item in self.items if item.status not in DONE]
        if open_items and not self.app.dialogs.confirm(
            "Neuen Stapel beginnen?",
            f"{len(open_items)} {'Eintrag wurde' if len(open_items) == 1 else 'Einträge wurden'} noch nicht erstellt. Die Liste wird geleert – Excel-Dateien, erstellte PDFs, Kundenakten, Vorlagen und Einstellungen bleiben unverändert.",
            "Neuer Stapel",
            danger=False,
        ):
            return
        if self.analyzer is not None:
            self.analyzer.clear()
        for item in self.items:
            self.tool.comparison.forget_batch_item(item.id)
        self.items.clear()
        self.by_id.clear()
        self.resolutions.clear()
        self.summary = None
        self.filter = "all"
        self._removed = None
        self.detailId = ""
        self.app.hide_notice("batch_info")
        self._changed(structure=True)
        self._save_now()

    # Vorschau und Einzelmodus ----------------------------------------------------------------------------------------------------
    @Slot()
    def preview(self) -> None:
        """Vorschau genau dieses Eintrags – dieselbe Vorschau-Pipeline wie im Einzelmodus."""
        if self.detailId in self.by_id:
            self.flush()
            self.tool.preview.show_batch_item(self.detailId)

    def preview_fields(self, item_id: str) -> tuple[dict | None, str]:
        item = self.by_id.get(item_id)
        if item is None:
            return None, "Der Eintrag ist nicht mehr im Stapel."
        res = self.resolve(item, for_preview=True)
        if res.fields is None:
            blocking = [issue for issue in res.issues if issue.code in resolver.PREVIEW_BLOCKING]
            return None, (blocking[0].text if blocking else "Vorschau nicht möglich")
        return res.fields, ""

    @Slot()
    def editSingle(self) -> None:  # noqa: N802
        if self.detailId:
            self.flush()
            self.edit_single(self.detailId)

    def edit_single(self, item_id: str) -> None:
        """»Einzeln bearbeiten«: Eintrag in »Übersicht erstellen« übernehmen (rückgängig machbar)."""
        item = self.by_id.get(item_id)
        if item is None:
            return
        c = self.c
        customers = self.tool.customers
        res = self.resolve(item)
        previous = (c.firma, c.kd, c.mail, c.excel)
        customer_state = customers.leave()
        c._undo_overview = previous if any(value.strip() for value in previous) or customer_state else None
        c._undo_overview_customer = customer_state
        c._reset_work(("", "", "", item.path))
        if res.customer is not None:
            customers.apply_customer(res.customer.id)
        ov = item.overrides
        if ov.template is not None:
            entry = self.app.state.find_vorlage(ov.template) if ov.template else None
            if entry is not None:
                c.apply_vorlage(entry, texts=customers._texts_fresh(), quiet=True)
        for name, value in (("firma", res.company), ("kd", res.number)):
            if value and getattr(c, name).strip() != value:
                setattr(c, name, value)
        if len(res.emails) > 1 and res.email:
            c.mail = res.email
        elif ov.email:
            c.mail = ov.email
        if ov.logo and Path(ov.logo).is_file():
            c.logo = ov.logo
        if ov.target_dir:
            c.ziel = ov.target_dir
        c.refresh_files()
        self.app.navigate("create")
        actions = (("Rückgängig", c._undo_new_overview),) if c._undo_overview else ()
        self.app.notify("kunde_info", "info", f"„{item.name}“ aus dem Stapel übernommen. Der Stapel-Eintrag bleibt unverändert.", actions=actions, auto_hide=10000)

    # Sicherung der Warteschlange ------------------------------------------------------------------------------------------------
    def _queue_path(self) -> Path:
        return Path(appstate.CONFIG_FILE).parent / QUEUE_FILE

    def _load_queue(self) -> list[BatchItem]:
        path = self._queue_path()
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

    def _save_soon(self) -> None:
        if self._closing:
            return
        self.app.timers.later("batch:save", SAVE_DELAY, self._save_now)

    def _save_now(self) -> None:
        """Stapel sichern (nur Pfade, Zuordnungen, eigene Angaben, Ergebnisse) – atomar."""
        self.app.timers.cancel("batch:save")
        path = self._queue_path()
        if not self.items:
            try:
                path.unlink()
            except OSError:
                pass
            return
        data = {"version": QUEUE_VERSION, "eintraege": [item.to_dict() for item in self.items]}
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

    def confirm_close(self) -> bool:
        """Beenden während der Erstellung: nachfragen. Fertige PDFs bleiben erhalten."""
        if not self.running_now:
            return True
        return self.app.dialogs.confirm(
            "Stapel wird gerade erstellt",
            "Beenden bricht den Stapel ab. Bereits erstellte PDFs bleiben erhalten, die laufende wird sauber verworfen.",
            "Abbrechen und beenden",
        )

    def close(self) -> None:
        """Beim Beenden: laufende Erstellung abbrechen und kurz auf ihr sauberes Ende warten."""
        self.flush()
        self._closing = True
        runner = self.runner
        if runner is not None and not runner.finished:
            runner.cancel()
            deadline = time.monotonic() + 8.0
            while not runner.finished and time.monotonic() < deadline:
                QCoreApplication.processEvents()
                time.sleep(0.02)
        if self.analyzer is not None:
            self.analyzer.clear()
        self._save_now()

    # Anzeige (gesammelt) -------------------------------------------------------------------------------------------------------
    def _changed(self, item_ids: tuple[str, ...] | None = None, structure: bool = False) -> None:
        """Oberfläche gesammelt aktualisieren (höchstens einmal je Durchlauf der Ereignisschleife)."""
        self.app.timers.soon("batch:refresh", self.refresh)

    def refresh(self) -> None:
        if self.detailId:
            if self.detailId not in self.by_id:
                self.detailId = ""
            else:
                self.refresh_detail(load_fields=False)
        items = self.items
        self.hasItems = bool(items)
        self.running = self.running_now
        self._refresh_settings()
        counts = self.count_items()
        self.counts = counts
        visible = self.visible_items()
        comparison = self.tool.comparison
        defaults = self.defaults().regeln if items else ()
        rows = []
        for item in visible:
            res = self.resolutions.get(item.id)
            label, tone = status_label(item)
            detail, detail_tone = detail_line(item, res)
            badges = report.badges(comparison.batch_comparison(item, self.resolution(item.id), defaults)) if self.tool.customers.enabled else ""
            rows.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "facts": facts_line(item, badges),
                    "detail": detail,
                    "detailTone": detail_tone,
                    "status": label,
                    "statusTone": tone,
                    "statusKey": item.status.value,
                    "selected": item.selected,
                }
            )
        self.model.set_items(rows)
        self.visibleCount = len(rows)
        self.filterEmpty = FILTER_EMPTY.get(self.filter, "Keine Einträge.") if items and not rows else ""
        selected = [item for item in visible if item.selected]
        self.checkAll = 2 if visible and len(selected) == len(visible) else (1 if selected else 0)
        total_selected = len(self.selected_items())
        self.selection = total_selected
        self.selectedText = f"{total_selected} ausgewählt" if total_selected else ""
        self._refresh_summary(counts)

    def _refresh_summary(self, counts: dict[str, int]) -> None:
        running = self.running_now
        total = counts["all"]
        waiting = sum(1 for item in self.items if item.status in (ItemStatus.PENDING, ItemStatus.ANALYZING))
        parts = ["1 Datei" if total == 1 else f"{total} Dateien", f"{counts['ready']} bereit"]
        if counts["needs_input"]:
            parts.append(f"{counts['needs_input']} Angaben erforderlich")
        if counts["failed"]:
            parts.append("1 Fehler" if counts["failed"] == 1 else f"{counts['failed']} Fehler")
        if counts["done"]:
            parts.append(f"{counts['done']} fertig")
        if waiting:
            parts.append(f"{waiting} {'wird' if waiting == 1 else 'werden'} geprüft")
        self.summaryText = " · ".join(parts)
        if running or waiting:
            self.summaryKind = "busy"
        elif counts["failed"] or counts["needs_input"]:
            self.summaryKind = "caution"  # einzelne Einträge – der Stapel selbst ist nicht fehlerhaft
        elif counts["ready"] or counts["done"]:
            self.summaryKind = "success"
        else:
            self.summaryKind = "neutral"
        runner = self.runner
        if running and runner is not None:
            summary = runner.summary
            processed = summary.processed + summary.cancelled
            self.progress = processed / max(1, summary.total)
            self.progressError = bool(summary.failed)
            done_text = f"{summary.created} von {summary.total} {'Übersicht' if summary.total == 1 else 'Übersichten'} erstellt"
            extra = [f"{summary.failed} fehlgeschlagen"] if summary.failed else []
            if summary.skipped:
                extra.append(f"{summary.skipped} übersprungen")
            self.progressText = " · ".join([done_text, *extra])
            job = runner.current_job
            if runner.cancel_requested:
                self.currentText = "Wird abgebrochen – die laufende PDF wird sauber beendet …"
            elif job is not None:
                self.currentText = f"{job.label} wird verarbeitet …"
            else:
                self.currentText = ""
        self.canRun = bool(counts["ready"]) and not running
        self.canCancel = running and not (runner is not None and runner.cancel_requested)
        self.canRetry = bool(counts["failed"]) and not running
        result = self.summary
        if result is not None and not running:
            severity = "warning" if (result.failed or result.aborted) else "success"
            self.result = {
                "shown": True,
                "title": "Stapel abgebrochen" if result.aborted else "Stapel abgeschlossen",
                "severity": severity,
                "message": self.summary_text(result).split(": ", 1)[1],
                "hasOutput": bool(self.output_folders()),
                "hasErrors": bool(counts["failed"]),
            }
        else:
            self.result = {"shown": False}
        # »Neuer Stapel« steht im Ergebnis – oben nur, solange es kein Ergebnis gibt
        self.newVisible = bool(self.items) and not running and not self.result.get("shown")

    def _refresh_settings(self) -> None:
        settings = self.settings
        if settings.target_dir:
            self.targetText, self.targetPath = (Path(settings.target_dir).name or settings.target_dir), settings.target_dir
        else:
            self.targetText, self.targetPath = "Kein Zielordner gewählt", ""
        if settings.logo:
            name, full = _caption(settings.logo, "")
            self.logoText, self.logoPath = name + ("" if Path(settings.logo).is_file() else " – nicht gefunden"), full
        else:
            self.logoText, self.logoPath = "Installiertes Standardlogo", ""
        names = self.template_names()
        self.templateChoices = [TEMPLATE_NONE, *names]
        current = self.template_name(settings.template)
        self.templateValue = current if current in names else TEMPLATE_NONE
        self.conflictValue = settings.conflict.value
        self.subfolders = bool(settings.subfolders)
        self.customerTarget = bool(settings.customer_target)

    # Detailansicht --------------------------------------------------------------------------------------------------------
    @Slot(str)
    def showDetail(self, item_id: str) -> None:  # noqa: N802
        self.show_detail(item_id)

    def show_detail(self, item_id: str) -> None:
        if item_id not in self.by_id:
            self.show_list()
            return
        self.flush()
        self.detailId = item_id
        self.app.hide_notice("batch_detail_info")
        self.refresh_detail(load_fields=True)

    @Slot()
    def showList(self) -> None:  # noqa: N802
        self.show_list()

    def show_list(self) -> None:
        self.flush()
        self.detailId = ""
        self._changed()

    @Slot(int)
    def step(self, delta: int) -> None:
        order = [item.id for item in self.visible_items()] or [item.id for item in self.items]
        if self.detailId not in order:
            order = [item.id for item in self.items]
        if self.detailId not in order:
            return
        index = order.index(self.detailId) + int(delta)
        if 0 <= index < len(order):
            self.show_detail(order[index])

    def current(self) -> BatchItem | None:
        return self.by_id.get(self.detailId) if self.detailId else None

    def refresh_detail(self, load_fields: bool = False) -> None:
        item = self.current()
        if item is None:
            return
        res = self.resolution(item.id)
        order = [entry.id for entry in self.visible_items()]
        if item.id not in order:
            order = [entry.id for entry in self.items]
        index = order.index(item.id)
        self.position = f"{index + 1} von {len(order)}"
        self.canPrev = index > 0
        self.canNext = index < len(order) - 1
        self.detailTitle = item.name
        self.detailFolder = str(Path(item.path).parent)
        label, _tone = status_label(item)
        kind = {"success": "success", "caution": "caution", "critical": "critical", "accent": "busy", "neutral": "neutral"}[STATUS[item.status][1]]
        if item.status in (ItemStatus.ANALYZING, ItemStatus.PENDING):
            kind = "busy"
        if item.status is ItemStatus.NEEDS_INPUT and res is not None:
            detail = " · ".join(issue.text for issue in res.issues)
        elif item.status is ItemStatus.FAILED:
            detail = item.error or (item.analysis.error if item.analysis is not None and not item.analysis.ok else "") or " · ".join(issue.text for issue in item.issues[:1])
        else:
            detail = ""
        self.detailKind = kind
        self.detailText = label + (f": {detail}" if detail and detail != label else "")
        notes = [note for note in item.notes if note]
        if item.status in CREATED and item.output:
            self.app.notify("batch_detail_info", "success" if item.status is ItemStatus.SUCCESS else "warning", " ".join(notes) or Path(item.output).name, title="Erstellt", status=False, animate=False)
        elif notes and item.status not in DONE:
            self.app.notify("batch_detail_info", "info", " ".join(notes), status=False, animate=False)
        else:
            self.app.hide_notice("batch_detail_info", animate=False)
        self._refresh_excel(item, res)
        self._refresh_customer(item, res, load_fields)
        self._refresh_changes(item, res)
        self._refresh_output(item, res)
        self.itemRunning = item.status is ItemStatus.PROCESSING
        self.customerMode = item.customer_mode.value
        self.hasOutput = item.status in CREATED and bool(item.output) and Path(item.output).is_file()
        preview_ok = True if res is None else not any(issue.code in resolver.PREVIEW_BLOCKING for issue in res.issues)
        self.canPreview = preview_ok and item.analysis is not None and item.analysis.ok

    def _refresh_changes(self, item: BatchItem, res) -> None:
        """Vertragsänderungen des Eintrags – mit Kundenakte und gespeichertem Stand."""
        view = self.detail
        customer = res.customer if res is not None else None
        if item.analysis is None or not item.analysis.ok:
            view.show_message("info", "Die Vertragsänderungen erscheinen nach der Excel-Prüfung.")
            return
        if customer is None:
            view.show_message("info", NO_CUSTOMER)
            return
        comparison = self.tool.comparison.batch_comparison(item, res, self.defaults().regeln)
        if comparison is None:
            view.show_message("info", f"{report.NO_HISTORY} {AFTER_EXPORT}")
            return
        choices, _selected, _baseline = self.tool.comparison.batch_choices(item, res)
        view.show_comparison(comparison, choices, comparison.baseline.id, snapshot_facts(comparison.baseline))

    def _choose_baseline(self, snapshot_id: str) -> None:
        if self.detailId:
            self.tool.comparison.batch_choose_baseline(self.detailId, snapshot_id)
            self._changed(item_ids=(self.detailId,))

    def _copy_comparison(self) -> None:
        item = self.current()
        if item is None:
            return
        res = self.resolution(item.id)
        comparison = self.tool.comparison.batch_comparison(item, res, self.defaults().regeln)
        if comparison is None:
            return
        label = res.customer.label if res is not None and res.customer is not None else ""
        self.app.copy_text(report.comparison_text(comparison, label), "Änderungen kopiert.")

    def _refresh_excel(self, item: BatchItem, res) -> None:
        analysis = item.analysis
        facts: list[dict] = []
        if analysis is None:
            self.app.notify("batch_excel", "info", "Excel wird geprüft …", status=False, animate=False)
        elif not analysis.ok:
            self.app.notify("batch_excel", "error", analysis.error or "Die Datei konnte nicht gelesen werden.", title="Excel-Prüfung fehlgeschlagen", status=False, animate=False)
        elif analysis.missing:
            spalten = ", ".join(f"»{name}«" for name in analysis.missing)
            self.app.notify("batch_excel", "error", f"Für die PDF fehlt {'die Spalte' if len(analysis.missing) == 1 else 'die Spalten'} {spalten}.", title="Spalten fehlen", status=False, animate=False)
        elif not analysis.active:
            self.app.notify("batch_excel", "warning", "In der Datei steht kein aktiver Vertrag." + (f" {analysis.inactive} inaktive wurden ausgeblendet." if analysis.inactive else ""), title="Keine aktiven Verträge", status=False, animate=False)
        else:
            self.app.notify("batch_excel", "success", contract_summary(analysis.active, analysis.inactive), title="Excel geprüft", status=False, animate=False)
            if len(analysis.numbers) > 1:
                facts.append({"label": "Kundennummer", "value": f"{len(analysis.numbers)} verschiedene in der Datei: " + ", ".join(analysis.numbers), "tone": "caution"})
            if len(analysis.companies) > 1:
                facts.append({"label": "Firmenname", "value": f"{len(analysis.companies)} verschiedene in der Datei: " + ", ".join(analysis.companies), "tone": "caution"})
            if analysis.bold:
                facts.append({"label": "Fettschrift", "value": f"{analysis.bold} {'Zelle' if analysis.bold == 1 else 'Zellen'} in der PDF fett", "tone": "muted"})
            for hint in analysis.hints:
                if "Rechnungsempfänger" not in hint:
                    facts.append({"label": "Hinweis", "value": hint, "tone": "muted"})
        self.excelFacts = facts
        emails = list(analysis.emails) if analysis is not None and analysis.ok else []
        if len(emails) > 1:
            self.mailValue = f"{len(emails)} erkannt"
            self.mailChoices = emails
            self.mailChoice = res.email if res is not None and res.email in emails else ""
            self.mailField = False
        elif len(emails) == 1:
            self.mailValue = emails[0]
            self.mailChoices = []
            self.mailField = False
        elif analysis is not None and analysis.ok:
            self.mailValue = "keine in der Excel"
            self.mailChoices = []
            self.mailField = True
        else:
            self.mailValue = "–"
            self.mailChoices = []
            self.mailField = False

    def _refresh_customer(self, item: BatchItem, res, load_fields: bool) -> None:
        if res is None:
            return
        customers = self.tool.customers
        if res.customer is not None:
            self.customerTitle = res.customer.label
            via = ", ".join(res.match.emails_of(res.customer.id)) if res.match is not None else ""
            note = f"Erkannt an {via}" if res.customer_source == "erkannt" and via else ("Bewusst gewählt" if res.customer_source == "gewählt" else "")
            self.customerNote = note + (" · Kundenakte bleibt unverändert – Angaben hier gelten nur für diesen Eintrag." if note else "")
        elif item.customer_mode is CustomerMode.NONE:
            self.customerTitle = "Ohne Kundenakte"
            self.customerNote = "Firmenname und Kundennummer bitte selbst eintragen (oder aus der Excel)."
        else:
            conflict = [issue for issue in res.issues if issue.area == "kunde"]
            if conflict and conflict[0].code == "customer_conflict":
                names = ", ".join(f"„{c.label}“" for c in (customers.customers.get(i) for i in (res.match.customer_ids if res.match else ())) if c is not None)
                self.customerTitle = "Mehrere bekannte Kunden"
                self.customerNote = f"Die Excel enthält Rechnungsempfänger, die verschiedenen bekannten Kunden zugeordnet sind: {names}. Bitte den passenden Kunden auswählen."
            elif conflict:
                self.customerTitle = "Kunde bitte prüfen"
                self.customerNote = conflict[0].text
            elif res.company and res.number:
                self.customerTitle = "Keine Kundenakte zugeordnet"
                self.customerNote = "Die Angaben gelten nur für diesen Eintrag."
            else:
                self.customerTitle = "Kunde nicht zugeordnet"
                self.customerNote = "Kein bekannter Rechnungsempfänger. Kunden auswählen oder Firmenname und Kundennummer eintragen."
        # ein Feld, in dem gerade getippt wird, nie neu laden (wie 2.6.1) – sonst verschwinden z. B. Leerzeichen am Ende
        if load_fields or not (self._focused or self.app.timers.pending("batch:edit")):
            self._loading = True
            try:
                self.company = res.company
                self.number = res.number
                email = item.overrides.email or (res.email if res.email_source == resolver.SOURCE_CUSTOMER else "")
                if not res.emails:
                    self.email = email
            finally:
                self._loading = False
        sources = []
        if res.company:
            sources.append(f"Firmenname: {SOURCE_TEXT.get(res.company_source, res.company_source)}")
        if res.number:
            sources.append(f"Kundennummer: {SOURCE_TEXT.get(res.number_source, res.number_source)}")
        self.valueSource = " · ".join(sources)
        self.companyError = any(issue.code == "company_missing" for issue in res.issues)
        self.numberError = any(issue.code == "number_missing" for issue in res.issues)
        offer = self.offer_emails(item.id)
        if res.customer is not None and offer and customers.enabled:
            single = len(offer) == 1
            item_id = item.id
            self.app.notify(
                "batch_mail_info",
                "info",
                f"{', '.join(offer)} → „{res.customer.label}“. PDF Tool erkennt den Kunden dann in der nächsten Excel-Liste wieder.",
                title="Diese E-Mail künftig diesem Kunden zuordnen?" if single else "Diese E-Mail-Adressen künftig diesem Kunden zuordnen?",
                actions=(("Zuordnung merken", lambda: self.remember_emails(item_id)), ("Nicht zuordnen", lambda: self.decline_emails(item_id))),
                status=False,
                animate=False,
            )
        else:
            self.app.hide_notice("batch_mail_info", animate=False)

    def _refresh_output(self, item: BatchItem, res) -> None:
        names = self.template_names()
        self.itemTemplateChoices = [TEMPLATE_AUTO, TEMPLATE_NONE, *names]
        chosen = item.overrides.template
        self.itemTemplate = TEMPLATE_AUTO if chosen is None else (TEMPLATE_NONE if chosen == "" else self.template_name(chosen))
        rule_sets = self.rule_set_names()
        self.itemRuleSetChoices = [RULE_SET_AUTO, RULE_SET_NONE, *(name for _id, name in rule_sets)]
        own = item.overrides.rule_set
        self.itemRuleSet = RULE_SET_AUTO if own is None else (RULE_SET_NONE if own == "" else next((name for ident, name in rule_sets if ident == own), "gelöschtes Regelwerk"))
        if res is None:
            return
        if res.template:
            note = f"Verwendet: Vorlage „{res.template}“ ({SOURCE_TEXT.get(res.template_source, res.template_source)}) · Kopf- und Fußzeile: {res.header_source}"
        else:
            note = f"Keine Vorlage – es gilt die »Darstellung« · Kopf- und Fußzeile: {res.header_source}"
        if res.rule_set:
            source = SOURCE_TEXT.get(res.rule_set_source, res.rule_set_source)
            note += f" · Regelwerk: „{res.rule_set}“ ({'Darstellung' if res.rule_set_source == resolver.SOURCE_DEFAULT else source})"
        self.templateNote = note
        logo_name, logo_full = _caption(res.logo, "Kein Logo")
        self.itemLogoText = f"{logo_name}  ·  {SOURCE_TEXT.get(res.logo_source, res.logo_source)}" if res.logo else logo_name
        self.itemLogoPath = logo_full
        self.itemLogoReset = item.overrides.logo is not None
        folder = res.folder or "Kein Zielordner"
        self.itemTargetText = f"{Path(folder).name or folder}  ·  {SOURCE_TEXT.get(res.folder_source, res.folder_source)}" if res.folder else folder
        self.itemTargetPath = res.folder or ""
        self.itemTargetReset = item.overrides.target_dir is not None
        if item.status in CREATED and item.output:
            self.outputText = f"Erstellt: {item.output}"
        elif res.fields is not None or res.number:
            try:
                from engine import dateiname_fuer

                layout_name = (res.fields or {}).get("dateiname") or self.c.dateiname
                name = dateiname_fuer(layout_name, res.number or "…", res.company)
                self.outputText = f"Wird gespeichert als »{name}« in {res.folder or '–'}"
            except (KeyError, ValueError, IndexError):
                self.outputText = ""
        else:
            self.outputText = ""

    # Eingaben der Detailansicht --------------------------------------------------------------------------------------------------
    def _schedule_edit(self) -> None:
        if self._loading or not self.detailId:
            return
        self.app.timers.later("batch:edit", EDIT_DELAY, self._flush_edit)

    @Slot(str, bool)
    def setFieldFocus(self, field: str, focused: bool) -> None:  # noqa: N802
        """QML meldet, ob Firmenname, Kundennummer oder E-Mail gerade den Tastaturfokus haben."""
        if focused:
            self._focused.add(field)
        else:
            self._focused.discard(field)

    def flush(self) -> None:
        if self.app.timers.pending("batch:edit"):
            self.app.timers.cancel("batch:edit")
            self._flush_edit()

    def _flush_edit(self) -> None:
        item = self.current()
        if item is None or self._loading:
            return
        values = {}
        inherited = self.inherited(item.id)
        for key, value in (("company", self.company), ("number", self.number)):
            value = value.strip()
            values[key] = None if value == inherited.get(key, "") else value
        email = self.email.strip()
        if not (item.analysis is not None and item.analysis.emails):
            values["email"] = None if email == inherited.get("email", "") else email
        self.edit(item.id, **values)

    @Slot(str)
    def pickMail(self, mail: str) -> None:  # noqa: N802
        if self.detailId and mail:
            self.edit(self.detailId, email=mail)

    @Slot(str)
    def setItemTemplate(self, label: str) -> None:  # noqa: N802
        if not self.detailId:
            return
        value = None if label == TEMPLATE_AUTO else ("" if label == TEMPLATE_NONE else self.template_ref(label))
        self.apply_template(value, [self.detailId])

    @Slot(str)
    def setItemRuleSet(self, label: str) -> None:  # noqa: N802
        """Regelwerk dieses Eintrags: »Automatisch« (Vorlage bzw. Darstellung), keines oder ein bestimmtes."""
        if not self.detailId:
            return
        if label == RULE_SET_AUTO:
            value = None
        elif label == RULE_SET_NONE:
            value = ""
        else:
            value = next((ident for ident, name in self.rule_set_names() if name == label), None)
            if value is None:
                return
        self.apply_rule_set(value, [self.detailId])

    @Slot()
    def pickItemLogo(self) -> None:  # noqa: N802
        item = self.current()
        if item is None:
            return
        path = files.open_file("Logo für diesen Eintrag", self.app.initial_dir("logo", item.overrides.logo or ""), files.IMAGE_FILTER)
        if path:
            self.app.remember_dir("logo", path)
            self.edit(item.id, logo=path)

    @Slot()
    def resetItemLogo(self) -> None:  # noqa: N802
        if self.detailId:
            self.edit(self.detailId, logo=None)

    @Slot()
    def pickItemTarget(self) -> None:  # noqa: N802
        item = self.current()
        if item is None:
            return
        path = files.pick_folder("Zielordner für diesen Eintrag", self.app.initial_dir("ziel", item.overrides.target_dir or self.settings.target_dir))
        if path:
            self.edit(item.id, target_dir=path)

    @Slot()
    def resetItemTarget(self) -> None:  # noqa: N802
        if self.detailId:
            self.edit(self.detailId, target_dir=None)

    @Slot()
    def openPdf(self) -> None:  # noqa: N802
        item = self.current()
        if item is not None and item.output:
            self.app.open_file(item.output, "batch_detail_info")

    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        item = self.current()
        if item is not None and item.output:
            self.app.open_folder_of(item.output, "batch_detail_info")

    @Slot()
    def removeCurrent(self) -> None:  # noqa: N802
        item = self.current()
        if item is None:
            return
        self.show_list()
        self.remove([item.id])

    @Slot(str)
    def openItemPdf(self, item_id: str) -> None:  # noqa: N802
        item = self.by_id.get(item_id)
        if item is not None and item.output:
            self.app.open_file(item.output, "batch_info")

    @Slot(str)
    def copyItemPath(self, item_id: str) -> None:  # noqa: N802
        item = self.by_id.get(item_id)
        if item is not None:
            self.app.copy_path(item.path)

    @Slot(str)
    def removeItem(self, item_id: str) -> None:  # noqa: N802
        self.remove([item_id])

    # Hilfe ---------------------------------------------------------------------------------------------------------------------------
    def show_help(self) -> None:
        if self.tool.customers.enabled:
            self.app.show_steps("Kurzanleitung – Stapel", HELP_STEPS, HELP_NOTES)
        else:
            self.app.show_steps("Kurzanleitung – Stapel", HELP_STEPS_PLAIN, HELP_NOTES_PLAIN)
