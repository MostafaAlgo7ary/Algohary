"""تنظيف النص العربي والتحقق منه."""
import re

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def normalize(text):
    if not text:
        return ""
    text = _DIACRITICS.sub("", text)          # تشكيل وتطويل
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([،؛؟.!:])", r"\1", text)
    text = text.replace(",", "،").replace("?", "؟")
    return text.strip()


def _all_text(article):
    parts = [article.get("title", ""), article.get("description", ""),
             article.get("intro", ""), article.get("conclusion", "")]
    for s in article.get("sections", []):
        parts.append(s.get("heading", ""))
        parts.extend(s.get("paragraphs", []))
    return " ".join(parts)


def validate(article, allowed_latin, config):
    problems = []
    text = _all_text(article)
    if not article.get("title"):
        problems.append("العنوان فارغ")
    if not article.get("sections"):
        problems.append("لا توجد أقسام في المقال")
    bad = {w for w in _LATIN_WORD.findall(text) if w.lower() not in allowed_latin}
    if bad:
        problems.append("كلمات لاتينية غير مسموحة: " + ", ".join(sorted(bad)[:8]))
    letters = [c for c in text if c.isalpha()]
    if letters:
        ratio = len(_ARABIC.findall(text)) / len(letters)
        if ratio < 0.85:
            problems.append(f"نسبة العربية منخفضة ({ratio:.0%})")
    return problems


def source_overlap(body, source_text):
    """نسبة تتابعات الكلمات (3 كلمات) في المقال الموجودة في المصدر."""
    def grams(t):
        w = re.findall(r"[\u0600-\u06FF\w]+", t.lower())
        return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}
    b, s = grams(body), grams(source_text)
    return len(b & s) / len(b) if b else 0.0
