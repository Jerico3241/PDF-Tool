"""Blitzvorschau (Strg+E, seit 5.0 Beta 5): aus ein paar Beispielen in einer Spalte das Muster erkennen und die übrigen
Zeilen ausfüllen – wie in Excel, z. B. Vorname aus »Max Müller«, »M. Müller«, die Firma aus einer E-Mail-Adresse oder
nur die Ziffern einer Telefonnummer.

Ein Muster ist eine Folge von Bausteinen: ganze Zelle, ein Wort (von vorn oder hinten gezählt), sein Anfangsbuchstabe,
die Ziffern einer Zelle – jeweils wie geschrieben, GROSS, klein oder mit großem Anfang – und feste Zeichen dazwischen.
Gesucht wird das günstigste Muster, das alle Beispiele ergibt (feste Zeichen sind teuer, damit Bausteine gewinnen).
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache

WORD = re.compile(r"[^\W_]+")
LITERAL_COST = 10.0
MAX_TARGET = 200  # längere Beispiele: kein Muster suchen
MAX_WORDS = 12
CASES = ("same", "upper", "lower", "title")


class NoPattern(Exception):
    """Aus den Beispielen ließ sich kein Muster erkennen."""


def _case(text: str, case: str) -> str:
    if case == "upper":
        return text.upper()
    if case == "lower":
        return text.lower()
    if case == "title":
        return text[:1].upper() + text[1:].lower()
    return text


def _words(text: str) -> list[str]:
    return WORD.findall(text)


def run_token(token: tuple, row: list[str]) -> str:
    kind, col = token[0], token[1]
    if kind == "lit":
        return token[1]
    text = row[col].strip() if col < len(row) else ""
    if kind == "cell":
        return _case(text, token[2])
    if kind == "digits":
        return "".join(char for char in text if char.isdigit())
    words = _words(text)
    index = token[2]
    if not -len(words) <= index < len(words):
        return ""
    word = words[index]
    if kind == "word":
        return _case(word, token[3])
    if kind == "initial":
        return _case(word[:1], token[3])
    return ""


def run(program: list[tuple], row: list[str]) -> str:
    return "".join(run_token(token, row) for token in program)


def _cost(token: tuple) -> float:
    kind = token[0]
    extra = 0.0 if kind in ("lit", "digits") or token[-1] == "same" else 0.5  # wie geschrieben bevorzugt
    if kind == "cell":
        return 0.0 + extra
    if kind == "word":
        # erstes und letztes Wort am günstigsten; sonst lieber von hinten gezählt (die Firma in »max.m@firma.de«)
        return (1.0 if token[2] in (0, -1) else 1.9 if token[2] < 0 else 2.0) + extra
    if kind == "initial":
        return (2.0 if token[2] in (0, -1) else 3.0) + extra
    if kind == "digits":
        return 2.0
    return LITERAL_COST


def _tokens(row: list[str], sources: list[int]) -> list[tuple]:
    """Alle Bausteine, die aus dieser Zeile etwas ergeben."""
    tokens: list[tuple] = []
    for col in sources:
        text = row[col].strip() if col < len(row) else ""
        if not text:
            continue
        for case in CASES:
            tokens.append(("cell", col, case))
        words = _words(text)[:MAX_WORDS]
        count = len(words)
        for index in list(range(count)) + list(range(-count, 0)):
            for case in CASES:
                tokens.append(("word", col, index, case))
                tokens.append(("initial", col, index, case))
        if any(char.isdigit() for char in text):
            tokens.append(("digits", col))
    return tokens


def learn(examples: list[tuple[list[str], str]], sources: list[int]) -> list[tuple]:
    """Günstigstes Muster für alle Beispiele (Zeile, gewünschter Text) – ``NoPattern``, wenn keines (nur feste
    Zeichen zählen nicht als Muster)."""
    examples = [(row, target) for row, target in examples if target != ""]
    if not examples or any(len(target) > MAX_TARGET for _row, target in examples):
        raise NoPattern
    first_row = examples[0][0]
    tokens = []
    seen = set()
    for token in _tokens(first_row, sources):
        output = run_token(token, first_row)
        if output and token not in seen:
            seen.add(token)
            tokens.append((token, _cost(token)))
    outputs = [[run_token(token, row) for row, _target in examples] for token, _cost_ in tokens]
    targets = [target for _row, target in examples]
    ends = tuple(len(target) for target in targets)
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, MAX_TARGET * 4 + 100))

    @lru_cache(maxsize=None)
    def best(state: tuple) -> tuple[float, tuple]:
        if state == ends:
            return 0.0, ()
        found = (float("inf"), ())
        for number, (token, cost) in enumerate(tokens):
            nexts = []
            for index, position in enumerate(state):
                output = outputs[number][index]
                if not targets[index].startswith(output, position) or position + len(output) > ends[index]:
                    break
                nexts.append(position + len(output))
            else:
                following = tuple(nexts)
                if following == state:
                    continue  # ergibt nirgends etwas: kein Fortschritt
                rest, program = best(following)
                if cost + rest < found[0]:
                    found = (cost + rest, (token,) + program)
        if all(position < end for position, end in zip(state, ends)):
            char = targets[0][state[0]]
            if all(targets[index][position] == char for index, position in enumerate(state)):
                rest, program = best(tuple(position + 1 for position in state))
                if LITERAL_COST + rest < found[0]:
                    found = (LITERAL_COST + rest, (("lit", char),) + program)
        return found

    try:
        cost, program = best(tuple(0 for _example in examples))
    finally:
        sys.setrecursionlimit(limit)
    if cost == float("inf") or all(token[0] == "lit" for token in program):
        raise NoPattern
    merged: list[tuple] = []
    for token in program:
        if token[0] == "lit" and merged and merged[-1][0] == "lit":
            merged[-1] = ("lit", merged[-1][1] + token[1])
        else:
            merged.append(token)
    return merged


def flash_fill(rows: list[list[str]], target: int) -> list[str | None]:
    """Spalte ``target`` der Tabelle ``rows`` ausfüllen: je Zeile der neue Text bzw. ``None`` (schon gefüllt oder nichts
    daraus abzuleiten). Die erste Zeile gilt als Kopfzeile, wenn es ohne sie ein Muster gibt."""
    width = max((len(row) for row in rows), default=0)
    sources = [col for col in range(width) if col != target]
    examples = [(index, row, row[target].strip() if target < len(row) else "") for index, row in enumerate(rows)]
    examples = [(index, row, text) for index, row, text in examples if text and any(row[col].strip() for col in sources if col < len(row))]
    if not examples:
        raise NoPattern
    attempts = []
    if len(examples) >= 2 and examples[0][0] == 0:
        attempts.append(examples[1:])  # die erste Zeile ist meist die Überschrift
    attempts.append(examples)
    program = None
    for attempt in attempts:
        try:
            program = learn([(row, text) for _index, row, text in attempt], sources)
            break
        except NoPattern:
            continue
    if program is None:
        raise NoPattern
    result: list[str | None] = []
    for row in rows:
        own = row[target].strip() if target < len(row) else ""
        if own or not any(row[col].strip() for col in sources if col < len(row)):
            result.append(None)
            continue
        text = run(program, row)
        result.append(text if text.strip() else None)
    return result
