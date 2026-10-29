"""Seiten einer PDF als Bilder speichern – für »Text als Bild« (seit 5.0 Beta 7).

Jede Seite ein Bild (»Name – Seite 01.png«) oder alle Seiten untereinander als ein langes Bild (»Name.png«, mit einem
schmalen grauen Abstand zwischen den Seiten wie in der Ansicht). Ein langes Bild bleibt unter ``MAX_LONG`` Pixeln Höhe
(Grenze von JPEG und vieler Bildprogramme) – bei sehr vielen Seiten wird es dafür kleiner gerechnet.
"""

from __future__ import annotations

from pathlib import Path

from .jobs import ConvertError, _save_image, unique_path, write_new

MAX_LONG = 60_000
MAX_PAGES = 500
GAP = 16  # Pixel zwischen den Seiten im langen Bild


def write(pdf: Path, folder: Path, stem: str, suffix: str, dpi: int, long: bool = False) -> list[Path]:
    import io

    from PIL import Image

    from tools.pdf_editor import render
    from tools.pdf_editor.document import EditorDocument

    target = "jpg" if suffix == "jpg" else "png"
    if not folder.is_dir():
        raise ConvertError("Der Zielordner existiert nicht.")
    document = EditorDocument.open(pdf)
    written: list[Path] = []
    try:
        count = document.page_count
        if count > MAX_PAGES:
            raise ConvertError(f"Höchstens {MAX_PAGES} Seiten als Bilder auf einmal.")
        sizes = [document.geometry(index) for index in range(count)]
        scale = dpi / 72
        if long:
            height = sum(geo.height * scale for geo in sizes) + GAP * (count - 1)
            if height > MAX_LONG:
                scale *= (MAX_LONG - GAP * (count - 1)) / (height - GAP * (count - 1))
            width = max(int(geo.width * scale) for geo in sizes)
            pages = [render.to_pil(render.render_page(document, index, max(8, int(geo.width * scale)))) for index, geo in enumerate(sizes)]
            total = sum(page.height for page in pages) + GAP * (count - 1)
            sheet = Image.new("RGB", (width, total), (232, 232, 232))
            top = 0
            for page in pages:
                sheet.paste(page, ((width - page.width) // 2, top))
                top += page.height + GAP
            buffer = io.BytesIO()
            _save_image(sheet, target, buffer, dpi=round(scale * 72))
            written.append(write_new(unique_path(folder, f"{stem}.{suffix}"), buffer.getvalue()))
            return written
        digits = max(2, len(str(count)))
        for index, geo in enumerate(sizes):
            image = render.to_pil(render.render_page(document, index, max(8, int(geo.width * scale))))
            buffer = io.BytesIO()
            _save_image(image, target, buffer, dpi=dpi)
            written.append(write_new(unique_path(folder, f"{stem} – Seite {index + 1:0{digits}d}.{suffix}"), buffer.getvalue()))
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    finally:
        document.close()
    return written
