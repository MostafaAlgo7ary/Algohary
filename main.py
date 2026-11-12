"""نقطة التشغيل: يختار الأقسام، يجلب خبرًا جديدًا، يكتب مقالًا أصليًا، يراجعه، وينشره."""
import json
import os
import sys
from urllib.parse import urlparse

import config
from src import arabic_check, blogger, fetcher, html_builder, images, state, writer


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def allowed_latin_words():
    return {"var", "vr", "ai", "ps5", "ps4", "pc", "fifa", "uefa", "vpn", "gps", "usb", "5g", "4g"}


def fit_article(article, target, glossary, source_name):
    """جولات ضبط قصيرة حتى يطابق المقال طول المصدر ويخلو من الصياغات الحرفية وذكر المصدر ومشكلات السيو.
    يعيد (المقال، المشكلات المتبقية)."""
    k = config.SUBHEADINGS
    allowed = allowed_latin_words()
    problems = arabic_check.validate(article, allowed, config, target, source_name, glossary)
    for round_no in range(1, config.FIT_ROUNDS + 1):
        if not problems:
            break
        print(f"   🔧 جولة ضبط {round_no}/{config.FIT_ROUNDS}: {' | '.join(problems)[:220]}")
        try:
            revised = writer.revise(article, target, problems, article_gloss_rows(glossary, article))
        except writer.LLMUnavailable:
            raise
        except Exception as e:
            print(f"   ⚠️ تعذّرت جولة الضبط: {str(e)[:100]}")
            break
        article = arabic_check.clean_article(revised, glossary, k)
        problems = arabic_check.validate(article, allowed, config, target, source_name, glossary)
    return article, problems


def article_gloss_rows(glossary, article):
    """صفوف القاموس الخاصة بأسماء المقال (بالعربية) لتثبيت كتابتها في المراجعة."""
    text = " ".join(arabic_check.body_parts(article) + [article.get("title", "")])
    rows = [f"{en} = {ar}" for en, ar in glossary.items() if ar and ar in text]
    return "\n".join(rows[:40]) if rows else "لا يوجد"


def build_article(item, section, glossary):
    """يكتب ويراجع ويضبط الطول ويتحقق. يعيد (مقال، None) أو (None، سبب الفشل)."""
    text = fetcher.fetch_article_text(item["url"])
    source_text = f"{item['title']} {item.get('summary', '')} {text}"
    if len(source_text) < 300:
        return None, "مادة المصدر قصيرة جدًا"

    # طول المقال المطلوب = عدد كلمات مقال المصدر
    target = arabic_check.count_words(text)
    if target < config.MIN_WORDS:
        return None, f"مقال المصدر قصير جدًا ({target} كلمة)"
    if target > config.MAX_WORDS:
        return None, f"مقال المصدر طويل جدًا ({target} كلمة)"
    print(f"   📏 طول المصدر = الطول المطلوب: {target} كلمة")

    k = config.SUBHEADINGS
    gloss_rows = writer.glossary_text(glossary, source_text)
    problems = None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        print(f"   ✍️ محاولة الكتابة {attempt}/{config.MAX_ATTEMPTS}")
        try:
            article = writer.write_article(item, text, section, glossary, target, problems)
            article = arabic_check.clean_article(article, glossary, k)
            article = writer.proofread(article, gloss_rows)
            article = arabic_check.clean_article(article, glossary, k)
            article, problems = fit_article(article, target, glossary, item["source"])
        except writer.LLMUnavailable:
            raise   # عطل تقني في النماذج لا ذنب للخبر فيه: لا نحرق الخبر ولا نكمل
        except Exception as e:
            problems = [f"خطأ تقني: {str(e)[:100]}"]
            continue

        body = " ".join(arabic_check.body_parts(article))
        overlap = arabic_check.source_overlap(body, source_text)
        if overlap > config.MAX_SOURCE_OVERLAP:
            problems.append(f"تشابه مرتفع مع المصدر ({overlap:.0%}) — أعد الصياغة بالكامل")
        if not problems:
            return article, None
        print("   ⚠️ مشكلات:", " | ".join(problems))
    return None, "؛ ".join(problems or ["فشل غير معروف"])


RESULTS = []   # ملخص التشغيلة يظهر في صفحة Summary داخل GitHub


def external_item(url):
    title = fetcher.fetch_page_title(url) or url
    return {"title": title, "url": url, "summary": "",
            "source": urlparse(url).netloc.replace("www.", "")}


def pick_candidates(section, sources_cfg, history):
    """أخبار القسم بعد تطبيق فلتر المصدر والرابط المخصص، مع تنويع المصادر."""
    cfg = dict(sources_cfg)
    if config.CUSTOM_FEED:
        cfg[section["label"]] = [fetcher.guess_source(config.CUSTOM_FEED)]
    if config.SOURCE_FILTER:
        key = config.SOURCE_FILTER.lower()
        cfg[section["label"]] = [s for s in cfg.get(section["label"], [])
                                 if key in s["name"].lower()]
        if not cfg[section["label"]]:
            print(f"   ⏭️ لا يوجد مصدر باسم «{config.SOURCE_FILTER}» في هذا القسم")
            return []
    candidates = [c for c in fetcher.fetch_candidates(section["label"], cfg)
                  if c["url"] not in history]
    print(f"   عدد الأخبار الجديدة: {len(candidates)}")
    by_source, mixed = {}, []
    for c in candidates:
        by_source.setdefault(c["source"], []).append(c)
    while any(by_source.values()):
        for k in list(by_source):
            if by_source[k]:
                mixed.append(by_source[k].pop(0))
    return mixed


def run_section(section, sources_cfg, glossary, history, forced_item=None):
    print(f"\n━━━ القسم: {section['label']} ━━━")
    mixed = [forced_item] if forced_item else pick_candidates(section, sources_cfg, history)

    for item in mixed[:config.MAX_CANDIDATES]:
        print(f" • {item['source']}: {item['title'][:70]}")
        article, reason = build_article(item, section, glossary)
        if not article:
            RESULTS.append((section["label"], "❌ فشل", item["title"][:60], reason[:80]))
            if not config.DRY_RUN:
                state.save_failed(item["url"], item["source"], section["label"], reason)
                state.save_history(item["url"], item["source"], section["label"], "(فشل) " + reason[:80])
            history.add(item["url"])
            continue

        if config.DRY_RUN:
            print(f"   🧪 تجربة (بدون نشر): {article['title']}\n   {article.get('description', '')}")
            RESULTS.append((section["label"], "🧪 تجربة", article["title"], item["source"]))
            history.add(item["url"])
            return True

        card = images.make_card(article["title"], section)
        related = blogger.related_posts(section["label"], config.RELATED_LINKS)
        html = html_builder.build_html(article, images.public_url(card), item["source"], item["url"], related)
        labels = [section["label"]] + [l for l in article.get("extra_labels", [])][:config.EXTRA_LABELS]
        result = blogger.publish(article["title"], html, labels)
        mode = "مسودة" if config.PUBLISH_AS_DRAFT else "منشور"
        print(f"   ✅ تم ({mode}): {result}")
        RESULTS.append((section["label"], f"✅ {mode}", article["title"], str(result)))
        state.save_history(item["url"], item["source"], section["label"], article["title"])
        history.add(item["url"])
        return True
    print("   ⛔ لم يُنشر شيء لهذا القسم")
    RESULTS.append((section["label"], "⛔ لا شيء", "-", "لم تتوفر أخبار مناسبة"))
    return False


def build_plan():
    """يعيد (قائمة الأقسام بالترتيب، رقم دور التناوب الجديد أو None)."""
    n = 1 if config.EXTERNAL_URL else config.ARTICLES_PER_RUN
    mode = config.SECTION_MODE
    if mode == "كل الأقسام":
        return [s for s in config.SECTIONS for _ in range(n)], None
    if mode != "تناوب تلقائي":
        found = [s for s in config.SECTIONS if s["label"] == mode]
        if not found:
            sys.exit(f"❌ قسم غير معروف: {mode}")
        return found * n, None
    return state.next_sections(n)


def write_summary():
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## نتيجة التشغيل", "",
             f"القسم: **{config.SECTION_MODE}** | الأسلوب: **{config.WRITING_STYLE}** | "
             f"تجربة: **{config.DRY_RUN}**", "",
             "| القسم | الحالة | العنوان | تفاصيل |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in RESULTS]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    if not config.GROQ_API_KEY or not config.BLOG_ID:
        sys.exit("❌ GROQ_API_KEY و BLOG_ID مطلوبان")
    sources_cfg, glossary = load_json(config.SOURCES_FILE), load_json(config.GLOSSARY_FILE)
    history = set() if config.IGNORE_HISTORY else state.load_history_links()
    plan, next_index = build_plan()
    forced = external_item(config.EXTERNAL_URL) if config.EXTERNAL_URL else None
    errors = 0
    llm_down = False
    for section in plan:
        try:
            run_section(section, sources_cfg, glossary, history, forced_item=forced)
        except writer.LLMUnavailable as e:
            # كل النماذج معطلة/في حد الاستخدام: لا فائدة من إكمال بقية الأقسام ولا نحرق الأخبار
            errors += 1
            llm_down = True
            print(f"⛔ توقف التشغيل: {e}")
            RESULTS.append((section["label"], "⛔ النماذج غير متاحة", "-", str(e)[:80]))
            break
        except Exception as e:  # خطأ في قسم لا يوقف الباقي
            errors += 1
            print(f"❌ خطأ في قسم {section['label']}: {e}")
            RESULTS.append((section["label"], "❌ خطأ", "-", str(e)[:80]))
    if next_index is not None and not config.DRY_RUN and not llm_down:
        state.commit_section_index(next_index)
    write_summary()
    if errors:
        sys.exit(1)   # يظهر الفشل باللون الأحمر بدل النجاح الكاذب


if __name__ == "__main__":
    main()
