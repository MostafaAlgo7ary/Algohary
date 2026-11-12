"""الإعدادات المركزية للمشروع. عدّل هنا فقط."""
import os

# ---------- المدونة ----------
BLOG_NAME = "مدونة الجوهري"
BLOG_ID = os.environ.get("BLOG_ID", "")
BLOG_URL = os.environ.get("BLOG_URL", "").rstrip("/")  # مثال: https://example.blogspot.com

# ---------- النشر ----------
# True = يُنشر المقال كمسودة لتراجعه ثم تضغط "نشر". غيّرها إلى False بعد أن تطمئن للجودة.
PUBLISH_AS_DRAFT = os.environ.get("PUBLISH_AS_DRAFT", "true").lower() != "false"
# عدد المقالات في كل تشغيلة (قسم واحد لكل مقال، بالتناوب)
ARTICLES_PER_RUN = int(os.environ.get("ARTICLES_PER_RUN", "1"))
# عدد التصنيفات الإضافية غير القسم (0 = القسم فقط، وهو الأنظف للسيو)
EXTRA_LABELS = int(os.environ.get("EXTRA_LABELS", "0"))
# عدد روابط "اقرأ أيضًا" الداخلية
RELATED_LINKS = 3

# ---------- الأقسام (الاسم يجب أن يطابق التصنيف في بلوجر حرفيًا) ----------
SECTIONS = [
    {"label": "رياضة",  "key": "sport",  "color": (27, 138, 60),  "topic": "الأخبار الرياضية وكرة القدم"},
    {"label": "تقنية",  "key": "tech",   "color": (11, 79, 138),  "topic": "أخبار التقنية والذكاء الاصطناعي والهواتف"},
    {"label": "ألعاب",  "key": "games",  "color": (109, 63, 208), "topic": "أخبار الألعاب الإلكترونية"},
    {"label": "سفر",    "key": "travel", "color": (10, 143, 152), "topic": "السفر والسياحة والوجهات"},
    {"label": "فن",     "key": "art",    "color": (194, 37, 92),  "topic": "الفنون والثقافة والمعارض"},
    {"label": "طعام",   "key": "food",   "color": (217, 87, 15),  "topic": "الطعام والمطبخ والوصفات"},
    {"label": "اقتصاد", "key": "econ",   "color": (148, 102, 0),  "topic": "الاقتصاد والأسواق والأعمال"},
]

# ---------- نماذج Groq (تُجرَّب بالترتيب) ----------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODELS = [
    m.strip() for m in os.environ.get(
        "GROQ_MODELS",
        "openai/gpt-oss-120b,openai/gpt-oss-20b,qwen/qwen3.6-27b",
    ).split(",") if m.strip()
]

# ---------- حدود الجودة ----------
TITLE_MAX = 60
DESCRIPTION_MAX = 150
MIN_WORDS = 350
MAX_WORDS = 900
MAX_SOURCE_OVERLAP = 0.12   # أقصى نسبة تشابه (5 كلمات متتالية) مع نص المصدر
MAX_ATTEMPTS = 3            # محاولات الكتابة لكل خبر
MAX_CANDIDATES = 6          # عدد الأخبار التي نجرب بها قبل التخلي عن القسم

# ---------- الملفات ----------
HISTORY_FILE = "data/history.json"
STATE_FILE = "data/state.json"
FAILED_FILE = "data/failed.json"
IMAGES_DIR = "images"
SOURCES_FILE = "sources.json"
GLOSSARY_FILE = "glossary.json"
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")  # يملأه GitHub تلقائيًا
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

USER_AGENT = ("Mozilla/5.0 (compatible; AlJawhariBot/1.0; +news-lead-reader) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
