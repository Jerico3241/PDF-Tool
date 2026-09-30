"""Eigene Kopf- und Fußzeile einer Kundenakte als ``RichText`` (gemeinsam für Einzelmodus und Stapel)."""

from __future__ import annotations

from richtext import FOOTER_ALIGN, FOOTER_STYLE, HEADER_ALIGN, HEADER_STYLE, RichText

from .models import Customer


def header_of(customer: Customer) -> RichText | None:
    """Eigene Kopfzeile der Kundenakte – ``None`` ohne eigene."""
    if customer.header is None:
        return None
    return RichText.from_storage(customer.header.text, customer.header.format, HEADER_STYLE, HEADER_ALIGN)


def footer_of(customer: Customer) -> RichText | None:
    """Eigene Fußzeile der Kundenakte – ``None`` ohne eigene (nie eine leere)."""
    if customer.footer is None or not customer.footer.text.strip():
        return None
    return RichText.from_storage(customer.footer.text, customer.footer.format, FOOTER_STYLE, FOOTER_ALIGN)
