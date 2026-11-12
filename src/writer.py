"""كتابة المقال ثم مراجعته لغويًا بنماذج Groq مع تبديل تلقائي بين النماذج."""
import json
import re
import time

import groq
from groq import Groq

import config


class LLMUnavailable(RuntimeError):
    """كل النماذج فشلت لأسباب تقنية (حد استخدام/نموذج غير موجود/انقطاع).
    ليست خطأ في الخبر نفسه، لذلك لا يجوز وسم الخبر كـ«فاشل»."""


_client = None
_dead = set()        # نماذج غير موجودة/مُوقفة/ممنوعة: لا نعيد تجربتها في هذه التشغيلة
_cooldown = {}       # نموذج -> وقت (time.monotonic) يصلح بعده بعد 429
_no_json_mode = set()  # نماذج لا تدعم response_format
_discovered = None

_NON_CHAT = re.compile(r"whisper|orpheus|tts|guard|safeguard|embed|compound|moderation|distil", re.I)


def _groq():
    global _client
    if _client is None:
        # max_retries=0: لا نضيع الوقت في إعادة المحاولة على نفس النموذج، ننتقل للتالي فورًا
        _client = Groq(api_key=config.GROQ_API_KEY, max_retries=0, timeout=config.LLM_TIMEOUT)
    return _client


def _model_chain():
    """النماذج المعدّة أولًا ثم أي نماذج دردشة متاحة للحساب (إن فُعّل الاكتشاف)."""
    global _discovered
    if config.GROQ_AUTO_DISCOVER and _discovered is None:
        _discovered = []
        try:
            for m in _groq().models.list().data:
                mid = getattr(m, "id", "")
                if mid and getattr(m, "active", True) and not _NON_CHAT.search(mid):
                    _discovered.append(mid)
            print(f"ℹ️ نماذج Groq المتاحة: {', '.join(_discovered)}")
        except Exception as e:
            print(f"⚠️ تعذّر جلب قائمة النماذج: {str(e)[:100]}")
    chain = list(config.GROQ_MODELS)
    for mid in (_discovered or []):
        if mid not in chain:
            chain.append(mid)
    # لو الاكتشاف نجح، تجاهل النماذج المعدّة غير الموجودة أصلًا في حسابك
    if _discovered:
        chain = [m for m in chain if m in _discovered]
    return [m for m in chain if m not in _dead]


def _parse_wait(e):
    """يستخرج مدة الانتظار (ثوانٍ) من رأس retry-after أو نص الرسالة."""
    try:
        ra = e.response.headers.get("retry-after")
        if ra:
            return float(ra)
    except Exception:
        pass
    m = re.search(r"try again in\s*(?:(\d+)h)?\s*(?:(\d+)m(?!s))?\s*(?:([\d.]+)s)?", str(e))
    if m and any(m.groups()):
        h, mi, sec = (float(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + sec
    return 60.0


def _extract_json(text):
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b > a:
            return json.loads(text[a:b + 1])
        raise


def _call(model, system, user, temperature):
    kwargs = dict(model=model,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": user}],
                  temperature=temperature)
    if model not in _no_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        r = _groq().chat.completions.create(**kwargs)
    except groq.BadRequestError as e:
        body = getattr(e, "body", None)
        err = body.get("error", body) if isinstance(body, dict) else {}
        failed = err.get("failed_generation") if isinstance(err, dict) else None
        if failed:                       # النموذج كتب JSON لكنه فشل في تحققه: نحاول إنقاذه
            try:
                return _extract_json(failed)
            except Exception:
                pass
        if "response_format" in kwargs:  # ربما لا يدعم هذا النموذج وضع JSON: نعيد بدونه
            _no_json_mode.add(model)
            kwargs.pop("response_format")
            r = _groq().chat.completions.create(**kwargs)
        else:
            raise
    return _extract_json(r.choices[0].message.content)


def _handle_error(model, e):
    msg = str(e)[:140].replace("\n", " ")
    if isinstance(e, groq.RateLimitError):
        wait = _parse_wait(e)
        _cooldown[model] = time.monotonic() + wait
        print(f"⚠️ {model}: حد الاستخدام (429) — يتاح بعد ~{int(wait)} ث → ننتقل للنموذج التالي")
    elif isinstance(e, (groq.NotFoundError, groq.PermissionDeniedError)):
        _dead.add(model)
        print(f"⚠️ {model}: غير متاح لحسابك ({getattr(e, 'status_code', '')}) → يُستبعد: {msg}")
    elif isinstance(e, groq.AuthenticationError):
        raise LLMUnavailable("مفتاح GROQ_API_KEY غير صحيح أو منتهٍ") from e
    elif isinstance(e, groq.BadRequestError) and re.search(r"decommission|no longer supported|does not exist", msg, re.I):
        _dead.add(model)
        print(f"⚠️ {model}: مُوقف → يُستبعد: {msg}")
    else:
        print(f"⚠️ {model} فشل: {type(e).__name__}: {msg}")


def _chat(system, user, temperature):
    """يجرب النماذج بالترتيب؛ عند فشل أحدها ينتقل للتالي. عند امتلاء الحدود ينتظر قليلًا ثم يعيد."""
    last = None
    deadline = time.monotonic() + config.LLM_TOTAL_WAIT
    for _ in range(config.LLM_PASSES):
        chain = _model_chain()
        if not chain:
            break
        for model in chain:
            if _cooldown.get(model, 0) > time.monotonic():
                continue
            try:
                return _call(model, system, user, temperature)
            except LLMUnavailable:
                raise
            except Exception as e:
                last = e
                _handle_error(model, e)
        # لو كل النماذج الحية في فترة انتظار: ننتظر أقربها إن كان الانتظار معقولًا
        waits = [_cooldown[m] - time.monotonic() for m in _model_chain() if m in _cooldown]
        waits = [w for w in waits if w > 0]
        live = [m for m in _model_chain() if _cooldown.get(m, 0) <= time.monotonic()]
        if not live and waits:
            w = min(waits)
            if w > config.LLM_MAX_WAIT or time.monotonic() + w > deadline:
                break
            print(f"⏳ كل النماذج في حد الاستخدام، ننتظر {int(w) + 1} ث...")
            time.sleep(w + 1)
    raise LLMUnavailable(f"فشلت كل نماذج Groq: {str(last)[:150]}")


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
    """مراجعة لغوية. إن فشلت أو أعادت بنية ناقصة نُبقي المسودة الأصلية بدل إسقاط المقال."""
    system = PROOF_SYSTEM.format(tmax=config.TITLE_MAX, dmax=config.DESCRIPTION_MAX)
    try:
        fixed = _chat(system, json.dumps(article, ensure_ascii=False), temperature=0.1)
    except LLMUnavailable as e:
        print(f"   ⚠️ تعذّرت المراجعة اللغوية، نستخدم المسودة: {str(e)[:80]}")
        return article
    if (not isinstance(fixed, dict) or not fixed.get("sections")
            or not fixed.get("title") or not fixed.get("intro")):
        print("   ⚠️ المراجعة أعادت بنية ناقصة، نستخدم المسودة")
        return article
    return fixed
