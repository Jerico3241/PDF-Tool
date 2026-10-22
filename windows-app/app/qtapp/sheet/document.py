"""Eine geöffnete Tabelle (in QML: ``Reader.sheet``): Blätter, Auswahl, Eingabe, Formate, Daten, Diagramme, Speichern.

Der Inhalt lebt im Rechenkern (LibreOffice); hier liegen nur die angezeigten Zellen und der Aufbau der Blätter
(``model``). Jede Änderung geht als Befehl an den Kern (``CalcService``) und lädt danach, was sich geändert haben
kann – bis dahin zeigt das Raster den bisherigen Stand. Der Tab gehört zum Reader (gleiche Tab-Leiste, Schließen,
»Zuletzt verwendet«, letzte Sitzung); dafür hat ``SheetController`` dieselben Grundzüge wie ein PDF-Dokument
(``ident``, ``name``, ``path``, ``dirty``, ``save``, ``shutdown``).
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from tools.pdf_editor import office
from tools.sheet import engine as calc

from ..base import Observable, prop
from . import model
from .model import Cells, Layout, block_range

ROW_CHUNK = 1000  # Zeilenhöhen in Stücken laden
MAX_ZOOM, MIN_ZOOM = 400, 25
ZOOM_STEPS = (25, 50, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400)
STATS_DELAY_MS = 120
SAVE_FILTER = (
    "Excel-Arbeitsmappe (*.xlsx);;Excel-Arbeitsmappe mit Makros (*.xlsm);;Excel 97–2003 (*.xls);;"
    "OpenDocument-Tabelle (*.ods);;CSV (Trennzeichen-getrennt) (*.csv)"
)
SAVE_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".ods", ".csv")
FORMAT_KEYS = ("bold", "italic", "underline", "strike", "font", "size", "color", "background", "halign", "valign", "wrap")


def _log():
    return logging.getLogger("pdftool.tabelle")


class SheetController(Observable):
    nameChanged, name = prop(str, "name", "")
    pathChanged, path = prop(str, "path", "")
    dirtyChanged, dirty = prop(bool, "dirty", False)
    savingChanged, saving = prop(bool, "saving", False)
    busyChanged, busy = prop(bool, "busy", False)
    readyChanged, ready = prop(bool, "ready", False)  # geöffnet und erstes Bild geladen
    sheetsChanged, sheets = prop(list, "sheets", [])  # [{name, visible, color}]
    activeSheetChanged, activeSheet = prop(int, "activeSheet", 0)
    cursorRowChanged, cursorRow = prop(int, "cursorRow", 0)
    cursorColChanged, cursorCol = prop(int, "cursorCol", 0)
    selectionChanged, selection = prop(list, "selection", [0, 0, 0, 0])  # [Zeile, Spalte, letzte Zeile, letzte Spalte]
    cellNameChanged, cellName = prop(str, "cellName", "A1")  # Namenfeld: »D6« bzw. »A1:C4«
    cellInputChanged, cellInput = prop(str, "cellInput", "")  # Formelzeile: Eingabe der aktiven Zelle
    cellStyleChanged, cellStyle = prop(dict, "cellStyle", {})  # Format der aktiven Zelle (für die Knöpfe)
    formatKindChanged, formatKind = prop(str, "formatKind", "standard")
    mergedChanged, merged = prop(bool, "merged", False)
    statsChanged, stats = prop(dict, "stats", {})  # {sum, count, numbers, average}
    undoTextChanged, undoText = prop(str, "undoText", "")
    redoTextChanged, redoText = prop(str, "redoText", "")
    zoomChanged, zoom = prop(int, "zoom", 100)
    freezeChanged, freeze = prop(list, "freeze", [0, 0])
    filterOnChanged, filterOn = prop(bool, "filterOn", False)
    objectsChanged, objects = prop(list, "objects", [])  # Diagramme und Bilder des Blatts
    filterMenuChanged, filterMenu = prop(dict, "filterMenu", {})  # {col, values: [{text, checked}]}
    functionListChanged, functionList = prop(list, "functionList", [])
    findTextChanged, findText = prop(str, "findText", "")
    findResultChanged, findResult = prop(str, "findResult", "")
    revisionChanged, revision = prop(int, "revision", 0)  # Raster neu zeichnen
    layoutRevisionChanged, layoutRevision = prop(int, "layoutRevision", 0)  # Größen/Aufbau neu
    csvChanged, csv = prop(bool, "csv", False)

    contentChanged = Signal()
    editRequested = Signal(str)  # Bearbeiten beginnen (mit diesem Text, »« = bisheriger Inhalt)
    editEmptyRequested = Signal()  # Rücktaste: leer bearbeiten (wie Excel)
    cursorMoved = Signal()  # aktive Zelle sichtbar machen
    findRequested = Signal()  # Strg+F: Suchleiste zeigen

    def __init__(self, reader, service, ident: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.reader = reader
        self.app = reader.app
        self.service = service
        self.ident = ident
        self.sourcePath = ""  # wie ein PDF-Dokument ohne umgewandelte Quelle
        self.panels: dict = {}
        self.currentPage = 0
        self.pageCount = 0
        self.isSheet = True
        self.session = None  # kein PDF (der Reader rendert für Tabellen keine Seiten)
        self.doc = 0  # Nummer im Rechenkern
        self.generation = 0
        self.layouts: dict[int, Layout] = {}
        self.cells: dict[int, Cells] = {}
        self.styles: dict[int, dict] = {}
        self._row_chunks: dict[int, set[int]] = {}
        self._pending: set = set()
        self._viewport = (0, 0, 40, 15)
        self._anchor = (0, 0)
        self._end = (0, 0)
        self._closing = False
        self._closed = False
        self._copied_text = ""
        self._input_cell: tuple | None = None  # (Zeile, Spalte, Blatt), zu der ``cellInput`` gehört
        self._images: dict = {}
        self._save_then: list[Callable[[bool], None]] = []
        self._object_revision = 0
        self.password: str | None = None
        self.csv_options = ""
        service.lost.connect(self._engine_lost)

    # Gemeinsame Grundzüge mit PDF-Dokumenten (für den Reader) ---------------------------------------------------
    @property
    def busy_saving(self) -> bool:
        return self.saving

    def goTo(self, _page: int) -> None:  # noqa: N802
        pass

    def write_recovery_now(self) -> None:
        pass

    def layout(self) -> Layout:
        layout = self.layouts.get(self.activeSheet)
        if layout is None:
            layout = self.layouts[self.activeSheet] = Layout()
        return layout

    def sheet_cells(self) -> Cells:
        cells = self.cells.get(self.activeSheet)
        if cells is None:
            cells = self.cells[self.activeSheet] = Cells()
        return cells

    # Öffnen ----------------------------------------------------------------------------------------------------------
    def open(self, path: str, done: Callable[[], None], failed: Callable[[BaseException], None], password: str | None = None) -> None:
        """Datei im Rechenkern öffnen (``path`` leer: neue Tabelle). ``done``/``failed`` im GUI-Thread."""
        self.path = path
        self.name = Path(path).name if path else self.name or "Mappe1.xlsx"
        self.password = password
        self.csv_options = office.csv_options(Path(path)) if path else ""
        self.csv = bool(self.csv_options)
        args = {"path": str(Path(path).resolve())} if path else {}
        if path and self.csv_options:
            args["csv"] = self.csv_options
        if password:
            args["password"] = password

        def opened(result: dict) -> None:
            if self._closed:
                self.service.submit("close", {"doc": result["doc"]})
                return
            self.doc = int(result["doc"])
            self.generation = self.service.generation
            self._apply_state(result, adopt_active=True)
            self._load_layout(then=lambda: self._first_view(done), failed=failed)

        self.service.submit("open" if path else "new", args, opened, failed)

    def _first_view(self, done: Callable[[], None]) -> None:
        self.ready = True
        self.select(0, 0, False)
        self.request_visible()
        done()

    def _call(self, command: str, args: dict | None = None, done: Callable | None = None, failed: Callable | None = None,
              *, quiet: bool = False) -> None:
        """Befehl für dieses Dokument (Nummer und Blatt ergänzt). Fehler: Hinweis, außer ``quiet``."""
        if self._closed or not self.doc:
            return
        payload = {"doc": self.doc, "sheet": self.activeSheet}
        payload.update(args or {})

        def error(exc: BaseException) -> None:
            if failed is not None:
                failed(exc)
            if quiet or self._closed:
                return
            if isinstance(exc, calc.EngineGone):
                return  # meldet ``_engine_lost``
            message = str(exc) if isinstance(exc, calc.CalcError) else "Das hat nicht geklappt."
            self.app.notify("reader", "warning", message, title=self.name, auto_hide=8000)

        def finished(result) -> None:
            if not self._closed and done is not None:
                done(result)

        self.service.submit(command, payload, finished, error, generation=self.generation)

    def _change(self, command: str, args: dict | None = None, *, layout: bool = False, then: Callable[[dict], None] | None = None,
                status: str = "") -> None:
        """Ändernder Befehl: danach Zustand, sichtbare Zellen (und mit ``layout`` den Aufbau) neu laden."""
        self.busy = True

        def done(result) -> None:
            self.busy = False
            if isinstance(result, dict):
                self._apply_state(result)
            self.refresh(layout=layout)
            if status:
                self.app.set_status(status, "success")
            if then is not None:
                then(result if isinstance(result, dict) else {})

        def failed(_exc: BaseException) -> None:
            self.busy = False
            self.refresh(layout=True)

        self._call(command, args, done, failed)

    def _apply_state(self, state: dict, *, adopt_active: bool = False) -> None:
        """Zustand aus einer Antwort übernehmen. Das aktive Blatt nur beim Öffnen: Danach bestimmt es die Oberfläche
        (eine Antwort, die vor einem Blattwechsel abgeschickt wurde, setzte sonst das alte Blatt zurück)."""
        if "sheets" in state:
            sheets = list(state["sheets"])
            if [s.get("name") for s in sheets] != [s.get("name") for s in self.sheets]:
                # Blätter umbenannt, verschoben, gelöscht oder neu: zwischengespeicherte Blätter verwerfen
                self.layouts = {}
                self.cells = {}
                self._row_chunks = {}
            self.sheets = sheets
            if sheets and not adopt_active and self.activeSheet >= len(sheets):
                adopt_active = True  # das gezeigte Blatt gibt es nicht mehr (z. B. »Rückgängig« nach »Blatt einfügen«)
        if adopt_active and "active" in state and int(state["active"]) != self.activeSheet and 0 <= int(state["active"]) < max(1, len(self.sheets)):
            self.activeSheet = int(state["active"])
        if "modified" in state:
            was = self.dirty
            self.dirty = bool(state["modified"])
            if was != self.dirty:
                self.reader.tab_changed(self)
        self.undoText = str(state.get("undo") or "") if "undo" in state else self.undoText
        self.redoText = str(state.get("redo") or "") if "redo" in state else self.redoText

    # Laden ---------------------------------------------------------------------------------------------------------
    def _load_layout(self, then: Callable[[], None] | None = None, failed: Callable[[BaseException], None] | None = None) -> None:
        sheet = self.activeSheet

        def done(data: dict) -> None:
            layout = self.layouts.setdefault(sheet, Layout())
            layout.apply(data)
            self._row_chunks[sheet] = set()
            if sheet == self.activeSheet:
                self.freeze = list(layout.freeze)
                self.filterOn = layout.filter is not None
                self._set_objects(layout.objects)
                self.layoutRevision += 1
                self._ensure_rows()
            if then is not None:
                then()

        self._call("sheet", {"sheet": sheet}, done, failed, quiet=then is None or failed is not None)

    def _ensure_rows(self) -> None:
        r0, _c0, r1, _c1 = self._viewport
        sheet = self.activeSheet
        loaded = self._row_chunks.setdefault(sheet, set())
        for chunk in range(r0 // ROW_CHUNK, r1 // ROW_CHUNK + 1):
            key = ("rows", sheet, chunk)
            if chunk in loaded or key in self._pending:
                continue
            self._pending.add(key)

            def done(data: dict, key=key, chunk=chunk, sheet=sheet) -> None:
                self._pending.discard(key)
                layout = self.layouts.get(sheet)
                if layout is None:
                    return
                layout.apply_rows(data)
                self._row_chunks.setdefault(sheet, set()).add(chunk)
                if sheet == self.activeSheet:
                    self.layoutRevision += 1

            self._call("rows", {"sheet": sheet, "start": chunk * ROW_CHUNK, "end": chunk * ROW_CHUNK + ROW_CHUNK - 1},
                       done, lambda _exc, key=key: self._pending.discard(key), quiet=True)

    def set_viewport(self, r0: int, c0: int, r1: int, c1: int) -> None:
        """Vom Raster: sichtbarer Bereich (samt fixierter Zeilen und Spalten) – fehlende Zellen nachladen."""
        self._viewport = (max(0, r0), max(0, c0), max(0, r1), max(0, c1))
        self.request_visible()

    def request_visible(self) -> None:
        if not self.ready and not self.doc:
            return
        r0, c0, r1, c1 = self._viewport
        layout = self.layout()
        rows, cols = layout.freeze
        sheet = self.activeSheet
        cells = self.sheet_cells()
        wanted = cells.missing(r0, c0, r1 + 8, c1 + 2)
        if rows:
            wanted += [b for b in cells.missing(0, c0, rows - 1, c1 + 2) if b not in wanted]
        if cols:
            wanted += [b for b in cells.missing(r0, 0, r1 + 8, cols - 1) if b not in wanted]
        for block in wanted:
            key = ("cells", sheet, block)
            if key in self._pending:
                continue
            self._pending.add(key)

            def done(data: dict, key=key, sheet=sheet) -> None:
                self._pending.discard(key)
                self._take_styles(data.get("styles") or {})
                self.cells.setdefault(sheet, Cells()).apply(data)
                if sheet == self.activeSheet:
                    self.revision += 1
                    self.contentChanged.emit()

            self._call("cells", {"sheet": sheet, "range": block_range(block)}, done, lambda _exc, key=key: self._pending.discard(key), quiet=True)
        self._ensure_rows()

    def _take_styles(self, styles: dict) -> None:
        for key, value in styles.items():
            self.styles[int(key)] = value

    def refresh(self, layout: bool = False) -> None:
        """Nach einer Änderung: sichtbare Zellen (veraltet, bis neu geladen), aktive Zelle, Statuszeile – mit ``layout``
        auch Aufbau und Zeilenhöhen."""
        self.sheet_cells().invalidate()
        self._pending = {key for key in self._pending if key[0] not in ("cells", "rows")}
        self._row_chunks[self.activeSheet] = set()
        if layout:
            self._load_layout()
        else:
            self._ensure_rows()
        self.request_visible()
        self._load_cell()
        self._schedule_stats()

    # Auswahl ---------------------------------------------------------------------------------------------------------
    @Slot(int, int, bool)
    def select(self, row: int, col: int, extend: bool) -> None:
        layout = self.layout()
        row = max(0, min(layout.max_rows - 1, row))
        col = max(0, min(layout.max_cols - 1, col))
        merge = layout.merge_of(row, col)
        if extend:
            self._end = (row, col)
        else:
            if merge is not None:
                row, col = merge[0], merge[1]
            self._anchor = self._end = (row, col)
        self._update_selection()

    @Slot(int, int, int, int)
    def selectRange(self, r0: int, c0: int, r1: int, c1: int) -> None:  # noqa: N802
        self._anchor = (max(0, r0), max(0, c0))
        self._end = (max(0, r1), max(0, c1))
        self._update_selection()

    @Slot()
    def selectAll(self) -> None:  # noqa: N802
        layout = self.layout()
        self._anchor = (0, 0)
        self._end = (layout.max_rows - 1, layout.max_cols - 1)
        self._update_selection(keep_cursor=True)

    @Slot(int, bool)
    def selectColumn(self, col: int, extend: bool) -> None:  # noqa: N802
        layout = self.layout()
        if extend:
            self._anchor = (0, self._anchor[1])
            self._end = (layout.max_rows - 1, col)
        else:
            self._anchor = (0, col)
            self._end = (layout.max_rows - 1, col)
        self._update_selection()

    @Slot(int, bool)
    def selectRow(self, row: int, extend: bool) -> None:  # noqa: N802
        layout = self.layout()
        if extend:
            self._anchor = (self._anchor[0], 0)
            self._end = (row, layout.max_cols - 1)
        else:
            self._anchor = (row, 0)
            self._end = (row, layout.max_cols - 1)
        self._update_selection()

    def _update_selection(self, keep_cursor: bool = False) -> None:
        layout = self.layout()
        (ar, ac), (er, ec) = self._anchor, self._end
        r0, c0, r1, c1 = min(ar, er), min(ac, ec), max(ar, er), max(ac, ec)
        r0, c0, r1, c1 = layout.expand(r0, c0, r1, c1)
        self.selection = [r0, c0, r1, c1]
        row, col = self._anchor
        moved = (row, col) != (self.cursorRow, self.cursorCol)
        self.cursorRow, self.cursorCol = row, col
        if r0 == r1 and c0 == c1 or layout.merge_at.get((r0, c0)) == (r0, c0, r1, c1):
            self.cellName = calc.cell_name(row, col)
        elif r0 == 0 and r1 == layout.max_rows - 1:
            self.cellName = f"{calc.column_name(c0)}:{calc.column_name(c1)}"
        elif c0 == 0 and c1 == layout.max_cols - 1:
            self.cellName = f"{r0 + 1}:{r1 + 1}"
        else:
            self.cellName = f"{calc.cell_name(r0, c0)}:{calc.cell_name(r1, c1)}"
        self.revision += 1
        self.contentChanged.emit()
        if moved or not keep_cursor:
            self._load_cell()
        self._schedule_stats()

    def _load_cell(self) -> None:
        row, col = self.cursorRow, self.cursorCol
        cached = self.sheet_cells().get(row, col)
        sheet = self.activeSheet
        if cached is not None and cached[1] in ("t",) and not cached[0].startswith("="):
            self.cellInput = cached[0]
            self._input_cell = (row, col, sheet)
        else:
            self._input_cell = None  # Inhalt noch unbekannt: »Eingabe übernehmen« gilt dann immer als Änderung

        def done(data: dict) -> None:
            if (row, col, sheet) != (self.cursorRow, self.cursorCol, self.activeSheet):
                return
            self.cellInput = str(data.get("input") or "")
            self._input_cell = (row, col, sheet)
            style = dict(data.get("style") or {})
            self.cellStyle = style
            self.formatKind = str(data.get("formatKind") or "standard")
            merged = data.get("merged") or [row, col, row, col]
            self.merged = merged[0] != merged[2] or merged[1] != merged[3]

        self._call("cell", {"row": row, "col": col}, done, quiet=True)

    def _schedule_stats(self) -> None:
        self.app.timers.later(f"sheet:stats:{self.ident}", STATS_DELAY_MS, self._load_stats)

    def _load_stats(self) -> None:
        if self._closed:
            return
        r0, c0, r1, c1 = self.selection
        if r0 == r1 and c0 == c1:
            self.stats = {}
            return
        selection = list(self.selection)

        def done(data: dict) -> None:
            if selection == self.selection:
                self.stats = dict(data or {})

        self._call("stats", {"range": selection}, done, quiet=True)

    @Slot(int, int, bool)
    def move(self, dr: int, dc: int, extend: bool) -> None:
        """Pfeiltasten: aktive Zelle (bzw. mit Umschalt das Ende der Auswahl) um eine Zelle – über verbundene Zellen
        und ausgeblendete Zeilen/Spalten hinweg."""
        layout = self.layout()
        row, col = self._end if extend else self._anchor
        merge = layout.merge_of(row, col)
        if merge is not None and not extend:
            if dr > 0:
                row = merge[2]
            if dc > 0:
                col = merge[3]
        row = layout.rows.visible(row + dr, dr or 1, layout.max_rows) if dr else row
        col = layout.cols.visible(col + dc, dc or 1, layout.max_cols) if dc else col
        self.select(row, col, extend)
        self.cursorMoved.emit()

    @Slot(int, int, bool)
    def jump(self, dr: int, dc: int, extend: bool) -> None:
        """Strg+Pfeil: zum Rand des Datenbereichs (wie Excel)."""
        row, col = self._end if extend else self._anchor

        def done(data: dict) -> None:
            self.select(int(data["row"]), int(data["col"]), extend)
            self.cursorMoved.emit()

        self._call("edge", {"row": row, "col": col, "dr": dr, "dc": dc}, done, quiet=True)

    @Slot(int, bool)
    def page(self, rows: int, extend: bool) -> None:
        self.move(rows, 0, extend)

    @Slot(str, result=bool)
    def goToName(self, text: str) -> bool:  # noqa: N802
        """Namenfeld: »B12« oder »A1:C5« auswählen."""
        found = calc.parse_range(text)
        if found is None:
            self.app.set_status(f"»{text}« ist keine Zelle (z. B. B12 oder A1:C5).", "warning")
            return False
        layout = self.layout()
        r0, r1 = (min(value, layout.max_rows - 1) for value in found[0::2])
        c0, c1 = (min(value, layout.max_cols - 1) for value in found[1::2])
        self._anchor, self._end = (r0, c0), (r1, c1)
        self._update_selection()
        self.cursorMoved.emit()
        return True

    # Eingabe ---------------------------------------------------------------------------------------------------------
    @Slot(str, int, int)
    def commit(self, text: str, dr: int, dc: int) -> None:
        """Eingabe in die aktive Zelle übernehmen und weiter (Eingabe: nach unten, Tab: nach rechts)."""
        row, col = self.cursorRow, self.cursorCol
        old = self.sheet_cells().get(row, col)
        known = self._input_cell == (row, col, self.activeSheet)
        unchanged = known and text == self.cellInput and (old is not None or text == "")
        if not unchanged:
            self.sheet_cells().put_text(row, col, text)
            self.cellInput = text
            self._input_cell = (row, col, self.activeSheet)
            self.revision += 1
            self.contentChanged.emit()
            self._mark_dirty()
            self._change("input", {"row": row, "col": col, "text": text})
        if dr or dc:
            r0, c0, r1, c1 = self.selection
            if (r0, c0) != (r1, c1) and not (self.layout().merge_at.get((r0, c0)) == (r0, c0, r1, c1)):
                # Eingabe in einer Auswahl: innerhalb der Auswahl weiter (wie Excel)
                nr, nc = row + dr, col + dc
                if nr > r1:
                    nr, nc = r0, nc + 1
                elif nr < r0:
                    nr, nc = r1, nc - 1
                if nc > c1:
                    nc, nr = c0, (nr + 1 if dc else nr)
                elif nc < c0:
                    nc, nr = c1, (nr - 1 if dc else nr)
                if nr > r1:
                    nr = r0
                elif nr < r0:
                    nr = r1
                self._anchor = (nr, nc)
                self.cellName = calc.cell_name(nr, nc)
                self.cursorRow, self.cursorCol = nr, nc
                self.revision += 1
                self.contentChanged.emit()
                self._load_cell()
                return
            self.move(dr, dc, False)

    def _mark_dirty(self) -> None:
        """Sofort »ungespeichert« – nicht erst mit der Antwort des Kerns (Schließen direkt nach der Eingabe fragt sonst
        nicht nach)."""
        if not self.dirty:
            self.dirty = True
            self.reader.tab_changed(self)

    @Slot()
    def startEdit(self) -> None:  # noqa: N802
        self.editRequested.emit("")

    @Slot(str)
    def typeText(self, text: str) -> None:  # noqa: N802
        self.editRequested.emit(text)

    @Slot()
    def clearAndEdit(self) -> None:  # noqa: N802
        """Rücktaste: Inhalt löschen und die Zelle leer bearbeiten."""
        self.clearContents()
        self.editEmptyRequested.emit()

    @Slot()
    def clearContents(self) -> None:  # noqa: N802
        """Entf: Inhalte der Auswahl löschen (Formate bleiben)."""
        r0, c0, r1, c1 = self.selection
        cells = self.sheet_cells()
        for (row, col), value in list(cells.values.items()):
            if r0 <= row <= r1 and c0 <= col <= c1:
                cells.values[(row, col)] = ("", " ", value[2])
        self.revision += 1
        self.contentChanged.emit()
        self._mark_dirty()
        self._change("clear", {"range": self.selection, "what": "contents"})

    @Slot(str)
    def clear(self, what: str) -> None:
        """Löschen: »contents«, »formats« oder »all«."""
        self._change("clear", {"range": self.selection, "what": what}, layout=what != "contents")

    # Zwischenablage --------------------------------------------------------------------------------------------------
    @Slot()
    def copy(self) -> None:
        self._copy(False)

    @Slot()
    def cut(self) -> None:
        self._copy(True)

    def _copy(self, cut: bool) -> None:
        def done(data: dict) -> None:
            text = str(data.get("text") or "")
            self._copied_text = text
            SheetController.last_copied = text
            SheetController.clip_owner = self
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(text)
            self.app.set_status("Ausgeschnitten – an der Zielzelle einfügen." if cut else "Kopiert.", "success")

        self._call("copy", {"range": self.selection, "cut": cut}, done)

    @Slot()
    def paste(self) -> None:
        from PySide6.QtGui import QGuiApplication

        text = QGuiApplication.clipboard().text()
        row, col = self.cursorRow, self.cursorCol
        mine = text and text.replace("\r\n", "\n") == SheetController.last_copied.replace("\r\n", "\n") if SheetController.last_copied else False
        if mine:
            def pasted(result: dict) -> None:
                area = result.get("pasted")
                if area:
                    self.selectRange(area[0], area[1], area[2], area[3])

            def fallback(exc: BaseException) -> None:
                if isinstance(exc, calc.CalcError) and exc.code == "zwischenablage":
                    self._paste_text(text, row, col)

            self.busy = True

            def done(result: dict) -> None:
                self.busy = False
                self._apply_state(result)
                self.refresh(layout=True)
                pasted(result)

            def failed(exc: BaseException) -> None:
                self.busy = False
                fallback(exc)

            self._call("paste", {"row": row, "col": col, "text": text}, done, failed, quiet=True)
            return
        if text:
            self._paste_text(text, row, col)

    def _paste_text(self, text: str, row: int, col: int) -> None:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        rows = [line.split("\t") for line in lines]
        if not rows:
            return

        def then(result: dict) -> None:
            area = result.get("pasted")
            if area:
                self.selectRange(area[0], area[1], area[2], area[3])

        self._change("paste_text", {"row": row, "col": col, "rows": rows}, layout=True, then=then)

    @Slot(int, int)
    def fillTo(self, row: int, col: int) -> None:  # noqa: N802
        """Ausfüllkästchen bis (``row``, ``col``) gezogen: die Auswahl als Reihe fortsetzen (nach unten bzw. rechts)."""
        r0, c0, r1, c1 = self.selection
        if row > r1:
            area, direction, source = [r0, c0, row, c1], "down", r1 - r0 + 1
        elif col > c1:
            area, direction, source = [r0, c0, r1, col], "right", c1 - c0 + 1
        elif row < r0:
            area, direction, source = [row, c0, r1, c1], "up", r1 - r0 + 1
        elif col < c0:
            area, direction, source = [r0, col, r1, c1], "left", c1 - c0 + 1
        else:
            return
        self.selectRange(area[0], area[1], area[2], area[3])
        self._change("fill", {"range": area, "direction": direction, "source": source}, layout=True)

    @Slot(str)
    def fill(self, direction: str) -> None:
        """Strg+U / Strg+R: erste Zeile bzw. Spalte der Auswahl nach unten bzw. rechts übernehmen."""
        self._change("fill", {"range": self.selection, "direction": direction}, layout=True)

    # Formate ---------------------------------------------------------------------------------------------------------
    @Slot(str, "QVariant")
    def setFormat(self, key: str, value) -> None:  # noqa: N802
        if key not in FORMAT_KEYS:
            return
        if key in ("bold", "italic", "underline", "strike", "wrap"):
            value = bool(value)
        style = dict(self.cellStyle)
        style[key] = value
        self.cellStyle = style
        self._change("format", {"range": self.selection, "set": {key: value}}, layout=key in ("size", "font", "wrap"))

    @Slot(str)
    def toggle(self, key: str) -> None:
        self.setFormat(key, not bool(self.cellStyle.get(key)))

    @Slot(str)
    def numberFormat(self, kind: str) -> None:  # noqa: N802
        self.formatKind = kind
        self._change("number_format", {"range": self.selection, "kind": kind})

    @Slot(int)
    def decimals(self, delta: int) -> None:
        self._change("number_format", {"range": self.selection, "decimals": int(delta)})

    @Slot(str)
    def borders(self, preset: str) -> None:
        self._change("borders", {"range": self.selection, "preset": preset})

    @Slot()
    def toggleMerge(self) -> None:  # noqa: N802
        """Verbinden und zentrieren (bzw. Verbindung aufheben)."""
        r0, c0, r1, c1 = self.selection
        if self.merged:
            self._change("merge", {"range": self.selection, "merge": False}, layout=True)
            return
        if r0 == r1 and c0 == c1:
            return

        def center(_result: dict) -> None:
            self._change("format", {"range": [r0, c0, r0, c0], "set": {"halign": "center", "valign": "center"}})

        self._change("merge", {"range": self.selection, "merge": True}, layout=True, then=center)

    # Zeilen und Spalten ----------------------------------------------------------------------------------------------
    @Slot(str, bool)
    def insertCells(self, axis: str, delete: bool) -> None:  # noqa: N802
        """Zeilen (»rows«) bzw. Spalten (»cols«) der Auswahl einfügen (davor) oder löschen."""
        r0, c0, r1, c1 = self.selection
        at, count = (r0, r1 - r0 + 1) if axis == "rows" else (c0, c1 - c0 + 1)
        layout = self.layout()
        if axis == "rows" and count >= layout.max_rows or axis == "cols" and count >= layout.max_cols:
            count = (layout.used_rows if axis == "rows" else layout.used_cols) or 1
        self._change("insert", {"axis": axis, "at": at, "count": count, "delete": bool(delete)}, layout=True)

    @Slot(str, int, float)
    def resize(self, axis: str, index: int, pixels: float) -> None:
        """Breite einer Spalte bzw. Höhe einer Zeile (Pixel bei 100 %) – bei einer Auswahl ganzer Spalten/Zeilen für
        alle ausgewählten."""
        indexes = self._axis_indexes(axis, index)
        layout = self.layout()
        for i in indexes:
            (layout.rows if axis == "rows" else layout.cols).set_sizes([max(0.0, float(pixels))], i)
        self.layoutRevision += 1
        self._change("size", {"axis": axis, "indexes": indexes, "size": model.mm100(pixels)}, layout=True)

    @Slot(str, int)
    def autoFit(self, axis: str, index: int) -> None:  # noqa: N802
        self._change("size", {"axis": axis, "indexes": self._axis_indexes(axis, index), "optimal": True}, layout=True)

    @Slot(str, bool)
    def hideCells(self, axis: str, hidden: bool) -> None:  # noqa: N802
        r0, c0, r1, c1 = self.selection
        indexes = list(range(r0, r1 + 1)) if axis == "rows" else list(range(c0, c1 + 1))
        if hidden is False:
            # Einblenden: auch die Nachbarn der Auswahl (ausgeblendete liegen meist dazwischen)
            indexes = list(range(max(0, indexes[0] - 1), indexes[-1] + 2))
        self._change("size", {"axis": axis, "indexes": indexes[:5000], "hidden": bool(hidden)}, layout=True)

    def _axis_indexes(self, axis: str, index: int) -> list[int]:
        r0, c0, r1, c1 = self.selection
        layout = self.layout()
        if axis == "cols" and r0 == 0 and r1 == layout.max_rows - 1 and c0 <= index <= c1:
            return list(range(c0, c1 + 1))[:1000]
        if axis == "rows" and c0 == 0 and c1 == layout.max_cols - 1 and r0 <= index <= r1:
            return list(range(r0, r1 + 1))[:5000]
        return [index]

    # Daten -----------------------------------------------------------------------------------------------------------
    @Slot(bool)
    def sort(self, ascending: bool) -> None:
        self._change("sort", {"range": self.selection, "col": self.cursorCol, "ascending": bool(ascending)}, layout=True,
                     status="Sortiert." if ascending else "Absteigend sortiert.")

    @Slot()
    def toggleFilter(self) -> None:  # noqa: N802
        self._change("autofilter", {"range": self.selection, "on": not self.filterOn}, layout=True)

    @Slot(int)
    def openFilter(self, col: int) -> None:  # noqa: N802
        def done(data: dict) -> None:
            self.filterMenu = {"col": int(data.get("col", col)), "values": list(data.get("values") or []), "name": calc.column_name(col)}

        self._call("filter_values", {"col": col}, done)

    @Slot(int, "QVariant")
    def applyFilter(self, col: int, values) -> None:  # noqa: N802
        """Filter einer Spalte: angehakte Werte (Liste) oder ``None``/alle angehakt → Filter der Spalte aus."""
        chosen = None if values is None else [str(v) for v in values]
        menu = self.filterMenu
        if chosen is not None and menu.get("col") == col and len(chosen) >= len(menu.get("values") or []):
            chosen = None
        self.filterMenu = {}
        self._change("filter", {"col": col, "values": chosen}, layout=True)

    @Slot(str)
    def freezePanes(self, kind: str) -> None:  # noqa: N802
        """Fixieren: »row« (oberste Zeile), »col« (erste Spalte), »cursor« (über und links der aktiven Zelle), »none«."""
        rows, cols = {"row": (1, 0), "col": (0, 1), "none": (0, 0)}.get(kind, (self.cursorRow, self.cursorCol))
        self.freeze = [rows, cols]
        self.layout().freeze = (rows, cols)
        self.layoutRevision += 1
        self._change("freeze", {"rows": rows, "cols": cols}, layout=True)

    @Slot(str)
    def autoSum(self, function: str) -> None:  # noqa: N802
        """Σ Summe (bzw. MITTELWERT, ANZAHL, MAX, MIN): Bereich darüber bzw. links mit Zahlen vorschlagen und die Formel
        zum Bestätigen in die Zelle schreiben – eine markierte Spalte mit Zahlen bekommt die Summe darunter."""
        function = function or "SUMME"
        r0, c0, r1, c1 = self.selection
        cells = self.sheet_cells()

        def numeric(row: int, col: int) -> bool:
            value = cells.get(row, col)
            return value is not None and value[1] == "n"

        if (r0, c0) != (r1, c1) and c0 == c1 and r1 > r0:
            target = r1 + 1
            formula = f"={function}({calc.cell_name(r0, c0)}:{calc.cell_name(r1, c0)})"
            self.select(target, c0, False)
            self._change("input", {"row": target, "col": c0, "text": formula})
            return
        row, col = self.cursorRow, self.cursorCol
        top = row - 1
        while top >= 0 and numeric(top, col):
            top -= 1
        if top < row - 1:
            self.editRequested.emit(f"={function}({calc.cell_name(top + 1, col)}:{calc.cell_name(row - 1, col)})")
            return
        left = col - 1
        while left >= 0 and numeric(row, left):
            left -= 1
        if left < col - 1:
            self.editRequested.emit(f"={function}({calc.cell_name(row, left + 1)}:{calc.cell_name(row, col - 1)})")
            return
        self.editRequested.emit(f"={function}()")

    @Slot()
    def loadFunctions(self) -> None:  # noqa: N802
        if self.functionList:
            return
        cached = SheetController.functions_cache
        if cached:
            self.functionList = cached
            return

        def done(items: list) -> None:
            SheetController.functions_cache = list(items or [])
            self.functionList = SheetController.functions_cache

        self._call("functions", {}, done)

    @Slot(str, bool)
    def find(self, text: str, backward: bool) -> None:
        self.findText = text
        if not text:
            self.findResult = ""
            return

        def done(data) -> None:
            if not data:
                self.findResult = "Nicht gefunden"
                return
            self.findResult = f"{data['index']} von {data['count']}"
            self.select(int(data["row"]), int(data["col"]), False)
            self.cursorMoved.emit()

        self._call("find", {"text": text, "row": self.cursorRow, "col": self.cursorCol, "backward": bool(backward)}, done)

    @Slot(bool)
    def setPrintArea(self, on: bool) -> None:  # noqa: N802
        self._change("print_area", {"range": self.selection if on else None}, layout=True,
                     status="Druckbereich festgelegt." if on else "Druckbereich aufgehoben.")

    # Diagramme und Bilder ----------------------------------------------------------------------------------------------
    @Slot(str)
    def addChart(self, kind: str) -> None:  # noqa: N802
        self._change("add_chart", {"range": self.selection, "type": kind}, layout=True, status="Diagramm eingefügt.")

    @Slot(str, str)
    def chartType(self, name: str, kind: str) -> None:  # noqa: N802
        self._change("chart_type", {"name": name, "type": kind}, layout=True)

    @Slot(int, float, float, float, float)
    def moveObject(self, index: int, x: float, y: float, w: float, h: float) -> None:  # noqa: N802
        """Objekt verschieben bzw. Größe ändern – Lage in Pixeln bei 100 %."""
        self._change("move_object", {"index": index, "x": model.mm100(x), "y": model.mm100(y), "w": model.mm100(w), "h": model.mm100(h)}, layout=True)

    @Slot(int)
    def deleteObject(self, index: int) -> None:  # noqa: N802
        self._change("delete_object", {"index": index}, layout=True)

    def _set_objects(self, items: list[dict]) -> None:
        """Objekte für QML: Lage in Pixeln bei 100 %, Bild als data-URL (nachgeladen)."""
        self._object_revision += 1
        revision = self._object_revision
        self._images = {}  # Bilder gehören zu einem Stand der Objekte (Schlüssel mit ``revision``)
        shown = []
        for item in items:
            shown.append({**item, "px": model.px(item["x"]), "py": model.px(item["y"]), "pw": model.px(item["w"]),
                          "ph": model.px(item["h"]), "image": self._image_for(item)})
        self.objects = shown
        sheet = self.activeSheet
        for item in items:
            if self._image_for(item):
                continue
            scale = max(1.0, self.zoom / 100) * 2
            width, height = int(model.px(item["w"]) * scale), int(model.px(item["h"]) * scale)

            def done(data: dict, item=item) -> None:
                if revision != self._object_revision or sheet != self.activeSheet:
                    return
                self._images[self._image_key(item)] = "data:image/png;base64," + str(data.get("png") or "")
                self.objects = [{**entry, "image": self._image_for(entry)} for entry in self.objects]

            self._call("object_image", {"index": item["index"], "width": width, "height": height}, done, quiet=True)

    def _image_key(self, item: dict) -> tuple:
        return (self.ident, self.activeSheet, item.get("index"), item.get("name"), item.get("w"), item.get("h"), self._object_revision)

    def _image_for(self, item: dict) -> str:
        return self._images.get(self._image_key(item), "")

    # Blätter ---------------------------------------------------------------------------------------------------------
    @Slot(int)
    def activateSheet(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.sheets) or index == self.activeSheet:
            return
        self.activeSheet = index
        layout = self.layouts.get(index)
        self.freeze = list(layout.freeze) if layout else [0, 0]
        self.filterOn = bool(layout and layout.filter)
        self._anchor = self._end = (0, 0)
        self._call("activate", {"sheet": index}, quiet=True)
        if layout is None or not layout.loaded:
            self._load_layout(then=lambda: (self.select(0, 0, False), self.request_visible(), self.contentChanged.emit()))
        else:
            self._set_objects(layout.objects)
            self.layoutRevision += 1
            self.select(0, 0, False)
            self.request_visible()

    @Slot()
    def addSheet(self) -> None:  # noqa: N802
        def then(result: dict) -> None:
            self.activeSheet = -1
            self.activateSheet(int(result.get("active", len(self.sheets) - 1)))

        self._change("add_sheet", {"at": self.activeSheet + 1}, then=then)

    @Slot(int)
    def renameSheet(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.sheets):
            return
        old = self.sheets[index]["name"]
        answer, data = self.app.dialogs.ask("text_input", "Blatt umbenennen", "Neuer Name des Tabellenblatts:", primary="Umbenennen",
                                            data={"label": "Name", "value": old})
        name = str(data.get("value") or "").strip()
        if answer != "primary" or not name or name == old:
            return
        self._change("rename_sheet", {"sheet": index, "name": name})

    @Slot(int)
    def deleteSheet(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self.sheets) or len(self.sheets) <= 1:
            return
        name = self.sheets[index]["name"]
        if not self.app.dialogs.confirm(f"Blatt »{name}« löschen?", "Das Blatt und sein Inhalt werden gelöscht. Mit »Rückgängig« lässt es sich wiederholen.", "Löschen"):
            return

        def then(_result: dict) -> None:
            self.activeSheet = -1
            self.activateSheet(max(0, min(index, len(self.sheets) - 1)))

        self._change("delete_sheet", {"sheet": index}, then=then)

    @Slot(int, int)
    def moveSheet(self, index: int, target: int) -> None:  # noqa: N802
        if index == target or not 0 <= index < len(self.sheets):
            return
        target = max(0, min(len(self.sheets) - 1, target))

        def then(_result: dict) -> None:
            self.activeSheet = -1
            self.activateSheet(target)

        self._change("move_sheet", {"sheet": index, "to": target}, then=then)

    # Rückgängig, Zoom --------------------------------------------------------------------------------------------------
    @Slot()
    def undo(self) -> None:
        if self.undoText:
            self._change("undo", {}, layout=True)

    @Slot()
    def redo(self) -> None:
        if self.redoText:
            self._change("undo", {"redo": True}, layout=True)

    @Slot(int)
    def setZoom(self, value: int) -> None:  # noqa: N802
        value = max(MIN_ZOOM, min(MAX_ZOOM, int(value)))
        if value != self.zoom:
            self.zoom = value
            self.layoutRevision += 1
            self._set_objects([{k: v for k, v in item.items() if k not in ("px", "py", "pw", "ph", "image")} for item in self.objects])

    @Slot(int)
    def zoomStep(self, direction: int) -> None:  # noqa: N802
        if direction > 0:
            bigger = [step for step in ZOOM_STEPS if step > self.zoom]
            self.setZoom(bigger[0] if bigger else MAX_ZOOM)
        else:
            smaller = [step for step in ZOOM_STEPS if step < self.zoom]
            self.setZoom(smaller[-1] if smaller else MIN_ZOOM)

    # Speichern, PDF, Drucken -------------------------------------------------------------------------------------------
    def save(self, target: str | None = None, *, force: bool = False, then: Callable[[bool], None] | None = None) -> None:
        """Speichern (``target`` = Speichern unter). ``then(erfolgreich)`` danach."""
        del force
        if self.saving:
            if then is not None:
                self._save_then.append(then)
            return
        if not target:
            if not self.path or Path(self.path).suffix.lower() not in SAVE_SUFFIXES:
                target = self._pick_target()
                if not target:
                    if then is not None:
                        then(False)
                    return
            else:
                target = self.path
        if Path(target).suffix.lower() == ".csv" and len(self.sheets) > 1:
            answer, _data = self.app.dialogs.ask(
                "confirm", "Nur das aktive Blatt wird gespeichert",
                f"Eine CSV-Datei kann nur ein Blatt enthalten – gespeichert wird »{self.sheets[self.activeSheet]['name']}«, ohne Formate. "
                "Als Excel-Arbeitsmappe bleiben alle Blätter und Formate erhalten.",
                primary="Als Excel speichern", secondary="Nur dieses Blatt als CSV", close="Abbrechen")
            if answer == "primary":
                target = self._pick_target(str(Path(target).with_suffix(".xlsx")))
                if not target:
                    if then is not None:
                        then(False)
                    return
            elif answer != "secondary":
                if then is not None:
                    then(False)
                return
        if not self.doc:
            self.app.notify("reader", "error", "Der Rechenkern für Tabellen läuft nicht – die Tabelle wird neu geladen.",
                            title="Nicht gespeichert")
            if then is not None:
                then(False)
            return
        if then is not None:
            self._save_then.append(then)
        self.saving = True
        self.app.set_status(f"Wird gespeichert: {Path(target).name} …", "busy")
        args = {"path": str(Path(target).resolve())}
        if Path(target).suffix.lower() == ".csv":
            args["csv"] = self.csv_options or "59,34,76,1"

        def done(result: dict) -> None:
            self.saving = False
            self.path = str(Path(target))
            self.name = Path(target).name
            self.csv = Path(target).suffix.lower() == ".csv"
            self._apply_state(result)
            self.reader.tab_changed(self)
            self.reader.remember_recent(self.path)
            self.app.set_status(f"Gespeichert: {self.name}", "success")
            self._finish_save(True)

        def failed(exc: BaseException) -> None:
            self.saving = False
            message = str(exc) if isinstance(exc, calc.CalcError) else "Die Tabelle ließ sich nicht speichern."
            self.app.notify("reader", "error", message, title="Nicht gespeichert")
            self._finish_save(False)

        self._call("save", args, done, failed, quiet=True)

    def save_and_wait(self, timeout: float = 600.0) -> bool:
        """Beim Beenden: speichern und warten, bis es fertig ist (``True`` = gespeichert)."""
        from PySide6.QtCore import QEventLoop, QTimer

        result: dict = {}
        loop = QEventLoop()

        def finished(ok: bool) -> None:
            result["ok"] = ok
            loop.quit()

        self.save(then=finished)
        if "ok" not in result:
            QTimer.singleShot(int(timeout * 1000), loop.quit)
            loop.exec()
        return bool(result.get("ok"))

    def _finish_save(self, ok: bool) -> None:
        callbacks, self._save_then = self._save_then, []
        for callback in callbacks:
            callback(ok)

    def _pick_target(self, suggestion: str = "") -> str:
        from .. import files

        folder = str(Path(self.path).parent) if self.path else self.app.initial_dir("reader", self.reader.source_dir)
        stem = Path(self.name or "Mappe1").stem
        suffix = Path(self.path).suffix.lower() if self.path and Path(self.path).suffix.lower() in SAVE_SUFFIXES else ".xlsx"
        target = files.save_file("Speichern unter", suggestion or str(Path(folder) / (stem + suffix)), SAVE_FILTER)
        if target and Path(target).suffix.lower() not in SAVE_SUFFIXES:
            target += ".xlsx"
        return target

    @Slot()
    def saveNow(self) -> None:  # noqa: N802
        self.save()

    # Gleiche Namen wie bei PDF-Dokumenten (Strg+S, Strg+Umschalt+S, Strg+P, Strg+F aus Fenster und Reader)
    @Slot()
    def saveDocument(self) -> None:  # noqa: N802
        self.save()

    @Slot()
    def saveDocumentAs(self) -> None:  # noqa: N802
        self.saveAs()

    @Slot()
    def printDocument(self) -> None:  # noqa: N802
        self.printSheet()

    @Slot()
    def requestSearch(self) -> None:  # noqa: N802
        self.findRequested.emit()

    @Slot()
    def saveAs(self) -> None:  # noqa: N802
        target = self._pick_target()
        if target:
            self.save(target)

    @Slot(str)
    def exportPdf(self, scope: str) -> None:  # noqa: N802
        """Als PDF speichern: »all« (alle Blätter), »sheet« (dieses Blatt) oder »selection« (Auswahl)."""
        target = self.reader.pick_save_pdf(Path(self.name or "Tabelle").stem + ".pdf", "Als PDF speichern")
        if not target:
            return
        self.app.set_status("PDF wird erstellt …", "busy")

        def done(_result) -> None:
            name = Path(target).name
            self.app.notify("reader", "success", f"»{name}« wurde gespeichert.", title="Als PDF gespeichert", auto_hide=10000,
                            actions=[("Öffnen", lambda: self.reader.open_paths([target]))])

        self._call("pdf", {"path": str(Path(target).resolve()), "scope": scope, "range": self.selection}, done)

    @Slot()
    def printSheet(self) -> None:  # noqa: N802
        """Drucken: alle Blätter (Druckbereiche beachtet) als PDF vorbereiten, dann der Druckdialog von Windows."""
        folder = Path(tempfile.mkdtemp(prefix="novadesk-druck-"))
        target = folder / (Path(self.name or "Tabelle").stem + ".pdf")
        self.app.set_status("Druck wird vorbereitet …", "busy")

        def done(_result) -> None:
            from .printing import print_pdf

            try:
                print_pdf(self.app, str(target), self.name)
            finally:
                try:
                    target.unlink()
                    folder.rmdir()
                except OSError:
                    pass

        self._call("pdf", {"path": str(target), "scope": "all"}, done)

    @Slot()
    def createOverview(self) -> None:  # noqa: N802
        """Vertragsübersicht aus dieser Tabelle: liest die Datei – ungespeicherte Änderungen vorher speichern."""
        from tools.registry import CONTRACTS

        def go(ok: bool = True) -> None:
            if ok and self.path:
                self.app.open_with_tool(CONTRACTS.key, [self.path])

        if self.dirty or not self.path or Path(self.path).suffix.lower() not in (".xlsx", ".xlsm", ".xls"):
            answer, _data = self.app.dialogs.ask(
                "confirm", "Erst speichern?",
                "Die Vertragsübersicht entsteht aus der gespeicherten Excel-Datei. Jetzt speichern und dann die Übersicht erstellen?",
                primary="Speichern", close="Abbrechen")
            if answer != "primary":
                return
            target = None
            if not self.path or Path(self.path).suffix.lower() not in (".xlsx", ".xlsm", ".xls"):
                target = self._pick_target(str(Path(self.path or self.name).with_suffix(".xlsx")))
                if not target:
                    return
            self.save(target, then=go)
            return
        go()

    # Schließen ---------------------------------------------------------------------------------------------------------
    def shutdown(self, discard_recovery: bool = True) -> None:
        del discard_recovery
        self._closed = True
        self.app.timers.cancel(f"sheet:stats:{self.ident}")
        if self.doc:
            self.service.submit("close", {"doc": self.doc}, generation=self.generation)
        if SheetController.clip_owner is self:
            SheetController.clip_owner = None

    def _engine_lost(self, generation: int) -> None:
        """Der Rechenkern ist abgestürzt: Die Tabelle ist dort fort – aus der Datei neu öffnen (ungespeicherte
        Änderungen sind verloren) bzw. eine neue leere Tabelle."""
        if self._closed or generation != self.generation or not self.doc:
            return
        self.doc = 0
        self.ready = False
        lost = self.dirty
        self.app.notify("reader", "error",
                        ("Ungespeicherte Änderungen sind verloren. " if lost else "") + "Die Tabelle wird neu geöffnet.",
                        title="Rechenkern neu gestartet")
        self.layouts, self.cells, self._row_chunks, self._pending = {}, {}, {}, set()
        self.dirty = False
        self.reader.tab_changed(self)
        self.open(self.path, lambda: None, lambda exc: self.app.notify("reader", "error", str(exc), title=self.name), self.password)

    # Für das Raster ------------------------------------------------------------------------------------------------------
    def style(self, number: int) -> dict:
        return self.styles.get(number) or {}

    def _get_kind(self) -> str:
        return "tabelle"

    _constant = Signal()
    kind = Property(str, _get_kind, notify=_constant)


# Kopieren über Tabellen hinweg: zuletzt kopierter Text (aus Novadesk) und wessen
SheetController.last_copied = ""
SheetController.clip_owner = None
SheetController.functions_cache = []
