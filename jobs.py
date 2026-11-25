"""وظائف الحكومة من بوابة CAOA: مصدر موثوق. لا نموذج لغوي هنا: كل معلومة تُنقل حرفيًا من صفحة الوظيفة،
فلا مجال لاختلاق شروط أو مواعيد. الاستخدام: python -m src.jobs  (من جذر المشروع)."""
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
from src import blogger

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


def _p(text):
    return "".join(f"<p>{html.escape(x)}</p>" for x in text.split("\n") if x.strip())


def _list(text):
    items = [x for x in text.split("\n") if x.strip()]
    return "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in items) + "</ul>" if items else ""


def render(group):
    """HTML المقال: كل وظيفة بعنوان فرعي وبياناتها الكاملة كما وردت في الإعلان الرسمي."""
    j0 = group[0]
    ent = _clean_name(j0["entity"])
    intro = (f"أعلنت {ent} عن وظائف جديدة عبر البوابة الحكومية للوظائف (عدد الإعلانات في هذا المقال: {len(group)}). "
             f"التقديم ينتهي في {j0.get('end', 'الموعد المذكور في الإعلان')}. "
             "هذه البيانات منقولة من صفحة الإعلان الرسمي، ويُنصح بمراجعة الصفحة نفسها قبل التقديم.")
    parts = [f"<p>{html.escape(intro)}</p>"]
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
    history = load_history()
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
        title, body = title_for(g), render(g)
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
