"""كتابة المقال ثم مراجعته لغويًا بنموذج ثانٍ (Groq)."""
import json
import re

from groq import Groq

import config

_client = None


def _groq():
    global _client
    if _client is None:
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _chat(system, user, temperature):
    """يجرب النماذج بالترتيب حتى ينجح أحدها ويعيد JSON."""
    last = None
    for model in config.GROQ_MODELS:
        try:
            r = _groq().chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            text = r.choices[0].message.content or ""
            text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
            return json.loads(text)
        except Exception as e:
            last = e
            print(f"⚠️ النموذج {model} فشل: {str(e)[:120]}")
    raise RuntimeError(f"فشلت كل النماذج: {last}")


SCHEMA = """{
  "title": "عنوان جذاب بالفصحى لا يزيد عن 60 حرفًا ويحتوي الكلمة المفتاحية",
  "description": "وصف البحث (ميتا) لا يزيد عن 150 حرفًا",
  "keyphrase": "الكلمة المفتاحية الرئيسية (2-4 كلمات)",
  "image_alt": "وصف نصي للصورة",
  "intro": "فقرة افتتاحية 40-70 كلمة تحتوي الكلمة المفتاحية وتجيب عن: ماذا حدث؟",
  "sections": [
    {"heading": "عنوان فرعي (H2)", "paragraphs": ["فقرة", "فقرة"]}
  ],
  "conclusion": "خاتمة قصيرة 30-50 كلمة فيها خلاصة أو ما ينتظر القارئ",
  "extra_labels": ["تصنيف إضافي اختياري"]
}"""

WRITE_SYSTEM = """أنت محرر صحفي عربي محترف في «{blog}». تكتب بالعربية الفصحى المعاصرة السليمة فقط.
قواعد صارمة:
1) اكتب مقالًا أصليًا بالكامل من الحقائق الواردة، ولا تنقل جملًا من المصدر ولا تترجمها حرفيًا. أعد تنظيم المعلومات وأضف سياقًا مفيدًا وتحليلًا موجزًا للقارئ دون اختلاق وقائع.
2) لا تذكر أي رقم أو اسم أو اقتباس أو تاريخ غير موجود في المادة المعطاة. إن لم تتأكد من معلومة فاحذفها.
3) فصحى خالصة بلا أي كلمة عامية. التزم بالهمزات (أ، إ، ء) والتنوين وعلامات الترقيم العربية (، ؛ ؟).
4) اكتب أسماء اللاعبين والأندية والشركات والمدن بالعربية، ملتزمًا بالقاموس المرفق حيث وُجد. لا تستخدم حروفًا لاتينية إلا لاختصار شائع جدًا مثل VAR.
5) أسلوب صحفي مباشر: الأهم أولًا، فقرات قصيرة (2-4 جمل)، عناوين فرعية وصفية.
6) طول المقال بين 400 و 750 كلمة، وفيه 3 إلى 5 عناوين فرعية.
7) لا تضف عبارات مثل «بحسب المصدر» داخل النص؛ الموقع يضيف المصدر تلقائيًا.
أعد JSON فقط بهذا الشكل:
{schema}"""

PROOF_SYSTEM = """أنت مدقق لغوي عربي خبير بالنحو والإملاء والصرف. ستتلقى مقالًا بصيغة JSON.
مهمتك: تصحيح الإملاء (الهمزات، التاء المربوطة والمفتوحة، الألف المقصورة)، والنحو، وعلامات الترقيم، والتنوين، وتوحيد كتابة الأسماء، وحذف أي كلمة عامية أو حرف لاتيني غير ضروري، وتحسين الركاكة، دون تغيير المعنى أو الحقائق أو إضافة معلومات جديدة.
حافظ على نفس بنية JSON وأسماء الحقول تمامًا، والتزم بحدود الطول: العنوان ≤ {tmax} حرفًا والوصف ≤ {dmax} حرفًا.
أعد JSON المصحح فقط."""


def _glossary_text(glossary, text_hint):
    """يرسل فقط مصطلحات القاموس التي تظهر في المادة لتقليل الحجم."""
    hint = text_hint.lower()
    rows = [f"{en} = {ar}" for en, ar in glossary.items() if en.lower() in hint]
    return "\n".join(rows) if rows else "لا يوجد"


STYLE_NOTES = {
    "مختصر": "الأسلوب المطلوب: مقال مختصر (250-400 كلمة) وعنوانان فرعيان على الأكثر.",
    "تحليلي": "الأسلوب المطلوب: مقال تحليلي أعمق يشرح الخلفية والدلالات وما قد يترتب، دون اختلاق وقائع.",
    "عاجل": "الأسلوب المطلوب: خبر عاجل قصير ومباشر (200-300 كلمة) يبدأ بالأهم فورًا.",
}


def write_article(item, article_text, section, glossary, problems=None):
    material = f"العنوان الأصلي: {item['title']}\nملخص: {item.get('summary', '')}\nالمادة:\n{article_text}"
    system = WRITE_SYSTEM.format(blog=config.BLOG_NAME, schema=SCHEMA)
    user = (f"القسم: {section['label']} ({section['topic']})\n\n"
            f"القاموس الإلزامي للأسماء:\n{_glossary_text(glossary, material)}\n\n"
            f"{material}")
    if config.WRITING_STYLE in STYLE_NOTES:
        user += "\n\n" + STYLE_NOTES[config.WRITING_STYLE]
    if problems:
        user += "\n\nملاحظات من المحاولة السابقة يجب إصلاحها:\n- " + "\n- ".join(problems)
    return _chat(system, user, temperature=0.5)


def proofread(article):
    system = PROOF_SYSTEM.format(tmax=config.TITLE_MAX, dmax=config.DESCRIPTION_MAX)
    return _chat(system, json.dumps(article, ensure_ascii=False), temperature=0.1)
