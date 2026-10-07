"""Grenzen der Darstellung – ohne schwere Abhängigkeiten, damit die Oberfläche sie beim Start lesen kann,
ohne PDFium und pikepdf zu laden."""

from __future__ import annotations

MAX_PIXELS = 16_000_000  # ≈ 64 MB je Bild; z. B. A4 bis ≈ 400 % bei 96 dpi
