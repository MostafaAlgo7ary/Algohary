"""توليد بطاقة صورة أصلية بهوية القسم (لون + أيقونة + شارة لكل قسم). نفس واجهة الملف القديم:
make_card(title, section) و public_url(path)."""
import os

import config

try:
    from src import section_image
except ImportError:  # للاختبار المحلي
    import section_image


def make_card(title, section):
    label = section["label"]
    if label not in section_image.SECTIONS:
        # قسم جديد غير معرّف: نبني له هوية من لونه بدون أيقونة خاصة
        r, g, b = section["color"]
        dark = tuple(int(c * 0.5) for c in (r, g, b))
        section_image.SECTIONS[label] = (section.get("key", "section"), (r, g, b), dark, (245, 190, 70), "none")
    return section_image.make_card(label, title)


def public_url(path):
    """رابط الصورة بعد رفعها على GitHub (المستودع يجب أن يكون عامًا)."""
    if not config.GITHUB_REPOSITORY:
        return ""
    name = os.path.basename(path)
    return (f"https://raw.githubusercontent.com/{config.GITHUB_REPOSITORY}/"
            f"{config.GITHUB_BRANCH}/{config.IMAGES_DIR}/{name}")
