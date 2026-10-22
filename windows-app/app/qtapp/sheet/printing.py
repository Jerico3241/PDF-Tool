"""Tabellen drucken: der Rechenkern legt die Seiten als PDF an (Druckbereiche, Seitenumbrüche und Kopfzeilen wie in
der Datei), gedruckt wird dann mit demselben Druckdialog wie bei PDFs (``reader.printing``)."""

from __future__ import annotations


class _Now:
    """Wie ``reader.engine.Engine`` für den Druck – führt Aufträge sofort aus (der Druck läuft ohnehin im GUI-Thread)."""

    class _Task:
        def __init__(self, result) -> None:
            self.result = result

    def submit(self, func, *_args, **_kwargs):
        return self._Task(func())

    @staticmethod
    def wait(task, timeout: float = 0) -> object:  # noqa: ARG004 - gleiche Schnittstelle
        return task.result


class _Pages:
    """Die Seiten des PDFs so, wie ``print_document`` ein Dokument erwartet."""

    def __init__(self, app, session, name: str) -> None:
        self.app = app
        self.session = session
        self.name = name
        self.engine = _Now()
        document = session.document
        self.pageCount = document.page_count  # noqa: N815 - Name wie im Leser
        self.currentPage = 0  # noqa: N815
        self.pageSizes = [(document.geometry(index).width, document.geometry(index).height) for index in range(self.pageCount)]  # noqa: N815


def print_pdf(app, path: str, name: str) -> None:
    """Druckdialog für das PDF ``path`` (die Seiten einer Tabelle); ``name`` erscheint in der Druckerwarteschlange."""
    from ..reader.printing import print_document
    from ..reader.session import Session

    try:
        session = Session.open("tabelle-druck", path)
    except Exception:  # noqa: BLE001 - kaputte Datei: Meldung statt Absturz
        app.notify("reader", "error", "Die Seiten für den Druck konnten nicht angelegt werden.", title="Drucken nicht möglich")
        return
    try:
        if session.document.page_count == 0:
            app.notify("reader", "warning", "Die Tabelle ist leer – es gibt nichts zu drucken.", title="Nichts zu drucken")
            return
        app.set_status("Bereit")
        print_document(_Pages(app, session, name))
    finally:
        try:
            session.document.close()
        except Exception:  # noqa: BLE001
            pass
