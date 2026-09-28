"""Erzeugt das App-Symbol von PDF Tool (Windows-Symbol, Favicons, Logo der Downloadseite).

Motiv: ein Blatt mit Eselsohr und Textzeilen, unten rechts ein rotes Abzeichen mit
Schraubenschlüssel – »Werkzeuge für PDF-Dateien«. Eigene Grafik aus einfachen Formen,
keine fremden Logos. Jede Größe wird vierfach überabgetastet gezeichnet und
verkleinert; kleine Größen (16–24 px) erhalten eine vereinfachte Fassung mit
kräftigeren Linien, damit das Symbol in Taskleiste und Explorer lesbar bleibt.

Aufruf (aus dem Repository-Hauptordner):
    python windows-app/scripts/make_icons.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
FAVICON_SIZES = (16, 32, 48)
SUPERSAMPLE = 4

RED_LIGHT = (232, 72, 74)
RED_DARK = (181, 31, 31)
PAGE_TOP = (255, 255, 255)
PAGE_BOTTOM = (238, 241, 245)
PAGE_EDGE = (150, 160, 173)
FOLD = (214, 220, 228)
LINE_GRAY = (196, 203, 212)
WORDMARK = (32, 32, 32)


def _gradient(size: int, top: tuple, bottom: tuple, diagonal: bool = False) -> Image.Image:
    """Farbverlauf von oben (bzw. oben links) nach unten (bzw. unten rechts)."""
    ramp = Image.linear_gradient("L").resize((size, size))
    if diagonal:
        # Mittel aus senkrechtem und waagerechtem Verlauf: gleichmäßig von oben links nach unten rechts
        ramp = ImageChops.add(ramp, ramp.transpose(Image.Transpose.ROTATE_90).transpose(Image.Transpose.FLIP_LEFT_RIGHT), scale=2.0)
    return Image.composite(Image.new("RGB", (size, size), bottom), Image.new("RGB", (size, size), top), ramp)


def _circle(cx: float, cy: float, r: float, steps: int = 96) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(2 * math.pi * i / steps), cy + r * math.sin(2 * math.pi * i / steps)) for i in range(steps)]


def _wrench(mask: Image.Image, cx: float, cy: float, scale: float) -> None:
    """Schraubenschlüssel (weiß) in die Maske zeichnen: Kopf oben rechts, Griff nach unten links."""
    angle = math.radians(135)  # Achse Kopf → Griff zeigt nach unten links
    cos, sin = math.cos(angle), math.sin(angle)
    center_x = 24  # Mitte der Form auf der Achse

    def tf(points):
        return [(cx + ((x - center_x) * cos - y * sin) * scale, cy + ((x - center_x) * sin + y * cos) * scale) for x, y in points]

    draw = ImageDraw.Draw(mask)
    draw.polygon(tf(_circle(0, 0, 21)), fill=255)  # Kopf
    draw.polygon(tf([(0, -9), (62, -9), (62, 9), (0, 9)]), fill=255)  # Griff
    draw.polygon(tf(_circle(62, 0, 9)), fill=255)  # abgerundetes Griffende
    draw.polygon(tf([(-30, -8.5), (-5, -8.5), (-5, 8.5), (-30, 8.5)]), fill=0)  # Maulöffnung
    draw.polygon(tf(_circle(-5, 0, 8.5)), fill=0)


def render(size: int) -> Image.Image:
    small = size <= 24
    s = size * SUPERSAMPLE
    u = s / 256  # Zeichenraster: 256 Einheiten

    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    left, top, right, bottom = 44 * u, 14 * u, 204 * u, 242 * u
    if small:
        left, top, right, bottom = 30 * u, 8 * u, 214 * u, 248 * u
    ear = (54 if not small else 70) * u
    radius = (18 if not small else 22) * u

    # Blatt mit Eselsohr
    page = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(page)
    draw.rounded_rectangle((left, top, right, bottom), radius=radius, fill=255)
    draw.polygon([(right - ear, top - 1), (right + 1, top - 1), (right + 1, top + ear)], fill=0)
    if size >= 48:
        shadow = page.filter(ImageFilter.GaussianBlur(5 * u))
        shadow = ImageChops.offset(shadow, 0, int(4 * u)).point(lambda v: v * 0.22)
        image.paste(Image.new("RGBA", (s, s), (0, 0, 0, 255)), (0, 0), shadow)
    image.paste(_gradient(s, PAGE_TOP, PAGE_BOTTOM).convert("RGBA"), (0, 0), page)
    edge_width = max(SUPERSAMPLE, int((5 if not small else 12) * u))
    inner = page.filter(ImageFilter.MinFilter(edge_width * 2 + 1))
    edge = ImageChops.subtract(page, inner)
    image.paste(Image.new("RGBA", (s, s), PAGE_EDGE + (255,)), (0, 0), edge)
    # umgeschlagene Ecke
    fold = Image.new("L", (s, s), 0)
    ImageDraw.Draw(fold).polygon([(right - ear, top), (right - ear + radius * 0.2, top + ear - radius * 0.2), (right, top + ear)], fill=255)
    fold = ImageChops.lighter(fold, Image.new("L", (s, s), 0))
    image.paste(Image.new("RGBA", (s, s), FOLD + (255,)), (0, 0), fold)
    fold_edge = ImageChops.subtract(fold, fold.filter(ImageFilter.MinFilter(edge_width * 2 + 1)))
    image.paste(Image.new("RGBA", (s, s), PAGE_EDGE + (255,)), (0, 0), fold_edge)

    # Textzeilen (die erste in Rot)
    draw = ImageDraw.Draw(image)
    if small:
        rows = ((78, 118, RED_DARK, 26),)
        x0 = 66
    else:
        rows = ((70, 136, RED_DARK, 13), (98, 150, LINE_GRAY, 12), (126, 120, LINE_GRAY, 12))
        x0 = 72
    for y, x1, color, thickness in rows:
        draw.rounded_rectangle((x0 * u, y * u, x1 * u, (y + thickness) * u), radius=thickness * u / 2, fill=color)

    # Abzeichen mit Schraubenschlüssel
    bx, by, br = (178 * u, 184 * u, 64 * u) if not small else (170 * u, 170 * u, 82 * u)
    ring = (11 if not small else 16) * u
    halo = Image.new("L", (s, s), 0)
    ImageDraw.Draw(halo).ellipse((bx - br - ring, by - br - ring, bx + br + ring, by + br + ring), fill=255)
    image.paste(Image.new("RGBA", (s, s), (255, 255, 255, 255)), (0, 0), halo)
    badge = Image.new("L", (s, s), 0)
    ImageDraw.Draw(badge).ellipse((bx - br, by - br, bx + br, by + br), fill=255)
    image.paste(_gradient(s, RED_LIGHT, RED_DARK, diagonal=True).convert("RGBA"), (0, 0), badge)
    if size > 16:  # bei 16 px wäre der Schlüssel nur ein Fleck – dort bleibt das Abzeichen schlicht
        tool = Image.new("L", (s, s), 0)
        _wrench(tool, bx, by, (br / 64) * (1.0 if not small else 1.12))
        image.paste(Image.new("RGBA", (s, s), (255, 255, 255, 255)), (0, 0), ImageChops.multiply(tool, badge))

    return image.resize((size, size), Image.LANCZOS)


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
    draw.text((height + 14 - box[0], (height - (box[3] - box[1])) // 2 - box[1]), "PDF", font=font, fill=RED_DARK + (255,))
    pdf_width = probe.textlength("PDF ", font=font)
    draw.text((height + 14 - box[0] + pdf_width, (height - (box[3] - box[1])) // 2 - box[1]), "Tool", font=font, fill=WORDMARK + (255,))
    logo.save(path, optimize=True)


def _hex(color: tuple) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def write_svg(path: Path) -> None:
    """Dasselbe Motiv als SVG (Favicon), im selben 256er-Raster wie ``render``."""
    left, top, right, bottom, ear, radius = 44, 14, 204, 242, 54, 18
    inset = 2.5  # halbe Randbreite: der Rand liegt wie in der Rastergrafik innen
    l, t_, r, b = left + inset, top + inset, right - inset, bottom - inset
    page = (
        f"M{l + radius} {t_}H{r - ear + inset}L{r} {t_ + ear - inset}V{b - radius}"
        f"A{radius} {radius} 0 0 1 {r - radius} {b}H{l + radius}A{radius} {radius} 0 0 1 {l} {b - radius}"
        f"V{t_ + radius}A{radius} {radius} 0 0 1 {l + radius} {t_}Z"
    )
    fold = f"M{right - ear} {top}L{right - ear + radius * 0.2:.1f} {top + ear - radius * 0.2:.1f}L{right} {top + ear}Z"
    rows = ((70, 136, RED_DARK, 13), (98, 150, LINE_GRAY, 12), (126, 120, LINE_GRAY, 12))
    lines = "".join(
        f'<rect x="72" y="{y}" width="{x1 - 72}" height="{h}" rx="{h / 2}" fill="{_hex(color)}"/>' for y, x1, color, h in rows
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="page" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{_hex(PAGE_TOP)}"/><stop offset="1" stop-color="{_hex(PAGE_BOTTOM)}"/></linearGradient>
    <linearGradient id="badge" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{_hex(RED_LIGHT)}"/><stop offset="1" stop-color="{_hex(RED_DARK)}"/></linearGradient>
    <mask id="wrench" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
      <g transform="translate(178 184) rotate(135) translate(-24 0)">
        <circle r="21" fill="#FFF"/><rect x="0" y="-9" width="62" height="18" fill="#FFF"/><circle cx="62" r="9" fill="#FFF"/>
        <rect x="-30" y="-8.5" width="25" height="17" fill="#000"/><circle cx="-5" r="8.5" fill="#000"/>
      </g>
    </mask>
  </defs>
  <path d="{page}" fill="url(#page)" stroke="{_hex(PAGE_EDGE)}" stroke-width="5" stroke-linejoin="round"/>
  <path d="{fold}" fill="{_hex(FOLD)}" stroke="{_hex(PAGE_EDGE)}" stroke-width="5" stroke-linejoin="round"/>
  {lines}
  <circle cx="178" cy="184" r="75" fill="#FFF"/>
  <circle cx="178" cy="184" r="64" fill="url(#badge)"/>
  <rect width="256" height="256" fill="#FFF" mask="url(#wrench)"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    assets = ROOT / "windows-app" / "assets"
    public = ROOT / "public"
    write_ico(assets / "icon.ico", ICON_SIZES)
    write_ico(public / "favicon.ico", FAVICON_SIZES)
    render(32).save(public / "favicon.png", optimize=True)
    render(512).save(public / "app-icon.png", optimize=True)
    write_logo(public / "app-logo.png")
    write_svg(public / "favicon.svg")
    print("Symbole geschrieben:", assets / "icon.ico", public)


if __name__ == "__main__":
    main()
