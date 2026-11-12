"""توزيع الحصص بين المجالات (طريقة أكبر باقٍ + اختيار بالعجز)."""


def largest_remainder(total: int, ratios: dict) -> dict:
    """يوزّع total على المجالات بحسب النسب، مع ضمان أن المجموع يساوي total تماماً."""
    s = sum(ratios.values()) or 1.0
    exact = {k: total * v / s for k, v in ratios.items()}
    base = {k: int(x) for k, x in exact.items()}
    left = total - sum(base.values())
    order = sorted(exact, key=lambda k: (exact[k] - base[k], ratios[k]), reverse=True)
    for k in order[:left]:
        base[k] += 1
    return base


def select(cands: list, n: int, ratios: dict, already: dict, day_total: int, mode: str = "ratio") -> list:
    """
    يختار حتى n قصة.
    cands: قوائم فيها 'category' و'score'.
    already: ما نُشر فعلاً لكل مجال ضمن نطاق الحساب (يوم أو دفعة).
    day_total: العدد الكلي المتوقع في ذلك النطاق (المنشور + المتبقي).
    """
    pools: dict[str, list] = {}
    for c in sorted(cands, key=lambda x: x["score"], reverse=True):
        if c["category"] in ratios:
            pools.setdefault(c["category"], []).append(c)
    if mode == "weight":
        flat = [c for p in pools.values() for c in p]
        return sorted(flat, key=lambda x: x["score"], reverse=True)[:n]

    target = largest_remainder(max(day_total, 1), ratios)
    counts = {k: already.get(k, 0) for k in ratios}
    chosen = []
    for _ in range(n):
        options = [k for k, p in pools.items() if p]
        if not options:
            break
        best = max(options, key=lambda k: (target[k] - counts[k], pools[k][0]["score"]))
        chosen.append(pools[best].pop(0))
        counts[best] += 1
    return chosen
