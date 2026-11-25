"""بطاقات صور الأقسام: لكل قسم هوية بصرية (لون + أيقونة + شارة) بنفس ألوان القالب.
الأقسام: تقنية، ألعاب، رياضة، سفر، فن، طعام، اقتصاد، وظائف.
الاستعمال: make_card("تقنية", "عنوان المقال", chips=["نص صغير"], entity="")"""
import hashlib
import os
import re

from PIL import Image, ImageDraw, ImageFont

import config

W, H = 1200, 630
GOLD = (245, 190, 70)
# label: (key, main color, dark color, accent, icon)
SECTIONS = {
    "تقنية": ("tech", (11, 79, 138), (6, 32, 66), (111, 177, 255), "chip"),
    "ألعاب": ("games", (109, 63, 208), (48, 22, 100), (183, 156, 255), "pad"),
    "رياضة": ("sport", (27, 138, 60), (10, 62, 28), (94, 209, 127), "ball"),
    "سفر": ("travel", (10, 143, 152), (4, 66, 82), (79, 214, 223), "plane"),
    "فن": ("art", (194, 37, 92), (92, 14, 52), (255, 127, 174), "palette"),
    "طعام": ("food", (217, 87, 15), (102, 36, 6), (255, 154, 92), "bowl"),
    "اقتصاد": ("econ", (148, 102, 0), (66, 44, 0), (240, 193, 75), "chart"),
    "وظائف": ("jobs", (150, 38, 44), (84, 18, 28), (245, 190, 70), "case"),
}
FONT_DIRS = ["/usr/share/fonts/truetype/noto", "/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/dejavu"]
FONT_NAMES = {
    "bold": ["NotoKufiArabic-Bold.ttf", "NotoSansArabic-Bold.ttf", "NotoNaskhArabic-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "reg": ["NotoKufiArabic-Regular.ttf", "NotoSansArabic-Regular.ttf", "NotoNaskhArabic-Regular.ttf", "DejaVuSans.ttf"],
}


def _font(kind, size):
    for d in FONT_DIRS:
        for n in FONT_NAMES[kind]:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _raqm():
    from PIL import features
    return features.check("raqm")


def _shape(text):
    if _raqm():
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def _w(draw, text, font):
    return draw.textlength(_shape(text), font=font, **({"direction": "rtl"} if _raqm() else {}))


def _text(draw, xy, text, font, fill, anchor="ra"):
    kw = {"direction": "rtl", "language": "ar"} if _raqm() else {}
    draw.text(xy, _shape(text), font=font, fill=fill, anchor=anchor, **kw)


def _wrap(draw, text, font, max_w, max_lines):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if _w(draw, t, font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("،:- ") + "…"
    return lines


# ---------- أيقونات مرسومة بالأشكال (cx, cy مركز، s حجم) ----------
def _icon(d, kind, cx, cy, s, dark, accent):
    F = (255, 255, 255)
    u = s / 100.0
    def R(x0, y0, x1, y1, r=0, **k):
        d.rounded_rectangle((cx + x0 * u, cy + y0 * u, cx + x1 * u, cy + y1 * u), radius=r * u, **k)
    def E(x0, y0, x1, y1, **k):
        d.ellipse((cx + x0 * u, cy + y0 * u, cx + x1 * u, cy + y1 * u), **k)
    def P(pts, **k):
        d.polygon([(cx + x * u, cy + y * u) for x, y in pts], **k)
    def L(x0, y0, x1, y1, w):
        d.line((cx + x0 * u, cy + y0 * u, cx + x1 * u, cy + y1 * u), fill=F, width=int(w * u))
    if kind == "case":
        R(-20, -62, 20, -38, 6, outline=F, width=int(6 * u))
        R(-70, -45, 70, 45, 10, fill=F)
        R(-70, -2, 70, 3, 0, fill=dark)
        R(-9, -12, 9, 14, 3, fill=accent)
    elif kind == "chip":
        for i in (-36, -12, 12, 36):
            R(i - 4, -66, i + 4, -46, 2, fill=F); R(i - 4, 46, i + 4, 66, 2, fill=F)
            R(-66, i - 4, -46, i + 4, 2, fill=F); R(46, i - 4, 66, i + 4, 2, fill=F)
        R(-50, -50, 50, 50, 10, fill=F)
        R(-24, -24, 24, 24, 5, fill=dark)
        R(-10, -10, 10, 10, 2, fill=accent)
    elif kind == "pad":
        R(-72, -34, 72, 46, 34, fill=F)
        E(-84, 6, -34, 56, fill=F); E(34, 6, 84, 56, fill=F)
        R(-48, -4, -20, 6, 2, fill=dark); R(-39, -13, -29, 15, 2, fill=dark)
        E(26, -10, 38, 2, fill=accent); E(44, 4, 56, 16, fill=dark)
    elif kind == "ball":
        E(-66, -66, 66, 66, fill=F)
        P([(0, -26), (25, -8), (15, 22), (-15, 22), (-25, -8)], fill=dark)
        for a, b in [((0, -26), (0, -64)), ((25, -8), (62, -20)), ((15, 22), (38, 54)),
                     ((-15, 22), (-38, 54)), ((-25, -8), (-62, -20))]:
            d.line((cx + a[0] * u, cy + a[1] * u, cx + b[0] * u, cy + b[1] * u), fill=dark, width=int(5 * u))
    elif kind == "plane":
        P([(0, -72), (11, -20), (70, 22), (70, 38), (11, 22), (8, 52), (28, 66), (28, 76),
           (0, 68), (-28, 76), (-28, 66), (-8, 52), (-11, 22), (-70, 38), (-70, 22), (-11, -20)], fill=F)
        E(-6, -50, 6, -30, fill=dark)
    elif kind == "palette":
        E(-70, -62, 70, 62, fill=F)
        E(14, 14, 52, 52, fill=dark)
        for (x, y, c) in [(-42, -8, accent), (-22, -38, (255, 205, 80)), (10, -44, (90, 190, 255)), (40, -18, (120, 220, 140))]:
            E(x - 11, y - 11, x + 11, y + 11, fill=c)
    elif kind == "bowl":
        d.pieslice((cx - 70 * u, cy - 62 * u, cx + 70 * u, cy + 78 * u), 0, 180, fill=F)
        R(-48, 40, 48, 52, 5, fill=F) if False else None
        R(-30, 62, 30, 72, 4, fill=F)
        for x in (-30, 0, 30):
            d.arc((cx + (x - 12) * u, cy - 64 * u, cx + (x + 12) * u, cy - 14 * u), 90, 270, fill=F, width=int(6 * u))
    elif kind == "chart":
        R(-68, 6, -40, 56, 4, fill=F); R(-18, -24, 10, 56, 4, fill=F); R(32, -58, 60, 56, 4, fill=F)
        R(-72, 62, 72, 70, 3, fill=accent)
        d.line((cx - 62 * u, cy - 30 * u, cx - 4 * u, cy - 54 * u, cx + 30 * u, cy - 74 * u), fill=accent, width=int(6 * u))


def _bg(key_main, key_dark, accent):
    img = Image.new("RGB", (W, H), key_dark)
    px = img.load()
    for y in range(H):
        for x in range(0, W, 2):
            t = (x * 0.6 + y) / (W * 0.6 + H)
            c = tuple(int(key_main[i] * (1 - t) + key_dark[i] * t) for i in range(3))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for i in range(-H, W, 46):
        od.line((i, H, i + H, 0), fill=(255, 255, 255, 10), width=2)
    od.ellipse((-140, -160, 330, 310), fill=accent + (38,))
    od.ellipse((90, 150, 390, 450), fill=(255, 255, 255, 30), outline=accent + (255,), width=5)
    od.ellipse((W - 420, H - 330, W + 120, H + 200), fill=(255, 255, 255, 22))
    return Image.alpha_composite(img.convert("RGBA"), ov)


def section_for(labels):
    """أول تصنيف معروف من قائمة تصنيفات المقال، أو None."""
    for l in labels or []:
        if l in SECTIONS:
            return l
    return None


def make_card(section, title, chips=(), entity="", out_dir=None):
    """يرسم بطاقة القسم ويحفظها ويعيد المسار. section = اسم التصنيف (مثل "تقنية")."""
    key, main, dark, accent, icon = SECTIONS[section]
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    entity = re.sub(r"[^\w\s]", " ", entity).strip()
    img = _bg(main, dark, accent)
    d = ImageDraw.Draw(img)
    _icon(d, icon, 240, 300, 150, dark, accent)
    right = W - 70
    badge_f = _font("bold", 34)
    bw = int(_w(d, section, badge_f)) + 60
    d.rounded_rectangle((right - bw, 60, right, 120), radius=30, fill=accent)
    _text(d, (right - bw // 2, 90), section, badge_f, dark, anchor="mm")
    if entity:
        _text(d, (right - bw - 24, 90), entity[:40], _font("reg", 28), (255, 240, 225), anchor="rm")
    tf = _font("bold", 58)
    y = 165
    for ln in _wrap(d, title, tf, 690, 3):
        _text(d, (right, y), ln, tf, (255, 255, 255))
        y += 90
    cf = _font("bold", 30)
    x = right
    for c in chips:
        cw = int(_w(d, c, cf)) + 44
        d.rounded_rectangle((x - cw, 490, x, 545), radius=27, fill=(255, 255, 255, 235))
        _text(d, (x - cw // 2, 518), c, cf, dark, anchor="mm")
        x -= cw + 16
    d.rectangle((0, H - 14, W, H), fill=accent)
    _text(d, (90, H - 45), config.BLOG_NAME, _font("reg", 28), (255, 235, 215), anchor="lm")
    out_dir = out_dir or config.IMAGES_DIR
    os.makedirs(out_dir, exist_ok=True)
    name = key + "-" + hashlib.sha1((section + title + "|".join(chips)).encode("utf-8")).hexdigest()[:10] + ".png"
    path = os.path.join(out_dir, name)
    img.convert("RGB").save(path, optimize=True)
    return path


def public_url(path):
    repo = config.GITHUB_REPOSITORY
    if not repo:
        return ""
    return f"https://raw.githubusercontent.com/{repo}/{config.GITHUB_BRANCH}/{path.replace(os.sep, '/')}"
