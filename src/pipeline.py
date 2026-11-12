"""خط المعالجة: مرشحون → تصنيف → حصص → صياغة → نشر."""
import time

from . import config, dedupe, formatting, quota, scorer, scheduler, writer
from .llm import LLMError
from .util import log


def src_meta(state: dict) -> dict:
    return {s["id"]: s for s in config.effective_sources(state)}


def candidates(state: dict, cfg: dict, meta: dict, now: float) -> list:
    horizon = now - cfg["selection"]["max_age_hours"] * 3600
    items = [i for i in state["items"].values() if i["ts"] >= horizon]
    stories = dedupe.build_stories(items, cfg)
    stories = dedupe.drop_published(stories, state["published"], cfg, now)
    for s in stories:
        scorer.prescore(s, meta, cfg, now)
    stories.sort(key=lambda s: s["prescore"], reverse=True)
    return stories


def _worth_classifying(s: dict, cfg: dict) -> bool:
    sel = cfg["selection"]
    if s["n_sources"] >= sel["require_min_sources"]:
        return True
    return bool(sel["allow_single_trusted"] and s["has_trusted"])


def classify_missing(stories: list, state: dict, cfg: dict, meta: dict, now: float, top_k: int) -> None:
    todo = [s for s in stories[:top_k] if s["id"] not in state["classified"] and _worth_classifying(s, cfg)]
    if todo:
        try:
            res = writer.classify(todo, meta, cfg)
            for sid, r in res.items():
                state["classified"][sid] = {**r, "ts": now}
        except LLMError as e:
            log.error("تعذّر التصنيف: %s", e)
    for s in stories:
        c = state["classified"].get(s["id"])
        if c:
            s["category"], s["importance"] = c["category"], c["importance"]
            s["score"] = scorer.final_score(s, c["importance"], cfg)


def eligible(s: dict, cfg: dict, rat: dict) -> bool:
    sel = cfg["selection"]
    if s.get("category") not in rat or s.get("score", 0) < sel["min_score"]:
        return False
    if s["n_sources"] >= sel["require_min_sources"]:
        return True
    return bool(sel["allow_single_trusted"] and s["has_trusted"]
                and s.get("importance", 0) >= sel["single_trusted_importance"])


def _record(s: dict, out: dict, breaking: bool, now: float, cfg: dict, msg_id) -> dict:
    from .embed import pack

    return {
        "story_id": s["id"], "ts": now, "date": scheduler.local_date(cfg, now),
        "category": s["category"], "text": out["text"], "headline": out["headline"],
        "breaking": breaking, "sources": s["display_sources"], "msg_id": msg_id,
        "item_ids": [i["id"] for i in s["items"]], "ek": s["ek"], "centroid": pack(s["centroid"]),
    }


def publish_chosen(state, cfg, pub, chosen, meta, now, breaking=False, preview_chat=None) -> list:
    for s in chosen:
        writer.prepare(s, meta)
    results = writer.write_validated(chosen, cfg)
    published = []
    for s in chosen:
        out = results.get(s["id"])
        if not out:
            continue
        rec = _record(s, out, breaking, now, cfg, None)
        text = formatting.format_item(rec, cfg)
        if preview_chat:
            pub.send("👁 <b>معاينة (لن تُنشر)</b>\n\n" + text, chat_id=preview_chat)
            continue
        rec["msg_id"] = pub.send(text)
        state["published"].append(rec)
        published.append(rec)
        delay = cfg["style"].get("post_delay_seconds", 0)
        if delay and not getattr(pub, "dry_run", False):
            time.sleep(delay)
    return published


def published_today(state: dict, cfg: dict, now: float) -> list:
    d = scheduler.local_date(cfg, now)
    return [p for p in state["published"] if p["date"] == d]


def run_batch(state, cfg, pub, meta, now, remaining: int, preview_chat=None) -> list:
    rat = config.ratios(cfg)
    stories = candidates(state, cfg, meta, now)
    classify_missing(stories, state, cfg, meta, now, cfg["selection"]["llm_top_k"])
    elig = [s for s in stories if eligible(s, cfg, rat)]
    n = cfg["schedule"]["items_per_batch"]
    q = cfg["quotas"]
    if q["scope"] == "daily":
        already: dict = {}
        for p in published_today(state, cfg, now):
            already[p["category"]] = already.get(p["category"], 0) + 1
        day_total = sum(already.values()) + n * max(remaining, 1)
    else:
        already, day_total = {}, n
    chosen = quota.select(elig, n, rat, already, day_total, q["mode"])
    log.info("المرشحون: %d، المؤهلون: %d، المختارون: %d", len(stories), len(elig), len(chosen))
    if not chosen:
        return []
    return publish_chosen(state, cfg, pub, chosen, meta, now, preview_chat=preview_chat)


def run_breaking(state, cfg, pub, meta, now) -> list:
    b = cfg["breaking"]
    if not b["enabled"]:
        return []
    done = sum(1 for p in published_today(state, cfg, now) if p.get("breaking"))
    if done >= b["max_per_day"]:
        return []
    rat = config.ratios(cfg)
    stories = candidates(state, cfg, meta, now)
    cand = [s for s in stories if s["n_sources"] >= b["min_sources"] and s["recent_sources"] >= b["min_recent_sources"]]
    if not cand:
        return []
    classify_missing(cand, state, cfg, meta, now, 10)
    sel = [s for s in cand if s.get("category") in rat and s.get("importance", 0) >= b["importance_threshold"]]
    sel.sort(key=lambda s: s["score"], reverse=True)
    sel = sel[: b["max_per_day"] - done]
    if not sel:
        return []
    return publish_chosen(state, cfg, pub, sel, meta, now, breaking=True)


def run_digest(state, cfg, pub, now, preview_chat=None):
    recs = sorted(published_today(state, cfg, now), key=lambda p: p["ts"])
    if not recs:
        log.info("لا أخبار منشورة اليوم، لا موجز")
        return None
    text = formatting.format_digest(recs, cfg, list(config.ratios(cfg)), scheduler.local_dt(cfg, now))
    if preview_chat:
        return pub.send("👁 <b>معاينة (لن تُنشر)</b>\n\n" + text, chat_id=preview_chat)
    return pub.send(text)
