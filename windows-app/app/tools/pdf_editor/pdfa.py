"""Als PDF/A speichern (seit 4.0): eine Kopie für die Langzeitarchivierung (PDF/A-2b, ISO 19005-2).

PDF/A verlangt, dass eine Datei in Jahrzehnten noch genauso aussieht wie heute – ohne Zugriff auf
Schriften, Programme oder das Internet. Gearbeitet wird an einer Kopie des aktuellen Stands; das
geöffnete Dokument bleibt unverändert. Was die Kopie dafür bekommt bzw. verliert:

* **Schriften:** Alle Schriften müssen eingebettet sein. Nicht eingebettete einfache Schriften
  (z. B. Helvetica, Arial, Times) bekommen die passende Windows-Schrift als Teilmenge eingebettet
  (Arial für Helvetica, Times New Roman für Times, Courier New für Courier – gleiche Laufweite);
  die Breiten werden aus der eingebetteten Schrift übernommen.
* **Farben:** eine Ausgabebedingung sRGB (ICC-Profil aus Pillow/LittleCMS).
* **Metadaten:** XMP mit Kennung »PDF/A-2B«, abgeglichen mit dem Dokumentinfo-Verzeichnis.
* **Entfernt:** JavaScript und automatische Aktionen, Start- und Importaktionen, XFA, eingebettete
  Dateien (PDF/A-2 erlaubt nur geprüfte PDF/A-Anhänge), Ton- und Filmkommentare, Kennwortschutz
  (PDF/A erlaubt keine Verschlüsselung), Transferfunktionen, PostScript-Teile, ``/Interpolate``.
* **Kommentare** werden druckbar markiert; Kommentare ohne eigenes Erscheinungsbild entfallen.
* LZW-Kompression wird beim Schreiben durch Flate ersetzt.

Was sich nicht sicher umwandeln lässt (CMYK-Farben ohne passende Ausgabebedingung, nicht eingebettete
CID- oder Symbolschriften, Schriften ohne Ersatz auf diesem PC), wird **nicht** still übergangen:
Dann entsteht keine Datei, und die Meldung nennt die Gründe. Die Prüfung hier ersetzt keine
zertifizierte Validierung (z. B. veraPDF); sie deckt die häufigen Fälle ab.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name

from . import fonts
from .document import EditorDocument
from .errors import EditorError

PART = 2
CONFORMANCE = "B"
FORBIDDEN_ACTIONS = {"/Launch", "/Sound", "/Movie", "/ResetForm", "/ImportData", "/JavaScript", "/Hide", "/SetOCGState", "/Rendition", "/Trans", "/GoTo3DView", "/RichMediaExecute"}
FORBIDDEN_ANNOTS = {"/Sound", "/Movie", "/Screen", "/3D", "/RichMedia", "/FileAttachment"}
NO_APPEARANCE_NEEDED = {"/Popup", "/Link"}
SIMPLE = {"/Type1", "/TrueType", "/MMType1"}
STANDARD_ENCODINGS = {"/WinAnsiEncoding", "/MacRomanEncoding"}
MAX_DEPTH = 12
FLAG_INVISIBLE, FLAG_HIDDEN, FLAG_PRINT, FLAG_NOVIEW, FLAG_TOGGLENOVIEW = 1, 2, 4, 32, 256


class PdfaError(EditorError):
    """Die Kopie wäre kein gültiges PDF/A – mit den Gründen."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        reasons = "; ".join(problems[:6])
        super().__init__(f"Als PDF/A speichern ist für dieses Dokument nicht möglich: {reasons}.")


@dataclass
class PdfaResult:
    path: Path
    fonts: int = 0  # eingebettete Ersatzschriften
    notes: list[str] = field(default_factory=list)  # was entfernt oder geändert wurde (für die Meldung)


def save_copy(document: EditorDocument, target: str | Path) -> PdfaResult:
    """Den aktuellen Stand als PDF/A-2b nach ``target`` speichern (nie über das Original)."""
    from . import save

    target = Path(target)
    if document.path is not None and save._same(document.path, target):  # noqa: SLF001
        raise EditorError("Die PDF/A-Kopie braucht einen eigenen Namen – das Original bleibt unverändert.")
    data, result = convert(document.serialize(keep_encryption=False), encrypted=document.encrypted)
    result.path = target
    copy = EditorDocument.from_bytes(data, name=target.name)
    try:
        save.write_copy(copy, data, target)
    finally:
        copy.close()
    return result


def convert(data: bytes, *, encrypted: bool = False) -> tuple[bytes, PdfaResult]:
    """PDF-Bytes (unverschlüsselt) → PDF/A-2b-Bytes. Wirft ``PdfaError`` mit den Gründen."""
    result = PdfaResult(Path())
    if encrypted:
        result.notes.append("Kennwortschutz entfernt")
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except (pikepdf.PdfError, ValueError) as exc:
        raise EditorError("Das Dokument lässt sich nicht lesen.") from exc
    try:
        problems: list[str] = []
        state = _State(pdf, result, problems)
        state.catalog()
        for page in pdf.pages:
            state.page(page.obj)
        state.forms()
        state.file_specs()
        if state.cmyk and not _has_cmyk_intent(pdf):
            problems.append("Das Dokument enthält CMYK-Farben (Druckvorstufe)")
        if problems:
            raise PdfaError(sorted(set(problems)))
        _output_intent(pdf)
        _metadata(pdf)
        buffer = io.BytesIO()
        pdf.save(
            buffer,
            compress_streams=True,
            stream_decode_level=pikepdf.StreamDecodeLevel.generalized,  # LZW → Flate
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            min_version="1.7",
            fix_metadata_version=False,  # bräuchte lxml; das XMP-Paket schreibt ``_metadata``
        )
    finally:
        pdf.close()
    out = buffer.getvalue()
    remaining = check(out)
    if remaining:
        raise PdfaError(remaining)
    result.notes = _unique(result.notes)
    return out, result


def check(data: bytes) -> list[str]:
    """Kurzprüfung einer PDF/A-Datei: die Punkte, die ``convert`` sicherstellt."""
    problems: list[str] = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        if pdf.is_encrypted:
            problems.append("verschlüsselt")
        root = pdf.Root
        intents = root.get("/OutputIntents")
        if not isinstance(intents, Array) or not any(str(i.get("/S", "")) == "/GTS_PDFA1" for i in intents if isinstance(i, Dictionary)):
            problems.append("keine Ausgabebedingung")
        metadata = root.get("/Metadata")
        packet = metadata.read_bytes() if isinstance(metadata, pikepdf.Stream) else b""
        if f"<pdfaid:part>{PART}</pdfaid:part>".encode() not in packet or f"<pdfaid:conformance>{CONFORMANCE}</pdfaid:conformance>".encode() not in packet:
            problems.append("keine PDF/A-Kennung in den Metadaten")
        names = root.get("/Names")
        if isinstance(names, Dictionary) and ("/JavaScript" in names or "/EmbeddedFiles" in names):
            problems.append("Skripte oder Anhänge vorhanden")
        if "/AA" in root or ("/AcroForm" in root and "/XFA" in root.AcroForm):
            problems.append("automatische Aktionen oder XFA vorhanden")
        seen: set = set()
        for page in pdf.pages:
            for font in _fonts_of(page.obj, seen):
                if not _embedded(font):
                    problems.append(f"Schrift »{_font_label(font)}« nicht eingebettet")
    return _unique(problems)


# Umwandlung --------------------------------------------------------------------------------------------
class _State:
    def __init__(self, pdf: pikepdf.Pdf, result: PdfaResult, problems: list[str]) -> None:
        self.pdf = pdf
        self.result = result
        self.problems = problems
        self.seen: set = set()
        self.font_done: dict = {}
        self.substitutes: dict = {}  # (Schrift, Kodierung) → eingebettete Ersatzschrift (einmal je Datei)
        self.cmyk = False

    def note(self, text: str) -> None:
        self.result.notes.append(text)

    def catalog(self) -> None:
        root = self.pdf.Root
        if "/AA" in root:
            del root.AA
            self.note("Automatische Aktionen entfernt")
        action = root.get("/OpenAction")
        if isinstance(action, Dictionary) and _forbidden_action(action):
            del root.OpenAction
            self.note("Skripte entfernt")
        names = root.get("/Names")
        if isinstance(names, Dictionary):
            if "/JavaScript" in names:
                del names.JavaScript
                self.note("Skripte entfernt")
            if "/EmbeddedFiles" in names:
                del names.EmbeddedFiles
                self.note("Eingebettete Dateien entfernt")
        for key in ("/Perms", "/Requirements", "/Collection", "/NeedsRendering"):
            if key in root:
                del root[key]
        ocprops = root.get("/OCProperties")
        if isinstance(ocprops, Dictionary):
            configs = [ocprops.get("/D")] + list(ocprops.get("/Configs") or [])
            for number, config in enumerate(configs):
                if isinstance(config, Dictionary):
                    if "/AS" in config:
                        del config.AS
                    if "/Name" not in config:
                        config.Name = pikepdf.String("Standard" if number == 0 else f"Ansicht {number}")
        outlines = root.get("/Outlines")
        if isinstance(outlines, Dictionary):
            self._outline_actions(outlines.get("/First"), 0)

    def _outline_actions(self, item, depth: int) -> None:
        guard = 0
        while isinstance(item, Dictionary) and guard < 100_000 and depth < 64:
            guard += 1
            action = item.get("/A")
            if isinstance(action, Dictionary) and _forbidden_action(action):
                del item.A
                self.note("Skripte entfernt")
            self._outline_actions(item.get("/First"), depth + 1)
            item = item.get("/Next")

    def page(self, page: pikepdf.Dictionary) -> None:
        for key in ("/AA", "/PresSteps"):
            if key in page:
                del page[key]
        self.resources(page.get("/Resources"), 0)
        self.contents(page)
        group = page.get("/Group")
        if isinstance(group, Dictionary) and _is_cmyk(group.get("/CS")):
            self.cmyk = True
        annots = page.get("/Annots")
        if isinstance(annots, Array):
            keep = Array()
            for annot in annots:
                if isinstance(annot, Dictionary) and self.annotation(annot):
                    keep.append(annot)
            if len(keep) != len(annots):
                page.Annots = keep

    def annotation(self, annot: pikepdf.Dictionary) -> bool:
        subtype = str(annot.get("/Subtype", ""))
        if subtype in FORBIDDEN_ANNOTS:
            self.note("Anhänge, Ton und Filme in Kommentaren entfernt")
            return False
        if "/AA" in annot:
            del annot.AA
        action = annot.get("/A")
        if isinstance(action, Dictionary) and _forbidden_action(action):
            del annot.A
            self.note("Skripte entfernt")
        if subtype == "/Popup":
            return True
        rect = annot.get("/Rect")
        empty = not isinstance(rect, Array) or len(rect) != 4 or abs(float(rect[2]) - float(rect[0])) < 0.01 or abs(float(rect[3]) - float(rect[1])) < 0.01
        appearance = annot.get("/AP")
        if subtype not in NO_APPEARANCE_NEEDED and not empty and not isinstance(appearance, Dictionary):
            self.note("Kommentare ohne eigenes Erscheinungsbild entfernt")
            return False
        try:
            flags = int(annot.get("/F", 0))
        except (TypeError, ValueError):
            flags = 0
        annot.F = (flags | FLAG_PRINT) & ~(FLAG_INVISIBLE | FLAG_HIDDEN | FLAG_NOVIEW | FLAG_TOGGLENOVIEW)
        if isinstance(appearance, Dictionary):
            for key in ("/D", "/R"):  # PDF/A: nur das normale Erscheinungsbild
                if key in appearance:
                    del appearance[key]
            normal = appearance.get("/N")
            if isinstance(normal, pikepdf.Stream):
                self.xobject(normal, 0)
            elif isinstance(normal, Dictionary):
                for state in normal.values():
                    if isinstance(state, pikepdf.Stream):
                        self.xobject(state, 0)
        return True

    def forms(self) -> None:
        form = self.pdf.Root.get("/AcroForm")
        if not isinstance(form, Dictionary):
            return
        if "/XFA" in form:
            del form.XFA
            self.note("XFA-Formularteil entfernt")
        if "/NeedAppearances" in form:
            del form.NeedAppearances
        self.resources(form.get("/DR"), 0)
        stack = list(form.get("/Fields") or [])
        guard = 0
        while stack and guard < 50_000:
            guard += 1
            field_ = stack.pop()
            if not isinstance(field_, Dictionary):
                continue
            if "/AA" in field_:
                del field_.AA
            if str(field_.get("/FT", "")) == "/Sig" and "/V" in field_:
                del field_.V  # nach der Umwandlung ohnehin ungültig
                self.note("Digitale Signatur entfernt (durch die Umwandlung ungültig)")
            stack.extend(field_.get("/Kids") or [])

    def file_specs(self) -> None:
        """Eingebettete Dateien an anderer Stelle (z. B. ``/AF``, Links): nur noch der Verweis, nicht die Datei."""
        for obj in self.pdf.objects:
            if isinstance(obj, Dictionary) and "/EF" in obj and str(obj.get("/Type", "/Filespec")) in ("/Filespec", "/F"):
                del obj.EF
                self.note("Eingebettete Dateien entfernt")

    def contents(self, holder: pikepdf.Object) -> None:
        if self.cmyk:
            return
        try:
            for operands, operator in pikepdf.parse_content_stream(holder):
                op = str(operator)
                if op in ("k", "K"):
                    self.cmyk = True
                    return
        except (pikepdf.PdfError, TypeError, ValueError):
            return

    def resources(self, resources, depth: int) -> None:
        if not isinstance(resources, Dictionary) or depth > MAX_DEPTH:
            return
        key = _ident(resources)
        if key is not None:
            if key in self.seen:
                return
            self.seen.add(key)
        for font in (resources.get("/Font") or {}).values() if isinstance(resources.get("/Font"), Dictionary) else ():
            if isinstance(font, Dictionary):
                self.font(font)
        spaces = resources.get("/ColorSpace")
        if isinstance(spaces, Dictionary):
            for space in spaces.values():
                if _is_cmyk(space):
                    self.cmyk = True
        states = resources.get("/ExtGState")
        if isinstance(states, Dictionary):
            for gstate in states.values():
                if not isinstance(gstate, Dictionary):
                    continue
                for name in ("/TR", "/TR2", "/HTO"):
                    if name in gstate and not (name == "/TR2" and str(gstate.get(name)) == "/Default"):
                        del gstate[name]
                halftone = gstate.get("/HT")
                if isinstance(halftone, Dictionary) and "/TransferFunction" in halftone:
                    del halftone.TransferFunction
        xobjects = resources.get("/XObject")
        if isinstance(xobjects, Dictionary):
            for name in list(xobjects.keys()):
                obj = xobjects[name]
                if not isinstance(obj, pikepdf.Stream):
                    continue
                if str(obj.get("/Subtype", "")) == "/PS" or "/PS" in obj and str(obj.get("/Subtype2", "")) == "/PS":
                    del xobjects[name]
                    self.problems.append("Das Dokument enthält PostScript-Teile")
                    continue
                self.xobject(obj, depth + 1)
        patterns = resources.get("/Pattern")
        if isinstance(patterns, Dictionary):
            for pattern in patterns.values():
                if isinstance(pattern, pikepdf.Stream):
                    self.resources(pattern.get("/Resources"), depth + 1)

    def xobject(self, obj: pikepdf.Stream, depth: int) -> None:
        key = _ident(obj)
        if key is not None:
            if key in self.seen:
                return
            self.seen.add(key)
        subtype = str(obj.get("/Subtype", ""))
        if subtype == "/Image":
            if obj.get("/Interpolate") is True or str(obj.get("/Interpolate", "")) == "true":
                obj.Interpolate = False
            for name in ("/Alternates", "/OPI"):
                if name in obj:
                    del obj[name]
            if _is_cmyk(obj.get("/ColorSpace")):
                self.cmyk = True
            return
        if subtype == "/Form":
            for name in ("/OPI", "/PS"):
                if name in obj:
                    del obj[name]
            group = obj.get("/Group")
            if isinstance(group, Dictionary) and _is_cmyk(group.get("/CS")):
                self.cmyk = True
            self.resources(obj.get("/Resources"), depth + 1)
            self.contents(obj)

    def font(self, font: pikepdf.Dictionary) -> None:
        key = _ident(font)
        if key is not None:
            if key in self.font_done:
                return
            self.font_done[key] = True
        subtype = str(font.get("/Subtype", ""))
        if subtype == "/Type3":
            self.resources(font.get("/Resources"), 1)
            return
        if subtype == "/Type0":
            for descendant in font.get("/DescendantFonts") or []:
                if isinstance(descendant, Dictionary) and str(descendant.get("/Subtype", "")) == "/CIDFontType2" and "/CIDToGIDMap" not in descendant:
                    descendant.CIDToGIDMap = Name.Identity  # Standardwert ausdrücklich (PDF/A verlangt den Eintrag)
        if _embedded(font):
            return
        label = _font_label(font)
        if subtype not in SIMPLE:
            self.problems.append(f"Schrift »{label}« ist nicht eingebettet und lässt sich nicht ersetzen")
            return
        try:
            embedded = _embed_simple(self.pdf, font, self.substitutes)
        except _NoSubstitute:
            self.problems.append(f"Für die Schrift »{label}« gibt es auf diesem PC keinen Ersatz zum Einbetten")
            return
        except (pikepdf.PdfError, PermissionError, ValueError, KeyError, OSError):
            self.problems.append(f"Schrift »{label}« lässt sich nicht einbetten")
            return
        if embedded:
            self.result.fonts += 1


class _NoSubstitute(Exception):
    pass


def _embed_simple(pdf: pikepdf.Pdf, font: pikepdf.Dictionary, cache: dict) -> bool:
    """Nicht eingebettete einfache Schrift: passende Systemschrift (TrueType) als Teilmenge einbetten.
    Kodierung: WinAnsi als Grundlage, Abweichungen der bisherigen Kodierung als ``/Differences``."""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    base_font = str(font.get("/BaseFont", "/Helvetica")).lstrip("/")
    name = base_font.split("+", 1)[-1]
    if name in ("Symbol", "ZapfDingbats") or "symbol" in name.lower() or "dingbat" in name.lower() or "wingding" in name.lower():
        raise _NoSubstitute()
    descriptor = font.get("/FontDescriptor")
    style = fonts.style_of(base_font, descriptor)
    family = fonts.standard_substitute(style, descriptor)  # Art der Schrift: Helvetica, Times oder Courier
    path = fonts.find_system_font(style)  # dieselbe Familie (Arial für Helvetica …), sonst eine allgemeine
    if path is None:
        raise _NoSubstitute()
    raw = path.read_bytes()
    if not fonts.embedding_allowed(raw):
        raise _NoSubstitute()
    names = _encoding_chars(font, base_font)  # Code → Zeichen (256 Einträge, "" = keins)
    key = (str(path), tuple(names))
    if key in cache:
        _set_entries(font, cache[key])
        return False  # schon eingebettet (dieselbe Schrift auf einer anderen Seite)
    full = TTFont(io.BytesIO(raw))
    cmap = full.getBestCmap() or {}
    unicodes: dict[int, int] = {}
    for code, char in enumerate(names):
        if len(char) == 1 and ord(char) in cmap:
            unicodes[code] = ord(char)
    options = subset.Options()
    options.notdef_outline = True
    options.layout_features = []
    options.name_IDs = ["*"]
    options.hinting = False
    options.drop_tables += ["GSUB", "GPOS", "GDEF", "kern", "DSIG", "FFTM"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(set(unicodes.values()) | {0x20}))
    subsetter.subset(full)
    winansi = fonts.base_encoding("/WinAnsiEncoding")
    # Weicht die Kodierung von WinAnsi ab (eigene /Differences), wird die Schrift »symbolisch«: Code → Glyphe über
    # eine eigene cmap (3,0) – PDF/A erlaubt bei nicht-symbolischen TrueType-Schriften nur einfache Kodierungen.
    symbolic = any(names[code] and names[code] != winansi[code] for code in unicodes)
    sub_cmap = full.getBestCmap() or {}
    glyph_of = {code: sub_cmap.get(value) for code, value in unicodes.items() if sub_cmap.get(value)}
    if symbolic:
        from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

        table = CmapSubtable.newSubtable(4)
        table.platformID, table.platEncID, table.language = 3, 0, 0
        table.cmap = {0xF000 + code: glyph for code, glyph in glyph_of.items()}
        full["cmap"].tables = [table]
    buffer = io.BytesIO()
    full.save(buffer)
    head, hhea = full["head"], full["hhea"]
    os2 = full["OS/2"] if "OS/2" in full else None
    scale = 1000.0 / head.unitsPerEm
    hmtx = full["hmtx"].metrics
    first, last = 0, 255
    used = sorted(glyph_of)
    if used:
        first, last = used[0], used[-1]
    widths = Array()
    missing_width = round(hmtx[".notdef"][0] * scale) if ".notdef" in hmtx else 0
    for code in range(first, last + 1):
        glyph = glyph_of.get(code)
        widths.append(round(hmtx[glyph][0] * scale) if glyph in hmtx else missing_width)
    ps_name = re.sub(r"[^A-Za-z0-9\-]", "", full["name"].getDebugName(6) or path.stem) or "Schrift"
    tag = _tag(ps_name + base_font + ("S" if symbolic else ""))
    flags = (4 if symbolic else 32) | (64 if style.italic else 0) | (2 if family.startswith("Times") else 0) | (1 if family.startswith("Courier") else 0)
    new_descriptor = pdf.make_indirect(Dictionary(
        Type=Name.FontDescriptor,
        FontName=Name(f"/{tag}+{ps_name}"),
        Flags=flags,
        FontBBox=Array([round(head.xMin * scale), round(head.yMin * scale), round(head.xMax * scale), round(head.yMax * scale)]),
        ItalicAngle=float(full["post"].italicAngle) if "post" in full else 0,
        Ascent=round(hhea.ascent * scale),
        Descent=round(hhea.descent * scale),
        CapHeight=round((getattr(os2, "sCapHeight", 0) or hhea.ascent) * scale),
        StemV=80,
        MissingWidth=missing_width,
        FontFile2=pdf.make_stream(buffer.getvalue()),
    ))
    entries = {
        "/Subtype": Name.TrueType,
        "/BaseFont": Name(f"/{tag}+{ps_name}"),
        "/FirstChar": first,
        "/LastChar": last,
        "/Widths": pdf.make_indirect(widths),
        "/FontDescriptor": new_descriptor,
        "/Encoding": None if symbolic else Name.WinAnsiEncoding,
        "/ToUnicode": pdf.make_stream(_tounicode({code: names[code] for code in glyph_of})),
    }
    cache[key] = entries
    _set_entries(font, entries)
    return True


def _set_entries(font: pikepdf.Dictionary, entries: dict) -> None:
    for name, value in entries.items():
        if value is None:
            if name in font:
                del font[name]
        else:
            font[name] = value


def _tounicode(mapping: dict[int, str]) -> bytes:
    """ToUnicode-CMap für eine einfache Schrift (ein Byte je Code)."""
    lines = [
        "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
        "1 begincodespacerange", "<00> <FF>", "endcodespacerange",
    ]
    items = sorted((code, char) for code, char in mapping.items() if char)
    for start in range(0, len(items), 100):
        chunk = items[start : start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        lines += [f"<{code:02X}> <{char.encode('utf-16-be').hex().upper()}>" for code, char in chunk]
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return ("\n".join(lines) + "\n").encode("ascii")


def _encoding_chars(font: pikepdf.Dictionary, base_font: str) -> list[str]:
    """Zeichen je Code (0–255) nach ``/Encoding`` samt ``/Differences`` – wie ein Betrachter die Schrift liest."""
    encoding = font.get("/Encoding")
    base_name = None
    differences = None
    if isinstance(encoding, Name):
        base_name = str(encoding)
    elif isinstance(encoding, Dictionary):
        base_name = str(encoding.get("/BaseEncoding")) if "/BaseEncoding" in encoding else None
        differences = encoding.get("/Differences")
    if base_name is None and base_font.split("+")[-1] not in fonts.STANDARD_14:
        base_name = "/StandardEncoding"
    chars = [c if isinstance(c, str) else "" for c in fonts.base_encoding(base_name or "/StandardEncoding", base_font)]
    chars = (chars + [""] * 256)[:256]
    if isinstance(differences, Array):
        code = 0
        for item in differences:
            if isinstance(item, Name):
                if 0 <= code < 256:
                    chars[code] = fonts.glyph_to_unicode(str(item))
                code += 1
            else:
                try:
                    code = int(item)
                except (TypeError, ValueError):
                    continue
    return chars


def _tag(seed: str) -> str:
    import hashlib

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return "".join(chr(65 + b % 26) for b in digest[:6])


def _output_intent(pdf: pikepdf.Pdf) -> None:
    root = pdf.Root
    intents = root.get("/OutputIntents")
    if isinstance(intents, Array) and any(isinstance(i, Dictionary) and str(i.get("/S", "")) == "/GTS_PDFA1" and "/DestOutputProfile" in i for i in intents):
        return
    from PIL import ImageCms

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    icc = pdf.make_stream(profile)
    icc.N = 3
    intent = pdf.make_indirect(Dictionary(
        Type=Name.OutputIntent,
        S=Name.GTS_PDFA1,
        OutputConditionIdentifier=pikepdf.String("sRGB IEC61966-2.1"),
        RegistryName=pikepdf.String("http://www.color.org"),
        Info=pikepdf.String("sRGB IEC61966-2.1"),
        DestOutputProfile=icc,
    ))
    root.OutputIntents = Array([intent])


def _has_cmyk_intent(pdf: pikepdf.Pdf) -> bool:
    intents = pdf.Root.get("/OutputIntents")
    if not isinstance(intents, Array):
        return False
    for intent in intents:
        profile = intent.get("/DestOutputProfile") if isinstance(intent, Dictionary) else None
        if isinstance(profile, pikepdf.Stream) and int(profile.get("/N", 0)) == 4:
            return True
    return False


def _metadata(pdf: pikepdf.Pdf) -> None:
    """Neues XMP-Paket aus dem Dokumentinfo-Verzeichnis – beide stimmen danach überein (PDF/A verlangt das).

    Geschrieben mit der Standardbibliothek (die Laufzeit der App hat kein lxml, ``open_metadata`` braucht es).
    Eigene Eigenschaften eines vorhandenen Pakets entfallen: PDF/A erlaubt sie nur mit Erweiterungsschema."""
    info = pdf.docinfo
    for key in list(info.keys()):
        value = info[key]
        if key not in INFO_KEYS or not isinstance(value, pikepdf.String) or not str(value).strip():
            del info[key]  # leere, fremde oder nicht abbildbare Einträge (z. B. /Trapped)
    info[Name.Producer] = pikepdf.String("Novadesk")
    for key in ("/CreationDate", "/ModDate"):
        if key in info and _iso_date(str(info[key])) is None:
            del info[key]
    if "/ModDate" not in info:
        info[Name.ModDate] = pikepdf.String(_pdf_date(datetime.now(timezone.utc)))
    pdf.Root.Metadata = pdf.make_stream(_xmp_packet(info), Type=Name.Metadata, Subtype=Name.XML)


INFO_KEYS = {"/Title", "/Author", "/Subject", "/Keywords", "/Creator", "/Producer", "/CreationDate", "/ModDate"}


def _xmp_packet(info) -> bytes:
    from xml.sax.saxutils import escape

    def text(key: str) -> str:
        return escape(str(info[key])) if key in info else ""

    parts = []
    if "/Title" in info:
        parts.append(f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{text("/Title")}</rdf:li></rdf:Alt></dc:title>')
    if "/Author" in info:
        parts.append(f"<dc:creator><rdf:Seq><rdf:li>{text('/Author')}</rdf:li></rdf:Seq></dc:creator>")
    if "/Subject" in info:
        parts.append(f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{text("/Subject")}</rdf:li></rdf:Alt></dc:description>')
    if "/Keywords" in info:
        parts.append(f"<pdf:Keywords>{text('/Keywords')}</pdf:Keywords>")
    parts.append(f"<pdf:Producer>{text('/Producer')}</pdf:Producer>")
    if "/Creator" in info:
        parts.append(f"<xmp:CreatorTool>{text('/Creator')}</xmp:CreatorTool>")
    if "/CreationDate" in info:
        parts.append(f"<xmp:CreateDate>{_iso_date(str(info['/CreationDate']))}</xmp:CreateDate>")
    parts.append(f"<xmp:ModifyDate>{_iso_date(str(info['/ModDate']))}</xmp:ModifyDate>")
    parts.append(f"<pdfaid:part>{PART}</pdfaid:part><pdfaid:conformance>{CONFORMANCE}</pdfaid:conformance>")
    body = "".join(parts)
    packet = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:pdf="http://ns.adobe.com/pdf/1.3/" '
        'xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/">'
        f"{body}</rdf:Description></rdf:RDF></x:xmpmeta>"
        + " " * 1024
        + '<?xpacket end="w"?>'
    )
    return packet.encode("utf-8")


_PDF_DATE = re.compile(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz+\-])?(\d{2})?'?(\d{2})?'?$")


def _iso_date(value: str) -> str | None:
    """PDF-Datum (``D:20261019093000+02'00'``) → XMP-Datum (``2026-10-19T09:30:00+02:00``) – gleicher Zeitpunkt
    und gleiche Genauigkeit, wie PDF/A es verlangt. Unlesbar: ``None``."""
    match = _PDF_DATE.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, sign, tz_hour, tz_minute = match.groups()
    out = year
    if month:
        out += f"-{month}"
        if day:
            out += f"-{day}"
            if hour and minute:
                out += f"T{hour}:{minute}"
                if second:
                    out += f":{second}"
                if sign in ("Z", "z"):
                    out += "Z"
                elif sign in ("+", "-"):
                    out += f"{sign}{tz_hour or '00'}:{tz_minute or '00'}"
    return out


def _pdf_date(moment: datetime) -> str:
    return moment.strftime("D:%Y%m%d%H%M%S") + "Z"


# Hilfen ----------------------------------------------------------------------------------------------------
def _forbidden_action(action: Dictionary, depth: int = 0) -> bool:
    if depth > 16:
        return True
    if str(action.get("/S", "")) in FORBIDDEN_ACTIONS:
        return True
    following = action.get("/Next")
    if isinstance(following, Dictionary):
        return _forbidden_action(following, depth + 1)
    if isinstance(following, Array):
        return any(isinstance(item, Dictionary) and _forbidden_action(item, depth + 1) for item in following)
    return False


def _is_cmyk(space) -> bool:
    if isinstance(space, Name):
        return str(space) == "/DeviceCMYK"
    if isinstance(space, Array) and len(space) >= 2:
        kind = str(space[0])
        if kind in ("/Separation", "/DeviceN") and len(space) >= 3:
            return _is_cmyk(space[2])
        if kind == "/Indexed":
            return _is_cmyk(space[1])
    return False


def _embedded(font: pikepdf.Dictionary) -> bool:
    subtype = str(font.get("/Subtype", ""))
    if subtype == "/Type3":
        return True
    if subtype == "/Type0":
        descendants = font.get("/DescendantFonts")
        if not isinstance(descendants, Array) or not len(descendants):
            return False
        return all(isinstance(d, Dictionary) and _embedded(d) for d in descendants)
    descriptor = font.get("/FontDescriptor")
    return isinstance(descriptor, Dictionary) and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def _font_label(font: pikepdf.Dictionary) -> str:
    return str(font.get("/BaseFont", "/unbenannt")).lstrip("/").split("+", 1)[-1]


def _fonts_of(page: pikepdf.Dictionary, seen: set):
    stack = [(page.get("/Resources"), 0)]
    for annot in page.get("/Annots") or []:
        appearance = annot.get("/AP") if isinstance(annot, Dictionary) else None
        normal = appearance.get("/N") if isinstance(appearance, Dictionary) else None
        if isinstance(normal, pikepdf.Stream):
            stack.append((normal.get("/Resources"), 1))
        elif isinstance(normal, Dictionary):
            stack += [(state.get("/Resources"), 1) for state in normal.values() if isinstance(state, pikepdf.Stream)]
    while stack:
        resources, depth = stack.pop()
        if not isinstance(resources, Dictionary) or depth > MAX_DEPTH:
            continue
        key = _ident(resources)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        font_dict = resources.get("/Font")
        if isinstance(font_dict, Dictionary):
            for font in font_dict.values():
                if isinstance(font, Dictionary):
                    yield font
        xobjects = resources.get("/XObject")
        if isinstance(xobjects, Dictionary):
            for obj in xobjects.values():
                if isinstance(obj, pikepdf.Stream) and str(obj.get("/Subtype", "")) == "/Form":
                    stack.append((obj.get("/Resources"), depth + 1))


def _ident(obj):
    """Kennung eines indirekten Objekts – direkte Objekte haben keine (``None``: nie als »schon gesehen« zählen;
    ``id()`` der Python-Hülle taugt nicht, sie wird nach dem Aufräumen wiederverwendet)."""
    try:
        return obj.objgen if obj.is_indirect else None
    except AttributeError:
        return None


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
