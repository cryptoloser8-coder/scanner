"""Poprawka 120 — ponawianie wysyłki na Telegram przy chwilowych błędach (502 z 19.11.2026)."""
import os
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import alerts  # noqa: E402


class Resp:
    def __init__(self, code, js=None):
        self.status_code = code
        self._js = js or {}
        self.text = str(self._js)

    def json(self):
        return self._js


class Sess:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def tg(answers):
    t = alerts.Telegram(token="T", chat_id="1", session=Sess(answers))
    t.waits = []
    t.sleep = t.waits.append
    return t


def test_502_then_ok():
    t = tg([Resp(502, {"ok": False, "error_code": 502, "description": "Bad Gateway"}), Resp(200)])
    assert t.post("report", "📄 raport") is True
    assert t.session.calls == 2 and t.waits == [5]


def test_connection_error_then_ok():
    t = tg([requests.ConnectionError("reset"), requests.Timeout("slow"), Resp(200)])
    assert t.send("x") is True
    assert t.waits == [5, 15]


def test_429_uses_retry_after():
    t = tg([Resp(429, {"ok": False, "parameters": {"retry_after": 7}}), Resp(200)])
    assert t.send("x") is True
    assert t.waits == [8]


def test_gives_up_after_all_tries():
    t = tg([Resp(502)] * 4)
    assert t.send("x") is False
    assert t.session.calls == 4 and t.waits == [5, 15, 40]


def test_400_not_retried():
    t = tg([Resp(400, {"ok": False, "description": "Bad Request: can't parse entities"})])
    assert t.send("x") is False
    assert t.session.calls == 1 and t.waits == []


def test_long_text_retries_only_failed_chunk():
    text = "\n".join(["a" * 100] * 60)          # 2 kawałki po ≤ 3900 znaków
    t = tg([Resp(200), Resp(503), Resp(200)])
    assert t.send(text) is True
    assert t.session.calls == 3                  # pierwszy kawałek nie wysłany drugi raz
