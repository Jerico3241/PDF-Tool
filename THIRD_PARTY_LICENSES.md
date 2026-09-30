# Lizenzen von Drittanbietern

PDF Tool (Windows-App) wird mit einer eingebetteten Python-Laufzeit und den folgenden Paketen
ausgeliefert. Die Versionen und SHA-256-Prüfsummen stehen in
[`windows-app/runtime-requirements.txt`](windows-app/runtime-requirements.txt) bzw. in
[`windows-app/build.py`](windows-app/build.py) (Python). Alle Pakete werden unverändert als
Original-Wheels von PyPI bzw. als Original-Archiv von python.org übernommen.

Die vollständigen Lizenztexte liegen im installierten Programm neben dem jeweiligen Paket:

- Python: `%LOCALAPPDATA%\PDF-Tool\runtime\LICENSE.txt` (enthält auch die Lizenzen der mit Python
  gelieferten Bibliotheken wie OpenSSL, libffi, bzip2, xz, zlib, SQLite, expat, mpdecimal; Tcl/Tk
  gehört seit 2.7.0 nicht mehr zur Laufzeit)
- Pakete: `%LOCALAPPDATA%\PDF-Tool\runtime\Lib\site-packages\<Paket>-<Version>.dist-info\`
  (bei pikepdf zusätzlich `…\pikepdf-10.15.0.dist-info\licenses\third-party-licenses\`, bei
  pypdfium2 `…\pypdfium2-5.13.0.dist-info\licenses\`)

## Laufzeit und Pakete

| Komponente | Version | Lizenz | Verwendet für | Quelle |
| --- | --- | --- | --- | --- |
| Python (Windows, 64 Bit), ohne tkinter/Tcl/Tk | 3.13.15 | PSF-2.0 | Laufzeit | https://www.python.org |
| PySide6-Essentials (Qt for Python) | 6.11.2 | LGPL-3.0-only (alternativ GPL-2.0/GPL-3.0 oder kommerziell) | Oberfläche (Qt Quick/QML), Dateiauswahl, Zwischenablage | https://doc.qt.io/qtforpython-6/ · https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2 |
| ↳ shiboken6 | 6.11.2 | LGPL-3.0-only (alternativ GPL-2.0/GPL-3.0 oder kommerziell) | Python-Bindung von PySide6 | https://pypi.org/project/shiboken6/6.11.2/ |
| ↳ Qt (in PySide6 enthalten: QtCore, QtGui, QtWidgets, QtNetwork, QtOpenGL, QtQml, QtQuick, Qt Quick Controls (nur Stil »Basic«), Qt Quick Templates, Layouts, Shapes, QtSvg; Plugins qwindows, qoffscreen, qico, qjpeg, qsvg, qwebp, qsvgicon) | 6.11.2 | LGPL-3.0-only | Oberfläche | https://download.qt.io/official_releases/qt/6.11/ |
| ↳ Bibliotheken von Qt (u. a. libjpeg-turbo, libwebp, PCRE2, HarfBuzz, FreeType, double-conversion, zlib) | – | BSD-artig / MIT / IJG / FTL / Zlib | Bildformate, Textdarstellung | https://doc.qt.io/qt-6/licenses-used-in-qt.html |
| pikepdf | 10.15.0 | MPL-2.0 | PDF reparieren (Analyse, Neuaufbau) | https://github.com/pikepdf/pikepdf |
| ↳ qpdf (in pikepdf enthalten) | 12.4.1 | Apache-2.0 | PDF-Engine 1 | https://github.com/qpdf/qpdf |
| ↳ libjpeg-turbo, zlib, OpenSSL, Teile von pdfminer.six, sRGB-Farbprofil (in pikepdf enthalten) | – | IJG / BSD-3-Clause / Zlib / Apache-2.0 / MIT | Bilddaten, Verschlüsselung, Farbprofile | `pikepdf-10.15.0.dist-info\licenses\third-party-licenses\` |
| ↳ Microsoft Visual C++ Runtime (msvcp140, in pikepdf, numpy, pandas enthalten) | – | Microsoft Redistributable | C++-Laufzeit | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| pypdfium2 | 5.13.0 | Apache-2.0 oder BSD-3-Clause | PDF reparieren (zweite Engine, Rettungsmodus) | https://github.com/pypdfium2-team/pypdfium2 |
| ↳ PDFium (in pypdfium2 enthalten) | 153.0.7999.0 | BSD-3-Clause | PDF-Engine 2 | https://pdfium.googlesource.com/pdfium |
| ↳ Bibliotheken von PDFium | – | Apache-2.0 (abseil, llvm-libc mit LLVM-Exception), FTL (FreeType), Unicode-3.0 (ICU), MIT (lcms, simdutf), BSD (agg, OpenJPEG, libjpeg-turbo), libpng, libtiff, Zlib, MIT/Apache-2.0 (fast_float) | Schriften, Bilder, Farbprofile | https://github.com/bblanchon/pdfium-binaries |
| pypdf | 6.19.0 | BSD-3-Clause | PDF reparieren (dritte, tolerante Engine der erweiterten Wiederherstellung) | https://github.com/py-pdf/pypdf |
| packaging | 26.3 | Apache-2.0 oder BSD-2-Clause | von pikepdf benötigt | https://github.com/pypa/packaging |
| pandas | 2.3.3 | BSD-3-Clause | Vertragsübersichten (Excel lesen) | https://pandas.pydata.org |
| NumPy | 2.5.3 | BSD-3-Clause (enthält OpenBLAS: BSD-3-Clause, LAPACK: BSD, GCC-Laufzeit: GPL-3.0 mit GCC Runtime Library Exception 3.1) | von pandas benötigt | https://numpy.org |
| python-dateutil | 2.9.0.post0 | Apache-2.0 / BSD-3-Clause | von pandas benötigt | https://github.com/dateutil/dateutil |
| pytz | 2026.3.post1 | MIT | von pandas benötigt | https://pythonhosted.org/pytz |
| tzdata | 2026.4 | Apache-2.0 | von pandas benötigt | https://github.com/python/tzdata |
| six | 1.17.0 | MIT | von python-dateutil benötigt | https://github.com/benjaminp/six |
| openpyxl | 3.1.5 | MIT | Excel (.xlsx) mit Formatierung lesen | https://foss.heptapod.net/openpyxl/openpyxl |
| et-xmlfile | 2.0.0 | MIT | von openpyxl benötigt | https://foss.heptapod.net/openpyxl/et_xmlfile |
| xlrd | 2.0.2 | BSD-3-Clause | Excel (.xls) lesen | https://github.com/python-excel/xlrd |
| ReportLab | 4.5.1 | BSD-3-Clause (enthält Schriften: Bitstream Vera, DarkGarden unter GPL mit Font-Ausnahme) | PDF erzeugen, Rettungsmodus | https://www.reportlab.com |
| charset-normalizer | 3.5.1 | MIT | von ReportLab benötigt | https://github.com/jawah/charset_normalizer |
| Pillow | 12.3.0 | MIT-CMU (enthält brotli, FreeType, HarfBuzz, lcms2, libavif, libjpeg-turbo, libpng, libwebp, OpenJPEG, libtiff, xz, zlib-ng mit ihren Lizenzen) | Bilder, Symbole, Rettungsmodus | https://python-pillow.github.io |

Nicht mitgeliefert: lxml (von pikepdf nur für XMP-Metadaten benötigt – PDF Tool schreibt
Metadaten unverändert und braucht es nicht), qpdf- oder Ghostscript-Programme, Kommandozeilen-
werkzeuge. pypdf wird ohne optionale Zusatzpakete (cryptography, PyCryptodome, fontTools)
ausgeliefert; Verschlüsselung übernimmt weiterhin qpdf. Von PySide6 bleiben nur die Module,
Plugins und QML-Module, die die App lädt (`windows-app/qtruntime.py`): keine Entwicklerwerkzeuge
(Designer, Linguist, qmlls …), keine weiteren Stile, kein Software-OpenGL (`opengl32sw.dll`), keine
Übersetzungen – die Dateien selbst bleiben unverändert (Original-Wheel).

## Geprüfte, aber nicht verwendete Engines (erweiterte PDF-Wiederherstellung, 2.6.0)

Für die dritte, tolerante Engine wurden Lizenz und Eignung geprüft:

| Kandidat | Lizenz | Entscheidung |
| --- | --- | --- |
| **pypdf** | BSD-3-Clause | **verwendet** – freizügig, reines Python ohne Abhängigkeiten, eigene tolerante Leseregeln (`strict=False`) |
| PyMuPDF / MuPDF | AGPL-3.0 (oder kommerzielle Lizenz von Artifex) | abgelehnt – die AGPL würde die Offenlegung von PDF Tool unter AGPL verlangen |
| Ghostscript | AGPL-3.0 (oder kommerzielle Lizenz von Artifex) | abgelehnt – gleiche Lizenzfolgen, zudem ein externes Programm |
| pdf.js | Apache-2.0 | nicht geeignet – braucht eine JavaScript-Laufzeit |

Die Rohrekonstruktion (Objekte suchen, Querverweise, Trailer und Seitenbaum neu aufbauen) ist
eigener Code von PDF Tool; das Ergebnis wird mit qpdf (pikepdf) normalisiert und geprüft.

## Hinweise zu einzelnen Lizenzen

- **PySide6, shiboken6 und Qt (LGPL-3.0):** Seit 2.7.0 ist die Oberfläche eine Qt-Quick-Anwendung
  mit PySide6. PDF Tool verwendet die unveränderten Original-Wheels von PyPI
  (`PySide6_Essentials-6.11.2`, `shiboken6-6.11.2`, Prüfsummen in `runtime-requirements.txt`) unter
  der LGPL-3.0. Qt und PySide6 werden dynamisch geladen: Die Bibliotheken liegen als eigene Dateien
  im Programmordner (`runtime\Lib\site-packages\PySide6\`, `…\shiboken6\`) und lassen sich durch
  eigene, kompatible Fassungen ersetzen; PDF Tool schränkt das weder technisch noch vertraglich ein
  (kein Reverse-Engineering-Verbot, keine Signaturprüfung der Qt-Dateien). Der Quellcode genau
  dieser Versionen ist erhältlich unter https://download.qt.io/official_releases/QtForPython/pyside6/
  (PySide6/shiboken6 6.11.2) und https://download.qt.io/official_releases/qt/6.11/ (Qt 6.11.2).
  Den Text der LGPL-3.0 (und der GPL-3.0, auf die sie verweist) enthält
  https://www.gnu.org/licenses/lgpl-3.0.html bzw. https://www.gnu.org/licenses/gpl-3.0.html.
  **Verträglichkeit:** PDF Tool steht laut Projektinhaber unter **GPL-3.0-or-later**; die LGPL-3.0
  von Qt/PySide6 ist damit vereinbar. Qt-Module unter reiner GPL (z. B. Qt Charts, Qt Data
  Visualization) oder kommerzieller Lizenz werden nicht verwendet.
- **pikepdf (MPL-2.0):** PDF Tool verwendet pikepdf unverändert. Der Quellcode genau dieser
  Version ist unter https://github.com/pikepdf/pikepdf/tree/v10.15.0 und
  https://pypi.org/project/pikepdf/10.15.0/#files erhältlich.
- **FreeType (FTL):** Portions of this software are copyright © The FreeType Project
  (www.freetype.org). All rights reserved.
- **GCC-Laufzeit in NumPy:** GPL-3.0 mit GCC Runtime Library Exception 3.1 – die Ausnahme erlaubt
  die Weitergabe zusammen mit Programmen unter beliebiger Lizenz.
- **Microsoft Visual C++ Runtime:** von den jeweiligen Paketen als weiterverteilbare
  Laufzeitdateien mitgeliefert.

Alle genannten Lizenzen erlauben die Weitergabe als Teil einer Anwendung. Die LGPL-3.0 von
Qt/PySide6 verlangt die oben beschriebene Ersetzbarkeit der Qt-Bibliotheken und den Hinweis auf
deren Quellcode; sie verpflichtet nicht zur Offenlegung des Quellcodes von PDF Tool.

## Grafiken und Schriften

- **App-Symbol von PDF Tool:** eigene Grafik aus einfachen Formen (erzeugt mit
  `windows-app/scripts/make_icons.py`), keine fremden Logos.
- **Logo in den erzeugten Vertragsübersichten** (`windows-app/assets/hott_logo_final.png`):
  Dokument-Branding der Vertragsübersichten, unverändert aus den bisherigen Versionen übernommen;
  kein Bestandteil des App-Brandings.
- **Schriften der Oberfläche** (Segoe UI Variable, Segoe UI) werden nicht mitgeliefert, sondern aus
  Windows verwendet.
- **Symbole der Oberfläche** (seit 2.7.0): 110 SVG-Symbole aus **Fluent UI System Icons** von
  Microsoft (Paket `@fluentui/svg-icons` 1.1.343, https://github.com/microsoft/fluentui-system-icons),
  unverändert unter `windows-app/app/qml/icons/`, im Setup als Teil der QML-Ressource. Lizenz: MIT.

  ```
  MIT License

  Copyright (c) 2020 Microsoft Corporation

  Permission is hereby granted, free of charge, to any person obtaining a copy
  of this software and associated documentation files (the "Software"), to deal
  in the Software without restriction, including without limitation the rights
  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
  copies of the Software, and to permit persons to whom the Software is
  furnished to do so, subject to the following conditions:

  The above copyright notice and this permission notice shall be included in all
  copies or substantial portions of the Software.

  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
  SOFTWARE.
  ```
