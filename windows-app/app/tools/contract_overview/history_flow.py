"""Vertragsvergleich in »Vertragsübersichten« (Mixin des Werkzeugs).

* Nach der Excel-Prüfung und mit einer Kundenakte wird der aktuelle Stand mit dem
  zuletzt gespeicherten Vertragsstand dieses Kunden verglichen.
* Ein Stand wird nur nach einer erfolgreich erstellten PDF gespeichert – nie für die
  Vorschau, die Excel-Prüfung, einen Abbruch oder einen Fehler und nie ohne Kundenakte.
* Der Vergleich ist eine reine Anzeige: Er ändert die PDF nicht und löst keine neue
  Vorschau aus.
* Der Stapel nutzt dieselben Stände und denselben Vergleich (kompakte Angaben in der
  Liste, Einzelheiten in der Detailansicht).
* Ohne eingeschaltete Kundenakte gibt es keine sichere Kundenidentität: Dann entsteht kein
  Stand und es wird nichts verglichen (nie über Firmenname, Domain oder E-Mail geraten).
  Gespeicherte Stände bleiben unverändert erhalten.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import appstate
from ui import diagnostics

from .history import report
from .history.compare import compare
from .history.models import ContractComparison, ContractRecord, Snapshot, SnapshotSource, records_from
from .history.repository import FOLDER, HistoryStore, file_sha256

if TYPE_CHECKING:
    from .batch.models import BatchItem

NO_CUSTOMER = "Mit einer Kundenakte speichert PDF Tool nach jedem Erstellen den Vertragsstand und zeigt beim nächsten Mal, was sich geändert hat."
FIRST_SAVED = "Erster Vertragsstand gespeichert. Beim nächsten Excel-Import ist ein Vergleich möglich."
AFTER_EXPORT = "Nach dem Erstellen der PDF wird der aktuelle Stand gespeichert – ab dann zeigt PDF Tool hier neue, entfernte und geänderte Verträge."


def _file_fact(label: str, path: str) -> tuple[str, str, str]:
    if not path:
        return (label, "–", "muted")
    name = Path(path).name or path
    if Path(path).exists():
        return (label, name, "")
    return (label, f"{name} (nicht mehr vorhanden)", "muted")


def snapshot_facts(snapshot: Snapshot) -> list[tuple[str, str, str]]:
    """Datum, Uhrzeit und Herkunft eines Stands – die Dateien selbst werden nicht gebraucht."""
    when = report.stand_label(snapshot)
    if snapshot.export_count > 1:
        when += f" · {snapshot.export_count}× erstellt, zuletzt {snapshot.exported.astimezone().strftime('%d.%m.%Y, %H:%M')}"
    return [("Stand", when, ""), _file_fact("Excel", snapshot.source.excel_path), _file_fact("PDF", snapshot.source.pdf_path)]


def baseline_choices(snapshots: list[Snapshot], latest_before: Snapshot | None, saved: set[str]) -> list[tuple[str, str]]:
    """(Stand-ID, Beschriftung) für »Vergleichen mit«, neueste zuerst. Stände aus derselben
    Minute werden mit Sekunden unterschieden – jede Beschriftung ist eindeutig."""
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


class HistoryFlow:
    """Vertragsstände speichern und vergleichen."""

    def _init_history(self) -> None:
        self.history = HistoryStore(Path(appstate.CONFIG_FILE).parent / FOLDER)
        self.history_version = 0
        self._history_cache: dict[str, list[Snapshot]] = {}
        # Einzelmodus: eine »Sitzung« ist eine Excel mit einer Kundenakte. Stände, die in ihr
        # gespeichert wurden, sind nicht der Ausgangsstand – so bleibt der Vergleich nach dem
        # Erstellen sichtbar, bis eine andere Excel oder ein anderer Kunde gewählt wird.
        self._history_session: tuple = ()
        self._history_saved: set[str] = set()
        self._history_baseline: str | None = None
        self._history_note: tuple[str, str, str] | None = None
        self._history_job = None
        self.comparison: ContractComparison | None = None
        # Schlüssel der gezeigten Anzeige: Neu berechnet wird nur bei geänderten Daten, anderem
        # Kunden, anderem Ausgangsstand oder neuen Ständen – nicht bei jeder Eingabe.
        self._comparison_state: tuple | None = None
        self._comparison_source: dict | None = None
        self.comparison_runs = 0  # berechnete Vergleiche im Einzelmodus (Tests, Diagnose)
        # Stapel: je Eintrag der beim Erstellen gespeicherte Stand und der gewählte Vergleich
        self._batch_saved_snapshot: dict[str, str] = {}
        self._batch_baselines: dict[str, str] = {}
        self._batch_comparisons: dict[str, tuple[tuple, ContractComparison | None]] = {}

    # Gespeicherte Stände ------------------------------------------------------------------------------------
    def history_snapshots(self, customer_id: str | None) -> list[Snapshot]:
        """Stände eines Kunden (neueste zuerst), zwischengespeichert bis zur nächsten Änderung."""
        if not customer_id:
            return []
        if customer_id not in self._history_cache:
            self._history_cache[customer_id] = self.history.snapshots(customer_id)
        return self._history_cache[customer_id]

    def _history_changed(self, customer_id: str | None = None) -> None:
        self.history_version += 1
        if customer_id is None:
            self._history_cache.clear()
        else:
            self._history_cache.pop(customer_id, None)
        self._batch_comparisons.clear()

    def record_contract_state(self, customer_id: str | None, label: str, records: tuple[ContractRecord, ...], excel: str, pdf: str, area: str = "pdf_info") -> tuple[Snapshot, bool, bool] | None:
        """Stand nach einem erfolgreichen Export speichern. Rückgabe: (Stand, neu angelegt, erster Stand)."""
        if not customer_id or not records or not self.customer_records_enabled():
            return None
        first = not self.history_snapshots(customer_id)
        try:
            snapshot, created = self.history.record(customer_id, records, SnapshotSource(excel, file_sha256(excel), pdf), label)
        except (OSError, ValueError) as exc:
            self.write_error_log(f"Vertragsstand konnte nicht gespeichert werden: {type(exc).__name__}: {exc}")
            self.notify(area, "warning", "Die PDF wurde erstellt, der Vertragsstand für den Vergleich konnte aber nicht gespeichert werden. Bitte prüfen, ob der Datenordner beschreibbar ist.", title="Vertragsstand nicht gespeichert", status=False)
            return None
        self._history_changed(customer_id)
        return snapshot, created, first

    def merge_history(self, target_id: str, source_id: str) -> None:
        """Nach dem Zusammenführen von Kundenakten gehören beide Verläufe zum Ziel."""
        try:
            self.history.merge(target_id, source_id)
        except OSError as exc:
            self.write_error_log(f"Vertragsstände konnten nicht zusammengeführt werden: {exc}")
        self._history_changed()

    # Einzelmodus ----------------------------------------------------------------------------------------------
    def current_contracts(self) -> tuple[ContractRecord, ...] | None:
        """Verträge der geprüften Excel mit den aktuellen Zyklus-Regeln (wie in der PDF)."""
        result = self._analysis
        if not result or not result.get("ok") or self._analysis_path != self.var_excel.get().strip():
            return None
        return records_from(result.get("vertraege") or (), self.state.regeln)

    def refresh_comparison(self) -> None:
        """Gesammelt aktualisieren (nach Prüfung, Kundenwechsel, Regeln, Export)."""
        if self._history_job is None:
            try:
                self._history_job = self.after_idle(self._refresh_comparison_now)
            except Exception:  # noqa: BLE001 - Fenster wird geschlossen
                self._history_job = None

    def _refresh_comparison_now(self) -> None:
        self._history_job = None
        view = getattr(self.ui, "comparison", None)
        area = getattr(self.ui, "comparison_area", None)
        if view is None or area is None:
            return
        if not self.customer_records_enabled():
            # Ohne Kundenakte keine Kundenidentität – kein Vergleich, die Karte bleibt verborgen.
            self.comparison = None
            self._comparison_state = None
            if area.expanded:
                area.collapse(animate=False)
            return
        excel = self.var_excel.get().strip()
        result = self._analysis
        if result is None and self._analysis_path and self._analysis_path == excel:
            return  # die Prüfung läuft – die bisherige Anzeige bleibt bis zum Ergebnis stehen
        if not result or not result.get("ok") or self._analysis_path != excel:
            self.comparison = None
            self._comparison_state = None
            if area.expanded:
                area.collapse(animate=False)
            return
        customer = self.active_customer()
        if customer is not None:
            session = (customer.id, excel)
            if session != self._history_session:
                self._history_session = session
                self._history_saved = set()
                self._history_baseline = None
                self._history_note = None
        state = (
            customer.id if customer is not None else None,
            excel,
            id(result),
            json.dumps(self.state.regeln, sort_keys=True, default=str),
            self.history_version,
            self._history_baseline,
            tuple(sorted(self._history_saved)),
            self._history_note,
        )
        if state == self._comparison_state and area.expanded:
            return  # nichts geändert: keine Berechnung, keine neue Anzeige
        self._comparison_state = state
        self._comparison_source = result  # hält das Ergebnis fest (die id im Schlüssel bleibt eindeutig)
        contracts = records_from(result.get("vertraege") or (), self.state.regeln)
        if customer is None:
            self.comparison = None
            view.show_message("info", NO_CUSTOMER, "Vertragsvergleich")
        else:
            snapshots = self.history_snapshots(customer.id)
            earlier = [snapshot for snapshot in snapshots if snapshot.id not in self._history_saved]
            if not earlier:
                self.comparison = None
                if self._history_note is not None:
                    view.show_message(*self._history_note)
                else:
                    view.show_message("info", f"{report.NO_HISTORY} {AFTER_EXPORT}", "Vertragsvergleich")
            else:
                baseline = next((s for s in snapshots if s.id == self._history_baseline), None) or earlier[0]
                self.comparison = compare(baseline, contracts)
                self.comparison_runs += 1
                diagnostics.count("comparison")
                view.show_comparison(self.comparison, baseline_choices(snapshots, earlier[0], self._history_saved), baseline.id, snapshot_facts(baseline), self._history_note)
        if not area.expanded:
            area.expand(animate=False)

    def choose_baseline(self, snapshot_id: str) -> None:
        self._history_baseline = snapshot_id
        self._refresh_comparison_now()

    def copy_comparison(self) -> None:
        comparison = self.comparison
        if comparison is None:
            return
        customer = self.active_customer()
        self._copy_text(report.comparison_text(comparison, customer.label if customer is not None else ""), "Änderungen kopiert.")

    def _copy_text(self, text: str, done: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception as exc:  # noqa: BLE001 - Zwischenablage nicht verfügbar
            self.set_status(f"Kopieren nicht möglich: {exc}", "error")
            return
        self.set_status(done, "success")

    def _history_after_export(self, customer_id: str | None, label: str, records: tuple[ContractRecord, ...], excel: str, pdf: Path) -> None:
        """Einzelmodus: Stand der gerade erstellten PDF speichern und die Anzeige anpassen."""
        saved = self.record_contract_state(customer_id, label, records, excel, str(pdf))
        if saved is None:
            self.refresh_comparison()
            return
        snapshot, created, first = saved
        customer = self.active_customer()
        if customer is not None and customer.id == customer_id and self._history_session == (customer_id, self.var_excel.get().strip()):
            if created:
                self._history_saved.add(snapshot.id)
            if first:
                self._history_note = ("success", FIRST_SAVED, "Vertragsstand gespeichert")
        self.refresh_comparison()

    # Stapel -------------------------------------------------------------------------------------------------
    def batch_comparison(self, item: "BatchItem") -> ContractComparison | None:
        """Vergleich eines Stapel-Eintrags mit dem Stand seiner Kundenakte (zwischengespeichert)."""
        if not self.customer_records_enabled() or item.analysis is None or not item.analysis.ok:
            return None
        res = self.batch_resolution(item.id)
        customer = res.customer if res is not None else None
        if customer is None:
            return None
        rules = (res.fields or {}).get("regeln") if res.fields else None
        if rules is None:
            rules = self.batch_defaults().regeln
        saved = self._batch_saved_snapshot.get(item.id)
        chosen = self._batch_baselines.get(item.id)
        key = (item.stamp, customer.id, json.dumps(rules, sort_keys=True, default=str), self.history_version, saved, chosen)
        cached = self._batch_comparisons.get(item.id)
        if cached is not None and cached[0] == key:
            return cached[1]
        snapshots = self.history_snapshots(customer.id)
        earlier = [snapshot for snapshot in snapshots if snapshot.id != saved]
        baseline = next((s for s in snapshots if s.id == chosen), None) or (earlier[0] if earlier else None)
        comparison = compare(baseline, records_from(item.analysis.contracts, rules)) if baseline is not None else None
        self._batch_comparisons[item.id] = (key, comparison)
        return comparison

    def batch_comparison_badges(self, item: "BatchItem") -> str:
        return report.badges(self.batch_comparison(item))

    def batch_choose_baseline(self, item_id: str, snapshot_id: str) -> None:
        self._batch_baselines[item_id] = snapshot_id
        self._batch_changed(item_ids=(item_id,))

    def batch_copy_comparison(self, item_id: str) -> None:
        item = self.batch_by_id.get(item_id)
        comparison = self.batch_comparison(item) if item is not None else None
        if comparison is None:
            return
        res = self.batch_resolution(item_id)
        label = res.customer.label if res is not None and res.customer is not None else ""
        self._copy_text(report.comparison_text(comparison, label), "Änderungen kopiert.")

    def _history_after_batch_item(self, item: "BatchItem", customer_id: str | None, records: tuple[ContractRecord, ...]) -> None:
        """Stapel: eigener Stand für jeden erfolgreich erstellten Eintrag (nie für übersprungene oder fehlgeschlagene)."""
        customer = self.customers.get(customer_id) if customer_id else None
        saved = self.record_contract_state(customer_id, customer.label if customer is not None else "", records, item.path, item.output, area="batch_info")
        if saved is not None and saved[1]:
            self._batch_saved_snapshot[item.id] = saved[0].id
