"""حساب «الصدى»: مزيج من عدد المصادر وجودتها وسرعة الانتشار وتقدير النموذج."""


def prescore(story: dict, src_meta: dict, cfg: dict, now: float) -> None:
    sc, sel = cfg["scoring"], cfg["selection"]
    n = len(story["src_ids"])
    c_count = min(n / sc["saturate_sources"], 1.0)
    q = sorted((src_meta.get(s, {}).get("weight", 0.5) for s in story["src_ids"]), reverse=True)[:3]
    c_quality = sum(q) / len(q) if q else 0.0
    vel_cut = now - sc["velocity_hours"] * 3600
    recent = {i["src"] for i in story["items"] if i["ts"] >= vel_cut}
    c_vel = min(len(recent) / sc["saturate_velocity"], 1.0)
    br_cut = now - cfg["breaking"]["recent_hours"] * 3600
    story["recent_sources"] = len({i["src"] for i in story["items"] if i["ts"] >= br_cut})
    age_h = max(0.0, (now - story["last_ts"]) / 3600)
    story["fresh"] = max(0.4, 1 - 0.6 * age_h / sel["max_age_hours"])
    story["n_sources"] = n
    story["has_trusted"] = any(src_meta.get(s, {}).get("trusted") for s in story["src_ids"])
    story["c"] = (c_count, c_quality, c_vel)
    w = sc["weights"]
    wsum = w["source_count"] + w["source_quality"] + w["velocity"]
    base = (w["source_count"] * c_count + w["source_quality"] * c_quality + w["velocity"] * c_vel) / wsum
    story["prescore"] = 10 * base * story["fresh"]


def final_score(story: dict, importance: float, cfg: dict) -> float:
    w = cfg["scoring"]["weights"]
    c_count, c_quality, c_vel = story["c"]
    wsum = sum(w.values())
    s = (w["source_count"] * c_count + w["source_quality"] * c_quality
         + w["velocity"] * c_vel + w["llm_importance"] * importance / 10.0) / wsum
    return 10 * s * story["fresh"]
