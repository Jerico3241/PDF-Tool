"""Ein geöffnetes PDF: Stand der Bearbeitung (pikepdf/qpdf) und Darstellung (PDFium).

* Die Datei wird einmal vollständig gelesen und nicht offen gehalten – so lässt sie sich beim
  Speichern unter Windows atomar ersetzen, und Änderungen durch andere Programme fallen auf
  (``FileStamp``).
* **pikepdf** hält den Stand. Jede Änderung erhöht ``revision``; ``view()`` liefert dann ein
  PDFium-Dokument dieses Stands (im Speicher serialisiert, nie auf die Platte). Bis zur ersten
  Änderung zeigt PDFium die Originalbytes.
* Berechtigungen der Datei werden respektiert, nie umgangen: Ohne Besitzerpasswort gelten die
  Einschränkungen des Erstellers (Bearbeiten, Anmerkungen, Formulare, Drucken, Kopieren).
* Das Passwort bleibt nur im Speicher.

Alle Methoden laufen im Engine-Thread des Editors; PDFium-Aufrufe nur unter ``PDFIUM_LOCK``.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from pathlib import Path

import pikepdf

from pdfium_lock import PDFIUM_LOCK

from .errors import DamagedDocument, EditorError, NotAPdf, PasswordRequired, ReadOnlyDocument
from .geometry import PageGeometry, Rect, rotation_of

DEFAULT_MEDIABOX: Rect = (0.0, 0.0, 612.0, 792.0)  # US Letter – Standard laut PDF-Norm
RESTRICTED_REASON = "Der Ersteller dieses PDFs hat das Bearbeiten nicht erlaubt."
HEADER_WINDOW = 1024  # »%PDF-« muss in den ersten 1024 Bytes stehen (wie bei Acrobat/PDFium)
TEXTPAGE_CACHE = 24  # geladene Textseiten je Dokument


@dataclass(frozen=True)
class FileStamp:
    """Größe und Änderungszeit der Datei beim Öffnen bzw. Speichern."""

    size: int
    mtime_ns: int

    @classmethod
    def of(cls, path: Path) -> "FileStamp | None":
        try:
            info = os.stat(path)
        except OSError:
            return None
        return cls(info.st_size, info.st_mtime_ns)


@dataclass(frozen=True)
class Permissions:
    """Was die Datei erlaubt (ohne Verschlüsselung: alles)."""

    edit: bool = True  # Inhalte ändern, Seiten organisieren
    annotate: bool = True
    fill_forms: bool = True
    assemble: bool = True  # Seiten einfügen, löschen, drehen
    print: bool = True
    copy: bool = True

    def summary(self) -> list[str]:
        names = {"edit": "Bearbeiten", "annotate": "Kommentieren", "fill_forms": "Formulare ausfüllen", "assemble": "Seiten organisieren", "print": "Drucken", "copy": "Text kopieren"}
        return [label for key, label in names.items() if not getattr(self, key)]


@dataclass
class OpenReport:
    """Was beim Öffnen auffiel – für Hinweise in der Oberfläche (keine Inhalte)."""

    repaired: bool = False  # qpdf hat Strukturfehler beim Lesen korrigiert
    warnings: list[str] = field(default_factory=list)
    signed: int = 0  # Anzahl Signaturen
    javascript: bool = False  # enthält JavaScript (wird nie ausgeführt)
    xfa: bool = False  # XFA-Formular (nur der AcroForm-Teil ist bearbeitbar)


class EditorDocument:
    """Ein geöffnetes PDF. Erzeugen über ``open()`` bzw. ``from_bytes()``."""

    def __init__(self, pdf: pikepdf.Pdf, data: bytes | None, *, path: Path | None, name: str, password: str | None, stamp: FileStamp | None, report: OpenReport) -> None:
        self.pdf = pdf
        self.path = path
        self.name = name
        self.password = password
        self.stamp = stamp
        self.report = report
        self.revision = 0  # zählt jede Änderung am pikepdf-Stand (Darstellung, Zwischenspeicher)
        # Standnummer des Inhalts (``commands``) und die zuletzt gespeicherte: gleich = unverändert –
        # auch wenn Rückgängig zum gespeicherten Stand zurückführt
        self.state = 0
        self.saved_state = 0
        self._data = data  # Originalbytes – Quelle der Darstellung bis zur ersten Änderung
        self._view = None
        self._view_bytes: bytes | None = None
        self._view_revision = -1
        self._textpages: dict[int, object] = {}
        self._geometry: dict[int, PageGeometry] = {}
        self.permissions = _permissions(pdf)
        self.read_only_reason = "" if self.permissions.edit else RESTRICTED_REASON
        # Kennwortschutz für das nächste Speichern (``protect``): ``None`` = wie die Datei
        self.protection = None
        self.closed = False
        # Quellen eingefügter Seiten (andere PDFs): qpdf liest deren Stream-Daten erst beim
        # Schreiben – sie bleiben deshalb geöffnet, solange das Dokument offen ist.
        self._sources: list[pikepdf.Pdf] = []

    # Öffnen ---------------------------------------------------------------------------------
    @classmethod
    def open(cls, path: str | os.PathLike, password: str | None = None) -> "EditorDocument":
        path = Path(path)
        stamp = FileStamp.of(path)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise EditorError(f"Die Datei kann nicht gelesen werden ({exc.strerror or 'Zugriff verweigert'}).") from exc
        return cls.from_bytes(data, name=path.name, path=path, password=password, stamp=stamp)

    @classmethod
    def from_bytes(cls, data: bytes, *, name: str, path: Path | None = None, password: str | None = None, stamp: FileStamp | None = None) -> "EditorDocument":
        if b"%PDF-" not in data[:HEADER_WINDOW]:
            raise NotAPdf()
        report = OpenReport()
        try:
            pdf = pikepdf.open(io.BytesIO(data), password=password or "")
        except pikepdf.PasswordError as exc:
            raise PasswordRequired(wrong=bool(password)) from exc
        except (pikepdf.PdfError, ValueError, RuntimeError) as exc:
            raise DamagedDocument(type(exc).__name__ + ": " + str(exc)[:240]) from exc
        try:
            warnings = list(pdf.get_warnings())
        except Exception as exc:  # noqa: BLE001 - Warnungen sind nur ein Hinweis
            _noted("Warnungen von qpdf nicht lesbar", exc)
            warnings = []
        report.repaired = bool(warnings)
        report.warnings = [str(w)[:200] for w in warnings[:20]]
        try:
            pages = len(pdf.pages)
        except (pikepdf.PdfError, RuntimeError) as exc:
            pdf.close()
            raise DamagedDocument("Seitenbaum: " + str(exc)[:240]) from exc
        if pages == 0:
            pdf.close()
            raise DamagedDocument("Das Dokument enthält keine lesbaren Seiten.")
        # Zweite Meinung: PDFium muss dieselbe Datei darstellen können
        import pypdfium2 as pdfium

        with PDFIUM_LOCK:
            try:
                probe = pdfium.PdfDocument(data, password=password or None)
            except pdfium.PdfiumError as exc:
                pdf.close()
                if "password" in str(exc).lower():
                    raise PasswordRequired(wrong=bool(password)) from exc
                raise DamagedDocument("PDFium: " + str(exc)[:240]) from exc
            try:
                rendered = len(probe)
            finally:
                probe.close()
        _inspect(pdf, report)
        document = cls(pdf, data, path=path, name=name, password=password, stamp=stamp, report=report)
        if rendered != pages:
            document.read_only_reason = "Die Seitenstruktur dieses PDFs ist fehlerhaft. Bitte zuerst »PDF reparieren« verwenden."
            report.repaired = True
        return document

    # Zustand ---------------------------------------------------------------------------------
    @property
    def dirty(self) -> bool:
        return self.state != self.saved_state

    @property
    def read_only(self) -> bool:
        return bool(self.read_only_reason)

    @property
    def encrypted(self) -> bool:
        """Verschlüsselt gespeichert – wie die Datei oder wie der festgelegte Kennwortschutz."""
        if self.protection is not None:
            return self.protection.enabled
        return bool(self.pdf.is_encrypted)

    @property
    def save_password(self) -> str | None:
        """Kennwort, mit dem sich der gespeicherte Stand öffnen lässt (Prüfung nach dem Schreiben)."""
        if self.protection is not None:
            return self.protection.effective_owner or None
        return self.password

    def original_bytes(self) -> bytes:
        """Die Datei, wie sie geöffnet wurde (verschlüsselt wie auf der Platte)."""
        if self._data is not None:
            return self._data
        buffer = io.BytesIO()
        self.pdf.save(buffer, encryption=True if self.pdf.is_encrypted else False, fix_metadata_version=False)
        return buffer.getvalue()

    @property
    def page_count(self) -> int:
        return len(self.pdf.pages)

    def ensure_editable(self, what: str = "edit") -> None:
        """Wirft ``ReadOnlyDocument``, wenn die Datei diese Art Bearbeitung nicht erlaubt."""
        if self.read_only_reason and what in ("edit", "assemble"):
            raise ReadOnlyDocument(self.read_only_reason)
        if not getattr(self.permissions, what, True):
            raise ReadOnlyDocument("Die Berechtigungen dieses PDFs erlauben das nicht.")

    def touch(self) -> None:
        """Nach jeder Änderung des pikepdf-Stands: Darstellung und Zwischenspeicher verwerfen."""
        self.revision += 1
        self._geometry.clear()

    def mark_saved(self, path: Path, stamp: FileStamp | None) -> None:
        self.path = path
        self.name = path.name
        self.stamp = stamp
        self.saved_state = self.state

    # Geometrie --------------------------------------------------------------------------------
    def geometry(self, index: int) -> PageGeometry:
        cached = self._geometry.get(index)
        if cached is None:
            cached = self._geometry[index] = page_geometry(self.pdf.pages[index])
        return cached

    # Darstellung (PDFium) -----------------------------------------------------------------------
    def view(self):
        """PDFium-Dokument des aktuellen Stands. Nur unter ``PDFIUM_LOCK`` aufrufen."""
        if self._view is not None and self._view_revision == self.revision:
            return self._view
        import pypdfium2 as pdfium

        self._close_view()
        if self.revision == 0 and self._data is not None:
            data, password = self._data, self.password
        else:
            data, password = self.serialize(for_view=True), None
        self._view = pdfium.PdfDocument(data, password=password or None)
        try:
            self._view.init_forms()  # Formularfelder mit ihren Werten darstellen (vor dem ersten Laden einer Seite)
        except Exception as exc:  # noqa: BLE001 - ohne Formularumgebung erscheinen nur die gespeicherten Erscheinungsbilder
            _noted("Formularumgebung von PDFium nicht verfügbar", exc)
        self._view_bytes = data  # PDFium liest aus diesem Puffer – solange gültig halten
        self._view_revision = self.revision
        return self._view

    def textpage(self, index: int):
        """PDFium-Textseite (Zeichen, Positionen) des aktuellen Stands – unter ``PDFIUM_LOCK``.

        Die zuletzt benutzten ``TEXTPAGE_CACHE`` Seiten bleiben geladen (Suche, Auswahl, Bearbeiten)."""
        view = self.view()
        entry = self._textpages.pop(index, None)
        if entry is None:
            page = view[index]
            entry = (page, page.get_textpage())
            while len(self._textpages) >= TEXTPAGE_CACHE:
                _old_index, (old_page, old_text) = next(iter(self._textpages.items()))
                del self._textpages[_old_index]
                old_text.close()
                old_page.close()
        self._textpages[index] = entry  # zuletzt benutzt ans Ende
        return entry[1]

    def page_object(self, index: int):
        """Geladene PDFium-Seite (zur Textseite gehörig) – unter ``PDFIUM_LOCK``."""
        self.textpage(index)
        return self._textpages[index][0]

    def serialize(self, *, for_view: bool = False, keep_encryption: bool = False) -> bytes:
        """Aktuellen Stand als PDF-Bytes. Für die Darstellung schnell und ohne Verschlüsselung
        (bleibt im Speicher); zum Speichern mit Kompression und – auf Wunsch – mit der
        Verschlüsselung der Datei (Besitzerpasswort und Berechtigungen bleiben erhalten).

        Immer ``fix_metadata_version=False``: Sonst liest pikepdf beim Schreiben die XMP-Metadaten
        mit lxml, um dort die PDF-Version nachzutragen – lxml gehört nicht zur Laufzeit der App
        (runtime-requirements.txt), und jedes PDF mit XMP-Metadaten ließe sich nicht speichern.
        Die XMP-Metadaten bleiben deshalb unverändert (Eigenschaften ändern: ``metadata.update``).

        Ein festgelegter Kennwortschutz (``protection``) ersetzt beim Speichern die Verschlüsselung der
        Datei – auch bei allen weiteren Speichervorgängen."""
        buffer = io.BytesIO()
        if for_view:
            self.pdf.save(buffer, encryption=False, compress_streams=False, fix_metadata_version=False, object_stream_mode=pikepdf.ObjectStreamMode.preserve)
        else:
            self.pdf.save(buffer, encryption=self._encryption(keep_encryption), compress_streams=True, fix_metadata_version=False, object_stream_mode=pikepdf.ObjectStreamMode.preserve)
        return buffer.getvalue()

    def _encryption(self, keep: bool):
        if not keep:
            return False
        if self.protection is not None:
            return self.protection.encryption() if self.protection.enabled else False
        return True if self.pdf.is_encrypted else False

    def _close_view(self) -> None:
        for page, textpage in self._textpages.values():
            try:
                textpage.close()
                page.close()
            except Exception as exc:  # noqa: BLE001 - schon geschlossen
                _noted("Seite der Darstellung schließen", exc, cleanup=True)
        self._textpages.clear()
        if self._view is not None:
            try:
                self._view.close()
            except Exception as exc:  # noqa: BLE001 - schon geschlossen
                _noted("Darstellung schließen", exc, cleanup=True)
        self._view = None
        self._view_bytes = None
        self._view_revision = -1

    def adopt(self, source: pikepdf.Pdf) -> None:
        """Eine PDF, aus der Seiten übernommen wurden, bis zum Schließen offen halten."""
        if all(source is not known for known in self._sources):
            self._sources.append(source)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with PDFIUM_LOCK:
            self._close_view()
        try:
            self.pdf.close()
        except Exception as exc:  # noqa: BLE001 - schon geschlossen
            _noted("Dokument schließen", exc, cleanup=True)
        for source in self._sources:
            try:
                source.close()
            except Exception as exc:  # noqa: BLE001 - schon geschlossen
                _noted("Quelldokument schließen", exc, cleanup=True)
        self._sources.clear()
        self._data = None
        self.password = None


# Hilfen --------------------------------------------------------------------------------------
def inherited(obj: pikepdf.Object, key: str):
    """Seitenattribut samt Vererbung über ``/Parent`` (MediaBox, CropBox, Rotate, Resources)."""
    seen = 0
    while obj is not None and seen < 64:
        try:
            if key in obj:
                return obj[key]
            obj = obj.get("/Parent")
        except (pikepdf.PdfError, TypeError, AttributeError):
            return None
        seen += 1
    return None


def _box(value) -> Rect | None:
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    if len(numbers) != 4:
        return None
    x0, y0, x1, y1 = numbers
    box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    return box if box[2] - box[0] > 0.5 and box[3] - box[1] > 0.5 else None


def page_geometry(page: pikepdf.Page) -> PageGeometry:
    obj = page.obj
    media = _box(inherited(obj, "/MediaBox")) or DEFAULT_MEDIABOX
    crop = _box(inherited(obj, "/CropBox")) or media
    crop = (max(crop[0], media[0]), max(crop[1], media[1]), min(crop[2], media[2]), min(crop[3], media[3]))
    if crop[2] - crop[0] <= 0.5 or crop[3] - crop[1] <= 0.5:
        crop = media
    return PageGeometry(crop=crop, rotation=rotation_of(inherited(obj, "/Rotate")))


def _permissions(pdf: pikepdf.Pdf) -> Permissions:
    if not pdf.is_encrypted or getattr(pdf, "owner_password_matched", False):
        return Permissions()
    allow = pdf.allow
    return Permissions(
        edit=bool(allow.modify_other),
        annotate=bool(allow.modify_annotation),
        fill_forms=bool(allow.modify_form or allow.modify_annotation),
        assemble=bool(allow.modify_assembly or allow.modify_other),
        print=bool(allow.print_lowres or allow.print_highres),
        copy=bool(allow.extract),
    )


def _inspect(pdf: pikepdf.Pdf, report: OpenReport) -> None:
    """Signaturen, JavaScript und XFA erkennen (nur Strukturen, keine Inhalte)."""
    root = pdf.Root
    try:
        form = root.get("/AcroForm")
        if form is not None:
            report.xfa = "/XFA" in form
            report.signed = sum(1 for item in _fields(form.get("/Fields")) if item.get("/FT") == pikepdf.Name.Sig and item.get("/V") is not None)
    except (pikepdf.PdfError, TypeError, AttributeError):
        pass
    try:
        names = root.get("/Names")
        report.javascript = bool(names is not None and "/JavaScript" in names)
        action = root.get("/OpenAction")
        if isinstance(action, pikepdf.Dictionary) and action.get("/S") == pikepdf.Name.JavaScript:
            report.javascript = True
        if "/AA" in root:
            report.javascript = True
    except (pikepdf.PdfError, TypeError, AttributeError):
        pass


def _fields(fields, depth: int = 0):
    if fields is None or depth > 32:
        return
    for item in fields:
        if not isinstance(item, pikepdf.Dictionary):
            continue
        yield item
        kids = item.get("/Kids")
        if kids is not None:
            yield from _fields(kids, depth + 1)


def _noted(action: str, exc: BaseException, *, cleanup: bool = False) -> None:
    """Fehler ohne Folgen für das Dokument (Hinweise, Aufräumen schon geschlossener Teile): kein Abbruch,
    aber im Protokoll (Bereich »pdf«, nur die Art des Fehlers – nie Inhalte). Aufräumen nur auf Stufe DEBUG."""
    from diagnostics.applog import PDF, get

    log = get(PDF)
    (log.debug if cleanup else log.info)("%s: %s", action, type(exc).__name__)
