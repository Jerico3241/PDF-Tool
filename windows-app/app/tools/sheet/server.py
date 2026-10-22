"""Rechenkern der Tabellen in Novadesk – läuft *in* LibreOffice, nicht in Novadesk.

Novadesk startet das mitgelieferte LibreOffice ohne Fenster (``--headless``) mit einem eigenen Profil, legt diese Datei
dort unter ``user/Scripts/python/novadesk_tabelle.py`` ab und ruft ``start`` als Skript auf. ``start`` öffnet einen
Server auf 127.0.0.1 (zufälliger Port, in ``NOVADESK_TABELLE_PORT`` geschrieben) und bedient genau eine Verbindung:
die von Novadesk, die sich zuerst mit dem Schlüssel aus ``NOVADESK_TABELLE_SCHLUESSEL`` ausweisen muss. Endet die
Verbindung, schließt der Kern alle Dokumente und beendet LibreOffice.

Protokoll: je Zeile ein JSON-Objekt. Anfrage ``{"id", "cmd", "args"}``, Antwort ``{"id", "ok": true, "result"}`` oder
``{"id", "ok": false, "error", "code"}``. Die Befehle stehen unten in ``COMMANDS``. Zeilen und Spalten zählen ab 0.

Diese Datei läuft im Python von LibreOffice (nicht im Python von Novadesk): nur Standardbibliothek und ``uno``, keine
Importe aus Novadesk, Syntax bis Python 3.8.
"""

import base64
import json
import os
import select
import socket
import tempfile
import time
import traceback

import uno
import unohelper
from com.sun.star.beans import PropertyValue
from com.sun.star.frame import TerminationVetoException, XTerminateListener

PORT_VARIABLE = "NOVADESK_TABELLE_PORT"
TOKEN_VARIABLE = "NOVADESK_TABELLE_SCHLUESSEL"

# Dateiformate: Endung → Filter von LibreOffice (Speichern); Laden erkennt das Format selbst
FILTERS = {
    ".xlsx": "Calc MS Excel 2007 XML",
    ".xlsm": "Calc MS Excel 2007 VBA XML",
    ".xls": "MS Excel 97",
    ".ods": "calc8",
    ".csv": "Text - txt - csv (StarCalc)",
}
CSV_FILTER = "Text - txt - csv (StarCalc)"
PDF_FILTER = "calc_pdf_Export"

# Zellinhalt: com.sun.star.table.CellContentType und FormulaResult
EMPTY, VALUE, TEXT, FORMULA = 0, 1, 2, 3
RESULT_VALUE, RESULT_STRING, RESULT_ERROR = 1, 2, 4
CONTENT_ALL = 1 | 2 | 4 | 8 | 16 | 256  # Werte, Datum, Text, Notizen, Formeln, Objekte nicht (128)
CONTENT_DATA = 1 | 2 | 4 | 16  # Taste Entf: Inhalte ohne Formate
HARD_FORMATS = 32
BOLD = 150.0  # com.sun.star.awt.FontWeight.BOLD

# Kategorien der Funktionen (com.sun.star.sheet.FunctionCategory)
CATEGORIES = {
    1: "Datenbank", 2: "Datum & Zeit", 3: "Finanzen", 4: "Information", 5: "Logik", 6: "Mathematik",
    7: "Matrix", 8: "Statistik", 9: "Tabelle", 10: "Text", 11: "Add-in",
}
CHART_TYPES = {
    "column": ("com.sun.star.chart.BarDiagram", False),
    "bar": ("com.sun.star.chart.BarDiagram", True),
    "line": ("com.sun.star.chart.LineDiagram", False),
    "pie": ("com.sun.star.chart.PieDiagram", False),
    "area": ("com.sun.star.chart.AreaDiagram", False),
}
LOCALE = ("de", "DE")
I18N_CALLS = ("CalcError",)  # Oberflächentexte nur in Fehlermeldungen (sonst technische Namen von LibreOffice)


class CalcError(Exception):
    """Fehler mit einem Text für die Oberfläche (deutsch, ohne Fachbegriffe)."""

    def __init__(self, message, code="fehler"):
        Exception.__init__(self, message)
        self.code = code


class _Veto(unohelper.Base, XTerminateListener):
    """LibreOffice endet sonst, sobald kein Dokument mehr offen ist – der Kern läuft, bis Novadesk ihn beendet."""

    def __init__(self, state):
        self.state = state

    def queryTermination(self, event):  # noqa: N802 - UNO
        if not self.state["quit"]:
            raise TerminationVetoException()

    def notifyTermination(self, event):  # noqa: N802 - UNO
        pass

    def disposing(self, event):
        pass


def _prop(name, value):
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def _locale():
    locale = uno.createUnoStruct("com.sun.star.lang.Locale")
    locale.Language, locale.Country = LOCALE
    return locale


def _url(path):
    return uno.systemPathToFileUrl(os.path.abspath(path))


def column_name(index):
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _address(sheet_range):
    a = sheet_range.getRangeAddress()
    return [a.StartRow, a.StartColumn, a.EndRow, a.EndColumn]


def _color(value):
    """Farbe als »#rrggbb« oder "" (automatisch / keine)."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return ""
    if value < 0:
        return ""
    return "#%06x" % (value & 0xFFFFFF)


def _parse_color(text):
    if not text:
        return -1
    return int(str(text).lstrip("#"), 16)


def _enum_value(value):
    try:
        return value.value
    except AttributeError:
        return value


class Document:
    def __init__(self, ident, model, path, filter_name, filter_options):
        self.ident = ident
        self.model = model
        self.path = path
        self.filter = filter_name
        self.filter_options = filter_options
        self.styles = {}  # Stil (Tupel) → Nummer; die Oberfläche bekommt jeden Stil einmal
        self.filters = {}  # Blatt → {Spalte: [Werte]} – gesetzte Filter (zum Anzeigen im Filter-Menü)
        self.clip = None  # zuletzt kopierter Bereich (Transferable von LibreOffice)
        self.password = ""  # Kennwort der Datei (bleibt beim Speichern als Excel/ODF erhalten)

    @property
    def controller(self):
        return self.model.getCurrentController()

    def sheet(self, index):
        sheets = self.model.Sheets
        if not 0 <= int(index) < sheets.getCount():
            raise CalcError("Dieses Tabellenblatt gibt es nicht mehr.", "blatt")
        return sheets.getByIndex(int(index))


class Kernel:
    def __init__(self, ctx):
        self.ctx = ctx
        self.smgr = ctx.ServiceManager
        self.desktop = self.smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        self.docs = {}
        self.next_id = 1
        self.functions = None
        self.clip = None  # (Dokument, Transferable, Text) – »Kopieren« über Dokumente hinweg

    # Hilfen ------------------------------------------------------------------------------------------------
    def doc(self, args):
        doc = self.docs.get(int(args.get("doc", 0)))
        if doc is None:
            raise CalcError("Die Tabelle ist nicht mehr geöffnet.", "dokument")
        return doc

    def cell_range(self, doc, args):
        sheet = doc.sheet(args.get("sheet", 0))
        r0, c0, r1, c1 = (int(v) for v in args["range"])
        r0, r1 = sorted((max(0, r0), max(0, r1)))
        c0, c1 = sorted((max(0, c0), max(0, c1)))
        return sheet, sheet.getCellRangeByPosition(c0, r0, c1, r1)

    def state(self, doc):
        """Was die Oberfläche nach jeder Änderung braucht: ungespeichert, Rückgängig/Wiederholen, Blätter."""
        undo = doc.model.UndoManager
        sheets = doc.model.Sheets
        names = []
        for index in range(sheets.getCount()):
            sheet = sheets.getByIndex(index)
            names.append({"name": sheet.getName(), "visible": bool(sheet.IsVisible), "color": _color(getattr(sheet, "TabColor", -1))})
        return {
            "modified": bool(doc.model.isModified()),
            "undo": undo.getCurrentUndoActionTitle() if undo.isUndoPossible() else "",
            "redo": undo.getCurrentRedoActionTitle() if undo.isRedoPossible() else "",
            "sheets": names,
            "active": self.active_sheet(doc),
        }

    def active_sheet(self, doc):
        try:
            active = doc.controller.getActiveSheet()
            return active.getRangeAddress().Sheet
        except Exception:  # noqa: BLE001 - ohne Ansicht: das erste Blatt
            return 0

    def changed(self, doc, extra=None):
        result = self.state(doc)
        if extra:
            result.update(extra)
        return result

    def undo_context(self, doc, title):
        manager = doc.model.UndoManager
        manager.enterUndoContext(title)
        return manager

    # Öffnen, Schließen, Speichern ------------------------------------------------------------------------
    def cmd_open(self, args):
        path = args["path"]
        options = args.get("csv") or ""
        load = [_prop("Hidden", False), _prop("MacroExecutionMode", 0), _prop("UpdateDocMode", 0), _prop("ReadOnly", False)]
        if options:
            load += [_prop("FilterName", CSV_FILTER), _prop("FilterOptions", options)]
        if args.get("password"):
            load.append(_prop("Password", args["password"]))
        try:
            model = self.desktop.loadComponentFromURL(_url(path), "_blank", 0, tuple(load))
        except Exception as exc:  # noqa: BLE001 - IOException, IllegalArgumentException
            if args.get("password"):
                raise CalcError("Das Kennwort ist falsch.", "kennwort")
            raise CalcError("Die Datei ließ sich nicht öffnen. Ist sie beschädigt oder mit einem Kennwort geschützt?", "laden") from exc
        if model is None or not model.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
            if model is not None:
                model.close(True)
            raise CalcError("Diese Datei ist keine Tabelle.", "art")
        suffix = os.path.splitext(path)[1].lower()
        filter_name = CSV_FILTER if options else FILTERS.get(suffix, FILTERS[".xlsx"])
        result = self._register(model, path, filter_name, options)
        self.docs[result["doc"]].password = args.get("password") or ""  # beim Speichern wieder verschlüsseln
        return result

    def cmd_new(self, args):
        model = self.desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, (_prop("Hidden", False),))
        try:
            # wie eine neue Mappe in Excel: Calibri 11 (LibreOffice zeigt ohne Calibri das gleich breite Carlito)
            default = model.getStyleFamilies().getByName("CellStyles").getByName("Default")
            default.CharFontName = args.get("font") or "Calibri"
            default.CharHeight = float(args.get("size") or 11)
        except Exception:  # noqa: BLE001 - dann eben die Vorgabe von LibreOffice
            pass
        model.setModified(False)
        return self._register(model, "", FILTERS[".xlsx"], "")

    def _register(self, model, path, filter_name, options):
        ident = self.next_id
        self.next_id += 1
        doc = Document(ident, model, path, filter_name, options)
        self.docs[ident] = doc
        try:
            model.UndoManager.clear()
        except Exception:  # noqa: BLE001
            pass
        result = self.state(doc)
        result["doc"] = ident
        return result

    def cmd_blank(self, args):
        """Leeres Text-Dokument (»text«) oder leere Präsentation (»praesentation«) unter ``path`` anlegen (Word- bzw.
        PowerPoint-Format nach der Endung) – bearbeitet werden sie bis Beta 3/4 im Standardprogramm."""
        kind = args.get("kind")
        path = args["path"]
        suffix = os.path.splitext(path)[1].lower()
        factories = {"text": "private:factory/swriter", "praesentation": "private:factory/simpress"}
        filters = {".docx": "MS Word 2007 XML", ".odt": "writer8", ".pptx": "Impress MS PowerPoint 2007 XML", ".odp": "impress8"}
        if kind not in factories or suffix not in filters:
            raise CalcError("Diese Dateiart kann Novadesk nicht neu anlegen.", "format")
        model = self.desktop.loadComponentFromURL(factories[kind], "_blank", 0, (_prop("Hidden", True),))
        try:
            model.storeToURL(_url(path), (_prop("FilterName", filters[suffix]), _prop("Overwrite", True)))
        except Exception as exc:  # noqa: BLE001
            raise CalcError("Die Datei ließ sich nicht anlegen. Ist der Ordner schreibgeschützt?", "speichern") from exc
        finally:
            try:
                model.close(True)
            except Exception:  # noqa: BLE001
                pass
        return True

    def cmd_close(self, args):
        doc = self.docs.pop(int(args.get("doc", 0)), None)
        if doc is not None:
            if self.clip is not None and self.clip[0] is doc:
                self.clip = None
            try:
                doc.model.close(True)
            except Exception:  # noqa: BLE001 - schon geschlossen
                pass
        return True

    def cmd_save(self, args):
        """Speichern unter ``path`` im Format der Endung (CSV: nur das aktive Blatt). Erst in eine Datei daneben, dann
        ersetzen – so bleibt bei einem Fehler die bisherige Datei unverändert."""
        doc = self.doc(args)
        path = args["path"]
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in FILTERS:
            raise CalcError("In diesem Format kann Novadesk nicht speichern.", "format")
        filter_name = FILTERS[suffix]
        props = [_prop("FilterName", filter_name), _prop("Overwrite", True)]
        options = ""
        if suffix == ".csv":
            options = args.get("csv") or (doc.filter_options if doc.filter == CSV_FILTER else "") or "59,34,76,1"
            props.append(_prop("FilterOptions", options))
            if "sheet" in args:
                try:
                    doc.controller.setActiveSheet(doc.sheet(args["sheet"]))  # CSV: das Blatt, das Novadesk zeigt
                except Exception:  # noqa: BLE001
                    pass
        elif doc.password and suffix in (".xlsx", ".xlsm", ".ods"):
            props.append(_prop("Password", doc.password))
        folder = os.path.dirname(os.path.abspath(path))
        temp = ""
        try:
            handle, temp = tempfile.mkstemp(prefix=".novadesk-", suffix=suffix, dir=folder)
            os.close(handle)
            doc.model.storeToURL(_url(temp), tuple(props))
            os.replace(temp, path)
        except PermissionError as exc:
            raise CalcError("Die Datei ist in einem anderen Programm geöffnet oder schreibgeschützt.", "gesperrt") from exc
        except OSError as exc:
            raise CalcError("Die Datei ließ sich nicht speichern (%s)." % (exc.strerror or type(exc).__name__), "speichern") from exc
        except Exception as exc:  # noqa: BLE001 - IOException von LibreOffice
            raise CalcError("Die Datei ließ sich nicht speichern.", "speichern") from exc
        finally:
            if temp and os.path.exists(temp):
                try:
                    os.remove(temp)
                except OSError:
                    pass
        if not args.get("copy"):
            doc.path, doc.filter, doc.filter_options = path, filter_name, options
            self._mark_saved(doc)
        return self.changed(doc)

    @staticmethod
    def _mark_saved(doc):
        """Als gespeichert markieren – auch die Diagramme: Deren eingebettete Dokumente melden sich sonst beim
        Speichern wieder als geändert, und die Tabelle bliebe »ungespeichert«."""
        sheets = doc.model.getSheets()
        for name in sheets.getElementNames():
            charts = sheets.getByName(name).getCharts()
            for chart_name in charts.getElementNames():
                try:
                    charts.getByName(chart_name).getEmbeddedObject().setModified(False)
                except Exception:  # noqa: BLE001 - Diagramm ohne Inhalt
                    pass
        doc.model.setModified(False)

    def cmd_pdf(self, args):
        """Als PDF: ``scope`` »all« (alle Blätter, Druckbereiche beachtet), »sheet« (aktives Blatt) oder »selection«."""
        doc = self.doc(args)
        data = []
        scope = args.get("scope", "all")
        if scope == "selection":
            _sheet, selection = self.cell_range(doc, args)
            data.append(_prop("Selection", selection))
        elif scope == "sheet":
            data.append(_prop("Selection", doc.sheet(args.get("sheet", 0))))
        props = [_prop("FilterName", PDF_FILTER), _prop("Overwrite", True)]
        if data:
            props.append(_prop("FilterData", uno.Any("[]com.sun.star.beans.PropertyValue", tuple(data))))
        try:
            uno.invoke(doc.model, "storeToURL", (_url(args["path"]), tuple(props)))
        except Exception as exc:  # noqa: BLE001
            raise CalcError("Die PDF ließ sich nicht erstellen.", "pdf") from exc
        return True

    # Blätter ------------------------------------------------------------------------------------------------
    def cmd_state(self, args):
        return self.state(self.doc(args))

    def cmd_activate(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args["sheet"])
        try:
            doc.controller.setActiveSheet(sheet)
        except Exception:  # noqa: BLE001
            pass
        return self.changed(doc)

    def _unique_name(self, doc, base):
        sheets = doc.model.Sheets
        if not sheets.hasByName(base):
            return base
        number = 2
        stem = base.rstrip("0123456789").rstrip() or base
        while sheets.hasByName("%s%d" % (stem, number)):
            number += 1
        return "%s%d" % (stem, number)

    def cmd_add_sheet(self, args):
        doc = self.doc(args)
        sheets = doc.model.Sheets
        count = sheets.getCount()
        name = self._unique_name(doc, args.get("name") or "Tabelle%d" % (count + 1))
        at = int(args.get("at", count))
        sheets.insertNewByName(name, max(0, min(count, at)))
        sheet = sheets.getByName(name)
        try:
            doc.controller.setActiveSheet(sheet)
        except Exception:  # noqa: BLE001
            pass
        return self.changed(doc)

    def cmd_rename_sheet(self, args):
        doc = self.doc(args)
        name = str(args.get("name") or "").strip()
        bad = set("[]*?:/\\")
        if not name or len(name) > 31 or any(ch in bad for ch in name) or name.startswith("'") or name.endswith("'"):
            raise CalcError("Der Name ist nicht erlaubt (höchstens 31 Zeichen, ohne [ ] * ? : / \\).", "name")
        sheet = doc.sheet(args["sheet"])
        if sheet.getName() != name and doc.model.Sheets.hasByName(name):
            raise CalcError("Es gibt schon ein Blatt mit diesem Namen.", "name")
        sheet.setName(name)
        return self.changed(doc)

    def cmd_delete_sheet(self, args):
        doc = self.doc(args)
        sheets = doc.model.Sheets
        if sheets.getCount() <= 1:
            raise CalcError("Das letzte Blatt lässt sich nicht löschen.", "blatt")
        sheet = doc.sheet(args["sheet"])
        sheets.removeByName(sheet.getName())
        return self.changed(doc)

    def cmd_move_sheet(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args["sheet"])
        sheets = doc.model.Sheets
        target = int(args["to"])
        # moveByName: Ziel ist die Stelle *vor* dem Blatt mit diesem Index (nach rechts: eins weiter)
        if target > int(args["sheet"]):
            target += 1
        sheets.moveByName(sheet.getName(), max(0, min(sheets.getCount(), target)))
        return self.changed(doc)

    def cmd_tab_color(self, args):
        doc = self.doc(args)
        doc.sheet(args["sheet"]).TabColor = _parse_color(args.get("color"))
        return self.changed(doc)

    # Aufbau eines Blatts --------------------------------------------------------------------------------------
    def cmd_sheet(self, args):
        """Größe (benutzter Bereich), Spaltenbreiten, Fixierung, verbundene Zellen, Filter, Objekte, Druckbereich."""
        doc = self.doc(args)
        index = int(args.get("sheet", 0))
        sheet = doc.sheet(index)
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(False)
        used = cursor.getRangeAddress()
        last_row, last_col = used.EndRow, used.EndColumn
        columns = sheet.getColumns()
        count = min(columns.getCount(), max(last_col + 1, int(args.get("columns", 0))) + 30)
        widths, hidden_cols = [], []
        for col in range(count):
            column = columns.getByIndex(col)
            widths.append(int(column.Width))
            if not column.IsVisible:
                hidden_cols.append(col)
        rows = sheet.getRows()
        return {
            "rows": last_row + 1,
            "cols": last_col + 1,
            "maxRows": rows.getCount(),
            "maxCols": columns.getCount(),
            "widths": widths,
            "hiddenCols": hidden_cols,
            "defaultWidth": int(columns.getByIndex(min(columns.getCount() - 1, count)).Width),
            "defaultHeight": int(rows.getByIndex(min(rows.getCount() - 1, last_row + 1000)).Height) if last_row + 1000 < rows.getCount() else 452,
            "freeze": self._freeze(doc, sheet),
            "merges": self._merges(sheet, last_row, last_col),
            "filter": self._filter_info(doc, sheet, index),
            "objects": self._objects(sheet),
            "printArea": [self._range_list(area) for area in sheet.getPrintAreas()],
            "grid": bool(self._view_flag(doc, "ShowGrid", True)),
        }

    def _range_list(self, address):
        return [address.StartRow, address.StartColumn, address.EndRow, address.EndColumn]

    def _view_flag(self, doc, name, default):
        try:
            return getattr(doc.controller, name)
        except Exception:  # noqa: BLE001
            return default

    def cmd_rows(self, args):
        """Höhen und ausgeblendete Zeilen von ``start`` bis ``end`` (einschließlich) – in Stücken abgefragt."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        rows = sheet.getRows()
        start = max(0, int(args["start"]))
        end = min(rows.getCount() - 1, int(args["end"]))
        heights, hidden = [], []
        for row in range(start, end + 1):
            item = rows.getByIndex(row)
            heights.append(int(item.Height))
            if not item.IsVisible:
                hidden.append(row)
        return {"start": start, "heights": heights, "hidden": hidden}

    def _freeze(self, doc, sheet):
        """Fixierte Zeilen und Spalten [Zeilen, Spalten] – aus der Ansicht von LibreOffice: Der Bereich oben links
        (erster Teil der Ansicht) endet vor der ersten beweglichen Zeile bzw. Spalte."""
        try:
            controller = doc.controller
            if controller.getActiveSheet().getRangeAddress().Sheet != sheet.getRangeAddress().Sheet:
                controller.setActiveSheet(sheet)
            if not controller.hasFrozenPanes():
                return [0, 0]
            first = controller.getByIndex(0).getVisibleRange()
            rows = first.EndRow + 1 if controller.getSplitVertical() > 0 else 0
            cols = first.EndColumn + 1 if controller.getSplitHorizontal() > 0 else 0
            return [rows, cols]
        except Exception:  # noqa: BLE001
            return [0, 0]

    def cmd_freeze(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        controller = doc.controller
        controller.setActiveSheet(sheet)
        rows, cols = max(0, int(args.get("rows", 0))), max(0, int(args.get("cols", 0)))
        # die Ansicht nach oben links: fixiert wird ab der ersten Zeile und Spalte (wie Excel »Oberste Zeile fixieren«)
        controller.freezeAtPosition(0, 0)
        if rows or cols:
            try:
                controller.select(sheet.getCellByPosition(0, 0))
            except Exception:  # noqa: BLE001
                pass
            controller.freezeAtPosition(cols, rows)
        doc.model.setModified(True)
        return self.changed(doc, {"freeze": [rows, cols]})

    def _merges(self, sheet, last_row, last_col):
        """Verbundene Zellen im benutzten Bereich: [Zeile, Spalte, letzte Zeile, letzte Spalte]."""
        found = []
        if last_row < 0 or last_col < 0:
            return found
        ranges = sheet.getCellRangeByPosition(0, 0, last_col, last_row).getCellFormatRanges()
        for index in range(ranges.getCount()):
            block = ranges.getByIndex(index)
            if not block.getIsMerged():
                continue
            a = block.getRangeAddress()
            for row in range(a.StartRow, a.EndRow + 1):
                for col in range(a.StartColumn, a.EndColumn + 1):
                    cursor = sheet.createCursorByRange(sheet.getCellByPosition(col, row))
                    cursor.collapseToMergedArea()
                    m = cursor.getRangeAddress()
                    if m.StartRow == row and m.StartColumn == col and (m.EndRow > row or m.EndColumn > col):
                        found.append([row, col, m.EndRow, m.EndColumn])
        return found

    # Zellen --------------------------------------------------------------------------------------------------
    def cmd_cells(self, args):
        """Inhalt und Aussehen eines Bereichs. ``cells``: Zeilen mit je einem Eintrag pro Spalte – ``None`` (leer, ohne
        Format) oder [Text, Art, Stil]. Art: »n« Zahl, »t« Text, »e« Fehler, »" "« leer. ``styles``: neue Stile."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        a = block.getRangeAddress()
        r0, c0 = a.StartRow, a.StartColumn
        height, width = a.EndRow - r0 + 1, a.EndColumn - c0 + 1
        styles = [[0] * width for _ in range(height)]
        new_styles = {}
        ranges = block.getCellFormatRanges()
        for index in range(ranges.getCount()):
            part = ranges.getByIndex(index)
            style = self._style_of(part)
            number = doc.styles.get(style)
            if number is None:
                number = len(doc.styles) + 1
                doc.styles[style] = number
                new_styles[number] = self._style_dict(style)
            pa = part.getRangeAddress()
            for row in range(pa.StartRow, pa.EndRow + 1):
                line = styles[row - r0]
                for col in range(pa.StartColumn, pa.EndColumn + 1):
                    line[col - c0] = number
        default = doc.styles.get(self._default_style(doc))
        cells = [[None if styles[r][c] == default else ["", " ", styles[r][c]] for c in range(width)] for r in range(height)]
        content = block.queryContentCells(CONTENT_DATA)
        enum = content.getCells().createEnumeration()
        while enum.hasMoreElements():
            cell = enum.nextElement()
            ca = cell.getCellAddress()
            row, col = ca.Row - r0, ca.Column - c0
            kind = cell.getType().value
            if kind == "VALUE":
                art = "n"
            elif kind == "TEXT":
                art = "t"
            elif kind == "FORMULA":
                if cell.getError():
                    art = "e"
                else:
                    art = "n" if cell.FormulaResultType2 == RESULT_VALUE else "t"
            else:
                continue
            cells[row][col] = [cell.getString(), art, styles[row][col]]
        return {"range": [r0, c0, a.EndRow, a.EndColumn], "cells": cells, "styles": new_styles, "default": default or 0}

    def _default_style(self, doc):
        key = getattr(doc, "_default", None)
        if key is None:
            sheet = doc.model.Sheets.getByIndex(0)
            columns = sheet.getColumns()
            probe = sheet.getCellByPosition(columns.getCount() - 1, sheet.getRows().getCount() - 1)
            key = self._style_of(probe)
            if key not in doc.styles:
                doc.styles[key] = len(doc.styles) + 1
            doc._default = key
        return key

    def _border(self, line):
        try:
            if line is None or (int(line.OuterLineWidth) + int(line.InnerLineWidth) + int(getattr(line, "LineWidth", 0))) == 0:
                return None
            width = max(int(getattr(line, "LineWidth", 0)), int(line.OuterLineWidth) + int(line.InnerLineWidth))
            return (_color(line.Color) or "#000000", width, int(getattr(line, "LineStyle", 0)))
        except Exception:  # noqa: BLE001
            return None

    def _style_of(self, part):
        """Aussehen eines einheitlich formatierten Bereichs als Tupel (Schlüssel der Stil-Tabelle)."""
        background = -1 if part.IsCellBackgroundTransparent else part.CellBackColor
        return (
            part.CharFontName, round(float(part.CharHeight), 1), float(part.CharWeight) >= BOLD,
            _enum_value(part.CharPosture) not in ("NONE", 0), int(part.CharUnderline) != 0, int(part.CharStrikeout) not in (0, 3),
            _color(part.CharColor), _color(background), _enum_value(part.HoriJustify), int(part.VertJustify),
            bool(part.IsTextWrapped),
            self._border(part.TopBorder2), self._border(part.BottomBorder2), self._border(part.LeftBorder2), self._border(part.RightBorder2),
            int(part.NumberFormat),
        )

    def _style_dict(self, style):
        font, size, bold, italic, underline, strike, color, background, halign, valign, wrap, top, bottom, left, right, number = style
        return {
            "font": font, "size": size, "bold": bold, "italic": italic, "underline": underline, "strike": strike,
            "color": color, "background": background, "halign": {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "BLOCK": "justify"}.get(halign, ""),
            "valign": {1: "top", 2: "center", 3: "bottom"}.get(valign, ""), "wrap": wrap,
            "top": top, "bottom": bottom, "left": left, "right": right, "format": number,
        }

    def cmd_cell(self, args):
        """Eine Zelle für die Formelzeile: Eingabe (Formel mit deutschen Funktionsnamen) und Format."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        cell = sheet.getCellByPosition(int(args["col"]), int(args["row"]))
        cursor = sheet.createCursorByRange(cell)
        cursor.collapseToMergedArea()
        style = self._style_dict(self._style_of(cell))
        return {"input": cell.FormulaLocal if cell.getType().value != "EMPTY" else "", "style": style,
                "formatKind": self._format_kind(doc, cell.NumberFormat), "merged": _address(cursor)}

    def _format_kind(self, doc, key):
        try:
            number_format = doc.model.NumberFormats.getByKey(key)
            kind = int(number_format.Type)
            code = str(number_format.FormatString)
        except Exception:  # noqa: BLE001
            return "standard"
        # Eigene Formate aus Excel wie »#.##0,00 "€"« meldet LibreOffice als Zahl – für die Knöpfe ist es Währung
        if not kind & 8 and not kind & 2 and ("€" in code or "[$" in code):
            kind |= 8
        # com.sun.star.util.NumberFormat: DATE 2, TIME 4, CURRENCY 8, NUMBER 16, PERCENT 128, TEXT 256, DATETIME 6
        if kind & 8:
            return "currency"
        if kind & 128:
            return "percent"
        if kind & 2 and kind & 4:
            return "datetime"
        if kind & 2:
            return "date"
        if kind & 4:
            return "time"
        if kind & 256:
            return "text"
        if key % 10000 == 0:
            return "standard"
        return "number"

    def cmd_input(self, args):
        """Eingabe in eine Zelle wie in Excel getippt: »=SUMME(A1:A3)«, »1.250,50«, »01.01.2026«, »15 %«, Text."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        cell = sheet.getCellByPosition(int(args["col"]), int(args["row"]))
        text = str(args.get("text", ""))
        if text == "":
            cell.setString("")
            sheet.getCellRangeByPosition(int(args["col"]), int(args["row"]), int(args["col"]), int(args["row"])).clearContents(CONTENT_DATA)
        else:
            cell.FormulaLocal = text
        return self.changed(doc)

    def cmd_paste_text(self, args):
        """Text aus der Zwischenablage (Zeilen und Spalten, z. B. aus Excel oder einer Webseite) ab einer Zelle."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        rows = args.get("rows") or []
        r0, c0 = int(args["row"]), int(args["col"])
        manager = self.undo_context(doc, "Einfügen")
        try:
            for r, line in enumerate(rows):
                for c, text in enumerate(line):
                    cell = sheet.getCellByPosition(c0 + c, r0 + r)
                    if text == "":
                        cell.setString("")
                    else:
                        cell.FormulaLocal = str(text)
        finally:
            manager.leaveUndoContext()
        height = len(rows)
        width = max((len(line) for line in rows), default=0)
        return self.changed(doc, {"pasted": [r0, c0, r0 + max(0, height - 1), c0 + max(0, width - 1)]})

    def cmd_clear(self, args):
        doc = self.doc(args)
        _sheet, block = self.cell_range(doc, args)
        what = args.get("what", "contents")
        flags = CONTENT_DATA if what == "contents" else HARD_FORMATS if what == "formats" else CONTENT_ALL | HARD_FORMATS | 128
        block.clearContents(flags)
        return self.changed(doc)

    def cmd_copy(self, args):
        """Bereich kopieren: LibreOffice merkt sich Inhalt und Formate; zurück kommt der Text für die Zwischenablage."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        controller = doc.controller
        controller.setActiveSheet(sheet)
        controller.select(block)
        transferable = controller.getTransferable()
        a = block.getRangeAddress()
        lines = []
        for row in range(a.StartRow, a.EndRow + 1):
            lines.append("\t".join(sheet.getCellByPosition(col, row).getString() for col in range(a.StartColumn, a.EndColumn + 1)))
        text = "\r\n".join(lines) + "\r\n"
        self.clip = (doc, transferable, text, bool(args.get("cut")), int(args.get("sheet", 0)), [a.StartRow, a.StartColumn, a.EndRow, a.EndColumn])
        return {"text": text}

    def cmd_paste(self, args):
        """Zuletzt in Novadesk kopierten Bereich einfügen (mit Formaten). ``text``: was jetzt in der Zwischenablage
        steht – stammt es nicht mehr aus Novadesk, wird es als Text eingefügt."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        text = args.get("text")
        clip = self.clip
        if clip is None or (text is not None and text.replace("\r\n", "\n") != clip[2].replace("\r\n", "\n")):
            raise CalcError("Nichts zum Einfügen aus Novadesk.", "zwischenablage")
        source_doc, transferable, _text, cut, source_sheet, source = clip
        if source_doc.ident not in self.docs:
            raise CalcError("Die kopierte Tabelle ist geschlossen.", "zwischenablage")
        controller = doc.controller
        controller.setActiveSheet(sheet)
        r0, c0 = int(args["row"]), int(args["col"])
        height, width = source[2] - source[0], source[3] - source[1]
        controller.select(sheet.getCellRangeByPosition(c0, r0, c0 + width, r0 + height))
        manager = self.undo_context(doc, "Einfügen")
        try:
            controller.insertTransferable(transferable)
            if cut:
                # Ausschneiden: die Quelle leeren (einmal), es sei denn, sie liegt genau am Ziel
                if not (source_doc is doc and source_sheet == int(args.get("sheet", 0)) and source[0] == r0 and source[1] == c0):
                    src = source_doc.sheet(source_sheet).getCellRangeByPosition(source[1], source[0], source[3], source[2])
                    target = sheet.getCellRangeByPosition(c0, r0, c0 + width, r0 + height).getRangeAddress()
                    if source_doc is doc and source_sheet == int(args.get("sheet", 0)):
                        self._clear_outside(sheet, source, target)
                    else:
                        src.clearContents(CONTENT_ALL | HARD_FORMATS)
                self.clip = None
        finally:
            manager.leaveUndoContext()
        return self.changed(doc, {"pasted": [r0, c0, r0 + height, c0 + width], "cut": bool(cut)})

    def _clear_outside(self, sheet, source, target):
        """Ausschneiden im selben Blatt: nur die Zellen der Quelle leeren, die nicht im Ziel liegen."""
        for row in range(source[0], source[2] + 1):
            for col in range(source[1], source[3] + 1):
                inside = target.StartRow <= row <= target.EndRow and target.StartColumn <= col <= target.EndColumn
                if not inside:
                    sheet.getCellRangeByPosition(col, row, col, row).clearContents(CONTENT_ALL | HARD_FORMATS)

    def cmd_fill(self, args):
        """Ausfüllen nach unten oder rechts (Strg+U / Strg+R): die erste Zeile bzw. Spalte des Bereichs übernehmen."""
        doc = self.doc(args)
        _sheet, block = self.cell_range(doc, args)
        direction = {"down": 0, "right": 1, "up": 2, "left": 3}[args.get("direction", "down")]
        source = max(1, int(args.get("source", 1)))  # Ausfüllkästchen: so viele Zeilen/Spalten bilden die Reihe (1, 2 → 3, 4 …)
        manager = self.undo_context(doc, "Ausfüllen")
        try:
            block.fillAuto(uno.Enum("com.sun.star.sheet.FillDirection", ["TO_BOTTOM", "TO_RIGHT", "TO_TOP", "TO_LEFT"][direction]), source)
        finally:
            manager.leaveUndoContext()
        return self.changed(doc)

    # Formate --------------------------------------------------------------------------------------------------
    def cmd_format(self, args):
        """Zeichen und Zelle: bold, italic, underline, strike, font, size, color, background, halign, valign, wrap."""
        doc = self.doc(args)
        _sheet, block = self.cell_range(doc, args)
        values = args.get("set") or {}
        manager = self.undo_context(doc, "Format")
        try:
            for key, value in values.items():
                if key == "bold":
                    block.CharWeight = BOLD if value else 100.0
                elif key == "italic":
                    block.CharPosture = uno.Enum("com.sun.star.awt.FontSlant", "ITALIC" if value else "NONE")
                elif key == "underline":
                    block.CharUnderline = 1 if value else 0
                elif key == "strike":
                    block.CharStrikeout = 1 if value else 0
                elif key == "font":
                    block.CharFontName = str(value)
                elif key == "size":
                    block.CharHeight = max(1.0, min(409.0, float(value)))
                elif key == "color":
                    block.CharColor = _parse_color(value)
                elif key == "background":
                    if value:
                        block.CellBackColor = _parse_color(value)
                    else:
                        block.IsCellBackgroundTransparent = True
                elif key == "halign":
                    block.HoriJustify = uno.Enum("com.sun.star.table.CellHoriJustify", {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "BLOCK"}.get(value, "STANDARD"))
                elif key == "valign":
                    block.VertJustify = {"top": 1, "center": 2, "bottom": 3}.get(value, 0)
                elif key == "wrap":
                    block.IsTextWrapped = bool(value)
        finally:
            manager.leaveUndoContext()
        return self.changed(doc)

    def cmd_number_format(self, args):
        """Zahlenformat: standard, number, currency, percent, date, time, datetime, text – oder ``decimals`` ±1."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        formats = doc.model.NumberFormats
        locale = _locale()
        kind = args.get("kind", "")
        index = uno.getConstantByName
        if args.get("decimals"):
            first = sheet.getCellByPosition(block.getRangeAddress().StartColumn, block.getRangeAddress().StartRow)
            key = first.NumberFormat
            current = formats.getByKey(key)
            decimals = max(0, min(10, int(current.Decimals) + int(args["decimals"])))
            code = formats.generateFormat(key, locale, bool(current.ThousandsSeparator), bool(current.NegativeRed), decimals, max(1, int(current.LeadingZeros)))
            key = formats.queryKey(code, locale, False)
            if key < 0:
                key = formats.addNew(code, locale)
        elif kind == "standard":
            key = 0
        elif kind == "number":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.NUMBER_1000DEC2"), locale)
        elif kind == "currency":
            key = formats.getStandardFormat(8, locale)
        elif kind == "percent":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.PERCENT_DEC2"), locale)
        elif kind == "date":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.DATE_SYS_DDMMYYYY"), locale)
        elif kind == "time":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.TIME_HHMMSS"), locale)
        elif kind == "datetime":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.DATETIME_SYS_DDMMYYYY_HHMMSS"), locale)
        elif kind == "text":
            key = formats.getFormatIndex(index("com.sun.star.i18n.NumberFormatIndex.TEXT"), locale)
        else:
            raise CalcError("Unbekanntes Zahlenformat.", "format")
        block.NumberFormat = key
        return self.changed(doc)

    def cmd_borders(self, args):
        """Rahmen: »all« (alle Linien), »outer« (außen), »bottom«, »top«, »left«, »right«, »thick« (dicker Rahmen außen),
        »none« (keine)."""
        doc = self.doc(args)
        _sheet, block = self.cell_range(doc, args)
        preset = args.get("preset", "all")
        color = _parse_color(args.get("color") or "#000000")
        border = block.TableBorder2
        thin = uno.createUnoStruct("com.sun.star.table.BorderLine2")
        thin.Color, thin.OuterLineWidth, thin.LineWidth, thin.LineStyle = color, 26 if preset != "thick" else 53, 26 if preset != "thick" else 53, 0
        none = uno.createUnoStruct("com.sun.star.table.BorderLine2")
        sides = {
            "all": ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"),
            "outer": ("Top", "Bottom", "Left", "Right"), "thick": ("Top", "Bottom", "Left", "Right"),
            "bottom": ("Bottom",), "top": ("Top",), "left": ("Left",), "right": ("Right",), "none": (),
        }[preset]
        for side in ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"):
            if preset == "none" or side in sides:
                setattr(border, side + "Line", thin if side in sides else none)
                setattr(border, "Is" + side + "LineValid", True)
            else:
                setattr(border, "Is" + side + "LineValid", False)
        border.IsDistanceValid = False
        block.TableBorder2 = border
        return self.changed(doc)

    def cmd_merge(self, args):
        doc = self.doc(args)
        _sheet, block = self.cell_range(doc, args)
        block.merge(bool(args.get("merge", True)))
        return self.changed(doc)

    # Zeilen und Spalten ----------------------------------------------------------------------------------------
    def cmd_insert(self, args):
        """Zeilen (``axis`` »rows«) oder Spalten (»cols«) einfügen bzw. löschen (``delete``) ab ``at``."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        at, count = int(args["at"]), max(1, int(args.get("count", 1)))
        group = sheet.getRows() if args.get("axis") == "rows" else sheet.getColumns()
        try:
            if args.get("delete"):
                group.removeByIndex(at, count)
            else:
                group.insertByIndex(at, count)
        except Exception as exc:  # noqa: BLE001 - z. B. Daten am Ende würden herausgeschoben
            raise CalcError("Das geht nicht: Am Ende des Blatts ist kein Platz mehr oder verbundene Zellen sind im Weg.", "einfuegen") from exc
        return self.changed(doc)

    def cmd_size(self, args):
        """Breite der Spalten bzw. Höhe der Zeilen ``indexes`` (1/100 mm) setzen; ``optimal``: passend zum Inhalt;
        ``hidden``: aus- bzw. einblenden."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        rows = args.get("axis") == "rows"
        group = sheet.getRows() if rows else sheet.getColumns()
        manager = self.undo_context(doc, "Zeilenhöhe" if rows else "Spaltenbreite")
        try:
            for index in args.get("indexes", []):
                item = group.getByIndex(int(index))
                if "hidden" in args:
                    item.IsVisible = not args["hidden"]
                elif args.get("optimal"):
                    if rows:
                        item.OptimalHeight = True
                    else:
                        item.OptimalWidth = True
                else:
                    value = max(0, int(args["size"]))
                    if rows:
                        item.Height = value
                    else:
                        item.Width = value
        finally:
            manager.leaveUndoContext()
        return self.changed(doc)

    # Daten ----------------------------------------------------------------------------------------------------
    def _region(self, sheet, block):
        """Ein einzelne Zelle steht für die zusammenhängende Tabelle um sie herum (wie in Excel)."""
        a = block.getRangeAddress()
        if a.StartRow == a.EndRow and a.StartColumn == a.EndColumn:
            cursor = sheet.createCursorByRange(block)
            cursor.collapseToCurrentRegion()
            return cursor
        return block

    def cmd_sort(self, args):
        """Sortieren nach einer Spalte (``col``, absolut) – die Tabelle um die Auswahl, Kopfzeile erkannt."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        region = self._region(sheet, block)
        a = region.getRangeAddress()
        col = int(args.get("col", a.StartColumn))
        if not a.StartColumn <= col <= a.EndColumn:
            col = a.StartColumn
        header = args.get("header")
        if header is None:
            header = self._has_header(sheet, a)
        field = uno.createUnoStruct("com.sun.star.table.TableSortField")
        field.Field = col - a.StartColumn
        field.IsAscending = bool(args.get("ascending", True))
        field.IsCaseSensitive = False
        descriptor = [_prop("SortFields", uno.Any("[]com.sun.star.table.TableSortField", (field,))),
                      _prop("ContainsHeader", bool(header)), _prop("IsSortColumns", False), _prop("BindFormatsToContent", True)]
        uno.invoke(region, "sort", (tuple(descriptor),))
        return self.changed(doc, {"range": [a.StartRow, a.StartColumn, a.EndRow, a.EndColumn], "header": bool(header)})

    def _has_header(self, sheet, a):
        """Kopfzeile, wenn die erste Zeile nur Text enthält und darunter eine Zahl oder Formel steht – oder die erste
        Zeile fett ist und die zweite nicht (wie »Bereich enthält Spaltenbeschriftungen« in Excel)."""
        if a.EndRow <= a.StartRow:
            return False
        first = [sheet.getCellByPosition(c, a.StartRow) for c in range(a.StartColumn, a.EndColumn + 1)]
        second = [sheet.getCellByPosition(c, a.StartRow + 1) for c in range(a.StartColumn, a.EndColumn + 1)]
        if any(cell.getType().value == "VALUE" for cell in first):
            return False
        if not any(cell.getType().value == "TEXT" for cell in first):
            return False
        if any(cell.getType().value in ("VALUE", "FORMULA") for cell in second):
            return True
        return bool(first[0].CharWeight >= BOLD and second[0].CharWeight < BOLD)

    def _database(self, doc, index):
        ranges = doc.model.getPropertyValue("UnnamedDatabaseRanges")
        return ranges.getByTable(index) if ranges.hasByTable(index) else None

    def _filter_info(self, doc, sheet, index):
        """Autofilter des Blatts: Bereich, Spalten mit Filter (Werte, soweit bekannt)."""
        try:
            database = self._database(doc, index)
        except Exception:  # noqa: BLE001
            database = None
        if database is None or not database.AutoFilter:
            return None
        a = database.getDataArea()
        active = {}
        try:
            for field in database.getFilterDescriptor().FilterFields3:
                col = a.StartColumn + int(field.Field)
                active[str(col)] = doc.filters.get(index, {}).get(col)
        except Exception:  # noqa: BLE001
            pass
        return {"range": [a.StartRow, a.StartColumn, a.EndRow, a.EndColumn], "active": active}

    def cmd_autofilter(self, args):
        """Filter ein- oder ausschalten (``on``) für die Tabelle um die Auswahl."""
        doc = self.doc(args)
        index = int(args.get("sheet", 0))
        sheet, block = self.cell_range(doc, args)
        ranges = doc.model.getPropertyValue("UnnamedDatabaseRanges")
        manager = self.undo_context(doc, "Filter")
        try:
            existing = self._database(doc, index)
            if existing is not None and existing.AutoFilter and not args.get("on", False):
                descriptor = existing.getFilterDescriptor()
                descriptor.FilterFields3 = ()
                existing.refresh()
                existing.AutoFilter = False
                doc.filters.pop(index, None)
            elif args.get("on", True):
                region = self._region(sheet, block)
                ranges.setByTable(region.getRangeAddress())
                database = ranges.getByTable(index)
                database.AutoFilter = True
                database.getFilterDescriptor().ContainsHeader = True
                doc.filters.pop(index, None)
        finally:
            manager.leaveUndoContext()
        return self.changed(doc, {"filter": self._filter_info(doc, sheet, index)})

    def cmd_filter_values(self, args):
        """Werte einer Spalte für das Filter-Menü: [{text, checked}] (sortiert, leer als »(Leer)«)."""
        doc = self.doc(args)
        index = int(args.get("sheet", 0))
        sheet = doc.sheet(index)
        database = self._database(doc, index)
        if database is None:
            raise CalcError("Für diese Tabelle ist kein Filter eingeschaltet.", "filter")
        a = database.getDataArea()
        col = int(args["col"])
        chosen = doc.filters.get(index, {}).get(col)
        filtered = False
        try:
            filtered = any(a.StartColumn + int(field.Field) == col for field in database.getFilterDescriptor().FilterFields3)
        except Exception:  # noqa: BLE001
            pass
        values = {}
        numbers = {}
        shown = set()
        rows = sheet.getRows()
        for row in range(a.StartRow + 1, a.EndRow + 1):
            cell = sheet.getCellByPosition(col, row)
            text = cell.getString()
            values[text] = True
            if cell.getType().value == "VALUE" or (cell.getType().value == "FORMULA" and cell.FormulaResultType2 == RESULT_VALUE):
                numbers[text] = cell.getValue()
            if filtered and chosen is None and rows.getByIndex(row).IsVisible:
                shown.add(text)
        if filtered and chosen is None:
            # Filter aus der Datei (z. B. in Excel gesetzt): angehakt ist, was gerade zu sehen ist
            chosen = shown

        def order(text):
            return (0, numbers[text], "") if text in numbers else (1 if text else 2, 0, text.lower())

        items = [{"text": text, "checked": chosen is None or text in chosen} for text in sorted(values, key=order)]
        return {"col": col, "values": items}

    def cmd_filter(self, args):
        """Filter einer Spalte setzen: ``values`` (angezeigte Texte) oder ``None`` (alle zeigen)."""
        doc = self.doc(args)
        index = int(args.get("sheet", 0))
        sheet = doc.sheet(index)
        database = self._database(doc, index)
        if database is None:
            raise CalcError("Für diese Tabelle ist kein Filter eingeschaltet.", "filter")
        a = database.getDataArea()
        col = int(args["col"])
        chosen = args.get("values")
        filters = doc.filters.setdefault(index, {})
        if chosen is None:
            filters.pop(col, None)
        else:
            filters[col] = list(chosen)
        fields = []
        for column, texts in sorted(filters.items()):
            field = uno.createUnoStruct("com.sun.star.sheet.TableFilterField3")
            field.Connection = uno.Enum("com.sun.star.sheet.FilterConnection", "AND")
            field.Field = column - a.StartColumn
            field.Operator = 2  # com.sun.star.sheet.FilterOperator2.EQUAL
            entries = []
            for text in texts:
                value = uno.createUnoStruct("com.sun.star.sheet.FilterFieldValue")
                value.IsNumeric = False
                value.StringValue = text
                if hasattr(value, "FilterType"):
                    value.FilterType = 1  # com.sun.star.sheet.FilterFieldType.STRING (0 wäre NUMERIC)
                entries.append(value)
            field.Values = tuple(entries)
            fields.append(field)
        manager = self.undo_context(doc, "Filter")
        try:
            descriptor = database.getFilterDescriptor()
            descriptor.ContainsHeader = True
            descriptor.FilterFields3 = tuple(fields)
            database.refresh()
        finally:
            manager.leaveUndoContext()
        return self.changed(doc, {"filter": self._filter_info(doc, sheet, index)})

    def cmd_print_area(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        if args.get("range"):
            _sheet, block = self.cell_range(doc, args)
            sheet.setPrintAreas((block.getRangeAddress(),))
        else:
            sheet.setPrintAreas(())
        doc.model.setModified(True)
        return self.changed(doc)

    def cmd_find(self, args):
        """Nächste Zelle mit ``text`` ab der Zelle hinter ``row``/``col`` (in Zeilen gelesen, am Ende wieder oben)."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        search = sheet.createSearchDescriptor()
        search.SearchString = str(args.get("text", ""))
        search.SearchCaseSensitive = False
        search.SearchWords = False
        if not search.SearchString:
            return None
        found = sheet.findAll(search)
        if found is None:
            return None
        hits = []
        for index in range(found.getCount()):
            a = found.getByIndex(index).getRangeAddress()
            for row in range(a.StartRow, a.EndRow + 1):
                for col in range(a.StartColumn, a.EndColumn + 1):
                    hits.append((row, col))
        if not hits:
            return None
        hits.sort()
        here = (int(args.get("row", -1)), int(args.get("col", -1)))
        if args.get("backward"):
            before = [hit for hit in hits if hit < here]
            target = before[-1] if before else hits[-1]
        else:
            after = [hit for hit in hits if hit > here]
            target = after[0] if after else hits[0]
        return {"row": target[0], "col": target[1], "count": len(hits), "index": hits.index(target) + 1}

    def cmd_edge(self, args):
        """Strg+Pfeil wie in Excel: im gefüllten Bereich an dessen Ende, sonst zur nächsten gefüllten Zelle, sonst an
        den Rand des Blatts."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        row, col = int(args["row"]), int(args["col"])
        dr, dc = int(args.get("dr", 0)), int(args.get("dc", 0))
        cursor = sheet.createCursor()
        cursor.gotoEndOfUsedArea(False)
        used = cursor.getRangeAddress()
        max_row = sheet.getRows().getCount() - 1
        max_col = sheet.getColumns().getCount() - 1
        if dr:
            limit = max_row if dr > 0 else 0
            last_used = used.EndRow
            if dr > 0 and row >= last_used:
                return {"row": max_row, "col": col}
            lo, hi = (row, last_used) if dr > 0 else (0, row)
            line = [r[0] for r in sheet.getCellRangeByPosition(col, lo, col, max(lo, hi)).getDataArray()]
            index = row - lo
        else:
            limit = max_col if dc > 0 else 0
            last_used = used.EndColumn
            if dc > 0 and col >= last_used:
                return {"row": row, "col": max_col}
            lo, hi = (col, last_used) if dc > 0 else (0, col)
            line = list(sheet.getCellRangeByPosition(lo, row, max(lo, hi), row).getDataArray()[0])
            index = col - lo
        step = 1 if (dr or dc) > 0 else -1
        filled = [value != "" for value in line]
        here = filled[index]
        nxt = index + step
        if 0 <= nxt < len(filled) and here and filled[nxt]:
            while 0 <= nxt + step < len(filled) and filled[nxt + step]:
                nxt += step
            target = nxt
        else:
            while 0 <= nxt < len(filled) and not filled[nxt]:
                nxt += step
            target = nxt if 0 <= nxt < len(filled) else None
        if target is None:
            position = limit
        else:
            position = lo + target
        return {"row": position, "col": col} if dr else {"row": row, "col": position}

    def cmd_stats(self, args):
        """Statuszeile: Summe (im Format der ersten Zahl), Anzahl der Zahlen und gefüllten Zellen, Mittelwert."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        filled = block.queryContentCells(CONTENT_DATA)
        count = 0
        for index in range(filled.getCount()):
            a = filled.getByIndex(index).getRangeAddress()
            count += (a.EndRow - a.StartRow + 1) * (a.EndColumn - a.StartColumn + 1)
        if count == 0:
            return {"count": 0, "numbers": 0, "sum": "", "average": ""}
        numbers = int(block.computeFunction(uno.Enum("com.sun.star.sheet.GeneralFunction", "COUNTNUMS")))
        if numbers == 0:
            return {"count": count, "numbers": 0, "sum": "", "average": ""}
        total = block.computeFunction(uno.Enum("com.sun.star.sheet.GeneralFunction", "SUM"))
        average = block.computeFunction(uno.Enum("com.sun.star.sheet.GeneralFunction", "AVERAGE"))
        key = 0
        values = block.queryContentCells(1 | 2 | 16)
        if values.getCount():
            first = values.getByIndex(0).getRangeAddress()
            key = sheet.getCellByPosition(first.StartColumn, first.StartRow).NumberFormat
        formatter = self.smgr.createInstanceWithContext("com.sun.star.util.NumberFormatter", self.ctx)
        formatter.attachNumberFormatsSupplier(doc.model)
        return {"count": count, "numbers": numbers, "sum": formatter.convertNumberToString(key, total),
                "average": formatter.convertNumberToString(key, average)}

    # Objekte (Diagramme, Bilder) --------------------------------------------------------------------------------
    def _objects(self, sheet):
        page = sheet.getDrawPage()
        found = []
        for index in range(page.getCount()):
            shape = page.getByIndex(index)
            try:
                kind = "chart" if shape.ShapeType == "com.sun.star.drawing.OLE2Shape" and self._chart_name(sheet, shape) else "image"
                position, size = shape.Position, shape.Size
                found.append({"index": index, "kind": kind, "name": self._chart_name(sheet, shape) or getattr(shape, "Name", "") or "",
                              "x": int(position.X), "y": int(position.Y), "w": int(size.Width), "h": int(size.Height)})
            except Exception:  # noqa: BLE001 - unbekannte Form: auslassen
                continue
        return found

    def _chart_name(self, sheet, shape):
        try:
            name = shape.PersistName
        except Exception:  # noqa: BLE001
            return ""
        return name if name and sheet.getCharts().hasByName(name) else ""

    def cmd_object_image(self, args):
        """Bild eines Objekts (Diagramm, Bild) als PNG (Base64) in ``width`` × ``height`` Pixeln."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        page = sheet.getDrawPage()
        index = int(args["index"])
        if not 0 <= index < page.getCount():
            raise CalcError("Das Objekt gibt es nicht mehr.", "objekt")
        shape = page.getByIndex(index)
        export = self.smgr.createInstanceWithContext("com.sun.star.drawing.GraphicExportFilter", self.ctx)
        export.setSourceDocument(shape)
        handle, path = tempfile.mkstemp(prefix="novadesk-objekt-", suffix=".png")
        os.close(handle)
        try:
            data = uno.Any("[]com.sun.star.beans.PropertyValue", (_prop("PixelWidth", max(16, int(args.get("width", 400)))), _prop("PixelHeight", max(16, int(args.get("height", 300))))))
            uno.invoke(export, "filter", ((_prop("URL", _url(path)), _prop("MediaType", "image/png"), _prop("FilterData", data)),))
            with open(path, "rb") as handle_file:
                return {"png": base64.b64encode(handle_file.read()).decode("ascii")}
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def cmd_add_chart(self, args):
        """Diagramm aus dem Bereich (Tabelle um die Auswahl): ``type`` column, bar, line, pie, area – rechts neben den
        Daten, erste Zeile und Spalte als Beschriftung, wenn sie Text enthalten."""
        doc = self.doc(args)
        sheet, block = self.cell_range(doc, args)
        region = self._region(sheet, block)
        a = region.getRangeAddress()
        first_row = [sheet.getCellByPosition(c, a.StartRow).getType().value for c in range(a.StartColumn, a.EndColumn + 1)]
        first_col = [sheet.getCellByPosition(a.StartColumn, r).getType().value for r in range(a.StartRow, a.EndRow + 1)]
        col_headers = "TEXT" in first_row[1:] or (len(first_row) == 1 and first_row[0] == "TEXT")
        row_headers = first_col[1:].count("TEXT") > 0 and a.EndColumn > a.StartColumn
        charts = sheet.getCharts()
        number = 1
        while charts.hasByName("Diagramm %d" % number):
            number += 1
        name = "Diagramm %d" % number
        columns = sheet.getColumns()
        x = sum(int(columns.getByIndex(c).Width) for c in range(0, a.EndColumn + 1)) + 500
        rows = sheet.getRows()
        y = sum(int(rows.getByIndex(r).Height) for r in range(0, a.StartRow))
        rect = uno.createUnoStruct("com.sun.star.awt.Rectangle")
        rect.X, rect.Y, rect.Width, rect.Height = x, y, 12000, 7500
        charts.addNewByName(name, rect, (a,), bool(col_headers), bool(row_headers))
        self._chart_type(sheet, name, args.get("type", "column"))
        series = a.EndColumn - a.StartColumn + 1 - (1 if row_headers else 0)
        try:  # mehrere Reihen: Legende wie in Excel
            sheet.getCharts().getByName(name).getEmbeddedObject().HasLegend = series > 1
        except Exception:  # noqa: BLE001
            pass
        doc.model.setModified(True)
        return self.changed(doc, {"objects": self._objects(sheet), "name": name})

    def _chart_type(self, sheet, name, kind):
        service, vertical = CHART_TYPES.get(kind, CHART_TYPES["column"])
        chart = sheet.getCharts().getByName(name).getEmbeddedObject()
        diagram = chart.createInstance(service)
        chart.setDiagram(diagram)
        try:
            chart.getDiagram().Vertical = vertical
        except Exception:  # noqa: BLE001 - Kreis und Linie kennen das nicht
            pass

    def cmd_chart_type(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        if not sheet.getCharts().hasByName(args["name"]):
            raise CalcError("Das Diagramm gibt es nicht mehr.", "objekt")
        self._chart_type(sheet, args["name"], args.get("type", "column"))
        doc.model.setModified(True)
        return self.changed(doc, {"objects": self._objects(sheet)})

    def cmd_move_object(self, args):
        """Objekt verschieben bzw. Größe ändern (1/100 mm)."""
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        page = sheet.getDrawPage()
        shape = page.getByIndex(int(args["index"]))
        point = uno.createUnoStruct("com.sun.star.awt.Point")
        point.X, point.Y = max(0, int(args["x"])), max(0, int(args["y"]))
        size = uno.createUnoStruct("com.sun.star.awt.Size")
        size.Width, size.Height = max(500, int(args["w"])), max(500, int(args["h"]))
        shape.setPosition(point)
        shape.setSize(size)
        doc.model.setModified(True)
        return self.changed(doc, {"objects": self._objects(sheet)})

    def cmd_delete_object(self, args):
        doc = self.doc(args)
        sheet = doc.sheet(args.get("sheet", 0))
        page = sheet.getDrawPage()
        shape = page.getByIndex(int(args["index"]))
        name = self._chart_name(sheet, shape)
        if name:
            sheet.getCharts().removeByName(name)
        else:
            page.remove(shape)
        doc.model.setModified(True)
        return self.changed(doc, {"objects": self._objects(sheet)})

    # Rückgängig ---------------------------------------------------------------------------------------------------
    def cmd_undo(self, args):
        doc = self.doc(args)
        manager = doc.model.UndoManager
        if args.get("redo"):
            if manager.isRedoPossible():
                manager.redo()
        elif manager.isUndoPossible():
            manager.undo()
        return self.changed(doc)

    # Funktionen ---------------------------------------------------------------------------------------------------
    def cmd_functions(self, args):
        """Alle Funktionen mit deutschem Namen, Kategorie, Beschreibung und Argumenten (für den Funktions-Assistenten)."""
        if self.functions is None:
            descriptions = self.smgr.createInstanceWithContext("com.sun.star.sheet.FunctionDescriptions", self.ctx)
            items = []
            for index in range(descriptions.getCount()):
                entry = {item.Name: item.Value for item in descriptions.getByIndex(index)}
                name = entry.get("Name") or ""
                if not name:
                    continue
                arguments = [{"name": arg.Name, "description": arg.Description, "optional": bool(arg.IsOptional)} for arg in (entry.get("Arguments") or ())]
                items.append({"name": name, "category": CATEGORIES.get(int(entry.get("Category") or 0), "Weitere"),
                              "description": entry.get("Description") or "", "arguments": arguments})
            items.sort(key=lambda item: item["name"])
            self.functions = items
        return self.functions



def _commands(kernel):
    return {name[4:]: getattr(kernel, name) for name in dir(kernel) if name.startswith("cmd_")}


def _trace(text):
    """Ablauf des Kerns in »<Port-Datei>.log« (Novadesk zeigt ihn, wenn der Kern unerwartet endet)."""
    if not os.environ.get(PORT_VARIABLE):
        return
    try:
        with open(os.environ[PORT_VARIABLE] + ".log", "a", encoding="utf-8") as handle:
            handle.write("%.3f %s\n" % (time.time(), text))
    except Exception:  # noqa: BLE001
        pass


class _Lines:
    """Zeilen über den Socket – mit Wartezeit, damit LibreOffice zwischen den Befehlen seine Ereignisse abarbeitet."""

    def __init__(self, connection):
        self.connection = connection
        self.buffer = b""

    def read(self, pump):
        while b"\n" not in self.buffer:
            readable, _w, _x = select.select([self.connection], [], [], 0.05)
            if not readable:
                pump()
                continue
            chunk = self.connection.recv(65536)
            if not chunk:
                return None
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode("utf-8")

    def write(self, data):
        self.connection.sendall((json.dumps(data) + "\n").encode("utf-8"))


def _pump_events(ctx):
    """Ereignisse von LibreOffice abarbeiten (der Kern läuft im Hauptthread – sonst stünde LibreOffice still)."""
    try:
        toolkit = ctx.ServiceManager.createInstanceWithContext("com.sun.star.awt.Toolkit", ctx)
        process = toolkit.processEventsToIdle
    except Exception:  # noqa: BLE001
        return lambda: None

    def pump():
        try:
            process()
        except Exception:  # noqa: BLE001
            pass

    return pump


def _serve(ctx, state):
    """Der Kern: im Hauptthread von LibreOffice, bis Novadesk die Verbindung beendet. Das Skript kehrt so erst am Ende
    zurück – unter Windows beendete sich LibreOffice sonst nach dem Aufruf des Skripts (ohne geöffnetes Dokument)."""
    log = []
    try:
        _trace("Kern startet")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port_file = os.environ[PORT_VARIABLE]
        with open(port_file + ".tmp", "w") as handle:
            handle.write(str(server.getsockname()[1]))
        os.replace(port_file + ".tmp", port_file)
        server.settimeout(120)
        connection, _address_info = server.accept()
        server.close()
        connection.settimeout(None)
        lines = _Lines(connection)
        pump = _pump_events(ctx)
        hello = json.loads(lines.read(pump) or "{}")
        if hello.get("token") != os.environ.get(TOKEN_VARIABLE):
            _trace("falscher Schlüssel")
            connection.close()
            return
        lines.write({"ok": True, "hello": "novadesk-tabelle"})
        _trace("verbunden")
        kernel = Kernel(ctx)
        commands = _commands(kernel)
        while True:
            line = lines.read(pump)
            if line is None:
                _trace("Verbindung beendet")
                break
            if not line.strip():
                continue
            request = json.loads(line)
            ident = request.get("id")
            command = request.get("cmd")
            if command == "quit":
                lines.write({"id": ident, "ok": True, "result": True})
                _trace("beenden")
                break
            handler = commands.get(command)
            try:
                if handler is None:
                    raise CalcError("Unbekannter Befehl: %s" % command, "befehl")
                answer = {"id": ident, "ok": True, "result": handler(request.get("args") or {})}
            except CalcError as exc:
                answer = {"id": ident, "ok": False, "error": str(exc), "code": exc.code}
            except Exception as exc:  # noqa: BLE001 - jeder Fehler wird gemeldet, der Kern läuft weiter
                answer = {"id": ident, "ok": False, "error": "%s: %s" % (type(exc).__name__, str(exc)[:300]), "code": "intern",
                          "trace": traceback.format_exc()[-2000:]}
            lines.write(answer)
        for doc in list(kernel.docs.values()):
            try:
                doc.model.close(True)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        log.append(traceback.format_exc())
    finally:
        state["quit"] = True
        if log and os.environ.get(PORT_VARIABLE):
            try:
                with open(os.environ[PORT_VARIABLE] + ".fehler", "w", encoding="utf-8") as handle:
                    handle.write("\n".join(log))
            except Exception:  # noqa: BLE001
                pass
        try:
            desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
            desktop.terminate()
        except Exception:  # noqa: BLE001
            os._exit(0)


class _TerminateTrace(unohelper.Base, XTerminateListener):
    def queryTermination(self, event):  # noqa: N802 - UNO
        _trace("LibreOffice soll enden")

    def notifyTermination(self, event):  # noqa: N802 - UNO
        _trace("LibreOffice endet")

    def disposing(self, event):
        pass


def start(*_args):
    """Einstieg (»vnd.sun.star.script:novadesk_tabelle.py$start?language=Python&location=user«): bedient Novadesk und
    kehrt erst zurück, wenn die Verbindung endet."""
    ctx = uno.getComponentContext()
    state = {"quit": False}
    desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    desktop.addTerminateListener(_TerminateTrace())
    desktop.addTerminateListener(_Veto(state))
    _serve(ctx, state)


g_exportedScripts = (start,)
