"""Textkern von Novadesk – ein eigener Prozess, der Texte (Word, OpenDocument, RTF) mit LibreOfficeKit bearbeitet.

Novadesk startet diese Datei mit seinem eigenen Python (nicht im Python von LibreOffice und nicht im Prozess der
Oberfläche): ``python -I kernel.py <program-Ordner von LibreOffice> <Profil-Ordner> <Port-Datei>``. Der Kern lädt
LibreOfficeKit aus dem mitgelieferten LibreOffice (``sofficeapp.dll``/``mergedlo.dll`` bzw. ``libmergedlo.so``),
öffnet einen Server auf 127.0.0.1 (zufälliger Port, in die Port-Datei geschrieben) und bedient genau eine Verbindung:
die von Novadesk, die sich zuerst mit dem Schlüssel aus ``NOVADESK_TEXT_SCHLUESSEL`` ausweisen muss. Endet sie, endet
der Kern.

Protokoll: Anfragen sind JSON-Zeilen ``{"id", "cmd", "args"}``. Antworten ``{"id", "ok": true, "result"}`` bzw.
``{"id", "ok": false, "error", "code"}``; trägt eine Antwort ``"bytes": n``, folgen ihr n Bytes (Kacheln: BGRA,
vormultipliziert). Ereignisse von LibreOfficeKit kommen ungefragt als ``{"event": Nummer, "doc", "payload"}``.
Koordinaten sind Twips (1/1440 Zoll).

Nur Standardbibliothek und ``ctypes`` – keine Importe aus Novadesk.
"""

from __future__ import annotations

import base64
import ctypes as C
import json
import os
import queue
import socket
import sys
import threading
import time
import traceback

TOKEN_VARIABLE = "NOVADESK_TEXT_SCHLUESSEL"
WATCH_VARIABLE = "NOVADESK_TEXT_WACHE"
MAIN_THREAD_VARIABLE = "NOVADESK_TEXT_HAUPTTHREAD"

# LibreOfficeKitEnums.h
FEATURE_DOCUMENT_PASSWORD = 1 << 0
CALLBACK_DOCUMENT_PASSWORD = 20
SETTEXTSELECTION_RESET = 2
EXT_TEXTINPUT, EXT_TEXTINPUT_END = 0, 2
# Ereignisse, die Novadesk braucht (die übrigen bleiben im Kern)
EVENTS = {
    0,   # INVALIDATE_TILES
    1,   # INVALIDATE_VISIBLE_CURSOR
    2,   # TEXT_SELECTION
    3,   # TEXT_SELECTION_START
    4,   # TEXT_SELECTION_END
    5,   # CURSOR_VISIBLE
    6,   # GRAPHIC_SELECTION
    7,   # HYPERLINK_CLICKED
    8,   # STATE_CHANGED
    12,  # SEARCH_NOT_FOUND
    13,  # DOCUMENT_SIZE_CHANGED
    16,  # UNO_COMMAND_RESULT
    18,  # MOUSE_POINTER
    22,  # ERROR
    23,  # CONTEXT_MENU
    15,  # SEARCH_RESULT_SELECTION
}
# Ereignisse der Notizenansicht: dieselben Nummern, um 1000 erhöht (Kacheln, Schreibmarke, Auswahl, Größe)
NOTES_BASE = 1000
NOTES_EVENTS = {0, 1, 2, 5, 13}

# Dateiformate zum Speichern: Endung → Format von LibreOfficeKit
FORMATS = {".docx": "docx", ".doc": "doc", ".odt": "odt", ".rtf": "rtf", ".txt": "txt", ".pdf": "pdf", ".html": "html",
           ".pptx": "pptx", ".ppt": "ppt", ".odp": "odp"}

# Dokumentarten: Novadesk-Name → (LOK_DOCTYPE, Fabrik für ein neues Dokument, Name in Meldungen)
KINDS = {
    "text": (0, "private:factory/swriter", "Textdokument"),
    "praesentation": (2, "private:factory/simpress", "Präsentation"),
}

P = C.c_void_p
CALLBACK = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_void_p)
POLL_CALLBACK = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int)
WAKE_CALLBACK = C.CFUNCTYPE(None, C.c_void_p)


def _fn(restype, *argtypes):
    return C.CFUNCTYPE(restype, *argtypes)


class KitClass(C.Structure):
    _fields_ = [
        ("nSize", C.c_size_t),
        ("destroy", _fn(None, P)),
        ("documentLoad", _fn(P, P, C.c_char_p)),
        ("getError", _fn(P, P)),
        ("documentLoadWithOptions", _fn(P, P, C.c_char_p, C.c_char_p)),
        ("freeError", _fn(None, P)),
        ("registerCallback", _fn(None, P, CALLBACK, P)),
        ("getFilterTypes", _fn(P, P)),
        ("setOptionalFeatures", _fn(None, P, C.c_ulonglong)),
        ("setDocumentPassword", _fn(None, P, C.c_char_p, C.c_char_p)),
        ("getVersionInfo", _fn(P, P)),
        ("runMacro", _fn(C.c_int, P, C.c_char_p)),
        ("signDocument", _fn(C.c_bool, P, C.c_char_p, P, C.c_int, P, C.c_int)),
        ("runLoop", _fn(None, P, POLL_CALLBACK, WAKE_CALLBACK, P)),
    ]


class Kit(C.Structure):
    _fields_ = [("pClass", C.POINTER(KitClass))]


_DOC_FUNCTIONS = (
    ("destroy", None, (P,)),
    ("saveAs", C.c_int, (P, C.c_char_p, C.c_char_p, C.c_char_p)),
    ("getDocumentType", C.c_int, (P,)),
    ("getParts", C.c_int, (P,)),
    ("getPartPageRectangles", P, (P,)),
    ("getPart", C.c_int, (P,)),
    ("setPart", None, (P, C.c_int)),
    ("getPartName", P, (P, C.c_int)),
    ("setPartMode", None, (P, C.c_int)),
    ("paintTile", None, (P, P, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int)),
    ("getTileMode", C.c_int, (P,)),
    ("getDocumentSize", None, (P, C.POINTER(C.c_long), C.POINTER(C.c_long))),
    ("initializeForRendering", None, (P, C.c_char_p)),
    ("registerCallback", None, (P, CALLBACK, P)),
    ("postKeyEvent", None, (P, C.c_int, C.c_int, C.c_int)),
    ("postMouseEvent", None, (P, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int)),
    ("postUnoCommand", None, (P, C.c_char_p, C.c_char_p, C.c_bool)),
    ("setTextSelection", None, (P, C.c_int, C.c_int, C.c_int)),
    ("getTextSelection", P, (P, C.c_char_p, C.POINTER(P))),
    ("paste", C.c_bool, (P, C.c_char_p, C.c_char_p, C.c_size_t)),
    ("setGraphicSelection", None, (P, C.c_int, C.c_int, C.c_int)),
    ("resetSelection", None, (P,)),
    ("getCommandValues", P, (P, C.c_char_p)),
    ("setClientZoom", None, (P, C.c_int, C.c_int, C.c_int, C.c_int)),
    ("setClientVisibleArea", None, (P, C.c_int, C.c_int, C.c_int, C.c_int)),
    ("createView", C.c_int, (P,)),
    ("destroyView", None, (P, C.c_int)),
    ("setView", None, (P, C.c_int)),
    ("getView", C.c_int, (P,)),
    ("getViewsCount", C.c_int, (P,)),
    ("renderFont", P, (P,)),  # unbenutzt (Platzhalter für die Reihenfolge)
    ("getPartHash", P, (P,)),
    # paintPartTile(Puffer, Teil, Modus, Breite px, Höhe px, x, y, Breite twips, Höhe twips)
    ("paintPartTile", None, (P, P, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int)),
    ("getViewIds", P, (P,)),
    ("setOutlineState", P, (P,)),
    ("paintWindow", P, (P,)),
    ("postWindow", P, (P,)),
    ("postWindowKeyEvent", P, (P,)),
    ("postWindowMouseEvent", P, (P,)),
    ("setViewLanguage", None, (P, C.c_int, C.c_char_p)),
    ("postWindowExtTextInputEvent", None, (P, C.c_uint, C.c_int, C.c_char_p)),
)


class DocClass(C.Structure):
    _fields_ = [("nSize", C.c_size_t)] + [(name, _fn(restype, *args)) for name, restype, args in _DOC_FUNCTIONS]


class Doc(C.Structure):
    _fields_ = [("pClass", C.POINTER(DocClass))]


class KernelError(Exception):
    def __init__(self, message, code="fehler"):
        Exception.__init__(self, message)
        self.code = code


def file_url(path):
    """Dateipfad → ``file:///…`` (auch unter Windows mit Laufwerksbuchstaben, Leerzeichen und Umlauten)."""
    from pathlib import Path
    from urllib.parse import quote

    absolute = Path(path).resolve()
    text = absolute.as_posix()
    if not text.startswith("/"):
        text = "/" + text
    return "file://" + quote(text, safe="/:")


def load_kit(program, profile):
    """LibreOfficeKit aus dem ``program``-Ordner laden und starten (blockiert, bis LibreOffice bereit ist)."""
    if os.name == "nt":
        ure = os.path.normpath(os.path.join(program, "..", "URE", "bin"))
        os.environ["PATH"] = program + os.pathsep + ure + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(program)
        except (OSError, AttributeError):
            pass
        names = ("sofficeapp.dll", "mergedlo.dll")
    else:
        os.environ.setdefault("SAL_USE_VCLPLUGIN", "svp")
        names = ("libsofficeapp.so", "libmergedlo.so")
    library = None
    errors = []
    for name in names:
        path = os.path.join(program, name)
        if not os.path.isfile(path):
            continue
        try:
            library = C.CDLL(path, winmode=0) if os.name == "nt" else C.CDLL(path, mode=C.RTLD_GLOBAL)
        except OSError as exc:
            errors.append(f"{name}: {exc}")
            continue
        try:
            library.libreofficekit_hook_2
        except AttributeError:
            errors.append(f"{name}: libreofficekit_hook_2 fehlt")
            library = None
            continue
        break
    if library is None:
        raise KernelError("LibreOfficeKit fehlt: " + ("; ".join(errors) or f"keine von {', '.join(names)} in {program}"), "kern")
    hook = library.libreofficekit_hook_2
    hook.restype = C.POINTER(Kit)
    hook.argtypes = [C.c_char_p, C.c_char_p]
    kit = hook(program.encode("utf-8"), file_url(profile).encode("utf-8"))
    if not kit:
        raise KernelError("LibreOfficeKit ließ sich nicht starten.", "kern")
    return library, kit


class Document:
    def __init__(self, ident, pointer, view):
        self.ident = ident
        self.pointer = pointer
        self.cls = pointer.contents.pClass.contents
        self.view = view
        self.callback = None
        self.notes_view = None  # zweite Ansicht im Notizen-Modus (Präsentationen: Notizen unter der Folie)
        self.notes_callback = None


class Kernel:
    def __init__(self, kit, send_event):
        self.kit = kit
        self.kc = kit.contents.pClass.contents
        self.docs = {}
        self.next_id = 1
        self.send_event = send_event
        self.password = None  # Kennwort für das Dokument, das gerade geladen wird
        self.password_asked = 0
        self.last_event = time.monotonic()
        self.kit_callback = CALLBACK(self._kit_event)
        self.kc.registerCallback(self.kit, self.kit_callback, None)
        self.kc.setOptionalFeatures(self.kit, FEATURE_DOCUMENT_PASSWORD)

    # Hilfen ------------------------------------------------------------------------------------------------
    def _string(self, pointer):
        if not pointer:
            return ""
        try:
            return C.string_at(pointer).decode("utf-8", "replace")
        finally:
            self.kc.freeError(pointer)

    def error_text(self):
        return self._string(self.kc.getError(self.kit))

    def _kit_event(self, kind, payload, _data):
        if kind == CALLBACK_DOCUMENT_PASSWORD:
            # Läuft im Thread von ``documentLoad``: Kennwort (einmal) übergeben, sonst Abbruch
            url = payload
            self.password_asked += 1
            password = self.password if self.password and self.password_asked == 1 else None
            self.kc.setDocumentPassword(self.kit, url, password.encode("utf-8") if password else None)

    def doc(self, args):
        doc = self.docs.get(int(args.get("doc", 0)))
        if doc is None:
            raise KernelError("Das Dokument ist nicht mehr geöffnet.", "dokument")
        view = doc.notes_view if args.get("notes") and doc.notes_view is not None else doc.view
        if doc.cls.getView(doc.pointer) != view:
            doc.cls.setView(doc.pointer, view)
        return doc

    def settle(self, quiet=0.06, limit=2.0):
        """Warten, bis LibreOffice die eingereihten Tasten und Klicks verarbeitet hat (keine Ereignisse mehr)."""
        end = time.monotonic() + limit
        time.sleep(0.02)
        while time.monotonic() < end and time.monotonic() - self.last_event < quiet:
            time.sleep(0.02)

    # Befehle -------------------------------------------------------------------------------------------------
    def cmd_open(self, args):
        path = args.get("path") or ""
        doctype, factory, label = KINDS.get(str(args.get("kind") or "text"), KINDS["text"])
        url = file_url(path) if path else factory
        options = "Language=" + str(args.get("language") or "de-DE")
        self.password = args.get("password") or None
        self.password_asked = 0
        try:
            pointer = self.kc.documentLoadWithOptions(self.kit, url.encode("utf-8"), options.encode("utf-8"))
        finally:
            asked, self.password_asked, self.password = self.password_asked, 0, None
        if not pointer:
            message = self.error_text()
            if asked:
                raise KernelError("Das Kennwort ist falsch." if args.get("password") else "Die Datei ist mit einem Kennwort geschützt.", "kennwort")
            raise KernelError("Die Datei ließ sich nicht öffnen." + (f" ({message[:200]})" if message else ""), "laden")
        pointer = C.cast(pointer, C.POINTER(Doc))
        cls = pointer.contents.pClass.contents
        if cls.getDocumentType(pointer) != doctype:
            cls.destroy(pointer)
            raise KernelError(f"Das ist keine {label}." if label != "Textdokument" else "Das ist kein Textdokument.", "art")
        ident = self.next_id
        self.next_id += 1
        doc = Document(ident, pointer, cls.getView(pointer))
        self.docs[ident] = doc

        def event(kind, payload, _data, ident=ident):
            self.last_event = time.monotonic()
            if kind in EVENTS:
                self.send_event(ident, kind, (payload or b"").decode("utf-8", "replace"))

        doc.callback = CALLBACK(event)
        cls.registerCallback(pointer, doc.callback, None)
        cls.initializeForRendering(pointer, json.dumps(args.get("render") or {}).encode("utf-8"))
        return {"doc": ident, "view": doc.view, **self._size(doc)}

    def cmd_close(self, args):
        doc = self.docs.pop(int(args.get("doc", 0)), None)
        if doc is not None:
            if doc.cls.getView(doc.pointer) != doc.view:
                doc.cls.setView(doc.pointer, doc.view)
            doc.cls.destroy(doc.pointer)
        return True

    def _size(self, doc):
        width, height = C.c_long(), C.c_long()
        doc.cls.getDocumentSize(doc.pointer, C.byref(width), C.byref(height))
        pages = []
        for part in self._string(doc.cls.getPartPageRectangles(doc.pointer)).split(";"):
            values = [int(v) for v in part.replace(" ", "").split(",") if v.strip("-").isdigit()]
            if len(values) == 4:
                pages.append(values)
        return {"width": width.value, "height": height.value, "pages": pages}

    def cmd_size(self, args):
        return self._size(self.doc(args))

    def cmd_parts(self, args):
        """Teile des Dokuments – bei Präsentationen die Folien: Anzahl, gezeigter Teil und die Namen."""
        doc = self.doc(args)
        count = doc.cls.getParts(doc.pointer)
        return {"count": count, "current": doc.cls.getPart(doc.pointer),
                "names": [self._string(doc.cls.getPartName(doc.pointer, index)) for index in range(count)]}

    def cmd_part(self, args):
        """Zu einem Teil wechseln (Folie zeigen und bearbeiten)."""
        doc = self.doc(args)
        doc.cls.setPart(doc.pointer, int(args["part"]))
        return {"current": doc.cls.getPart(doc.pointer), **self._size(doc)}

    def cmd_partmode(self, args):
        """Ansicht der Präsentation: 0 = Folie, 1 = Notizen (die Notizenseite der gezeigten Folie)."""
        doc = self.doc(args)
        doc.cls.setPartMode(doc.pointer, int(args.get("mode", 0)))
        return {"mode": int(args.get("mode", 0)), **self._size(doc)}

    def cmd_notes(self, args):
        """Zweite Ansicht im Notizen-Modus anlegen (einmal je Präsentation): Tasten und Klicks mit ``notes`` gehen
        dorthin, die Folie der Hauptansicht bleibt, wie sie ist. Antwort: Größe der Notizenseite."""
        doc = self.doc(args)
        if doc.notes_view is None:
            main = doc.cls.getView(doc.pointer)
            view = doc.cls.createView(doc.pointer)
            doc.cls.setView(doc.pointer, view)

            def event(kind, payload, _data, ident=doc.ident):
                # Die Notizenansicht meldet getrennt (1000 + Nummer), damit Schreibmarke und Auswahl der Folie
                # nicht durcheinandergeraten
                self.last_event = time.monotonic()
                if kind in NOTES_EVENTS:
                    self.send_event(ident, NOTES_BASE + kind, (payload or b"").decode("utf-8", "replace"))

            doc.notes_callback = CALLBACK(event)
            doc.cls.registerCallback(doc.pointer, doc.notes_callback, None)
            doc.cls.initializeForRendering(doc.pointer, b"{}")
            doc.cls.setPartMode(doc.pointer, 1)
            doc.notes_view = view
            doc.cls.setView(doc.pointer, main)
        doc.cls.setView(doc.pointer, doc.notes_view)
        doc.cls.setPart(doc.pointer, int(args.get("part", doc.cls.getPart(doc.pointer))))
        size = self._size(doc)
        doc.cls.setView(doc.pointer, doc.view)
        return size

    def cmd_thumb(self, args):
        """Bild eines Teils (Folie), ohne zu ihm zu wechseln – für die Folienleiste."""
        doc = self.doc(args)
        pw, ph = int(args["pw"]), int(args["ph"])
        if not (0 < pw <= 4096 and 0 < ph <= 4096):
            raise KernelError("Ungültige Kachelgröße.")
        buffer = (C.c_ubyte * (pw * ph * 4))()
        doc.cls.paintPartTile(doc.pointer, C.cast(buffer, P), int(args["part"]), int(args.get("mode", 0)), pw, ph,
                              int(args.get("x", 0)), int(args.get("y", 0)), int(args["w"]), int(args["h"]))
        return bytes(buffer)

    def cmd_tile(self, args):
        doc = self.doc(args)
        pw, ph = int(args["pw"]), int(args["ph"])
        if not (0 < pw <= 4096 and 0 < ph <= 4096):
            raise KernelError("Ungültige Kachelgröße.")
        buffer = (C.c_ubyte * (pw * ph * 4))()
        doc.cls.paintTile(doc.pointer, C.cast(buffer, P), pw, ph, int(args["x"]), int(args["y"]), int(args["w"]), int(args["h"]))
        return bytes(buffer)

    def cmd_key(self, args):
        doc = self.doc(args)
        char, code = int(args.get("char", 0)), int(args.get("code", 0))
        if args.get("type") is None:  # drücken und loslassen
            doc.cls.postKeyEvent(doc.pointer, 0, char, code)
            doc.cls.postKeyEvent(doc.pointer, 1, char, code)
        else:
            doc.cls.postKeyEvent(doc.pointer, int(args["type"]), char, code)
        return True

    def cmd_text(self, args):
        """Getippter Text (auch Umlaute, Emojis und Eingaben über die Eingabemethode)."""
        doc = self.doc(args)
        text = str(args.get("text") or "")
        if text:
            data = text.encode("utf-8")
            doc.cls.postWindowExtTextInputEvent(doc.pointer, 0, EXT_TEXTINPUT, data)
            doc.cls.postWindowExtTextInputEvent(doc.pointer, 0, EXT_TEXTINPUT_END, data)
        return True

    def cmd_mouse(self, args):
        doc = self.doc(args)
        doc.cls.postMouseEvent(doc.pointer, int(args["type"]), int(args["x"]), int(args["y"]), int(args.get("count", 1)),
                               int(args.get("buttons", 1)), int(args.get("mods", 0)))
        return True

    def cmd_uno(self, args):
        doc = self.doc(args)
        values = args.get("args")
        text = json.dumps(values) if isinstance(values, (dict, list)) else (values or None)
        doc.cls.postUnoCommand(doc.pointer, str(args["command"]).encode("utf-8"), text.encode("utf-8") if text else None,
                               bool(args.get("notify", False)))
        return True

    def cmd_select(self, args):
        doc = self.doc(args)
        doc.cls.setTextSelection(doc.pointer, int(args["type"]), int(args["x"]), int(args["y"]))
        return True

    def cmd_graphic(self, args):
        """Ausgewähltes Bild ziehen: Anfang (0) bzw. Ende (1) – verschieben oder an einem Anfasser die Größe ändern."""
        doc = self.doc(args)
        doc.cls.setGraphicSelection(doc.pointer, int(args["type"]), int(args["x"]), int(args["y"]))
        return True

    def cmd_reset(self, args):
        doc = self.doc(args)
        doc.cls.resetSelection(doc.pointer)
        return True

    def cmd_selection(self, args):
        """Ausgewählter Inhalt: {mime: Text} für die gewünschten Arten (zum Kopieren)."""
        doc = self.doc(args)
        self.settle()
        result = {}
        for mime in args.get("mimes") or ["text/plain;charset=utf-8"]:
            used = P()
            pointer = doc.cls.getTextSelection(doc.pointer, mime.encode("utf-8"), C.byref(used))
            used_text = self._string(used.value) if used.value else mime
            if pointer:
                try:
                    data = C.string_at(pointer)
                finally:
                    self.kc.freeError(pointer)
                if data:
                    result[used_text or mime] = base64.b64encode(data).decode("ascii")
        return result

    def cmd_paste(self, args):
        doc = self.doc(args)
        data = base64.b64decode(args.get("data") or "")
        return bool(doc.cls.paste(doc.pointer, str(args["mime"]).encode("utf-8"), data, len(data)))

    def cmd_values(self, args):
        doc = self.doc(args)
        text = self._string(doc.cls.getCommandValues(doc.pointer, str(args["command"]).encode("utf-8")))
        try:
            return json.loads(text) if text else None
        except ValueError:
            return text

    def cmd_visible(self, args):
        doc = self.doc(args)
        doc.cls.setClientVisibleArea(doc.pointer, int(args["x"]), int(args["y"]), int(args["w"]), int(args["h"]))
        return True

    def cmd_zoom(self, args):
        doc = self.doc(args)
        doc.cls.setClientZoom(doc.pointer, int(args["pw"]), int(args["ph"]), int(args["tw"]), int(args["th"]))
        return True

    def cmd_settle(self, args):
        self.doc(args)
        self.settle(limit=float(args.get("limit", 2.0)))
        return True

    def cmd_save(self, args):
        doc = self.doc(args)
        path = str(args["path"])
        extension = os.path.splitext(path)[1].lower()
        fmt = args.get("format") or FORMATS.get(extension)
        if not fmt:
            raise KernelError("Dieses Dateiformat kann Novadesk nicht speichern.", "format")
        self.settle()
        # Erst neben das Ziel, dann ersetzen: Bricht das Speichern ab, bleibt die bisherige Datei heil
        folder = os.path.dirname(os.path.abspath(path))
        temp = os.path.join(folder, f".~novadesk-{os.getpid()}-{int(time.time() * 1000)}{extension}")
        options = args.get("options") or None
        ok = doc.cls.saveAs(doc.pointer, file_url(temp).encode("utf-8"), fmt.encode("utf-8"), options.encode("utf-8") if options else None)
        if not ok or not os.path.isfile(temp):
            message = self.error_text()
            try:
                os.remove(temp)
            except OSError:
                pass
            raise KernelError("Das Dokument ließ sich nicht speichern." + (f" ({message[:200]})" if message else ""), "speichern")
        try:
            os.replace(temp, path)
        except OSError as exc:
            try:
                os.remove(temp)
            except OSError:
                pass
            raise KernelError(f"Die Datei ist gesperrt oder schreibgeschützt ({exc.strerror or exc}).", "gesperrt") from exc
        return True

    def cmd_export(self, args):
        """Kopie in einem anderen Format (PDF) – ohne die Datei des Dokuments zu ändern."""
        doc = self.doc(args)
        self.settle()
        path = str(args["path"])
        options = args.get("options") or None
        ok = doc.cls.saveAs(doc.pointer, file_url(path).encode("utf-8"), str(args.get("format") or "pdf").encode("utf-8"),
                            options.encode("utf-8") if options else None)
        if not ok:
            raise KernelError("Die PDF ließ sich nicht erstellen.", "export")
        return True

    def cmd_version(self, _args):
        return self._string(self.kc.getVersionInfo(self.kit))


def handle(kernel, request, send):
    """Einen Befehl ausführen und beantworten; ``False`` bei »quit«."""
    ident, command, args = request.get("id"), str(request.get("cmd") or ""), request.get("args") or {}
    if command == "quit":
        send({"id": ident, "ok": True, "result": True})
        return False
    handler = getattr(kernel, "cmd_" + command, None)
    try:
        if handler is None:
            raise KernelError(f"Unbekannter Befehl: {command}", "befehl")
        result = handler(args)
    except KernelError as exc:
        send({"id": ident, "ok": False, "error": str(exc), "code": exc.code})
        return True
    except Exception as exc:  # noqa: BLE001 - Fehler gehen an Novadesk, der Kern läuft weiter
        send({"id": ident, "ok": False, "error": f"{type(exc).__name__}: {exc}", "code": "intern", "trace": traceback.format_exc()[-2000:]})
        return True
    if isinstance(result, bytes):
        send({"id": ident, "ok": True, "bytes": len(result)}, result)
    else:
        send({"id": ident, "ok": True, "result": result})
    return True


# Befehle, die erst warten, bis LibreOffice eingereihte Tasten und Klicks verarbeitet hat (Kernel.settle)
SETTLING = {"settle", "save", "selection", "export"}


class Connection:
    """Verbindung zu Novadesk: Port-Datei schreiben, Schlüssel prüfen, Antworten über einen eigenen Thread senden."""

    def __init__(self, port_file, token):
        self.port_file, self.token = port_file, token
        self.socket = None
        self.reader = None
        self.outbox = queue.Queue()
        self.thread = None

    def open(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        temp = self.port_file + ".tmp"
        with open(temp, "w", encoding="ascii") as port:
            port.write(str(server.getsockname()[1]))
        os.replace(temp, self.port_file)
        server.settimeout(60)
        try:
            connection, _address = server.accept()
        finally:
            server.close()
        connection.settimeout(None)
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket, self.reader = connection, connection.makefile("rb")
        self.thread = threading.Thread(target=self._write, name="novadesk-text-writer", daemon=True)
        self.thread.start()
        hello = self.reader.readline()
        try:
            if json.loads(hello.decode("utf-8")).get("token") != self.token:
                raise ValueError
        except ValueError:
            connection.close()
            return False
        return True

    def _write(self):
        while True:
            item = self.outbox.get()
            if item is None:
                return
            try:
                self.socket.sendall(item)
            except OSError:
                return

    def send(self, message, data=b""):
        line = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.outbox.put(line + data if data else line)

    def send_event(self, doc, kind, payload):
        self.send({"event": kind, "doc": doc, "payload": payload})

    def requests(self):
        """Befehle, bis Novadesk die Verbindung schließt."""
        while True:
            line = self.reader.readline()
            if not line:
                return
            try:
                yield json.loads(line.decode("utf-8"))
            except ValueError:
                continue

    def close(self, kernel):
        if kernel is not None:
            for doc in list(kernel.docs.values()):
                try:
                    kernel.cmd_close({"doc": doc.ident})
                except Exception:  # noqa: BLE001
                    pass
        self.outbox.put(None)
        if self.thread is not None:
            self.thread.join(timeout=2)
        try:
            self.socket.close()
        except (OSError, AttributeError):
            pass


def serve(kernel_factory, port_file, token):
    """Befehle im eigenen Thread ausführen; LibreOffice läuft in seinem Hauptthread daneben (Linux)."""
    link = Connection(port_file, token)
    if not link.open():
        return
    kernel = kernel_factory(link.send_event)
    link.send({"ok": True})
    try:
        for request in link.requests():
            if not handle(kernel, request, link.send):
                break
    finally:
        link.close(kernel)


class MainThreadLoop:
    """Befehle im Hauptthread von LibreOffice ausführen (LibreOffice ohne eigenen Thread, »unipoll«, in ``runLoop``).

    Unter Windows nötig: Aus einem anderen Thread hängt dort das Laden einer Präsentation – Impress wartet auf den
    Hauptthread, der auf den Kern. Ein Lese-Thread nimmt die Befehle an; ``tick`` führt sie im Hauptthread aus, wenn
    LibreOffice ihn lässt (Windows: Nachricht an ein unsichtbares Fenster, Linux: Poll-Rückruf von ``runLoop``)."""

    def __init__(self, kernel_factory, port_file, token, notify=lambda: None, arm=lambda on: None):
        self.kernel_factory = kernel_factory
        self.link = Connection(port_file, token)
        self.requests = queue.Queue()
        self.notify = notify  # Hauptthread wecken (aus dem Lese-Thread)
        self.arm = arm  # Zeitgeber für das Warten in settled() an- bzw. abschalten
        self.kernel = None
        self.started = threading.Event()  # LibreOffice läuft (erster tick): erst dann die Port-Datei für Novadesk
        self.ready = False
        self.greeted = False
        self.busy = False
        self.pending = None
        self.settle = None

    def read(self):
        """Lese-Thread: Verbindung annehmen, dann jeden Befehl einreihen und den Hauptthread wecken."""
        self.started.wait()
        try:
            if self.link.open():
                self.ready = True
                self.notify()
                for request in self.link.requests():
                    self.requests.put(request)
                    self.notify()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        self.requests.put(None)
        self.ready = True
        self.notify()

    def finish(self):
        self.link.close(self.kernel)
        sys.stdout.flush()
        os._exit(0)

    def settled(self, request):
        """Warten, bis LibreOffice die eingereihten Tasten und Klicks verarbeitet hat (wie ``Kernel.settle``) – ohne den
        Hauptthread anzuhalten: Bis dahin läuft LibreOffice weiter, ``tick`` prüft beim nächsten Mal wieder."""
        now = time.monotonic()
        if self.settle is None:
            args = request.get("args") or {}
            limit = float(args.get("limit", 2.0)) if request.get("cmd") == "settle" else 2.0
            # Mindestens 0,1 s: LibreOffice arbeitet eingereihte Befehle erst ab, wenn der Kern ihm den Thread lässt
            self.settle = (now + 0.1, now + limit)
            self.arm(True)
            return False
        earliest, end = self.settle
        if now < end and (now < earliest or now - self.kernel.last_event < 0.06):
            return False
        self.arm(False)
        self.settle = None
        return True

    def tick(self):
        """Eingereihte Befehle ausführen (im Hauptthread). ``True``, wenn etwas geschah."""
        if self.busy:
            return False  # verschachtelt (LibreOffice arbeitet Nachrichten ab, während ein Befehl läuft)
        self.busy = True
        worked = False
        try:
            if self.kernel is None:
                self.kernel = self.kernel_factory(self.link.send_event)
                self.kernel.settle = lambda **_options: None  # geschieht vorher in settled()
                self.started.set()
                worked = True
            if not self.ready:
                return worked
            if not self.greeted:
                self.greeted = True
                self.link.send({"ok": True})
            while True:
                if self.pending is None:
                    try:
                        self.pending = self.requests.get_nowait()
                    except queue.Empty:
                        return worked
                request = self.pending
                if request is None:
                    self.finish()
                if request.get("cmd") in SETTLING and not self.settled(request):
                    return worked
                self.pending = None
                worked = True
                if not handle(self.kernel, request, self.link.send):
                    self.finish()
        finally:
            self.busy = False


def serve_main_thread(kit, kernel_factory, port_file, token):
    """``MainThreadLoop`` starten und LibreOffice im Hauptthread laufen lassen (kehrt nicht zurück: »quit« oder das Ende
    der Verbindung beenden den Prozess)."""
    keep = []
    if os.name == "nt":
        loop = _windows_loop(kernel_factory, port_file, token, keep)

        def poll(_data, _timeout):
            return 0  # Windows ruft ihn nicht auf (nur Linux/svp)
    else:
        # Linux (zum Testen dieses Wegs): runLoop ruft den Poll-Rückruf, der auf Befehle wartet
        loop = MainThreadLoop(kernel_factory, port_file, token)
        woken = threading.Event()
        loop.notify = woken.set

        def poll(_data, timeout):
            if not loop.busy:
                woken.wait(min(max(timeout, 0), 20000) / 1e6)
                woken.clear()
            return 1 if loop.tick() else 0

    threading.Thread(target=loop.read, name="novadesk-text-reader", daemon=True).start()
    callbacks = (POLL_CALLBACK(poll), WAKE_CALLBACK(lambda _data: None))
    keep.append(callbacks)
    # pData darf nicht leer sein: Sonst ruft LibreOffice den Poll-Rückruf gar nicht erst auf
    kit.contents.pClass.contents.runLoop(kit, callbacks[0], callbacks[1], C.c_void_p(1))


def _windows_loop(kernel_factory, port_file, token, keep):
    """Unsichtbares Fenster im Hauptthread: ``PostMessage`` aus dem Lese-Thread weckt ``tick``, ein Zeitgeber prüft
    das Warten in ``settled``. LibreOffice reicht die Nachrichten in seiner eigenen Schleife weiter."""
    from ctypes import wintypes

    user32 = C.WinDLL("user32", use_last_error=True)
    kernel32 = C.WinDLL("kernel32", use_last_error=True)
    LRESULT = C.c_ssize_t
    WNDPROC = C.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(C.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.RegisterClassW.argtypes = [C.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, C.c_int, C.c_int,
                                       C.c_int, C.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.SetTimer.argtypes = [wintypes.HWND, C.c_size_t, wintypes.UINT, C.c_void_p]
    user32.SetTimer.restype = C.c_size_t
    user32.KillTimer.argtypes = [wintypes.HWND, C.c_size_t]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    WM_APP, WM_TIMER, SETTLE_TIMER = 0x8000, 0x0113, 1
    window = {}

    def notify():
        user32.PostMessageW(window["hwnd"], WM_APP, 0, 0)

    def arm(on):
        if on:
            user32.SetTimer(window["hwnd"], SETTLE_TIMER, 20, None)
        else:
            user32.KillTimer(window["hwnd"], SETTLE_TIMER)

    loop = MainThreadLoop(kernel_factory, port_file, token, notify, arm)

    @WNDPROC
    def window_proc(hwnd, message, wparam, lparam):
        if message == WM_APP or (message == WM_TIMER and wparam == SETTLE_TIMER):
            try:
                loop.tick()
            except Exception:  # noqa: BLE001 - nie in LibreOffice hinein werfen
                traceback.print_exc()
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW(lpfnWndProc=window_proc, hInstance=instance, lpszClassName="NovadeskTextkern")
    keep.extend((window_proc, window_class))
    if not user32.RegisterClassW(C.byref(window_class)):
        raise OSError(C.get_last_error(), "RegisterClassW")
    hwnd = user32.CreateWindowExW(0, "NovadeskTextkern", "", 0, 0, 0, 0, 0, wintypes.HWND(-3), None,
                                  instance, None)  # HWND_MESSAGE: nur für Nachrichten
    if not hwnd:
        raise OSError(C.get_last_error(), "CreateWindowExW")
    window["hwnd"] = hwnd
    notify()  # der erste tick, sobald LibreOffice in seiner Schleife läuft
    return loop


def main(argv):
    program, profile, port_file = argv[1], argv[2], argv[3]
    token = os.environ.pop(TOKEN_VARIABLE, "")
    watch = os.environ.pop(WATCH_VARIABLE, "")
    if watch:
        # Build-Probe: hängt ein Befehl, schreibt Python alle paar Sekunden auf, wo der Kern gerade steht
        import faulthandler

        faulthandler.dump_traceback_later(float(watch), repeat=True, file=open("wache.log", "w", encoding="utf-8"))  # noqa: SIM115
    # Windows: im Hauptthread (siehe MainThreadLoop); unter Linux läuft dieser Weg nur zum Testen
    main_thread = os.name == "nt" or os.environ.pop(MAIN_THREAD_VARIABLE, "") == "1"
    if main_thread:
        os.environ["SAL_LOK_OPTIONS"] = "unipoll"
    try:
        _library, kit = load_kit(program, profile)
    except Exception as exc:  # noqa: BLE001 - Grund für Novadesk (Build-Probe, Protokoll)
        with open(port_file + ".fehler", "w", encoding="utf-8") as report:
            report.write(f"{exc}\n{traceback.format_exc()}")
        return 3
    try:
        if main_thread:
            serve_main_thread(kit, lambda send: Kernel(kit, send), port_file, token)
        else:
            serve(lambda send: Kernel(kit, send), port_file, token)
    except Exception:  # noqa: BLE001
        with open(port_file + ".fehler", "w", encoding="utf-8") as report:
            report.write(traceback.format_exc())
        return 4
    return 0


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    # LibreOffice nicht ordentlich herunterfahren (dauert und kann hängen): Dokumente sind geschlossen
    os._exit(code)
