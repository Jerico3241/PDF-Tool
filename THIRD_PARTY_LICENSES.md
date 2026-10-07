# Lizenzen von Drittanbietern

PDF Tool (Windows-App) wird mit einer eingebetteten Python-Laufzeit, den folgenden Paketen, der
Texterkennung Tesseract ([eigener Abschnitt](#texterkennung-ocr-tesseract-und-seine-bibliotheken)) und der
Laufzeit des optionalen KI-Assistenten ([eigener Abschnitt](#ki-assistent-optional-llamacpp-und-sprachmodelle))
ausgeliefert. Die Versionen und SHA-256-Prüfsummen stehen in
[`windows-app/runtime-requirements.txt`](windows-app/runtime-requirements.txt) bzw. in
[`windows-app/build.py`](windows-app/build.py) (Python, Tesseract, Sprachdaten). Alle Pakete werden
unverändert als Original-Wheels von PyPI bzw. als Original-Archiv von python.org übernommen.

Die vollständigen Lizenztexte liegen im installierten Programm neben dem jeweiligen Paket:

- Python: `%LOCALAPPDATA%\PDF-Tool\runtime\LICENSE.txt` (enthält auch die Lizenzen der mit Python
  gelieferten Bibliotheken wie OpenSSL, libffi, bzip2, xz, zlib, SQLite, expat, mpdecimal; Tcl/Tk
  gehört seit 2.7.0 nicht mehr zur Laufzeit)
- Pakete: `%LOCALAPPDATA%\PDF-Tool\runtime\Lib\site-packages\<Paket>-<Version>.dist-info\`
  (bei pikepdf zusätzlich `…\pikepdf-10.15.0.dist-info\licenses\third-party-licenses\`, bei
  pypdfium2 `…\pypdfium2-5.13.0.dist-info\licenses\`)
- Texterkennung: `%LOCALAPPDATA%\PDF-Tool\ocr\LICENSE.txt` (Apache-2.0 – Tesseract und Sprachdaten);
  die Lizenzen der übrigen Bibliotheken nennt der Abschnitt zur Texterkennung
- KI-Assistent: `%LOCALAPPDATA%\PDF-Tool\ai\LICENSES.txt` (alle in llama.cpp eingebauten Bestandteile)

## Laufzeit und Pakete

| Komponente | Version | Lizenz | Verwendet für | Quelle |
| --- | --- | --- | --- | --- |
| Python (Windows, 64 Bit), ohne tkinter/Tcl/Tk | 3.13.15 | PSF-2.0 | Laufzeit | https://www.python.org |
| PySide6-Essentials (Qt for Python) | 6.11.2 | LGPL-3.0-only (alternativ GPL-2.0/GPL-3.0 oder kommerziell) | Oberfläche (Qt Quick/QML), Dateiauswahl, Zwischenablage | https://doc.qt.io/qtforpython-6/ · https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2 |
| ↳ shiboken6 | 6.11.2 | LGPL-3.0-only (alternativ GPL-2.0/GPL-3.0 oder kommerziell) | Python-Bindung von PySide6 | https://pypi.org/project/shiboken6/6.11.2/ |
| ↳ Qt (in PySide6 enthalten: QtCore, QtGui, QtWidgets, QtNetwork, QtOpenGL, QtQml, QtQuick, Qt Quick Controls (nur Stil »Basic«), Qt Quick Templates, Layouts, Shapes, QtSvg, QtPrintSupport; Plugins qwindows, qoffscreen, qico, qjpeg, qsvg, qwebp, qsvgicon, qschannelbackend) | 6.11.2 | LGPL-3.0-only | Oberfläche; Qt Network mit TLS über Windows-Schannel für die Update-Prüfung (seit 2.7.2, keine zusätzliche Bibliothek); Qt Print Support für den Druckdialog von Windows im PDF Reader (seit 3.0.0) | https://download.qt.io/official_releases/qt/6.11/ |
| ↳ Bibliotheken von Qt (u. a. libjpeg-turbo, libwebp, PCRE2, HarfBuzz, FreeType, double-conversion, zlib) | – | BSD-artig / MIT / IJG / FTL / Zlib | Bildformate, Textdarstellung | https://doc.qt.io/qt-6/licenses-used-in-qt.html |
| pikepdf | 10.15.0 | MPL-2.0 | PDF reparieren (Analyse, Neuaufbau); PDF Reader & Editor (Struktur, Bearbeiten, Speichern) | https://github.com/pikepdf/pikepdf |
| ↳ qpdf (in pikepdf enthalten) | 12.4.1 | Apache-2.0 | PDF-Engine 1 | https://github.com/qpdf/qpdf |
| ↳ libjpeg-turbo, zlib, OpenSSL, Teile von pdfminer.six, sRGB-Farbprofil (in pikepdf enthalten) | – | IJG / BSD-3-Clause / Zlib / Apache-2.0 / MIT | Bilddaten, Verschlüsselung, Farbprofile | `pikepdf-10.15.0.dist-info\licenses\third-party-licenses\` |
| ↳ Microsoft Visual C++ Runtime (msvcp140, in pikepdf, numpy, pandas enthalten) | – | Microsoft Redistributable | C++-Laufzeit | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| pypdfium2 | 5.13.0 | Apache-2.0 oder BSD-3-Clause | PDF reparieren (zweite Engine, Rettungsmodus); PDF Reader & Editor (Darstellung, Text, Suche, Prüfung von Änderungen) | https://github.com/pypdfium2-team/pypdfium2 |
| ↳ PDFium (in pypdfium2 enthalten) | 153.0.7999.0 | BSD-3-Clause | PDF-Engine 2 | https://pdfium.googlesource.com/pdfium |
| ↳ Bibliotheken von PDFium | – | Apache-2.0 (abseil, llvm-libc mit LLVM-Exception), FTL (FreeType), Unicode-3.0 (ICU), MIT (lcms, simdutf), BSD (agg, OpenJPEG, libjpeg-turbo), libpng, libtiff, Zlib, MIT/Apache-2.0 (fast_float) | Schriften, Bilder, Farbprofile | https://github.com/bblanchon/pdfium-binaries |
| fontTools | 4.66.1 | MIT | PDF Reader & Editor: Teilmengen lokaler Schriften einbetten (nur wenn die Schrift es erlaubt) | https://github.com/fonttools/fonttools |
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
werkzeuge außer `tesseract.exe` (Texterkennung, siehe unten). pypdf wird ohne optionale
Zusatzpakete (cryptography, PyCryptodome) ausgeliefert; Verschlüsselung übernimmt weiterhin qpdf.
fontTools gehört seit 3.0.0 für den PDF Editor zur
Laufzeit; Schriften selbst werden nie mitgeliefert, aus PDFs extrahiert oder weitergegeben. Von PySide6 bleiben nur die Module,
Plugins und QML-Module, die die App lädt (`windows-app/qtruntime.py`): keine Entwicklerwerkzeuge
(Designer, Linguist, qmlls …), keine weiteren Stile, kein Software-OpenGL (`opengl32sw.dll`), keine
Übersetzungen – die Dateien selbst bleiben unverändert (Original-Wheel).

## Texterkennung (OCR): Tesseract und seine Bibliotheken

Die Texterkennung des PDF Editors läuft lokal mit Tesseract im Programmordner
(`%LOCALAPPDATA%\PDF-Tool\ocr\`). Quelle ist der signierte Windows-Installer der UB Mannheim aus dem
Release 5.5.3 von tesseract-ocr
(`https://github.com/tesseract-ocr/tesseract/releases/download/5.5.3/tesseract-ocr-w64-setup-5.5.3.20260724.exe`,
SHA-256 `bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4`). Übernommen werden
unverändert nur `tesseract.exe` und die 33 DLLs, die es laut Importtabellen direkt oder indirekt lädt
(`windows-app/build.py`, `TESSERACT_DLLS`) – keine Trainingswerkzeuge, kein ICU, Pango, Cairo,
GLib, FreeType oder HarfBuzz des Installers. Versionen laut den Dateien selbst (Versionsressource,
Versionsfunktion oder Versionstext); »–«: in der Datei nicht vermerkt.

| Komponente (Datei in `ocr\`) | Version | Lizenz | Verwendet für | Quelle |
| --- | --- | --- | --- | --- |
| Tesseract OCR (`tesseract.exe`, `libtesseract-5.dll`, `tessdata\pdf.ttf`) | 5.5.3 (Build 5.5.3.20260724) | Apache-2.0 | Texterkennung, Text-only-PDF | https://github.com/tesseract-ocr/tesseract |
| Sprachdaten `deu`, `eng`, `osd` (`tessdata\*.traineddata`, tessdata_fast) | Commit 87416418657359cb625c412a48b6e1d6d41c29bd | Apache-2.0 | Deutsch, Englisch, Lageerkennung | https://github.com/tesseract-ocr/tessdata_fast |
| Leptonica (`libleptonica-6.dll`) | 1.87.0 | BSD-2-Clause | Bildverarbeitung für Tesseract | http://www.leptonica.org |
| GCC-Laufzeit (`libgcc_s_seh-1.dll`, `libstdc++-6.dll`) | GCC 14 (mingw-w64, POSIX-Threads) | GPL-3.0-or-later WITH GCC-exception-3.1 | C/C++-Laufzeit | https://gcc.gnu.org |
| winpthreads (`libwinpthread-1.dll`) | – (mingw-w64) | MIT, Teile BSD-3-Clause | POSIX-Threads | https://www.mingw-w64.org |
| libarchive (`libarchive-13.dll`) | 3.8.8 | BSD-2-Clause | von Tesseract gebunden (Sprachdaten in Archiven) | https://libarchive.org |
| libcurl (`libcurl-4.dll`), TLS über Windows-Schannel | 8.21.0 | curl | von Tesseract gebunden (Bilder per URL – PDF Tool übergibt nur lokale Dateien) | https://curl.se |
| libssh2 (`libssh2-1.dll`) | 1.11.1 | BSD-3-Clause | von libcurl benötigt | https://libssh2.org |
| libpsl (`libpsl-5.dll`) mit eingebauter Public Suffix List | 0.21.5 | MIT (Public Suffix List: MPL-2.0) | von libcurl benötigt | https://github.com/rockdaboot/libpsl |
| libidn2 (`libidn2-0.dll`) | 2.3.8 | LGPL-3.0-or-later OR GPL-2.0-or-later | von libcurl benötigt | https://www.gnu.org/software/libidn/ |
| libunistring (`libunistring-5.dll`) | 1.4.2 | LGPL-3.0-or-later OR GPL-2.0-or-later | von libidn2 benötigt | https://www.gnu.org/software/libunistring/ |
| libiconv (`libiconv-2.dll`) | 1.19 | LGPL-2.1-or-later | Zeichensätze (libarchive, libidn2) | https://www.gnu.org/software/libiconv/ |
| libintl aus gettext (`libintl-8.dll`) | 1.0 | LGPL-2.1-or-later | von libidn2 benötigt | https://www.gnu.org/software/gettext/ |
| Brotli (`libbrotlidec.dll`, `libbrotlicommon.dll`) | 1.2.0 | MIT | von libcurl benötigt | https://github.com/google/brotli |
| Zstandard (`libzstd.dll`) | 1.5.7 | BSD-3-Clause (alternativ GPL-2.0-only) | Kompression (libarchive, libcurl, libtiff) | https://facebook.github.io/zstd/ |
| XZ Utils, liblzma (`liblzma-5.dll`) | 5.8.3 | 0BSD | Kompression (libarchive, libtiff) | https://tukaani.org/xz/ |
| LZ4 (`liblz4.dll`) | 1.10.0 | BSD-2-Clause | Kompression (libarchive) | https://lz4.org |
| bzip2 (`libbz2-1.dll`) | 1.0.8 | bzip2-1.0.6 | Kompression (libarchive) | https://sourceware.org/bzip2/ |
| libb2, BLAKE2 (`libb2-1.dll`) | – | CC0-1.0 (alternativ OpenSSL oder Apache-2.0) | Prüfsummen (libarchive) | https://github.com/BLAKE2/libb2 |
| Expat (`libexpat-1.dll`) | 2.8.2 | MIT | XML (libarchive) | https://libexpat.github.io |
| zlib (`zlib1.dll`) | 1.3.2 | Zlib | Kompression | https://zlib.net |
| LibTIFF (`libtiff-6.dll`) | 4.7.2 | libtiff | Bildformat TIFF (Leptonica) | https://libtiff.gitlab.io/libtiff/ |
| JBIG-KIT (`libjbig-0.dll`) | 2.1 | GPL-2.0-or-later | JBIG in TIFF (libtiff) | https://www.cl.cam.ac.uk/~mgk25/jbigkit/ |
| LERC (`libLerc.dll`) | – | Apache-2.0 | Kompression in TIFF (libtiff) | https://github.com/Esri/lerc |
| libdeflate (`libdeflate.dll`) | – | MIT | Kompression in TIFF (libtiff) | https://github.com/ebiggers/libdeflate |
| libjpeg-turbo (`libjpeg-8.dll`) | 3.2.0 | IJG AND BSD-3-Clause AND Zlib | Bildformat JPEG | https://libjpeg-turbo.org |
| libpng (`libpng16-16.dll`) | 1.6.58 | libpng-2.0 | Bildformat PNG (Seitenbild für die Erkennung) | http://www.libpng.org |
| OpenJPEG (`libopenjp2-7.dll`) | 2.5.4 | BSD-2-Clause | Bildformat JPEG 2000 | https://www.openjpeg.org |
| GIFLIB (`libgif-7.dll`) | – | MIT | Bildformat GIF | https://giflib.sourceforge.net |
| libwebp (`libwebp-7.dll`, `libwebpmux-3.dll`, `libsharpyuv-0.dll`) | 1.6.0 | BSD-3-Clause | Bildformat WebP | https://chromium.googlesource.com/webm/libwebp |

Gebaut sind `tesseract.exe` und `libtesseract-5.dll` von der UB Mannheim mit einem mingw-w64-Cross-
Compiler (GCC 14), die übrigen DLLs stammen aus MSYS2 (mingw64; Quellen und Build-Skripte:
https://github.com/msys2/MINGW-packages, Quellarchive: https://repo.msys2.org/mingw/sources/).
Alle Teile sind mit der GPL-3.0-or-later von PDF Tool vereinbar; nichts davon steht unter der AGPL.
JBIG-KIT (GPL-2.0-or-later, von LibTIFF gebunden) ist nur unter einer GPL nutzbar – für PDF Tool
(GPL-3.0-or-later) ist das erfüllt. Die LGPL-Bibliotheken (libiconv, libintl, libidn2, libunistring)
liegen als eigene DLLs neben `tesseract.exe` und lassen sich durch kompatible Fassungen ersetzen; ihr
Quellcode (wie der von JBIG-KIT und der GCC-Laufzeit) ist unter den genannten Adressen erhältlich.

## KI-Assistent (optional): llama.cpp und Sprachmodelle

Der KI-Assistent (seit 3.2, standardmäßig aus) rechnet lokal mit llama.cpp im Programmordner
(`%LOCALAPPDATA%\PDF-Tool\ai\`). Quelle ist das offizielle Windows-Paket für den Prozessor aus dem Release
b11476 von ggml-org/llama.cpp
(`https://github.com/ggml-org/llama.cpp/releases/download/b11476/llama-b11476-bin-win-cpu-x64.zip`,
SHA-256 `a23e548c6b3525c38bcfeceaff919786ae06741857043cb670279b70100e5483`). Übernommen werden unverändert nur `llama-server.exe`, die
DLLs, die es laut Importtabellen direkt oder indirekt lädt, und die Rechenwerke `ggml-cpu-*.dll` (eines je
Prozessorgeneration; llama-server wählt selbst) – keine weiteren Programme, kein RPC- und kein GPU-Backend.
Die vollständigen Lizenztexte aller eingebauten Bestandteile gibt das Paket selbst aus (`llama.exe licenses`);
sie liegen unverändert in `%LOCALAPPDATA%\PDF-Tool\ai\LICENSES.txt`.

| Komponente | Lizenz | Verwendet für | Quelle |
| --- | --- | --- | --- |
| llama.cpp und ggml (`llama-server.exe`, `llama*.dll`, `ggml*.dll`, `ggml-cpu-*.dll`, `mtmd.dll`) | MIT | lokales Sprachmodell (KI-Assistent) | https://github.com/ggml-org/llama.cpp |
| cpp-httplib (in llama.cpp eingebaut) | MIT | lokale Schnittstelle des KI-Prozesses (nur 127.0.0.1) | https://github.com/yhirose/cpp-httplib |
| nlohmann/json (in llama.cpp eingebaut) | MIT | JSON | https://github.com/nlohmann/json |
| BoringSSL (in llama.cpp eingebaut) | siehe `ai\LICENSES.txt` | TLS in llama.cpp (Modell-Downloads von llama.cpp selbst – PDF Tool nutzt sie nicht) | https://boringssl.googlesource.com/boringssl |
| LLVM OpenMP (`libomp.dll`) | Apache-2.0 WITH LLVM-exception | parallele Berechnung | https://openmp.llvm.org |

Die **Sprachmodelle** gehören nicht zum Setup: Sie werden nur auf ausdrücklichen Wunsch über HTTPS von
Hugging Face geladen (feste Revision, SHA-256 geprüft, `windows-app/app/assistant/catalog.py`), liegen in
`%LOCALAPPDATA%\PDF-Tool-KI\modelle\` und lassen sich jederzeit entfernen (auch die Deinstallation entfernt sie).

| Modell (Datei) | Lizenz | Quelle |
| --- | --- | --- |
| Qwen3.5 4B, GGUF Q4_K_M (`Qwen3.5-4B-Q4_K_M.gguf`, »Genau«) | Apache-2.0 | https://huggingface.co/unsloth/Qwen3.5-4B-GGUF (Basis: https://huggingface.co/Qwen/Qwen3.5-4B) |
| Qwen3.5 2B, GGUF Q4_K_M (`Qwen3.5-2B-Q4_K_M.gguf`, »Kompakt«) | Apache-2.0 | https://huggingface.co/unsloth/Qwen3.5-2B-GGUF (Basis: https://huggingface.co/Qwen/Qwen3.5-2B) |

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
- **Symbole der Oberfläche** (seit 2.7.0): 175 SVG-Symbole aus **Fluent UI System Icons** von
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
