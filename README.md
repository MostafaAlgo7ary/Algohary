# Auto Blogger News — النشر التلقائي لمدونة الجوهري

كل تشغيلة (GitHub Actions) تختار قسمًا بالتناوب → تجلب خبرًا جديدًا من مصادر القسم → تكتب مقالًا عربيًا أصليًا →
مراجعة لغوية بنموذج ثانٍ + فحوصات برمجية → بطاقة صورة بهوية القسم → نشر في بلوجر (مسودة افتراضيًا).

## الإعداد (مرة واحدة)
1. أنشئ مستودع GitHub **عامًا** (لأن الصور تُعرض من raw.githubusercontent) وارفع الملفات.
2. من Groq: انسخ API Key.
3. Blogger API:
   - console.cloud.google.com → مشروع جديد → فعّل **Blogger API v3**.
   - OAuth consent screen (External) وأضف بريدك كـ Test user.
   - Credentials → Create OAuth client ID → **Desktop app** → نزّل `client_secret.json`.
   - على جهازك: `pip install google-auth-oauthlib` ثم `python scripts/get_blogger_token.py client_secret.json`
     وسجّل الدخول بحساب المدونة؛ انسخ الناتج.
4. معرّف المدونة (Blog ID): في لوحة بلوجر، الرابط `blogger.com/blog/posts/XXXXXXXX` الرقم هو الـID.
5. GitHub → Settings → Secrets and variables → Actions → **Secrets**: `GROQ_API_KEY`، `BLOGGER_TOKEN`، `BLOG_ID`.
6. (اختياري) **Variables**: `PUBLISH_AS_DRAFT` = `true` (افتراضي) أو `false`، و `ARTICLES_PER_RUN`.
7. تبويب Actions → Auto Blogger News → Run workflow للتجربة.

## ملاحظات
- التصنيفات في بلوجر يجب أن تطابق أسماء الأقسام في `config.py` حرفيًا.
- ابدأ بـ `PUBLISH_AS_DRAFT=true` وراجع 10 مقالات قبل التحويل للنشر المباشر.
- المصادر في `sources.json` تُستخدم كخيوط أخبار فقط، والمقال يُكتب بصياغة أصلية مع رابط المصدر.
- إن تعذّر جلب مصدر (حجب أو تغيّر شكل الموقع) يُتجاوز تلقائيًا؛ راجع `data/failed.json`.
- أضف أسماء اللاعبين والأندية والشركات في `glossary.json` لتثبيت كتابتها.
