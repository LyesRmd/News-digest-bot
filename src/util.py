"""دوال مساعدة عامة."""
import hashlib
import html
import logging
import re

log = logging.getLogger("newsbot")

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def norm_digits(s: str) -> str:
    """تحويل الأرقام العربية/الفارسية إلى 0-9."""
    return s.translate(_DIGITS)


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def esc(s: str) -> str:
    """تهريب HTML لرسائل تيليغرام."""
    return html.escape(s or "", quote=False)


def truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"
