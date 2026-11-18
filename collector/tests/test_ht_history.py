import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ht_history as H  # noqa: E402

NOW = 1795000000.0     # 2026-11-18


class Resp:
    def __init__(self, obj, code=200):
        self._o, self.status_code, self.text = obj, code, str(obj)

    def json(self):
        return self._o

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(self.status_code)


class Fake:
    """HL: 9 coinów (2 bez OI, 1 z innej giełdy); HT: każda seria = 3 strony po 5 punktów."""
    def __init__(self, pages=3, reject=False):
        self.pages, self.reject, self.ht = pages, reject, []

    def post(self, url, json=None, headers=None, timeout=None):
        names = ["BTC", "ETH", "HYPE", "SOL", "ZEC", "DOGE", "TAO", "TINY", "xyz:IBM"]
        oi = [1e9, 5e8, 4e8, 3e8, 2e8, 3e7, 2e7, 1e5, 9e9]
        return Resp([{"universe": [{"name": n} for n in names]}, [{"markPx": "1", "openInterest": str(v)} for v in oi]])

    def get(self, url, params=None, headers=None, timeout=None):
        self.ht.append((url, dict(params or {})))
        if self.reject:
            return Resp({"message": "Unauthorized"}, 401)
        if url.endswith("/state/summary"):
            return Resp({"countTraders": 10, "countActiveTraders": 5, "segments": [
                {"segmentId": 9, "segment": {"id": 9, "name": "Smart Money", "category": "pnl"}, "positionLongValue": 40,
                 "positionShortValue": 60, "countTraders": 3, "countTradersInPosition": 2, "exposureRatio": 3.7}]})
        page = int((params or {}).get("nextCursor") or 0)
        base = int(NOW) - (page + 1) * 5 * 3600
        items = [{"createdAt": H.datetime.fromtimestamp(base + i * 3600, H.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                  "positionCount": 10, "positionCountLong": 4, "totalPositionValue": 100.0, "totalPositionValueLong": 30.0,
                  "totalUnrealizedPnl": 1, "totalFunding": 2} for i in range(5)]
        return Resp({"metrics": items, "nextCursor": str(page + 1) if page + 1 < self.pages else None})


class TG:
    def __init__(self):
        self.msgs = []

    def post(self, kind, text):
        self.msgs.append((kind, text))


def test_queue_order_budget_and_stages(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "Bearer K")
    s, tg, pubs = Fake(), TG(), []
    out = H.run(session=s, now=NOW, ddir=str(tmp_path), telegram=tg, per_run=500,
                publish_fn=lambda d, st, now: pubs.append(H.build_public(st, d, now)))
    st = H._read(os.path.join(str(tmp_path), "state.json"), {})
    assert st["coins"] == ["BTC", "ETH", "HYPE", "SOL", "DOGE", "TAO", "ZEC"]      # 6 osobnych, potem wg OI; bez TINY i xyz
    q = st["queue"]
    assert [(t["stage"], t["seg"], t["coin"]) for t in q[:4]] == [(1, 9, "BTC"), (1, 14, "BTC"), (1, 9, "ETH"), (1, 14, "ETH")]
    assert q[14]["stage"] == 2 and q[14]["seg"] == 8
    # 1 stan grup + 84 strony (mieści się w dziennym limicie 1 + 92)
    assert len(s.ht) == 85 and st["calls"][H.day_key(NOW)] == 85
    assert s.ht[0][0].endswith("/state/summary")
    # 7 coinów × 4 grupy × 3 strony = 84 → całość w jeden dzień
    assert all(t["done"] and t["pages"] == 3 and t["n"] == 15 for t in q)
    texts = " ".join(m for _, m in tg.msgs)
    assert "etap 1 gotowy" in texts and "etap 2 gotowy" in texts and "Całość pobrana" in texts and "start pobierania" in texts
    series, prog = pubs[-1]
    ser = series["series"]
    assert ser["ht9_BTC_lpct"][0][1] == 30.0 and ser["ht14_BTC_short"][0][1] == 70
    assert "ht9_ALT_long" in ser and "ht9_ZEC_lpct" not in ser                     # alty tylko jako koszyk
    assert prog["complete"] and prog["pct"] == 100.0 and prog["attribution"] == "Powered by HyperTracker"
    assert "postęp 100.0%" in out
    summ = H._read(os.path.join(str(tmp_path), "summary_latest.json"), {})
    assert summ["groups"][0]["lpct"] == 40.0


def test_resume_next_day_and_partial_basket(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "K")
    s = Fake(pages=30)
    H.run(session=s, now=NOW, ddir=str(tmp_path), telegram=TG(), per_run=500, publish_fn=lambda *a: None)
    st = H._read(os.path.join(str(tmp_path), "state.json"), {})
    assert sum(t["pages"] for t in st["queue"]) == H.DAY_BUDGET
    n1 = len(s.ht)
    H.run(session=s, now=NOW + 600, ddir=str(tmp_path), telegram=TG(), per_run=500, publish_fn=lambda *a: None)
    assert len(s.ht) == n1                                                          # ten sam dzień — limit wyczerpany
    H.run(session=s, now=NOW + 86400, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=lambda *a: None)
    st = H._read(os.path.join(str(tmp_path), "state.json"), {})
    assert sum(t["pages"] for t in st["queue"]) == H.DAY_BUDGET + 8                 # stan grup osobno + 8 stron
    prog = H.progress(st, NOW + 86400)
    assert 0 < prog["pct"] < 100 and prog["current"] == {"coin": "ETH", "seg": 14} and prog["eta"] > H.day_key(NOW)
    series, _ = H.build_public(st, str(tmp_path), NOW + 86400)
    ser = series["series"]
    assert "ht9_BTC_lpct" in ser and "ht9_ETH_lpct" in ser and "ht14_ETH_lpct" not in ser   # tylko pełne serie
    assert not any("_ALT_" in k for k in ser)                                       # koszyk dopiero po wszystkich altach


def test_key_rejected_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "ZLYKLUCZ")
    s, tg = Fake(reject=True), TG()
    H.run(session=s, now=NOW, ddir=str(tmp_path), telegram=tg, publish_fn=lambda *a: None)
    assert any("odrzucił klucz" in m for _, m in tg.msgs) and "ZLYKLUCZ" not in str(tg.msgs)
    n = len(s.ht)
    out = H.run(session=s, now=NOW + 300, ddir=str(tmp_path), telegram=tg, publish_fn=lambda *a: None)
    assert len(s.ht) == n and "odrzucony" in out


def test_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERTRACKER_API_KEY", raising=False)
    monkeypatch.setattr(H, "load_env", lambda: None)
    assert "brak klucza" in H.run(session=Fake(), now=NOW, ddir=str(tmp_path))


def test_bucketize():
    raw = {str(H.BUCKET * 10 + 60): [1, 1, 100, 25, 0, 0], str(H.BUCKET * 10 + 3600): [2, 1, 200, 100, 0, 0],
           str(H.BUCKET * 11): [1, 0, 50, 0, 0, 0]}
    assert H.bucketize(raw) == [[H.BUCKET * 10, 50.0, 100, 100, 2, 1], [H.BUCKET * 11, 0.0, 0, 50, 1, 0]]


def test_publish_copies_files_and_calls_script(tmp_path):
    st = {"coins": ["BTC"], "queue": H.make_queue(["BTC"]), "calls": {}}
    calls = []

    def runner(args, env=None, capture_output=None, text=None):
        calls.append((args, env["DATA_BRANCH"], sorted(os.listdir(args[2]))))

        class R:
            returncode = 0
        return R()
    H._write(os.path.join(str(tmp_path), "summary_latest.json"), {"groups": []})
    H.publish(str(tmp_path), st, NOW, remote="https://x@github.com/r.git", runner=runner)
    args, branch, files = calls[0]
    assert args[1].endswith("publish.sh") and branch == "ht"
    assert files == ["ht_groups.json", "ht_progress.json", "ht_summary.json"] and not os.path.exists(args[2])
    assert st["published_at"] == int(NOW)


def test_publishes_pending_after_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "K")
    s, pubs = Fake(pages=30), []
    pf = lambda d, st, now: (pubs.append(now), st.update({"published_at": int(now)}))
    H.run(session=s, now=NOW, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=pf)
    H.run(session=s, now=NOW + 300, ddir=str(tmp_path), telegram=TG(), per_run=500, publish_fn=pf)   # do limitu
    n = len(pubs)
    H.run(session=s, now=NOW + 7 * 3600, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=pf)  # limit, 0 zapytań
    assert len(pubs) == n + 1
    H.run(session=s, now=NOW + 10 * 3600, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=pf)
    assert len(pubs) == n + 1                                                       # nic nowego — bez publikacji


def test_no_tokens_pauses_one_hour(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERTRACKER_API_KEY", "K")

    class NoTok(Fake):
        def __init__(self):
            super().__init__(pages=30)
            self.broke = True

        def get(self, url, params=None, headers=None, timeout=None):
            if self.broke and not url.endswith("/state/summary"):
                self.ht.append((url, dict(params or {})))
                return Resp({"statusCode": 402, "code": "insufficient_tokens"}, 402)
            return super().get(url, params, headers, timeout)
    s = NoTok()
    H.run(session=s, now=NOW, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=lambda *a: None)
    st = H._read(os.path.join(str(tmp_path), "state.json"), {})
    assert st["pause_until"] == int(NOW + 3600) and st["calls"][H.day_key(NOW)] == 1    # tylko stan grup policzony
    n = len(s.ht)
    H.run(session=s, now=NOW + 1800, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=lambda *a: None)
    assert len(s.ht) == n                                                           # przerwa — bez zapytań
    s.broke = False
    H.run(session=s, now=NOW + 3700, ddir=str(tmp_path), telegram=TG(), per_run=8, publish_fn=lambda *a: None)
    st = H._read(os.path.join(str(tmp_path), "state.json"), {})
    assert sum(t["pages"] for t in st["queue"]) == 8
