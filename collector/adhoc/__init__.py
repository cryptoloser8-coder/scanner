"""Raporty specjalne (kind "adhoc", poprawka 39) — jednorazowe analizy zamawiane, gdy na rynku dzieje się coś
nietypowego (np. BTC blisko zejścia pod EMA200 po pierwszym wybiciu po bessie). Bez harmonogramu: budowane na
polecenie, z ostatnich danych (gałęzie data i ema), zapisywane w historii raportów na zawsze (bez przycinania).

Każdy plik w tym katalogu = jeden raport specjalny (nazwa pliku = nazwa raportu, np. btc_ema200):
  TITLE = "…"                                     — tytuł (bot czyta go bez importu, przez ast)
  build(d, ema, cfg, now) → {"why": str, "summary": str, "blocks": [...]}
      d = report.Data (serie z gałęzi data), ema = ema.json z gałęzi ema (albo None), now = czas budowy.
      "why" — krótki opis sytuacji: dlaczego raport powstał (pierwszy blok raportu).
Bloki jak w report.py; dodatkowo wykres z osią dni: {"type": "chart", "x": "days", "series": [{"data": [[dzień, v]]}]}.

Uruchamianie: Telegram /raport_specjalny NAZWA (admin; bez nazwy = lista), GitHub Actions → Raport → pole
„special”, lokalnie: python collector/report.py make --kind adhoc:NAZWA.
"""
import ast
import importlib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def catalog():
    """{nazwa: tytuł} raportów specjalnych w tym katalogu — bez importu modułów (wystarczy plik)."""
    out = {}
    for f in sorted(os.listdir(HERE)):
        name, ext = os.path.splitext(f)
        if ext != ".py" or not NAME_RE.match(name):
            continue
        try:
            with open(os.path.join(HERE, f), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
        except (OSError, SyntaxError, ValueError):
            continue
        title = name
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TITLE" for t in node.targets)
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                title = node.value.value
        out[name] = title
    return out


def build(name, d, ema, cfg, now):
    """Zbuduj raport specjalny `name` → słownik raportu (jak report.build)."""
    import report as R
    if not NAME_RE.match(name or "") or name not in catalog():
        raise ValueError(f"nieznany raport specjalny: {name}")
    mod = importlib.import_module(f"adhoc.{name}")
    res = mod.build(d, ema, cfg or {}, int(now))
    blocks = [{"type": "text", "title": "Dlaczego ten raport", "text": res["why"]}] + list(res.get("blocks") or [])
    ema_upd = (ema or {}).get("updated") or None
    return {"id": R.utc(now, "%Y%m%d-%H%M") + "-adhoc-" + name, "kind": "adhoc", "topic": name, "layout": 2,
            "title": "Raport specjalny: " + getattr(mod, "TITLE", name), "created": int(now),
            "summary": res.get("summary") or "", "sources": {"data_updated": d.updated or None, "ema_updated": ema_upd},
            "blocks": blocks}
