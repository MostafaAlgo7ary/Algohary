"""توليد بطاقة صورة أصلية بهوية القسم (بدل نسخ صور المصادر)."""
import glob
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, features

import config

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:  # للاختبار المحلي فقط
    arabic_reshaper = None

W, H = 1200, 630
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    paths = FONT_CANDIDATES + glob.glob("/usr/share/fonts/**/*Arabic*Bold*.ttf", recursive=True)
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


HAS_RAQM = features.check("raqm")  # raqm يتولى الربط والاتجاه بنفسه


def _shape(text):
    if not HAS_RAQM and arabic_reshaper:
        return get_display(arabic_reshaper.reshape(text))
    return text


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(_shape(test), font=font) <= max_w:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_card(title, section):
    r, g, b = section["color"]
    img = Image.new("RGB", (W, H), (r, g, b))
    px = img.load()
    for y in range(H):  # تدرج لوني عمودي
        k = y / H
        for x in range(W):
            px[x, y] = (int(r * (1 - .45 * k)), int(g * (1 - .45 * k)), int(b * (1 - .45 * k)))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 24, W, H], fill=(227, 169, 43))  # شريط ذهبي

    chip_font, title_font, site_font = _font(40), _font(64), _font(34)
    chip = _shape(section["label"])
    cw = d.textlength(chip, font=chip_font)
    d.rounded_rectangle([W - 70 - cw - 40, 60, W - 70, 130], radius=35, fill=(255, 255, 255))
    d.text((W - 70 - 20, 95), chip, font=chip_font, fill=(r, g, b), anchor="rm")

    lines = _wrap(d, title, title_font, W - 160)[:4]
    y = 190
    for line in lines:
        d.text((W - 80, y), _shape(line), font=title_font, fill=(255, 255, 255), anchor="ra")
        y += 92
    d.text((W - 80, H - 70), _shape(config.BLOG_NAME), font=site_font, fill=(255, 255, 255), anchor="rm")

    os.makedirs(config.IMAGES_DIR, exist_ok=True)
    name = f"{datetime.utcnow():%Y%m%d-%H%M%S}-{section['key']}.jpg"
    path = os.path.join(config.IMAGES_DIR, name)
    img.save(path, "JPEG", quality=84, optimize=True)
    return path


def public_url(path):
    """رابط الصورة بعد رفعها على GitHub (المستودع يجب أن يكون عامًا)."""
    if not config.GITHUB_REPOSITORY:
        return ""
    name = os.path.basename(path)
    return (f"https://raw.githubusercontent.com/{config.GITHUB_REPOSITORY}/"
            f"{config.GITHUB_BRANCH}/{config.IMAGES_DIR}/{name}")
