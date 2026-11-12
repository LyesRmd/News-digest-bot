"""الحالة الدائمة: ملف JSON واحد (يُحفظ في فرع state على GitHub)."""
import json
import os
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("STATE_DIR", "state"))
STATE_FILE = STATE_DIR / "state.json"


def default_state() -> dict:
    return {
        "items": {},          # id -> خبر خام
        "published": [],      # الأخبار المنشورة
        "classified": {},     # story_id -> {category, importance, ts}
        "done_slots": [],     # مفاتيح الدفعات المنفّذة
        "overrides": {},      # تجاوزات الإعدادات من Telegram
        "tg_offset": 0,
        "last_collect": 0,
        "skip_next": False,
        "preview_request": False,
        "force_batch": False,   # يُفعَّل بالأمر /now
        "slot_tries": {},       # عدد محاولات كل دفعة
    }


def load() -> dict:
    st = default_state()
    if STATE_FILE.exists():
        try:
            st.update(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return st


def save(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STATE_FILE)


def prune(state: dict, cfg: dict, now: float | None = None) -> None:
    now = now or time.time()
    keep_items = 48 * 3600
    state["items"] = {k: v for k, v in state["items"].items() if now - v["ts"] <= keep_items}
    mem = max(cfg["dedupe"]["published_memory_hours"], 24) * 3600
    state["published"] = [p for p in state["published"] if now - p["ts"] <= max(mem, 4 * 86400)]
    state["classified"] = {k: v for k, v in state["classified"].items() if now - v["ts"] <= 72 * 3600}
    state["done_slots"] = state["done_slots"][-60:]
    tries = state.get("slot_tries", {})
    state["slot_tries"] = dict(list(tries.items())[-60:])
