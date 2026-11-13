"""كتابة المقال ثم مراجعته لغويًا بنماذج Groq مع تبديل تلقائي بين النماذج."""
import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import groq
from groq import Groq

import config
from src import arabic_check


class LLMUnavailable(RuntimeError):
    """كل النماذج فشلت لأسباب تقنية (حد استخدام/نموذج غير موجود/انقطاع).
    ليست خطأ في الخبر نفسه، لذلك لا يجوز وسم الخبر كـ«فاشل»."""


_client = None
_dead = set()        # نماذج غير موجودة/مُوقفة/ممنوعة: لا نعيد تجربتها في هذه التشغيلة
_cooldown = {}       # نموذج -> وقت (time.monotonic) يصلح بعده بعد 429
_no_json_mode = set()  # نماذج لا تدعم response_format
_no_extras = set()     # نماذج لا تدعم max_completion_tokens/reasoning_effort
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
    return [m for m in chain if m not in _dead and m not in config.GROQ_EXCLUDE]


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


def _call(model, system, user, temperature, max_tokens=None):
    kwargs = dict(model=model,
                  messages=[{"role": "system", "content": system},
                            {"role": "user", "content": user}],
                  temperature=temperature)
    if model not in _no_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if model not in _no_extras:
        if max_tokens:   # سقف للرد: يمنع استهلاك الحصة في التفكير الطويل ويقلل أخطاء 429
            kwargs["max_completion_tokens"] = int(max_tokens)
        if model.startswith("openai/gpt-oss"):
            kwargs["reasoning_effort"] = "low"   # تفكير أقصر = رد JSON غير فارغ وتوفير في الحصة
    try:
        try:
            r = _groq().chat.completions.create(**kwargs)
        except TypeError:   # نسخة SDK قديمة لا تعرف الوسيطات الإضافية
            _no_extras.add(model)
            kwargs.pop("max_completion_tokens", None)
            kwargs.pop("reasoning_effort", None)
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
        if re.search(r"reasoning_effort|max_completion_tokens", str(e)) and (
                "reasoning_effort" in kwargs or "max_completion_tokens" in kwargs):
            _no_extras.add(model)        # وسيطة إضافية غير مدعومة لهذا النموذج: نعيد بدونها
            kwargs.pop("max_completion_tokens", None)
            kwargs.pop("reasoning_effort", None)
            r = _groq().chat.completions.create(**kwargs)
        elif "response_format" in kwargs:  # ربما لا يدعم هذا النموذج وضع JSON: نعيد بدونه
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


def _valid(res):
    """رد صالح البنية فقط: وإلا يُعدّ فشلًا لهذا النموذج ولا يفوز بالسباق."""
    return (isinstance(res, dict) and bool(res.get("intro")) and
            isinstance(res.get("sections"), list) and bool(res["sections"]))


def _race(chain, system, user, temperature, max_tokens, check):
    """يجرّب النماذج بالترتيب بتغطية سريعة: الأول وحده، فإن فشل أو تأخر يبدأ التالي معه، وأول رد صالح يفوز.
    هكذا لا نحرق الحصة بإرسال الطلب لكل النماذج معًا."""
    def run(model):
        try:
            res = _call(model, system, user, temperature, max_tokens)
            if check and not check(res):
                raise ValueError("رد غير صالح البنية")
            return res
        except LLMUnavailable:
            raise
        except Exception as e:
            _handle_error(model, e)   # يسجّل حد الاستخدام/الاستبعاد حتى للنماذج المتأخرة
            raise

    ex = ThreadPoolExecutor(max_workers=len(chain))
    queue, pending, last, last_launch = list(chain), {}, None, 0.0
    try:
        while queue or pending:
            while queue and _cooldown.get(queue[0], 0) > time.monotonic():
                queue.pop(0)   # دخل فترة انتظار أثناء السباق
            if queue and (not pending or time.monotonic() - last_launch >= config.LLM_HEDGE_SECONDS):
                m = queue.pop(0)
                pending[ex.submit(run, m)] = m
                last_launch = time.monotonic()
            if not pending:
                break
            timeout = (max(0.1, config.LLM_HEDGE_SECONDS - (time.monotonic() - last_launch))
                       if queue else None)
            done, _ = wait(list(pending), timeout=timeout, return_when=FIRST_COMPLETED)
            for fut in done:
                m = pending.pop(fut)
                try:
                    res = fut.result()
                except LLMUnavailable:
                    raise
                except Exception as e:
                    last = e
                    continue
                if res is not None:
                    print(f"   🏁 رد صالح من: {m}")
                    return res, None
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return None, last


def _chat(system, user, temperature, max_tokens=None, check=_valid):
    """يجرّب النماذج المتاحة (بتغطية سريعة) ويأخذ أول رد صالح. عند امتلاء الحدود ينتظر قليلًا ثم يعيد."""
    last = None
    deadline = time.monotonic() + config.LLM_TOTAL_WAIT
    for _ in range(config.LLM_PASSES):
        chain = [m for m in _model_chain() if _cooldown.get(m, 0) <= time.monotonic()]
        if chain:
            res, err = _race(chain, system, user, temperature, max_tokens, check)
            if res is not None:
                return res
            last = err or last
        elif not _model_chain():
            break
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
  "title": "عنوان جذاب بالفصحى لا يزيد عن 60 حرفًا، يبدأ بالكلمة المفتاحية أو يحتويها",
  "description": "وصف البحث (ميتا) لا يزيد عن 150 حرفًا ويحتوي الكلمة المفتاحية",
  "keyphrase": "الكلمة المفتاحية الرئيسية: عبارة البحث التي يكتبها القارئ (2-4 كلمات عربية)",
  "secondary_keywords": ["3 إلى 5 كلمات أو عبارات مفتاحية ثانوية ذات صلة"],
  "image_alt": "وصف نصي للصورة يحتوي الكلمة المفتاحية",
  "intro": "فقرة افتتاحية قصيرة تبدأ بالكلمة المفتاحية في جملتها الأولى وتجيب عن: ماذا حدث؟",
  "sections": [
    {"heading": "العنوان الفرعي الوحيد (H2) يحتوي كلمة مفتاحية", "paragraphs": ["فقرة قصيرة", "فقرة قصيرة"]}
  ],
  "extra_labels": ["تصنيف إضافي اختياري"]
}"""

WRITE_SYSTEM = """أنت محرر صحفي عربي محترف في «{blog}» وخبير في تحسين محركات البحث (SEO). تكتب بالعربية الفصحى المعاصرة السليمة فقط.
قواعد صارمة:
1) اكتب مقالًا أصليًا بالكامل من الحقائق الواردة، ولا تنقل جملًا من المصدر ولا تترجمها حرفيًا. أعد تنظيم المعلومات بصياغة عربية طبيعية كأن كاتبًا عربيًا كتبها ابتداءً، وأضف سياقًا مفيدًا مما ورد في المادة دون اختلاق وقائع.
2) لا تذكر أي رقم أو اسم أو اقتباس أو تاريخ غير موجود في المادة المعطاة. إن لم تتأكد من معلومة فاحذفها.
3) فصحى خالصة بلا أي كلمة عامية. التزم بالهمزات (أ، إ، ء) والتنوين وعلامات الترقيم العربية (، ؛ ؟).
4) الأسماء: اكتب أسماء اللاعبين والمدربين والأندية والشركات والمنتجات والألعاب والمدن بالعربية، ملتزمًا بالقاموس المرفق حيث وُجد. الاسم الذي ليس في القاموس اكتبه بحروف عربية كما يُكتب في الإعلام العربي المعروف، ولا تترجم الأسماء ولا عناوين الألعاب والأفلام والمنتجات بمعناها (لا تحوّل The Last of Us إلى «آخرنا»)، ووحّد كتابة الاسم الواحد في المقال كله. لا تستخدم حروفًا لاتينية إلا لاختصار شائع جدًا مثل VAR.
5) تجنب الترجمة الحرفية: لا تنقل التعابير كلمة بكلمة؛ عبّر عن المعنى بتعبير عربي أصيل وبترتيب الجملة العربية. تجنب خاصة: «تم/يتم + مصدر» (قل «أُطلقت اللعبة» لا «تم إطلاق اللعبة»)، و«قام/يقوم + بـ + مصدر» (قل «زار» لا «قام بزيارة»)، و«كان قادرًا على» (قل «استطاع»)، و«أخذ قرارًا» (قل «اتخذ قرارًا»)، و«على أساس يومي» (قل «يوميًا»)، و«في نهاية اليوم»، و«حقيقة أن».
6) لا تذكر المصدر إطلاقًا: لا اسم موقع أو صحيفة أو شبكة أو وكالة، ولا «بحسب/نقلًا عن/ذكرت/أفاد» منسوبة إلى جهة إعلامية. اكتب الحقائق مباشرة. (نسبة تصريح إلى صاحبه، كمدرب أو مسؤول، مسموحة.)
7) سيو: الكلمة المفتاحية (keyphrase) هي عبارة البحث التي يكتبها القارئ في غوغل عن هذا الخبر (الكيان الرئيسي + الحدث، من 2 إلى 4 كلمات عربية). ضعها في: بداية العنوان، وأول جملة من المقدمة، والعنوان الفرعي، ووصف الصورة، وكررها طبيعيًا في الفقرات دون حشو (كثافة نحو 1%). اختر 3 إلى 5 كلمات مفتاحية ثانوية ذات صلة ووزّعها في النص. العنوان جذاب وصادق بلا مبالغة وفي حدود 60 حرفًا. الوصف في حدود 150 حرفًا ويحوي الكلمة المفتاحية.
8) البنية: مقدمة قصيرة، ثم عنوان فرعي واحد وصفي فقط، ثم فقرات قصيرة (2-3 جمل). لا خاتمة ولا عنوان «الخلاصة» ولا أي عناوين أخرى.
9) الطول: عدد كلمات المقال (المقدمة + العنوان الفرعي + كل الفقرات) يجب أن يساوي العدد المطلوب في رسالة المستخدم بالضبط، لا أكثر ولا أقل؛ التزم بميزانية الكلمات. لا تُطل بحشو أو تكرار ولا تختصر بحذف حقائق مهمة.
أعد JSON فقط بهذا الشكل:
{schema}"""

PROOF_SYSTEM = """أنت مدقق لغوي عربي خبير بالنحو والإملاء والصرف والأسلوب الصحفي. ستتلقى مقالًا بصيغة JSON.
مهمتك: تصحيح الإملاء (الهمزات، التاء المربوطة والمفتوحة، الألف المقصورة)، والنحو، وعلامات الترقيم، والتنوين، وتوحيد كتابة الأسماء (التزم بالقاموس المرفق)، وتحويل أي اسم بحروف لاتينية إلى العربية، وحذف أي كلمة عامية أو حرف لاتيني غير ضروري، وإزالة الصياغات المترجمة حرفيًا من الإنجليزية (مثل «تم/يتم + مصدر» و«قام بـ + مصدر» وترتيب الجملة الإنجليزي والتعابير المنقولة كلمة بكلمة) واستبدالها بصياغة عربية أصيلة بالمعنى نفسه، وحذف أي ذكر لمصدر الخبر أو إسناد لمؤسسة إعلامية، وتحسين الركاكة، دون تغيير المعنى أو الحقائق أو إضافة معلومات جديدة.
حافظ قدر الإمكان على عدد الكلمات الحالي (استبدل ولا تحذف ولا تضف جملًا)، ولا تغيّر الكلمة المفتاحية ولا الكلمات الثانوية ولا مواضعها في العنوان والمقدمة والعنوان الفرعي.
حافظ على نفس بنية JSON وأسماء الحقول تمامًا (بلا خاتمة)، والتزم بحدود الطول: العنوان ≤ {tmax} حرفًا والوصف ≤ {dmax} حرفًا.
أعد JSON المصحح فقط."""

REVISE_SYSTEM = """أنت محرر عربي دقيق. ستتلقى مقالًا بصيغة JSON وقائمة بمشكلات يجب إصلاحها.
أصلح المشكلات المذكورة فقط بأقل تغيير ممكن، وأبقِ باقي النص كما هو حرفيًا.
العدّ: الكلمة = أي مقطع يفصله فراغ ويحوي حرفًا أو رقمًا. عدد كلمات المقال = المقدمة + العنوان الفرعي + كل الفقرات (لا خاتمة). عند الإضافة أضف تفصيلًا مفيدًا من معنى النص نفسه دون اختلاق وقائع ودون حشو؛ وعند الحذف احذف الأقل أهمية دون حذف حقيقة. عدّل فقرة أو فقرتين فقط ليتطابق العدد، وأعد العدّ بدقة قبل الإرسال. إن كان النقص 25 كلمة أو أكثر فأضف فقرة جديدة كاملة (بمعلومات من المادة نفسها) بدل مط الفقرات الموجودة.
وعند استبدال صياغة مترجمة حرفيًا قد يتغير العدد، فعوّض الفرق ليبقى العدد المطلوب بالضبط.
حافظ على: الأسماء بالعربية وفق القاموس، وخلو النص من الحروف اللاتينية ومن ذكر المصدر، والكلمة المفتاحية في العنوان وأول المقدمة والعنوان الفرعي ووصف الصورة، وعنوان ≤ {tmax} حرفًا ووصف ≤ {dmax} حرفًا، وفقرات قصيرة.
أعد JSON كاملًا بنفس البنية وأسماء الحقول (بلا خاتمة)."""


def glossary_text(glossary, text_hint):
    """يرسل فقط مصطلحات القاموس التي تظهر في المادة لتقليل الحجم."""
    hint = text_hint.lower()
    rows = [f"{en} = {ar}" for en, ar in glossary.items() if en.lower() in hint]
    return "\n".join(rows) if rows else "لا يوجد"


STYLE_NOTES = {
    "مختصر": "الأسلوب المطلوب: جمل قصيرة وفقرات مركزة بلا استطراد (مع الالتزام التام بعدد الكلمات المحدد).",
    "تحليلي": "الأسلوب المطلوب: نبرة تحليلية تشرح الخلفية والدلالات وما قد يترتب، دون اختلاق وقائع (مع الالتزام التام بعدد الكلمات المحدد).",
    "عاجل": "الأسلوب المطلوب: نبرة خبر عاجل مباشرة تبدأ بالأهم فورًا (مع الالتزام التام بعدد الكلمات المحدد).",
}


def _cap(words):
    """سقف رموز الرد بحسب عدد كلمات المقال (JSON عربي + تفكير قصير)."""
    return min(8000, int(words * 3.5) + 2000)


def length_plan(target):
    """ميزانية الكلمات: (مقدمة، كلمات العنوان الفرعي، [عدد الفقرات لكل قسم]، متوسط الفقرة)."""
    k = max(1, config.SUBHEADINGS)
    intro = min(70, max(30, round(target * 0.12)))
    heading = 6
    rest = max(target - intro - heading * k, 2 * k * 20)
    total_paras = max(2 * k, round(rest / config.PARAGRAPH_WORDS))
    base, extra = divmod(total_paras, k)
    per_section = [base + (1 if i < extra else 0) for i in range(k)]
    return intro, heading, per_section, max(20, round(rest / total_paras))


def write_article(item, article_text, section, glossary, target, problems=None):
    material = f"العنوان الأصلي: {item['title']}\nملخص: {item.get('summary', '')}\nالمادة:\n{article_text}"
    system = WRITE_SYSTEM.format(blog=config.BLOG_NAME, schema=SCHEMA)
    planned = round(target * config.WRITE_OVERSHOOT)   # النماذج تكتب أقل مما يُطلب
    intro_w, head_w, per_section, para_w = length_plan(planned)
    plan = (f"الطول المطلوب: {planned} كلمة بالضبط: مقدمة + عنوان فرعي + فقرات، بلا خاتمة. لا تكتب أقل من هذا العدد.\n"
            f"ميزانية الكلمات: المقدمة {intro_w} كلمة؛ "
            f"{config.SUBHEADINGS} عنوان فرعي (نحو {head_w} كلمات)؛ "
            f"ثم فقرات قصيرة بواقع {', '.join(map(str, per_section))} فقرة لكل عنوان، وكل فقرة نحو {para_w} كلمة.\n"
            "الكلمة = أي مقطع يفصله فراغ ويحوي حرفًا أو رقمًا.")
    user = (f"القسم: {section['label']} ({section['topic']})\n\n{plan}\n\n"
            f"القاموس الإلزامي للأسماء:\n{glossary_text(glossary, material)}\n\n"
            f"{material}")
    if config.WRITING_STYLE in STYLE_NOTES:
        user += "\n\n" + STYLE_NOTES[config.WRITING_STYLE]
    if problems:
        user += "\n\nملاحظات من المحاولة السابقة يجب إصلاحها:\n- " + "\n- ".join(problems)
    return _chat(system, user, temperature=0.5, max_tokens=_cap(target))


def _merge(old, new):
    """يكمل أي حقل ناقص في رد النموذج من النسخة السابقة."""
    if not isinstance(new, dict):
        return old
    merged = dict(old)
    merged.update({k: v for k, v in new.items() if v not in (None, "", [])})
    return merged


def proofread(article, gloss_rows="لا يوجد"):
    """مراجعة لغوية. إن فشلت أو أعادت بنية ناقصة نُبقي المسودة الأصلية بدل إسقاط المقال."""
    system = PROOF_SYSTEM.format(tmax=config.TITLE_MAX, dmax=config.DESCRIPTION_MAX)
    user = f"القاموس الإلزامي للأسماء:\n{gloss_rows}\n\nالمقال:\n{json.dumps(article, ensure_ascii=False)}"
    try:
        fixed = _chat(system, user, temperature=0.1,
                       max_tokens=_cap(arabic_check.article_words(article)))
    except LLMUnavailable as e:
        print(f"   ⚠️ تعذّرت المراجعة اللغوية، نستخدم المسودة: {str(e)[:80]}")
        return article
    if (not isinstance(fixed, dict) or not fixed.get("sections")
            or not fixed.get("title") or not fixed.get("intro")):
        print("   ⚠️ المراجعة أعادت بنية ناقصة، نستخدم المسودة")
        return article
    return _merge(article, fixed)


EXTEND_SYSTEM = """أنت محرر عربي. أمامك مقال ومادة المصدر. اكتب فقرات قصيرة إضافية تُلحق بنهاية المقال، بمعلومات حقيقية من المادة لم يغطها المقال بعد (بلا اختلاق وبلا تكرار لما كُتب)، بالعربية الفصحى وبصياغة أصلية لا حرفية، وبلا ذكر للمصدر وبلا خاتمة.
الأسماء بالعربية وفق القاموس، بلا حروف لاتينية، ولا تستخدم «تم/يتم» ولا «قام بـ». كل فقرة بين 40 و60 كلمة، ونقطة واحدة في نهايتها فقط (استخدم ؛ أو ، داخل الفقرة). عدد الكلمات المطلوب هو مجموع كلمات الفقرات المذكور في رسالة المستخدم، التزم به بدقة.
أعد JSON فقط بهذا الشكل: {"paragraphs": ["فقرة", "فقرة"]}"""


def _valid_extra(res):
    return (isinstance(res, dict) and isinstance(res.get("paragraphs"), list)
            and any(isinstance(p, str) and p.strip() for p in res["paragraphs"]))


def extend(article, need, source_text, gloss_rows="لا يوجد"):
    """يطلب فقرات إضافية مجموع كلماتها need تقريبًا، لسد نقص طول المقال. يعيد قائمة فقرات."""
    k = max(1, round(need / 55))
    body = "\n".join(p for p in arabic_check.body_parts(article) if p)
    user = (f"المطلوب إضافته: {need} كلمة بالضبط (مجموع كلمات الفقرات)، موزعة على {k} فقرة.\n\n"
            f"القاموس الإلزامي للأسماء:\n{gloss_rows}\n\n"
            f"المقال الحالي:\n{body}\n\nمادة المصدر:\n{source_text[:12000]}")
    res = _chat(EXTEND_SYSTEM, user, temperature=0.3, max_tokens=_cap(need), check=_valid_extra)
    return [p for p in res["paragraphs"] if isinstance(p, str) and p.strip()]


REFIT_SYSTEM = """أنت محرر عربي دقيق في العدّ. ستتلقى فقرة واحدة قصيرة وعدد الكلمات المطلوب لها. أعد كتابتها بحيث يصبح عدد كلماتها هو العدد المطلوب بالضبط، بنفس المعنى والحقائق (عند الإضافة أضف تفصيلًا مفيدًا من المعنى نفسه دون اختلاق؛ وعند الحذف احذف الأقل أهمية)، بعربية فصحى سليمة وبلا «تم/يتم» ولا «قام بـ»، وبلا حروف لاتينية، ونقطة واحدة في نهايتها فقط (استخدم ؛ أو ، داخلها).
الكلمة = أي مقطع يفصله فراغ ويحوي حرفًا أو رقمًا. عُدّ كلمة كلمة قبل الإرسال.
أعد JSON فقط: {"paragraph": "النص"}"""


def refit_paragraph(paragraph, want, have, gloss_rows="لا يوجد", feedback=None, context=""):
    """يعيد كتابة فقرة واحدة لتصير want كلمة بالضبط (فقرة قصيرة يسهل عدّها)."""
    user = (f"الفقرة الحالية ({have} كلمة):\n{paragraph}\n\n"
            f"عدد الكلمات المطلوب: {want} بالضبط.\n")
    if feedback:
        user += f"ملاحظة من المحاولة السابقة: {feedback}\n"
    user += f"\nالقاموس الإلزامي للأسماء:\n{gloss_rows}\n\nسياق المقال (للفهم فقط):\n{context[:1500]}"
    res = _chat(REFIT_SYSTEM, user, temperature=0.2, max_tokens=_cap(want),
                check=lambda r: isinstance(r, dict) and isinstance(r.get("paragraph"), str) and r["paragraph"].strip())
    return res["paragraph"]


def revise(article, target, problems, gloss_rows="لا يوجد", with_length=True):
    """جولة ضبط: يصلح الطول والصياغة الحرفية والسيو بأقل تغيير ممكن."""
    system = REVISE_SYSTEM.format(tmax=config.TITLE_MAX, dmax=config.DESCRIPTION_MAX)
    material = json.dumps(article, ensure_ascii=False)
    if with_length:
        head = (f"الطول المطلوب: {target} كلمة بالضبط.\n"
                f"عدد الكلمات الحالي: {arabic_check.article_words(article)}.\n\n"
                f"عدد كلمات كل جزء حاليًا:\n{arabic_check.word_report(article)}\n\n")
    else:
        head = "ضبط الطول يتم آليًا لاحقًا: لا تتعمد زيادة النص أو تقليصه، وركّز على المشكلات التالية فقط.\n\n"
    user = (head +
            "المشكلات المطلوب إصلاحها:\n- " + "\n- ".join(problems) +
            f"\n\nالقاموس الإلزامي للأسماء:\n{gloss_rows}\n\nالمقال:\n{material}")
    return _merge(article, _chat(system, user, temperature=0.2, max_tokens=_cap(target)))
