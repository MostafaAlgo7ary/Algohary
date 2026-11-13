"""تنظيف النص العربي والتحقق منه: الأسماء، الصياغات المترجمة حرفيًا، السيو، وعدد الكلمات."""
import math
import re

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670\u0640]")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def normalize(text):
    if not text:
        return ""
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([،؛؟.!:])", r"\1", text)
    text = text.replace(",", "،").replace("?", "؟")
    return text.strip()


# ======================================================================
# بنية المقال وعدّ الكلمات
# المقال = مقدمة + عنوان فرعي + فقرات قصيرة (بلا خاتمة ولا ذكر للمصدر)
# عدد كلمات المقال = المقدمة + العناوين الفرعية + كل الفقرات
# الكلمة = أي مقطع يفصله فراغ ويحوي حرفًا أو رقمًا (علامات الترقيم المنفصلة لا تُحسب)
# ======================================================================
def count_words(text):
    return sum(1 for t in (text or "").split() if re.search(r"\w", t))


def body_parts(article):
    parts = [article.get("intro", "")]
    for s in article.get("sections", []):
        parts.append(s.get("heading", ""))
        parts.extend(s.get("paragraphs", []))
    return parts


def article_words(article):
    return sum(count_words(p) for p in body_parts(article))


def word_report(article):
    """عدد كلمات كل جزء (يُرسل للنموذج ليعرف أين يحذف أو يضيف)."""
    lines = [f"المقدمة: {count_words(article.get('intro', ''))} كلمة"]
    for i, s in enumerate(article.get("sections", []), 1):
        lines.append(f"القسم {i} — العنوان الفرعي: {count_words(s.get('heading', ''))} كلمة")
        for j, p in enumerate(s.get("paragraphs", []), 1):
            lines.append(f"القسم {i} — الفقرة {j}: {count_words(p)} كلمة")
    return "\n".join(lines)


def _str(v):
    return v.strip() if isinstance(v, str) else ""


def coerce(article, subheadings=None):
    """يضمن أن حقول المقال بالأنواع المتوقعة، ويحصر العناوين الفرعية في العدد المطلوب
    بضم فقرات الزائد إلى آخر قسم."""
    a = dict(article) if isinstance(article, dict) else {}
    for k in ("title", "description", "keyphrase", "image_alt", "intro"):
        a[k] = _str(a.get(k))
    a.pop("conclusion", None)   # لا خاتمة في المقال
    kws = a.get("secondary_keywords")
    if isinstance(kws, str):
        kws = re.split(r"[,،;؛\n]", kws)
    a["secondary_keywords"] = [_str(k) for k in (kws or []) if _str(k)]
    secs = []
    for s in a.get("sections") or []:
        if not isinstance(s, dict):
            continue
        paras = s.get("paragraphs")
        if isinstance(paras, str):
            paras = [paras]
        secs.append({"heading": _str(s.get("heading")),
                     "paragraphs": [_str(p) for p in (paras or []) if _str(p)]})
    if subheadings and len(secs) > subheadings:
        for extra in secs[subheadings:]:
            secs[subheadings - 1]["paragraphs"].extend(extra["paragraphs"])
        secs = secs[:subheadings]
    a["sections"] = secs
    extra = a.get("extra_labels")
    a["extra_labels"] = [_str(x) for x in extra if _str(x)] if isinstance(extra, list) else []
    return a


# ======================================================================
# الأسماء: القاموس (لاتيني → عربي) وتوحيد الكتابة
# ======================================================================
_LB = r"(?<![A-Za-z0-9\u00C0-\u024F])"
_RB = r"(?![A-Za-z0-9\u00C0-\u024F])"


def _glossary_patterns(glossary):
    items = sorted(glossary.items(), key=lambda kv: -len(kv[0]))   # الأطول أولًا
    return [(re.compile(_LB + re.escape(en) + r"(?:['’]s)?" + _RB, re.I), ar) for en, ar in items]


def apply_glossary(text, glossary):
    """يستبدل أي اسم لاتيني موجود في القاموس بالعربية، ويوحّد صيغة (غ/ج) في الأسماء المعتمدة."""
    if not text:
        return text
    for rx, ar in _glossary_patterns(glossary):
        text = rx.sub(lambda m, ar=ar: ar, text)
    for ar in set(glossary.values()):
        if "غ" in ar:
            variant = ar.replace("غ", "ج")
            if len(variant) >= 4:
                text = text.replace(variant, ar)
    return text


_INNER_STOP = re.compile(r"(?<!\.)\.(?!\.)\s+(?=(\S+))")


def single_stop(text):
    """نقطة واحدة فقط في نهاية الفقرة: أي نقطة في وسطها تتحول إلى فاصلة (قبل «و/ثم») أو فاصلة منقوطة."""
    if not text:
        return text

    def rep(m):
        return "، " if re.match(r"(?:و|ثم)", m.group(1)) else "؛ "

    text = _INNER_STOP.sub(rep, text).strip()
    if text and text[-1] not in ".؟!?…":
        text += "."
    return text


def _no_stop(text):
    """العناوين: بلا نقطة في النهاية ولا في الوسط."""
    return single_stop(text).rstrip(".").strip() if text else text


TITLE_LIMIT = 70   # أقصى طول عنوان بعد الإصلاح الآلي


def repair_seo(a):
    """إصلاحات سيو آلية بلا نموذج: الكلمة المفتاحية في العنوان ووصف الصورة والعنوان الفرعي،
    وتنقية الكلمات الثانوية (لا تُنشر) بحيث تبقى الموجودة في النص فقط."""
    key = a.get("keyphrase", "")
    if key:
        if not _occ(key, a["title"]) and len(key) + 2 + len(a["title"]) <= TITLE_LIMIT:
            a["title"] = f"{key}: {a['title']}"
        if not _occ(key, a["image_alt"]):
            a["image_alt"] = a["title"] if _occ(key, a["title"]) else key
        heads = [s["heading"] for s in a["sections"]]
        if a["sections"] and not any(_occ(k, h) for h in heads for k in [key] + a["secondary_keywords"]):
            a["sections"][0]["heading"] = f"{key}: {a['sections'][0]['heading']}".strip(": ")
    body = " ".join(x for x in body_parts(a) if x)
    a["secondary_keywords"] = [k for k in a["secondary_keywords"] if _occ(k, body)]
    return a


def clean_article(article, glossary, subheadings=None):
    """تنظيف آلي لكل الحقول: القاموس + التطبيع + نقطة في نهاية الفقرة فقط، وضبط بنية المقال."""
    a = coerce(article, subheadings)

    def fix(t):
        return normalize(apply_glossary(t, glossary))

    for k in ("title", "description", "keyphrase", "image_alt", "intro"):
        a[k] = fix(a[k])
    a["title"] = _no_stop(a["title"])
    a["intro"] = single_stop(a["intro"])
    a["secondary_keywords"] = [fix(k) for k in a["secondary_keywords"]]
    for s in a["sections"]:
        s["heading"] = _no_stop(fix(s["heading"]))
        s["paragraphs"] = [single_stop(fix(p)) for p in s["paragraphs"]]
    return repair_seo(a)


# ======================================================================
# الصياغات المترجمة حرفيًا
# ======================================================================
_NB = r"(?<![\u0600-\u06FF])"   # بداية كلمة
_NE = r"(?![\u0600-\u06FF])"    # نهاية كلمة

CALQUES = [
    (re.compile(_NB + r"[وف]?(?:سي|ست|لي|لت)?[يت]?تمت?" + _NE + r"(?:\s+[\u0600-\u06FF]+)?"),
     "«تم/يتم + مصدر» ترجمة حرفية للمبني للمجهول؛ استخدم فعلًا مبنيًا للمجهول أو فاعلًا صريحًا "
     "(«أُطلقت اللعبة» لا «تم إطلاق اللعبة»)"),
    (re.compile(_NB + r"[وف]?(?:س)?(?:[يتنأ]قوم|قام(?:ت|وا)?|قمنا|قمت)" + _NE +
                r"(?:\s+\S+){0,3}?\s+ب(?!عد|ين|عض|سبب|دل|ناء)[\u0600-\u06FF]+"),
     "«قام/يقوم + بـ + مصدر» ترجمة حرفية؛ استخدم الفعل مباشرة («زار» لا «قام بزيارة»)"),
    (re.compile(_NB + r"كان(?:ت|وا)?\s+قادر(?:ا|ة|ين|ون)?\s+على" + _NE),
     "«كان قادرًا على» ترجمة لـ was able to؛ قل «استطاع»"),
    (re.compile(_NB + r"(?:[يت]?[أا]خذ|[أا]خذت|[أا]خذوا)\s+قرار"),
     "«أخذ قرارًا» ترجمة لـ took a decision؛ قل «اتخذ قرارًا»"),
    (re.compile(r"على\s+أساس\s+(?:يومي|أسبوعي|اسبوعي|شهري|سنوي)"),
     "«على أساس يومي» ترجمة حرفية؛ قل «يوميًا» و«أسبوعيًا» و«شهريًا»"),
    (re.compile(r"في\s+نهاية\s+اليوم"),
     "«في نهاية اليوم» ترجمة لـ at the end of the day؛ قل «في المحصلة»"),
    (re.compile(_NB + r"حقيقة\s+(?:أن|ان)" + _NE),
     "«حقيقة أن» ترجمة لـ the fact that؛ اختصر الجملة"),
]


def _fields(article):
    yield article.get("title", "")
    yield article.get("description", "")
    yield article.get("intro", "")
    for s in article.get("sections", []):
        yield s.get("heading", "")
        yield from s.get("paragraphs", [])


def find_calques(article):
    """[(النصيحة, [أمثلة من النص])] للصياغات المترجمة حرفيًا."""
    found = {}
    for piece in _fields(article):
        for rx, advice in CALQUES:
            for m in rx.finditer(piece):
                found.setdefault(advice, []).append(m.group(0).strip())
    return list(found.items())


# ======================================================================
# عدم ذكر المصدر
# ======================================================================
_ATTRIBUTION = re.compile(
    r"(?:نقلا|نقلًا)\s+عن|"
    r"(?:بحسب|حسب|وفقا\s+ل|وفقًا\s+ل|وفق|طبقا\s+ل|طبقًا\s+ل)\s*(?:ما\s+)?(?:نشر(?:ه|ت)?\s+)?"
    r"(?:موقع|صحيفة|جريدة|شبكة|قناة|وكالة|مجلة|تقرير|هيئة\s+الإذاعة)|"
    r"(?:ذكر|ذكرت|أفاد|أفادت|نشر|نشرت|كشف|كشفت|أوردت|أورد)\s+(?:موقع|صحيفة|جريدة|شبكة|قناة|وكالة|مجلة)|"
    r"(?:موقع|صحيفة|جريدة|شبكة|وكالة|مجلة)\s+[A-Za-z]")

_GENERIC_SOURCE_WORDS = {"business", "news", "sport", "sports", "evening", "times", "football",
                         "london", "man", "the", "planet", "lonely", "serious", "eats", "world"}


def source_mentions(article, source_name, glossary):
    """أمثلة لذكر اسم المصدر أو عبارات الإسناد الإعلامي في النص."""
    hits = []
    names = {source_name}
    first = re.split(r"[\s.]+", source_name.strip())[0] if source_name else ""
    if len(first) >= 3 and first.lower() not in _GENERIC_SOURCE_WORDS:
        names.add(first)
    for n in list(names):
        ar = apply_glossary(n, glossary)
        if ar != n:
            names.add(ar)
    for piece in (p for p in _fields(article) if p):
        for m in _ATTRIBUTION.finditer(piece):
            hits.append(m.group(0).strip())
        for n in names:
            if len(n) >= 3 and _occ(n, piece):
                hits.append(n)
    return hits[:4]


# ======================================================================
# السيو
# ======================================================================
def _loose(text):
    """صيغة مخففة للمطابقة: بلا تشكيل/ترقيم، وتوحيد الألف والياء والتاء المربوطة، وإسقاط «ال»."""
    t = _DIACRITICS.sub("", text or "")
    t = re.sub(r"[أإآٱ]", "ا", t).replace("ى", "ي").replace("ة", "ه")
    t = re.sub(r"[^\w\s]|_", " ", t)
    return " ".join(re.sub(r"^ال(?=\w{3})", "", w) for w in t.split())


def _occ(phrase, text):
    p = _loose(phrase)
    return _loose(text).count(p) if p else 0


def seo_problems(article):
    p = []
    key = article.get("keyphrase", "")
    if not key:
        return ["الكلمة المفتاحية (keyphrase) مفقودة"]
    n_words = article_words(article)
    klen = len(key.split())
    if klen < 2 or klen > 5:
        p.append("الكلمة المفتاحية يجب أن تكون من 2 إلى 4 كلمات")
    if not _occ(key, article.get("title", "")):
        p.append("الكلمة المفتاحية غير موجودة في العنوان (ضعها في بدايته)")
    if not _occ(key, article.get("intro", "")[:160]):
        p.append("الكلمة المفتاحية غير موجودة في أول 160 حرفًا من المقدمة")
    if not article.get("image_alt"):
        p.append("وصف الصورة (image_alt) مفقود")
    elif not _occ(key, article["image_alt"]):
        p.append("الكلمة المفتاحية غير موجودة في وصف الصورة")
    sec = article.get("secondary_keywords", [])
    heads = [s.get("heading", "") for s in article.get("sections", [])]
    if not any(_occ(k, h) for h in heads for k in [key] + sec):
        p.append("لا يوجد عنوان فرعي يحوي الكلمة المفتاحية أو إحدى الكلمات الثانوية")
    body = " ".join(x for x in body_parts(article) if x)
    occ = _occ(key, body)
    lo = 2 if n_words >= 250 else 1
    hi = max(4, int(n_words * 0.04 / max(klen, 1)) + 1)
    if occ < lo:
        p.append(f"الكلمة المفتاحية ظهرت {occ} مرة فقط في النص؛ كررها طبيعيًا {lo} مرات على الأقل")
    elif occ > hi:
        p.append(f"حشو للكلمة المفتاحية ({occ} مرة)؛ لا تتجاوز {hi} مرات")
    return p


# ======================================================================
# التحقق الشامل
# ======================================================================
def _all_text(article):
    parts = [article.get("title", ""), article.get("description", ""),
             article.get("image_alt", "")] + body_parts(article)
    return " ".join(parts)


def validate(article, allowed_latin, config, target=None, source_name=None, glossary=None):
    problems = []
    text = _all_text(article)
    if not article.get("title"):
        problems.append("العنوان فارغ")
    elif len(article["title"]) > config.TITLE_MAX + 10:
        problems.append(f"العنوان أطول من {config.TITLE_MAX} حرفًا")
    if not article.get("intro"):
        problems.append("المقدمة فارغة")
    sections = article.get("sections", [])
    k = getattr(config, "SUBHEADINGS", 1)
    if not sections:
        problems.append("لا توجد أقسام في المقال")
    elif len(sections) != k or any(not s.get("heading") or not s.get("paragraphs") for s in sections):
        problems.append(f"يجب أن يحتوي المقال على {k} عنوان فرعي فقط، وتحته فقرات قصيرة")
    bad = {w for w in _LATIN_WORD.findall(text) if w.lower() not in allowed_latin}
    if bad:
        problems.append("كلمات لاتينية غير مسموحة: " + ", ".join(sorted(bad)[:8]))
    letters = [c for c in text if c.isalpha()]
    if letters:
        ratio = len(_ARABIC.findall(text)) / len(letters)
        if ratio < 0.85:
            problems.append(f"نسبة العربية منخفضة ({ratio:.0%})")

    # فقرات قصيرة
    pmax = getattr(config, "PARAGRAPH_MAX_WORDS", 90)
    paras = [article.get("intro", "")] + [p for s in sections for p in s.get("paragraphs", [])]
    if any(count_words(p) > pmax for p in paras):
        problems.append(f"فقرات أطول من {pmax} كلمة؛ قسّمها إلى فقرات قصيرة")

    # الطول المطلوب = طول مقال المصدر
    if target:
        n = article_words(article)
        tol = max(getattr(config, "WORD_TOLERANCE", 0),
                  round(target * getattr(config, "WORD_TOLERANCE_PCT", 0) / 100))
        if abs(n - target) > tol:
            verb = "احذف" if n > target else "أضف"
            problems.append(f"عدد كلمات المقال {n} والمطلوب {target} بالضبط: {verb} {abs(n - target)} كلمة")

    # الترجمة الحرفية
    for advice, hits in find_calques(article):
        problems.append(f"صياغة مترجمة حرفيًا ({advice}): " + " | ".join(f"«{h}»" for h in hits[:3]))

    # لا ذكر للمصدر
    if source_name is not None:
        hits = source_mentions(article, source_name, glossary or {})
        if hits:
            problems.append("ممنوع ذكر المصدر أو الإسناد لمؤسسة إعلامية: " + " | ".join(f"«{h}»" for h in hits))

    problems += seo_problems(article)
    return problems


def source_overlap(body, source_text):
    """نسبة تتابعات (5 كلمات) في المقال الموجودة في المصدر."""
    def grams(t):
        w = re.findall(r"[\u0600-\u06FF\w]+", t.lower())
        return {tuple(w[i:i + 5]) for i in range(len(w) - 4)}
    b, s = grams(body), grams(source_text)
    return len(b & s) / len(b) if b else 0.0
