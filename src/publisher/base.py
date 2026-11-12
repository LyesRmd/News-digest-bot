"""واجهة النشر. لإضافة منصة جديدة (X مثلاً) ابنِ صنفاً بنفس الدوال وبدّل get_publisher."""
import os


class Publisher:
    def send(self, text: str, chat_id=None) -> int | None:  # يرجع معرّف الرسالة
        raise NotImplementedError

    def get_updates(self, offset: int) -> list:
        return []


def get_publisher(cfg: dict, dry_run: bool = False) -> Publisher:
    from .telegram import TelegramPublisher

    return TelegramPublisher(
        token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=cfg["channel"]["id"],
        link_preview=cfg["channel"].get("link_preview", False),
        dry_run=dry_run,
    )
