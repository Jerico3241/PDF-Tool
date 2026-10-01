"""Release Notes sicher anzeigen: Markdown → einfache Blöcke mit geprüftem Inline-Markup.

Unterstützt: Überschriften, Absätze, Aufzählungen (``-``, ``*``, ``+``, ``1.``) mit
Fortsetzungszeilen und zwei Ebenen, Zitate, Trennlinien, Codeblöcke, **fett**, *kursiv*,
``Code``, Links ``[Text](https://…)`` und nackte ``https://``-Adressen.

Sicherheit – die Oberfläche bekommt nur, was hier erzeugt wird:

* Jeder Text wird maskiert; erzeugt werden ausschließlich ``<b>``, ``<i>``, ``<code>``,
  ``<br>`` und ``<a href="https://…">``.
* Rohes HTML erscheint als Text, HTML-Kommentare entfallen.
* Bilder werden nie geladen – es erscheint ihr Alternativtext.
* Nur ``https``-Links werden klickbar; ``javascript:``, ``file:``, ``http:`` … bleiben Text.
  Geöffnet wird ein Link erst bei einem Klick – im Standardbrowser, nie in der App.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

MAX_BLOCKS = 300
MAX_TEXT = 60_000

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^(?:-\s*){3,}$|^(?:\*\s*){3,}$|^(?:_\s*){3,}$")
_BULLET = re.compile(r"^(?P<indent>\s*)(?P<marker>[-*+]|\d{1,3}[.)])\s+(?P<text>.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TOKEN = re.compile(
    r"(?P<code>`(?P<code_in>[^`\n]+)`)"
    r"|(?P<image>!\[(?P<alt>[^\]\n]*)\]\([^)\n]*\))"
    r"|(?P<link>\[(?P<label>[^\]\n]+)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"\n]*\")?\))"
    r"|(?P<auto><(?P<auto_url>[a-zA-Z][a-zA-Z0-9+.-]*:[^>\s]+)>)"
    r"|(?P<bare>https://[^\s<>()\[\]\"']+[^\s<>()\[\]\"'.,;:!?])"
    r"|(?P<bold>\*\*(?P<bold_in>[^*\n]+?)\*\*|__(?P<bold_in2>[^_\n]+?)__)"
    r"|(?P<italic>\*(?P<it_in>[^*\s][^*\n]*?)\*|(?<![0-9A-Za-z])_(?P<it_in2>[^_\s][^_\n]*?)_(?![0-9A-Za-z]))"
)


def safe_link(url: str) -> bool:
    """Darf dieser Link klickbar sein? Nur vollständige ``https``-Adressen ohne Zugangsdaten."""
    text = str(url or "")
    if not text or len(text) > 2048 or any(char.isspace() or ord(char) < 32 or char in "\"'<>\\`" for char in text):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and parts.username is None and "@" not in parts.netloc


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _anchor(url: str, label: str) -> str:
    if not safe_link(url):
        return label
    return f'<a href="{_escape(url)}">{label}</a>'


def inline(text: str, depth: int = 0) -> str:
    """Eine Zeile Markdown → sicheres Inline-Markup (maskierter Text, wenige erlaubte Tags)."""
    out: list[str] = []
    position = 0
    for match in _TOKEN.finditer(text):
        out.append(_escape(text[position : match.start()]))
        position = match.end()
        kind = match.lastgroup
        if match.group("code") is not None:
            out.append(f"<code>{_escape(match.group('code_in'))}</code>")
        elif match.group("image") is not None:
            alt = match.group("alt").strip()
            out.append(_escape(f"[Bild: {alt}]" if alt else "[Bild]"))
        elif match.group("link") is not None:
            label = inline(match.group("label"), depth + 1) if depth < 3 else _escape(match.group("label"))
            out.append(_anchor(match.group("href"), label))
        elif match.group("auto") is not None:
            url = match.group("auto_url")
            out.append(_anchor(url, _escape(url)) if safe_link(url) else _escape(match.group("auto")))
        elif match.group("bare") is not None:
            url = match.group("bare")
            out.append(_anchor(url, _escape(url)))
        elif match.group("bold") is not None:
            inner = match.group("bold_in") or match.group("bold_in2") or ""
            out.append(f"<b>{inline(inner, depth + 1) if depth < 3 else _escape(inner)}</b>")
        elif match.group("italic") is not None:
            inner = match.group("it_in") or match.group("it_in2") or ""
            out.append(f"<i>{inline(inner, depth + 1) if depth < 3 else _escape(inner)}</i>")
        else:  # pragma: no cover - jede Alternative ist oben behandelt
            out.append(_escape(match.group(kind or 0)))
    out.append(_escape(text[position:]))
    return "".join(out)


def render(markdown: str) -> list[dict]:
    """Markdown → Blöcke ``{"kind", "level", "marker", "html"}`` für die Oberfläche.

    ``kind``: ``heading`` (``level`` 1–6), ``paragraph``, ``bullet`` (``level`` 0/1, ``marker``
    »•« oder »1.«), ``quote``, ``code`` und ``rule``.
    """
    text = _COMMENT.sub("", str(markdown or "")[:MAX_TEXT]).replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    blocks: list[dict] = []
    paragraph: list[str] = []
    bullet: dict | None = None
    bullet_lines: list[str] = []
    code: list[str] | None = None

    def flush() -> None:
        nonlocal bullet, bullet_lines
        if paragraph:
            blocks.append({"kind": "paragraph", "level": 0, "marker": "", "html": inline(" ".join(paragraph))})
            paragraph.clear()
        if bullet is not None:
            bullet["html"] = inline(" ".join(bullet_lines))
            blocks.append(bullet)
            bullet, bullet_lines = None, []

    for raw in text.split("\n"):
        line = raw.rstrip()
        if code is not None:
            if _FENCE.match(line):
                blocks.append({"kind": "code", "level": 0, "marker": "", "html": "<br>".join(_escape(part) for part in code)})
                code = None
            else:
                code.append(line)
            continue
        if _FENCE.match(line):
            flush()
            code = []
            continue
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        heading = _HEADING.match(stripped)
        if heading and not line.startswith("    "):
            flush()
            blocks.append({"kind": "heading", "level": len(heading.group(1)), "marker": "", "html": inline(heading.group(2))})
            continue
        if _RULE.match(stripped):
            flush()
            blocks.append({"kind": "rule", "level": 0, "marker": "", "html": ""})
            continue
        item = _BULLET.match(line)
        if item:
            flush()
            indent = len(item.group("indent"))
            marker = item.group("marker")
            bullet = {"kind": "bullet", "level": 1 if indent >= 2 else 0, "marker": "•" if marker in "-*+" else marker.rstrip(")").rstrip(".") + ".", "html": ""}
            bullet_lines = [item.group("text").strip()]
            continue
        if stripped.startswith(">"):
            flush()
            blocks.append({"kind": "quote", "level": 0, "marker": "", "html": inline(stripped.lstrip(">").strip())})
            continue
        if bullet is not None and line.startswith(" "):
            bullet_lines.append(stripped)  # Fortsetzung des Aufzählungspunkts
            continue
        if bullet is not None:
            flush()
        paragraph.append(stripped)
        if len(blocks) >= MAX_BLOCKS:
            break
    if code is not None:
        blocks.append({"kind": "code", "level": 0, "marker": "", "html": "<br>".join(_escape(part) for part in code)})
    flush()
    return blocks[:MAX_BLOCKS]


def plain(markdown: str, limit: int = 280) -> str:
    """Kurzfassung als reiner Text (z. B. für Barrierefreiheit oder ein Protokoll)."""
    text = re.sub(r"<[^>]+>", "", " ".join(block["html"] for block in render(markdown) if block["kind"] != "rule"))
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
