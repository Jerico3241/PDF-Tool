"""Messung des PDF Readers/Editors mit künstlichen Dokumenten (1, 10, 100, 500, 1000 Seiten).

    python windows-app/tests/bench_editor.py [Seitenzahlen …]

Gemessen wird die Engine ohne Oberfläche, so wie der Arbeitsthread des Readers sie aufruft:
Öffnen, erste Seite zeichnen (1190 px breit ≈ 150 % bei 96 dpi), 20 Miniaturen, Zeichentabelle
einer Seite, Suche im ganzen Dokument, Text direkt ändern und »Speichern unter« mit Prüfung.
Ausgabe: Markdown-Tabelle mit Millisekunden (Median aus drei Läufen) und dem höchsten
Arbeitsspeicher des Prozesses. Kein Test – Ergebnisse hängen vom Rechner ab.
"""

from __future__ import annotations

import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))
sys.path.insert(0, str(HERE))

import editorsamples as samples  # noqa: E402
from tools.pdf_editor import commands, render, save, textedit, textlayer  # noqa: E402
from tools.pdf_editor.document import EditorDocument  # noqa: E402

RUNS = 3


def peak_mb() -> float:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return usage / 1024 if sys.platform != "darwin" else usage / 1024 / 1024
    except ImportError:  # Windows
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakWorkingSetSize / 1024 / 1024


def timed(func) -> float:
    start = time.perf_counter()
    func()
    return (time.perf_counter() - start) * 1000


def measure(pages: int, folder: Path) -> dict:
    source = samples.big(folder / f"bench-{pages}.pdf", pages=pages)
    results: dict[str, list[float]] = {key: [] for key in ("open", "render", "thumbs", "text", "search", "edit", "save")}
    hits = 0
    for run in range(RUNS):
        holder: dict = {}
        results["open"].append(timed(lambda: holder.setdefault("doc", EditorDocument.open(str(source)))))
        doc = holder["doc"]
        try:
            results["render"].append(timed(lambda: render.render_page(doc, 0, 1190)))
            count = min(20, pages)
            results["thumbs"].append(timed(lambda: [render.render_page(doc, index, 120) for index in range(count)]) / count)
            results["text"].append(timed(lambda: textlayer.text(doc, 0, 0, 200)))

            def search() -> None:
                nonlocal hits
                hits = sum(len(textlayer.search(doc, index, "SuchwortTreffer")) for index in range(doc.page_count))

            results["search"].append(timed(search))
            history = commands.History()
            block = next(b for b in textedit.analyze(doc, 0) if "Seite 1 von" in b.text)
            results["edit"].append(timed(lambda: textedit.edit_block(doc, history, block, block.text.replace("Seite 1", "Blatt 1"))))
            target = folder / f"bench-{pages}-gespeichert-{run}.pdf"
            results["save"].append(timed(lambda: save.save(doc, target, backup_dir=folder / "sicherungen")))
        finally:
            doc.close()
    size_in = source.stat().st_size
    size_out = (folder / f"bench-{pages}-gespeichert-0.pdf").stat().st_size
    row = {key: statistics.median(values) for key, values in results.items()}
    row.update(pages=pages, hits=hits, size_in=size_in, size_out=size_out)
    return row


def main(argv: list[str]) -> int:
    counts = [int(value) for value in argv] or [1, 10, 100, 500, 1000]
    print(f"Python {platform.python_version()} · {platform.system()} {platform.release()} · {platform.processor() or platform.machine()} · {os.cpu_count()} Kerne")
    print()
    print("| Seiten | Öffnen | 1. Seite (1190 px) | Miniatur (je) | Zeichentabelle | Suche (alle Seiten) | Text ändern | Speichern + Prüfung | Datei vorher → nachher |")
    print("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    with tempfile.TemporaryDirectory(prefix="pdftool-bench-") as tmp:
        for pages in counts:
            row = measure(pages, Path(tmp))
            print(
                f"| {row['pages']} | {row['open']:.0f} ms | {row['render']:.0f} ms | {row['thumbs']:.1f} ms | {row['text']:.1f} ms | "
                f"{row['search']:.0f} ms ({row['hits']} Treffer) | {row['edit']:.0f} ms | {row['save']:.0f} ms | "
                f"{row['size_in'] / 1024:.0f} → {row['size_out'] / 1024:.0f} KB |",
                flush=True,
            )
    print()
    print(f"Höchster Arbeitsspeicher des Prozesses: {peak_mb():.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
