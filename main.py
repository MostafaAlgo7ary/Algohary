"""نقطة التشغيل: يختار الأقسام بالتناوب، يجلب خبرًا جديدًا، يكتب مقالًا أصليًا، يراجعه، وينشره."""
import json
import sys

import config
from src import arabic_check, blogger, fetcher, html_builder, images, state, writer


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def allowed_latin_words():
    return {"var", "vr", "ai", "ps5", "ps4", "pc", "fifa", "uefa", "vpn", "gps", "usb", "5g", "4g"}


def build_article(item, section, glossary):
    """يكتب ويراجع ويتحقق. يعيد (مقال، None) أو (None، سبب الفشل)."""
    text = fetcher.fetch_article_text(item["url"])
    source_text = f"{item['title']} {item.get('summary', '')} {text}"
    if len(source_text) < 300:
        return None, "مادة المصدر قصيرة جدًا"

    problems = None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        print(f"   ✍️ محاولة الكتابة {attempt}/{config.MAX_ATTEMPTS}")
        try:
            article = writer.write_article(item, text or item.get("summary", ""), section, glossary, problems)
            article = writer.proofread(article)
        except Exception as e:
            problems = [f"خطأ تقني: {str(e)[:100]}"]
            continue

        # تنظيف آلي لكل الحقول النصية
        article["title"] = arabic_check.normalize(article.get("title", ""))
        article["description"] = arabic_check.normalize(article.get("description", ""))
        article["intro"] = arabic_check.normalize(article.get("intro", ""))
        article["conclusion"] = arabic_check.normalize(article.get("conclusion", ""))
        for s in article.get("sections", []):
            s["heading"] = arabic_check.normalize(s.get("heading", ""))
            s["paragraphs"] = [arabic_check.normalize(p) for p in s.get("paragraphs", [])]

        problems = arabic_check.validate(article, allowed_latin_words(), config)
        body = " ".join([article["intro"], article["conclusion"]] +
                        [p for s in article["sections"] for p in s["paragraphs"]])
        overlap = arabic_check.source_overlap(body, source_text)
        if overlap > config.MAX_SOURCE_OVERLAP:
            problems.append(f"تشابه مرتفع مع المصدر ({overlap:.0%}) — أعد الصياغة بالكامل")
        if not problems:
            return article, None
        print("   ⚠️ مشكلات:", " | ".join(problems))
    return None, "؛ ".join(problems or ["فشل غير معروف"])


def run_section(section, sources_cfg, glossary, history):
    print(f"\n━━━ القسم: {section['label']} ━━━")
    candidates = [c for c in fetcher.fetch_candidates(section["label"], sources_cfg)
                  if c["url"] not in history]
    print(f"   عدد الأخبار الجديدة: {len(candidates)}")
    # مصادر متنوعة: نتناوب بين المصادر بدل الاكتفاء بالأول
    by_source, mixed = {}, []
    for c in candidates:
        by_source.setdefault(c["source"], []).append(c)
    while any(by_source.values()):
        for k in list(by_source):
            if by_source[k]:
                mixed.append(by_source[k].pop(0))

    for item in mixed[:config.MAX_CANDIDATES]:
        print(f" • {item['source']}: {item['title'][:70]}")
        article, reason = build_article(item, section, glossary)
        if not article:
            state.save_failed(item["url"], item["source"], section["label"], reason)
            history.add(item["url"])      # لا نكرر نفس الخبر الفاشل
            state.save_history(item["url"], item["source"], section["label"], "(فشل) " + reason[:80])
            continue

        card = images.make_card(article["title"], section)
        related = blogger.related_posts(section["label"], config.RELATED_LINKS)
        html = html_builder.build_html(article, images.public_url(card), item["source"], item["url"], related)
        labels = [section["label"]] + [l for l in article.get("extra_labels", [])][:config.EXTRA_LABELS]
        result = blogger.publish(article["title"], html, labels)
        print(f"   ✅ تم ({'مسودة' if config.PUBLISH_AS_DRAFT else 'منشور'}): {result}")
        state.save_history(item["url"], item["source"], section["label"], article["title"])
        history.add(item["url"])
        return True
    print("   ⛔ لم يُنشر شيء لهذا القسم")
    return False


def main():
    if not config.GROQ_API_KEY or not config.BLOG_ID:
        sys.exit("❌ GROQ_API_KEY و BLOG_ID مطلوبان")
    sources_cfg, glossary = load_json(config.SOURCES_FILE), load_json(config.GLOSSARY_FILE)
    history = state.load_history_links()
    sections, next_index = state.next_sections(config.ARTICLES_PER_RUN)
    for section in sections:
        try:
            run_section(section, sources_cfg, glossary, history)
        except Exception as e:  # خطأ في قسم لا يوقف الباقي
            print(f"❌ خطأ في قسم {section['label']}: {e}")
    state.commit_section_index(next_index)


if __name__ == "__main__":
    main()
