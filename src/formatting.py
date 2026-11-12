"""تنسيق رسائل تيليغرام (HTML)."""
import html
from datetime import datetime

from .config import CATEGORY_LABELS
from .util import esc

MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
          "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def format_item(rec: dict, cfg: dict) -> str:
    emoji, label = CATEGORY_LABELS.get(rec["category"], CATEGORY_LABELS["other"])
    head = f"🔴 <b>عاجل</b> · {label}" if rec.get("breaking") else f"{emoji} <b>{label}</b>"
    parts = [head, "", esc(rec["text"])]
    st = cfg["style"]
    if st.get("include_source") and rec.get("sources"):
        links = []
        for s in rec["sources"]:
            if s.get("link"):
                links.append(f'<a href="{html.escape(s["link"], quote=True)}">{esc(s["name"])}</a>')
            else:
                links.append(esc(s["name"]))
        parts += ["", "المصدر: " + "، ".join(links)]
    if st.get("hashtags"):
        tags = f"#{label}" + (" #عاجل" if rec.get("breaking") else "")
        parts += ["", tags]
    return "\n".join(parts)


def _post_link(channel_id: str, msg_id) -> str | None:
    if msg_id and str(channel_id).startswith("@"):
        return f"https://t.me/{str(channel_id)[1:]}/{msg_id}"
    return None


def format_digest(records: list, cfg: dict, order: list, now_dt: datetime) -> str:
    title = f"📰 <b>موجز اليوم — {now_dt.day} {MONTHS[now_dt.month - 1]} {now_dt.year}</b>"
    lines = [title]
    by_cat: dict[str, list] = {}
    for r in records:
        by_cat.setdefault(r["category"], []).append(r)
    cats = [c for c in order if c in by_cat] + [c for c in by_cat if c not in order]
    for c in cats:
        emoji, label = CATEGORY_LABELS.get(c, CATEGORY_LABELS["other"])
        lines += ["", f"{emoji} <b>{label}</b>"]
        for r in by_cat[c]:
            h = esc(r.get("headline") or r["text"][:90])
            link = _post_link(cfg["channel"]["id"], r.get("msg_id"))
            mark = "🔴 " if r.get("breaking") else ""
            lines.append(f'• {mark}<a href="{link}">{h}</a>' if link else f"• {mark}{h}")
    lines += ["", "#موجز_اليوم"]
    return "\n".join(lines)
