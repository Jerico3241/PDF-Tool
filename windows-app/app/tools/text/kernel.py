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


def serve(kernel_factory, port_file, token):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    temp = port_file + ".tmp"
    with open(temp, "w", encoding="ascii") as handle:
        handle.write(str(server.getsockname()[1]))
    os.replace(temp, port_file)
    server.settimeout(60)
    try:
        connection, _address = server.accept()
    finally:
        server.close()
    connection.settimeout(None)
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    reader = connection.makefile("rb")
    outbox = queue.Queue()

    def writer():
        while True:
            item = outbox.get()
            if item is None:
                return
            try:
                connection.sendall(item)
            except OSError:
                return

    thread = threading.Thread(target=writer, name="novadesk-text-writer", daemon=True)
    thread.start()

    def send(message, data=b""):
        line = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        outbox.put(line + data if data else line)

    hello = reader.readline()
    try:
        if json.loads(hello.decode("utf-8")).get("token") != token:
            raise ValueError
    except ValueError:
        connection.close()
        return
    kernel = kernel_factory(lambda doc, kind, payload: send({"event": kind, "doc": doc, "payload": payload}))
    send({"ok": True})
    try:
        while True:
            line = reader.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            ident, command, args = request.get("id"), str(request.get("cmd") or ""), request.get("args") or {}
            if command == "quit":
                send({"id": ident, "ok": True, "result": True})
                break
            handler = getattr(kernel, "cmd_" + command, None)
            try:
                if handler is None:
                    raise KernelError(f"Unbekannter Befehl: {command}", "befehl")
                result = handler(args)
            except KernelError as exc:
                send({"id": ident, "ok": False, "error": str(exc), "code": exc.code})
                continue
            except Exception as exc:  # noqa: BLE001 - Fehler gehen an Novadesk, der Kern läuft weiter
                send({"id": ident, "ok": False, "error": f"{type(exc).__name__}: {exc}", "code": "intern", "trace": traceback.format_exc()[-2000:]})
                continue
            if isinstance(result, bytes):
                send({"id": ident, "ok": True, "bytes": len(result)}, result)
            else:
                send({"id": ident, "ok": True, "result": result})
    finally:
        for doc in list(kernel.docs.values()):
            try:
                kernel.cmd_close({"doc": doc.ident})
            except Exception:  # noqa: BLE001
                pass
        outbox.put(None)
        thread.join(timeout=2)
        try:
            connection.close()
        except OSError:
            pass


def main(argv):
    program, profile, port_file = argv[1], argv[2], argv[3]
    token = os.environ.pop(TOKEN_VARIABLE, "")
    try:
        _library, kit = load_kit(program, profile)
    except Exception as exc:  # noqa: BLE001 - Grund für Novadesk (Build-Probe, Protokoll)
        with open(port_file + ".fehler", "w", encoding="utf-8") as handle:
            handle.write(f"{exc}\n{traceback.format_exc()}")
        return 3
    try:
        serve(lambda send: Kernel(kit, send), port_file, token)
    except Exception:  # noqa: BLE001
        with open(port_file + ".fehler", "w", encoding="utf-8") as handle:
            handle.write(traceback.format_exc())
        return 4
    return 0


if __name__ == "__main__":
    code = main(sys.argv)
    sys.stdout.flush()
    # LibreOffice nicht ordentlich herunterfahren (dauert und kann hängen): Dokumente sind geschlossen
    os._exit(code)
