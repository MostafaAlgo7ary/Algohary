"""وظائف الحكومة من بوابة CAOA: مصدر موثوق. بيانات الوظيفة تُنقل حرفيًا من صفحة الإعلان، وفوقها قيمة مضافة:
ملخص وخطوات تقديم ودليل «هل تناسبك» تُبنى بالكود من حقول الإعلان نفسها (بلا اختلاق)، وتحليل نصي اختياري بالنموذج
يُرفض آليًا إن ذكر رقمًا أو تاريخًا غير موجود في الإعلان. الاستخدام: python -m src.jobs  (من جذر المشروع)."""
import hashlib
import html
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests

import config
from src import blogger, jobs_image

JOBS_SOURCE_URL = "https://jobs.caoa.gov.eg/Jobs/SearchJobs.aspx?WorkType=1"
JOBS_SOURCE_NAME = "بوابة الوظائف الحكومية (CAOA)"
JOBS_LABEL = "وظائف"
SEED_FILE = "data/jobs_seed.txt"
JOBS_HISTORY = "data/jobs_history.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# عناوين الحقول كما تظهر في صفحة الوظيفة
FIELDS = {
    "الجهة الطالبة للإعلان:": "entity",
    "العدد المطلوب:": "count",
    "محل العمل:": "place",
    "الغرض من الوظيفة:": "purpose",
    "الحد الأقصى للسن وقت التقديم:": "age",
    "المؤهل المطلوب:": "qualification",
    "التقدير المطلوب:": "grade",
    "الخبرات والجدارات:": "skills",
    "تاريخ بداية التقديم:": "start",
    "تاريخ نهاية التقديم:": "end",
    "المستندات المطلوبة:": "documents",
    "مكان التقديم:": "how",
    "بيانات أخرى:": "other",
}
SECTION_TITLES = {"بيانات أساسية", "وصف الوظيفة", "بيانات التقديم", "الجهة التابع لها:",
                  "الملفات الخاصة بالوظيفة:"}


def parse_jobs(text):
    """يحوّل نص صفحات الوظائف (كل وظيفة تبدأ بـ«مسمى الوظيفة:») إلى قواميس."""
    jobs = []
    for block in re.split(r"(?m)^(?=مسمى الوظيفة:)", text):
        if not block.strip().startswith("مسمى الوظيفة:"):
            continue
        lines = [l.strip() for l in block.splitlines()]
        job = {"title": lines[0].split(":", 1)[1].strip()}
        cur = None
        for l in lines[1:]:
            if l in FIELDS:
                cur = FIELDS[l]
                job.setdefault(cur, [])
            elif l in SECTION_TITLES:
                cur = None
            elif cur and l:
                job[cur].append(l)
        for k, v in list(job.items()):
            if isinstance(v, list):
                job[k] = "\n".join(v).strip()
        if job.get("entity"):
            jobs.append(job)
    return jobs


def fingerprint(job):
    raw = "|".join(job.get(k, "") for k in ("entity", "title", "place", "end", "count", "qualification"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ---------- جلب الجديد من البوابة (best effort) ----------
def fetch_live():
    """يقرأ صفحة القائمة ثم كل صفحة تفاصيل. أي فشل يُطبع ولا يُسقط التشغيل."""
    from bs4 import BeautifulSoup
    try:
        r = requests.get(JOBS_SOURCE_URL, headers={"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"}, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"⚠️ تعذّر فتح بوابة الوظائف: {e}")
        return []
    soup = BeautifulSoup(r.content, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"(JobDetails|Details|ViewJob|JobID|JobId|ID=)", href, re.I) and not href.startswith("javascript"):
            url = urljoin(JOBS_SOURCE_URL, href)
            if url not in seen:
                seen.add(url)
                links.append(url)
    print(f"ℹ️ روابط تفاصيل وجدناها في البوابة: {len(links)}")
    jobs = []
    for url in links[:80]:
        try:
            page = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"}, timeout=30)
            page.raise_for_status()
            text = BeautifulSoup(page.content, "html.parser").get_text("\n")
            text = re.sub(r"\n\s*\n+", "\n", text)
            found = parse_jobs(text[text.find("مسمى الوظيفة:"):] if "مسمى الوظيفة:" in text else "")
            for j in found:
                j["url"] = url
            jobs.extend(found)
        except Exception as e:
            print(f"⚠️ تخطي {url}: {e}")
        time.sleep(1)
    return jobs


# ---------- التجميع والكتابة ----------
def _subject(title):
    m = re.search(r"مادة\s+(.+?)(?:\s+(?:بمحافظة|محافظة)\s+(.+))?$", title)
    return (m.group(1).strip(), (m.group(2) or "").strip()) if m else ("", "")


def group_jobs(jobs):
    groups = {}
    for j in jobs:
        if j["title"].startswith("معلم حصة"):
            subj, gov = _subject(j["title"])
            key = f"{j['entity']}|معلم حصة|{subj}|{gov}"
        else:
            key = f"{j['entity']}|{j.get('start', '')}|{j.get('end', '')}"
            if "بنك" in j["entity"]:
                key = j["entity"] + "|" + j.get("end", "") + ("|تعاقد" if "(تعاقد)" in j["title"] else "|تعيين")
        groups.setdefault(key, []).append(j)
    return list(groups.values())


def _clean_name(entity):
    return entity.replace("والتعليم الفني", "").strip()


def title_for(group):
    j = group[0]
    ent = _clean_name(j["entity"])
    if j["title"].startswith("معلم حصة"):
        subj, gov = _subject(j["title"])
        return f"وظائف معلم حصة {subj} {('في ' + gov) if gov else ''} من {ent}".replace("  ", " ")[:90]
    kind = ""
    if "بنك" in j["entity"]:
        kind = " (تعاقد)" if "(تعاقد)" in j["title"] else " (تعيين)"
    return f"وظائف {ent}{kind}: التقديم حتى {j.get('end', '')}".replace("  ", " ")[:90]


# ---------- القيمة المضافة (بلا اختلاق) ----------
_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _parse_date(text):
    """يحاول قراءة تاريخ بصيغة يوم/شهر/سنة أو سنة-شهر-يوم. يعيد None إن لم يفهمه."""
    import datetime
    t = (text or "").translate(_AR)
    m = re.search(r"(\d{1,4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,4})", t)
    if not m:
        return None
    a, b, c = (int(x) for x in m.groups())
    try:
        if a > 31:
            return datetime.date(a, b, c)
        return datetime.date(c, b, a)
    except ValueError:
        return None


def _days_left(job):
    import datetime
    d = _parse_date(job.get("end", ""))
    if not d:
        return None
    return (d - datetime.date.today()).days


def _total_count(group):
    total = 0
    for j in group:
        m = re.search(r"\d+", (j.get("count") or "").translate(_AR))
        if not m:
            return None
        total += int(m.group())
    return total


def _lines(text):
    return [x.strip() for x in (text or "").split("\n") if x.strip()]


def quick_summary(group):
    """ملخص سريع: كل بند مأخوذ من حقول الإعلان أو محسوب منها."""
    j0 = group[0]
    items = []
    total = _total_count(group)
    if total:
        items.append(f"عدد الوظائف المعلنة في هذا الإعلان: {total}")
    places = sorted({p for j in group for p in _lines(j.get("place"))})
    if places:
        items.append("محل العمل: " + "، ".join(places[:6]))
    if j0.get("start") and j0.get("end"):
        items.append(f"فترة التقديم: من {j0['start']} إلى {j0['end']}")
    left = _days_left(j0)
    if left is not None:
        if left < 0:
            items.append("تنبيه: موعد نهاية التقديم المذكور في الإعلان انقضى، تأكد من الصفحة الرسمية قبل أي خطوة")
        elif left == 0:
            items.append("آخر يوم للتقديم هو اليوم")
        else:
            items.append(f"المتبقي على نهاية التقديم: {left} يومًا")
    return items


def who_fits(group):
    """من تناسبه الوظيفة: مأخوذ من شروط الإعلان نفسها."""
    items = []
    for j in group[:4]:
        bits = []
        if j.get("qualification"):
            bits.append("المؤهل المطلوب: " + " - ".join(_lines(j["qualification"])[:3]))
        if j.get("grade"):
            bits.append("التقدير: " + " - ".join(_lines(j["grade"])[:2]))
        if j.get("age"):
            bits.append("الحد الأقصى للسن: " + " - ".join(_lines(j["age"])[:2]))
        if bits:
            items.append((j["title"], "؛ ".join(bits)))
    return items


def apply_steps(group):
    """خطوات التقديم مرتبة، كل خطوة مبنية على بيانات الإعلان."""
    j0 = group[0]
    src = j0.get("url") or JOBS_SOURCE_URL
    steps = ["افتح صفحة الإعلان الرسمية وراجع بيانات الوظيفة التي تهمك قبل أي خطوة."]
    steps.append("تأكد من أن شروطك تنطبق على الوظيفة: المؤهل والتقدير والحد الأقصى للسن المذكورة في قسم «هل تناسبك».")
    docs = []
    for j in group:
        for d in _lines(j.get("documents")):
            if d not in docs:
                docs.append(d)
    if docs:
        steps.append("جهّز المستندات المطلوبة (" + "؛ ".join(docs[:8]) + ") في صورة واضحة قبل بدء التقديم.")
    how = " ".join(_lines(j0.get("how")))
    if how:
        steps.append("قدّم بالطريقة المذكورة في الإعلان: " + how)
    else:
        steps.append("قدّم عبر الرابط أو الجهة المذكورة في صفحة الإعلان الرسمية.")
    if j0.get("end"):
        steps.append(f"أنهِ التقديم قبل {j0['end']}، ولا تترك الخطوة الأخيرة ليوم الانتهاء.")
    steps.append("احتفظ بما يثبت إتمام التقديم (رقم الطلب أو لقطة شاشة) لحين الإعلان عن المرحلة التالية.")
    return steps


def _facts_blob(group):
    rows = []
    for j in group[:6]:
        rows.append("\n".join(f"{k}: {v}" for k, v in j.items() if k not in ("fp", "url") and v))
    return "\n---\n".join(rows)


JOB_ANALYSIS_SYSTEM = """أنت محرر عربي في «{blog}». تتلقى بيانات إعلان وظيفي رسمي. اكتب تحليلًا مفيدًا للقارئ الباحث عن عمل بالعربية الفصحى، من البيانات المعطاة فقط.
ممنوع ذكر أي رقم أو تاريخ أو اسم جهة أو شرط غير موجود حرفيًا في البيانات. لا تعد بالتعيين ولا تتوقع فرص القبول ولا تذكر رواتب أو مزايا غير مذكورة.
المطلوب: (1) overview: فقرة من 50 إلى 80 كلمة تشرح بلغة بسيطة طبيعة الوظيفة أو الوظائف ولمن تناسب، (2) watch_out: من 2 إلى 3 نقاط عن أشياء ينتبه لها المتقدم وتستند إلى البيانات (مثل تعدد الشروط أو قرب الموعد أو اختلاف المؤهل بين الوظائف)، (3) preparation: من 2 إلى 3 نصائح عامة للاستعداد لهذا النوع من الوظائف بصياغة حذرة («يفيد أن»، «يُستحسن») دون ادعاء حقائق عن الجهة.
لا تنسخ الجمل من الإعلان، وبلا أي حروف لاتينية، وبلا «تم/يتم» ولا «قام بـ».
أعد JSON فقط: {{"overview": "...", "watch_out": ["..."], "preparation": ["..."]}}"""


def llm_analysis(group):
    """تحليل اختياري. أي فشل أو رقم غير موجود في الإعلان = نتجاهله ونكتفي بالبنود المبنية بالكود."""
    if not config.GROQ_API_KEY:
        return None
    try:
        from src import writer, arabic_check
        blob = _facts_blob(group)
        system = JOB_ANALYSIS_SYSTEM.format(blog=config.BLOG_NAME)
        res = writer._chat(system, "بيانات الإعلان:\n" + blob, temperature=0.3, max_tokens=1800,
                           check=lambda r: isinstance(r, dict) and isinstance(r.get("overview"), str) and r["overview"].strip())
        texts = [res["overview"]] + [x for k in ("watch_out", "preparation") for x in (res.get(k) or []) if isinstance(x, str)]
        allowed = arabic_check._numbers(blob)
        for t in texts:
            if arabic_check._numbers(t) - allowed or re.search(r"[A-Za-z]", t):
                print("ℹ️ تحليل النموذج رُفض (رقم أو حرف لاتيني غير موجود في الإعلان)، نكتفي بالبنود الآلية")
                return None
        if arabic_check.count_words(res["overview"]) < 25:
            return None
        return {"overview": arabic_check.normalize(res["overview"]),
                "watch_out": [arabic_check.normalize(x) for x in (res.get("watch_out") or []) if isinstance(x, str)][:3],
                "preparation": [arabic_check.normalize(x) for x in (res.get("preparation") or []) if isinstance(x, str)][:3]}
    except Exception as e:
        print(f"ℹ️ تعذّر تحليل النموذج: {str(e)[:100]}")
        return None


def _p(text):
    return "".join(f"<p>{html.escape(x)}</p>" for x in text.split("\n") if x.strip())


def _list(text):
    items = [x for x in text.split("\n") if x.strip()]
    return "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>" if items else ""


def render(group, image_url="", alt="", related=None, analysis=None):
    """HTML المقال: كل وظيفة بعنوان فرعي وبياناتها الكاملة كما وردت في الإعلان الرسمي."""
    j0 = group[0]
    ent = _clean_name(j0["entity"])
    intro = (f"أعلنت {ent} عن وظائف جديدة عبر البوابة الحكومية للوظائف (عدد الإعلانات في هذا المقال: {len(group)}). "
             f"التقديم ينتهي في {j0.get('end', 'الموعد المذكور في الإعلان')}. "
             "هذه البيانات منقولة من صفحة الإعلان الرسمي، ويُنصح بمراجعة الصفحة نفسها قبل التقديم.")
    parts = []
    if image_url:
        parts.append('<div class="separator" style="clear: both; text-align: center;">'
                     f'<img alt="{html.escape(alt)}" border="0" height="630" width="1200" '
                     f'src="{html.escape(image_url)}" style="max-width:100%;height:auto"/></div>')
    parts.append(f"<p>{html.escape(intro)}</p>")
    summary = quick_summary(group)
    if summary:
        parts.append("<h2>ملخص سريع للإعلان</h2><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in summary) + "</ul>")
    fits = who_fits(group)
    if fits:
        parts.append("<h2>هل تناسبك هذه الوظيفة؟</h2><p>راجع شروطك مع ما ورد في الإعلان الرسمي لكل وظيفة:</p><ul>" +
                     "".join(f"<li><b>{html.escape(t)}:</b> {html.escape(d)}</li>" for t, d in fits) + "</ul>")
    parts.append("<h2>خطوات التقديم</h2><ol>" + "".join(f"<li>{html.escape(x)}</li>" for x in apply_steps(group)) + "</ol>")
    if analysis:
        parts.append("<h2>قراءة في الإعلان</h2>" + f"<p>{html.escape(analysis['overview'])}</p>")
        if analysis.get("watch_out"):
            parts.append("<h3>انتبه إلى</h3><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in analysis["watch_out"]) + "</ul>")
        if analysis.get("preparation"):
            parts.append("<h3>كيف تستعد</h3><ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in analysis["preparation"]) + "</ul>")
    parts.append("<h2>تفاصيل الإعلان الرسمي</h2>")
    for j in group:
        parts.append(f"<h2>{html.escape(j['title'])}</h2>")
        rows = [("جهة الإعلان", j.get("entity")), ("العدد المطلوب", j.get("count")), ("محل العمل", j.get("place")),
                ("الحد الأقصى للسن", j.get("age")), ("التقدير المطلوب", j.get("grade")),
                ("بداية التقديم", j.get("start")), ("نهاية التقديم", j.get("end"))]
        parts.append("<ul>" + "".join(f"<li><b>{k}:</b> {html.escape(v.replace(chr(10), ' - '))}</li>"
                                      for k, v in rows if v) + "</ul>")
        for k, label in (("purpose", "الغرض من الوظيفة"), ("qualification", "المؤهل المطلوب"),
                         ("skills", "الخبرات والجدارات"), ("documents", "المستندات المطلوبة"),
                         ("how", "طريقة ومكان التقديم"), ("other", "بيانات أخرى")):
            if j.get(k):
                parts.append(f"<h3>{label}</h3>" + (_list(j[k]) if k in ("qualification", "skills", "documents") else _p(j[k])))
    src = j0.get("url") or JOBS_SOURCE_URL
    parts.append(f'<p><small>المصدر: <a href="{html.escape(src)}" target="_blank" rel="nofollow noopener">'
                 f"{JOBS_SOURCE_NAME}</a></small></p>")
    if related:
        items = "".join(f'<li><a href="{html.escape(u)}">{html.escape(t)}</a></li>' for t, u in related)
        parts.append(f"<h3>اقرأ أيضًا</h3><ul>{items}</ul>")
    return "\n".join(parts)


def load_history():
    try:
        with open(JOBS_HISTORY, encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def save_history(h):
    os.makedirs("data", exist_ok=True)
    with open(JOBS_HISTORY, "w", encoding="utf-8") as f:
        json.dump(sorted(h), f, ensure_ascii=False, indent=1)


def main():
    dry = os.environ.get("INPUT_DRY_RUN", "false").lower() == "true"
    only_live = os.environ.get("INPUT_ONLY_LIVE", "false").lower() == "true"
    if not dry and not config.BLOG_ID:
        sys.exit("❌ BLOG_ID مطلوب")
    jobs = []
    if not only_live and os.path.exists(SEED_FILE):
        with open(SEED_FILE, encoding="utf-8") as f:
            jobs += parse_jobs(f.read())
    jobs += fetch_live()
    history = set() if os.environ.get("INPUT_IGNORE_HISTORY", "false").lower() == "true" else load_history()
    new, seen = [], set()
    for j in jobs:
        fp = fingerprint(j)
        if fp not in history and fp not in seen:
            seen.add(fp)
            j["fp"] = fp
            new.append(j)
    groups = group_jobs(new)
    print(f"وظائف جديدة: {len(new)} في {len(groups)} مقال")
    failed = 0
    for g in groups:
        title = title_for(g)
        try:
            card = jobs_image.make_card(title, g[0].get("end", ""), len(g), _clean_name(g[0]["entity"]))
            img_url = jobs_image.public_url(card)
        except Exception as e:          # فشل الصورة لا يمنع النشر
            print(f"⚠️ تعذّر رسم الصورة: {e}")
            img_url = ""
        related = [] if dry else blogger.related_posts(JOBS_LABEL, config.RELATED_LINKS)
        analysis = None if dry else llm_analysis(g)
        body = render(g, img_url, title, related, analysis)
        if dry:
            print("🧪", title, len(body))
            continue
        try:
            res = blogger.publish(title, body, [JOBS_LABEL])
            print(f"✅ {title}: {res}")
            history.update(j["fp"] for j in g)
            save_history(history)
        except Exception as e:
            failed += 1
            print(f"❌ {title}: {e}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
