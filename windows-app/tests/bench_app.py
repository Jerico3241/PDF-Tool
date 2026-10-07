"""Messung der App mit Oberfläche: Start, PDF öffnen, Seiten- und Tabwechsel, Miniaturen, Suche,
Speichern, Reparatur und Arbeitsspeicher.

    python windows-app/tests/bench_app.py [--runs 5] [--app ORDNER] [--json DATEI] [start oeffnen_mit reader stapel repair]

Jeder Durchgang läuft in einem eigenen Prozess – der Programmstart wie beim Anwender, nur der
Dateicache des Systems ist warm. Die PDFs sind künstlich (``editorsamples``, ``pdfsamples``) und
liegen in einem temporären Ordner; Einstellungen und Datenordner sind eigene (``UE_CONFIG_FILE``,
``UE_DATA_DIR``), die automatische Update-Prüfung ist aus – kein Netzwerk, nichts aus dem echten
Datenordner. ``--app`` misst einen anderen Stand (z. B. die Vorversion, ``…/windows-app/app``) mit
denselben Messungen; verglichen werden nur Läufe auf demselben Rechner.

Zeitpunkte der Oberfläche kommen aus Signalen der QML-Elemente (»Seite sichtbar«: das Seitenbild
meldet ``ready`` – ``PageImage``), nicht aus einem Durchsuchen des Elementbaums in jedem Schritt: Python-
Code in der Warteschleife hielte sonst den GIL und bremste den Bild-Thread von Qt aus (das verfälschte
eine frühere Fassung dieser Messung um rund 150 ms je Seitenbild). Gesucht wird nur selten und nur in
der Reader-Ansicht und den Miniaturen. Ausgabe: Markdown-Tabelle mit Median, kleinstem und größtem Wert
(ms bzw. MB). Kein Test – Ergebnisse hängen vom Rechner ab.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLL_MS = 5

# Messgrößen in der Reihenfolge der Tabelle: Schlüssel → (Bereich, Beschreibung, Einheit)
METRICS = {
    "start.imports": ("Start", "Python und Module geladen", "ms"),
    "start.controller": ("Start", "Controller bereit", "ms"),
    "start.qml": ("Start", "Oberfläche (QML) geladen", "ms"),
    "start.erstes_bild": ("Start", "Fenster sichtbar (erstes Bild)", "ms"),
    "start.startseite": ("Start", "Startseite vollständig eingeblendet", "ms"),
    "start.alle_seiten": ("Start", "alle Seiten im Hintergrund geladen", "ms"),
    "start.rss": ("Start", "Arbeitsspeicher nach dem Start (Hintergrundarbeit fertig)", "MB"),
    "oeffnen_mit.erstes_bild": ("Öffnen mit", "Start mit PDF: Fenster sichtbar (erstes Bild)", "ms"),
    "oeffnen_mit.reader": ("Öffnen mit", "Start mit PDF: Reader vollständig eingeblendet", "ms"),
    "oeffnen_mit.seite": ("Öffnen mit", "Start mit PDF: erste Seite sichtbar", "ms"),
    "reader.zum_reader": ("Reader", "Wechsel zum Reader direkt nach dem Start", "ms"),
    "reader.klein": ("Reader", "kleine PDF (1 Seite) öffnen → Seite sichtbar", "ms"),
    "reader.gross": ("Reader", "große PDF (500 Seiten) öffnen → Seite sichtbar", "ms"),
    "reader.miniaturen": ("Reader", "große PDF: sichtbare Miniaturen fertig", "ms"),
    "reader.scan": ("Reader", "Scan-PDF (20 Seiten, Bilder) öffnen → Seite sichtbar", "ms"),
    "reader.tabwechsel": ("Reader", "Tabwechsel → Seite sichtbar (Median)", "ms"),
    "reader.seitenwechsel": ("Reader", "Sprung zu einer fernen Seite → sichtbar (Median)", "ms"),
    "reader.zoom": ("Reader", "Zoom 100 % → 200 % → Seite scharf", "ms"),
    "reader.suche": ("Reader", "Suche in 500 Seiten bis zum Ende", "ms"),
    "reader.speichern_klein": ("Reader", "kleine PDF drehen und speichern (mit Prüfung)", "ms"),
    "reader.speichern_gross": ("Reader", "große PDF drehen und speichern (mit Prüfung)", "ms"),
    "reader.rss_offen": ("Reader", "Arbeitsspeicher mit 3 offenen PDFs", "MB"),
    "reader.rss_zu": ("Reader", "Arbeitsspeicher nach dem Schließen aller PDFs", "MB"),
    "reader.rss_zyklen": ("Reader", "Arbeitsspeicher nach 5× Öffnen/Schließen", "MB"),
    "reader.cache_zu": ("Reader", "Seitenbilder im Zwischenspeicher nach dem Schließen", "MB"),
    "stapel.eine": ("PDF reparieren", "eine beschädigte PDF hinzufügen → analysiert (Oberfläche)", "ms"),
    "stapel.analyse": ("PDF reparieren", "20 weitere beschädigte PDFs hinzufügen → alle analysiert", "ms"),
    "stapel.reparatur": ("PDF reparieren", "»Alle reparieren«: 21 PDFs repariert und gespeichert", "ms"),
    "repair.gesund": ("Reparatur", "Analyse + Reparatur 300 Seiten mit Bildern", "ms"),
    "repair.xref": ("Reparatur", "Analyse + Reparatur zerstörte xref-Tabelle", "ms"),
    "repair.abgeschnitten": ("Reparatur", "Analyse + Reparatur abgeschnittene PDF (300 Seiten)", "ms"),
}


# --- Elternprozess ----------------------------------------------------------------------------------
def make_samples(folder: Path) -> dict[str, str]:
    sys.path.insert(0, str(HERE))
    import editorsamples
    import pdfsamples

    files = {
        "klein": editorsamples.standard_text(folder / "klein.pdf"),
        "gross": editorsamples.big(folder / "gross.pdf", pages=500),
        "scan": scan_pdf(folder / "scan.pdf", pages=20),
        "gesund": pdfsamples.large(folder / "gesund.pdf", pages=300),
        "xref": pdfsamples.xref_garbage(pdfsamples.healthy(folder / "xref.pdf", pages=50, image=True)),
        "abgeschnitten": pdfsamples.truncated(pdfsamples.large(folder / "abgeschnitten.pdf", pages=300)),
        "stapel": damaged_folder(folder / "stapel", 21),
    }
    return {key: str(path) for key, path in files.items()}


def damaged_folder(folder: Path, count: int) -> Path:
    """``count`` kleine PDFs mit zerstörter Querverweistabelle (reparierbar), je 3 Seiten."""
    import pdfsamples

    folder.mkdir(parents=True, exist_ok=True)
    for number in range(1, count + 1):
        path = folder / f"Datei {number:02}.pdf"
        pdfsamples.xref_garbage(path)
        path.with_name("_quelle_" + path.name).unlink()  # gesunde Vorlage nicht mit in den Ordner
    return folder


def scan_pdf(path: Path, pages: int) -> Path:
    """Seiten wie aus einem Scanner: je Seite ein Graustufenbild (A4, 200 dpi, JPEG) ohne Text."""
    import io
    import random

    import pikepdf
    from PIL import Image, ImageDraw

    pdf = pikepdf.new()
    rnd = random.Random(4711)
    for number in range(pages):
        image = Image.new("L", (1654, 2339), 245)
        draw = ImageDraw.Draw(image)
        for line in range(60):
            y = 120 + line * 36
            x = 140
            while x < 1500:
                width = rnd.randint(20, 120)
                draw.rectangle((x, y, x + width, y + 18), fill=rnd.randint(20, 80))
                x += width + rnd.randint(12, 30)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=70)
        stream = pikepdf.Stream(pdf, buffer.getvalue())
        stream.Type, stream.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        stream.Width, stream.Height, stream.ColorSpace, stream.BitsPerComponent = 1654, 2339, pikepdf.Name.DeviceGray, 8
        stream.Filter = pikepdf.Name.DCTDecode
        page = pdf.add_blank_page(page_size=(595, 842))
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=stream))
        page.Contents = pdf.make_stream(b"q 595 0 0 842 0 0 cm /Im0 Do Q")
        del number
    pdf.save(path)
    return path


def run_child(scenario: str, app: Path, samples: dict, timeout: float) -> dict:
    work = Path(tempfile.mkdtemp(prefix="bench-"))
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["BENCH_T0"] = repr(time.time())
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", scenario, "--app", str(app), "--work", str(work), "--samples", json.dumps(samples)],
        env=env, capture_output=True, text=True, timeout=timeout,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("BENCH "):
            return json.loads(line[6:])
    raise RuntimeError(f"Messung »{scenario}« ohne Ergebnis (Code {proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")


def table(results: dict[str, list[float]], label: str) -> str:
    lines = [f"| Bereich | Messung | {label} Median | min | max | Läufe |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for key, (area, text, unit) in METRICS.items():
        values = results.get(key)
        if not values:
            continue
        fmt = (lambda v: f"{v:.0f} {unit}") if unit == "ms" else (lambda v: f"{v:.0f} {unit}")
        lines.append(f"| {area} | {text} | {fmt(statistics.median(values))} | {fmt(min(values))} | {fmt(max(values))} | {len(values)} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("scenarios", nargs="*", default=["start", "oeffnen_mit", "reader", "stapel", "repair"])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--app", default=str(HERE.parent / "app"), help="app-Ordner des zu messenden Stands")
    parser.add_argument("--json", help="Rohwerte zusätzlich als JSON speichern")
    parser.add_argument("--label", default="", help="Spaltenname (z. B. die Version)")
    parser.add_argument("--child")
    parser.add_argument("--work")
    parser.add_argument("--samples")
    args = parser.parse_args()
    if args.child:
        return child(args.child, Path(args.app), Path(args.work), json.loads(args.samples))
    app = Path(args.app).resolve()
    sys.path.insert(0, str(app))
    version = (app.parent / "VERSION").read_text(encoding="utf-8").strip() if (app.parent / "VERSION").is_file() else "?"
    folder = Path(tempfile.mkdtemp(prefix="bench-pdfs-"))
    samples = make_samples(folder)
    results: dict[str, list[float]] = {}
    for scenario in args.scenarios:
        for run in range(args.runs):
            values = run_child(scenario, app, samples, timeout=900)
            for key, value in values.items():
                results.setdefault(f"{scenario}.{key}", []).append(value)
            print(f"{scenario} {run + 1}/{args.runs}: " + ", ".join(f"{k} {v:.0f}" for k, v in values.items()), file=sys.stderr, flush=True)
    import platform

    print(f"PDF Tool {version} · Python {platform.python_version()} · {platform.system()} {platform.release()} · {os.cpu_count()} Kerne · Qt-Plattform {os.environ.get('QT_QPA_PLATFORM', 'offscreen')}")
    print()
    print(table(results, args.label or version))
    if args.json:
        Path(args.json).write_text(json.dumps({"version": version, "results": results}, indent=1), encoding="utf-8")
    return 0


# --- Kindprozess ------------------------------------------------------------------------------------
T0 = float(os.environ.get("BENCH_T0") or time.time())


def since_start() -> float:
    return (time.time() - T0) * 1000


def rss_mb() -> float:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / 1024 / 1024
    with open("/proc/self/status", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def prepare(app_dir: Path, work: Path) -> None:
    """Eigene Einstellungen und Datenordner (keine automatische Update-Prüfung), App-Ordner in den Suchpfad."""
    os.environ["UE_DATA_DIR"] = str(work / "daten")
    os.environ["UE_CONFIG_FILE"] = str(work / "daten" / "gui-config.json")
    os.environ["UE_UPDATE_DIR"] = str(work / "updates")
    (work / "daten").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(app_dir))
    import appstate

    Path(os.environ["UE_CONFIG_FILE"]).write_text(json.dumps({"gesehen": appstate.VERSION, "update_automatisch": False, "animationsprofil": os.environ.get("BENCH_MOTION", "full")}), encoding="utf-8")


class App:
    """Die App wie beim echten Start (``qtapp.application.main``), ohne Ereignisschleife zu blockieren."""

    PAGES = ("home", "reader", "create", "layout", "preview", "templates", "rules", "batch", "comparison", "customers", "repair", "settings")

    def __init__(self, app_dir: Path, work: Path, marks: dict | None = None) -> None:
        self.marks = marks if marks is not None else {}
        prepare(app_dir, work)
        from qtapp import application as appmod

        self.mark("imports")
        self.appmod = appmod
        appmod.start_log()
        appmod.prepare_data()
        cfg = appmod.load_config()
        self.qt = appmod.create_application([])
        self.runtime = appmod.Runtime(cfg)
        self.mark("controller")
        self.engine = appmod.create_engine(self.runtime)
        self.mark("qml")
        self.window = appmod.show_window(self.runtime, self.engine)
        self.window.resize(1280, 860)
        self.window.frameSwapped.connect(lambda: self.mark("erstes_bild"))

    def mark(self, name: str) -> None:
        self.marks.setdefault(name, since_start())

    def pump(self, ms: int = POLL_MS) -> None:
        from PySide6.QtCore import QCoreApplication, QEventLoop

        end = time.perf_counter() + ms / 1000
        while time.perf_counter() < end:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 5)
            time.sleep(0.002)

    def wait(self, condition, timeout: float = 120.0) -> float:
        """Millisekunden bis ``condition()`` gilt – ``condition`` muss billig sein (keine Baumsuche)."""
        start = time.perf_counter()
        while not condition():
            if time.perf_counter() - start > timeout:
                raise TimeoutError("Zeitlimit")
            self.pump()
        return (time.perf_counter() - start) * 1000

    def slot(self, key: str):
        """Loader einer Seite (``page_<key>``) – einmal gesucht, danach zwischengespeichert."""
        import shiboken6

        cache = self.__dict__.setdefault("_slots", {})
        found = cache.get(key)
        if found is None or not shiboken6.isValid(found):
            found = self.item(f"page_{key}")
            if found is not None:
                cache[key] = found
        return found

    def items(self, name: str, root=None) -> list:
        found = []
        stack = [root if root is not None else self.window.contentItem()]
        while stack:
            item = stack.pop()
            if item.objectName() == name:
                found.append(item)
            stack.extend(item.childItems())
        return found

    def item(self, name: str, root=None):
        found = self.items(name, root)
        return found[0] if found else None

    def page_shown(self, key: str) -> bool:
        slot = self.slot(key)
        host = slot.parentItem() if slot is not None else None
        return host is not None and host.property("shownKey") == key and not host.property("transitioning") and slot.isVisible() and slot.opacity() > 0.999

    def pages_loaded(self) -> bool:
        for key in self.PAGES:
            if key in self.runtime.app.unavailablePages:
                continue
            slot = self.slot(key)
            if slot is None or slot.property("item") is None:
                return False
        return True

    def close(self) -> None:
        self.runtime.app.shutdown()
        self.appmod.finish_incubation(self.engine)


class ImageWatch:
    """Seitenbilder (``PageImage``) der Reader-Ansicht und der Miniaturen per Signal beobachten.

    ``readyChanged`` liefert den Zeitpunkt, zu dem ein Bild einer Quelle fertig dasteht. Neue Elemente
    (wiederverwendete Plätze sind schon verbunden) sucht ``scan`` – selten (alle 25 ms) und nur bis zu
    einer geringen Tiefe unterhalb von »readerView« und »readerThumbnails«."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.seen: set[int] = set()
        self.items: list = []  # beobachtete Seitenbilder
        self.events: list[tuple[float, str]] = []
        self.roots: dict = {}
        self.last = 0.0

    def _root(self, name: str):
        import shiboken6

        item = self.roots.get(name)
        if item is None or not shiboken6.isValid(item):
            item = self.app.item(name)
            if item is not None:
                self.roots[name] = item
        return item

    def scan(self, force: bool = False) -> None:
        import shiboken6

        now = time.perf_counter()
        if not force and now - self.last < 0.025:
            return
        self.last = now
        for name, depth in (("readerView", 5), ("readerThumbnails", 5)):
            root = self._root(name)
            if root is None:
                continue
            stack = [(root, 0)]
            while stack:
                item, level = stack.pop()
                if item.property("readyPage") is not None and item.property("ready") is not None:
                    key = shiboken6.getCppPointer(item)[0]
                    if key not in self.seen:
                        self.seen.add(key)
                        self.items.append(item)
                        item.readyChanged.connect(lambda it=item: self._changed(it))
                        if item.property("ready"):
                            self.events.append((now, str(item.property("source").toString())))
                    continue
                if level < depth:
                    stack.extend((child, level + 1) for child in item.childItems())

    def _changed(self, item) -> None:
        if item.property("ready") and item.isVisible():
            self.events.append((time.perf_counter(), str(item.property("source").toString())))

    def when(self, since: float, doc: str, page: int, thumb: bool = False, other_than: str = "") -> float | None:
        prefix = f"image://pdfpage/{doc}/{page}/"
        for at, source in reversed(self.events):
            if at < since:
                break
            if source.startswith(prefix) and source.endswith("/thumb") == thumb and source != other_than:
                return at
        return None

    def latest(self, doc: str, page: int) -> str:
        """Zuletzt fertige Quelle des Seitenbilds (ohne Miniatur)."""
        prefix = f"image://pdfpage/{doc}/{page}/"
        for _at, source in reversed(self.events):
            if source.startswith(prefix) and not source.endswith("/thumb"):
                return source
        return ""

    def shown_now(self, doc: str, page: int, thumb: bool, other_than: str) -> bool:
        """Steht ein fertiges Bild der Seite jetzt sichtbar da? (Es kann fertig geworden sein, bevor seine
        Seite sichtbar wurde – z. B. beim Start mit einer PDF.)"""
        import shiboken6

        prefix = f"image://pdfpage/{doc}/{page}/"
        for item in self.items:
            if not shiboken6.isValid(item) or not item.property("ready") or not item.isVisible():
                continue
            source = str(item.property("source").toString())
            if source.startswith(prefix) and source.endswith("/thumb") == thumb and source != other_than:
                return True
        return False

    def wait_page(self, since: float, doc: str, page: int, thumb: bool = False, timeout: float = 60.0, other_than: str = "") -> float:
        """Millisekunden von ``since`` bis das Bild der Seite (bzw. ihre Miniatur) fertig dasteht."""
        while True:
            self.scan()
            at = self.when(since, doc, page, thumb, other_than)
            if at is None and self.shown_now(doc, page, thumb, other_than):
                at = time.perf_counter()
            if at is not None:
                return (at - since) * 1000
            if time.perf_counter() - since > timeout:
                raise TimeoutError(f"Seite {page + 1} von {doc}")
            self.app.pump()


def child(scenario: str, app_dir: Path, work: Path, samples: dict) -> int:
    if scenario == "start":
        values = child_start(app_dir, work)
    elif scenario == "oeffnen_mit":
        values = child_open_with(app_dir, work, samples)
    elif scenario == "reader":
        values = child_reader(app_dir, work, samples)
    elif scenario == "repair":
        values = child_repair(app_dir, work, samples)
    elif scenario == "stapel":
        values = child_batch_repair(app_dir, work, samples)
    else:
        raise SystemExit(f"unbekannte Messung: {scenario}")
    print("BENCH " + json.dumps(values), flush=True)
    os._exit(0)


def child_start(app_dir: Path, work: Path) -> dict:
    marks: dict = {}
    app = App(app_dir, work, marks)
    app.wait(lambda: "erstes_bild" in marks and app.runtime.app.ready and app.page_shown("home"), 60)
    app.mark("startseite")
    app.wait(app.pages_loaded, 120)
    app.mark("alle_seiten")
    app.wait(lambda: app.runtime.reader.controller.engine.idle(), 60)  # Vorarbeit im Arbeitsthread fertig
    marks["rss"] = rss_mb()
    app.close()
    return {key: round(value, 1) for key, value in marks.items() if key != "python"}


def child_open_with(app_dir: Path, work: Path, samples: dict) -> dict:
    """»Öffnen mit« bzw. Doppelklick auf eine PDF: der echte Programmstart (``main``) mit einer PDF in der
    Befehlszeile. Statt der Ereignisschleife läuft die Messung; danach beendet ``main`` die App wie sonst."""
    marks: dict = {}
    prepare(app_dir, work)
    from qtapp import application as appmod

    app = App.__new__(App)  # nur die Hilfen (warten, suchen) – gestartet wird über main
    app.marks = marks
    app.mark("imports")
    path = samples["klein"]
    perf_zero = time.perf_counter() - since_start() / 1000  # perf_counter beim Prozessstart

    class Runtime(appmod.Runtime):
        def __init__(self, cfg) -> None:
            super().__init__(cfg)
            app.runtime = self

    real_show = appmod.show_window

    def show_window(runtime, engine):
        window = real_show(runtime, engine)
        window.resize(1280, 860)
        window.frameSwapped.connect(lambda: app.mark("erstes_bild"))
        app.window = window
        return window

    class Application:
        """QApplication mit der Messung an Stelle der Ereignisschleife."""

        def __init__(self, qt) -> None:
            self._qt = qt

        def __getattr__(self, name):
            return getattr(self._qt, name)

        def exec(self) -> int:
            reader = app.runtime.reader.controller
            watch = ImageWatch(app)
            app.wait(lambda: (watch.scan(), reader.current is not None and bool(reader.current.path) and Path(reader.current.path) == Path(path))[1], 60)
            marks["seite"] = watch.wait_page(perf_zero, reader.current.ident, reader.current.currentPage)
            app.wait(lambda: app.page_shown("reader"), 60)
            app.mark("reader")
            return 0

    real_create = appmod.create_application
    appmod.Runtime = Runtime
    appmod.show_window = show_window
    appmod.create_application = lambda argv=None: Application(real_create(argv))
    appmod.main(["PDF-Tool", path])
    return {key: round(value, 1) for key, value in marks.items() if key in ("erstes_bild", "reader", "seite")}


def child_reader(app_dir: Path, work: Path, samples: dict) -> dict:
    values: dict = {}
    app = App(app_dir, work)
    app.wait(lambda: app.runtime.app.ready and app.page_shown("home"), 60)
    reader = app.runtime.reader.controller
    # Wechsel zum Reader direkt nach dem Start (die Seite lädt evtl. noch im Hintergrund)
    app.runtime.app.dialogs.shutdown()
    app.slot("reader")  # Loader vorher suchen – nicht in der Messung
    start = time.perf_counter()
    app.runtime.app.navigate("reader")
    app.wait(lambda: app.page_shown("reader"), 60)
    values["zum_reader"] = (time.perf_counter() - start) * 1000
    app.wait(app.pages_loaded, 120)  # ab hier ohne Hintergrundaufbau der übrigen Seiten …
    app.wait(lambda: reader.engine.idle(), 60)  # … und ohne Vorarbeit im Arbeitsthread (Aufräumen, Vorladen)
    watch = ImageWatch(app)
    watch.scan(force=True)

    def open_timed(path: str) -> float:
        before = reader.tabs.count
        start = time.perf_counter()
        reader.open_paths([path])
        app.wait(lambda: reader.tabs.count == before + 1 and reader.current is not None and reader.current.path and Path(reader.current.path) == Path(path), 60)
        return watch.wait_page(start, reader.current.ident, reader.current.currentPage)

    def idle() -> None:
        app.wait(lambda: reader.engine.idle() and reader.opening == 0 and (reader.current is None or not reader.current.busy), 120)
        app.pump(150)
        watch.scan(force=True)

    values["klein"] = open_timed(samples["klein"])
    idle()
    start = time.perf_counter()
    values["gross"] = open_timed(samples["gross"])
    big = reader.current
    if reader.leftPanel == "thumbs":
        # sichtbare Miniaturen: die ersten Seiten (die Leiste zeigt bei 860 px Fensterhöhe mindestens vier)
        values["miniaturen"] = max(watch.wait_page(start, big.ident, page, thumb=True) for page in range(4))
    idle()
    values["scan"] = open_timed(samples["scan"])
    idle()
    scan = reader.current
    switches = []
    for _ in range(3):
        for doc in (big, scan):
            start = time.perf_counter()
            reader.activate(doc.ident)
            switches.append(watch.wait_page(start, doc.ident, doc.currentPage))
            idle()
    values["tabwechsel"] = statistics.median(switches)
    reader.activate(big.ident)
    idle()
    jumps = []
    for target in (250, 499, 120, 380, 10):
        start = time.perf_counter()
        big.goTo(target)
        jumps.append(watch.wait_page(start, big.ident, target))
        idle()
    values["seitenwechsel"] = statistics.median(jumps)
    big.setZoom(100)
    idle()
    before = watch.latest(big.ident, big.currentPage)
    start = time.perf_counter()
    big.setZoom(200)
    # scharf: das Seitenbild in der neuen Breite (die Quelle enthält die Breite in Pixeln)
    values["zoom"] = watch.wait_page(start, big.ident, big.currentPage, other_than=before)
    idle()
    start = time.perf_counter()
    big.search("SuchwortTreffer", False, False)
    app.wait(lambda: not big.searchRunning, 300)
    values["suche"] = (time.perf_counter() - start) * 1000
    idle()
    values["rss_offen"] = rss_mb()

    def save_timed(document, target: Path) -> float:
        document.rotatePages([0], 90)
        app.wait(lambda: document.dirty, 60)
        idle()
        start = time.perf_counter()
        document.save(str(target))
        app.wait(lambda: not document.saving and document.saveState in ("saved", ""), 300)
        if document.dirty:
            raise RuntimeError("Speichern fehlgeschlagen")
        return (time.perf_counter() - start) * 1000

    values["speichern_gross"] = save_timed(big, work / "gross-gespeichert.pdf")
    idle()
    small = next((doc for doc in reader._docs.values() if doc.path and Path(doc.path).name == "klein.pdf"), None)
    if small is not None:
        reader.activate(small.ident)
        idle()
        values["speichern_klein"] = save_timed(small, work / "klein-gespeichert.pdf")
        idle()
    close_all(app, reader)
    values["rss_zu"] = rss_mb()
    values["cache_zu"] = reader.cache.bytes / 1024 / 1024
    for _ in range(5):
        for path in (samples["gross"], samples["scan"]):
            open_timed(path)
            idle()
        close_all(app, reader)
    values["rss_zyklen"] = rss_mb()
    app.close()
    return {key: round(value, 1) for key, value in values.items()}


def close_all(app: App, reader) -> None:
    import gc

    for key in list(reader._docs):
        reader.closeTab(key)  # wie per Klick auf »Schließen« (``close_all`` beendet den Arbeitsthread)
    app.wait(lambda: reader.tabs.count == 0, 60)
    app.pump(300)
    gc.collect()
    app.pump(200)


def child_batch_repair(app_dir: Path, work: Path, samples: dict) -> dict:
    """»PDF reparieren« mit der Oberfläche – Arbeitsprozesse wie beim Anwender (je Datei eine Analyse,
    beim Reparieren eine Reparatur). Die PDFs liegen in einer eigenen Kopie (die Ausgaben entstehen daneben)."""
    import shutil

    values: dict = {}
    app = App(app_dir, work)
    app.wait(lambda: app.runtime.app.ready and app.page_shown("home"), 60)
    app.runtime.app.dialogs.shutdown()
    app.wait(app.pages_loaded, 120)
    app.runtime.app.navigate("repair")
    app.wait(lambda: app.page_shown("repair"), 60)
    app.pump(1000)  # was beim Öffnen der Seite im Hintergrund vorbereitet wird, darf fertig werden
    repair = app.runtime.repair.controller
    folder = work / "stapel"
    shutil.copytree(samples["stapel"], folder)
    files = sorted(folder.glob("*.pdf"))

    def idle() -> bool:
        return not repair.busy and not repair.running

    start = time.perf_counter()
    repair.use(str(files[0]))
    app.wait(lambda: idle() and all(item.analysis is not None for item in repair.batch.items), 120)
    values["eine"] = round((time.perf_counter() - start) * 1000, 1)
    start = time.perf_counter()
    repair.add([str(path) for path in files[1:]])
    app.wait(lambda: idle() and len(repair.batch.items) == len(files) and all(item.analysis is not None for item in repair.batch.items), 300)
    values["analyse"] = round((time.perf_counter() - start) * 1000, 1)
    start = time.perf_counter()
    repair.startRepair()
    app.wait(lambda: idle() and all(item.output is not None for item in repair.batch.items), 600)
    values["reparatur"] = round((time.perf_counter() - start) * 1000, 1)
    app.close()
    return values


def child_repair(app_dir: Path, work: Path, samples: dict) -> dict:
    sys.path.insert(0, str(app_dir))
    from tools.pdf_repair import engine
    from tools.pdf_repair.models import RepairMode

    values = {}
    for key in ("gesund", "xref", "abgeschnitten"):
        folder = work / key
        folder.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        analysis = engine.analyze(samples[key])
        engine.repair(samples[key], folder, None, RepairMode.AUTO, analysis.sha256)
        values[key] = round((time.perf_counter() - start) * 1000, 1)
    return values


if __name__ == "__main__":
    sys.exit(main())
