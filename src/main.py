"""نقطة الدخول: python -m src.main   (تعمل كل ~10 دقائق عبر GitHub Actions)."""
import logging
import os
import time

from . import collector, commands, config, embed, pipeline, scheduler, store
from .publisher.base import get_publisher
from .util import log


def tick(state: dict, pub, now: float, admin_id: str | None) -> None:
    def notify(msg: str) -> None:
        if admin_id:
            try:
                pub.send(msg, chat_id=admin_id)
            except Exception:
                pass

    commands.process(state, pub, admin_id or "", now)
    cfg = config.effective(state)
    pub.chat_id = cfg["channel"]["id"]
    pub.link_preview = cfg["channel"].get("link_preview", False)
    if cfg["channel"]["paused"]:
        log.info("النشر متوقف (paused)")
        return

    meta = pipeline.src_meta(state)
    try:
        if now - state["last_collect"] >= cfg["schedule"]["collect_every_minutes"] * 60:
            collector.collect(state, config.effective_sources(state), cfg["selection"]["max_age_hours"] * 2, now)
        embed.embed_items(state, cfg)
        store.prune(state, cfg, now)
    except Exception as e:
        log.exception("فشل الجمع")
        notify(f"⚠️ فشل جمع الأخبار: {e}")

    try:
        local = scheduler.local_dt(cfg, now)
        log.info("الوقت المحلي (%s): %s", cfg["schedule"]["timezone"], local.strftime("%Y-%m-%d %H:%M"))
        log.info("القصص في الذاكرة: %d خبراً خاماً", len(state["items"]))

        if state["preview_request"]:
            state["preview_request"] = False
            if admin_id:
                pipeline.run_batch(state, cfg, pub, meta, now, remaining=1, preview_chat=admin_id)

        pipeline.run_breaking(state, cfg, pub, meta, now)

        if state["force_batch"]:
            state["force_batch"] = False
            recs = pipeline.run_batch(state, cfg, pub, meta, now, remaining=1)
            notify(f"⚡ دفعة فورية: نُشر {len(recs)} خبراً." + ("" if recs else " (لا قصص مؤهلة الآن، راجع السجل)"))

        slot = scheduler.due(cfg, state, now)
        if slot is None:
            log.info("لا دفعة مستحقة الآن (المواعيد: %s + موجز %s، المهلة %d دقيقة)",
                     " ".join(cfg["schedule"]["batch_times"]), cfg["schedule"]["digest_time"],
                     cfg["schedule"]["grace_minutes"])
        else:
            tries = state["slot_tries"]
            tries[slot.key] = tries.get(slot.key, 0) + 1
            if state["skip_next"]:
                state["skip_next"] = False
                state["done_slots"].append(slot.key)
                notify(f"⏭ تم تخطي دفعة {slot.dt.strftime('%H:%M')}.")
            elif slot.kind == "digest":
                state["done_slots"].append(slot.key)
                pipeline.run_digest(state, cfg, pub, now)
            else:
                rem = scheduler.remaining_batches(cfg, state, slot)
                recs = pipeline.run_batch(state, cfg, pub, meta, now, remaining=rem)
                if recs:
                    state["done_slots"].append(slot.key)
                else:
                    # لا نُغلق الدفعة: نعيد المحاولة في الدورات القادمة خلال المهلة
                    log.info("لم يُنشر شيء في دفعة %s (المحاولة %d)، ستُعاد المحاولة خلال المهلة",
                             slot.key, tries[slot.key])
                    if tries[slot.key] == 1:
                        notify(f"ℹ️ حان موعد دفعة {slot.dt.strftime('%H:%M')} لكن لا قصص مؤهلة بعد. "
                               "سأعيد المحاولة خلال المهلة. راجع سجل GitHub Actions للتفاصيل.")
    except Exception as e:
        log.exception("فشل النشر")
        notify(f"⚠️ خطأ أثناء النشر: {e}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry = os.environ.get("DRY_RUN") == "1"
    state = store.load()
    cfg = config.effective(state)
    pub = get_publisher(cfg, dry_run=dry)
    admin = os.environ.get("TELEGRAM_ADMIN_ID")
    if not dry and not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("TELEGRAM_BOT_TOKEN غير مضبوط")
    try:
        tick(state, pub, time.time(), admin)
    finally:
        store.save(state)


if __name__ == "__main__":
    main()
