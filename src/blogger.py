"""النشر عبر Blogger API."""
import base64
import binascii
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config

SCOPES = ["https://www.googleapis.com/auth/blogger"]


def _load_token_info(raw):
    raw = "".join(raw.strip().strip("\"'").split())   # يشيل المسافات والاقتباسات
    if raw.startswith("{"):             # JSON مباشر بدون base64
        return json.loads(raw)
    if raw.startswith("1//"):           # refresh token لوحده (حوالي 104 حرف)
        cid = os.environ.get("BLOGGER_CLIENT_ID", "").strip()
        secret = os.environ.get("BLOGGER_CLIENT_SECRET", "").strip()
        if not (cid and secret):
            raise RuntimeError(
                "BLOGGER_TOKEN يحتوي refresh token فقط. أضف Secrets باسم "
                "BLOGGER_CLIENT_ID و BLOGGER_CLIENT_SECRET، أو ولّد التوكن الكامل "
                "بـ scripts/get_blogger_token.py.")
        return {"refresh_token": raw, "client_id": cid, "client_secret": secret,
                "token_uri": "https://oauth2.googleapis.com/token"}
    raw += "=" * (-len(raw) % 4)        # تصحيح الـ padding
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            return json.loads(decode(raw).decode("utf-8"))
        except (binascii.Error, ValueError):
            continue
    raise RuntimeError(
        f"قيمة BLOGGER_TOKEN غير صالحة (طولها {len(raw)} حرفًا فقط). "
        "أعد توليدها بـ scripts/get_blogger_token.py وانسخها كاملة في الـ Secret.")


def _service():
    raw = os.environ.get("BLOGGER_TOKEN", "")
    if not raw:
        raise RuntimeError("متغير BLOGGER_TOKEN غير موجود")
    creds = Credentials.from_authorized_user_info(_load_token_info(raw), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds, cache_discovery=False)


def related_posts(label, limit):
    """أحدث مقالات القسم لوضعها كروابط داخلية."""
    try:
        res = _service().posts().list(blogId=config.BLOG_ID, labels=label,
                                      maxResults=limit, fetchBodies=False,
                                      orderBy="published").execute()
        return [(p["title"], p["url"]) for p in res.get("items", [])]
    except Exception as e:
        print(f"⚠️ تعذّر جلب المقالات ذات الصلة: {e}")
        return []


def publish(title, html, labels):
    body = {"kind": "blogger#post", "title": title, "content": html, "labels": labels}
    res = _service().posts().insert(blogId=config.BLOG_ID, body=body,
                                    isDraft=config.PUBLISH_AS_DRAFT).execute()
    return res.get("url") or res.get("id")
