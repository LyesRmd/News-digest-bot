"""طبقة موحّدة لمزوّدي النماذج المجانيين مع تبديل تلقائي عند الفشل."""
import json
import os
import re
import time

import requests

from .util import log


class LLMError(RuntimeError):
    pass


def parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except Exception:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a : b + 1])
        raise


def _gemini(p: dict, key: str, system: str, user: str, temp: float) -> str:
    r = requests.post(
        f'https://generativelanguage.googleapis.com/v1beta/models/{p["model"]}:generateContent',
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temp, "responseMimeType": "application/json"},
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _groq(p: dict, key: str, system: str, user: str, temp: float) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": p["model"],
            "temperature": temp,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


_IMPL = {"gemini": _gemini, "groq": _groq}


def call_json(system: str, user: str, cfg: dict):
    """يجرّب المزوّدين بالترتيب. يرجع كائن JSON أو يرفع LLMError."""
    temp = cfg["llm"].get("temperature", 0.3)
    last = None
    for p in cfg["llm"]["providers"]:
        key = os.environ.get(p["key_env"])
        fn = _IMPL.get(p["name"])
        if not key or not fn:
            continue
        for attempt in range(2):
            try:
                return parse_json(fn(p, key, system, user, temp))
            except requests.HTTPError as e:
                last = e
                code = e.response.status_code if e.response is not None else 0
                log.warning("%s فشل (HTTP %s)", p["name"], code)
                if code == 429 or code >= 500:
                    time.sleep(4)
                    continue
                break
            except Exception as e:
                last = e
                log.warning("%s فشل: %s", p["name"], e)
                time.sleep(2)
    raise LLMError(f"فشلت كل مزوّدات النماذج: {last}")
