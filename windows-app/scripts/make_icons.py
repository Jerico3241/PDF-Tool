"""Erzeugt das App-Symbol von PDF Tool (Windows-Symbol, Favicons, Logo der Downloadseite).

Motiv (seit 4.0): ein Blatt mit Smiley und Textzeilen, darauf ein blau-violettes Abzeichen »PDF«.
Vorlage ist ``windows-app/assets/icon-source.png`` (512 × 512, »Pdf« von Magnific auf Flaticon, Stil
»lineal color«, Namensnennung nötig – siehe THIRD_PARTY_LICENSES.md). Jede Größe wird mit LANCZOS aus
der Vorlage verkleinert und leicht nachgeschärft, damit die Linien auch in Taskleiste und Explorer (16–24 px) erkennbar bleiben.

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


def _source() -> Image.Image:
    """Vorlage als quadratisches RGBA-Bild (transparent aufgefüllt, falls nicht quadratisch)."""
    image = Image.open(SOURCE).convert("RGBA")
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
    return square


def render(size: int) -> Image.Image:
    image = _source()
    if size == image.width:
        return image
    small = image.resize((size, size), Image.LANCZOS)
    if size <= 48:
        # Kleine Größen wirken nach dem Verkleinern weich – Farbe leicht nachschärfen, Transparenz unverändert
        alpha = small.getchannel("A")
        small = small.filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=1))
        small.putalpha(alpha)
    return small


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
