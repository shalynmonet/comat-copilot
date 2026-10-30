"""Generates the made-up part-tag photos used by the demo's low-confidence
and pick-and-issue scenarios -- every filename app/adapters/verify_tag.py
has a canned read for. These are simple, obviously-fake renderings of a
data plate -- never a real photo -- and the mock vision adapter keys off
filename, not pixel content, so their look only matters for a human
looking at the upload flow.

Run with:  python -m seed.tag_images
"""

from pathlib import Path

from PIL import Image, ImageDraw

from app.adapters.verify_tag import _MOCK_READS

ASSETS_DIR = Path(__file__).parent / "assets"


def _render_tag(lines: list[str]) -> Image.Image:
    width, height = 640, 400
    img = Image.new("RGB", (width, height), color=(235, 235, 225))
    draw = ImageDraw.Draw(img)

    draw.rectangle([10, 10, width - 10, height - 10], outline=(40, 40, 40), width=4)
    draw.rectangle([10, 10, width - 10, 70], fill=(40, 40, 40))
    draw.text((24, 28), "DATA PLATE -- MADE-UP DEMO IMAGE, NOT A REAL PART", fill=(255, 255, 255))

    y = 110
    for line in lines:
        draw.text((32, y), line, fill=(20, 20, 20))
        y += 36

    draw.text((24, height - 36), "COMAT Copilot demo asset -- synthetic, for the Stores verify flow only", fill=(90, 90, 90))
    return img


def main() -> None:
    ASSETS_DIR.mkdir(exist_ok=True)

    for filename, tag in _MOCK_READS.items():
        lines = [
            f"PART NUMBER:  {tag.part_number}",
            f"SERIAL:       {tag.serial}",
            f"CONDITION:    {(tag.condition or '').upper()}",
        ]
        img = _render_tag(lines)
        img.save(ASSETS_DIR / filename, quality=85)
        print(f"wrote {ASSETS_DIR / filename}")


if __name__ == "__main__":
    main()
