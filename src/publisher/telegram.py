"""النشر عبر Telegram Bot API."""
import time

import requests

from ..util import log
from .base import Publisher

LIMIT = 4000


def split_message(text: str, limit: int = LIMIT) -> list:
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.rstrip())
    return out


class TelegramPublisher(Publisher):
    def __init__(self, token: str, chat_id, link_preview: bool = False, dry_run: bool = False):
        self.token, self.chat_id = token, chat_id
        self.link_preview, self.dry_run = link_preview, dry_run
        self._fake_id = 0
        self.sent: list = []  # للاختبارات

    def _api(self, method: str, **params):
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=30)
        if r.status_code == 429:
            wait = r.json().get("parameters", {}).get("retry_after", 5)
            time.sleep(min(int(wait) + 1, 60))
            r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=30)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f'Telegram {method}: {data.get("description")}')
        return data["result"]

    def send(self, text: str, chat_id=None) -> int | None:
        target = chat_id or self.chat_id
        first_id = None
        for chunk in split_message(text):
            if self.dry_run:
                self._fake_id += 1
                self.sent.append((target, chunk))
                print(f"\n----- [{target}] -----\n{chunk}\n")
                mid = self._fake_id
            else:
                res = self._api("sendMessage", chat_id=target, text=chunk, parse_mode="HTML",
                                disable_web_page_preview=not self.link_preview)
                mid = res.get("message_id")
            first_id = first_id or mid
        return first_id

    def get_updates(self, offset: int) -> list:
        if self.dry_run or not self.token:
            return []
        try:
            return self._api("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
        except Exception as e:
            log.warning("تعذّر قراءة أوامر Telegram: %s", e)
            return []
