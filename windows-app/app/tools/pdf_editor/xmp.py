"""XMP-Metadaten ohne lxml: Titel, Autor, Thema, Stichwörter und Änderungsdatum eines vorhandenen
XMP-Pakets an die geänderten Eigenschaften angleichen.

Die Laufzeit der App liefert lxml nicht mit – pikepdf braucht es für ``open_metadata``. XMP ist
RDF/XML; gelesen und geschrieben wird deshalb mit ``xml.dom.minidom`` aus der Standardbibliothek.
Präfixe, Namensräume, Verarbeitungsanweisungen (``<?xpacket …?>``) und alle übrigen Eigenschaften
bleiben unverändert. Pakete mit DOCTYPE oder Entitäten werden nicht angefasst (``XmpError``) – XMP
braucht beides nie, und so wird nie etwas nachgeladen oder aufgebläht.
"""

from __future__ import annotations

from datetime import datetime
from xml.dom import Node, minidom
from xml.parsers.expat import ExpatError

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DC = "http://purl.org/dc/elements/1.1/"
PDF = "http://ns.adobe.com/pdf/1.3/"
XMP = "http://ns.adobe.com/xap/1.0/"
XML = "http://www.w3.org/XML/1998/namespace"
PREFIXES = {DC: "dc", PDF: "pdf", XMP: "xmp"}

# Eigenschaft der Oberfläche → (Namensraum, Name, Art): »alt« = Sprachvarianten, »seq« = Liste, »text«
FIELDS = {
    "title": (DC, "title", "alt"),
    "author": (DC, "creator", "seq"),
    "subject": (DC, "description", "alt"),
    "keywords": (PDF, "Keywords", "text"),
}
DATES = ((XMP, "ModifyDate"), (XMP, "MetadataDate"))


class XmpError(ValueError):
    """Das XMP-Paket lässt sich nicht sicher lesen oder ändern."""


def sync(data: bytes, values: dict[str, str | None], modified: datetime) -> bytes:
    """``values``: Text setzen, ``""`` entfernen, ``None`` unverändert lassen. Datumsangaben
    (``xmp:ModifyDate``, ``xmp:MetadataDate``) erhalten ``modified``."""
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise XmpError("XMP mit DOCTYPE oder Entitäten")
    try:
        document = minidom.parseString(data)
    except (ExpatError, ValueError) as exc:
        raise XmpError(f"XMP nicht lesbar: {exc}") from exc
    try:
        rdf = document.getElementsByTagNameNS(RDF, "RDF")
        if not rdf:
            raise XmpError("XMP ohne rdf:RDF")
        root = rdf[0]
        rdf_prefix = root.prefix or "rdf"
        descriptions = [node for node in root.childNodes if node.nodeType == Node.ELEMENT_NODE and node.namespaceURI == RDF and node.localName == "Description"]
        if not descriptions:
            description = document.createElementNS(RDF, f"{rdf_prefix}:Description")
            description.setAttributeNS(RDF, f"{rdf_prefix}:about", "")
            root.appendChild(description)
            descriptions = [description]
        for key, (namespace, name, kind) in FIELDS.items():
            value = values.get(key)
            if value is None:
                continue
            _remove(descriptions, namespace, name)
            if value.strip():
                _add(document, descriptions[0], namespace, name, kind, value.strip(), rdf_prefix)
        stamp = modified.replace(microsecond=0).isoformat()
        for namespace, name in DATES:
            if not _set_simple(descriptions, namespace, name, stamp):
                _add(document, descriptions[0], namespace, name, "text", stamp, rdf_prefix)
        # Ohne XML-Deklaration (wie bisher): das Paket beginnt mit <?xpacket begin=…?>
        text = "".join(node.toxml() for node in document.childNodes)
    finally:
        document.unlink()
    return text.encode("utf-8")


def read(data: bytes) -> dict[str, str]:
    """Die vier Felder aus einem XMP-Paket (für Tests und Prüfungen) – leer, wenn nicht lesbar."""
    try:
        document = minidom.parseString(data)
    except (ExpatError, ValueError):
        return {}
    try:
        result = {}
        for key, (namespace, name, _kind) in FIELDS.items():
            for element in document.getElementsByTagNameNS(namespace, name):
                items = element.getElementsByTagNameNS(RDF, "li")
                result[key] = _text(items[0]) if items else _text(element)
                break
            else:
                for element in document.getElementsByTagNameNS(RDF, "Description"):
                    if element.hasAttributeNS(namespace, name):
                        result[key] = element.getAttributeNS(namespace, name)
                        break
        return result
    finally:
        document.unlink()


# Hilfen ---------------------------------------------------------------------------------------
def _text(element) -> str:
    return "".join(node.data for node in element.childNodes if node.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE)).strip()


def _remove(descriptions, namespace: str, name: str) -> None:
    for description in descriptions:
        if description.hasAttributeNS(namespace, name):
            description.removeAttributeNS(namespace, name)
        for child in list(description.childNodes):
            if child.nodeType == Node.ELEMENT_NODE and child.namespaceURI == namespace and child.localName == name:
                description.removeChild(child).unlink()


def _set_simple(descriptions, namespace: str, name: str, value: str) -> bool:
    """Vorhandene einfache Eigenschaft (Attribut oder Element) setzen; ``False``: gibt es nicht."""
    found = False
    for description in descriptions:
        if description.hasAttributeNS(namespace, name):
            attribute = description.getAttributeNodeNS(namespace, name)
            attribute.value = value
            found = True
        for child in list(description.childNodes):
            if child.nodeType == Node.ELEMENT_NODE and child.namespaceURI == namespace and child.localName == name:
                for old in list(child.childNodes):
                    child.removeChild(old).unlink()
                child.appendChild(child.ownerDocument.createTextNode(value))
                found = True
    return found


def _add(document, description, namespace: str, name: str, kind: str, value: str, rdf_prefix: str) -> None:
    prefix = _prefix(description, namespace)
    element = document.createElementNS(namespace, f"{prefix}:{name}")
    if kind == "text":
        element.appendChild(document.createTextNode(value))
    else:
        container = document.createElementNS(RDF, f"{rdf_prefix}:{'Alt' if kind == 'alt' else 'Seq'}")
        item = document.createElementNS(RDF, f"{rdf_prefix}:li")
        if kind == "alt":
            item.setAttributeNS(XML, "xml:lang", "x-default")
        item.appendChild(document.createTextNode(value))
        container.appendChild(item)
        element.appendChild(container)
    description.appendChild(element)


def _prefix(element, namespace: str) -> str:
    """Präfix, das an ``element`` für ``namespace`` gilt – sonst eines festlegen (Standardname, bei
    Kollision mit Nummer) und am Element erklären."""
    bound: dict[str, str] = {}
    node = element
    while node is not None and node.nodeType == Node.ELEMENT_NODE:
        for index in range(node.attributes.length):
            attribute = node.attributes.item(index)
            if attribute.name.startswith("xmlns:"):
                bound.setdefault(attribute.name[6:], attribute.value)
        node = node.parentNode
    for prefix, uri in bound.items():
        if uri == namespace:
            return prefix
    base = PREFIXES.get(namespace, "ns")
    prefix, number = base, 1
    while prefix in bound:
        prefix, number = f"{base}{number}", number + 1
    element.setAttribute(f"xmlns:{prefix}", namespace)
    return prefix
