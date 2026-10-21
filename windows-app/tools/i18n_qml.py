"""Textbindungen der QML-Dateien über ``I18n.tr(…, I18n.revision)`` führen (englische Oberfläche, seit 4.0 Beta 6).

Aufruf: ``python tools/i18n_qml.py [--check]`` – ohne ``--check`` werden die Dateien umgeschrieben, mit ``--check`` nur
die Stellen genannt, die noch nicht übersetzt werden (Test ``test_i18n.py``). Erfasst werden Anzeige-Eigenschaften von
Elementen (``text``, ``title``, ``tip`` …) – nicht Eingabefelder (deren ``text`` ist die Eingabe), nicht Schlüssel in
JavaScript-Listen und nicht Eigenschaftsdeklarationen (die übersetzt erst die Stelle, die sie anzeigt).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

QML = Path(__file__).resolve().parents[1] / "app" / "qml"
DISPLAY = {
    "text", "label", "tip", "title", "subtitle", "placeholderText", "placeholder", "description", "message", "busyText",
    "Accessible.name", "Accessible.description", "closeTip", "tooltip", "displayText", "emptyText", "hint", "caption",
    "heading", "detail", "note", "actionText", "primaryText", "secondaryText", "confirmText", "doneText",
}
INPUTS = {"PTextField", "PTextArea", "TextInput", "TextEdit", "TextField", "TextArea", "T.TextField", "T.TextArea", "PRichTextEditor", "PTextCaret"}
WRAP = "I18n.tr("
SUFFIX = ", I18n.revision)"


class Element:
    def __init__(self, kind: str) -> None:
        self.kind = kind  # Typname eines QML-Elements oder "js"


def _skip_string(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == quote:
            return i + 1
        if quote == "`" and src.startswith("${", i):
            depth = 1
            i += 2
            while i < len(src) and depth:
                if src[i] in "\"'`":
                    i = _skip_string(src, i)
                    continue
                depth += {"{": 1, "}": -1}.get(src[i], 0)
                i += 1
            continue
        i += 1
    return i


def _skip_comment(src: str, i: int) -> int:
    if src.startswith("//", i):
        end = src.find("\n", i)
        return len(src) if end < 0 else end
    end = src.find("*/", i + 2)
    return len(src) if end < 0 else end + 2


def expression_end(src: str, start: int) -> int:
    """Ende eines Bindungsausdrucks ab ``start``: »;«, »}« oder Zeilenende auf oberster Ebene (nicht nach einem Operator)."""
    i, depth = start, 0
    if src[start] == "{":  # JavaScript-Block
        depth = 0
        while i < len(src):
            ch = src[i]
            if ch in "\"'`":
                i = _skip_string(src, i)
                continue
            if src.startswith("//", i) or src.startswith("/*", i):
                i = _skip_comment(src, i)
                continue
            if ch in "{([":
                depth += 1
            elif ch in "})]":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return i
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            i = _skip_string(src, i)
            continue
        if src.startswith("//", i) or src.startswith("/*", i):
            if depth == 0:
                return i
            i = _skip_comment(src, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and ch == ";":
            return i
        elif depth == 0 and ch == "\n":
            before = src[start:i].rstrip()
            after = src[i:].lstrip()
            if not (before.endswith(("+", "?", ":", "&&", "||", ",", "(")) or after.startswith(("+", "?", ":", "&&", "||", "."))):
                return i
        i += 1
    return i


STATEMENT = re.compile(r"(?:(readonly\s+)?(required\s+)?property\s+[\w<>.]+\s+)?([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)?)\s*:\s*")
TYPE_BEFORE = re.compile(r"([A-Z][\w]*(?:\.[A-Z][\w]*)*)\s*$")


def bindings(src: str):
    """Anzeige-Bindungen: (Beginn des Ausdrucks, Ende, Typ des Elements)."""
    stack: list[Element] = []
    i = 0
    statement_start = True
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            i = _skip_string(src, i)
            statement_start = False
            continue
        if src.startswith("//", i) or src.startswith("/*", i):
            i = _skip_comment(src, i)
            continue
        if ch == "{":
            head = src[max(0, i - 120):i]
            match = TYPE_BEFORE.search(head)
            kind = match.group(1) if match else "js"
            stack.append(Element(kind))
            i += 1
            statement_start = True
            continue
        if ch == "}":
            if stack:
                stack.pop()
            i += 1
            statement_start = True
            continue
        if ch in ";\n":
            i += 1
            statement_start = True
            continue
        if ch in " \t\r":
            i += 1
            continue
        if statement_start and stack and stack[-1].kind != "js":
            match = STATEMENT.match(src, i)
            if match is not None:
                name = match.group(3)
                declared = src[i:match.start(3)].strip() != ""
                start = match.end()
                if start < len(src) and src[start] not in "\n":
                    end = expression_end(src, start)
                    if not declared and name in DISPLAY and not (name == "text" and stack[-1].kind in INPUTS):
                        yield start, end, stack[-1].kind
                        i = end
                        statement_start = False
                        continue
                    if src[start] == "{":  # JavaScript-Block (Signalbehandlung, Bindung): nicht darin suchen
                        i = end
                        statement_start = False
                        continue
                    i = start  # Wert (auch ein Element, etwa »delegate: Item {«) normal weiterlesen
                    statement_start = False
                    continue
        statement_start = False
        i += 1


def wanted(expr: str) -> bool:
    text = expr.strip()
    if not text or WRAP in text or text in ('""', "''"):
        return False
    if re.fullmatch(r"-?[\d.]+|true|false|null|undefined", text) or re.match(r"[A-Z][\w.]*\s*\{", text):
        return False  # Zahl, Wahrheitswert oder ein Element (»header: Item {«)
    return True


def rewrite(src: str) -> tuple[str, int]:
    pieces = []
    last = 0
    count = 0
    for start, end, _kind in bindings(src):
        expr = src[start:end]
        trailing = len(expr) - len(expr.rstrip())
        core = expr.rstrip()
        if not wanted(core):
            continue
        if core.startswith("{"):
            replacement = f"{WRAP}(function() {core})(){SUFFIX}"
        else:
            replacement = f"{WRAP}{core}{SUFFIX}"
        pieces.append(src[last:start])
        pieces.append(replacement + expr[len(core):] if trailing else replacement)
        last = end
        count += 1
    pieces.append(src[last:])
    result = "".join(pieces)
    if count and "import PdfTool.Backend" not in result:
        result = re.sub(r"(^import [^\n]+\n)(?!import )", r"\1import PdfTool.Backend\n", result, count=1, flags=re.M)
    return result, count


def unwrapped(src: str) -> list[str]:
    return [src[s:e].strip() for s, e, _k in bindings(src) if wanted(src[s:e])]


def main(argv: list[str]) -> int:
    check = "--check" in argv
    total = 0
    for path in sorted(QML.rglob("*.qml")):
        src = path.read_text(encoding="utf-8")
        if check:
            missing = unwrapped(src)
            for expr in missing:
                print(f"{path.relative_to(QML)}: {expr[:100]}")
            total += len(missing)
            continue
        result, count = rewrite(src)
        if count:
            path.write_text(result, encoding="utf-8")
            total += count
    print(f"{total} Stellen", file=sys.stderr)
    return 1 if check and total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
