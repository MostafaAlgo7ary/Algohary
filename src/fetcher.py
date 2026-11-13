"""جلب أخبار المصادر. المصادر تُستخدم كـ«خيوط أخبار» فقط: نأخذ منها الحقائق ولا ننسخ نصّها."""
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": config.USER_AGENT, "Accept-Language": "ar,en;q=0.8"}
TIMEOUT = 15


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code in (403, 406, 429, 503):   # بعض المواقع ترفض الـUA الآلي: نعيد بمتصفح عادي
        r = requests.get(url, headers={**HEADERS, "User-Agent": BROWSER_UA,
                                       "Accept": "application/rss+xml, application/xml, text/xml, text/html, */*"},
                         timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ---------- RSS ----------
def _parse_xml(content):
    """يحلل XML، وعند الفشل ينظّفه من الرموز التالفة ثم يعيد المحاولة."""
    try:
        return ET.fromstring(content)
    except ET.ParseError:
        text = content.decode("utf-8", "ignore")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
        return ET.fromstring(text.encode("utf-8"))


def _discover_feed(html_bytes, base_url):
    soup = BeautifulSoup(html_bytes, "html.parser")
    for l in soup.find_all("link", href=True):
        t = (l.get("type") or "").lower()
        if "alternate" in (l.get("rel") or []) and ("rss" in t or "atom" in t):
            return urljoin(base_url, l["href"])
    return None


def fetch_rss(source, _fallback=True):
    items = []
    try:
        content = _get(source["url"]).content
        try:
            root = _parse_xml(content)
        except ET.ParseError:
            # الرابط لا يعيد XML (غالبًا صفحة HTML أو حماية بوتات): نكتشف رابط الـRSS أو نقرأه كصفحة قائمة
            if not _fallback:
                raise
            feed = _discover_feed(content, source["url"])
            if feed and feed != source["url"]:
                print(f"ℹ️ {source['name']}: استُخدم رابط RSS المكتشف {feed}")
                return fetch_rss({**source, "url": feed}, _fallback=False)
            print(f"ℹ️ {source['name']}: ليس RSS صالحًا، نقرأه كصفحة أخبار")
            return fetch_html_listing(source)
    except Exception as e:
        print(f"⚠️ فشل RSS {source['name']}: {e}")
        return items
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = summary = ""
        for ch in it:
            t = ch.tag.split("}")[-1]
            if t == "title":
                title = _clean(ch.text)
            elif t == "link":
                link = (ch.get("href") or ch.text or "").strip()
            elif t in ("description", "summary", "content"):
                summary = _clean(BeautifulSoup(ch.text or "", "html.parser").get_text(" "))
        if title and link:
            items.append({"title": title, "url": link, "summary": summary,
                          "source": source["name"]})
    return items


# ---------- صفحات القوائم (HTML) ----------
_SKIP = re.compile(r"/(tag|tags|category|author|video|videos|gallery|live|about|contact|privacy|search)(/|$)", re.I)


def fetch_html_listing(source):
    items, seen = [], set()
    try:
        soup = BeautifulSoup(_get(source["url"]).content, "html.parser")
    except Exception as e:
        print(f"⚠️ فشل جلب {source['name']}: {e}")
        return items
    host = urlparse(source["url"]).netloc
    for a in soup.find_all("a", href=True):
        url = urljoin(source["url"], a["href"]).split("#")[0]
        p = urlparse(url)
        title = _clean(a.get_text(" "))
        if p.netloc != host or url in seen or _SKIP.search(p.path):
            continue
        if len(title) < 25 or len(p.path.strip("/")) < 6:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "summary": "", "source": source["name"]})
    return items[:40]


def fetch_nav_section(source):
    """مصدر type=nav: نفتح الصفحة الرئيسية ونبحث في روابطها عن قسم باسم من source["labels"] (بالترتيب)،
    ثم نقرأ صفحة القسم كصفحة قائمة. هكذا لا نحتاج رابط القسم الدقيق."""
    home = source["url"]
    soup = BeautifulSoup(_get(home).content, "html.parser")
    links = [(_clean(a.get_text(" ")), urljoin(home, a["href"]).split("#")[0])
             for a in soup.find_all("a", href=True)]
    for label in source.get("labels", []):
        for text, url in links:
            if text == label and url.rstrip("/") != home.rstrip("/") and not url.startswith("javascript"):
                print(f"ℹ️ {source['name']}: قسم «{label}» → {url}")
                return fetch_html_listing({**source, "url": url})
    print(f"⚠️ {source['name']}: لم نجد قسمًا بالأسماء {source.get('labels')} في قائمة الموقع")
    return []


def fetch_candidates(section_label, sources_cfg):
    out = []
    for source in sources_cfg.get(section_label, []):
        fn = {"rss": fetch_rss, "nav": fetch_nav_section}.get(source["type"], fetch_html_listing)
        try:
            out.extend(fn(source))
        except Exception as e:   # مصدر واحد معطل لا يُسقط القسم كله
            print(f"⚠️ تخطي المصدر {source.get('name')}: {e}")
    return out


# ---------- نص الخبر (للحقائق فقط) ----------
_NOISE_CLASS = re.compile(
    r"(?:^|[-_\s])(related|recommend\w*|share|sharing|social|comments?|newsletter|promo\w*|widget|sidebar|"
    r"breadcrumbs?|advert\w*|ads?|banner|tags?|trending|popular|latest|subscribe|follow|byline|author|"
    r"read-?also|more-stories|outbrain|taboola)(?:$|[-_\s])", re.I)
_BOILER = re.compile(
    r"المصدر المفضل|المصادر المفضلة|تابع أخبار|اقرأ أيضا|اقرأ أيضًا|اقرأ ايضا|شاهد أيضا|الإضافة إلى|"
    r"Read more|Read also|Sign up|Subscribe|newsletter|جميع الحقوق|حقوق النشر|All rights reserved|اشترك", re.I)


def _ld_article_body(soup):
    """نص المقال من بيانات schema.org (articleBody) إن وُجدت: أدق مصدر لجسم الخبر."""
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or sc.get_text())
        except Exception:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                body = x.get("articleBody")
                if isinstance(body, str) and len(body.split()) >= 80:
                    return _clean(BeautifulSoup(body, "html.parser").get_text(" "))
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return ""


def _good_paragraph(p):
    """نص الفقرة إن كانت من جسم الخبر (لا روابط ولا إعلانات ولا عبارات «اقرأ أيضًا»)."""
    t = _clean(p.get_text(" "))
    if len(t) <= 40 or _BOILER.search(t):
        return None
    if sum(len(a.get_text()) for a in p.find_all("a")) / len(t) > 0.6:
        return None
    return t


def fetch_article_text(url, limit=None):
    """جسم الخبر فقط (بلا القوائم والمقالات ذات الصلة والإعلانات): نعدّ كلماته لتحديد طول مقالنا."""
    try:
        soup = BeautifulSoup(_get(url).content, "html.parser")
    except Exception as e:
        print(f"⚠️ تعذّر جلب الخبر: {e}")
        return ""
    text = _ld_article_body(soup)
    if not text:
        for t in soup(["script", "style", "nav", "footer", "aside", "form", "noscript",
                       "figcaption", "button", "header"]):
            t.decompose()
        for el in list(soup.find_all(True)):
            if getattr(el, "decomposed", False) or not el.attrs:
                continue
            marks = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
            if _NOISE_CLASS.search(marks):
                el.decompose()
        scope = soup
        arts = [a for a in soup.find_all("article")
                if sum(len(_good_paragraph(p) or "") for p in a.find_all("p")) > 300]
        if arts:   # أكبر <article> نصًّا
            scope = max(arts, key=lambda a: sum(len(_good_paragraph(p) or "") for p in a.find_all("p")))
        groups = {}
        for p in scope.find_all("p"):
            t = _good_paragraph(p)
            if t:
                groups.setdefault(id(p.parent), [p.parent, 0])[1] += len(t)
        if groups:
            best = max(groups.values(), key=lambda g: g[1])[0]
            cls = best.get("class")
            ok = {k for k, (par, _) in groups.items()
                  if par is best or (cls and par.get("class") == cls)}   # أجزاء الجسم المتفرقة بنفس الصنف
            seen, paras = set(), []
            for p in scope.find_all("p"):
                t = _good_paragraph(p)
                if t and id(p.parent) in ok and t not in seen:
                    seen.add(t)
                    paras.append(t)
            text = " ".join(paras)
    return text[:limit] if limit else text   # النص كاملًا افتراضيًا: نحتاجه لحساب طول المصدر


# ---------- للروابط الخارجية والمخصصة ----------
def fetch_page_title(url):
    """عنوان صفحة خبر (للروابط الخارجية)."""
    try:
        soup = BeautifulSoup(_get(url).content, "html.parser")
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return _clean(og["content"])
        return _clean(soup.title.get_text(" ")) if soup.title else ""
    except Exception as e:
        print(f"⚠️ تعذّر جلب عنوان الرابط: {e}")
        return ""


def guess_source(url):
    """يخمّن نوع الرابط: rss أو صفحة قائمة."""
    host = urlparse(url).netloc.replace("www.", "")
    is_rss = bool(re.search(r"(rss|feed|atom|\.xml)", url, re.I))
    return {"name": host, "type": "rss" if is_rss else "html", "url": url}
