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
        if state["preview_request"]:
            state["preview_request"] = False
            if admin_id:
                pipeline.run_batch(state, cfg, pub, meta, now, remaining=1, preview_chat=admin_id)

        pipeline.run_breaking(state, cfg, pub, meta, now)

        slot = scheduler.due(cfg, state, now)
        if slot:
            state["done_slots"].append(slot.key)  # نسجّل أولاً لمنع التكرار عند الفشل الجزئي
            if state["skip_next"]:
                state["skip_next"] = False
                notify(f"⏭ تم تخطي دفعة {slot.dt.strftime('%H:%M')}.")
            elif slot.kind == "digest":
                pipeline.run_digest(state, cfg, pub, now)
            else:
                rem = scheduler.remaining_batches(cfg, {**state, "done_slots": state["done_slots"][:-1]}, slot)
                pipeline.run_batch(state, cfg, pub, meta, now, remaining=rem)
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
