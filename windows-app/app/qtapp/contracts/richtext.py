"""Kopf- und Fußzeile bearbeiten: Brücke zwischen dem QML-Textfeld und ``richtext.RichText``.

Das Datenmodell (Formatierung je Zeichen, Ausrichtung je Absatz), die Speicherung und die
Umwandlung für ReportLab bleiben unverändert in ``richtext``. Diese Klasse überträgt nur
zwischen dem ``QTextDocument`` des Textfelds und ``RichText``:

* Laden (``set_rich``) und bewusstes Ersetzen (``replace_rich`` – rückgängig machbar)
* Lesen (``rich``) – exakt mit allen Zeilenumbrüchen, zwischengespeichert bis zur nächsten Änderung
* Formatleiste: Schrift, Größe, Fett, Kursiv, Unterstrichen, Durchgestrichen, Farbe, Ausrichtung
* Ohne Markierung gilt eine gewählte Formatierung für den als Nächstes eingegebenen Text
* Rückgängig/Wiederholen übernimmt das Dokument selbst (Text *und* Formatierung)

Das Textfeld zeigt den Text wie in der PDF (weißes »Papier«, leicht vergrößert, damit 8 pt
gut lesbar sind). Eingefügt wird nur reiner Text – fremde Formatierungen, Tabellen oder
Bilder aus der Zwischenablage gelangen nicht in Kopf- oder Fußzeile.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtQuick import QQuickTextDocument

from richtext import ALIGNMENTS, FONT_SIZES, TEXT_COLOR, CharStyle, RichText, size_text, valid_color, valid_size

from ..base import Observable, prop

ZOOM = 1.25  # Darstellungsgröße im Editor: 8 pt ≈ Größe der Oberflächenschrift
FONT_PROPERTY = QTextFormat.Property.UserProperty + 1  # exakter Schriftname aus dem Datenmodell
QUICK_COLORS = (
    ("Dunkel", "#333333"),
    ("Grau", "#6B6B6B"),
    ("Rot", "#B51F1F"),
    ("Blau", "#1F5AA6"),
    ("Grün", "#2E7D32"),
)
MORE_COLORS = (
    ("Schwarz", "#000000"),
    ("Dunkelgrau", "#4D4D4D"),
    ("Hellgrau", "#9E9E9E"),
    ("Dunkelrot", "#7F1D1D"),
    ("Orange", "#C2410C"),
    ("Gold", "#A16207"),
    ("Dunkelgrün", "#166534"),
    ("Petrol", "#0F766E"),
    ("Dunkelblau", "#1E3A8A"),
    ("Violett", "#6D28D9"),
    ("Magenta", "#A21CAF"),
    ("Braun", "#78350F"),
)
# PDF-Schriften am Bildschirm: die passende Windows-Schrift (wie in 2.6)
SCREEN_FONTS = {
    "Helvetica": ["Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"],
    "Times": ["Times New Roman", "Times", "Liberation Serif", "DejaVu Serif"],
    "Courier": ["Courier New", "Courier", "Liberation Mono", "DejaVu Sans Mono"],
}
ALIGN_FLAGS = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter, "right": Qt.AlignmentFlag.AlignRight}
LINE_SEPARATOR = " "
OBJECT_REPLACEMENT = "￼"


def font_families() -> list[str]:
    from pdffonts import available_families

    return available_families()


def char_format(style: CharStyle) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setProperty(FONT_PROPERTY, style.font)
    fmt.setFontFamilies(SCREEN_FONTS.get(style.font, [style.font]))
    fmt.setFontPointSize(float(style.size) * ZOOM)
    fmt.setForeground(QColor(valid_color(style.color)))
    fmt.setFontWeight(QFont.Weight.Bold if style.bold else QFont.Weight.Normal)
    fmt.setFontItalic(bool(style.italic))
    fmt.setFontUnderline(bool(style.underline))
    fmt.setFontStrikeOut(bool(style.strike))
    return fmt


def style_of(fmt: QTextCharFormat, default: CharStyle) -> CharStyle:
    font = fmt.property(FONT_PROPERTY)
    if not isinstance(font, str) or not font:
        families = fmt.fontFamilies() or []
        family = str(families[0]) if families else ""
        font = next((name for name, screen in SCREEN_FONTS.items() if family in screen), family or default.font)
    size = default.size
    if fmt.hasProperty(QTextFormat.Property.FontPointSize) and fmt.fontPointSize() > 0:
        size = valid_size(round(fmt.fontPointSize() / ZOOM, 1), default.size)
    color = default.color
    if fmt.hasProperty(QTextFormat.Property.ForegroundBrush):
        color = valid_color(fmt.foreground().color().name(), default.color)
    bold = fmt.fontWeight() >= 600 if fmt.hasProperty(QTextFormat.Property.FontWeight) else default.bold
    italic = fmt.fontItalic() if fmt.hasProperty(QTextFormat.Property.FontItalic) else default.italic
    underline = fmt.fontUnderline() if (fmt.hasProperty(QTextFormat.Property.TextUnderlineStyle) or fmt.hasProperty(QTextFormat.Property.FontUnderline)) else default.underline
    strike = fmt.fontStrikeOut() if fmt.hasProperty(QTextFormat.Property.FontStrikeOut) else default.strike
    return CharStyle(font=font, size=size, color=color, bold=bool(bold), italic=bool(italic), underline=bool(underline), strike=bool(strike))


def _align_of(block_format: QTextBlockFormat, default: str) -> str:
    flags = block_format.alignment()
    if flags & Qt.AlignmentFlag.AlignHCenter:
        return "center"
    if flags & Qt.AlignmentFlag.AlignRight:
        return "right"
    if flags & Qt.AlignmentFlag.AlignLeft:
        return "left"
    return default


def block_format(align: str) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    fmt.setAlignment(ALIGN_FLAGS.get(align, Qt.AlignmentFlag.AlignLeft))
    return fmt


def document_rich(doc: QTextDocument, default: CharStyle, align: str) -> RichText:
    """``QTextDocument`` → ``RichText`` (Absätze = Blöcke; weiche Umbrüche werden zu Absätzen)."""
    text: list[str] = []
    styles: list[CharStyle] = []
    aligns: list[str] = []
    block = doc.begin()
    first = True
    while block.isValid():
        paragraph_align = _align_of(block.blockFormat(), align)
        if not first:
            text.append("\n")
            styles.append(style_of(block.charFormat(), default))
        aligns.append(paragraph_align)
        first = False
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                style = style_of(fragment.charFormat(), default)
                for char in fragment.text():
                    if char == OBJECT_REPLACEMENT:
                        continue
                    if char == LINE_SEPARATOR:
                        text.append("\n")
                        styles.append(style)
                        aligns.append(paragraph_align)
                        continue
                    text.append(char)
                    styles.append(style)
            iterator += 1
        block = block.next()
    joined = "".join(text)
    rich = RichText(joined, styles, aligns, default, align)
    return rich


def load_document(doc: QTextDocument, rich: RichText, undoable: bool) -> None:
    """``RichText`` in das Dokument schreiben – bei ``undoable`` als ein Rückgängig-Schritt."""
    cursor = QTextCursor(doc)
    if undoable:
        cursor.beginEditBlock()
    else:
        doc.setUndoRedoEnabled(False)
    try:
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        for index, (start, end, align) in enumerate(rich.paragraphs()):
            if index == 0:
                cursor.setBlockFormat(block_format(align))
                cursor.setBlockCharFormat(char_format(rich.paragraph_style(start, end)))
            else:
                cursor.insertBlock(block_format(align), char_format(rich.styles[start - 1]))
            for run_start, run_end, style in rich.runs(start, end):
                cursor.insertText(rich.text[run_start:run_end], char_format(style))
    finally:
        if undoable:
            cursor.endEditBlock()
        else:
            doc.setUndoRedoEnabled(True)  # leerer Rückgängig-Verlauf nach dem Laden


class RichTextDocument(Observable):
    """Ein Textfeld mit Formatleiste (in QML: ``Contracts.header`` bzw. ``Contracts.footer``)."""

    boldChanged, bold = prop(bool, "bold", False)
    italicChanged, italic = prop(bool, "italic", False)
    underlineChanged, underline = prop(bool, "underline", False)
    strikeChanged, strike = prop(bool, "strike", False)
    fontFamilyChanged, fontFamily = prop(str, "fontFamily", "")
    fontSizeChanged, fontSize = prop(str, "fontSize", "")
    colorChanged, color = prop(str, "color", "")
    alignmentChanged, alignment = prop(str, "alignment", "")
    familiesChanged, families = prop(list, "families", [])
    sizesChanged, sizes = prop(list, "sizes", [])
    quickColorsChanged, quickColors = prop(list, "quickColors", [])
    moreColorsChanged, moreColors = prop(list, "moreColors", [])
    attachedChanged, attached = prop(bool, "attached", False)
    revisionChanged, revision = prop(int, "revision", 0)

    def __init__(self, default: CharStyle, align: str, initial: RichText, on_change: Callable[[], None] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.default = default
        self.default_align = align if align in ALIGNMENTS else "left"
        self._start = initial
        self._doc: QTextDocument | None = None
        self._quick: QObject | None = None
        self._on_change = on_change
        self._cache: RichText | None = None
        self._loading = False
        self._cursor = (0, 0, 0)  # Position, Markierungsanfang, Markierungsende
        self.pending: CharStyle | None = None  # Format für den als Nächstes eingegebenen Text
        self.set_quietly("families", font_families())
        self.set_quietly("sizes", [size_text(size) for size in FONT_SIZES])
        self.set_quietly("quickColors", [{"name": name, "value": value} for name, value in QUICK_COLORS])
        self.set_quietly("moreColors", [{"name": name, "value": value} for name, value in MORE_COLORS])
        self._refresh_state()

    # Verbindung mit QML ---------------------------------------------------------------
    @Slot(QObject)
    def attach(self, document: QObject) -> None:
        """Das Dokument des QML-Textfelds übernehmen und mit dem aktuellen Stand füllen."""
        doc = document.textDocument() if isinstance(document, QQuickTextDocument) else document
        if not isinstance(doc, QTextDocument) or doc is self._doc:
            return
        start = self.rich()
        # PySide bindet die Lebensdauer des zurückgegebenen Dokuments an das QQuickTextDocument-
        # Objekt: Beide Verweise halten, solange das Textfeld verbunden ist.
        self._quick = document
        self._doc = doc
        doc.setUndoRedoEnabled(True)
        doc.setDocumentMargin(0)
        default_font = QFont()
        default_font.setFamilies(SCREEN_FONTS.get(self.default.font, [self.default.font]))
        default_font.setPointSizeF(float(self.default.size) * ZOOM)
        doc.setDefaultFont(default_font)
        doc.contentsChange.connect(self._contents_change)
        self._set_document(start, undoable=False)
        self.attached = True

    @Slot()
    def detach(self) -> None:
        """Das Textfeld wird entfernt: den aktuellen Stand behalten (das Dokument gehört QML)."""
        if self._doc is not None:
            try:
                self._start = self.rich()
                self._doc.contentsChange.disconnect(self._contents_change)
            except (RuntimeError, TypeError):
                if self._cache is not None:
                    self._start = self._cache
        self._doc = None
        self._quick = None
        self._cache = None
        self.attached = False

    # Lesen und Schreiben (Python) ----------------------------------------------------------
    def rich(self) -> RichText:
        """Aktueller Inhalt samt Formatierung – exakt mit allen Zeilenumbrüchen."""
        if self._doc is None:
            return self._start
        if self._cache is None:
            self._cache = document_rich(self._doc, self.default, self.default_align)
        return self._cache

    def text(self) -> str:
        return self.rich().text

    def set_rich(self, rich: RichText) -> None:
        """Inhalt setzen (Laden, Vorlage, Kundenakte) – der Rückgängig-Verlauf beginnt neu."""
        self._start = rich
        if self._doc is not None:
            self._set_document(rich, undoable=False)
        else:
            self._cache = None
            self.revision = self.revision + 1
        self._refresh_state()

    def replace_rich(self, rich: RichText) -> None:
        """Inhalt ersetzen (z. B. »Standard wiederherstellen«) – mit Strg+Z rückgängig machbar."""
        self._start = rich
        if self._doc is not None:
            self._set_document(rich, undoable=True)
        else:
            self._cache = None
        self._refresh_state()

    def _set_document(self, rich: RichText, undoable: bool) -> None:
        assert self._doc is not None
        self._loading = True
        try:
            load_document(self._doc, rich, undoable)
        finally:
            self._loading = False
        self._cache = None
        self.pending = None
        self.revision = self.revision + 1

    def _contents_change(self, position: int, removed: int, added: int) -> None:
        if self._loading:
            return
        self._cache = None
        if added and self.pending is not None and self._doc is not None:
            # Gewählte Formatierung für neu eingegebenen Text (ohne Markierung gewählt)
            style, self.pending = self.pending, None
            self._loading = True
            try:
                cursor = QTextCursor(self._doc)
                cursor.joinPreviousEditBlock()
                cursor.setPosition(position)
                cursor.setPosition(position + added, QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(char_format(style))
                cursor.endEditBlock()
            finally:
                self._loading = False
            self._cache = None
        self.revision = self.revision + 1
        if self._on_change is not None:
            self._on_change()

    # Markierung und Formatleiste ---------------------------------------------------------------
    @Slot(int, int, int)
    def setCursor(self, position: int, selection_start: int, selection_end: int) -> None:  # noqa: N802
        state = (position, min(selection_start, selection_end), max(selection_start, selection_end))
        if state == self._cursor:
            return
        moved = state[0] != self._cursor[0] or state[1] != state[2]
        self._cursor = state
        if moved and self.pending is not None:
            self.pending = None  # Cursor woanders hin: die gewählte Formatierung verfällt
        self._refresh_state()

    def selection(self) -> tuple[int, int] | None:
        _position, start, end = self._cursor
        return (start, end) if end > start else None

    def insert_style(self, offset: int) -> CharStyle:
        """Format für an ``offset`` eingegebenen Text: das Zeichen davor, am Absatzanfang das danach."""
        if self.pending is not None:
            return self.pending
        rich = self.rich()
        text = rich.text
        if 0 < offset <= len(text) and text[offset - 1] != "\n":
            return rich.styles[offset - 1]
        if offset < len(text) and text[offset] != "\n":
            return rich.styles[offset]
        if 0 <= offset < len(text):
            return rich.styles[offset]
        if offset > 0 and rich.styles:
            return rich.styles[min(offset, len(rich.styles)) - 1]
        return self.default

    def current(self) -> tuple[set[CharStyle], set[str]]:
        """Formate und Ausrichtungen der Markierung (ohne Markierung: am Cursor)."""
        rich = self.rich()
        position, start, end = self._cursor
        position = max(0, min(position, len(rich.text)))
        if end > start:
            start, end = max(0, start), min(len(rich.text), end)
            styles = {rich.styles[index] for index in range(start, end) if rich.text[index] != "\n"} or {rich.style_at(start)}
        else:
            start = end = position
            styles = {self.insert_style(position)}
        aligns = {align for p_start, p_end, align in rich.paragraphs() if p_start <= end and p_end >= start}
        return styles, aligns or {self.default_align}

    def _refresh_state(self) -> None:
        styles, aligns = self.current()

        def common(attribute: str):
            values = {getattr(style, attribute) for style in styles}
            return next(iter(values)) if len(values) == 1 else None

        self.bold = common("bold") is True
        self.italic = common("italic") is True
        self.underline = common("underline") is True
        self.strike = common("strike") is True
        self.fontFamily = common("font") or ""
        size = common("size")
        self.fontSize = size_text(size) if size is not None else ""
        self.color = common("color") or ""
        self.alignment = next(iter(aligns)) if len(aligns) == 1 else ""

    def apply(self, change: Callable[[CharStyle], CharStyle], merge: QTextCharFormat) -> None:
        """Formatierung der Markierung ändern – ohne Markierung für den nächsten eingegebenen Text."""
        selection = self.selection()
        if selection is None or self._doc is None:
            position = self._cursor[0]
            self.pending = change(self.insert_style(position))
            self._refresh_state()
            return
        start, end = selection
        cursor = QTextCursor(self._doc)
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(merge)
        cursor.endEditBlock()
        self._cache = None
        self._refresh_state()

    @Slot(str)
    def toggle(self, attribute: str) -> None:
        if attribute not in ("bold", "italic", "underline", "strike"):
            return
        styles, _aligns = self.current()
        turn_on = not all(getattr(style, attribute) for style in styles)
        merge = QTextCharFormat()
        if attribute == "bold":
            merge.setFontWeight(QFont.Weight.Bold if turn_on else QFont.Weight.Normal)
        elif attribute == "italic":
            merge.setFontItalic(turn_on)
        elif attribute == "underline":
            merge.setFontUnderline(turn_on)
        else:
            merge.setFontStrikeOut(turn_on)
        self.apply(lambda style: style.with_(**{attribute: turn_on}), merge)

    @Slot(str)
    def setFontFamily(self, family: str) -> None:  # noqa: N802
        if not family:
            return
        merge = QTextCharFormat()
        merge.setProperty(FONT_PROPERTY, family)
        merge.setFontFamilies(SCREEN_FONTS.get(family, [family]))
        self.apply(lambda style: style.with_(font=family), merge)

    @Slot(str)
    def setFontSize(self, value: str) -> None:  # noqa: N802
        size = valid_size(str(value).replace(",", "."), 0)
        if not size:
            return
        merge = QTextCharFormat()
        merge.setFontPointSize(float(size) * ZOOM)
        self.apply(lambda style: style.with_(size=size), merge)

    @Slot(str)
    def setColor(self, value: str) -> None:  # noqa: N802
        color = valid_color(value, "")
        if not color:
            return
        merge = QTextCharFormat()
        merge.setForeground(QColor(color))
        self.apply(lambda style: style.with_(color=color), merge)

    @Slot(str)
    def setAlignment(self, align: str) -> None:  # noqa: N802
        if align not in ALIGNMENTS or self._doc is None:
            return
        _position, start, end = self._cursor
        position = self._cursor[0]
        if end <= start:
            start = end = position
        cursor = QTextCursor(self._doc)
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextBlockFormat()
        fmt.setAlignment(ALIGN_FLAGS[align])
        cursor.mergeBlockFormat(fmt)
        cursor.endEditBlock()
        self._cache = None
        self._refresh_state()

    @Slot(int, int)
    def pastePlain(self, start: int, end: int) -> None:  # noqa: N802
        """Einfügen aus der Zwischenablage – nur reiner Text, im Format an der Einfügestelle."""
        if self._doc is None:
            return
        text = QGuiApplication.clipboard().text() if QGuiApplication.clipboard() is not None else ""
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace(LINE_SEPARATOR, "\n").replace(OBJECT_REPLACEMENT, "")
        if not text:
            return
        start, end = min(start, end), max(start, end)
        style = self.insert_style(start)
        cursor = QTextCursor(self._doc)
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if index:
                cursor.insertBlock(cursor.blockFormat(), char_format(style))
            if line:
                cursor.insertText(line, char_format(style))
        cursor.endEditBlock()

    # Test- und Diagnosehilfen -------------------------------------------------------------------------
    def default_color(self) -> str:
        return TEXT_COLOR
