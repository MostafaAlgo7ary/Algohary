"""النشر عبر Blogger API."""
import base64
import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

import config

SCOPES = ["https://www.googleapis.com/auth/blogger"]


def _service():
    raw = os.environ.get("BLOGGER_TOKEN", "")
    if not raw:
        raise RuntimeError("متغير BLOGGER_TOKEN غير موجود")
    info = json.loads(base64.b64decode(raw).decode("utf-8"))
    creds = Credentials.from_authorized_user_info(info, SCOPES)
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
