"""حفظ السجل (الروابط المنشورة) ودور الأقسام."""
import json
import os
from datetime import datetime, timezone

import config


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # ملف تالف: لا نوقف المشروع
            print(f"⚠️ تعذّرت قراءة {path}: {e}")
    return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_history_links():
    data = _load(config.HISTORY_FILE, [])
    return {item.get("link") for item in data if isinstance(item, dict)}


def save_history(link, source, section, title):
    data = _load(config.HISTORY_FILE, [])
    data.append({"link": link, "source": source, "section": section,
                 "title": title, "added_at": now()})
    _save(config.HISTORY_FILE, data)


def save_failed(link, source, section, reason):
    data = _load(config.FAILED_FILE, [])
    data.append({"link": link, "source": source, "section": section,
                 "reason": reason, "failed_at": now()})
    # نحتفظ بآخر 300 سجل فقط
    _save(config.FAILED_FILE, data[-300:])


def next_sections(count):
    """يعيد أقسام هذه التشغيلة بالتناوب ويحفظ الدور التالي."""
    total = len(config.SECTIONS)
    state = _load(config.STATE_FILE, {"next_section_index": 0})
    start = int(state.get("next_section_index", 0)) % total
    chosen = [config.SECTIONS[(start + i) % total] for i in range(count)]
    return chosen, (start + count) % total


def commit_section_index(index):
    _save(config.STATE_FILE, {"next_section_index": index, "updated_at": now()})
