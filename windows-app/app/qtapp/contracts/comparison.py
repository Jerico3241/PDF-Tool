"""Vertragsvergleich (in QML: ``Comparison``).

* Nach der Excel-Prüfung und mit einer Kundenakte wird der aktuelle Stand mit dem zuletzt
  gespeicherten Vertragsstand dieses Kunden verglichen (Neu, Entfernt, Geändert, Unverändert).
* Ein Stand wird nur nach einer erfolgreich erstellten PDF gespeichert – nie für die Vorschau,
  die Excel-Prüfung, einen Abbruch oder einen Fehler und nie ohne Kundenakte.
* Der Vergleich ist eine reine Anzeige: Er ändert die PDF nicht und löst keine neue Vorschau aus.
* Der Stapel nutzt dieselben Stände und denselben Vergleich.
* Ohne eingeschaltete Kundenakte gibt es keine sichere Kundenidentität: Dann entsteht kein Stand
  und es wird nichts verglichen. Gespeicherte Stände bleiben unverändert erhalten.

Fachlogik (Speicher, Vergleich, Texte) bleibt in ``tools.contract_overview.history``. Die Liste
der Änderungen ist ein Listenmodell; aufgeklappte Einträge bleiben beim Blättern erhalten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import Property, QObject, Signal, Slot

import appstate
from tools.contract_overview.history import report
from tools.contract_overview.history.compare import compare
from tools.contract_overview.history.models import ChangeKind, ContractComparison, ContractRecord, Snapshot, SnapshotSource, records_from
from tools.contract_overview.history.repository import FOLDER, HistoryStore, file_sha256

from ..base import Observable, prop
from ..models import KeyedListModel

NO_CUSTOMER = "Mit einer Kundenakte speichert PDF Tool nach jedem Erstellen den Vertragsstand und zeigt beim nächsten Mal, was sich geändert hat."
FIRST_SAVED = "Erster Vertragsstand gespeichert. Beim nächsten Excel-Import ist ein Vergleich möglich."
AFTER_EXPORT = "Nach dem Erstellen der PDF wird der aktuelle Stand gespeichert – ab dann zeigt PDF Tool hier neue, entfernte und geänderte Verträge."
TONES = {ChangeKind.ADDED: "success", ChangeKind.REMOVED: "critical", ChangeKind.CHANGED: "caution", ChangeKind.UNCHANGED: "neutral"}
KIND_KEYS = {ChangeKind.ADDED: "added", ChangeKind.REMOVED: "removed", ChangeKind.CHANGED: "changed", ChangeKind.UNCHANGED: "unchanged"}


def _file_fact(label: str, path: str) -> dict:
    if not path:
        return {"label": label, "value": "–", "tone": "muted"}
    name = Path(path).name or path
    if Path(path).exists():
        return {"label": label, "value": name, "tone": ""}
    return {"label": label, "value": f"{name} (nicht mehr vorhanden)", "tone": "muted"}


def snapshot_facts(snapshot: Snapshot) -> list[dict]:
    """Datum, Uhrzeit und Herkunft eines Stands – die Dateien selbst werden nicht gebraucht."""
    when = report.stand_label(snapshot)
    if snapshot.export_count > 1:
        when += f" · {snapshot.export_count}× erstellt, zuletzt {snapshot.exported.astimezone().strftime('%d.%m.%Y, %H:%M')}"
    return [{"label": "Stand", "value": when, "tone": ""}, _file_fact("Excel", snapshot.source.excel_path), _file_fact("PDF", snapshot.source.pdf_path)]


def baseline_choices(snapshots: list[Snapshot], latest_before: Snapshot | None, saved: set[str]) -> list[tuple[str, str]]:
    """(Stand-ID, Beschriftung) für »Vergleichen mit«, neueste zuerst – jede Beschriftung eindeutig."""
    labels = [report.stand_label(snapshot) for snapshot in snapshots]
    labels = [snapshot.created.astimezone().strftime("%d.%m.%Y, %H:%M:%S") if labels.count(label) > 1 else label for snapshot, label in zip(snapshots, labels)]
    seen: dict[str, int] = {}
    choices = []
    for snapshot, label in zip(snapshots, labels):
        if labels.count(label) > 1:  # sogar in derselben Sekunde gespeichert (Stapel)
            seen[label] = seen.get(label, 0) + 1
            label = f"{label} · {seen[label]}"
        if snapshot.id in saved:
            label = f"Gerade gespeichert ({label})"
        elif latest_before is not None and snapshot.id == latest_before.id:
            label = f"Letzter Stand ({label})"
        choices.append((snapshot.id, label))
    return choices


def change_rows(comparison: ContractComparison, include_unchanged: bool, expanded: set[str]) -> list[dict]:
    rows = []
    for change in comparison.changes(include_unchanged):
        details = [{"field": report.FIELD_LABELS.get(f.field, f.field), "change": f"{report.format_value(f.field, f.old_value)} → {report.format_value(f.field, f.new_value)}"} for f in change.fields]
        if change.kind is ChangeKind.CHANGED:
            summary = f"{details[0]['field']} {details[0]['change']}" if len(details) == 1 else f"{len(details)} Änderungen"
        elif change.kind is ChangeKind.ADDED:
            summary = report.euro(change.record.net_amount) if change.record.net_amount else change.record.net_text
        elif change.kind is ChangeKind.REMOVED:
            summary = "nicht mehr in der Excel"
        else:
            summary = ""
        rows.append(
            {
                "key": change.key,
                "kind": KIND_KEYS[change.kind],
                "kindLabel": report.KIND_LABELS[change.kind],
                "tone": TONES[change.kind],
                "title": report.contract_title(change.record),
                "summary": summary,
                "details": details,
                "expandable": bool(details),
                "expanded": change.key in expanded and bool(details),
            }
        )
    return rows


def count_items(comparison: ContractComparison) -> list[dict]:
    counts = comparison.counts()
    items = []
    for kind, label in ((ChangeKind.ADDED, "neu"), (ChangeKind.REMOVED, "entfernt"), (ChangeKind.CHANGED, "geändert"), (ChangeKind.UNCHANGED, "unverändert")):
        if counts[kind]:
            items.append({"text": f"{counts[kind]} {label}", "tone": TONES[kind], "kind": KIND_KEYS[kind]})
    return items


class ComparisonView(Observable):
    """Anzeige eines Vergleichs: Hinweis oder Ergebnis mit »Vergleichen mit«, Liste und Stand-Angaben."""

    modeChanged, mode = prop(str, "mode", "none")  # none, message, comparison
    noteSeverityChanged, noteSeverity = prop(str, "noteSeverity", "info")
    noteTitleChanged, noteTitle = prop(str, "noteTitle", "")
    noteTextChanged, noteText = prop(str, "noteText", "")
    headlineChanged, headline = prop(str, "headline", "")
    countsChanged, counts = prop(list, "counts", [])
    choicesChanged, choices = prop(list, "choices", [])
    baselineChanged, baseline = prop(str, "baseline", "")
    unchangedCountChanged, unchangedCount = prop(int, "unchangedCount", 0)
    showUnchangedChanged, showUnchanged = prop(bool, "showUnchanged", False)
    unchangedLabelChanged, unchangedLabel = prop(str, "unchangedLabel", "")
    canCopyChanged, canCopy = prop(bool, "canCopy", False)
    metaChanged, meta = prop(list, "meta", [])
    badgesChanged, badges = prop(str, "badges", "")
    rowCountChanged, rowCount = prop(int, "rowCount", 0)

    def __init__(self, on_baseline: Callable[[str], None], on_copy: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.on_baseline = on_baseline
        self.on_copy = on_copy
        self.comparison: ContractComparison | None = None
        self.rows = KeyedListModel(("kind", "kindLabel", "tone", "title", "summary", "details", "expandable", "expanded"), key="key", parent=self)
        self._expanded: set[str] = set()

    def _rows_obj(self) -> QObject:
        return self.rows

    _constant = Signal()
    changeModel = Property(QObject, _rows_obj, notify=_constant)

    def clear(self) -> None:
        self.comparison = None
        self.mode = "none"
        self.rows.clear()
        self.rowCount = 0
        self.badges = ""

    def show_message(self, severity: str, message: str, title: str = "") -> None:
        """Nur ein Hinweis (ohne Kundenakte, noch kein früherer Stand)."""
        self.comparison = None
        self.noteSeverity, self.noteText, self.noteTitle = severity, message, title
        self.rows.clear()
        self.rowCount = 0
        self.badges = ""
        self.mode = "message"

    def show_comparison(self, comparison: ContractComparison, choices: Sequence[tuple[str, str]], selected: str, meta: Sequence[dict], note: tuple[str, str, str] | None = None) -> None:
        """Vergleich anzeigen. ``choices``: (Stand-ID, Beschriftung), neueste zuerst."""
        if comparison is not self.comparison and (self.comparison is None or comparison.baseline != self.comparison.baseline):
            self.showUnchanged = False
            self._expanded = set()
        self.comparison = comparison
        if note is not None:
            self.noteSeverity, self.noteText, self.noteTitle = note
        else:
            self.noteText, self.noteTitle = "", ""
        self.choices = [{"value": snapshot_id, "label": label} for snapshot_id, label in choices]
        self.baseline = selected if any(snapshot_id == selected for snapshot_id, _l in choices) else (choices[0][0] if choices else "")
        baseline = comparison.baseline
        since = report.stand_label(baseline, with_time=False) if baseline is not None else ""
        self.headline = f"Seit {since}" if comparison.has_changes else f"Keine Änderungen seit {since}"
        self.counts = count_items(comparison)
        self.unchangedCount = comparison.counts()[ChangeKind.UNCHANGED]
        self._update_unchanged_label()
        self.canCopy = comparison.has_changes
        self.meta = list(meta)
        self.badges = report.badges(comparison)
        self._update_rows()
        self.mode = "comparison"

    def _update_unchanged_label(self) -> None:
        count = self.unchangedCount
        if self.showUnchanged:
            self.unchangedLabel = "Unveränderte ausblenden"
        else:
            self.unchangedLabel = "1 unveränderten anzeigen" if count == 1 else f"{count} unveränderte anzeigen"

    def _update_rows(self) -> None:
        if self.comparison is None:
            self.rows.clear()
            self.rowCount = 0
            return
        rows = change_rows(self.comparison, self.showUnchanged, self._expanded)
        self.rows.set_items(rows)
        self.rowCount = len(rows)

    @Slot()
    def toggleUnchanged(self) -> None:  # noqa: N802
        self.showUnchanged = not self.showUnchanged
        self._update_unchanged_label()
        self._update_rows()

    @Slot(str)
    def toggle(self, key: str) -> None:
        """Geänderten Vertrag auf- bzw. zuklappen (bleibt beim Blättern und Aktualisieren erhalten)."""
        item = self.rows.item(key)
        if item is None or not item.get("expandable"):
            return
        if key in self._expanded:
            self._expanded.discard(key)
        else:
            self._expanded.add(key)
        self.rows.update_item(key, expanded=key in self._expanded)

    @Slot(str)
    def chooseBaseline(self, snapshot_id: str) -> None:  # noqa: N802
        if snapshot_id:
            self.on_baseline(snapshot_id)

    @Slot()
    def copy(self) -> None:
        self.on_copy()


def rule_set_key(rule_set) -> str:
    """Schlüssel des Regelwerks für den Zwischenspeicher der Anzeige ("" = keines)."""
    return f"{rule_set.id}:{rule_set.fingerprint()}" if rule_set is not None else ""


class ComparisonController(Observable):
    """Vertragsstände speichern und vergleichen (Einzelmodus und Stapel)."""

    visibleChanged, visible = prop(bool, "visible", False)  # Karte in »Übersicht erstellen«

    def __init__(self, app, tool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.tool = tool
        self.c = None
        self.history = HistoryStore(Path(appstate.CONFIG_FILE).parent / FOLDER)
        self.history_version = 0
        self._cache: dict[str, list[Snapshot]] = {}
        # Einzelmodus: eine »Sitzung« ist eine Excel mit einer Kundenakte. Stände, die in ihr
        # gespeichert wurden, sind nicht der Ausgangsstand – so bleibt der Vergleich nach dem
        # Erstellen sichtbar, bis eine andere Excel oder ein anderer Kunde gewählt wird.
        self._session: tuple = ()
        self._saved: set[str] = set()
        self._baseline: str | None = None
        self._note: tuple[str, str, str] | None = None
        self.comparison: ContractComparison | None = None
        # Schlüssel der gezeigten Anzeige: Neu berechnet wird nur bei geänderten Daten, anderem
        # Kunden, anderem Ausgangsstand oder neuen Ständen – nicht bei jeder Eingabe.
        self._state: tuple | None = None
        self._source: dict | None = None
        self.runs = 0  # berechnete Vergleiche im Einzelmodus (Tests, Diagnose)
        self.view = ComparisonView(self.choose_baseline, self.copy_comparison, self)
        # Stapel: je Eintrag der beim Erstellen gespeicherte Stand und der gewählte Vergleich
        self._batch_saved: dict[str, str] = {}
        self._batch_baselines: dict[str, str] = {}
        self._batch_comparisons: dict[str, tuple[tuple, ContractComparison | None]] = {}

    def attach(self, overview) -> None:
        self.c = overview

    def _view_obj(self) -> QObject:
        return self.view

    _constant = Signal()
    single = Property(QObject, _view_obj, notify=_constant)

    # Gespeicherte Stände ------------------------------------------------------------------------------------
    def snapshots(self, customer_id: str | None) -> list[Snapshot]:
        """Stände eines Kunden (neueste zuerst), zwischengespeichert bis zur nächsten Änderung."""
        if not customer_id:
            return []
        if customer_id not in self._cache:
            self._cache[customer_id] = self.history.snapshots(customer_id)
        return self._cache[customer_id]

    def _changed(self, customer_id: str | None = None) -> None:
        self.history_version += 1
        if customer_id is None:
            self._cache.clear()
        else:
            self._cache.pop(customer_id, None)
        self._batch_comparisons.clear()

    def record(self, customer_id: str | None, label: str, records: tuple[ContractRecord, ...], excel: str, pdf: str, area: str = "pdf_info") -> tuple[Snapshot, bool, bool] | None:
        """Stand nach einem erfolgreichen Export speichern. Rückgabe: (Stand, neu angelegt, erster Stand)."""
        if not customer_id or not records or not self.tool.customers.enabled:
            return None
        first = not self.snapshots(customer_id)
        try:
            snapshot, created = self.history.record(customer_id, records, SnapshotSource(excel, file_sha256(excel), pdf), label)
        except (OSError, ValueError) as exc:
            self.app.write_error_log(f"Vertragsstand konnte nicht gespeichert werden: {type(exc).__name__}: {exc}")
            self.app.notify(area, "warning", "Die PDF wurde erstellt, der Vertragsstand für den Vergleich konnte aber nicht gespeichert werden. Bitte prüfen, ob der Datenordner beschreibbar ist.", title="Vertragsstand nicht gespeichert", status=False)
            return None
        self._changed(customer_id)
        return snapshot, created, first

    def merge_history(self, target_id: str, source_id: str) -> None:
        """Nach dem Zusammenführen von Kundenakten gehören beide Verläufe zum Ziel."""
        try:
            self.history.merge(target_id, source_id)
        except OSError as exc:
            self.app.write_error_log(f"Vertragsstände konnten nicht zusammengeführt werden: {exc}")
        self._changed()

    # Einzelmodus -----------------------------------------------------------------------------------------------
    def current_contracts(self) -> tuple[ContractRecord, ...] | None:
        """Verträge der geprüften Excel mit den aktuellen Zyklus-Regeln und dem Regelwerk (wie in der PDF)."""
        result = self.c.analysis_for_current()
        if not result or not result.get("ok"):
            return None
        return records_from(result.get("vertraege") or (), self.app.state.regeln, self.c.rule_set())

    def refresh(self) -> None:
        """Gesammelt aktualisieren (nach Prüfung, Kundenwechsel, Regeln, Export)."""
        self.app.timers.soon("comparison", self._refresh_now)

    def _refresh_now(self) -> None:
        view = self.view
        if not self.tool.customers.enabled:
            # Ohne Kundenakte keine Kundenidentität – kein Vergleich, die Karte bleibt verborgen.
            self.comparison = None
            self._state = None
            view.clear()
            self.visible = False
            return
        excel = self.c.excel.strip()
        result = self.c.analysis()
        if result is None and self.c._analysis_path and self.c._analysis_path == excel:
            return  # die Prüfung läuft – die bisherige Anzeige bleibt bis zum Ergebnis stehen
        if not result or not result.get("ok") or self.c._analysis_path != excel:
            self.comparison = None
            self._state = None
            view.clear()
            self.visible = False
            return
        customer = self.tool.customers.active_customer()
        if customer is not None:
            session = (customer.id, excel)
            if session != self._session:
                self._session = session
                self._saved = set()
                self._baseline = None
                self._note = None
        state = (
            customer.id if customer is not None else None,
            excel,
            id(result),
            json.dumps(self.app.state.regeln, sort_keys=True, default=str),
            rule_set_key(self.c.rule_set()),
            self.history_version,
            self._baseline,
            tuple(sorted(self._saved)),
            self._note,
        )
        if state == self._state and self.visible:
            return  # nichts geändert: keine Berechnung, keine neue Anzeige
        self._state = state
        self._source = result  # hält das Ergebnis fest (die id im Schlüssel bleibt eindeutig)
        # Verglichen werden die Werte, die tatsächlich in der PDF stünden – nach dem Regelwerk.
        contracts = records_from(result.get("vertraege") or (), self.app.state.regeln, self.c.rule_set())
        if customer is None:
            self.comparison = None
            view.show_message("info", NO_CUSTOMER, "Vertragsvergleich")
        else:
            snapshots = self.snapshots(customer.id)
            earlier = [snapshot for snapshot in snapshots if snapshot.id not in self._saved]
            if not earlier:
                self.comparison = None
                if self._note is not None:
                    view.show_message(*self._note)
                else:
                    view.show_message("info", f"{report.NO_HISTORY} {AFTER_EXPORT}", "Vertragsvergleich")
            else:
                baseline = next((s for s in snapshots if s.id == self._baseline), None) or earlier[0]
                self.comparison = compare(baseline, contracts)
                self.runs += 1
                view.show_comparison(self.comparison, baseline_choices(snapshots, earlier[0], self._saved), baseline.id, snapshot_facts(baseline), self._note)
        self.visible = True

    def choose_baseline(self, snapshot_id: str) -> None:
        self._baseline = snapshot_id
        self._refresh_now()

    def copy_comparison(self) -> None:
        comparison = self.comparison
        if comparison is None:
            return
        customer = self.tool.customers.active_customer()
        self.app.copy_text(report.comparison_text(comparison, customer.label if customer is not None else ""), "Änderungen kopiert.")

    @Slot()
    def openDetails(self) -> None:  # noqa: N802
        self.app.navigate("comparison")

    def after_export(self, customer_id: str | None, label: str, records: tuple[ContractRecord, ...], excel: str, pdf: Path) -> None:
        """Einzelmodus: Stand der gerade erstellten PDF speichern und die Anzeige anpassen."""
        saved = self.record(customer_id, label, records, excel, str(pdf))
        if saved is None:
            self.refresh()
            return
        snapshot, created, first = saved
        customer = self.tool.customers.active_customer()
        if customer is not None and customer.id == customer_id and self._session == (customer_id, self.c.excel.strip()):
            if created:
                self._saved.add(snapshot.id)
            if first:
                self._note = ("success", FIRST_SAVED, "Vertragsstand gespeichert")
        self.refresh()

    # Stapel -------------------------------------------------------------------------------------------------------
    def batch_comparison(self, item, resolution, default_rules) -> ContractComparison | None:
        """Vergleich eines Stapel-Eintrags mit dem Stand seiner Kundenakte (zwischengespeichert)."""
        if not self.tool.customers.enabled or item.analysis is None or not item.analysis.ok:
            return None
        customer = resolution.customer if resolution is not None else None
        if customer is None:
            return None
        rules = (resolution.fields or {}).get("regeln") if resolution.fields else None
        rule_set = (resolution.fields or {}).get("regelwerk") if resolution.fields else None
        if rules is None:
            rules = default_rules
        saved = self._batch_saved.get(item.id)
        chosen = self._batch_baselines.get(item.id)
        key = (item.stamp, customer.id, json.dumps(rules, sort_keys=True, default=str), json.dumps(rule_set, sort_keys=True, default=str), self.history_version, saved, chosen)
        cached = self._batch_comparisons.get(item.id)
        if cached is not None and cached[0] == key:
            return cached[1]
        snapshots = self.snapshots(customer.id)
        earlier = [snapshot for snapshot in snapshots if snapshot.id != saved]
        baseline = next((s for s in snapshots if s.id == chosen), None) or (earlier[0] if earlier else None)
        comparison = compare(baseline, records_from(item.analysis.contracts, rules, rule_set)) if baseline is not None else None
        self._batch_comparisons[item.id] = (key, comparison)
        return comparison

    def batch_choices(self, item, resolution) -> tuple[list[tuple[str, str]], str | None, Snapshot | None]:
        customer = resolution.customer if resolution is not None else None
        if customer is None:
            return [], None, None
        snapshots = self.snapshots(customer.id)
        saved = self._batch_saved.get(item.id)
        earlier = [snapshot for snapshot in snapshots if snapshot.id != saved]
        chosen = self._batch_baselines.get(item.id)
        baseline = next((s for s in snapshots if s.id == chosen), None) or (earlier[0] if earlier else None)
        return baseline_choices(snapshots, earlier[0] if earlier else None, {saved} if saved else set()), (baseline.id if baseline else None), baseline

    def batch_choose_baseline(self, item_id: str, snapshot_id: str) -> None:
        self._batch_baselines[item_id] = snapshot_id

    def batch_after_item(self, item, customer_id: str | None, label: str, records: tuple[ContractRecord, ...]) -> None:
        """Stapel: eigener Stand für jeden erfolgreich erstellten Eintrag (nie für übersprungene oder fehlgeschlagene)."""
        saved = self.record(customer_id, label, records, item.path, item.output, area="batch_info")
        if saved is not None and saved[1]:
            self._batch_saved[item.id] = saved[0].id

    def forget_batch_item(self, item_id: str) -> None:
        self._batch_saved.pop(item_id, None)
        self._batch_baselines.pop(item_id, None)
        self._batch_comparisons.pop(item_id, None)
