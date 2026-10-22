"""Daten eines Tabellenblatts für die Anzeige – ohne Qt: Spalten und Zeilen (Größen, Lagen), verbundene Zellen und die
zuletzt geladenen Zellen.

Größen kommen vom Rechenkern in 1/100 mm und werden hier zu Pixeln bei 100 % (96 dpi). Zellen werden in Blöcken
geladen (``BLOCK_ROWS`` × ``BLOCK_COLS``); ein Block gilt nach einer Änderung als veraltet, bleibt aber sichtbar, bis
der neue Stand da ist (kein Flackern).
"""

from __future__ import annotations

import bisect
from itertools import accumulate

MM100_TO_PX = 96 / 2540
BLOCK_ROWS = 64
BLOCK_COLS = 16
DEFAULT_COL_PX = 2258 * MM100_TO_PX  # 2,258 cm wie in LibreOffice
DEFAULT_ROW_PX = 452 * MM100_TO_PX


def px(mm100: float) -> float:
    return float(mm100) * MM100_TO_PX


def mm100(pixels: float) -> int:
    return int(round(float(pixels) / MM100_TO_PX))


class Axis:
    """Spalten oder Zeilen: Größe je Index (Pixel bei 100 %), ausgeblendete haben die Größe 0."""

    def __init__(self, sizes: list[float] | None = None, default: float = DEFAULT_COL_PX, hidden: set[int] | None = None) -> None:
        self.sizes: list[float] = list(sizes or [])
        self.default = float(default)
        self.hidden: set[int] = set(hidden or ())
        self._starts: list[float] | None = None

    def set_sizes(self, sizes: list[float], start: int = 0) -> None:
        if start > len(self.sizes):
            self.sizes.extend([self.default] * (start - len(self.sizes)))
        self.sizes[start:start + len(sizes)] = sizes
        self._starts = None

    def set_hidden(self, hidden: set[int]) -> None:
        self.hidden = set(hidden)
        self._starts = None

    def size(self, index: int) -> float:
        if index in self.hidden:
            return 0.0
        return self.sizes[index] if 0 <= index < len(self.sizes) else self.default

    def _prefix(self) -> list[float]:
        if self._starts is None:
            self._starts = [0.0, *accumulate(self.size(i) for i in range(len(self.sizes)))]
        return self._starts

    def start(self, index: int) -> float:
        """Lage des Anfangs von ``index`` (Summe aller Größen davor)."""
        starts = self._prefix()
        if index <= len(self.sizes):
            return starts[max(0, index)]
        extra = index - len(self.sizes)
        hidden = sum(1 for i in self.hidden if len(self.sizes) <= i < index)
        return starts[-1] + (extra - hidden) * self.default

    def end(self, index: int) -> float:
        return self.start(index) + self.size(index)

    def index_at(self, position: float) -> int:
        """Index an der Lage ``position`` (Pixel bei 100 %); ausgeblendete werden übersprungen."""
        if position < 0:
            return 0
        starts = self._prefix()
        if position < starts[-1]:
            index = bisect.bisect_right(starts, position) - 1
            while index < len(self.sizes) - 1 and self.size(index) == 0:
                index += 1
            return max(0, index)
        index = len(self.sizes) + int((position - starts[-1]) // self.default) if self.default > 0 else len(self.sizes)
        while index in self.hidden:
            index += 1
        return index

    def visible(self, index: int, step: int, limit: int) -> int:
        """Nächster sichtbarer Index ab ``index`` in Richtung ``step`` (±1), innerhalb 0 … ``limit``-1."""
        while 0 <= index < limit and index in self.hidden:
            index += step
        return max(0, min(limit - 1, index))


class Layout:
    """Aufbau eines Blatts: Spalten, Zeilen, verbundene Zellen, Fixierung, Filter, Objekte, Druckbereich."""

    def __init__(self) -> None:
        self.cols = Axis(default=DEFAULT_COL_PX)
        self.rows = Axis(default=DEFAULT_ROW_PX)
        self.used_rows = 0
        self.used_cols = 0
        self.max_rows = 1048576
        self.max_cols = 16384
        self.freeze = (0, 0)
        self.filter: dict | None = None
        self.objects: list[dict] = []
        self.print_area: list = []
        self.grid = True
        self.loaded = False
        self.set_merges([])

    def apply(self, data: dict) -> None:
        self.used_rows = int(data.get("rows", 0))
        self.used_cols = int(data.get("cols", 0))
        self.max_rows = int(data.get("maxRows", self.max_rows))
        self.max_cols = int(data.get("maxCols", self.max_cols))
        self.cols = Axis([px(w) for w in data.get("widths", [])], px(data.get("defaultWidth", 2258)), set(data.get("hiddenCols", [])))
        default_row = px(data.get("defaultHeight", 452))
        if abs(default_row - self.rows.default) > 0.01:
            self.rows = Axis(default=default_row)
        freeze = data.get("freeze") or [0, 0]
        self.freeze = (int(freeze[0]), int(freeze[1]))
        self.filter = data.get("filter")
        self.objects = list(data.get("objects") or [])
        self.print_area = list(data.get("printArea") or [])
        self.grid = bool(data.get("grid", True))
        self.set_merges(data.get("merges") or [])
        self.loaded = True

    def apply_rows(self, data: dict) -> None:
        start = int(data.get("start", 0))
        heights = [px(h) for h in data.get("heights", [])]
        self.rows.set_sizes(heights, start)
        end = start + len(heights)
        hidden = {row for row in self.rows.hidden if not start <= row < end} | set(data.get("hidden", []))
        self.rows.set_hidden(hidden)

    def set_merges(self, merges: list) -> None:
        self.merges = [tuple(int(v) for v in m) for m in merges]
        self.merge_at: dict[tuple[int, int], tuple[int, int, int, int]] = {}
        self.covered: dict[tuple[int, int], tuple[int, int]] = {}
        for r0, c0, r1, c1 in self.merges:
            self.merge_at[(r0, c0)] = (r0, c0, r1, c1)
            for r in range(r0, r1 + 1):
                for c in range(c0, c1 + 1):
                    if (r, c) != (r0, c0):
                        self.covered[(r, c)] = (r0, c0)

    def merge_of(self, row: int, col: int) -> tuple[int, int, int, int] | None:
        origin = self.covered.get((row, col), (row, col))
        return self.merge_at.get(origin)

    def expand(self, r0: int, c0: int, r1: int, c1: int) -> tuple[int, int, int, int]:
        """Auswahl so erweitern, dass verbundene Zellen ganz darin liegen (wie Excel)."""
        changed = True
        while changed:
            changed = False
            for m0, n0, m1, n1 in self.merges:
                if m1 < r0 or m0 > r1 or n1 < c0 or n0 > c1:
                    continue
                if m0 < r0 or n0 < c0 or m1 > r1 or n1 > c1:
                    r0, c0, r1, c1 = min(r0, m0), min(c0, n0), max(r1, m1), max(c1, n1)
                    changed = True
        return r0, c0, r1, c1


class Cells:
    """Geladene Zellen eines Blatts: (Zeile, Spalte) → (Text, Art, Stil). Art: »n« Zahl, »t« Text, »e« Fehler,
    »" "« leer mit Format."""

    def __init__(self) -> None:
        self.values: dict[tuple[int, int], tuple[str, str, int]] = {}
        self.blocks: set[tuple[int, int]] = set()  # geladen und aktuell
        self.stale: set[tuple[int, int]] = set()  # geladen, aber seit einer Änderung veraltet
        self.default_style = 0

    @staticmethod
    def block_of(row: int, col: int) -> tuple[int, int]:
        return row // BLOCK_ROWS, col // BLOCK_COLS

    def missing(self, r0: int, c0: int, r1: int, c1: int) -> list[tuple[int, int]]:
        """Blöcke im Bereich, die noch fehlen oder veraltet sind (oben links zuerst)."""
        b0, k0 = self.block_of(r0, c0)
        b1, k1 = self.block_of(r1, c1)
        return [(b, k) for b in range(b0, b1 + 1) for k in range(k0, k1 + 1) if (b, k) not in self.blocks]

    def invalidate(self) -> None:
        self.stale |= self.blocks
        self.blocks = set()

    def clear(self) -> None:
        self.values = {}
        self.blocks = set()
        self.stale = set()

    def apply(self, data: dict) -> None:
        r0, c0, r1, c1 = data["range"]
        values = self.values
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                values.pop((row, col), None)
        for dr, line in enumerate(data["cells"]):
            for dc, cell in enumerate(line):
                if cell is not None:
                    values[(r0 + dr, c0 + dc)] = (cell[0], cell[1], int(cell[2]))
        self.default_style = int(data.get("default", self.default_style) or 0)
        for b in range(r0 // BLOCK_ROWS, r1 // BLOCK_ROWS + 1):
            for k in range(c0 // BLOCK_COLS, c1 // BLOCK_COLS + 1):
                block = (b, k)
                self.blocks.add(block)
                self.stale.discard(block)

    def get(self, row: int, col: int) -> tuple[str, str, int] | None:
        return self.values.get((row, col))

    def put_text(self, row: int, col: int, text: str) -> None:
        """Eingabe sofort zeigen, bis der Kern das Ergebnis liefert (Formeln: leer statt »=…«)."""
        old = self.values.get((row, col))
        style = old[2] if old else self.default_style
        shown = "" if text.startswith("=") else text
        kind = "n" if _looks_numeric(shown) else "t"
        if shown or old:
            self.values[(row, col)] = (shown, kind if shown else " ", style)


def _looks_numeric(text: str) -> bool:
    cleaned = text.strip().replace(".", "").replace(",", "").replace("€", "").replace("%", "").replace(" ", "").lstrip("-+")
    return cleaned.isdigit()


def block_range(block: tuple[int, int]) -> list[int]:
    b, k = block
    return [b * BLOCK_ROWS, k * BLOCK_COLS, b * BLOCK_ROWS + BLOCK_ROWS - 1, k * BLOCK_COLS + BLOCK_COLS - 1]
