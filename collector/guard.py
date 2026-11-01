"""Bezpiecznik publikacji: nie pozwala nadpisać gałęzi danych wersją, która straciła historię.

    python collector/guard.py OLD_DIR NEW_DIR      # kod 0 = OK, 1 = publikacja zablokowana

OLD_DIR = to, co jest teraz na gałęzi (świeży klon), NEW_DIR = to, co chcemy opublikować.
Reguły:
  - plik JSON z "series" (1h.json, 1d.json, …): musi istnieć i mieć co najmniej
    MIN_KEEP (95%) punktów z obecnej wersji (pojedyncza usunięta seria nie blokuje),
  - pozostałe pliki: liczba plików w każdym katalogu nie może spaść (np. reports/*.json).
Celowe przeliczenie historii (backfill) → zmienna PUBLISH_ALLOW_SHRINK=1.
"""
import json
import os
import sys

MIN_KEEP = 0.95


def _files(root):
    out = {}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for fn in files:
            p = os.path.join(d, fn)
            out[os.path.relpath(p, root)] = p
    return out


def series_points(path):
    """→ total number of points in a {"series": {id: [[t, v], …]}} file, or None if not such a file."""
    if not path.endswith(".json"):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return None
    s = obj.get("series") if isinstance(obj, dict) else None
    if not isinstance(s, dict):
        return None
    return sum(len(v) for v in s.values() if isinstance(v, list))


def check(old_dir, new_dir, min_keep=MIN_KEEP):
    """→ list of problems (empty = OK)."""
    old, new = _files(old_dir), _files(new_dir)
    problems = []
    for rel, p in sorted(old.items()):
        n_old = series_points(p)
        if n_old is None:
            continue
        if rel not in new:
            problems.append(f"{rel}: brak pliku w nowej wersji (było {n_old} punktów)")
            continue
        n_new = series_points(new[rel])
        if n_new is None:
            problems.append(f"{rel}: nowa wersja nie ma serii (było {n_old} punktów)")
        elif n_new < n_old * min_keep:
            problems.append(f"{rel}: {n_new} punktów zamiast {n_old} (−{(1 - n_new / n_old) * 100:.1f}%)")
    # katalogi: liczba plików nie może spaść
    def per_dir(files):
        c = {}
        for rel in files:
            c[os.path.dirname(rel)] = c.get(os.path.dirname(rel), 0) + 1
        return c
    c_old, c_new = per_dir(old), per_dir(new)
    for d, n in sorted(c_old.items()):
        if c_new.get(d, 0) < n:
            problems.append(f"{d or '.'}/: {c_new.get(d, 0)} plików zamiast {n}")
    return problems


def main(argv=None):
    a = argv if argv is not None else sys.argv[1:]
    if len(a) != 2:
        print(__doc__)
        return 2
    problems = check(a[0], a[1])
    if not problems:
        print("Bezpiecznik: OK — nowa wersja nie traci historii")
        return 0
    if os.environ.get("PUBLISH_ALLOW_SHRINK") == "1":
        print("Bezpiecznik: mniej danych, ale PUBLISH_ALLOW_SHRINK=1 (przeliczenie historii):")
        for p in problems:
            print("  - " + p)
        return 0
    print("::error::Bezpiecznik zablokował publikację — nowa wersja straciłaby historię:")
    for p in problems:
        print("  - " + p)
    return 1


if __name__ == "__main__":
    sys.exit(main())
