"""Draw the integration icon (own generic heat-pump drawing, not the Thermia logo).

    python scripts/make_icon.py

Writes brand/icon.png (256x256) and brand/icon@2x.png (512x512). Needs Pillow.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "thermia_cloud" / "brand"
S = 1024  # drawn large, then scaled down for smooth edges


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # background: rounded square, vertical teal gradient
    bg = Image.new("RGBA", (S, S))
    bd = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / S
        bd.line(
            [(0, y), (S, y)], fill=(int(18 + 20 * t), int(112 - 36 * t), int(150 - 40 * t), 255)
        )
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=210, fill=255)
    img.paste(bg, (0, 0), mask)

    # outdoor unit: white rounded body
    d.rounded_rectangle((170, 250, 700, 790), radius=70, fill=(245, 248, 250, 255))
    d.rounded_rectangle((200, 280, 670, 760), radius=50, outline=(190, 205, 214, 255), width=10)
    # fan: ring plus five blades
    cx, cy, r = 435, 520, 165
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(40, 90, 120, 255), width=14)
    for k in range(5):
        a = math.radians(72 * k - 90)
        pts = []
        for step in range(0, 61, 6):
            ang = a + math.radians(step * 0.9)
            rad = 28 + (r - 36) * math.sin(math.radians(step * 3))
            pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
        pts.append((cx, cy))
        d.polygon(pts, fill=(40, 90, 120, 255))
    d.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=(245, 248, 250, 255))

    # warm air: three rising waves on the right
    for i, y0 in enumerate((350, 520, 690)):
        pts = [
            (740 + t * 6, y0 + 28 * math.sin(math.radians(t * 12 + i * 60)) - t * 0.0)
            for t in range(0, 41)
        ]
        d.line(pts, fill=(255, 168, 60, 255), width=30, joint="curve")
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png")
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")


if __name__ == "__main__":
    main()
