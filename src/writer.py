"""التصنيف + الترجمة وإعادة الصياغة بالعربية عبر النموذج."""
import json

from . import llm, validator
from .config import read_prompt
from .util import log, truncate

CATS = {"politics", "economy", "technology", "other"}


def pick_reports(story: dict, src_meta: dict, k: int = 4) -> list:
    """أفضل k تقارير من مصادر مختلفة (الأعلى جودة ثم الأحدث)."""
    items = sorted(
        story["items"],
        key=lambda i: (src_meta.get(i["src"], {}).get("weight", 0.5), i["ts"]),
        reverse=True,
    )
    seen, out = set(), []
    for it in items:
        if it["src"] in seen:
            continue
        seen.add(it["src"])
        out.append(it)
        if len(out) == k:
            break
    return out


def prepare(story: dict, src_meta: dict) -> None:
    reps = pick_reports(story, src_meta)
    story["reports"] = [
        {
            "source": src_meta.get(i["src"], {}).get("name", i["src"]),
            "lang": src_meta.get(i["src"], {}).get("lang", "und"),
            "title": i["title"],
            "summary": truncate(i.get("summary", ""), 500),
        }
        for i in reps
    ]
    story["source_blob"] = " ".join(f'{r["title"]} {r["summary"]}' for r in story["reports"])
    story["display_sources"] = [
        {"name": src_meta.get(i["src"], {}).get("name_ar") or src_meta.get(i["src"], {}).get("name", i["src"]),
         "link": i.get("link", "")}
        for i in reps[:2]
    ]


def classify(stories: list, src_meta: dict, cfg: dict) -> dict:
    """يرجع {story_id: {category, importance}}."""
    system = read_prompt("classify.txt")
    result = {}
    for i in range(0, len(stories), 25):
        chunk = stories[i : i + 25]
        payload = {"stories": [
            {"id": s["id"], "headlines": [
                f'[{src_meta.get(it["src"], {}).get("name", it["src"])}] {it["title"]}'
                for it in pick_reports(s, src_meta, 4)]}
            for s in chunk]}
        data = llm.call_json(system, json.dumps(payload, ensure_ascii=False), cfg)
        for row in data.get("items", []):
            sid = str(row.get("id"))
            cat = str(row.get("category", "other")).lower().strip()
            try:
                imp = max(0.0, min(10.0, float(row.get("importance", 0))))
            except (TypeError, ValueError):
                imp = 0.0
            result[sid] = {"category": cat if cat in CATS else "other", "importance": imp}
    return result


def rewrite(stories: list, cfg: dict, feedback: dict | None = None) -> dict:
    """يرجع {story_id: {text, headline}}."""
    st = cfg["style"]
    system = (read_prompt("rewrite_ar.txt")
              .replace("{max_chars}", str(st["max_chars"]))
              .replace("{headline_max_chars}", str(st["headline_max_chars"])))
    payload = {"stories": [{"id": s["id"], "category": s.get("category"), "reports": s["reports"]} for s in stories]}
    if feedback:
        payload["feedback"] = feedback
    data = llm.call_json(system, json.dumps(payload, ensure_ascii=False), cfg)
    out = {}
    for row in data.get("items", []):
        out[str(row.get("id"))] = {"text": str(row.get("text", "")).strip(),
                                   "headline": str(row.get("headline", "")).strip()}
    return out


def write_validated(stories: list, cfg: dict) -> dict:
    """صياغة + فحص + إعادة محاولة. الأخبار التي لا تجتاز الفحص تُسقَط."""
    pending = {s["id"]: s for s in stories}
    results, feedback = {}, {}
    for attempt in range(1 + cfg["style"]["max_retries"]):
        if not pending:
            break
        try:
            out = rewrite(list(pending.values()), cfg, feedback or None)
        except llm.LLMError as e:
            log.error("تعذّرت الصياغة: %s", e)
            break
        for sid, s in list(pending.items()):
            o = out.get(sid)
            if not o:
                feedback[sid] = "missing from output"
                continue
            errs = validator.validate(o["text"], o["headline"], s["source_blob"], cfg)
            if errs:
                feedback[sid] = "; ".join(errs)
                log.info("رُفضت الصياغة (%s): %s", sid, feedback[sid])
            else:
                results[sid] = o
                del pending[sid]
    for sid in pending:
        log.warning("أُسقطت القصة %s بعد فشل الفحص: %s", sid, feedback.get(sid))
    return results
