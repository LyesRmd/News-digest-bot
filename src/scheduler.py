"""منطق مواعيد الدفعات."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass
class Slot:
    key: str
    dt: datetime
    kind: str  # batch | digest


def tz(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg["schedule"]["timezone"])


def local_dt(cfg: dict, ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz(cfg))


def local_date(cfg: dict, ts: float) -> str:
    return local_dt(cfg, ts).date().isoformat()


def _hm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def slots_for_day(cfg: dict, day) -> list:
    z = tz(cfg)
    out = [Slot(f"{day} {t}", datetime.combine(day, _hm(t), z), "batch") for t in cfg["schedule"]["batch_times"]]
    d = cfg["schedule"]["digest_time"]
    out.append(Slot(f"{day} {d}", datetime.combine(day, _hm(d), z), "digest"))
    return sorted(out, key=lambda s: s.dt)


def due(cfg: dict, state: dict, ts: float) -> Slot | None:
    now = local_dt(cfg, ts)
    grace = timedelta(minutes=cfg["schedule"]["grace_minutes"])
    done = set(state["done_slots"])
    today = now.date()
    cands = []
    for day in (today - timedelta(days=1), today):
        for s in slots_for_day(cfg, day):
            if s.key not in done and s.dt <= now < s.dt + grace:
                cands.append(s)
    return min(cands, key=lambda s: s.dt) if cands else None


def remaining_batches(cfg: dict, state: dict, slot: Slot) -> int:
    """عدد الدفعات العادية المتبقية في يوم الدفعة الحالية (تشمل الحالية)."""
    done = set(state["done_slots"])
    n = 0
    for s in slots_for_day(cfg, slot.dt.date()):
        if s.kind == "batch" and s.key not in done and s.dt >= slot.dt:
            n += 1
    return max(n, 1)
