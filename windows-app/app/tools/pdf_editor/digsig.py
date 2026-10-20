"""Digitale Signaturen (seit 4.0 Beta 6): PDFs mit einem Zertifikat signieren und vorhandene Signaturen prüfen.

Signiert wird nach PAdES (``ETSI.CAdES.detached``, Stufe B-B): ein CMS-Paket mit SHA-256 über alle Bytes der Datei
außer dem Platz für die Signatur selbst. Die Signatur kommt als inkrementelle Aktualisierung hinter das unveränderte
Original – frühere Signaturen bleiben gültig. Ein PDF ohne Signatur schreibt PDF Tool vorher einmal neu (gleicher
Inhalt, einfache Querverweistabelle), damit die Aktualisierung in jedem Programm sauber lesbar ist.

Das Zertifikat kommt aus dem Zertifikatspeicher von Windows (``winsign``, privater Schlüssel bleibt dort, auch auf
Chipkarten) oder aus einer Datei (.pfx/.p12 mit Kennwort). Geprüft wird ohne Netzwerk: Unverändertheit (Prüfsumme),
mathematische Gültigkeit der Signatur und – unter Windows – ob Windows dem Zertifikat vertraut.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import pikepdf
from pikepdf import Array, Dictionary, Name

from .errors import EditorError

CONTENTS_SIZE = 16384  # Bytes für das CMS-Paket (Zertifikatskette eingeschlossen)
SUBFILTER = "/ETSI.CAdES.detached"
VERIFIABLE = ("/ETSI.CAdES.detached", "/adbe.pkcs7.detached")

VALID = "valid"  # unverändert, Signatur korrekt
CHANGED = "changed"  # Signatur korrekt, danach weitere Änderungen am Dokument
INVALID = "invalid"  # Inhalt passt nicht mehr zur Signatur
UNKNOWN = "unknown"  # Format, das PDF Tool nicht prüft


TEST_SIGNER: Callable | None = None  # Tests: ersetzt den Zertifikatspeicher von Windows (Fingerabdruck → Signierer)
TEST_CERTIFICATES: list | None = None  # Tests: angebotene Zertifikate


class SignError(EditorError):
    """Signieren nicht möglich – ``str()`` ist die Meldung für die Anwendenden."""


# Zertifikate -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class CertInfo:
    subject: str  # Name (CN), sonst der ganze Name
    issuer: str
    email: str
    not_before: datetime
    not_after: datetime
    serial: str
    thumbprint: str  # SHA-1 (wie in Windows angezeigt)
    self_signed: bool

    def valid_at(self, moment: datetime) -> bool:
        return self.not_before <= moment <= self.not_after


def cert_info(der: bytes) -> CertInfo:
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    cert = x509.load_der_x509_certificate(der)

    def common(name) -> str:
        values = name.get_attributes_for_oid(NameOID.COMMON_NAME)
        if values:
            return str(values[0].value)
        values = name.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
        return str(values[0].value) if values else name.rfc4514_string()

    emails = cert.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)
    email = str(emails[0].value) if emails else ""
    if not email:
        try:
            alt = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            names = alt.get_values_for_type(x509.RFC822Name)
            email = names[0] if names else ""
        except x509.ExtensionNotFound:
            pass
    return CertInfo(
        subject=common(cert.subject), issuer=common(cert.issuer), email=email,
        not_before=cert.not_valid_before_utc, not_after=cert.not_valid_after_utc,
        serial=format(cert.serial_number, "X"), thumbprint=hashlib.sha1(der).hexdigest().upper(),
        self_signed=cert.subject == cert.issuer,
    )


def can_sign(der: bytes) -> bool:
    """Zertifikat erlaubt Signaturen (Schlüsselverwendung »Digitale Signatur« bzw. »Nachweisbarkeit«, falls
    angegeben) und hat einen RSA- oder EC-Schlüssel."""
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, rsa

    cert = x509.load_der_x509_certificate(der)
    if not isinstance(cert.public_key(), (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
        return False
    try:
        usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return True
    return bool(usage.digital_signature or usage.content_commitment)


class Signer(Protocol):
    certificate: bytes  # DER
    chain: list[bytes]  # weitere Zertifikate (Zwischenstellen), DER

    def sign(self, data: bytes) -> bytes:
        """``data`` mit SHA-256 signieren (RSA PKCS#1 v1.5 bzw. ECDSA als DER)."""
        ...


class FileSigner:
    """Zertifikat mit privatem Schlüssel aus einer PKCS#12-Datei (.pfx/.p12)."""

    def __init__(self, data: bytes, password: str) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.serialization import pkcs12

        try:
            key, cert, extra = pkcs12.load_key_and_certificates(data, password.encode("utf-8") if password else None)
        except ValueError as exc:
            raise SignError("Das Kennwort ist falsch oder die Datei ist kein Zertifikat mit privatem Schlüssel (.pfx/.p12).") from exc
        if key is None or cert is None:
            raise SignError("Die Datei enthält kein Zertifikat mit privatem Schlüssel.")
        self._key = key
        self.certificate = cert.public_bytes(serialization.Encoding.DER)
        self.chain = [item.public_bytes(serialization.Encoding.DER) for item in (extra or []) if item != cert]

    def sign(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

        if isinstance(self._key, rsa.RSAPrivateKey):
            return self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        if isinstance(self._key, ec.EllipticCurvePrivateKey):
            return self._key.sign(data, ec.ECDSA(hashes.SHA256()))
        raise SignError("Dieser Schlüsseltyp wird nicht unterstützt (nur RSA und EC).")


# Signieren ---------------------------------------------------------------------------------------------------------

@dataclass
class SignOptions:
    reason: str = ""
    location: str = ""
    contact: str = ""
    visible_page: int = -1  # Seite mit sichtbarem Feld (-1: unsichtbar)
    visible_rect: tuple[float, float, float, float] | None = None  # PDF-Koordinaten, sonst unten rechts
    when: datetime | None = None  # Zeitpunkt (Tests); sonst jetzt


def sign_pdf(source: bytes, signer: Signer, options: SignOptions | None = None) -> bytes:
    """Das PDF ``source`` signieren; liefert die signierte Datei."""
    options = options or SignOptions()
    when = options.when or datetime.now(timezone.utc).astimezone()
    try:
        base = _prepared(source)
        update, contents_at = _update(base, signer, options, when)
    except (pikepdf.PdfError, ValueError, KeyError) as exc:
        raise SignError("Dieses PDF lässt sich nicht signieren (Aufbau nicht lesbar).") from exc
    data = bytearray(base + update)
    start = len(base) + contents_at  # Position von »<« vor dem Platzhalter
    end = start + 2 + CONTENTS_SIZE * 2
    ranges = [0, start, end, len(data) - end]
    _patch_byterange(data, ranges)
    digest = hashlib.sha256(bytes(data[:start]) + bytes(data[end:])).digest()
    cms = _cms(digest, signer, when)
    if len(cms) > CONTENTS_SIZE:
        raise SignError("Die Zertifikatskette ist zu groß für die Signatur.")
    data[start + 1:start + 1 + len(cms) * 2] = cms.hex().upper().encode("ascii")
    return bytes(data)


def _prepared(source: bytes) -> bytes:
    """Ohne vorhandene Signatur: einmal neu schreiben (einfache Querverweistabelle, keine Objektströme). Mit Signatur:
    unverändert – sonst würden die vorhandenen ungültig."""
    with pikepdf.open(io.BytesIO(source)) as pdf:
        if signatures_present(pdf):
            if not source.rstrip().endswith(b"%%EOF"):
                raise ValueError("Ende der Datei fehlt")
            return source if source.endswith(b"\n") else source + b"\n"
        out = io.BytesIO()
        pdf.save(out, object_stream_mode=pikepdf.ObjectStreamMode.disable, fix_metadata_version=False, qdf=False, static_id=False)
        data = out.getvalue()
    return data if data.endswith(b"\n") else data + b"\n"


def signatures_present(pdf: pikepdf.Pdf) -> bool:
    return any(True for _ in _signature_fields(pdf))


def _signature_fields(pdf: pikepdf.Pdf):
    form = pdf.Root.get("/AcroForm")
    if not isinstance(form, Dictionary):
        return
    todo = list(form.get("/Fields") or [])
    seen: set = set()
    while todo:
        item = todo.pop(0)
        if not isinstance(item, Dictionary):
            continue
        key = item.objgen if item.is_indirect else id(item)
        if key in seen:
            continue
        seen.add(key)
        if item.get("/FT") == Name.Sig and isinstance(item.get("/V"), Dictionary):
            yield item
        kids = item.get("/Kids")
        if isinstance(kids, Array):
            todo.extend(kids)


def _field_name(pdf: pikepdf.Pdf) -> str:
    taken = set()
    for item in pdf.acroform.fields if isinstance(pdf.Root.get("/AcroForm"), Dictionary) else []:
        taken.add(str(item.fully_qualified_name))
    index = 1
    while f"Signatur{index}" in taken:
        index += 1
    return f"Signatur{index}"


def _pdf_string(text: str) -> bytes:
    """Textstring für ein PDF: ASCII als Literal, sonst UTF-16 mit BOM (hexadezimal)."""
    if all(32 <= ord(char) < 127 for char in text):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return b"(" + escaped.encode("ascii") + b")"
    return b"<FEFF" + text.encode("utf-16-be").hex().upper().encode("ascii") + b">"


def _pdf_date(when: datetime) -> str:
    offset = when.utcoffset()
    if offset is None:
        return when.strftime("D:%Y%m%d%H%M%S") + "Z"
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return when.strftime("D:%Y%m%d%H%M%S") + f"{sign}{minutes // 60:02d}'{minutes % 60:02d}'"


BYTERANGE_PLACEHOLDER = b"/ByteRange [0 0000000000 0000000000 0000000000]"


def _update(base: bytes, signer: Signer, options: SignOptions, when: datetime) -> tuple[bytes, int]:
    """Inkrementelle Aktualisierung: Signaturwert, Feld mit Widget, Seite, Formular, Katalog; dazu die
    Querverweise. Liefert die Bytes und die Position des Platzhalters für /Contents darin."""
    pdf = pikepdf.open(io.BytesIO(base))
    try:
        info = cert_info(signer.certificate)
        size = int(pdf.trailer.Size)
        next_number = size
        objects: dict[int, bytes] = {}
        generations: dict[int, int] = {}

        def allocate() -> int:
            nonlocal next_number
            number = next_number
            next_number += 1
            return number

        sig_number = allocate()
        field_number = allocate()
        page_index = options.visible_page if 0 <= options.visible_page < len(pdf.pages) else 0
        page = pdf.pages[page_index]
        visible = 0 <= options.visible_page < len(pdf.pages)
        rect = (0.0, 0.0, 0.0, 0.0)
        appearance_number = None
        if visible:
            rect = options.visible_rect or _default_rect(page)
            appearance_number = allocate()
            font_number = allocate()
            objects[font_number] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
            objects[appearance_number] = _appearance(rect, info.subject, when, options.reason, font_number)

        sig = [b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter " + SUBFILTER.encode("ascii"),
               BYTERANGE_PLACEHOLDER,
               b"/Contents <" + b"0" * (CONTENTS_SIZE * 2) + b">",
               b"/M " + _pdf_string(_pdf_date(when)),
               b"/Name " + _pdf_string(info.subject)]
        if options.reason:
            sig.append(b"/Reason " + _pdf_string(options.reason))
        if options.location:
            sig.append(b"/Location " + _pdf_string(options.location))
        if options.contact:
            sig.append(b"/ContactInfo " + _pdf_string(options.contact))
        sig.append(b"/Prop_Build << /App << /Name /PDF#20Tool >> >> >>")
        objects[sig_number] = b"\n".join(sig)

        page_ref = f"{page.obj.objgen[0]} {page.obj.objgen[1]} R".encode("ascii")
        widget = [b"<< /Type /Annot /Subtype /Widget /FT /Sig",
                  b"/T " + _pdf_string(_field_name(pdf)),
                  f"/V {sig_number} 0 R".encode("ascii"),
                  b"/F " + (b"4" if visible else b"132"),
                  b"/P " + page_ref,
                  ("/Rect [%.2f %.2f %.2f %.2f]" % rect).encode("ascii")]
        if appearance_number is not None:
            widget.append(f"/AP << /N {appearance_number} 0 R >>".encode("ascii"))
        widget.append(b">>")
        objects[field_number] = b"\n".join(widget)

        field_ref = pdf.make_indirect(Dictionary())  # nur für die Verweise unten; die Nummer wird ersetzt
        # Seite: Widget in /Annots
        annots = page.obj.get("/Annots")
        if isinstance(annots, Array) and annots.is_indirect:
            annots.append(field_ref)
            objects[annots.objgen[0]] = _unparse(annots, field_ref, field_number)
            generations[annots.objgen[0]] = annots.objgen[1]
        else:
            current = Array(list(annots) if isinstance(annots, Array) else [])
            current.append(field_ref)
            page.obj.Annots = current
            objects[page.obj.objgen[0]] = _unparse(page.obj, field_ref, field_number)
            generations[page.obj.objgen[0]] = page.obj.objgen[1]
        # Formular: Feld in /Fields, SigFlags 3 (signiert, nur anhängen)
        form = pdf.Root.get("/AcroForm")
        if isinstance(form, Dictionary) and form.is_indirect:
            _add_field(form, field_ref, objects, generations, field_number)
            objects[form.objgen[0]] = _unparse(form, field_ref, field_number)
            generations[form.objgen[0]] = form.objgen[1]
        else:
            if not isinstance(form, Dictionary):
                form = Dictionary()
            form = Dictionary(dict(form.items()))
            _add_field(form, field_ref, objects, generations, field_number)
            pdf.Root.AcroForm = form
            objects[pdf.Root.objgen[0]] = _unparse(pdf.Root, field_ref, field_number)
            generations[pdf.Root.objgen[0]] = pdf.Root.objgen[1]
        for number in objects:
            generations.setdefault(number, 0)
        root_ref = f"{pdf.Root.objgen[0]} {pdf.Root.objgen[1]} R"
        info_ref = pdf.trailer.get("/Info")
        info_text = f" /Info {info_ref.objgen[0]} {info_ref.objgen[1]} R" if isinstance(info_ref, Dictionary) and info_ref.is_indirect else ""
        ids = pdf.trailer.get("/ID")
        id_text = ""
        if isinstance(ids, Array) and len(ids) == 2:
            id_text = " /ID [<%s> <%s>]" % (bytes(ids[0]).hex(), hashlib.md5(base[-4096:] + when.isoformat().encode()).hexdigest())
        prev = _startxref(base)
        stream_xref = re.match(rb"\s*\d+\s+\d+\s+obj", base[prev:prev + 64]) is not None
        xref_number = allocate() if stream_xref else None
    finally:
        pdf.close()

    out = bytearray()
    offsets: dict[int, int] = {}
    contents_at = -1
    for number in sorted(objects):
        offsets[number] = len(base) + len(out)
        head = f"{number} {generations[number]} obj\n".encode("ascii")
        body = objects[number]
        if number == sig_number:
            contents_at = len(out) + len(head) + body.index(b"/Contents <") + len(b"/Contents ")
        out += head + body + b"\nendobj\n"
    xref_at = len(base) + len(out)
    if xref_number is not None:  # das Original hat Querverweis-Ströme: die Aktualisierung auch
        offsets[xref_number] = xref_at
        generations[xref_number] = 0
        numbers = sorted(offsets)
        index, rows = [], b""
        for number in numbers:
            if index and number == index[-2] + index[-1]:
                index[-1] += 1
            else:
                index += [number, 1]
            rows += bytes([1]) + offsets[number].to_bytes(4, "big") + generations[number].to_bytes(2, "big")
        total = max(size, max(numbers) + 1)
        head = (f"{xref_number} 0 obj\n<< /Type /XRef /Size {total} /W [1 4 2] /Index [{' '.join(map(str, index))}] /Root {root_ref}{info_text}{id_text} /Prev {prev} /Length {len(rows)} >>\nstream\n").encode("ascii")
        out += head + rows + b"\nendstream\nendobj\n"
        out += f"startxref\n{xref_at}\n%%EOF\n".encode("ascii")
        return bytes(out), contents_at
    out += b"xref\n"
    numbers = sorted(offsets)
    groups: list[list[int]] = []
    for number in numbers:
        if groups and number == groups[-1][-1] + 1:
            groups[-1].append(number)
        else:
            groups.append([number])
    for group in groups:
        out += f"{group[0]} {len(group)}\n".encode("ascii")
        for number in group:
            out += f"{offsets[number]:010d} {generations[number]:05d} n\r\n".encode("ascii")
    total = max(size, max(numbers) + 1)
    out += f"trailer\n<< /Size {total} /Root {root_ref}{info_text}{id_text} /Prev {prev} >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    return bytes(out), contents_at


def _add_field(form: Dictionary, field_ref, objects: dict, generations: dict, field_number: int) -> None:
    fields = form.get("/Fields")
    if isinstance(fields, Array) and fields.is_indirect:
        fields.append(field_ref)
        objects[fields.objgen[0]] = _unparse(fields, field_ref, field_number)
        generations[fields.objgen[0]] = fields.objgen[1]
    else:
        current = Array(list(fields) if isinstance(fields, Array) else [])
        current.append(field_ref)
        form.Fields = current
    form.SigFlags = 3


def _unparse(obj, field_ref, field_number: int) -> bytes:
    """Objekt als PDF-Text; der Verweis auf das vorläufige Feld wird durch die richtige Nummer ersetzt."""
    text = obj.unparse(resolved=True)
    placeholder = f"{field_ref.objgen[0]} {field_ref.objgen[1]} R".encode("ascii")
    return re.sub(rb"(?<![0-9])" + re.escape(placeholder), f"{field_number} 0 R".encode("ascii"), text)


def _startxref(data: bytes) -> int:
    found = data.rfind(b"startxref")
    if found < 0:
        raise ValueError("startxref fehlt")
    return int(data[found + 9:].split()[0])


def _patch_byterange(data: bytearray, ranges: list[int]) -> None:
    at = data.find(BYTERANGE_PLACEHOLDER, ranges[1] - 200 - len(BYTERANGE_PLACEHOLDER) if ranges[1] > 300 else 0)
    if at < 0:
        at = data.rfind(BYTERANGE_PLACEHOLDER)
    text = b"/ByteRange [%d %d %d %d]" % tuple(ranges)
    data[at:at + len(BYTERANGE_PLACEHOLDER)] = text.ljust(len(BYTERANGE_PLACEHOLDER), b" ")


def _default_rect(page) -> tuple[float, float, float, float]:
    box = [float(value) for value in page.mediabox]
    width, height = 220.0, 64.0
    right = box[2] - 36
    bottom = box[1] + 36
    return (right - width, bottom, right, bottom + height)


def _appearance(rect, name: str, when: datetime, reason: str, font_number: int) -> bytes:
    width, height = rect[2] - rect[0], rect[3] - rect[1]

    def text(value: str) -> bytes:
        raw = value.encode("cp1252", "replace")
        return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

    lines = [("Digital signiert von", 7.5), (name, 10.0), ("Datum: " + when.strftime("%d.%m.%Y %H:%M"), 7.5)]
    if reason:
        lines.append(("Grund: " + reason, 7.5))
    ops = [b"q 0.94 0.96 1 rg 0 0 %.2f %.2f re f 0.20 0.35 0.65 RG 0.8 w 0.4 0.4 %.2f %.2f re S Q" % (width, height, width - 0.8, height - 0.8)]
    y = height - 6
    for value, size in lines:
        y -= size + 2.5
        if y < 2:
            break
        ops.append(b"BT /F1 %.1f Tf 0.1 0.1 0.1 rg 6 %.2f Td " % (size, y) + text(value) + b" Tj ET")
    stream = b"\n".join(ops)
    return (b"<< /Type /XObject /Subtype /Form /BBox [0 0 %.2f %.2f] /Resources << /Font << /F1 %d 0 R >> >> /Length %d >>\nstream\n"
            % (width, height, font_number, len(stream)) + stream + b"\nendstream")


def _cms(digest: bytes, signer: Signer, when: datetime) -> bytes:
    from asn1crypto import algos, cms, tsp, x509 as asn1x509  # noqa: F401 - tsp meldet signing_certificate_v2 an

    certificate = asn1x509.Certificate.load(signer.certificate)
    chain = [asn1x509.Certificate.load(item) for item in signer.chain]
    cert_hash = hashlib.sha256(signer.certificate).digest()
    signing_certificate = {
        "certs": [{"cert_hash": cert_hash, "issuer_serial": {
            "issuer": [asn1x509.GeneralName({"directory_name": certificate.issuer})],
            "serial_number": certificate.serial_number}}],
    }
    attrs = cms.CMSAttributes([
        cms.CMSAttribute({"type": "content_type", "values": ["data"]}),
        cms.CMSAttribute({"type": "message_digest", "values": [digest]}),
        cms.CMSAttribute({"type": "signing_certificate_v2", "values": [signing_certificate]}),
    ])
    key_algorithm = certificate.public_key.algorithm
    if key_algorithm == "rsa":
        signature_algorithm = {"algorithm": "rsassa_pkcs1v15"}
    elif key_algorithm == "ec":
        signature_algorithm = {"algorithm": "sha256_ecdsa"}
    else:
        raise SignError("Dieser Schlüsseltyp wird nicht unterstützt (nur RSA und EC).")
    try:
        signature = signer.sign(attrs.dump())
    except SignError:
        raise
    except Exception as exc:  # noqa: BLE001 - Chipkarte gezogen, PIN abgebrochen, Schlüssel gesperrt …
        raise SignError("Der private Schlüssel konnte nicht signieren (PIN abgebrochen oder Zugriff verweigert).") from exc
    signer_info = cms.SignerInfo({
        "version": "v1",
        "sid": cms.SignerIdentifier({"issuer_and_serial_number": cms.IssuerAndSerialNumber({
            "issuer": certificate.issuer, "serial_number": certificate.serial_number})}),
        "digest_algorithm": algos.DigestAlgorithm({"algorithm": "sha256"}),
        "signed_attrs": attrs,
        "signature_algorithm": algos.SignedDigestAlgorithm(signature_algorithm),
        "signature": signature,
    })
    signed_data = cms.SignedData({
        "version": "v1",
        "digest_algorithms": [algos.DigestAlgorithm({"algorithm": "sha256"})],
        "encap_content_info": {"content_type": "data"},
        "certificates": [certificate] + chain,
        "signer_infos": [signer_info],
    })
    return cms.ContentInfo({"content_type": "signed_data", "content": signed_data}).dump()


# Prüfen ------------------------------------------------------------------------------------------------------------

@dataclass
class SignatureReport:
    field: str
    status: str  # VALID, CHANGED, INVALID, UNKNOWN
    signer: str = ""
    email: str = ""
    issuer: str = ""
    when: datetime | None = None
    reason: str = ""
    location: str = ""
    page: int = -1
    visible: bool = False
    trust: str = ""  # "trusted", "untrusted", "expired", "revoked", "unchecked"
    trust_detail: str = ""
    cert: CertInfo | None = None
    subfilter: str = ""
    covers_whole: bool = False
    detail: str = ""
    certificates: list[bytes] = field(default_factory=list)


def verify_pdf(data: bytes, trust: Callable[[bytes, list[bytes], datetime | None], tuple[str, str]] | None = None) -> list[SignatureReport]:
    """Alle Signaturen von ``data`` prüfen. ``trust(cert, weitere, zeitpunkt)`` → (Vertrauen, Erklärung); ohne:
    unter Windows der Zertifikatspeicher, sonst »nicht geprüft«."""
    if trust is None:
        trust = default_trust()
    reports = []
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pages = {page.obj.objgen: index for index, page in enumerate(pdf.pages)}
        for item in _signature_fields(pdf):
            reports.append(_verify_one(data, item, pages, trust))
    return reports


def _text(value) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except (TypeError, ValueError):
        return ""


def parse_pdf_date(value: str) -> datetime | None:
    match = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz+\-])?(\d{2})?'?(\d{2})?", value or "")
    if not match:
        return None
    parts = [int(part) if part else default for part, default in zip(match.groups()[:6], (0, 1, 1, 0, 0, 0))]
    try:
        moment = datetime(*parts)
    except ValueError:
        return None
    sign, hours, minutes = match.group(7), match.group(8), match.group(9)
    from datetime import timedelta

    if sign in ("+", "-"):
        delta = timedelta(hours=int(hours or 0), minutes=int(minutes or 0))
        return moment.replace(tzinfo=timezone(delta if sign == "+" else -delta))
    if sign in ("Z", "z"):
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone()


def _verify_one(data: bytes, item, pages: dict, trust) -> SignatureReport:
    value = item.V
    report = SignatureReport(field=_text(item.get("/T")), status=UNKNOWN)
    report.subfilter = str(value.get("/SubFilter") or "")
    report.reason = _text(value.get("/Reason"))
    report.location = _text(value.get("/Location"))
    report.signer = _text(value.get("/Name"))
    report.when = parse_pdf_date(_text(value.get("/M")))
    page = item.get("/P")
    if isinstance(page, Dictionary):
        report.page = pages.get(page.objgen, -1)
    rect = item.get("/Rect")
    if isinstance(rect, Array) and len(rect) == 4:
        try:
            values = [float(number) for number in rect]
            report.visible = values[2] - values[0] > 1 and values[3] - values[1] > 1
        except (TypeError, ValueError):
            pass
    if report.subfilter not in VERIFIABLE:
        report.detail = "Dieses Signaturformat prüft PDF Tool nicht."
        return report
    try:
        ranges = [int(number) for number in value.ByteRange]
        contents = bytes(value.Contents)
    except (AttributeError, TypeError, ValueError, pikepdf.PdfError):
        report.status, report.detail = INVALID, "Die Signatur ist beschädigt."
        return report
    if len(ranges) != 4 or ranges[0] != 0 or ranges[1] < 0 or ranges[2] < ranges[1] or ranges[2] + ranges[3] > len(data):
        report.status, report.detail = INVALID, "Die Signatur ist beschädigt (Bereich ungültig)."
        return report
    signed = data[:ranges[1]] + data[ranges[2]:ranges[2] + ranges[3]]
    report.covers_whole = ranges[2] + ranges[3] >= len(data.rstrip(b"\r\n\0 ")) - 0
    try:
        status, detail, cert, certificates, signing_time = _check_cms(contents, signed)
    except Exception:  # noqa: BLE001 - beschädigtes oder unbekanntes CMS
        report.status, report.detail = INVALID, "Die Signatur ist beschädigt."
        return report
    report.status, report.detail = status, detail
    report.certificates = certificates
    if cert is not None:
        info = cert_info(cert)
        report.cert = info
        report.signer = info.subject or report.signer
        report.email = info.email
        report.issuer = info.issuer
        if report.when is None:
            report.when = signing_time
    if report.status == VALID and not report.covers_whole:
        report.status = CHANGED
        report.detail = "Die Signatur ist gültig, das Dokument wurde danach aber geändert (z. B. Formular ausgefüllt oder weiter signiert)."
    if cert is not None and report.status in (VALID, CHANGED):
        report.trust, report.trust_detail = trust(cert, certificates, report.when)
    return report


def _check_cms(contents: bytes, signed: bytes):
    from asn1crypto import cms, tsp  # noqa: F401 - tsp meldet signing_certificate_v2 an
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

    info = cms.ContentInfo.load(contents.rstrip(b"\0") if contents.endswith(b"\0\0") else contents, strict=False)
    signed_data = info["content"]
    certificates = [cert.chosen.dump() for cert in signed_data["certificates"] if cert.name == "certificate"]
    signer_info = signed_data["signer_infos"][0]
    sid = signer_info["sid"]
    cert_der = None
    for der in certificates:
        candidate = cms.Certificate.load(der)
        if sid.name == "issuer_and_serial_number":
            if candidate.issuer == sid.chosen["issuer"] and candidate.serial_number == sid.chosen["serial_number"].native:
                cert_der = der
                break
        elif candidate.key_identifier == sid.chosen.native:
            cert_der = der
            break
    if cert_der is None:
        return INVALID, "Das Zertifikat des Unterzeichners fehlt in der Signatur.", None, certificates, None
    algorithm = signer_info["digest_algorithm"]["algorithm"].native
    hashers = {"sha256": hashlib.sha256, "sha384": hashlib.sha384, "sha512": hashlib.sha512, "sha1": hashlib.sha1}
    crypto_hashes = {"sha256": hashes.SHA256(), "sha384": hashes.SHA384(), "sha512": hashes.SHA512(), "sha1": hashes.SHA1()}
    if algorithm not in hashers:
        return UNKNOWN, "Dieses Prüfverfahren kennt PDF Tool nicht.", cert_der, certificates, None
    digest = hashers[algorithm](signed).digest()
    attrs = signer_info["signed_attrs"]
    signing_time = None
    if attrs.native is not None and len(attrs):
        message_digest = None
        for attr in attrs:
            if attr["type"].native == "message_digest":
                message_digest = attr["values"][0].native
            elif attr["type"].native == "signing_time":
                signing_time = attr["values"][0].native
        if message_digest != digest:
            return INVALID, "Das Dokument wurde nach dem Signieren verändert – der Inhalt passt nicht mehr zur Signatur.", cert_der, certificates, signing_time
        payload = _set_of(attrs)
    else:
        payload = signed
    public_key = x509.load_der_x509_certificate(cert_der).public_key()
    signature = signer_info["signature"].native
    sig_algorithm = signer_info["signature_algorithm"]["algorithm"].native
    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            if sig_algorithm == "rsassa_pss":
                params = signer_info["signature_algorithm"]["parameters"]
                pss_hash = crypto_hashes.get(params["hash_algorithm"]["algorithm"].native, hashes.SHA256())
                public_key.verify(signature, payload, padding.PSS(padding.MGF1(pss_hash), params["salt_length"].native), pss_hash)
            else:
                public_key.verify(signature, payload, padding.PKCS1v15(), crypto_hashes[algorithm])
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, payload, ec.ECDSA(crypto_hashes[algorithm]))
        else:
            return UNKNOWN, "Dieser Schlüsseltyp wird nicht geprüft.", cert_der, certificates, signing_time
    except InvalidSignature:
        return INVALID, "Die Signatur ist ungültig – sie passt nicht zum Zertifikat.", cert_der, certificates, signing_time
    return VALID, "Das Dokument wurde seit dem Signieren nicht verändert.", cert_der, certificates, signing_time


def _set_of(attrs) -> bytes:
    """Die signierten Attribute so, wie sie signiert wurden: als SET OF (Tag 0x31 statt [0])."""
    raw = attrs.dump()
    return b"\x31" + raw[1:]


def default_trust():
    import sys

    if sys.platform == "win32":
        try:
            from . import winsign

            return winsign.trust
        except (ImportError, OSError):
            pass
    return lambda cert, extra, when: ("unchecked", "Ob das Zertifikat vertrauenswürdig ist, prüft PDF Tool nur unter Windows.")


def store_certificates() -> list[dict]:
    """Zertifikate aus Windows für den Dialog (unter Linux leer)."""
    if TEST_CERTIFICATES is not None:
        found = TEST_CERTIFICATES
    else:
        import sys

        if sys.platform != "win32":
            return []
        try:
            from . import winsign

            found = winsign.certificates()
        except (ImportError, OSError):
            return []
    return [{"thumbprint": item.thumbprint, "subject": item.subject, "issuer": item.issuer, "email": item.email,
             "until": item.not_after.astimezone().strftime("%d.%m.%Y"), "selfSigned": item.self_signed} for item in found]


# Texte für die Oberfläche --------------------------------------------------------------------------------------------

def summary(report: SignatureReport) -> dict:
    """Eine Signatur für die Oberfläche: Ampel, Überschrift, Zeilen."""
    if report.status == VALID and report.trust == "trusted":
        tone, title = "success", "Gültig"
    elif report.status in (VALID, CHANGED):
        tone = "warning" if report.status == CHANGED or report.trust != "trusted" else "success"
        title = "Gültig, aber danach geändert" if report.status == CHANGED else "Unverändert, Zertifikat nicht bestätigt"
        if report.status == VALID and report.trust == "unchecked":
            title = "Unverändert"
    elif report.status == INVALID:
        tone, title = "error", "Ungültig"
    else:
        tone, title = "info", "Nicht geprüft"
    lines = []
    if report.signer:
        lines.append(("Unterzeichnet von", report.signer + (f" <{report.email}>" if report.email else "")))
    if report.when is not None:
        lines.append(("Zeitpunkt", report.when.astimezone().strftime("%d.%m.%Y, %H:%M Uhr")))
    if report.reason:
        lines.append(("Grund", report.reason))
    if report.location:
        lines.append(("Ort", report.location))
    if report.issuer:
        lines.append(("Ausgestellt von", report.issuer))
    if report.cert is not None:
        lines.append(("Zertifikat gültig", f"{report.cert.not_before.astimezone():%d.%m.%Y} bis {report.cert.not_after.astimezone():%d.%m.%Y}"))
    if report.page >= 0 and report.visible:
        lines.append(("Feld", f"Seite {report.page + 1}"))
    return {
        "field": report.field, "status": report.status, "tone": tone, "title": title, "detail": report.detail,
        "trust": report.trust, "trustDetail": report.trust_detail, "page": report.page, "visible": report.visible,
        "lines": [{"label": label, "value": value} for label, value in lines],
    }
