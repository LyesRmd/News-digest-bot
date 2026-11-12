"""جمع الأخبار من مصادر RSS."""
import re
import time
from calendar import timegm

import requests

from .util import log, sha, strip_html, truncate

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"}
MAX_PER_FEED = 15


def _entry_ts(e, now: float) -> float:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            try:
                return float(timegm(t))
            except Exception:
                pass
    return now


def collect(state: dict, sources: list, lookback_hours: float = 36, now: float | None = None) -> int:
    import feedparser  # استيراد متأخر

    now = now or time.time()
    added = 0
    for src in sources:
        try:
            r = requests.get(src["url"], headers=HEADERS, timeout=20)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:
            log.warning("تعذّر جلب المصدر %s: %s", src.get("id"), e)
            continue
        for e in feed.entries[:MAX_PER_FEED]:
            title = strip_html(e.get("title", ""))
            link = e.get("link", "")
            if not title:
                continue
            if src.get("gnews"):
                title = re.sub(r"\s+-\s+[^-]{2,40}$", "", title)
            ts = _entry_ts(e, now)
            if now - ts > lookback_hours * 3600:
                continue
            iid = sha(link or title)
            if iid in state["items"]:
                continue
            summary = truncate(strip_html(e.get("summary", "") or e.get("description", "")), 600)
            if src.get("gnews"):
                summary = ""  # ملخص Google News غير مفيد
            state["items"][iid] = {
                "id": iid, "title": title, "summary": summary, "link": link,
                "src": src["id"], "ts": ts,
            }
            added += 1
    state["last_collect"] = now
    log.info("تم جمع %d خبراً جديداً", added)
    return added
