"""Build the deterministic LayerVault README hero from project artwork."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "docs" / "images"
BACKGROUND = IMAGE_DIR / "readme-hero-background.png"
LOGO = ROOT / "app" / "static" / "branding" / "layervault-logo.png"
OUTPUT = IMAGE_DIR / "layervault-readme-hero.png"


def font(name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def centered_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, face, fill) -> None:
    box = draw.textbbox((0, 0), text, font=face)
    draw.text((xy[0] - (box[2] - box[0]) / 2, xy[1]), text, font=face, fill=fill)


def main() -> None:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(BACKGROUND).convert("RGB")
    target_ratio = 3.0
    crop_height = round(source.width / target_ratio)
    top = max(0, round((source.height - crop_height) * 0.56))
    hero = source.crop((0, top, source.width, top + crop_height)).resize((1800, 600), Image.Resampling.LANCZOS)

    # Quiet the central artwork so the project identity stays crisp at thumbnail sizes.
    veil = Image.new("RGBA", hero.size, (255, 255, 255, 0))
    veil_draw = ImageDraw.Draw(veil)
    veil_draw.ellipse((405, -150, 1395, 760), fill=(248, 252, 255, 191))
    veil = veil.filter(ImageFilter.GaussianBlur(42))
    hero = Image.alpha_composite(hero.convert("RGBA"), veil)

    card = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    card_draw = ImageDraw.Draw(card)
    card_draw.rounded_rectangle((565, 54, 1235, 546), radius=54, fill=(247, 251, 255, 196), outline=(255, 255, 255, 238), width=3)
    card = card.filter(ImageFilter.GaussianBlur(0.25))
    hero = Image.alpha_composite(hero, card)

    mark = Image.open(LOGO).convert("RGBA")
    mark.thumbnail((205, 205), Image.Resampling.LANCZOS)
    shadow = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    shadow.alpha_composite(mark, ((hero.width - mark.width) // 2, 73))
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    tint = Image.new("RGBA", hero.size, (30, 73, 205, 0))
    tint.putalpha(shadow.getchannel("A").point(lambda alpha: round(alpha * 0.34)))
    hero = Image.alpha_composite(hero, tint)
    hero.alpha_composite(mark, ((hero.width - mark.width) // 2, 64))

    draw = ImageDraw.Draw(hero)
    centered_text(draw, (900, 278), "LayerVault", font("segoeuib.ttf", 69), (16, 31, 57, 255))
    centered_text(draw, (900, 365), "Your self-hosted 3D printing workspace", font("segoeui.ttf", 27), (78, 99, 132, 255))

    chips = ("MODELS", "MATERIALS", "PRINTERS", "PRINT HISTORY")
    chip_font = font("seguisb.ttf", 16)
    widths = [draw.textbbox((0, 0), item, font=chip_font)[2] + 36 for item in chips]
    gap = 11
    x = 900 - (sum(widths) + gap * (len(chips) - 1)) / 2
    for item, width in zip(chips, widths):
        draw.rounded_rectangle((x, 426, x + width, 470), radius=22, fill=(232, 241, 255, 220), outline=(255, 255, 255, 245), width=2)
        box = draw.textbbox((0, 0), item, font=chip_font)
        draw.text((x + (width - (box[2] - box[0])) / 2, 438), item, font=chip_font, fill=(57, 89, 160, 255))
        x += width + gap

    hero.convert("RGB").save(OUTPUT, optimize=True, quality=92)
    print(f"Created {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
