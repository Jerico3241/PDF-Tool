"""Welche Werte ein Stapel-Eintrag tatsächlich verwendet – und woher sie stammen.

Vorrang (die erste vorhandene Angabe gilt):

* **Vorlage:** 1. im Eintrag gewählt · 2. bevorzugte Vorlage der Kundenakte ·
  3. Vorlage des Stapels · 4. Standardvorlage · 5. keine (aktuelle »Darstellung«) –
  dieselbe Reihenfolge wie ``templates.priority``
* **Regelwerk:** 1. im Eintrag gewählt · 2. Regelwerk der geltenden Vorlage · 3. Regelwerk der
  »Darstellung« (Einzelmodus). Fehlt das Regelwerk der Vorlage, gilt keines (mit Hinweis).
* **Logo:** 1. im Eintrag gewählt · 2. Logo der Kundenakte · 3. Standardlogo des Stapels ·
  4. installiertes Standardlogo. Ein Logo aus einer Vorlage gilt auf der Stufe, auf der die
  Vorlage gewählt wurde – direkt nach dem Logo dieser Stufe.
* **Zielordner:** 1. im Eintrag gewählt · 2. bevorzugter Zielordner der Kundenakte (wenn im
  Stapel erlaubt und vorhanden) · 3. Zielordner des Stapels (auf Wunsch mit Unterordner je Kunde)
* **Firmenname, Kundennummer:** Eintrag → Kundenakte → Excel (nur Werte, die tatsächlich in der
  Datei stehen – nie aus einer E-Mail-Adresse abgeleitet)
* **Rechnungsempfänger:** Auswahl im Eintrag → einzige Adresse der Excel → eindeutige Adresse der
  Kundenakte unter mehreren → (ohne Adresse in der Excel) primäre Adresse der Kundenakte
* **Kopf- und Fußzeile:** eine im Eintrag gewählte Vorlage → eigene Texte der Kundenakte →
  Vorlage der Kundenakte bzw. des Stapels → »Darstellung«. Eine leere Fußzeile ersetzt nie die
  gültige; die Standard-Fußzeile bleibt erhalten.

Die Kundenakte wird über die Rechnungsempfänger erkannt – mit derselben Logik wie im
Einzelmodus (``CustomerStore.match``). Mehrdeutige oder widersprüchliche Treffer entscheidet
immer der Benutzer. Ergebnis ist eine ``Resolution`` samt offener Punkte (``Issue``); nur ohne
offene Punkte gibt es einen PDF-Auftrag (``fields``) – derselbe wie im Einzelmodus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from appstate import footer_rich_from, header_rich_from
from richtext import RichText

from ..customers.texts import footer_of, header_of
from ..customers.matching import MatchKind, MatchResult, normalize_email
from ..customers.models import Customer
from ..overview import FILE_CODES, Issue, excel_issues, output_issues, parse_width, pdf_fields, template_layout, template_rules
from ..templates.models import ENTRY_RULE_SET, valid_id
from ..templates.priority import Level, choose
from .models import BatchItem, BatchSettings, CustomerMode, ItemStatus

SOURCE_ITEM = "Eintrag"
SOURCE_CUSTOMER = "Kundenakte"
SOURCE_BATCH = "Stapel"
SOURCE_EXCEL = "Excel"
SOURCE_DEFAULT = "Standard"
SOURCE_DEFAULT_TEMPLATE = "Standardvorlage"
SOURCE_TEMPLATE = "Vorlage"
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
PLACEHOLDER_KD = "–"  # wie in der Vorschau des Einzelmodus
# Ohne diese Angaben gibt es auch keine Vorschau (fehlende Kundennummer o. Ä. zeigt die Vorschau als »–«)
PREVIEW_BLOCKING = frozenset({"excel_missing", "file_missing", "unreadable", "columns_missing", "no_active", "pending", "logo_missing", "width_invalid", "template_missing", "rule_set_missing"})


def ref_label(ref: str) -> str:
    """»„Name“ « für Verweise per Name (bis 2.7); eine ID allein sagt dem Benutzer nichts."""
    return "" if valid_id(ref) and len(ref) >= 32 else f"„{ref}“ "


@dataclass(frozen=True)
class Defaults:
    """Aktueller globaler Standard (Ansicht »Darstellung«) – ohne Werte einer aktiven Kundenakte."""

    dateiname: str
    seitenformat: str
    logo_breite: str
    titel: str
    untertitel: str
    header: RichText
    footer: RichText
    regeln: tuple[dict, ...]
    logo: str  # installiertes Standardlogo
    regelwerk: dict | None = None  # Regelwerk der »Darstellung« (``RuleSet.to_dict()``)
    regelwerk_name: str = ""
    vorlage_standard: str = ""  # ID der Standardvorlage ("" = keine)


@dataclass
class Resolution:
    """Die für einen Eintrag geltenden Werte, ihre Herkunft und was noch fehlt."""

    customer: Customer | None = None
    customer_source: str = ""  # »erkannt«, »gewählt« oder leer
    customer_records: bool = True  # Kundenakte eingeschaltet (sonst kein Kundenbezug)
    match: MatchResult | None = None
    emails: tuple[str, ...] = ()  # Rechnungsempfänger der Excel
    company: str = ""
    company_source: str = ""
    number: str = ""
    number_source: str = ""
    email: str = ""
    email_source: str = ""
    template: str = ""  # Name der geltenden Vorlage ("" = keine)
    template_id: str = ""
    template_source: str = SOURCE_DEFAULT
    rule_set: str = ""  # Name des geltenden Regelwerks ("" = keines)
    rule_set_id: str = ""
    rule_set_source: str = ""
    logo: str = ""
    logo_source: str = ""
    folder: str = ""
    folder_source: str = ""
    header_source: str = SOURCE_DEFAULT
    fields: dict | None = None  # Auftrag für engine.erstelle_pdf (ohne Ausgabe); nur wenn bereit
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unknown_emails: tuple[str, ...] = ()  # Adressen der Excel ohne Zuordnung

    @property
    def ready(self) -> bool:
        return not self.issues and self.fields is not None

    @property
    def customer_line(self) -> str:
        """»Kunde erkannt: Beispiel GmbH · 123456«, »Kunde nicht zugeordnet« …

        Ohne Kundenakte nur die Angaben selbst (»Muster GmbH · 10042«) – kein Kundenbezug."""
        if not self.customer_records:
            return " · ".join(part for part in (self.company, self.number) if part)
        if self.customer is not None:
            prefix = "Kunde erkannt" if self.customer_source == "erkannt" else "Kunde"
            return f"{prefix}: {self.customer.label}"
        if any(issue.code in ("customer_conflict", "customer_ambiguous") for issue in self.issues):
            return "Mehrere bekannte Kunden – bitte wählen"
        if self.company or self.number:
            name = " · ".join(part for part in (self.company, self.number) if part)
            return f"Kunde nicht zugeordnet · {name}"
        return "Kunde nicht zugeordnet"


def status_for(issues: list[Issue]) -> ItemStatus:
    """Status aus den offenen Punkten: Datei-Probleme sind Fehler, alles andere braucht Angaben."""
    if not issues:
        return ItemStatus.READY
    if any(issue.code == "pending" for issue in issues):
        return ItemStatus.PENDING
    if any(issue.code in FILE_CODES for issue in issues):
        return ItemStatus.FAILED
    return ItemStatus.NEEDS_INPUT


def subfolder_name(number: str, company: str) -> str:
    """Unterordner je Kunde, z. B. »123456 Beispiel GmbH« – für Windows gültig."""
    name = " ".join(part for part in (number.strip(), company.strip()) if part)
    name = _BAD_NAME.sub("_", name).strip(" .")
    return name[:120].strip(" .") or "Ohne Kundennummer"


def _key(text: str) -> str:
    return " ".join(str(text or "").split()).casefold()


def resolve(
    item: BatchItem,
    customers,
    find_template: Callable[[str], dict | None],
    settings: BatchSettings,
    defaults: Defaults,
    for_preview: bool = False,
    find_rule_set: Callable[[str], dict | None] | None = None,
) -> Resolution:
    """Geltende Werte eines Eintrags bestimmen (ohne etwas zu verändern).

    ``customers``: Speicher der Kundenakten – ``None``, wenn die Kundenakte ausgeschaltet ist
    (dann kein Abgleich, keine Kundenwerte; Angaben kommen aus dem Eintrag und der Excel).
    ``find_template``/``find_rule_set``: Verweis (ID oder Name) → gespeicherte Daten oder ``None``.
    ``for_preview``: Auftrag auch dann bilden, wenn nur Angaben wie die Kundennummer fehlen –
    für die Vorschau (dieselbe Pipeline wie im Einzelmodus), nie für die Erstellung.
    """
    res = Resolution(customer_records=customers is not None)
    analysis = item.analysis
    ov = item.overrides
    issues: list[Issue] = []
    notes: list[str] = []

    # 1. Excel ------------------------------------------------------------------------------
    issues += excel_issues(item.path, analysis)
    usable = analysis is not None and analysis.ok
    res.emails = tuple(analysis.emails) if usable else ()

    # 2. Kundenakte: bewusst gewählt, bewusst keine oder über die Rechnungsempfänger erkannt ------------
    customer: Customer | None = None
    if customers is not None and item.customer_mode is CustomerMode.MANUAL:
        customer = customers.get(item.customer_id)
        if customer is not None:
            res.customer_source = "gewählt"
    if customers is not None and customer is None and item.customer_mode is not CustomerMode.NONE and usable:
        match = customers.match(res.emails) if res.emails else MatchResult(MatchKind.NONE)
        res.match = match
        if item.customer_mode is CustomerMode.AUTO or customers.get(item.customer_id) is None:
            if match.kind is MatchKind.SINGLE:
                customer = customers.get(match.customer_id)
                if customer is not None:
                    res.customer_source = "erkannt"
                    numbers = tuple(analysis.numbers) if analysis else ()
                    if customer.number and len(numbers) == 1 and _key(numbers[0]) != _key(customer.number):
                        # Die Excel nennt eine andere Kundennummer: nie still mit der erkannten Akte weiter.
                        issues.append(Issue("kunde", "number_mismatch", f"Kundennummer der Excel ({numbers[0]}) passt nicht zu „{customer.label}“ – Kunden bitte wählen"))
                        customer = None
                        res.customer_source = ""
            elif match.kind is MatchKind.CONFLICT:
                issues.append(Issue("kunde", "customer_conflict", "Rechnungsempfänger verschiedener bekannter Kunden – Kunden bitte wählen"))
            elif match.kind is MatchKind.AMBIGUOUS:
                issues.append(Issue("kunde", "customer_ambiguous", "E-Mail-Adresse mehreren Kundenakten zugeordnet – Kunden bitte wählen"))
    res.customer = customer
    if customers is not None and usable and res.emails:
        res.unknown_emails = tuple(email for email in (normalize_email(mail) for mail in res.emails) if email and not customers.owner_ids(email))

    # 3. Firmenname, Kundennummer ------------------------------------------------------------------
    def pick(override: str | None, from_customer: str, from_excel: tuple[str, ...]) -> tuple[str, str]:
        if override is not None:
            return override.strip(), SOURCE_ITEM
        if customer is not None and from_customer.strip():
            return from_customer.strip(), SOURCE_CUSTOMER
        if len(from_excel) == 1:
            return from_excel[0], SOURCE_EXCEL
        return "", ""

    res.company, res.company_source = pick(ov.company, customer.company if customer else "", tuple(analysis.companies) if usable else ())
    res.number, res.number_source = pick(ov.number, customer.number if customer else "", tuple(analysis.numbers) if usable else ())

    # 4. Rechnungsempfänger ------------------------------------------------------------------------------
    emails = res.emails
    chosen = (ov.email or "").strip()
    if chosen and (len(emails) <= 1 or chosen in emails):
        # Bei mehreren Empfängern zählt nur eine Adresse, die in der Excel steht (sonst neu wählen).
        res.email, res.email_source = chosen, SOURCE_ITEM
    elif len(emails) == 1:
        res.email, res.email_source = emails[0], SOURCE_EXCEL
    elif len(emails) > 1:
        own = [mail for mail in emails if customer is not None and normalize_email(mail) in customer.emails]
        if len(own) == 1:
            res.email, res.email_source = own[0], SOURCE_CUSTOMER
    elif customer is not None and customer.primary_email:
        res.email, res.email_source = customer.primary_email, SOURCE_CUSTOMER

    # 5. Vorlage ---------------------------------------------------------------------------------------------
    chain = [Level(ov.template, SOURCE_ITEM, strict=True)]
    if customer is not None:
        chain.append(Level(customer.template or None, SOURCE_CUSTOMER))
    chain.append(Level(settings.template or None, SOURCE_BATCH))
    chain.append(Level(defaults.vorlage_standard or None, SOURCE_DEFAULT_TEMPLATE))
    choice = choose(chain, find_template)
    for ref, source in choice.missing:
        if choice.blocked and source == SOURCE_ITEM:
            issues.append(Issue("vorlage", "template_missing", f"Vorlage {ref_label(ref)}gibt es nicht mehr".replace("  ", " ")))
        else:
            notes.append(f"Vorlage {ref_label(ref)}({source}) gibt es nicht mehr – es gilt die nächste Stufe.")
    template_entry = choice.entry
    if template_entry is not None:
        res.template = str(template_entry.get("name") or choice.ref)
        res.template_id = str(template_entry.get("id") or choice.ref)
        res.template_source = choice.source
    elif choice.source == SOURCE_ITEM and not choice.blocked:  # bewusst keine Vorlage (nur im Eintrag möglich)
        res.template, res.template_source = "", SOURCE_ITEM
    layout = template_layout(template_entry) if template_entry is not None else {}

    # 6. Logo ----------------------------------------------------------------------------------------------------
    def template_logo(level: str) -> list[tuple[str, str]]:
        if template_entry is not None and res.template_source == level and layout.get("logo"):
            return [(layout["logo"], f"Vorlage „{res.template}“")]
        return []

    logo_chain: list[tuple[str, str]] = []
    if ov.logo is not None:
        logo_chain.append((ov.logo, SOURCE_ITEM))
    logo_chain += template_logo(SOURCE_ITEM)
    if customer is not None and customer.logo:
        logo_chain.append((customer.logo, SOURCE_CUSTOMER))
    logo_chain += template_logo(SOURCE_CUSTOMER)
    if settings.logo:
        logo_chain.append((settings.logo, SOURCE_BATCH))
    logo_chain += template_logo(SOURCE_BATCH)
    logo_chain.append((defaults.logo, SOURCE_DEFAULT))
    for value, source in logo_chain:
        value = str(value or "").strip()
        if value and Path(value).is_file():
            res.logo, res.logo_source = value, source
            break
        if source == SOURCE_ITEM:
            res.logo, res.logo_source = value, source  # bewusst gewählt: fehlt es, fehlt es (siehe offene Punkte)
            break
        if source == SOURCE_CUSTOMER:
            notes.append("Gespeichertes Logo wurde nicht gefunden.")
        elif source == SOURCE_BATCH:
            notes.append("Standardlogo des Stapels wurde nicht gefunden.")

    # 7. Zielordner -------------------------------------------------------------------------------------------
    if ov.target_dir is not None:
        res.folder, res.folder_source = ov.target_dir.strip(), SOURCE_ITEM
    else:
        if customer is not None and customer.target_dir and settings.customer_target:
            if Path(customer.target_dir).is_dir():
                res.folder, res.folder_source = customer.target_dir, SOURCE_CUSTOMER
            else:
                notes.append("Gespeicherter Zielordner der Kundenakte ist nicht verfügbar – es gilt der Zielordner des Stapels.")
        if not res.folder:
            base = settings.target_dir.strip()
            if base and settings.subfolders and (res.number or res.company):
                res.folder = str(Path(base) / subfolder_name(res.number, res.company))
            else:
                res.folder = base
            res.folder_source = SOURCE_BATCH

    # 8. Darstellung, Kopf- und Fußzeile -------------------------------------------------------------------------
    breite_text = layout.get("logo_breite", defaults.logo_breite)
    if template_entry is not None:
        base_header, base_footer = header_rich_from(template_entry), footer_rich_from(template_entry)
        regeln = template_rules(template_entry)
    else:
        base_header, base_footer = defaults.header, defaults.footer
        regeln = [dict(regel) for regel in defaults.regeln]
    header, footer = base_header, base_footer
    res.header_source = f"Vorlage „{res.template}“" if template_entry is not None else "Darstellung"
    if customer is not None and res.template_source != SOURCE_ITEM:
        own_header, own_footer = header_of(customer), footer_of(customer)
        if own_header is not None or own_footer is not None:
            res.header_source = SOURCE_CUSTOMER
        header = own_header if own_header is not None else header
        footer = own_footer if own_footer is not None else footer  # nie eine leere Fußzeile der Akte

    # 8b. Regelwerk: im Eintrag gewählt → Regelwerk der Vorlage → »Darstellung« ---------------------------------------
    regelwerk: dict | None = defaults.regelwerk
    res.rule_set, res.rule_set_source = (defaults.regelwerk_name, SOURCE_DEFAULT) if defaults.regelwerk else ("", "")
    res.rule_set_id = str((defaults.regelwerk or {}).get("id") or "")
    template_rule_set = template_entry.get(ENTRY_RULE_SET) if template_entry is not None else None
    if ov.rule_set is not None:
        ref, source, strict = ov.rule_set, SOURCE_ITEM, True
    elif isinstance(template_rule_set, str):
        ref, source, strict = template_rule_set, f"{SOURCE_TEMPLATE} „{res.template}“", False
    else:
        ref, source, strict = None, "", False
    if ref is not None:
        found = find_rule_set(ref) if (ref and find_rule_set is not None) else None
        if ref == "":
            regelwerk, res.rule_set, res.rule_set_id, res.rule_set_source = None, "", "", source
        elif found is not None:
            regelwerk, res.rule_set, res.rule_set_id, res.rule_set_source = found, str(found.get("name") or ""), str(found.get("id") or ref), source
        elif strict:
            issues.append(Issue("regelwerk", "rule_set_missing", "Das gewählte Regelwerk gibt es nicht mehr"))
            regelwerk, res.rule_set, res.rule_set_id, res.rule_set_source = None, "", "", source
        else:
            # Wie beim Laden der Vorlage im Einzelmodus: kein fremdes Regelwerk an seiner Stelle.
            notes.append(f"Das Regelwerk der Vorlage „{res.template}“ gibt es nicht mehr – es wird kein Regelwerk verwendet.")
            regelwerk, res.rule_set, res.rule_set_id, res.rule_set_source = None, "", "", source

    # 9. Offene Punkte und Auftrag -------------------------------------------------------------------------------------
    choose_customer = any(issue.area == "kunde" for issue in issues)
    if not res.company and customer is None and usable and not choose_customer and not any(issue.code in FILE_CODES for issue in issues):
        issues.append(Issue("firma", "company_missing", "Firmenname fehlt"))
    if usable:
        found = output_issues(res.number, emails, res.email, res.logo, breite_text, res.folder)
        # Muss erst der Kunde gewählt werden, folgen Firmenname und Kundennummer daraus – keine Folgefehler.
        issues += [issue for issue in found if not (choose_customer and issue.code == "number_missing")]
    res.issues = issues
    res.notes = notes
    if not issues or (for_preview and not any(issue.code in PREVIEW_BLOCKING for issue in issues)):
        res.fields = pdf_fields(
            excel=item.path,
            logo=res.logo,
            kd=res.number or PLACEHOLDER_KD,
            firma=res.company,
            mail=res.email,
            dateiname=layout.get("dateiname", defaults.dateiname),
            seitenformat=layout.get("format", defaults.seitenformat),
            breite=parse_width(breite_text) or 0.0,
            titel=layout.get("titel", defaults.titel),
            untertitel=layout.get("untertitel", defaults.untertitel),
            header=header,
            footer=footer,
            regeln=regeln,
            regelwerk=regelwerk,
        )
    return res
