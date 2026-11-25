"""بوابة الصلة: لا يُكتب ولا يُنشر خبر لا ينتمي لقسمه. تعمل على كل الأقسام، مرتين:
1) قبل الكتابة على (عنوان + ملخص + بداية نص الخبر)، 2) بعد الكتابة على المقال نفسه.
القاعدة: يجب وجود كلمة دالّة على القسم في العنوان، أو كلمتان في باقي النص. ووجود كلمة «غريبة» في العنوان
دون كلمة دالّة فيه يرفض الخبر. ثم فحص اختياري بالنموذج (سؤال نعم/لا) عند توفّر دالة ask."""
import re

# كلمات دالة على كل قسم (عربي + إنجليزي). أضف هنا ما تحتاجه.
POSITIVE = {
    "رياضة": "كرة قدم مباراة دوري هدف لاعب مدرب بطولة كأس نادي منتخب الأهلي الزمالك هداف تعادل فوز هزيمة حكم ملعب انتقال صفقة "
             "football soccer match league goal coach player cup premier transfer fifa uefa club striker champions "
             "midfielder manager derby fixture referee tennis basketball nba formula",
    "تقنية": "تقنية تكنولوجيا ذكاء اصطناعي هاتف تطبيق برمجيات شريحة آيفون أندرويد أبل جوجل مايكروسوفت إنفيديا روبوت حاسوب إنترنت "
             "سيبراني تحديث نظام معالج "
             "tech technology ai app iphone android chip software google apple microsoft nvidia openai robot cyber laptop gadget "
             "samsung tesla startup data cloud model processor gpu windows",
    "ألعاب": "لعبة ألعاب بلايستيشن إكس بوكس نينتندو ستيم جيمر توسعة "
             "game games gaming playstation xbox nintendo steam gta console dlc patch esports switch gamer studio "
             "zelda mario pokemon fortnite minecraft",
    "سفر": "سفر رحلة رحلات سياحة طيران فندق فنادق وجهة مطار سائح سياحي منتجع "
           "travel trip flight flights airline hotel hotels resort destination tourism airport cruise vacation itinerary "
           "tourist passport visa train landmark city island beach",
    "فن": "فن فنون فنان فنانة فنانين لوحة لوحات معرض متحف نحت تصميم عمارة سينما فيلم مسلسل مسرح مسرحية مهرجان موسيقى حفل ممثل "
          "تشكيلي ثقافة أغنية "
          "art artist artists painting museum gallery sculpture exhibition design architecture film photography illustration "
          "theatre theater festival music cinema drawing ceramic craft auction",
    "طعام": "طعام أكل وصفة وصفات مطبخ مطعم مطاعم طبخ شيف طبق حلوى خبز قهوة "
            "food recipe recipes restaurant restaurants cook cooking chef kitchen bake baking dinner meal dish wine coffee "
            "cuisine dessert breakfast lunch ingredients menu bar",
    "اقتصاد": "اقتصاد اقتصادي أسهم بورصة بنك بنوك تضخم فائدة أسعار دولار استثمار سوق أسواق شركة أرباح نمو ميزانية ناتج "
              "economy economic market markets stocks inflation bank rates fed earnings investors trade tariff gdp oil shares "
              "revenue business profit ceo company price prices fund bond currency",
}

# كلمات تدل على موضوع غريب عن الأقسام الفنية/الترفيهية (أخبار عامة): تُرفض إن كانت في العنوان بلا كلمة دالة فيه.
NEGATIVE = {
    "فن": "الأهلي الزمالك مباراة دوري كرة حريق حادث وفاة الصحة وزارة رئيس الوزراء الرئيس انتخابات مرور كوبري غلق عيادة أسعار الدواجن "
          "حكومة محافظ البرلمان نواب "
          "football match league fire accident election minister parliament nvidia stocks economy",
    "رياضة": "حريق حادث انتخابات وزارة الصحة أسعار الدواجن فنانة مسلسل "
             "election fire accident stocks recipe movie",
    "تقنية": "مباراة الأهلي حريق حادث انتخابات أسعار الدواجن مسلسل وصفة "
             "match fire accident election recipe",
    "ألعاب": "مباراة الأهلي حريق حادث انتخابات أسعار الدواجن "
             "election fire accident stocks",
    "سفر": "مباراة الأهلي انتخابات أسعار الدواجن مسلسل "
           "election stocks recipe match",
    "طعام": "مباراة الأهلي حريق حادث انتخابات مسلسل "
            "election match fire accident",
    "اقتصاد": "مباراة الأهلي حريق حادث مسلسل فنانة وصفة "
              "match recipe movie celebrity",
}

_AR = "\u0600-\u06FF"


def _rx(words):
    parts = []
    for w in dict.fromkeys(words.split()):
        w = re.escape(w)
        if re.match(r"[a-zA-Z]", w):
            parts.append(rf"(?<![A-Za-z]){w}(?:s|es)?(?![A-Za-z])")
        else:   # بادئات عربية شائعة (و ب ل ف ك ال) + لاحقة حرفين كحد أقصى
            parts.append(rf"(?<![{_AR}])(?:[وبفك]?(?:ال|لل|ل)?){w}[{_AR}]{{0,2}}(?![{_AR}])")
    return re.compile("|".join(parts), re.I)


_POS = {k: _rx(v) for k, v in POSITIVE.items()}
_NEG = {k: _rx(v) for k, v in NEGATIVE.items()}


def keyword_gate(label, title, rest=""):
    """(True, '') أو (False, سبب). label = اسم القسم."""
    pos, neg = _POS.get(label), _NEG.get(label)
    if pos is None:
        return True, ""
    title_hits = len(pos.findall(title or ""))
    rest_hits = len(pos.findall((rest or "")[:900]))
    if neg and neg.search(title or "") and title_hits == 0:
        return False, f"العنوان من موضوع آخر وليس من قسم «{label}»"
    if title_hits >= 1 or rest_hits >= 2:
        return True, ""
    return False, f"لا كلمات تدل على قسم «{label}» في العنوان أو بداية الخبر"


def article_text(article):
    """عنوان المقال وفقراته كنص واحد (لفحص ما بعد الكتابة). يتحمّل اختلاف مفاتيح البنية."""
    parts = [str(article.get("title", "")), str(article.get("description", ""))]
    for sec in article.get("sections", []) or []:
        parts.append(str(sec.get("heading", "")))
        parts.extend(str(p) for p in sec.get("paragraphs", []) or [])
    return " ".join(parts)


def post_write_gate(label, article):
    pos = _POS.get(label)
    if pos is None:
        return True, ""
    txt = article_text(article)
    title_hits = len(pos.findall(article.get("title", "")))
    hits = len(pos.findall(txt))
    if title_hits >= 1 or hits >= 4:
        return True, ""
    return False, f"المقال المكتوب لا يتصل بقسم «{label}»"


def llm_gate(label, topic, title, rest, ask):
    """فحص رخيص بالنموذج: هل الخبر من موضوع القسم؟ ask(prompt)->نص. عند أي عطل نعتمد قرار الكلمات (لا نرفض بسبب عطل)."""
    if ask is None:
        return True, ""
    prompt = (f"قسم المدونة: «{label}» (الموضوع: {topic}).\nعنوان الخبر: {title}\nبداية الخبر: {(rest or '')[:500]}\n"
              "هل هذا الخبر موضوعه الأساسي هو موضوع القسم؟ أجب بكلمة واحدة فقط: نعم أو لا.")
    try:
        ans = (ask(prompt) or "").strip()
    except Exception as e:
        print(f"   ℹ️ تعذّر فحص الصلة بالنموذج ({str(e)[:60]}): نكتفي بفحص الكلمات")
        return True, ""
    if ans.startswith("لا") or ans.lower().startswith("no"):
        return False, f"النموذج: الخبر ليس من موضوع قسم «{label}»"
    return True, ""
