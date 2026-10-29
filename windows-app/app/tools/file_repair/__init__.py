"""»Dateien reparieren« für andere Dateiarten als PDF (seit 5.0 Beta 7).

* ``engine`` – Analyse und Reparatur von Office-Dateien (ZIP-Formate neu verpacken, ältere Formate über LibreOffice),
  Bildern (lesbaren Teil retten) und Text/CSV (Zeichenkodierung, Steuerzeichen, Zeilenenden).

Ergebnisse sind dieselben Modelle wie bei PDFs (``tools.pdf_repair.models``): Liste, Namen, Arbeitsprozess und
Übernahme der Ausgabe bleiben die des PDF-Werkzeugs.
"""

from .engine import SUFFIXES, handles  # noqa: F401
