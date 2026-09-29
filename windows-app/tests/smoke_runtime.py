"""Prüft eine eingebettete bzw. installierte Python-Laufzeit der App – ohne zusätzliche Pakete.

Aufruf mit der zu prüfenden Laufzeit (nicht mit einem System-Python):

    build\\payload\\runtime\\python.exe -s windows-app\\tests\\smoke_runtime.py --app build\\payload\\app
    %LOCALAPPDATA%\\PDF-Tool\\runtime\\python.exe -s smoke_runtime.py --app ...\\app --ui

Geprüft wird:
1. Import aller Laufzeitmodule (tkinter, numpy, pandas, openpyxl, xlrd, reportlab, PIL,
   pikepdf mit qpdf, pypdfium2 mit PDFium) und der App-Module beider Werkzeuge
2. Vertragsübersichten: eine echte PDF aus einer Excel mit fett formatierter Zelle und
   formatierter Fußzeile; Kundenakte 2.0 (Übernahme einer Kundenhistorie aus 2.3 mit
   Sicherung, Wiedererkennung per E-Mail, Speichern) und Live-Vorschau (PDF im
   Hintergrund erzeugen, Seite mit PDFium zeichnen, temporäre Dateien löschen)
3. PDF reparieren: dieselbe PDF mit beschädigter Querverweistabelle im eigenen
   Arbeitsprozess analysieren und reparieren (wie in der App), Ausgabe prüfen
4. mit ``--ui``: Programmstart (Hauptfenster mit Startseite, Werkzeuge und die Ansichten
   »Vorschau« und »Kunden« öffnen, Einstellungen werden gespeichert)

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

    work = Path(tempfile.mkdtemp(prefix="pdf-tool-smoke-"))
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
    import pikepdf
    import pypdfium2
    import reportlab
    import xlrd

    print(f"tkinter {tkinter.TkVersion} · numpy {numpy.__version__} · pandas {pandas.__version__} · openpyxl {openpyxl.__version__} · xlrd {xlrd.__version__} · reportlab {reportlab.Version} · Pillow {PIL.__version__}")
    print(f"pikepdf {pikepdf.__version__} (qpdf {pikepdf.__libqpdf_version__}) · pypdfium2 {pypdfium2.version.PYPDFIUM_INFO} (PDFium {pypdfium2.version.PDFIUM_INFO})")
    import engine
    import excelstyle
    import pdffonts
    import richtext
    import vertragdesk
    from tools import registry
    from tools.contract_overview import controller, customer_flow, page_customers, page_preview, preview
    from tools.contract_overview.customers import matching, migration, repository
    from tools.pdf_repair import engine as repair_engine
    from tools.pdf_repair import process as repair_process
    from tools.pdf_repair.models import Condition, RepairStatus

    check([tool.key for tool in registry.TOOLS] == ["contracts", "repair"], "Werkzeuge fehlen")
    check(hasattr(controller, "ContractOverviewTool"), "Werkzeug Vertragsübersichten fehlt")
    check(registry.CONTRACTS.pages == ("create", "layout", "preview", "customers"), "Ansichten von Vertragsübersichten fehlen")
    check(hasattr(page_customers, "CustomerPage") and hasattr(page_preview, "PreviewView"), "Ansichten »Kunden« bzw. »Vorschau« fehlen")
    print(f"App {vertragdesk.VERSION} · Schriften: {', '.join(pdffonts.available_families())} · Engines: {repair_engine.engine_name()}")

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

    # Kundenakte 2.0: Kundenhistorie wie aus 2.3 übernehmen (mit Sicherung), wiedererkennen, speichern
    import json

    akten = work / "kundenakten"
    akten.mkdir()
    alt = {
        "gesehen": "2.3.0",
        "kunden": [
            {"firmenname": "Müller & Söhne GmbH", "kundennummer": "0815", "rechnungsempfaenger": "Rechnung@Mueller.de", "fusszeile": fuss.text, "fusszeile_format": fuss.to_dict(), "kopfzeile": ""},
            {"firmenname": "Alt AG", "kundennummer": "1", "rechnungsempfaenger": "", "fusszeile": "", "kopfzeile": ""},
        ],
    }
    alt_datei = akten / "gui-config.json"
    alt_datei.write_text(json.dumps(alt, ensure_ascii=False, indent=2), encoding="utf-8")
    store, report = migration.open_store(akten, alt, alt_datei)
    check(report is not None and report.ok and report.migrated == 2, f"Übernahme der Kundenhistorie: {report}")
    check(report.backup is not None and report.backup.read_bytes() == alt_datei.read_bytes(), "Sicherung vor der Übernahme weicht ab")
    treffer = store.match([" RECHNUNG@mueller.de "])
    check(treffer.kind is matching.MatchKind.SINGLE, f"Wiedererkennung: {treffer.kind.value}")
    kunde = store.get(treffer.customer_id)
    check(customer_flow.footer_of(kunde) == fuss, "Formatierung der Fußzeile ging bei der Übernahme verloren")
    check(customer_flow.footer_of(next(k for k in store.all() if k.number == "1")) is None, "leere Fußzeile aus 2.3 wurde übernommen")
    check(store.match(["rechnung@mueller-gmbh.de"]).kind is matching.MatchKind.NONE, "unbekannte Adresse wurde zugeordnet")
    gespeichert = repository.CustomerStore.load(akten / repository.FILE_NAME)
    check(gespeichert.get(kunde.id) is not None and gespeichert.get(kunde.id).company == "Müller & Söhne GmbH", "Kundenakte nicht dauerhaft gespeichert")
    print(f"Kundenakte: {report.migrated} Kunden übernommen (Sicherung {report.backup.name}), Wiedererkennung: {treffer.kind.value}")

    # Live-Vorschau: dieselbe PDF im Hintergrund erzeugen und die erste Seite mit PDFium zeichnen
    doc = preview.PreviewDocument.build(dict(excel=excel, logo=logo, kundennummer="4711", fusszeile=fuss.text, fusszeile_format=fuss.to_dict()))
    try:
        bild, breite, hoehe = doc.render(0, 1.0)
        check(doc.pages >= 1 and breite > 300 and hoehe > 300 and len(bild) > 1000, "Vorschau ist leer")
    finally:
        doc.close()
    check(not doc.folder.exists(), "Vorschau-Dateien wurden nicht gelöscht")
    print(f"Vorschau: {doc.pages} Seite(n), erste Seite {breite}×{hoehe} Pixel")

    # 3. PDF reparieren – im eigenen Arbeitsprozess wie in der App
    import re

    folder = work / "Übersichten März"
    folder.mkdir()
    damaged = folder / "Vertrag beschädigt.pdf"
    damaged.write_bytes(re.sub(rb"startxref\s+(\d+)", lambda m: b"startxref\n" + str(int(m.group(1)) + 97).encode(), data))
    before = damaged.read_bytes()
    job = repair_process.Job("analyze", {"path": str(damaged), "password": None})
    events = job.wait(120)
    results = [event[1] for event in events if event[0] == "result"]
    check(bool(results), f"Analyse ohne Ergebnis: {events[-1:]}")
    analysis = results[0]
    check(analysis.condition is Condition.REPAIRABLE, f"Analyse: {analysis.condition.value}")
    job = repair_process.Job("repair", {"path": str(damaged), "password": None, "mode": "auto", "sha256": analysis.sha256})
    events = job.wait(120)
    results = [event[1] for event in events if event[0] == "result"]
    check(bool(results), f"Reparatur ohne Ergebnis: {events[-1:]}")
    result = results[0]
    check(result.status is RepairStatus.REPAIRED, f"Reparatur: {result.status.value} {result.error}")
    output = repair_process.deliver(Path(result.output_path), damaged)
    job.cleanup()
    check(output == folder / "Vertrag beschädigt_repariert.pdf", f"Ausgabe: {output}")
    check(damaged.read_bytes() == before, "Original wurde verändert")
    with pikepdf.open(output) as repaired:
        check(len(repaired.pages) == result.pages_before, "Seitenzahl der reparierten PDF stimmt nicht")
    with pypdfium2.PdfDocument(str(output)) as second:
        check(len(second) == result.pages_before, "PDFium liest die reparierte PDF nicht")
    print(f"Reparatur: {output.name} ({result.method.value}, {result.pages_after} Seiten, {output.stat().st_size} Bytes)")

    # 4. Programmstart
    if args.ui:
        from ui import dialogs

        dialogs.AUTO_ANSWER = "primary"  # z. B. »Neu in Version« schließt sich selbst
        started = time.monotonic()
        app = vertragdesk.App()
        shown = {}

        def probe() -> None:
            shown["mapped"] = bool(app.winfo_ismapped())
            shown["page"] = app.nav.current
            shown["title"] = app.title()
            app.open_tool("repair")
            app.update()
            shown["repair"] = app.nav.current
            app.open_tool("contracts")
            app.update()
            shown["contracts"] = app.nav.current
            for view in ("preview", "customers"):
                app.nav.navigate(view)
                app.update()
                shown[view] = app.nav.current
            app._on_close()

        app.after(3000, probe)
        app.mainloop()
        check(shown.get("mapped") is True, "Hauptfenster wurde nicht angezeigt")
        check(shown.get("page") == "home", "Startseite fehlt")
        check(shown.get("title") == "PDF Tool", f"Fenstertitel: {shown.get('title')}")
        check(shown.get("repair") == "repair" and shown.get("contracts") == "create", "Werkzeuge lassen sich nicht öffnen")
        check(shown.get("preview") == "preview" and shown.get("customers") == "customers", "Ansichten »Vorschau« und »Kunden« lassen sich nicht öffnen")
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
