"""تجميع الأخبار المتشابهة (ولو بلغات مختلفة) في «قصة» واحدة."""
import numpy as np

from .embed import unpack


def _thr(cfg: dict, kind: str, published: bool = False) -> float:
    d = cfg["dedupe"]
    if published:
        return d["published_similarity_gemini"] if kind == "g" else d["published_similarity_hash"]
    return d["similarity_gemini"] if kind == "g" else d["similarity_hash"]


class _Index:
    """مصفوفة مراكز العناقيد لنوع embeddings واحد."""

    def __init__(self, dim: int):
        self.cap = 256
        self.sums = np.zeros((self.cap, dim), dtype=np.float32)
        self.cents = np.zeros((self.cap, dim), dtype=np.float32)
        self.n = 0

    def best(self, v):
        if self.n == 0:
            return -1, 0.0
        sims = self.cents[: self.n] @ v
        j = int(np.argmax(sims))
        return j, float(sims[j])

    def add_new(self, v) -> int:
        if self.n == self.cap:
            self.cap *= 2
            self.sums = np.vstack([self.sums, np.zeros_like(self.sums)])
            self.cents = np.vstack([self.cents, np.zeros_like(self.cents)])
        self.sums[self.n] = v
        self.cents[self.n] = v
        self.n += 1
        return self.n - 1

    def join(self, j, v):
        self.sums[j] += v
        norm = np.linalg.norm(self.sums[j])
        self.cents[j] = self.sums[j] / norm if norm else self.sums[j]


def build_stories(items: list, cfg: dict) -> list:
    stories_by_kind: dict[str, list] = {}
    index: dict[str, _Index] = {}
    for it in sorted(items, key=lambda x: x["ts"]):
        if "emb" not in it:
            continue
        v = unpack(it["emb"])
        kind = it.get("ek", "h")
        idx = index.setdefault(kind, _Index(v.shape[0]))
        stories = stories_by_kind.setdefault(kind, [])
        j, sim = idx.best(v)
        if j >= 0 and sim >= _thr(cfg, kind):
            stories[j]["items"].append(it)
            idx.join(j, v)
        else:
            idx.add_new(v)
            stories.append({"id": it["id"], "items": [it], "ek": kind})
    out = []
    for kind, stories in stories_by_kind.items():
        idx = index[kind]
        for j, s in enumerate(stories):
            s["centroid"] = idx.cents[j].copy()
            s["src_ids"] = {i["src"] for i in s["items"]}
            s["first_ts"] = min(i["ts"] for i in s["items"])
            s["last_ts"] = max(i["ts"] for i in s["items"])
            out.append(s)
    return out


def drop_published(stories: list, published: list, cfg: dict, now: float) -> list:
    mem = cfg["dedupe"]["published_memory_hours"] * 3600
    pubs = [p for p in published if now - p["ts"] <= mem]
    used_items = {iid for p in pubs for iid in p.get("item_ids", [])}
    used_stories = {p["story_id"] for p in pubs}
    kept = []
    for s in stories:
        if s["id"] in used_stories or any(i["id"] in used_items for i in s["items"]):
            continue
        dup = False
        for p in pubs:
            if p.get("ek") != s["ek"] or not p.get("centroid"):
                continue
            pv = unpack(p["centroid"])
            if pv.shape == s["centroid"].shape:
                n = np.linalg.norm(pv)
                if n and float(s["centroid"] @ (pv / n)) >= _thr(cfg, s["ek"], published=True):
                    dup = True
                    break
        if not dup:
            kept.append(s)
    return kept
