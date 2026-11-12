"""الإعدادات المركزية للمشروع. عدّل هنا فقط."""
import os

# ---------- المدونة ----------
BLOG_NAME = "مدونة الجوهري"
BLOG_ID = os.environ.get("BLOG_ID", "")
BLOG_URL = os.environ.get("BLOG_URL", "").rstrip("/")  # مثال: https://example.blogspot.com

# ---------- النشر ----------
# True = يُنشر المقال كمسودة لتراجعه ثم تضغط "نشر". غيّرها إلى False بعد أن تطمئن للجودة.
PUBLISH_AS_DRAFT = os.environ.get("PUBLISH_AS_DRAFT", "true").lower() != "false"
# عدد المقالات في كل تشغيلة
ARTICLES_PER_RUN = int(os.environ.get("ARTICLES_PER_RUN") or "1")
# عدد التصنيفات الإضافية غير القسم (0 = القسم فقط، وهو الأنظف للسيو)
EXTRA_LABELS = int(os.environ.get("EXTRA_LABELS") or "0")
# عدد روابط "اقرأ أيضًا" الداخلية
RELATED_LINKS = 3


# ---------- تحكم يدوي من Run workflow ----------
def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


SECTION_MODE = _env("INPUT_SECTION", "تناوب تلقائي")   # تناوب تلقائي | كل الأقسام | اسم قسم
EXTERNAL_URL = _env("INPUT_EXTERNAL_URL")               # رابط خبر واحد لتحويله إلى مقال
CUSTOM_FEED = _env("INPUT_CUSTOM_FEED")                 # رابط RSS/صفحة أخبار بديل
SOURCE_FILTER = _env("INPUT_SOURCE_FILTER")             # اسم مصدر محدد من sources.json
WRITING_STYLE = _env("INPUT_STYLE", "افتراضي")          # افتراضي | مختصر | تحليلي | عاجل
DRY_RUN = _env("INPUT_DRY_RUN", "false").lower() == "true"
IGNORE_HISTORY = _env("INPUT_IGNORE_HISTORY", "false").lower() == "true"

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
# الترتيب = الأفضل للعربية أولًا. إن فشل نموذج (حد استخدام/غير موجود/انقطاع) ينتقل تلقائيًا للتالي.
# ملاحظة: qwen/qwen3.6-27b أُوقف في 14/9/2026 وحلّ محله qwen/qwen3.8-27b.
DEFAULT_GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "minimaxai/minimax-m2.7",
    "meta-models/muse-spark-open",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
# لو ضبطت GROQ_MODELS كمتغير بيئة (وكان غير فارغ) يُستعمل بدل القائمة أعلاه
GROQ_MODELS = [
    m.strip() for m in (os.environ.get("GROQ_MODELS") or "").split(",") if m.strip()
] or DEFAULT_GROQ_MODELS
# يسأل Groq عن قائمة النماذج المتاحة فعلًا لحسابك ويضيف أي نموذج دردشة جديد في آخر الطابور
GROQ_AUTO_DISCOVER = (os.environ.get("GROQ_AUTO_DISCOVER") or "true").lower() != "false"
LLM_PASSES = 3             # عدد الدورات الكاملة على كل النماذج قبل الاستسلام
LLM_MAX_WAIT = 75          # أقصى انتظار (ثوانٍ) لانتهاء حد الاستخدام لنموذج واحد
LLM_TOTAL_WAIT = 240       # أقصى انتظار إجمالي لكل طلب
LLM_TIMEOUT = 90           # مهلة الطلب الواحد (ثوانٍ)

# ---------- حدود الجودة ----------
TITLE_MAX = 60
DESCRIPTION_MAX = 150
MIN_WORDS = 120             # أقل طول لمقال المصدر (بالكلمات)؛ الأقصر يُتجاوز
MAX_WORDS = 1200            # أقصى طول لمقال المصدر (بالكلمات)؛ الأطول يُتجاوز
WORD_TOLERANCE = 0          # الفرق المسموح بين عدد كلمات مقالنا ومقال المصدر (0 = مطابقة تامة)
FIT_ROUNDS = 3              # جولات الضبط (الطول + الصياغة + السيو) بعد الكتابة والمراجعة
SUBHEADINGS = 1             # عدد العناوين الفرعية في المقال (والباقي فقرات قصيرة، بلا خاتمة)
PARAGRAPH_WORDS = 55        # متوسط طول الفقرة المستهدف (بالكلمات)
PARAGRAPH_MAX_WORDS = 90    # أقصى طول مسموح لفقرة واحدة
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
