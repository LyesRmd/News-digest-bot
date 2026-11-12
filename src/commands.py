"""أوامر التحكم عبر Telegram (للأدمن فقط). تُطبَّق في الدورة التالية للمشغّل."""
import re
from urllib.parse import urlparse

from . import config, scheduler
from .util import esc, sha

HELP = """<b>أوامر التحكم</b>

/status — حالة النظام والنسب
/pause ، /resume — إيقاف/استئناف النشر
/batches 7 — إجمالي الدفعات يومياً (تشمل الموجز الأخير)
/times 08:00 12:00 18:00 — مواعيد الدفعات العادية
/digest 23:00 — موعد الموجز الأخير
/perbatch 4 — عدد الأخبار في كل دفعة
/ratio — عرض النسب | <code>/ratio 50 30 20</code> | <code>/ratio politics=60 economy=25</code>
/ratio scope daily|batch — نطاق النسبة (يوم كامل أو كل دفعة)
/ratio mode ratio|weight — حصص بالنسبة أو ترتيب بالصدى فقط
/other on|off — السماح بمجالات أخرى
/source list | add &lt;url&gt; [الاسم] | remove &lt;id&gt;
/preview — معاينة الدفعة القادمة دون نشر
/skip — تخطي الدفعة القادمة
/reset — إلغاء كل التعديلات والعودة لملف settings.yaml"""

ALIASES = {
    "politics": "politics", "سياسة": "politics", "سياسه": "politics",
    "economy": "economy", "اقتصاد": "economy", "economics": "economy",
    "technology": "technology", "tech": "technology", "تكنولوجيا": "technology", "تقنية": "technology",
    "other": "other", "أخرى": "other",
}


def set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _valid_hm(s: str) -> bool:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    return bool(m and int(m.group(1)) < 24 and int(m.group(2)) < 60)


def _norm_hm(s: str) -> str:
    h, m = s.split(":")
    return f"{int(h):02d}:{m}"


def _spread(start: str, end: str, n: int) -> list:
    a = int(start[:2]) * 60 + int(start[3:])
    b = int(end[:2]) * 60 + int(end[3:])
    if n == 1:
        pts = [a]
    else:
        pts = [a + (b - a) * i / (n - 1) for i in range(n)]
    out = []
    for p in pts:
        p = int(round(p / 5.0) * 5)
        out.append(f"{p // 60:02d}:{p % 60:02d}")
    return out


def ratio_summary(state: dict, cfg: dict, now: float) -> str:
    from .pipeline import published_today

    rat = config.ratios(cfg)
    today = published_today(state, cfg, now)
    total = len(today)
    cnt = {}
    for p in today:
        cnt[p["category"]] = cnt.get(p["category"], 0) + 1
    lines = ["<b>المحدد:</b> " + " | ".join(f'{config.CATEGORY_LABELS[k][1]} {v:.0f}%' for k, v in rat.items())]
    if total:
        actual = " | ".join(f'{config.CATEGORY_LABELS[k][1]} {cnt.get(k, 0)} ({cnt.get(k, 0) * 100 / total:.0f}%)' for k in rat)
        lines.append(f"<b>المنشور اليوم ({total}):</b> {actual}")
    else:
        lines.append("<b>المنشور اليوم:</b> لا شيء بعد")
    q = cfg["quotas"]
    lines.append(f'النمط: {q["mode"]} | النطاق: {q["scope"]} | مجالات أخرى: {"نعم" if q["allow_other"] else "لا"}')
    return "\n".join(lines)


def status(state: dict, cfg: dict, now: float) -> str:
    sc = cfg["schedule"]
    day = scheduler.local_dt(cfg, now).date()
    done = set(state["done_slots"])
    marks = []
    for s in scheduler.slots_for_day(cfg, day):
        icon = "✅" if s.key in done else "⏳"
        marks.append(f'{icon} {s.dt.strftime("%H:%M")}{" (موجز)" if s.kind == "digest" else ""}')
    paused = "⏸ متوقف" if cfg["channel"]["paused"] else "▶️ يعمل"
    return "\n".join([
        f"<b>الحالة:</b> {paused}",
        f'القناة: {esc(str(cfg["channel"]["id"]))} | المنطقة الزمنية: {sc["timezone"]}',
        "دفعات اليوم: " + "  ".join(marks),
        f'أخبار في الذاكرة: {len(state["items"])} | منشور محفوظ: {len(state["published"])}',
        "", ratio_summary(state, cfg, now),
        "", ("تعديلات فعّالة فوق الملف: نعم (/reset لإلغائها)" if state["overrides"] else "لا تعديلات فوق settings.yaml"),
    ])


def _parse_ratio_args(args: list, cfg: dict):
    base_keys = list(cfg["quotas"]["ratios"].keys())
    vals = {}
    if all("=" in a for a in args):
        for a in args:
            k, v = a.split("=", 1)
            k = ALIASES.get(k.strip().lower())
            if not k:
                return None, "مجال غير معروف. المتاح: politics economy technology"
            vals[k] = float(v)
    else:
        nums = [float(a) for a in args]
        if len(nums) != len(base_keys):
            return None, f"أدخل {len(base_keys)} أرقام بالترتيب: " + " ".join(base_keys)
        vals = dict(zip(base_keys, nums))
    if any(v < 0 for v in vals.values()):
        return None, "النسب لا تكون سالبة"
    return vals, None


def handle(text: str, state: dict, now: float) -> str:
    parts = text.split()
    cmd, args = parts[0].split("@")[0].lower(), parts[1:]
    cfg = config.effective(state)
    ov = state["overrides"]
    try:
        if cmd in ("/start", "/help"):
            return HELP
        if cmd == "/status":
            return status(state, cfg, now)
        if cmd == "/pause":
            set_path(ov, "channel.paused", True)
            return "⏸ تم إيقاف النشر. استخدم /resume للاستئناف."
        if cmd == "/resume":
            set_path(ov, "channel.paused", False)
            return "▶️ استُؤنف النشر."
        if cmd == "/perbatch":
            n = int(args[0])
            if not 1 <= n <= 10:
                return "الرقم بين 1 و 10"
            set_path(ov, "schedule.items_per_batch", n)
            return f"✅ عدد الأخبار في كل دفعة: {n}"
        if cmd == "/batches":
            n = int(args[0])
            if not 2 <= n <= 12:
                return "اكتب رقماً بين 2 و 12 (يشمل الموجز الأخير)"
            sc = cfg["schedule"]
            times = _spread(sc.get("day_start", "08:00"), sc.get("day_end", "21:00"), n - 1)
            set_path(ov, "schedule.batch_times", times)
            return f'✅ {n} دفعات يومياً: {" ".join(times)} + موجز {sc["digest_time"]}'
        if cmd == "/times":
            if not args or not all(_valid_hm(a) for a in args):
                return "الصيغة: /times 08:00 12:30 18:00"
            times = sorted({_norm_hm(a) for a in args})
            set_path(ov, "schedule.batch_times", times)
            return "✅ مواعيد الدفعات: " + " ".join(times)
        if cmd == "/digest":
            if not args or not _valid_hm(args[0]):
                return "الصيغة: /digest 23:00"
            set_path(ov, "schedule.digest_time", _norm_hm(args[0]))
            return f"✅ موعد الموجز: {_norm_hm(args[0])}"
        if cmd == "/other":
            on = args[0].lower() in ("on", "نعم", "1")
            set_path(ov, "quotas.allow_other", on)
            msg = "✅ المجالات الأخرى: " + ("مفعّلة" if on else "معطّلة")
            if on and "other" not in cfg["quotas"]["ratios"]:
                cur = dict(cfg["quotas"]["ratios"])
                cur["other"] = 10
                set_path(ov, "quotas.ratios", cur)
                msg += " (أُضيفت حصة 10 لمجال other؛ عدّلها بـ /ratio other=..)"
            return msg
        if cmd == "/ratio":
            if not args:
                return ratio_summary(state, cfg, now)
            if args[0] == "scope" and len(args) > 1 and args[1] in ("daily", "batch"):
                set_path(ov, "quotas.scope", args[1])
                return f"✅ نطاق النسبة: {args[1]}"
            if args[0] == "mode" and len(args) > 1 and args[1] in ("ratio", "weight"):
                set_path(ov, "quotas.mode", args[1])
                return f"✅ النمط: {args[1]}"
            vals, err = _parse_ratio_args(args, cfg)
            if err:
                return err
            cur = dict(cfg["quotas"]["ratios"])
            cur.update(vals)
            if sum(v for k, v in cur.items() if k != "other" or cfg["quotas"]["allow_other"]) <= 0:
                return "مجموع النسب يجب أن يكون أكبر من صفر"
            set_path(ov, "quotas.ratios", cur)
            return "✅ تم التحديث.\n" + ratio_summary(state, config.effective(state), now)
        if cmd == "/source":
            sub = args[0].lower() if args else "list"
            if sub == "list":
                rows = [f'<code>{esc(s["id"])}</code> — {esc(s["name"])} ({s["lang"]})' for s in config.effective_sources(state)]
                return f"<b>المصادر ({len(rows)})</b>\n" + "\n".join(rows[:60])
            if sub == "add" and len(args) >= 2:
                url = args[1]
                host = urlparse(url).netloc
                if not host:
                    return "رابط غير صالح"
                name = " ".join(args[2:]) or host.replace("www.", "")
                ov.setdefault("sources_add", []).append({
                    "id": "c_" + sha(url)[:6], "name": name, "name_ar": name, "url": url,
                    "lang": "und", "weight": 0.6, "trusted": False})
                return f"✅ أُضيف المصدر: {esc(name)}"
            if sub == "remove" and len(args) >= 2:
                key = args[1].lower()
                before = len(ov.get("sources_add", []))
                ov["sources_add"] = [s for s in ov.get("sources_add", []) if s["id"].lower() != key and s["name"].lower() != key]
                if len(ov["sources_add"]) == before:
                    ov.setdefault("sources_remove", []).append(key)
                return f"✅ حُذف المصدر: {esc(args[1])}"
            return "الصيغة: /source list | add &lt;url&gt; [الاسم] | remove &lt;id&gt;"
        if cmd == "/preview":
            state["preview_request"] = True
            return "👁 سأرسل معاينة الدفعة القادمة إليك في الدورة التالية (دقائق)."
        if cmd == "/skip":
            state["skip_next"] = True
            return "⏭ ستُتخطّى الدفعة القادمة."
        if cmd == "/reset":
            state["overrides"] = {}
            return "♻️ أُلغيت كل التعديلات، وعادت الإعدادات لملف settings.yaml."
    except (IndexError, ValueError):
        return "صيغة غير صحيحة. أرسل /help لعرض الأوامر."
    return "أمر غير معروف. أرسل /help"


def process(state: dict, pub, admin_id: str, now: float) -> int:
    """يقرأ الأوامر الجديدة وينفّذها. يرجع عددها."""
    if not admin_id:
        return 0
    n = 0
    for u in pub.get_updates(state["tg_offset"]):
        state["tg_offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("chat", {}).get("type") != "private":
            continue
        if str(m.get("from", {}).get("id")) != str(admin_id):
            continue
        text = (m.get("text") or "").strip()
        if not text.startswith("/"):
            continue
        pub.send(handle(text, state, now), chat_id=m["chat"]["id"])
        n += 1
    return n
