"""تحميل الإعدادات: settings.yaml + تجاوزات Telegram (overrides) المخزّنة في الحالة."""
import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CATEGORY_LABELS = {
    "politics": ("🏛", "سياسة"),
    "economy": ("💼", "اقتصاد"),
    "technology": ("💻", "تكنولوجيا"),
    "other": ("📌", "أخرى"),
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_base() -> dict:
    with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> list:
    with open(ROOT / "config" / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def effective(state: dict) -> dict:
    """الإعدادات الفعلية = الأساس + التجاوزات."""
    return deep_merge(load_base(), state.get("overrides", {}))


def effective_sources(state: dict) -> list:
    ov = state.get("overrides", {})
    removed = {x.lower() for x in ov.get("sources_remove", [])}
    srcs = [s for s in load_sources() if s["id"].lower() not in removed and s["name"].lower() not in removed]
    for s in ov.get("sources_add", []):
        srcs.append(s)
    return srcs


def ratios(cfg: dict) -> dict:
    """نسب المجالات المفعّلة، مُطبَّعة إلى مجموع 100."""
    r = {k: float(v) for k, v in cfg["quotas"]["ratios"].items() if float(v) > 0}
    if not cfg["quotas"].get("allow_other", False):
        r.pop("other", None)
    total = sum(r.values()) or 1.0
    return {k: v * 100.0 / total for k, v in r.items()}


def read_prompt(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")
