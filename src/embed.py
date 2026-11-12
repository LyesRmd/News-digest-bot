"""توليد embeddings: Gemini (يدعم لغات متعددة) مع بديل محلي بسيط عند الفشل."""
import base64
import hashlib
import os
import re

import numpy as np
import requests

from .util import log


def pack(v) -> str:
    return base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode("ascii")


def unpack(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def hash_embed(text: str, dim: int = 256) -> np.ndarray:
    """بديل: حقيبة كلمات مُجزّأة (يعمل داخل اللغة الواحدة فقط)."""
    v = np.zeros(dim, dtype=np.float32)
    for tok in re.findall(r"\w+", text.lower()):
        if len(tok) < 3:
            continue
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
        v[h % dim] += 1.0 if (h >> 20) & 1 else -1.0
        v[(h >> 8) % dim] += 0.5
    return _normalize(v)


def gemini_embed(texts: list[str], cfg: dict) -> list[np.ndarray]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY غير موجود")
    model = cfg["embeddings"]["model"]
    dim = cfg["embeddings"]["dim"]
    out: list[np.ndarray] = []
    for i in range(0, len(texts), 50):
        chunk = texts[i : i + 50]
        body = {
            "requests": [
                {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": t[:1500]}]},
                    "taskType": "SEMANTIC_SIMILARITY",
                    "outputDimensionality": dim,
                }
                for t in chunk
            ]
        }
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        out.extend(_normalize(np.asarray(e["values"], dtype=np.float32)) for e in r.json()["embeddings"])
    return out


def embed_items(state: dict, cfg: dict) -> int:
    """يضيف embedding لكل خبر ناقص. يرجع عدد ما جرى تضمينه."""
    todo = [it for it in state["items"].values() if "emb" not in it]
    if not todo:
        return 0
    texts = [f'{it["title"]}. {it.get("summary", "")[:300]}' for it in todo]
    vecs, kind = None, "h"
    if cfg["embeddings"].get("provider") == "gemini":
        try:
            vecs, kind = gemini_embed(texts, cfg), "g"
        except Exception as e:
            log.warning("فشل embeddings عبر Gemini، سأستخدم البديل المحلي: %s", e)
    if vecs is None:
        vecs = [hash_embed(t, cfg["embeddings"]["dim"]) for t in texts]
    for it, v in zip(todo, vecs):
        it["emb"], it["ek"] = pack(v), kind
    return len(todo)
