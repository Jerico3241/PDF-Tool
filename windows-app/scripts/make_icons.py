"""Erzeugt das App-Symbol von PDF Tool (Windows-Symbol, Favicons, Logo der Downloadseite).

Motiv (seit 4.0): ein Blatt mit Smiley und Textzeilen, darauf ein blau-violettes Abzeichen »PDF«.
Vorlage ist ``windows-app/assets/icon-source.png`` (512 × 512, »Pdf« von Magnific auf Flaticon, Stil
»lineal color«, Namensnennung nötig – siehe THIRD_PARTY_LICENSES.md). Jede Größe wird mit LANCZOS aus
der Vorlage verkleinert. 16, 20 und 24 px (Taskleiste, Explorer, Titelleiste) sind dagegen pixelgenau gezeichnet: vereinfacht
(zwei Blätter, Textzeilen, Abzeichen mit »PDF« in Pixelschrift), weil das verkleinerte Motiv dort weich und »PDF« unlesbar wird.

Aufruf (aus dem Repository-Hauptordner):
    python windows-app/scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "windows-app" / "assets" / "icon-source.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
FAVICON_SIZES = (16, 32, 48)

BADGE = (90, 108, 217)  # Blau-Violett des Abzeichens
WORDMARK = (32, 32, 32)

# Kleine Größen, pixelgenau gezeichnet
INK = (16, 16, 24, 255)
FRONT = (246, 244, 255, 255)
BACK = (195, 195, 244, 255)
BADGE_FILL = (98, 110, 230, 255)
WHITE = (255, 255, 255, 255)

FONT3 = {  # 3 × 5
    "P": ["###", "#.#", "###", "#..", "#.."],
    "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "F": ["###", "#..", "##.", "#..", "#.."],
}
FONT4 = {  # 4 × 7
    "P": ["###.", "#..#", "#..#", "###.", "#...", "#...", "#..."],
    "D": ["###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."],
    "F": ["####", "#...", "#...", "###.", "#...", "#...", "#..."],
}

# je Größe: Rückblatt, Vorderblatt, Zeilen (y, x0, x1), Abzeichen, Schrift
LAYOUT = {
    16: dict(back=(1, 2, 11, 15), front=(4, 0, 14, 13), lines=[(3, 6, 12), (5, 6, 12)], badge=(0, 8, 12, 14), font=FONT3),
    20: dict(back=(1, 3, 14, 19), front=(5, 0, 18, 16), lines=[(4, 8, 16), (6, 8, 16), (8, 8, 13)], badge=(0, 10, 15, 18), font=FONT3),
    24: dict(back=(1, 3, 17, 23), front=(6, 0, 22, 20), lines=[(4, 9, 19), (7, 9, 19), (10, 9, 15)], badge=(0, 12, 18, 22), font=FONT4),
}


def _box(img: Image.Image, box, fill) -> None:
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    d.rectangle(box, fill=fill, outline=INK)
    # runde Ecken: Eckpixel weglassen, innen Kontur nachziehen
    for x, y, ix, iy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        img.putpixel((x, y), (0, 0, 0, 0))
        img.putpixel((x + ix, y + iy), INK)


def small(size: int) -> Image.Image:
    spec = LAYOUT[size]
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for key, fill in (("back", BACK), ("front", FRONT)):
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        _box(layer, spec[key], fill)
        out.alpha_composite(layer)
    d = ImageDraw.Draw(out)
    for y, x0, x1 in spec["lines"]:
        d.line((x0, y, x1, y), fill=INK)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _box(layer, spec["badge"], BADGE_FILL)
    out.alpha_composite(layer)
    font = spec["font"]
    w, h = len(font["P"][0]), len(font["P"])
    bx0, by0, bx1, by1 = spec["badge"]
    total = 3 * w + 2
    x = bx0 + (bx1 - bx0 + 1 - total) // 2
    y = by0 + (by1 - by0 + 1 - h) // 2
    for ch in "PDF":
        for r, row in enumerate(font[ch]):
            for c, v in enumerate(row):
                if v == "#":
                    out.putpixel((x + c, y + r), WHITE)
        x += w + 1
    return out


def _source() -> Image.Image:
    """Vorlage als quadratisches RGBA-Bild (transparent aufgefüllt, falls nicht quadratisch)."""
    image = Image.open(SOURCE).convert("RGBA")
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    return square


def render(size: int) -> Image.Image:
    if size in LAYOUT:
        return small(size)
    image = _source()
    if size == image.width:
        return image
    small_image = image.resize((size, size), Image.LANCZOS)
    if size <= 48:
        # Kleine Größen wirken nach dem Verkleinern weich – Farbe leicht nachschärfen, Transparenz unverändert
        alpha = small_image.getchannel("A")
        small_image = small_image.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=1))
        small_image.putalpha(alpha)
    return small_image


def write_ico(path: Path, sizes) -> None:
    images = [render(size) for size in sizes]
    largest = images[-1]
    largest.save(path, format="ICO", sizes=[(size, size) for size in sizes], append_images=images[:-1])
    # Pillow wählt für jede Größe das Bild passender Größe aus append_images
    check = Image.open(path)
    assert sorted(check.ico.sizes()) == sorted((size, size) for size in sizes), check.ico.sizes()


def write_logo(path: Path) -> None:
    """Symbol mit Schriftzug »PDF Tool« (Downloadseite)."""
    height = 96
    icon = render(96)
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    font = ImageFont.truetype(str(font_path), 50) if font_path.is_file() else ImageFont.load_default()
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.textbbox((0, 0), "PDF Tool", font=font)
    width = height + 14 + (box[2] - box[0]) + 8
    logo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    logo.alpha_composite(icon, (0, 0))
    draw = ImageDraw.Draw(logo)
    draw.text((height + 14 - box[0], (height - (box[3] - box[1])) // 2 - box[1]), "PDF", font=font, fill=BADGE + (255,))
    pdf_width = probe.textlength("PDF ", font=font)
    draw.text((height + 14 - box[0] + pdf_width, (height - (box[3] - box[1])) // 2 - box[1]), "Tool", font=font, fill=WORDMARK + (255,))
    logo.save(path, optimize=True)


def main() -> None:
    assets = ROOT / "windows-app" / "assets"
    public = ROOT / "public"
    write_ico(assets / "icon.ico", ICON_SIZES)
    write_ico(public / "favicon.ico", FAVICON_SIZES)
    render(32).save(public / "favicon.png", optimize=True)
    render(512).save(public / "app-icon.png", optimize=True)
    write_logo(public / "app-logo.png")
    print("Symbole geschrieben:", assets / "icon.ico", public)


if __name__ == "__main__":
    main()
