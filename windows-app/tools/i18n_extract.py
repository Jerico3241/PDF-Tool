"""Deutsche Oberflächentexte der App sammeln – für den Katalog der englischen Oberfläche (``app/i18n/en.json``).

* QML: jeder Text in Anführungszeichen, dazu Verkettungen (»"Seite " + n + " von " + m« → Muster »Seite {0} von {1}«)
* Python: Texte und f-Strings (»f"{n} Bilder gespeichert"« → »{0} Bilder gespeichert«), ohne Docstrings und
  Protokollmeldungen

Aufruf: ``python tools/i18n_extract.py`` gibt die fehlenden Einträge als JSON aus (``--all``: alle); der Test
``test_i18n.py`` prüft, dass keiner fehlt.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
QML = APP / "qml"
CATALOG = APP / "i18n" / "en.json"
# Python-Module mit Oberflächentexten (Meldungen, Dialoge, Listen); Engine-Code ohne Anzeige bleibt außen vor
PY_DIRS = ("qtapp", "tools", "assistant", "updater", "backup", "diagnostics")
PY_FILES = ("appstate.py", "engine.py", "storage.py", "handoff.py", "start.py", "richtext.py")
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "log"}
SKIP_CALLS = {"getLogger", "get", "environ", "setdefault", "startswith", "endswith", "split", "replace", "compile", "match", "search", "sub",
              "findall", "fullmatch", "strip", "join", "encode", "decode", "Name", "Path", "open", "setProperty", "property", "item", "items"}
_LETTERS = re.compile(r"[A-Za-zÄÖÜäöüß]")
_GERMAN = re.compile(r"[äöüßÄÖÜ]|\b(der|die|das|und|oder|nicht|mit|für|von|ein|eine|ist|wird|werden|auf|im|zu|bitte|keine?|alle|nach|beim|zum|zur|den|dem|des|sich|Sie|Datei|Seite|Seiten|Ordner|Öffnen|Speichern|Abbrechen|Schließen)\b")


def ui_text(value: str) -> bool:
    """Sieht aus wie ein Oberflächentext (nicht Schlüssel, Pfad, Farbe, Format, Ausdruck)."""
    text = value.strip()
    if len(_LETTERS.findall(text)) < 2 or len(text) > 2500:
        return False
    if re.fullmatch(r"[a-z0-9_.\-/:#%]+", text) or re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(_[A-Za-z0-9]+)+", text):
        return False  # Schlüssel, Bezeichner, Dateinamen
    if re.match(r"(https?:|qrc:|image:|file:|#[0-9a-fA-F]{3,8}$)", text) or "\\" in text and " " not in text:
        return False
    if re.fullmatch(r"[A-Za-z][a-zA-Z]+", text):  # ein Wort: nur deutsch aussehende Wörter mit Großbuchstaben
        return text[0].isupper() and (bool(_GERMAN.search(text)) or text not in ENGLISH_WORDS)
    return bool(_GERMAN.search(text)) or (" " in text and text[0].isupper() and not re.search(r"[{}();=<>]", text))


ENGLISH_WORDS = {
    "Item", "Text", "Rectangle", "Image", "None", "True", "False", "Arial", "Helvetica", "Times", "Courier", "Calibri", "Segoe", "Windows", "Qt",
    "PDF", "OCR", "Excel", "Word", "PowerPoint", "Office", "Tesseract", "Mica", "Microsoft", "English", "Deutsch", "Light", "Dark",
}


# --- QML -----------------------------------------------------------------------------------------------------------
_TOKEN = re.compile(r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|//[^\n]*|/\*.*?\*/|[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|\S''', re.S)


def _js_string(token: str) -> str:
    try:
        return json.loads('"' + token[1:-1].replace('\\"', '"').replace('"', '\\"') + '"') if token[0] == "'" else json.loads(token)
    except ValueError:
        return token[1:-1]


def qml_strings(src: str) -> tuple[set[str], set[str]]:
    """Texte und Muster einer QML-Datei."""
    tokens = [t for t in _TOKEN.findall(src) if not t.startswith(("//", "/*"))]
    exact: set[str] = set()
    patterns: set[str] = set()
    for token in tokens:
        if token[0] in "\"'":
            value = _js_string(token)
            if ui_text(value):
                exact.add(value)
    # Verkettungen: Folgen von Termen, verbunden mit »+«
    i = 0
    while i < len(tokens):
        terms, end = _chain(tokens, i)
        if len(terms) >= 2 and any(kind == "s" and ui_text(value) for kind, value in terms):
            template, n = "", 0
            for kind, value in terms:
                if kind == "s":
                    template += value.replace("{", "{{").replace("}", "}}") if False else value
                else:
                    template += "{" + str(n) + "}"
                    n += 1
            if n and ui_text(re.sub(r"\{\d+\}", "", template)):
                patterns.add(template)
            i = end
            continue
        i += 1
    return exact, patterns


def _term(tokens: list[str], i: int) -> tuple[tuple[str, str] | None, int]:
    if i >= len(tokens):
        return None, i
    token = tokens[i]
    if token[0] in "\"'":
        return ("s", _js_string(token)), i + 1
    if token == "(" or re.match(r"[A-Za-z_$\d]", token):
        j = i
        if token == "(":
            j = _close(tokens, i)
        else:
            j = i + 1
        while j < len(tokens) and tokens[j] in (".", "(", "["):
            if tokens[j] == ".":
                j += 2
            else:
                j = _close(tokens, j)
        return ("x", ""), j
    return None, i


def _close(tokens: list[str], i: int) -> int:
    pairs = {"(": ")", "[": "]", "{": "}"}
    opener = tokens[i]
    depth = 0
    j = i
    while j < len(tokens):
        if tokens[j] == opener:
            depth += 1
        elif tokens[j] == pairs[opener]:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return j


def _chain(tokens: list[str], i: int) -> tuple[list[tuple[str, str]], int]:
    if i > 0 and tokens[i - 1] in (".",):
        return [], i
    first, j = _term(tokens, i)
    if first is None:
        return [], i
    terms = [first]
    while j < len(tokens) and tokens[j] == "+" and (j + 1 >= len(tokens) or tokens[j + 1] not in ("+", "=")):
        term, k = _term(tokens, j + 1)
        if term is None:
            break
        terms.append(term)
        j = k
    if j < len(tokens) and tokens[j] in (".", "(", "["):  # Teil eines größeren Ausdrucks (Methodenaufruf)
        return terms if len(terms) >= 2 else [], j
    return terms, j


# --- Python --------------------------------------------------------------------------------------------------------
class _Collector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.exact: set[str] = set()
        self.patterns: set[str] = set()
        self._skip: set[int] = set()

    def visit_Module(self, node):  # noqa: N802
        self._docstrings(node)
        self.generic_visit(node)

    def _docstrings(self, node) -> None:
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            self._skip.add(id(body[0].value))

    def visit_FunctionDef(self, node):  # noqa: N802
        self._docstrings(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Call(self, node):  # noqa: N802
        name = node.func.attr if isinstance(node.func, ast.Attribute) else (node.func.id if isinstance(node.func, ast.Name) else "")
        if name in LOG_METHODS and isinstance(node.func, ast.Attribute) and name != "error" or (name == "error" and isinstance(node.func, ast.Attribute) and "log" in ast.unparse(node.func.value).lower()):
            for sub in ast.walk(node):
                self._skip.add(id(sub))
        elif name in SKIP_CALLS:
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant):
                    self._skip.add(id(arg))
        self.generic_visit(node)

    def visit_Subscript(self, node):  # noqa: N802 - Schlüssel: cfg["…"]
        for sub in ast.walk(node.slice):
            self._skip.add(id(sub))
        self.generic_visit(node)

    def visit_Compare(self, node):  # noqa: N802 - Vergleiche mit Schlüsseln
        for sub in [node.left, *node.comparators]:
            if isinstance(sub, ast.Constant):
                self._skip.add(id(sub))
        self.generic_visit(node)

    def visit_Constant(self, node):  # noqa: N802
        if id(node) not in self._skip and isinstance(node.value, str) and ui_text(node.value):
            self.exact.add(node.value)

    def visit_JoinedStr(self, node):  # noqa: N802
        if id(node) in self._skip:
            return
        template, n = "", 0
        for value in node.values:
            if isinstance(value, ast.Constant):
                template += str(value.value)
            else:
                template += "{" + str(n) + "}"
                n += 1
        if ui_text(re.sub(r"\{\d+\}", " ", template)):
            (self.patterns if n else self.exact).add(template)
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                self.visit(value.value)

    def visit_BinOp(self, node):  # noqa: N802 - "…" + x + "…"
        if isinstance(node.op, ast.Add) and id(node) not in self._skip:
            terms = _flatten(node)
            if any(isinstance(t, ast.Constant) and isinstance(t.value, str) for t in terms) and len(terms) >= 2:
                template, n = "", 0
                for term in terms:
                    if isinstance(term, ast.Constant) and isinstance(term.value, str):
                        template += term.value
                    else:
                        template += "{" + str(n) + "}"
                        n += 1
                if n and ui_text(re.sub(r"\{\d+\}", " ", template)):
                    self.patterns.add(template)
        self.generic_visit(node)


def _flatten(node) -> list:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten(node.left) + _flatten(node.right)
    return [node]


def python_files() -> list[Path]:
    files = [APP / name for name in PY_FILES if (APP / name).is_file()]
    for folder in PY_DIRS:
        files += sorted((APP / folder).rglob("*.py"))
    # Anweisungen an das Sprachmodell sind keine Oberflächentexte
    return [path for path in files if "__pycache__" not in path.parts and path.name != "prompts.py"]


def collect() -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    patterns: set[str] = set()
    for path in sorted(QML.rglob("*.qml")):
        e, p = qml_strings(path.read_text(encoding="utf-8"))
        exact |= e
        patterns |= p
    for path in python_files():
        collector = _Collector()
        try:
            collector.visit(ast.parse(path.read_text(encoding="utf-8")))
        except SyntaxError:
            continue
        exact |= collector.exact
        patterns |= collector.patterns
    patterns = {p for p in patterns if re.search(r"\{\d+\}", p)}
    return exact, patterns


def missing() -> dict:
    exact, patterns = collect()
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    have_exact = data.get("exact") or {}
    have_patterns = data.get("patterns") or {}
    return {"exact": sorted(e for e in exact if e not in have_exact), "patterns": sorted(p for p in patterns if p not in have_patterns)}


if __name__ == "__main__":
    if "--all" in sys.argv:
        exact, patterns = collect()
        result = {"exact": sorted(exact), "patterns": sorted(patterns)}
    else:
        result = missing()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    print(f"\n{len(result['exact'])} Texte, {len(result['patterns'])} Muster", file=sys.stderr)
