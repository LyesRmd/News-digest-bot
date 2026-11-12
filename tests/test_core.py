"""اختبارات المنطق الأساسي (بلا شبكة). التشغيل: python -m unittest discover -s tests -v"""
import copy
import os
import tempfile
import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ["STATE_DIR"] = tempfile.mkdtemp()

from src import commands, config, embed, llm, pipeline, quota, scheduler, store, validator  # noqa: E402
from src.publisher.telegram import TelegramPublisher, split_message  # noqa: E402


def base_cfg():
    return config.load_base()


class QuotaTests(unittest.TestCase):
    def test_largest_remainder_sums_to_total(self):
        r = {"politics": 50, "economy": 30, "technology": 20}
        self.assertEqual(quota.largest_remainder(21, r), {"politics": 11, "economy": 6, "technology": 4})
        for total in range(1, 60):
            self.assertEqual(sum(quota.largest_remainder(total, r).values()), total)

    def test_select_interleaves_categories(self):
        r = {"politics": 50, "economy": 30, "technology": 20}
        cands = ([{"id": f"p{i}", "category": "politics", "score": 9 - i * 0.1} for i in range(10)]
                 + [{"id": f"e{i}", "category": "economy", "score": 7 - i * 0.1} for i in range(10)]
                 + [{"id": f"t{i}", "category": "technology", "score": 6 - i * 0.1} for i in range(10)])
        got = quota.select(cands, 10, r, {}, 10)
        cats = [c["category"] for c in got]
        self.assertEqual((cats.count("politics"), cats.count("economy"), cats.count("technology")), (5, 3, 2))

    def test_select_respects_already_published(self):
        r = {"politics": 50, "economy": 30, "technology": 20}
        cands = [{"id": "p", "category": "politics", "score": 9}, {"id": "t", "category": "technology", "score": 5}]
        got = quota.select(cands, 1, r, {"politics": 10}, 20)
        self.assertEqual(got[0]["category"], "technology")

    def test_missing_category_does_not_force_weak(self):
        r = {"politics": 50, "economy": 30, "technology": 20}
        cands = [{"id": "p1", "category": "politics", "score": 9}, {"id": "p2", "category": "politics", "score": 8}]
        got = quota.select(cands, 3, r, {}, 3)
        self.assertEqual(len(got), 2)  # لا نملأ بما ليس موجوداً

    def test_other_ignored(self):
        r = {"politics": 100}
        got = quota.select([{"id": "x", "category": "other", "score": 10}], 1, r, {}, 1)
        self.assertEqual(got, [])

    def test_weight_mode(self):
        r = {"politics": 50, "economy": 50}
        cands = [{"id": "a", "category": "politics", "score": 5}, {"id": "b", "category": "economy", "score": 9}]
        self.assertEqual(quota.select(cands, 1, r, {}, 1, mode="weight")[0]["id"], "b")


class ValidatorTests(unittest.TestCase):
    cfg = base_cfg()

    def test_ok(self):
        src = "Oil prices rose 3.5% to $82 a barrel on Tuesday"
        self.assertEqual(validator.validate("ارتفعت أسعار النفط 3.5% لتبلغ 82 دولاراً للبرميل.", "النفط يرتفع", src, self.cfg), [])

    def test_arabic_indic_digits_match(self):
        self.assertEqual(validator.numbers("٣٫٥ و 82"), {"35", "82"})

    def test_invented_number_rejected(self):
        errs = validator.validate("ارتفعت الأسعار 7%.", "عنوان", "prices rose 3%", self.cfg)
        self.assertTrue(any("numbers" in e for e in errs))

    def test_length_and_language(self):
        errs = validator.validate("a" * 700, "h", "", self.cfg)
        self.assertTrue(any("maximum" in e for e in errs))
        self.assertTrue(any("Arabic" in e for e in errs))

    def test_blocked(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["safety"]["blocked_keywords"] = ["محظور"]
        errs = validator.validate("خبر محظور هنا", "عنوان", "", cfg)
        self.assertTrue(any("blocked" in e for e in errs))


class SchedulerTests(unittest.TestCase):
    cfg = base_cfg()
    tz = ZoneInfo("Africa/Algiers")

    def ts(self, y, m, d, h, mi):
        return datetime(y, m, d, h, mi, tzinfo=self.tz).timestamp()

    def test_due_and_done(self):
        st = store.default_state()
        s = scheduler.due(self.cfg, st, self.ts(2026, 11, 12, 8, 7))
        self.assertEqual((s.key, s.kind), ("2026-11-12 08:00", "batch"))
        st["done_slots"].append(s.key)
        self.assertIsNone(scheduler.due(self.cfg, st, self.ts(2026, 11, 12, 8, 17)))

    def test_grace_expires(self):
        st = store.default_state()
        self.assertIsNone(scheduler.due(self.cfg, st, self.ts(2026, 11, 12, 9, 45)))

    def test_digest_after_midnight_grace(self):
        st = store.default_state()
        s = scheduler.due(self.cfg, st, self.ts(2026, 11, 13, 0, 10))
        self.assertEqual((s.key, s.kind), ("2026-11-12 23:00", "digest"))

    def test_remaining(self):
        st = store.default_state()
        s = scheduler.due(self.cfg, st, self.ts(2026, 11, 12, 8, 3))
        self.assertEqual(scheduler.remaining_batches(self.cfg, st, s), 6)
        st["done_slots"] = ["2026-11-12 08:00", "2026-11-12 10:30"]
        s2 = scheduler.due(self.cfg, st, self.ts(2026, 11, 12, 13, 5))
        self.assertEqual(scheduler.remaining_batches(self.cfg, st, s2), 4)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.st = store.default_state()
        self.now = time.time()

    def test_ratio_and_normalize(self):
        commands.handle("/ratio 5 3 2", self.st, self.now)
        r = config.ratios(config.effective(self.st))
        self.assertAlmostEqual(r["politics"], 50)
        commands.handle("/ratio politics=60 economy=20 technology=20", self.st, self.now)
        self.assertAlmostEqual(config.ratios(config.effective(self.st))["politics"], 60)
        commands.handle("/ratio اقتصاد=100", self.st, self.now)
        self.assertGreater(config.ratios(config.effective(self.st))["economy"], 50)

    def test_batches_and_times(self):
        commands.handle("/batches 5", self.st, self.now)
        cfg = config.effective(self.st)
        self.assertEqual(len(cfg["schedule"]["batch_times"]), 4)
        commands.handle("/times 9:00 12:30", self.st, self.now)
        self.assertEqual(config.effective(self.st)["schedule"]["batch_times"], ["09:00", "12:30"])
        self.assertIn("الصيغة", commands.handle("/times abc", self.st, self.now))

    def test_pause_reset(self):
        commands.handle("/pause", self.st, self.now)
        self.assertTrue(config.effective(self.st)["channel"]["paused"])
        commands.handle("/reset", self.st, self.now)
        self.assertFalse(config.effective(self.st)["channel"]["paused"])

    def test_sources(self):
        commands.handle("/source add https://example.com/feed.xml Example", self.st, self.now)
        ids = [s["id"] for s in config.effective_sources(self.st)]
        self.assertTrue(any(i.startswith("c_") for i in ids))
        commands.handle("/source remove bbc_world", self.st, self.now)
        self.assertNotIn("bbc_world", [s["id"] for s in config.effective_sources(self.st)])

    def test_bad_input(self):
        self.assertIn("غير صحيحة", commands.handle("/perbatch", self.st, self.now))
        self.assertIn("غير معروف", commands.handle("/zzz", self.st, self.now))

    def test_only_admin(self):
        class P:
            sent = []
            def get_updates(self, off):
                return [{"update_id": 5, "message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 999}, "text": "/pause"}},
                        {"update_id": 6, "message": {"chat": {"id": 7, "type": "private"}, "from": {"id": 7}, "text": "/pause"}}]
            def send(self, t, chat_id=None):
                self.sent.append(chat_id)
        p = P()
        n = commands.process(self.st, p, "7", self.now)
        self.assertEqual(n, 1)
        self.assertEqual(self.st["tg_offset"], 7)


class MiscTests(unittest.TestCase):
    def test_split_message(self):
        text = "\n".join(["س" * 100] * 100)
        chunks = split_message(text, 4000)
        self.assertTrue(all(len(c) <= 4000 for c in chunks))
        self.assertEqual("\n".join(chunks).count("س"), 10000)

    def test_parse_json_fences(self):
        self.assertEqual(llm.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm.parse_json('blah {"a": 2} tail'), {"a": 2})


# ---------- اختبار تكاملي بنموذج وهمي ----------
class FakeLLM:
    """يحاكي النموذج: يصنّف حسب كلمات مفتاحية ويرجع صياغة عربية."""
    def __init__(self):
        self.calls = 0

    def __call__(self, system, user, cfg):
        import json
        self.calls += 1
        data = json.loads(user)
        if "classify" in system.lower() or "news desk editor" in system:
            items = []
            for s in data["stories"]:
                h = " ".join(s["headlines"]).lower()
                cat = ("economy" if any(w in h for w in ("oil", "market", "inflation")) else
                       "technology" if any(w in h for w in ("ai ", "chip", "software")) else
                       "politics" if any(w in h for w in ("president", "ceasefire", "summit")) else "other")
                items.append({"id": s["id"], "category": cat, "importance": 7})
            return {"items": items}
        fb = data.get("feedback", {})
        out = []
        for s in data["stories"]:
            if s["id"] in fb or self.calls > 100:
                text = "خبر مصحّح بعد الملاحظات."
            else:
                text = "تفاصيل الخبر بصياغة عربية جديدة وواضحة."
            out.append({"id": s["id"], "text": text, "headline": "عنوان الخبر"})
        return {"items": out}


class IntegrationTests(unittest.TestCase):
    def make_state(self, now):
        st = store.default_state()
        cfg = config.effective(st)
        meta_ids = [s["id"] for s in config.load_sources()]
        topics = {
            "politics": ["President signs ceasefire deal after summit", "Leaders hold summit as ceasefire is agreed"],
            "economy": ["Oil prices jump as markets react to supply cut", "Markets rally while oil prices climb"],
            "technology": ["New AI chip unveiled by major firm", "Firm reveals AI chip for software developers"],
        }
        n = 0
        for cat, titles in topics.items():
            for k in range(4):  # 4 مصادر لكل موضوع
                title = titles[k % 2] + f" ({cat})"
                iid = f"{cat}{k}"
                st["items"][iid] = {"id": iid, "title": title, "summary": "", "link": f"https://x/{iid}",
                                    "src": meta_ids[n % len(meta_ids)], "ts": now - 600 * (k + 1)}
                n += 1
        embed.embed_items(st, {**cfg, "embeddings": {**cfg["embeddings"], "provider": "none"}})
        return st, cfg

    def test_batch_publishes_with_quota(self):
        now = time.time()
        st, cfg = self.make_state(now)
        cfg["style"]["post_delay_seconds"] = 0
        cfg["schedule"]["items_per_batch"] = 3
        pub = TelegramPublisher("t", "@chan", dry_run=True)
        fake = FakeLLM()
        real = llm.call_json
        llm.call_json = fake
        try:
            meta = pipeline.src_meta(st)
            recs = pipeline.run_batch(st, cfg, pub, meta, now, remaining=1)
        finally:
            llm.call_json = real
        self.assertTrue(1 <= len(recs) <= 3, len(recs))
        self.assertTrue(all(r["category"] in ("politics", "economy", "technology") for r in recs))
        self.assertEqual(len(st["published"]), len(recs))
        # تشغيل ثانٍ لا يكرر الأخبار نفسها
        llm.call_json = fake
        try:
            recs2 = pipeline.run_batch(st, cfg, pub, meta, now, remaining=1)
        finally:
            llm.call_json = real
        first = {r["story_id"] for r in recs}
        self.assertFalse(first & {r["story_id"] for r in recs2})
        # الموجز
        pipeline.run_digest(st, cfg, pub, now)
        self.assertIn("موجز اليوم", pub.sent[-1][1])


if __name__ == "__main__":
    unittest.main()
