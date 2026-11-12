"""جلب أخبار المصادر. المصادر تُستخدم كـ«خيوط أخبار» فقط: نأخذ منها الحقائق ولا ننسخ نصّها."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

HEADERS = {"User-Agent": config.USER_AGENT, "Accept-Language": "ar,en;q=0.8"}
TIMEOUT = 15


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ---------- RSS ----------
def fetch_rss(source):
    items = []
    try:
        root = ET.fromstring(_get(source["url"]).content)
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


def fetch_candidates(section_label, sources_cfg):
    out = []
    for source in sources_cfg.get(section_label, []):
        fn = fetch_rss if source["type"] == "rss" else fetch_html_listing
        out.extend(fn(source))
    return out


# ---------- نص الخبر (للحقائق فقط) ----------
def fetch_article_text(url, limit=4000):
    try:
        soup = BeautifulSoup(_get(url).content, "html.parser")
    except Exception as e:
        print(f"⚠️ تعذّر جلب الخبر: {e}")
        return ""
    for t in soup(["script", "style", "nav", "footer", "aside", "form"]):
        t.decompose()
    paras = [_clean(p.get_text(" ")) for p in soup.find_all("p")]
    text = " ".join(p for p in paras if len(p) > 40)
    return text[:limit]


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
