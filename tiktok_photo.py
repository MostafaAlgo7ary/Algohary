"""ينشر مقالات المدونة الجديدة على تيكتوك كبوست صور عن طريق Buffer.
- main.py بيسجل كل مقال اتنشر في ملف مؤقت (TT_QUEUE_FILE)
- الخطوة دي بتعمل صورة طولية 1080x1920 من بطاقة المقال، وترفعها على فرع media (رابط عام)، وتبعتها لـ Buffer
أي فشل بيتطبع بس ومبيوقفش المدونة."""
import array
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import wave

import requests
from PIL import Image, ImageFilter

BUFFER_API = "https://api.buffer.com"
MEDIA_BRANCH = "media"
QUEUE = os.environ.get("TT_QUEUE_FILE") or os.path.join(tempfile.gettempdir(), "tt_queue.json")

# هاشتاجات ثابتة لكل قسم (٥ هاشتاجات حد تيكتوك في Buffer)
TAGS = {
    "رياضة": ["#رياضة", "#كورة", "#الدوري_المصري", "#اخبار_الرياضة", "#مصر"],
    "تقنية": ["#تقنية", "#تكنولوجيا", "#ذكاء_اصطناعي", "#موبايلات", "#مصر"],
    "ألعاب": ["#العاب", "#جيمنج", "#بلايستيشن", "#اخبار_الالعاب", "#مصر"],
    "سفر": ["#سفر", "#سياحة", "#رحلات", "#وجهات_سفر", "#مصر"],
    "فن": ["#فن", "#ثقافة", "#معارض", "#فنون", "#مصر"],
    "طعام": ["#طعام", "#وصفات", "#طبخ", "#اكل_مصري", "#مصر"],
    "اقتصاد": ["#اقتصاد", "#بورصة", "#اسعار", "#اعمال", "#مصر"],
}


def _gql(key, query, variables=None):
    r = requests.post(BUFFER_API, json={"query": query, "variables": variables or {}},
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=60)
    try:
        data = r.json()
    except Exception:
        raise RuntimeError(f"Buffer HTTP {r.status_code}: {r.text[:300]}")
    if data.get("errors"):
        raise RuntimeError(f"Buffer errors: {str(data['errors'])[:400]}")
    return data.get("data") or {}


def find_tiktok_channel(key):
    cid = (os.environ.get("BUFFER_CHANNEL_ID") or "").strip()
    if cid:
        return cid
    orgs = _gql(key, "query { account { organizations { id name } } }")["account"]["organizations"]
    for org in orgs:
        chans = _gql(key, "query($i: ChannelsInput!) { channels(input: $i) { id name service } }",
                     {"i": {"organizationId": org["id"]}})["channels"]
        for c in chans:
            if str(c.get("service", "")).lower() == "tiktok":
                print(f"  قناة تيكتوك في Buffer: {c.get('name')} ({c['id']})")
                return c["id"]
    raise RuntimeError("مفيش قناة تيكتوك مربوطة في Buffer")


def vertical_image(src_path, out_path):
    """بطاقة المقال (أفقية 1200x630) في منتصف خلفية طولية 1080x1920 من نفس الصورة مغبّشة. JPG أقل من 20MB."""
    card = Image.open(src_path).convert("RGB")
    bg = card.resize((1080, 1920)).filter(ImageFilter.GaussianBlur(40))
    w = 1080
    h = int(card.height * w / card.width)
    fg = card.resize((w, h))
    bg.paste(fg, (0, (1920 - h) // 2))
    bg.save(out_path, "JPEG", quality=90)
    return out_path


def host_file(path):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("GH_TOKEN / GITHUB_REPOSITORY مش موجودين")
    name = f"tt_{int(time.time())}_{os.path.basename(path)}"
    tmp = tempfile.mkdtemp()
    try:
        shutil.copy(path, os.path.join(tmp, name))
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")

        def git(*a):
            subprocess.run(["git", *a], cwd=tmp, check=True, env=env, capture_output=True, text=True, timeout=300)

        git("init", "-q")
        git("checkout", "-q", "-b", MEDIA_BRANCH)
        git("config", "user.name", "Auto Blogger Bot")
        git("config", "user.email", "bot@users.noreply.github.com")
        git("add", name)
        git("commit", "-q", "-m", "media for TikTok [skip ci]")
        git("remote", "add", "origin", f"https://x-access-token:{token}@github.com/{repo}.git")
        git("push", "-q", "--force", "origin", MEDIA_BRANCH)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    url = f"https://raw.githubusercontent.com/{repo}/{MEDIA_BRANCH}/{name}"
    for _ in range(18):
        try:
            h = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=20)
            if h.status_code in (200, 206):
                return url
        except Exception:
            pass
        time.sleep(5)
    raise RuntimeError("الرابط العام ماظهرش بعد ٩٠ ثانية")


# ---------- موسيقى مولّدة بالكود (مفيش ملف صوت خارجي، فمفيش حقوق ملكية) ----------
CHORDS = [  # تقدم هادي: Am - F - C - G (ترددات بالهرتز)
    (220.00, 261.63, 329.63),
    (174.61, 220.00, 261.63),
    (261.63, 329.63, 392.00),
    (196.00, 246.94, 293.66),
]


def make_music(path, seed_text, seconds=10, rate=22050):
    """مسار موسيقي بسيط: وسادة هارمونية ناعمة + كيك خفيف + هاي هات. بيتغير شوية حسب العنوان."""
    rnd = random.Random(seed_text)
    bpm = rnd.choice([92, 100, 108, 116])
    shift = rnd.choice([0, 2, 3, 5, 7]) / 12.0
    mul = 2 ** shift
    beat = 60.0 / bpm
    n = int(seconds * rate)
    buf = array.array("h", [0]) * n
    chord_len = seconds / len(CHORDS)
    noise = random.Random(7)
    for i in range(n):
        t = i / rate
        ci = min(int(t / chord_len), len(CHORDS) - 1)
        lt = t - ci * chord_len
        env = min(1.0, lt / 0.4) * min(1.0, (chord_len - lt) / 0.4)
        pad = 0.0
        for f in CHORDS[ci]:
            f *= mul
            pad += math.sin(2 * math.pi * f * t) + 0.35 * math.sin(2 * math.pi * 2 * f * t)
        pad = pad / 3.0 * env * 0.30
        bt = t % beat
        kick = math.sin(2 * math.pi * (50 + 90 * math.exp(-bt * 25)) * bt) * math.exp(-bt * 9) * 0.55
        ht = (t + beat / 2) % beat
        hat = (noise.random() * 2 - 1) * math.exp(-ht * 60) * 0.12
        fade = min(1.0, t / 0.2) * min(1.0, (seconds - t) / 0.8)
        v = (pad + kick + hat) * fade
        buf[i] = int(max(-1.0, min(1.0, v)) * 30000)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(buf.tobytes())
    return path


def ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return True
    try:
        subprocess.run(["sudo", "apt-get", "install", "-y", "--no-install-recommends", "ffmpeg"],
                       check=True, capture_output=True, timeout=300)
    except Exception as e:
        print(f"  تعذّر تثبيت ffmpeg: {str(e)[:120]}")
    return bool(shutil.which("ffmpeg"))


def make_video(image_path, title, out_path, seconds=10):
    """صورة طولية 1080x1920 -> فيديو mp4 فيه تقريب هادي + الموسيقى المولّدة."""
    if not ensure_ffmpeg():
        raise RuntimeError("ffmpeg مش موجود")
    wav = make_music(os.path.join(tempfile.gettempdir(), "tt_music.wav"), title, seconds)
    fps = 25
    frames = seconds * fps
    vf = (f"scale=1620:2880,zoompan=z='min(1+0.0009*on,1.14)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-i", image_path, "-i", wav, "-vf", vf, "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", out_path],
                   check=True, capture_output=True, timeout=300)
    return out_path


CREATE = """
mutation($i: CreatePostInput!) {
  createPost(input: $i) {
    ... on PostActionSuccess { post { id status } }
    ... on MutationError { message }
  }
}
"""


def caption(item):
    tags = TAGS.get(item.get("section"), ["#مصر"])[:5]
    desc = re.sub(r"\s+", " ", item.get("description") or "").strip()
    parts = [item["title"].strip()]
    if desc:
        parts.append(desc)
    parts.append("📖 المقال كامل على مدونة الجوهري، الرابط في البايو")
    parts.append(" ".join(tags))
    return "\n\n".join(parts)[:2000]


def _send(key, channel, item, assets, metadata):
    last = ""
    for mode in ("shareNow", "addToQueue"):
        inp = {"text": caption(item), "channelId": channel, "schedulingType": "automatic",
               "mode": mode, "assets": assets, "metadata": metadata}
        try:
            res = _gql(key, CREATE, {"i": inp})["createPost"]
        except Exception as e:
            last = str(e)
            continue
        if res.get("post"):
            print(f"✅ تيكتوك: Buffer استلم البوست ({mode}) id={res['post']['id']}")
            return True, ""
        last = res.get("message", str(res))
    return False, last


def post_item(key, channel, item):
    img = vertical_image(item["image"], os.path.join(tempfile.gettempdir(), "tt_vertical.jpg"))
    mode = (os.environ.get("TT_MODE") or "video").strip().lower()  # video | photo
    if mode == "video":
        try:
            vid = make_video(img, item["title"], os.path.join(tempfile.gettempdir(), "tt_card.mp4"))
            url = host_file(vid)
            ok, err = _send(key, channel, item, [{"video": {"url": url}}],
                            {"tiktok": {"isAiGenerated": True}})
            if ok:
                return True
            print(f"⚠️ فيديو تيكتوك فشل ({err[:150]})، هجرب بوست صورة")
        except Exception as e:
            print(f"⚠️ تعذّر عمل الفيديو ({str(e)[:150]})، هجرب بوست صورة")
    url = host_file(img)
    ok, err = _send(key, channel, item, [{"image": {"url": url}}],
                    {"tiktok": {"title": item["title"].strip()[:90]}})
    if not ok:
        print(f"❌ تيكتوك فشل: {err}")
    return ok


def main():
    key = (os.environ.get("BUFFER_API_KEY") or "").strip()
    if not key:
        print("⚠️ تيكتوك غير مفعل: مفيش BUFFER_API_KEY")
        return
    if not os.path.exists(QUEUE):
        print("ℹ️ مفيش مقالات جديدة للنشر على تيكتوك")
        return
    try:
        items = json.load(open(QUEUE, encoding="utf-8"))
        channel = find_tiktok_channel(key)
    except Exception as e:
        print(f"❌ تيكتوك فشل: {e}")
        return
    for item in items:
        try:
            post_item(key, channel, item)
        except Exception as e:
            print(f"❌ تيكتوك فشل: {e}")
    os.remove(QUEUE)


if __name__ == "__main__":
    main()
