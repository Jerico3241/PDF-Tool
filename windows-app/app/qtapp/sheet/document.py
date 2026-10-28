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
CONDITION_RULES = {  # Regel: (Titel, Text, Felder)
    "greater": ("Größer als", "Zellen hervorheben, deren Wert größer ist als:", 1),
    "less": ("Kleiner als", "Zellen hervorheben, deren Wert kleiner ist als:", 1),
    "between": ("Zwischen", "Zellen hervorheben, deren Wert zwischen diesen Werten liegt:", 2),
    "equal": ("Gleich", "Zellen hervorheben, deren Wert gleich ist:", 1),
    "contains": ("Text enthält", "Zellen hervorheben, die diesen Text enthalten:", 1),
    "duplicate": ("Doppelte Werte", "Werte hervorheben, die in der Auswahl mehrfach vorkommen.", 0),
    "unique": ("Eindeutige Werte", "Werte hervorheben, die in der Auswahl nur einmal vorkommen.", 0),
    "top": ("Obere Werte", "Die größten Werte der Auswahl hervorheben – wie viele?", 1),
    "bottom": ("Untere Werte", "Die kleinsten Werte der Auswahl hervorheben – wie viele?", 1),
    "above": ("Über dem Durchschnitt", "Werte über dem Durchschnitt der Auswahl hervorheben.", 0),
    "below": ("Unter dem Durchschnitt", "Werte unter dem Durchschnitt der Auswahl hervorheben.", 0),
}
CONDITION_STYLES = [{"key": "red", "label": "Hellrote Füllung, dunkelrote Schrift"},
                    {"key": "yellow", "label": "Gelbe Füllung, dunkelgelbe Schrift"},
                    {"key": "green", "label": "Grüne Füllung, dunkelgrüne Schrift"}]
VALIDATION_KINDS = [{"key": "any", "label": "Jeder Wert"}, {"key": "list", "label": "Liste"}, {"key": "whole", "label": "Ganze Zahl"},
                    {"key": "decimal", "label": "Dezimalzahl"}, {"key": "date", "label": "Datum"}, {"key": "textlen", "label": "Textlänge"}]
VALIDATION_OPERATORS = [{"key": "between", "label": "zwischen"}, {"key": "not_between", "label": "nicht zwischen"},
                        {"key": "equal", "label": "gleich"}, {"key": "not_equal", "label": "ungleich"},
                        {"key": "greater", "label": "größer als"}, {"key": "less", "label": "kleiner als"},
                        {"key": "greater_equal", "label": "größer oder gleich"}, {"key": "less_equal", "label": "kleiner oder gleich"}]
PIVOT_FUNCTIONS = [{"key": "sum", "label": "Summe"}, {"key": "count", "label": "Anzahl"}, {"key": "average", "label": "Mittelwert"},
                   {"key": "max", "label": "Maximum"}, {"key": "min", "label": "Minimum"}]
SEPARATORS = [{"key": ";", "label": "Semikolon ( ; )"}, {"key": ",", "label": "Komma ( , )"}, {"key": "tab", "label": "Tabulator"},
              {"key": " ", "label": "Leerzeichen"}, {"key": "other", "label": "Anderes Zeichen"}]
WORKBOOK_FILTER = "Tabellen (*.xlsx *.xlsm *.xls *.ods *.csv);;Alle Dateien (*)"
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
    sheetProtectedChanged, sheetProtected = prop(bool, "sheetProtected", False)  # aktives Blatt geschützt
    bookProtectedChanged, bookProtected = prop(bool, "bookProtected", False)  # Aufbau der Mappe geschützt
    encryptedChanged, encrypted = prop(bool, "encrypted", False)  # Kennwort zum Öffnen gesetzt
    crosshairChanged, crosshair = prop(bool, "crosshair", False)  # Lese-Kreuz: Zeile und Spalte der Zelle hervorheben
    validationChanged, validation = prop(dict, "validation", {})  # Datenüberprüfung der aktiven Zelle

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
            self._call("state", {}, self._apply_state, quiet=True)  # z. B. abgelehnte Eingabe: wieder »gespeichert«

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
        if "book" in state:
            self.bookProtected = bool(state["book"])
        if "encrypted" in state:
            self.encrypted = bool(state["encrypted"])
        self._update_protection()
        self.undoText = str(state.get("undo") or "") if "undo" in state else self.undoText
        self.redoText = str(state.get("redo") or "") if "redo" in state else self.redoText

    def _update_protection(self) -> None:
        sheets = self.sheets
        self.sheetProtected = bool(0 <= self.activeSheet < len(sheets) and sheets[self.activeSheet].get("protected"))

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
            self.validation = dict(data.get("validation") or {})

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
            self._change("input", {"row": row, "col": col, "text": text}, then=self._input_done)
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

    def _input_done(self, result: dict) -> None:
        if result.get("warning"):  # Datenüberprüfung »nur warnen«: die Eingabe bleibt
            self.app.notify("reader", "warning", str(result["warning"]), title="Datenüberprüfung", auto_hide=8000)

    @Slot(str)
    def chooseListItem(self, text: str) -> None:  # noqa: N802
        """Auswahlliste der Datenüberprüfung: Eintrag in die aktive Zelle."""
        self.commit(text, 0, 0)

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
        self._update_protection()
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

    # Formulare (Pivot, Datenüberprüfung, Regeln, Schutz …) ------------------------------------------------------------
    def _form(self, title: str, fields: list[dict], primary: str, *, message: str = "", secondary: str = "",
              width: int = 480) -> tuple[str, dict]:
        """Formular »sheet_form«: Antwort und Werte je ``key`` (nicht geänderte Felder mit ihrem Anfangswert)."""
        answer, data = self.app.dialogs.ask("sheet_form", title, message, primary=primary, secondary=secondary,
                                            data={"fields": fields}, width=width)
        values = {field["key"]: field.get("value") for field in fields if field.get("key")}
        values.update({key: value for key, value in (data or {}).items() if key != "fields"})
        return answer, values

    def _table_info(self, then: Callable[[dict], None]) -> None:
        """Tabelle um die Auswahl (Spaltennamen, Zahlenspalten, Kopfzeile) – dann ``then``."""
        def done(info: dict) -> None:
            if not info.get("fields"):
                self.app.set_status("Hier ist keine Tabelle – bitte eine Zelle in den Daten wählen.", "warning")
                return
            then(info)

        self._call("table_info", {"range": self.selection}, done)

    def _activate_new(self, result: dict, index: int | None = None) -> None:
        target = result.get("sheet", index if index is not None else len(self.sheets) - 1)
        self.activeSheet = -1
        self.activateSheet(int(target))

    # Bedingte Formatierung
    @Slot(str)
    def conditional(self, rule: str) -> None:
        """Regel für die Auswahl: Hervorheben (greater, less, between, equal, contains, duplicate, unique), obere/untere
        Werte (top, bottom), über/unter dem Durchschnitt (above, below) oder Datenbalken (bar_blue, bar_green, bar_red)."""
        args = {"range": self.selection, "rule": rule}
        if rule.startswith("bar_"):
            self._change("conditional", args, status="Datenbalken eingefügt.")
            return
        if rule not in CONDITION_RULES:
            return
        title, text, count = CONDITION_RULES[rule]
        fields: list[dict] = []
        if count:
            number = rule in ("top", "bottom")
            fields.append({"key": "value1", "type": "text", "label": "Anzahl" if number else ("Von" if count == 2 else "Wert"),
                           "value": "10" if number else "", "required": True,
                           "placeholder": "z. B. 1000 oder Köln" if rule in ("equal", "contains") else "z. B. 1000"})
        if count == 2:
            fields.append({"key": "value2", "type": "text", "label": "Bis", "value": "", "required": True, "placeholder": "z. B. 5000"})
        fields.append({"key": "style", "type": "choice", "label": "Format", "value": "red", "options": CONDITION_STYLES})
        answer, values = self._form(title, fields, "Übernehmen", message=text)
        if answer != "primary":
            return
        args.update({key: values.get(key) for key in ("value1", "value2", "style") if values.get(key) not in (None, "")})
        self._change("conditional", args, status="Regel angelegt.")

    @Slot(str)
    def clearConditional(self, scope: str) -> None:  # noqa: N802
        """Regeln löschen: »selection« (die die Auswahl berühren) oder »sheet« (alle des Blatts)."""
        def then(result: dict) -> None:
            removed = int(result.get("removed") or 0)
            self.app.set_status(f"{removed} Regel(n) gelöscht." if removed else "Hier gibt es keine Regeln.", "success" if removed else "info")

        self._change("clear_conditional", {"range": self.selection} if scope == "selection" else {}, then=then)

    # Datenüberprüfung
    @Slot()
    def validationDialog(self) -> None:  # noqa: N802
        """Erlaubte Eingaben für die Auswahl festlegen (Liste, Zahlen, Datum, Textlänge) – wie »Datenüberprüfung«."""
        current = dict(self.validation or {})
        numeric = ["whole", "decimal", "date", "textlen"]
        fields = [
            {"key": "kind", "type": "choice", "label": "Zulassen", "value": current.get("kind", "list"), "options": VALIDATION_KINDS},
            {"key": "items", "type": "text", "label": "Einträge (mit ; getrennt)", "value": "; ".join(current.get("items") or []),
             "placeholder": "z. B. offen; in Arbeit; erledigt", "required": True, "show": {"key": "kind", "is": ["list"]}},
            {"key": "operator", "type": "choice", "label": "Daten", "value": current.get("operator", "between"),
             "options": VALIDATION_OPERATORS, "show": {"key": "kind", "is": numeric}},
            {"key": "value1", "type": "text", "label": "Wert (bei »zwischen«: von)", "value": current.get("value1", ""), "required": True,
             "placeholder": "z. B. 0 oder 01.01.2026", "show": {"key": "kind", "is": numeric}},
            {"key": "value2", "type": "text", "label": "Bis", "value": current.get("value2", ""), "required": True, "placeholder": "z. B. 100",
             "show": [{"key": "kind", "is": numeric}, {"key": "operator", "is": ["between", "not_between"]}]},
            {"key": "message", "type": "text", "label": "Meldung bei falscher Eingabe (optional)", "value": current.get("message", ""),
             "placeholder": "z. B. Bitte einen Status aus der Liste wählen.", "show": {"key": "kind", "is": ["list"] + numeric}},
            {"key": "strict", "type": "check", "label": "Falsche Eingaben ablehnen (sonst nur warnen)", "value": current.get("strict", True),
             "show": {"key": "kind", "is": ["list"] + numeric}},
        ]
        answer, values = self._form("Datenüberprüfung", fields, "Übernehmen", message="Welche Eingaben sind in den ausgewählten Zellen erlaubt?")
        if answer != "primary":
            return
        kind = str(values.get("kind") or "any")
        args = {"range": self.selection, "kind": kind, "operator": values.get("operator") or "between",
                "value1": str(values.get("value1") or ""), "value2": str(values.get("value2") or ""),
                "message": str(values.get("message") or ""), "strict": bool(values.get("strict", True)),
                "items": [item.strip() for item in str(values.get("items") or "").split(";") if item.strip()]}
        self._change("validation", args, status="Prüfung entfernt." if kind == "any" else "Datenüberprüfung festgelegt.",
                     then=lambda _result: self._load_cell())

    # Pivot-Tabelle
    @Slot()
    def pivotDialog(self) -> None:  # noqa: N802
        """Pivot-Tabelle aus der Tabelle um die Auswahl auf einem neuen Blatt."""
        def ask(info: dict) -> None:
            names = list(info["fields"])
            numeric = list(info.get("numeric") or [])
            options = [{"key": str(index), "label": name} for index, name in enumerate(names)]
            text_columns = [index for index, flag in enumerate(numeric) if not flag] or [0]
            number_columns = [index for index, flag in enumerate(numeric) if flag]
            data_default = number_columns[-1] if number_columns else len(names) - 1
            fields = [
                {"key": "rows", "type": "choice", "label": "Zeilen", "value": str(text_columns[0]), "options": options},
                {"key": "cols", "type": "choice", "label": "Spalten (optional)", "value": "",
                 "options": [{"key": "", "label": "(keine)"}] + options},
                {"key": "data", "type": "choice", "label": "Werte", "value": str(data_default), "options": options},
                {"key": "function", "type": "choice", "label": "Berechnen als", "value": "sum" if number_columns else "count",
                 "options": PIVOT_FUNCTIONS},
                {"type": "note", "label": f"Quelle: {info.get('rows', 0)} Zeilen in {self._range_name(info['range'])}. "
                                          "Die Pivot-Tabelle kommt auf ein neues Blatt."},
            ]
            answer, values = self._form("Pivot-Tabelle einfügen", fields, "Einfügen")
            if answer != "primary":
                return
            rows = [int(values["rows"])]
            cols = [int(values["cols"])] if str(values.get("cols") or "") not in ("", str(rows[0])) else []
            self._change("pivot", {"range": info["range"], "rows": rows, "cols": cols, "data": int(values["data"]),
                                   "function": values.get("function") or "sum"},
                         layout=True, status="Pivot-Tabelle eingefügt.", then=self._activate_new)

        self._table_info(ask)

    @Slot()
    def refreshPivots(self) -> None:  # noqa: N802
        def then(result: dict) -> None:
            count = int(result.get("count") or 0)
            self.app.set_status(f"{count} Pivot-Tabelle(n) aktualisiert." if count else "Diese Mappe hat keine Pivot-Tabellen.",
                                "success" if count else "info")

        self._change("pivot_refresh", {}, layout=True, then=then)

    def _range_name(self, area: list) -> str:
        r0, c0, r1, c1 = (int(value) for value in area)
        return f"{calc.cell_name(r0, c0)}:{calc.cell_name(r1, c1)}"

    # Duplikate, Text in Spalten, Blitzvorschau
    @Slot()
    def removeDuplicates(self) -> None:  # noqa: N802
        def ask(info: dict) -> None:
            options = [{"key": str(index), "label": name} for index, name in enumerate(info["fields"])]
            fields = [
                {"type": "note", "label": "Zeilen, die in den angehakten Spalten gleich sind, werden entfernt – die erste bleibt."},
                {"key": "columns", "type": "checks", "label": "Spalten vergleichen", "value": [option["key"] for option in options],
                 "options": options, "required": True},
                {"key": "header", "type": "check", "label": "Erste Zeile ist die Überschrift", "value": bool(info.get("header"))},
            ]
            answer, values = self._form("Duplikate entfernen", fields, "Entfernen")
            if answer != "primary":
                return

            def then(result: dict) -> None:
                removed, remaining = int(result.get("removed") or 0), int(result.get("remaining") or 0)
                if result.get("range"):
                    area = result["range"]
                    self.selectRange(area[0], area[1], area[2], area[3])
                self.app.notify("reader", "success" if removed else "info",
                                f"{removed} doppelte Zeile(n) entfernt, {remaining} eindeutige bleiben." if removed
                                else f"Keine Duplikate gefunden – alle {remaining} Zeilen sind eindeutig.",
                                title="Duplikate entfernen", auto_hide=8000)

            self._change("duplicates", {"range": info["range"], "columns": [int(key) for key in values.get("columns") or []],
                                        "header": bool(values.get("header"))}, layout=True, then=then)

        self._table_info(ask)

    @Slot()
    def textToColumns(self) -> None:  # noqa: N802
        """Texte der ausgewählten Spalte an einem Trennzeichen auf Spalten rechts daneben verteilen."""
        def ask(info: dict) -> None:
            samples = [str(sample) for sample in info.get("samples") or [] if str(sample)]
            if not samples:
                self.app.set_status("Die ausgewählte Spalte enthält keinen Text.", "warning")
                return
            guess = next((key for key in (";", "tab", ",") if any((key if key != "tab" else "\t") in sample for sample in samples)), " ")
            fields = [
                {"key": "separator", "type": "choice", "label": "Trennzeichen", "value": guess, "options": SEPARATORS},
                {"key": "custom", "type": "text", "label": "Zeichen", "value": "", "required": True, "placeholder": "z. B. | oder -",
                 "show": {"key": "separator", "is": ["other"]}},
                {"key": "preview", "type": "preview", "label": "Vorschau", "samples": samples[:6], "source": "separator", "custom": "custom"},
            ]
            rows = info.get("rows") or [0, 0]
            answer, values = self._form("Text in Spalten", fields, "Aufteilen",
                                        message=f"Spalte {calc.column_name(int(info['col']))}, Zeilen {int(rows[0]) + 1} bis {int(rows[1]) + 1}: "
                                                "die Teile kommen in die Spalten rechts daneben.")
            if answer != "primary":
                return
            separator = values.get("separator") or ";"
            if separator == "other":
                separator = str(values.get("custom") or "")[:1] or ";"
            area = [int(rows[0]), int(info["col"]), int(rows[1]), int(info["col"])]
            self._split_columns(area, separator, False)

        self._call("column_texts", {"range": self.selection}, ask)

    def _split_columns(self, area: list, separator: str, force: bool) -> None:
        def then(result: dict) -> None:
            if "overwrite" in result:
                if self.app.dialogs.confirm("Daten überschreiben?", f"In den Spalten rechts stehen schon {result['overwrite']} Werte. "
                                            "Sie werden durch die Teile ersetzt (mit »Rückgängig« wiederherstellbar).", "Überschreiben"):
                    self._split_columns(area, separator, True)
                return
            if result.get("range"):
                target = result["range"]
                self.selectRange(target[0], target[1], target[2], target[3])
            self.app.set_status("Text auf Spalten verteilt.", "success")

        self._change("text_to_columns", {"range": area, "separator": separator, "force": force}, layout=True, then=then)

    @Slot()
    def flashFill(self) -> None:  # noqa: N802
        """Blitzvorschau (Strg+E): aus den Beispielen in der Spalte der aktiven Zelle die übrigen Zeilen ausfüllen."""
        from .flashfill import NoPattern, flash_fill

        col = self.cursorCol

        def done(data: dict) -> None:
            area = data.get("range") or [0, 0, 0, 0]
            if not area[1] <= col <= area[3]:
                self.app.set_status("Für die Blitzvorschau ein Beispiel direkt neben die Daten tippen.", "warning")
                return
            try:
                texts = flash_fill([list(row) for row in data.get("rows") or []], col - area[1])
            except NoPattern:
                self.app.notify("reader", "info", "Kein Muster erkannt. Bitte in die Spalte ein oder zwei Beispiele mehr tippen "
                                "und dann erneut Strg+E drücken.", title="Blitzvorschau", auto_hide=8000)
                return
            count = sum(1 for text in texts if text is not None)
            if not count:
                self.app.set_status("Die Spalte ist schon ausgefüllt.", "info")
                return
            self._mark_dirty()
            self._change("set_texts", {"row": area[0], "col": col, "texts": texts, "title": "Blitzvorschau"}, layout=True,
                         status=f"Blitzvorschau: {count} Zelle(n) ausgefüllt.")

        self._call("region_texts", {"range": [self.cursorRow, col, self.cursorRow, col]}, done)

    # Blätter und Mappen teilen und zusammenführen
    @Slot()
    def splitSheet(self) -> None:  # noqa: N802
        """Tabelle nach den Werten einer Spalte auf neue Blätter verteilen."""
        def ask(info: dict) -> None:
            options = [{"key": str(index), "label": name} for index, name in enumerate(info["fields"])]
            start = self.cursorCol - int(info["range"][1])
            fields = [
                {"key": "col", "type": "choice", "label": "Je Wert dieser Spalte ein Blatt", "options": options,
                 "value": str(start if 0 <= start < len(options) else 0)},
                {"type": "note", "label": "Jedes neue Blatt bekommt die Überschrift und die Zeilen mit seinem Wert. Das Blatt selbst bleibt, wie es ist."},
            ]
            answer, values = self._form("Blatt teilen", fields, "Teilen")
            if answer != "primary":
                return

            def then(result: dict) -> None:
                created = list(result.get("created") or [])
                self.app.notify("reader", "success", f"{len(created)} Blätter angelegt: {', '.join(created[:8])}{' …' if len(created) > 8 else ''}",
                                title="Blatt teilen", auto_hide=8000)

            self._change("split_sheet", {"range": info["range"], "col": int(values.get("col") or 0)}, then=then)

        self._table_info(ask)

    @Slot()
    def mergeSheets(self) -> None:  # noqa: N802
        """Blätter untereinander auf ein neues Blatt »Zusammengeführt«."""
        if len(self.sheets) < 2:
            self.app.set_status("Die Mappe hat nur ein Blatt. Weitere Blätter holt »Mappe anfügen« aus anderen Dateien.", "info")
            return
        options = [{"key": str(index), "label": sheet["name"]} for index, sheet in enumerate(self.sheets)]
        fields = [
            {"key": "sheets", "type": "checks", "label": "Blätter", "value": [option["key"] for option in options], "options": options,
             "required": True, "minimum": 2},
            {"key": "header", "type": "check", "label": "Gleiche Überschrift: nur einmal oben übernehmen", "value": True},
        ]
        answer, values = self._form("Blätter zusammenführen", fields, "Zusammenführen")
        if answer != "primary":
            return
        chosen = sorted(int(key) for key in values.get("sheets") or [])
        self._change("merge_sheets", {"sheets": chosen, "header": bool(values.get("header"))},
                     status="Blätter zusammengeführt.", then=lambda result: self._activate_new(result))

    @Slot()
    def importBook(self) -> None:  # noqa: N802
        """Alle Blätter anderer Mappen hinten anfügen (Mappen zusammenführen)."""
        from .. import files

        paths = files.open_files("Mappen anfügen", self.app.initial_dir("reader", self.reader.source_dir), WORKBOOK_FILTER)
        paths = [path for path in paths if path and Path(path).resolve() != Path(self.path or ".").resolve()]
        if not paths:
            return
        created: list[str] = []

        def next_book(result: dict | None = None) -> None:
            if result:
                created.extend(result.get("created") or [])
            if paths:
                self._change("import_book", {"path": str(Path(paths.pop(0)).resolve())}, then=next_book)
                return
            self.app.notify("reader", "success", f"{len(created)} Blätter angefügt.", title="Mappen zusammenführen", auto_hide=8000)
            if created:
                self._activate_new({}, len(self.sheets) - len(created))

        next_book()

    @Slot()
    def exportSheets(self) -> None:  # noqa: N802
        """Jedes Blatt als eigene Mappe speichern (Mappe teilen)."""
        from .. import files

        folder = files.pick_folder("Ordner für die einzelnen Blätter", str(Path(self.path).parent) if self.path else
                                   self.app.initial_dir("reader", self.reader.source_dir))
        if not folder:
            return
        suffix = Path(self.path).suffix.lower() if self.path and Path(self.path).suffix.lower() in (".xlsx", ".xlsm", ".xls", ".ods") else ".xlsx"
        self.app.set_status("Blätter werden gespeichert …", "busy")

        def done(result: dict) -> None:
            written = list(result.get("files") or [])
            self.app.notify("reader", "success", f"{len(written)} Dateien gespeichert in »{Path(folder).name}«.", title="Mappe teilen",
                            auto_hide=10000, actions=[("Ordner öffnen", lambda: files.open_path(folder))])

        self._call("export_sheets", {"folder": str(Path(folder).resolve()), "stem": Path(self.name or "Mappe").stem, "suffix": suffix}, done)

    # Schutz
    def _protect_fields(self, on: bool, what: str) -> list[dict]:
        if not on:
            return [{"key": "password", "type": "password", "label": "Kennwort", "value": ""},
                    {"type": "note", "label": f"Leer lassen, wenn {what} ohne Kennwort geschützt wurde."}]
        return [{"key": "password", "type": "password", "label": "Kennwort (optional)", "value": ""},
                {"key": "repeat", "type": "password", "label": "Kennwort wiederholen", "value": "", "confirm": "password"},
                {"type": "note", "label": "Ohne Kennwort kann jeder den Schutz aufheben. Ein vergessenes Kennwort lässt sich nicht wiederherstellen."}]

    @Slot()
    def protectSheet(self) -> None:  # noqa: N802
        """Aktives Blatt schützen bzw. den Schutz aufheben. Freigegebene Zellen bleiben bearbeitbar."""
        on = not self.sheetProtected
        fields = self._protect_fields(on, "das Blatt")
        if on:
            fields.append({"type": "note", "label": "Zellen, die vorher mit »Zellen freigeben« freigegeben wurden, lassen sich weiter ausfüllen."})
        answer, values = self._form("Blatt schützen" if on else "Blattschutz aufheben", fields, "Schützen" if on else "Aufheben")
        if answer != "primary":
            return
        self._change("protect", {"target": "sheet", "password": str(values.get("password") or ""), "on": on},
                     status="Blatt geschützt." if on else "Blattschutz aufgehoben.")

    @Slot()
    def protectBook(self) -> None:  # noqa: N802
        """Aufbau der Mappe schützen (Blätter einfügen, löschen, umbenennen, verschieben) bzw. freigeben."""
        on = not self.bookProtected
        fields = self._protect_fields(on, "die Mappe")
        answer, values = self._form("Mappe schützen" if on else "Mappenschutz aufheben", fields, "Schützen" if on else "Aufheben",
                                    message="Blätter lassen sich dann nicht mehr einfügen, löschen, umbenennen oder verschieben." if on else "")
        if answer != "primary":
            return
        self._change("protect", {"target": "book", "password": str(values.get("password") or ""), "on": on},
                     status="Mappe geschützt." if on else "Mappenschutz aufgehoben.")

    @Slot()
    def encrypt(self) -> None:
        """Kennwort zum Öffnen der Datei setzen, ändern oder entfernen – gilt ab dem nächsten Speichern."""
        fields = [{"key": "password", "type": "password", "label": "Kennwort", "value": "", "required": True},
                  {"key": "repeat", "type": "password", "label": "Kennwort wiederholen", "value": "", "confirm": "password"},
                  {"type": "note", "label": "Die Datei lässt sich danach nur mit diesem Kennwort öffnen (auch in Excel). "
                                            "Ein vergessenes Kennwort lässt sich nicht wiederherstellen."}]
        if self.path and Path(self.path).suffix.lower() in (".csv", ".xls"):
            fields.append({"type": "note", "label": "Verschlüsseln geht nur als Excel-Arbeitsmappe (.xlsx) oder OpenDocument (.ods) – "
                                                    "beim Speichern bitte eines davon wählen."})
        answer, values = self._form("Mit Kennwort verschlüsseln", fields, "Verschlüsseln",
                                    secondary="Kennwort entfernen" if self.encrypted else "")
        if answer not in ("primary", "secondary"):
            return
        password = str(values.get("password") or "") if answer == "primary" else ""
        if answer == "primary" and not password:
            return
        self.password = password or None
        self._mark_dirty()
        self._change("encrypt", {"password": password},
                     status="Kennwort gesetzt – es gilt ab dem nächsten Speichern." if password else "Kennwort entfernt – gilt ab dem nächsten Speichern.")

    @Slot(bool)
    def lockCells(self, locked: bool) -> None:  # noqa: N802
        """Zellen der Auswahl sperren bzw. freigeben (bei geschütztem Blatt bleiben freigegebene bearbeitbar)."""
        if self.sheetProtected:
            self.app.set_status("Erst den Blattschutz aufheben, dann Zellen freigeben oder sperren.", "warning")
            return
        self._change("lock", {"range": self.selection, "locked": bool(locked)},
                     status="Zellen gesperrt." if locked else "Zellen freigegeben – sie bleiben bei geschütztem Blatt bearbeitbar.")

    # Lese-Kreuz
    @Slot()
    def toggleCrosshair(self) -> None:  # noqa: N802
        self.crosshair = not self.crosshair
        self.revision += 1

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
