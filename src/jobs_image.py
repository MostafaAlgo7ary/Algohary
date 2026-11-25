"""بطاقة صورة لمقالات الوظائف بهوية بصرية خاصة (أحمر طوبي + ذهبي + أيقونة حقيبة).
مستقلة عن images.py: لا تغيّر شيئًا في صور الأقسام الأخرى."""
import hashlib
import os
import re

from PIL import Image, ImageDraw, ImageFont

import config

W, H = 1200, 630
JOBS_COLOR = (150, 38, 44)       # أحمر طوبي داكن
JOBS_COLOR_DARK = (84, 18, 28)
GOLD = (245, 190, 70)
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
    """raqm يشكّل العربي ويرتّب الاتجاه بنفسه؛ وإلا نستعمل arabic_reshaper/bidi إن وُجدا."""
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
    words, lines, cur = text.split(), [], ""
    for w in words:
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


def _briefcase(d, cx, cy, s, color, fg):
    """حقيبة عمل مرسومة بالأشكال. s = العرض."""
    h = int(s * 0.7)
    x0, y0 = cx - s // 2, cy - h // 2 + int(s * 0.08)
    hw = int(s * 0.34)
    d.rounded_rectangle((cx - hw // 2, y0 - int(s * 0.17), cx + hw // 2, y0 + 10), radius=int(s * 0.05),
                        outline=color, width=int(s * 0.055))
    d.rounded_rectangle((x0, y0, x0 + s, y0 + h), radius=int(s * 0.1), fill=color)
    d.rectangle((x0, y0 + int(h * 0.48), x0 + s, y0 + int(h * 0.48) + max(3, int(s * 0.03))), fill=fg)
    d.rounded_rectangle((cx - int(s * 0.07), y0 + int(h * 0.40), cx + int(s * 0.07), y0 + int(h * 0.62)),
                        radius=int(s * 0.025), fill=GOLD)


MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def _pretty_date(s):
    m = re.match(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", s or "")
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1))} {MONTHS[int(m.group(2)) - 1]} {m.group(3)}"
    return re.sub(r"[/\-]", " ", s or "")


def make_card(title, deadline="", count=0, entity=""):
    """يرسم البطاقة ويحفظها في images/ ويعيد المسار."""
    title = re.sub(r"[:：]\s*التقديم.*$", "", title)          # الموعد يظهر في الشريط
    title = re.sub(r"[^\w\s]", " ", title)                  # خط Kufi يفتقد بعض علامات الترقيم
    title = re.sub(r"\s+", " ", title).strip()
    entity = re.sub(r"[^\w\s]", " ", entity).strip()
    img = Image.new("RGB", (W, H), JOBS_COLOR_DARK)
    px = img.load()
    for y in range(H):                       # تدرج قطري
        for x in range(0, W, 2):
            t = (x * 0.6 + y) / (W * 0.6 + H)
            c = tuple(int(JOBS_COLOR[i] * (1 - t) + JOBS_COLOR_DARK[i] * t) for i in range(3))
            px[x, y] = c
            if x + 1 < W:
                px[x + 1, y] = c
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for i in range(-H, W, 46):               # خطوط مائلة خفيفة
        od.line((i, H, i + H, 0), fill=(255, 255, 255, 10), width=2)
    od.ellipse((-140, -160, 330, 310), fill=(245, 190, 70, 38))
    od.ellipse((90, 150, 390, 450), fill=(255, 255, 255, 30), outline=GOLD + (255,), width=5)
    od.ellipse((W - 420, H - 330, W + 120, H + 200), fill=(255, 255, 255, 22))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    d = ImageDraw.Draw(img)

    # أيقونة الحقيبة على اليسار داخل دائرة
    _briefcase(d, 240, 300, 150, (255, 255, 255), JOBS_COLOR_DARK)

    right = W - 70
    # شارة القسم
    badge_f = _font("bold", 34)
    lab = config.__dict__.get("JOBS_LABEL", "وظائف")
    bw = int(_w(d, lab, badge_f)) + 60
    d.rounded_rectangle((right - bw, 60, right, 120), radius=30, fill=GOLD)
    _text(d, (right - bw // 2, 90), lab, badge_f, JOBS_COLOR_DARK, anchor="mm")
    if entity:
        _text(d, (right - bw - 24, 90), entity[:40], _font("reg", 28), (255, 235, 200), anchor="rm")

    # العنوان
    tf = _font("bold", 58)
    lines = _wrap(d, title, tf, 690, 3)
    y = 165
    for ln in lines:
        _text(d, (right, y), ln, tf, (255, 255, 255))
        y += 90
    # شرائط المعلومات
    chips = []
    if count:
        chips.append(f"{count} وظيفة")
    if deadline:
        chips.append("آخر موعد " + _pretty_date(deadline))
    cf = _font("bold", 30)
    x = right
    for c in chips:
        cw = int(_w(d, c, cf)) + 44
        d.rounded_rectangle((x - cw, 490, x, 545), radius=27, fill=(255, 255, 255, 235))
        _text(d, (x - cw // 2, 518), c, cf, JOBS_COLOR_DARK, anchor="mm")
        x -= cw + 16
    # التذييل
    d.rectangle((0, H - 14, W, H), fill=GOLD)
    _text(d, (90, H - 45), config.BLOG_NAME, _font("reg", 28), (255, 225, 190), anchor="lm")

    os.makedirs(config.IMAGES_DIR, exist_ok=True)
    name = "jobs-" + hashlib.sha1((title + deadline + str(count)).encode("utf-8")).hexdigest()[:10] + ".png"
    path = os.path.join(config.IMAGES_DIR, name)
    img.convert("RGB").save(path, optimize=True)
    return path


def public_url(path):
    """رابط الصورة بعد رفعها للمستودع (خطوة commit في الـ workflow). صور الأقسام الأخرى تستعمل نفس الأسلوب."""
    repo = config.GITHUB_REPOSITORY
    if not repo:
        return ""
    return f"https://raw.githubusercontent.com/{repo}/{config.GITHUB_BRANCH}/{path.replace(os.sep, '/')}"
