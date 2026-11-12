"""فحص آلي لجودة النص العربي قبل النشر."""
import re

from .util import norm_digits

_NUM = re.compile(r"\d[\d.,٬٫]*")


def numbers(s: str) -> set:
    s = norm_digits(s or "")
    return {re.sub(r"[.,٬٫]", "", m) for m in _NUM.findall(s)}


def arabic_ratio(s: str) -> float:
    letters = re.findall(r"[^\W\d_]", s or "")
    if not letters:
        return 0.0
    ar = re.findall(r"[\u0600-\u06FF]", s)
    return len(ar) / len(letters)


def validate(text: str, headline: str, source_blob: str, cfg: dict) -> list:
    """يرجع قائمة أخطاء (فارغة = سليم). الرسائل بالإنجليزية لأنها تُعاد للنموذج كملاحظات."""
    st = cfg["style"]
    errs = []
    text, headline = (text or "").strip(), (headline or "").strip()
    if not text:
        return ["text is empty"]
    if len(text) > st["max_chars"]:
        errs.append(f'text is {len(text)} chars; maximum is {st["max_chars"]}')
    if not headline:
        errs.append("headline is empty")
    elif len(headline) > st["headline_max_chars"]:
        errs.append(f'headline is {len(headline)} chars; maximum is {st["headline_max_chars"]}')
    if arabic_ratio(text) < 0.6:
        errs.append("text must be written in Arabic")
    if re.search(r"https?://|www\.", text):
        errs.append("text must not contain links")
    extra = numbers(text + " " + headline) - numbers(source_blob)
    if extra:
        errs.append("numbers not found in the reports: " + ", ".join(sorted(extra)))
    low = (text + " " + headline).lower()
    for kw in cfg["safety"].get("blocked_keywords", []):
        if kw and kw.lower() in low:
            errs.append(f"contains blocked keyword: {kw}")
    return errs
