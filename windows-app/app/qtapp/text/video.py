"""Präsentation als Video (seit 5.0 Beta 6): die Bilder der Folien nacheinander in eine MP4-Datei.

Die Folien malt der Textkern (``thumb``) in der Größe des Videos; ``VideoWriter`` gibt sie mit Qt Multimedia
(FFmpeg) als Einzelbilder an einen ``QMediaRecorder``: jede Folie so lange, wie sie stehen soll, mit Überblenden
dazwischen, wenn die Folie einen Übergang hat. Videos und Töne auf den Folien kommen nicht mit ins Video (nur ihr
Bild auf der Folie). H.264 nimmt Windows selbst (Media Foundation); fehlt es, wird es MPEG-4 Part 2 – beides
spielt der Windows-Medienplayer ab.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QSize, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QPainter

FPS = 25
FADE_SECONDS = 0.6  # Überblenden zwischen zwei Folien


def _log():
    return logging.getLogger("pdftool.text")


@dataclass
class Slide:
    image: QImage
    seconds: float  # so lange steht die Folie (ohne den Übergang zu ihr)
    transition: str  # »keiner«, »schwarz« oder sonst ein Übergang (wird Überblenden)


def available() -> bool:
    """Qt Multimedia mit einem Videoformat zum Schreiben vorhanden?"""
    try:
        return _media_format() is not None
    except ImportError:
        return False


def _media_format():
    from PySide6.QtMultimedia import QMediaFormat

    media = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
    codecs = media.supportedVideoCodecs(QMediaFormat.ConversionMode.Encode)
    for codec in (QMediaFormat.VideoCodec.H264, QMediaFormat.VideoCodec.MPEG4):
        if codec in codecs:
            media.setVideoCodec(codec)
            return media
    return None


def frame_plan(slides: list[Slide], fps: int = FPS) -> list[tuple[int, int, float]]:
    """Alle Einzelbilder: (Folie, vorige Folie oder -1, Anteil der neuen Folie 0 … 1). »schwarz« blendet erst die
    vorige Folie aus (Anteil < 0: so viel Schwarz) und dann die neue ein."""
    plan: list[tuple[int, int, float]] = []
    fade = max(1, int(round(FADE_SECONDS * fps)))
    for index, slide in enumerate(slides):
        if index > 0 and slide.transition not in ("", "keiner"):
            if slide.transition == "schwarz":
                half = max(1, fade // 2)
                plan += [(index, index - 1, -(step + 1) / half) for step in range(half)]
                plan += [(index, -1, (step + 1) / half) for step in range(half)]
            else:
                plan += [(index, index - 1, (step + 1) / (fade + 1)) for step in range(fade)]
        plan += [(index, -1, 1.0)] * max(1, int(round(slide.seconds * fps)))
    return plan


def compose(slides: list[Slide], entry: tuple[int, int, float], size: QSize) -> QImage:
    index, previous, share = entry
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    target = image.rect()
    if share < 0:  # vorige Folie wird dunkel
        painter.drawImage(target, slides[previous].image)
        painter.fillRect(target, QColor(0, 0, 0, int(255 * min(1.0, -share))))
    else:
        if previous >= 0:
            painter.drawImage(target, slides[previous].image)
            painter.setOpacity(share)
        elif share < 1.0:  # aus Schwarz
            painter.setOpacity(share)
        painter.drawImage(target, slides[index].image)
    painter.end()
    return image


class VideoWriter(QObject):
    """Schreibt die Folien als MP4. ``progress`` (0 … 1), am Ende ``finished`` oder ``failed`` (Meldung)."""

    progress = Signal(float)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, path: str, slides: list[Slide], size: QSize, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtMultimedia import QMediaCaptureSession, QMediaRecorder, QVideoFrameInput

        self.path = str(Path(path).resolve())
        self.slides = slides
        self.size = size
        self.plan = frame_plan(slides)
        self.sent = 0
        self.cancelled = False
        self._done = False
        self._failed = False
        self._session = QMediaCaptureSession(self)
        self._input = QVideoFrameInput(self)
        self._session.setVideoFrameInput(self._input)
        self._recorder = QMediaRecorder(self)
        self._session.setRecorder(self._recorder)
        media = _media_format()
        if media is None:
            raise RuntimeError("Auf diesem PC fehlt ein Videoformat zum Speichern.")
        self._recorder.setMediaFormat(media)
        self._recorder.setVideoResolution(size)
        self._recorder.setVideoFrameRate(FPS)
        self._recorder.setEncodingMode(QMediaRecorder.EncodingMode.ConstantQualityEncoding)
        self._recorder.setQuality(QMediaRecorder.Quality.VeryHighQuality)
        self._recorder.setOutputLocation(QUrl.fromLocalFile(self.path))
        self._recorder.recorderStateChanged.connect(self._state)
        self._recorder.errorOccurred.connect(self._error)
        # Nimmt der Recorder gerade kein Bild an, bald noch einmal (das Signal »bereit« kommt nicht immer)
        self._pump = QTimer(self)
        self._pump.setInterval(15)
        self._pump.timeout.connect(self._send)
        self._input.readyToSendVideoFrame.connect(self._send)

    def start(self) -> None:
        self._recorder.record()
        self._pump.start()

    def cancel(self) -> None:
        self.cancelled = True
        self._pump.stop()
        self._recorder.stop()

    def _send(self) -> None:
        from PySide6.QtMultimedia import QVideoFrame

        if self._done or self.cancelled or self._failed:
            return
        step = 1_000_000 // FPS
        cache: dict = {}
        while self.sent < len(self.plan):
            entry = self.plan[self.sent]
            if entry not in cache:
                cache.clear()
                cache[entry] = compose(self.slides, entry, self.size)
            frame = QVideoFrame(cache[entry])
            frame.setStartTime(self.sent * step)
            frame.setEndTime((self.sent + 1) * step)
            if not self._input.sendVideoFrame(frame):
                return
            self.sent += 1
            if self.sent % FPS == 0:
                self.progress.emit(self.sent / len(self.plan))
                return  # der Oberfläche Zeit lassen
        self._done = True
        self._pump.stop()
        self._recorder.stop()

    def _state(self, state) -> None:
        from PySide6.QtMultimedia import QMediaRecorder

        if state != QMediaRecorder.RecorderState.StoppedState:
            return
        self._pump.stop()
        if self.cancelled or self._failed:
            try:
                Path(self.path).unlink()
            except OSError:
                pass
            if self.cancelled and not self._failed:
                self.failed.emit("")
        elif self._done:
            self.progress.emit(1.0)
            self.finished.emit(self.path)

    def _error(self, _error, text: str) -> None:
        _log().warning("Video: %s", text)
        if not self._failed and not self.cancelled:
            self._failed = True
            self._pump.stop()
            self.failed.emit(text or "Das Video ließ sich nicht schreiben.")
            self._recorder.stop()


# Vorschaubild für Videos und Töne auf der Folie -----------------------------------------------------------------
POSTER_WIDTH = 960


def poster(frame: QImage | None, width: int, height: int, audio: bool) -> QImage:
    """Bild, das auf der Folie für das Video bzw. den Ton steht (auch im Export): das erste Bild des Videos mit einer
    Abspieltaste darüber, sonst eine dunkle Fläche; ein Ton als Lautsprecher in einem Kreis."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QLinearGradient, QPainterPath, QPen

    if audio:
        width = height = 256
    elif width <= 0 or height <= 0:
        width, height = 16, 9
    scale = POSTER_WIDTH / max(width, height)
    size = QSize(max(16, int(width * scale)), max(16, int(height * scale)))
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    rect = QRectF(image.rect())
    side = min(rect.width(), rect.height())
    centre = rect.center()
    if audio:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0F6CBD"))
        painter.drawEllipse(rect.adjusted(4, 4, -4, -4))
        unit = side / 16
        speaker = QPainterPath()
        speaker.moveTo(centre + QPointF(-4.6 * unit, -1.6 * unit))
        speaker.lineTo(centre + QPointF(-2.4 * unit, -1.6 * unit))
        speaker.lineTo(centre + QPointF(0.6 * unit, -4.2 * unit))
        speaker.lineTo(centre + QPointF(0.6 * unit, 4.2 * unit))
        speaker.lineTo(centre + QPointF(-2.4 * unit, 1.6 * unit))
        speaker.lineTo(centre + QPointF(-4.6 * unit, 1.6 * unit))
        speaker.closeSubpath()
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(speaker)
        pen = QPen(QColor("#FFFFFF"), unit * 0.9)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius in (2.6, 4.6):
            box = QRectF(centre.x() + 0.6 * unit - radius * unit, centre.y() - radius * unit, 2 * radius * unit, 2 * radius * unit)
            painter.drawArc(box, -45 * 16, 90 * 16)
    else:
        if frame is not None and not frame.isNull():
            painter.drawImage(rect, frame)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0, QColor("#2B2B2B"))
            gradient.setColorAt(1, QColor("#111111"))
            painter.fillRect(rect, QBrush(gradient))
        radius = side * 0.11
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawEllipse(centre, radius, radius)
        triangle = QPainterPath()
        triangle.moveTo(centre + QPointF(-0.35 * radius, -0.5 * radius))
        triangle.lineTo(centre + QPointF(0.55 * radius, 0))
        triangle.lineTo(centre + QPointF(-0.35 * radius, 0.5 * radius))
        triangle.closeSubpath()
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawPath(triangle)
    painter.end()
    return image


class FrameGrabber(QObject):
    """Erstes Bild eines Videos (Qt Multimedia), für das Vorschaubild. ``done`` kommt immer – ohne Bild (leeres
    ``QImage``), wenn es nicht klappt oder zu lange dauert."""

    done = Signal(QImage)

    def __init__(self, path: str, parent: QObject | None = None, timeout_ms: int = 4000) -> None:
        super().__init__(parent)
        self._finished = False
        self._player = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._finish(QImage()))
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except ImportError:
            QTimer.singleShot(0, lambda: self._finish(QImage()))
            return
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._frame)
        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._player.errorOccurred.connect(lambda *_args: self._finish(QImage()))
        self._player.setSource(QUrl.fromLocalFile(path))
        self._timer.start(timeout_ms)
        self._player.play()

    def _frame(self, frame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._finish(image.copy())

    def _finish(self, image: QImage) -> None:
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        if self._player is not None:
            self._player.stop()
            self._player.setVideoSink(None)
        self.done.emit(image)
        self.deleteLater()
