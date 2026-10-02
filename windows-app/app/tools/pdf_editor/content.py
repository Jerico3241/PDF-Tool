"""Inhaltsströme lesen und gezielt ändern (pikepdf).

``PageContent`` liest alle Inhaltsströme einer Seite als eine Folge von Anweisungen und verfolgt
dabei Grafik- und Textzustand (CTM, Textmatrix, Schrift, Abstände). Für jeden Textoperator
(``Tj``, ``TJ``, ``'``, ``"``) entsteht ein ``ShowOp``. PDFium erzeugt für jeden dieser Operatoren
genau ein Textobjekt in derselben Reihenfolge – ``textedit`` prüft das Seite für Seite (Anzahl
und Text); nur dann sind native Änderungen erlaubt.

Änderungen ersetzen **nur** die Operanden der betroffenen Operatoren bzw. fügen Anweisungen ein.
Alles andere – markierter Inhalt, Inline-Bilder, Formen, unbekannte Operatoren – bleibt erhalten.
Geschrieben wird ein **neuer** Inhaltsstrom; die bisherigen Stream-Objekte bleiben unverändert
(für Rückgängig). Formular-XObjects werden nicht betreten: Text darin ist nur über eine
Überlagerung änderbar.

Leere Textoperatoren (``() Tj``) erzeugen in PDFium kein Textobjekt – die Zuordnung zählt deshalb
nur Operatoren mit Text.
"""

from __future__ import annotations

from dataclasses import dataclass

import pikepdf
from pikepdf import Operator

from .fonts import FontCodec

SHOW = {"Tj", "TJ", "'", '"'}
Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mul(m: Matrix, n: Matrix) -> Matrix:
    """m × n (PDF-Konvention: Zeilenvektor · m · n)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2, e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


@dataclass
class TextState:
    font: str = ""
    size: float = 0.0
    char_spacing: float = 0.0
    word_spacing: float = 0.0
    hscale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0
    render: int = 0


@dataclass
class ShowOp:
    index: int  # Position in ``PageContent.instructions``
    operator: str
    raw: bytes  # alle Strings des Operators aneinander (TJ ohne Abstände)
    state: TextState
    tm: Matrix  # Textmatrix beim Beginn der Ausgabe
    tlm: Matrix  # Zeilenmatrix (Anfang der Zeile)
    ctm: Matrix
    bt: int  # laufende Nummer des BT-Blocks
    advance: float = 0.0  # Breite im Textraum (gemäß Schriftbreiten)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class PageContent:
    """Anweisungen einer Seite mit Textoperatoren und Zustand."""

    def __init__(self, pdf: pikepdf.Pdf, page: pikepdf.Object, fonts: dict[str, pikepdf.Object]) -> None:
        self.pdf = pdf
        self.page = page
        self.instructions = list(pikepdf.parse_content_stream(page))
        self.fonts = fonts
        self.codecs: dict[str, FontCodec] = {}
        self.shows: list[ShowOp] = []
        self._interpret()

    def codec(self, font: str) -> FontCodec | None:
        if font not in self.codecs:
            obj = self.fonts.get(font)
            self.codecs[font] = FontCodec(obj) if obj is not None else None
        return self.codecs[font]

    # Lesen ---------------------------------------------------------------------------------------------
    def _interpret(self) -> None:
        stack: list[tuple[Matrix, TextState]] = []
        ctm = IDENTITY
        state = TextState()
        tm = tlm = IDENTITY
        bt = -1
        for index, ins in enumerate(self.instructions):
            if isinstance(ins, pikepdf.ContentStreamInlineImage):
                continue
            op = str(ins.operator)
            ops = list(ins.operands)
            if op == "q":
                stack.append((ctm, TextState(**state.__dict__)))
            elif op == "Q":
                if stack:
                    ctm, state = stack.pop()
            elif op == "cm" and len(ops) == 6:
                ctm = mul(tuple(_num(v) for v in ops), ctm)  # type: ignore[arg-type]
            elif op == "BT":
                tm = tlm = IDENTITY
                bt += 1
            elif op == "Tf" and len(ops) == 2:
                state.font, state.size = str(ops[0]), _num(ops[1])
            elif op == "Tc" and ops:
                state.char_spacing = _num(ops[0])
            elif op == "Tw" and ops:
                state.word_spacing = _num(ops[0])
            elif op == "Tz" and ops:
                state.hscale = _num(ops[0]) / 100.0
            elif op == "TL" and ops:
                state.leading = _num(ops[0])
            elif op == "Ts" and ops:
                state.rise = _num(ops[0])
            elif op == "Tr" and ops:
                state.render = int(_num(ops[0]))
            elif op in ("Td", "TD") and len(ops) == 2:
                tx, ty = _num(ops[0]), _num(ops[1])
                if op == "TD":
                    state.leading = -ty
                tlm = mul((1.0, 0.0, 0.0, 1.0, tx, ty), tlm)
                tm = tlm
            elif op == "Tm" and len(ops) == 6:
                tm = tlm = tuple(_num(v) for v in ops)  # type: ignore[assignment]
            elif op == "T*":
                tlm = mul((1.0, 0.0, 0.0, 1.0, 0.0, -state.leading), tlm)
                tm = tlm
            elif op in SHOW:
                if op == '"' and len(ops) == 3:
                    state.word_spacing, state.char_spacing = _num(ops[0]), _num(ops[1])
                if op in ("'", '"'):
                    tlm = mul((1.0, 0.0, 0.0, 1.0, 0.0, -state.leading), tlm)
                    tm = tlm
                raw, adjust = _strings(op, ops)
                show = ShowOp(index, op, raw, TextState(**state.__dict__), tm, tlm, ctm, bt)
                codec = self.codec(state.font)
                if codec is not None and codec.editable:
                    show.advance = codec.text_width(raw, state.size, state.char_spacing, state.word_spacing, state.hscale) - adjust / 1000.0 * state.size * state.hscale
                self.shows.append(show)
                tm = mul((1.0, 0.0, 0.0, 1.0, show.advance, 0.0), tm)
            elif op == "ET":
                pass

    def text_of(self, show: ShowOp) -> str:
        codec = self.codec(show.state.font)
        return codec.decode(show.raw) if codec is not None else ""

    # Ändern --------------------------------------------------------------------------------------------
    def set_text(self, show: ShowOp, data: bytes) -> None:
        """Text eines Operators ersetzen (TJ verliert dabei seine Abstände – die Zeile wird neu gesetzt)."""
        ins = self.instructions[show.index]
        string = pikepdf.String(data)
        if show.operator == "TJ":
            new = pikepdf.ContentStreamInstruction([pikepdf.Array([string])], Operator("TJ"))
        elif show.operator == '"':
            operands = list(ins.operands)
            new = pikepdf.ContentStreamInstruction([operands[0], operands[1], string], Operator('"'))
        else:
            new = pikepdf.ContentStreamInstruction([string], Operator(show.operator))
        self.instructions[show.index] = new
        show.raw = data

    def blank(self, show: ShowOp) -> None:
        """Text eines Operators entfernen (Zeilenwechsel von ``'``/``"`` bleiben wirksam)."""
        self.set_text(show, b"")

    def insert_after(self, show: ShowOp, instructions: list) -> None:
        """Anweisungen direkt hinter einem Operator einfügen (Indizes späterer Operatoren verschieben sich)."""
        position = show.index + 1
        self.instructions[position:position] = instructions
        for other in self.shows:
            if other.index >= position:
                other.index += len(instructions)

    def text_object(self, show: ShowOp) -> tuple[int, int] | None:
        """Anweisungsbereich ``BT … ET`` (einschließlich) um einen Textoperator."""
        start = show.index
        while start >= 0 and _operator(self.instructions[start]) != "BT":
            start -= 1
        end = show.index
        while end < len(self.instructions) and _operator(self.instructions[end]) != "ET":
            end += 1
        if start < 0 or end >= len(self.instructions):
            return None
        return start, end

    def remove_range(self, start: int, end: int) -> None:
        """Anweisungen ``start`` bis ``end`` (einschließlich) entfernen; enthaltene Textoperatoren
        gelten danach als leer (``index`` −1)."""
        del self.instructions[start : end + 1]
        removed = end - start + 1
        for other in self.shows:
            if start <= other.index <= end:
                other.index = -1
                other.raw = b""
            elif other.index > end:
                other.index -= removed

    def fonts_in(self, start: int, end: int) -> set[str]:
        return {str(ins.operands[0]) for ins in self.instructions[start : end + 1] if _operator(ins) == "Tf" and len(ins.operands) == 2}

    def serialize(self) -> bytes:
        return pikepdf.unparse_content_stream(self.instructions)

    def commit(self) -> None:
        """Als **neuen** Inhaltsstrom der Seite setzen (bisherige Stream-Objekte bleiben unverändert)."""
        self.page["/Contents"] = self.pdf.make_stream(self.serialize())


# Operatoren, die den Grafikzustand ändern – außerhalb von ``q … Q`` wirken sie auf alles Folgende
STATE_OPERATORS = {"cm", "w", "J", "j", "M", "d", "ri", "i", "gs", "CS", "cs", "SC", "SCN", "sc", "scn", "G", "g", "RG", "rg", "K", "k", "Tc", "Tw", "Tz", "TL", "Tf", "Tr", "Ts", "W", "W*"}


def _operator(ins) -> str:
    return "" if isinstance(ins, pikepdf.ContentStreamInlineImage) else str(ins.operator)


def isolated(page: pikepdf.Object) -> bool:
    """Endet der Inhalt im Ausgangszustand? (alle ``q`` geschlossen, keine Zustandsänderung außerhalb
    von ``q … Q``) – dann läuft angehängter Inhalt ohne zusätzliche Klammer im Ausgangszustand."""
    depth = 0
    for ins in pikepdf.parse_content_stream(page):
        op = _operator(ins)
        if op == "q":
            depth += 1
        elif op == "Q":
            if depth == 0:
                return False
            depth -= 1
        elif depth == 0 and op in STATE_OPERATORS:
            return False
    return depth == 0


def append_content(pdf: pikepdf.Pdf, page: pikepdf.Object, data: bytes) -> None:
    """Inhalt isoliert anhängen (``q data Q`` als eigener Stream). Ändert der bisherige Inhalt den
    Grafikzustand dauerhaft, wird er einmalig in ``q … Q`` gefasst (neue Streams davor und danach;
    die bisherigen Stream-Objekte bleiben unverändert). Weitere Anhänge brauchen keine neue Klammer –
    die Verschachtelung wächst nicht mit jeder Bearbeitung."""
    contents = page.get("/Contents")
    existing = list(contents) if isinstance(contents, pikepdf.Array) else ([contents] if contents is not None else [])
    appendix = pdf.make_stream(b"q\n" + data + b"\nQ\n")
    if not existing or isolated(page):
        page["/Contents"] = pikepdf.Array([*existing, appendix])
        return
    prefix = pdf.make_stream(b"q\n")
    suffix = pdf.make_stream(b"\n" + b"Q\n" * (_depth_at_end(page) + 1))
    page["/Contents"] = pikepdf.Array([prefix, *existing, suffix, appendix])


def _depth_at_end(page: pikepdf.Object) -> int:
    depth = 0
    for ins in pikepdf.parse_content_stream(page):
        op = _operator(ins)
        if op == "q":
            depth += 1
        elif op == "Q" and depth:
            depth -= 1
    return depth


def prune_fonts(pdf: pikepdf.Pdf, page: pikepdf.Object, prefix: str = "/PTF") -> None:
    """Eigene Schriften (``/PTF1`` …), auf die kein ``Tf`` der Seite mehr verweist, aus den Ressourcen
    der Seite entfernen – so bleiben ersetzte Schriften nicht in der Datei. Die Ressourcen werden
    dafür für die Seite kopiert (nie gemeinsam genutzte Dictionaries in place ändern)."""
    from . import commands
    from .document import inherited

    resources = inherited(page, "/Resources")
    fonts = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
    if not isinstance(fonts, pikepdf.Dictionary):
        return
    ours = [str(key) for key in fonts.keys() if str(key).startswith(prefix)]
    if not ours:
        return
    used = {str(ins.operands[0]) for ins in pikepdf.parse_content_stream(page) if _operator(ins) == "Tf" and len(ins.operands) == 2}
    unused = [key for key in ours if key not in used]
    if unused:
        fonts = commands.own_resources(page, pdf, "/Font").Font
        for key in unused:
            del fonts[key]


def _strings(op: str, operands) -> tuple[bytes, float]:
    """Bytes aller Strings eines Textoperators und Summe der TJ-Abstände (in 1/1000 Text-Einheiten)."""
    if op == "TJ":
        raw = bytearray()
        adjust = 0.0
        array = operands[0] if operands else []
        for item in array:
            if isinstance(item, pikepdf.String):
                raw += bytes(item)
            else:
                adjust += _num(item)
        return bytes(raw), adjust
    string = operands[-1] if operands else b""
    return (bytes(string) if isinstance(string, pikepdf.String) else b""), 0.0


def page_fonts(page: pikepdf.Object) -> dict[str, pikepdf.Object]:
    """Schriften der Seite (samt vererbter Ressourcen): ``/F1`` → Schrift-Dictionary."""
    from .document import inherited

    resources = inherited(page, "/Resources")
    fonts = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
    if not isinstance(fonts, pikepdf.Dictionary):
        return {}
    return {str(name): font for name, font in fonts.items() if isinstance(font, pikepdf.Dictionary)}


def fmt(value: float) -> str:
    """Zahl für den Inhaltsstrom (kurz, ohne Exponentenschreibweise)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"
