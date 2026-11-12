"""تحويل المقال إلى HTML نظيف للنشر في بلوجر."""
from html import escape


def build_html(article, image_url, source_name, source_url, related):
    # لا يُذكر المصدر داخل المقال (المعاملان source_name/source_url يبقيان للتوافق فقط)
    parts = []
    if image_url:
        parts.append(
            f'<div class="separator" style="clear: both; text-align: center;">'
            f'<img alt="{escape(article["image_alt"])}" border="0" height="630" width="1200" '
            f'src="{escape(image_url)}" style="max-width:100%;height:auto"/></div>')
    parts.append(f"<p>{escape(article['intro'])}</p>")
    for sec in article["sections"]:
        parts.append(f"<h2>{escape(sec['heading'])}</h2>")
        for p in sec["paragraphs"]:
            parts.append(f"<p>{escape(p)}</p>")
    if related:
        items = "".join(f'<li><a href="{escape(u)}">{escape(t)}</a></li>' for t, u in related)
        parts.append(f"<h3>اقرأ أيضًا</h3><ul>{items}</ul>")
    return "\n".join(parts)
