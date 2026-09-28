"""Prüft eine eingebettete bzw. installierte Python-Laufzeit der App – ohne zusätzliche Pakete.

Aufruf mit der zu prüfenden Laufzeit (nicht mit einem System-Python):

    build\\payload\\runtime\\python.exe -s windows-app\\tests\\smoke_runtime.py --app build\\payload\\app
    %LOCALAPPDATA%\\Uebersichten-Ersteller\\runtime\\python.exe -s smoke_runtime.py --app ...\\app --ui

Geprüft wird:
1. Import aller Laufzeitmodule (tkinter, numpy, pandas, openpyxl, xlrd, reportlab, PIL)
   und der App-Module (engine, vertragdesk, excelstyle, richtext, pdffonts)
2. eine echte PDF: Excel mit fett formatierter Zelle und formatierter Fußzeile
3. mit ``--ui``: Programmstart (Hauptfenster erscheint, Einstellungen werden gespeichert)

Endet mit Code 0 und »OK«, sonst mit einer Fehlermeldung und Code 1.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FEHLER: {message}")


def main() -> int:
    # Windows-Konsole (cp1252): nicht darstellbare Zeichen ersetzen statt abzubrechen
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--app", required=True, help="app-Ordner der zu prüfenden Installation bzw. des Pakets")
    parser.add_argument("--ui", action="store_true", help="zusätzlich das Hauptfenster starten und schließen")
    args = parser.parse_args()

    app_dir = Path(args.app).resolve()
    check((app_dir / "vertragdesk.py").is_file(), f"App-Ordner nicht gefunden: {app_dir}")
    print(f"Python {sys.version.split()[0]} · {sys.executable}")
    check(Path(sys.executable).resolve().parent.name.lower() == "runtime", "Prüfung muss mit der eingebetteten Laufzeit laufen (runtime\\python.exe)")

    work = Path(tempfile.mkdtemp(prefix="ue-smoke-"))
    # Einstellungen der Prüfung in einem eigenen Ordner (vor dem Import von appstate setzen)
    os.environ["UE_DATA_DIR"] = str(work / "daten")
    os.environ["UE_NO_ANIMATIONS"] = "1"
    sys.path.insert(0, str(app_dir))

    # 1. Module
    import tkinter
    import numpy
    import openpyxl
    import pandas
    import PIL
    import reportlab
    import xlrd

    print(f"tkinter {tkinter.TkVersion} · numpy {numpy.__version__} · pandas {pandas.__version__} · openpyxl {openpyxl.__version__} · xlrd {xlrd.__version__} · reportlab {reportlab.Version} · Pillow {PIL.__version__}")
    import engine
    import excelstyle
    import pdffonts
    import richtext
    import vertragdesk

    print(f"App {vertragdesk.VERSION} · Schriften: {', '.join(pdffonts.available_families())}")

    # 2. PDF mit Excel-Fettschrift und formatierter Fußzeile
    from datetime import datetime

    from openpyxl.styles import Font

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Vertrag-Nr.", "Beginnt am", "Abrechnungszyklus", "Netto [€]", "Zahlungsart", "Bemerkung", "Rechnungsempfänger Email", "Anwenderstatus"])
    sheet.append(["V-2", datetime(2022, 1, 1), "jährlich", 20.0, "Sofort", "Beta", "a@b.de", "Aktiv"])
    sheet.append(["V-1", datetime(2021, 1, 1), "monatlich", 10.0, "Lastschr", "Alpha", "a@b.de", "Aktiv"])
    sheet["D2"].font = Font(bold=True)
    excel = work / "probe.xlsx"
    book.save(excel)
    check(engine.pruefe_excel(excel)["fett"] == 1, "Fettschrift in der Excel nicht erkannt")
    style = richtext.FOOTER_STYLE
    text = "Kundennummer: {kd}"
    styles = [style] * 14 + [style.with_(bold=True, color="#B51F1F")] * 4
    fuss = richtext.RichText(text, styles, None, style, "center")
    logo = app_dir.parent / "assets" / "hott_logo_final.png"
    pdf = engine.erstelle_pdf(
        engine.PdfAuftrag(excel=excel, logo=logo, kundennummer="4711", zielordner=work, fusszeile=fuss.text, fusszeile_format=fuss.to_dict())
    )
    data = pdf.read_bytes()
    check(data.startswith(b"%PDF") and len(data) > 5000, "PDF fehlt oder ist leer")
    check(b"Helvetica-Bold" in data, "keine fette Schrift in der PDF")
    print(f"PDF: {pdf.name} ({len(data)} Bytes)")
    check(excelstyle.SOURCE_ROW == "_source_excel_row", "Quellzeilen-Spalte unerwartet")

    # 3. Programmstart
    if args.ui:
        from ui import dialogs

        dialogs.AUTO_ANSWER = "primary"  # z. B. »Neu in Version« schließt sich selbst
        started = time.monotonic()
        app = vertragdesk.App()
        shown = {}

        def probe() -> None:
            shown["mapped"] = bool(app.winfo_ismapped())
            shown["page"] = app.nav.current
            app._on_close()

        app.after(3000, probe)
        app.mainloop()
        check(shown.get("mapped") is True, "Hauptfenster wurde nicht angezeigt")
        check(shown.get("page") == "create", "Startseite fehlt")
        config = Path(os.environ["UE_DATA_DIR"]) / "gui-config.json"
        check(config.is_file(), "Einstellungen wurden beim Beenden nicht gespeichert")
        print(f"Programmstart: Fenster sichtbar, beendet nach {time.monotonic() - started:.1f} s")

    print("OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
