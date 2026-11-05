"""Fetch internet-salience data for the crowd-pressure model.

For every distinct primary toponym and comarca name in
data/forest_regions_attrs.json, sums Wikipedia pageviews (ca + es
projects, last 12 full months) via the public Wikimedia Pageviews REST
API (no key). Result: data/toponym_fame.json, a resumable cache

    { "<name as in attrs>": {"ca": <views>, "es": <views>} }

Names are stored exactly as they appear in attrs; the Wikipedia article
title is derived with smart casing (ICGC all-caps toponyms ->
"Serra de Sant Vicenç" style). Names without an article get 0 — that is
expected for farmhouses and tiny hills; the comarca floor carries the
signal there (see rebuild_zones_from_regions.py, fame term).

Run from the project root (no extra deps):

    uv run python scripts/fetch_fame.py
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATTRS_FILE = ROOT / "data" / "forest_regions_attrs.json"
FAME_FILE = ROOT / "data" / "toponym_fame.json"

UA = "bolets-tracker/1.0 (https://github.com/dariogarcia/bolets-tracker)"
PV_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{article}/monthly/{start}/{end}"
WORKERS = int(os.environ.get("FAME_WORKERS", "4"))
THROTTLE_S = float(os.environ.get("FAME_THROTTLE", "0"))

# Catalan particles that stay lowercase in Wikipedia article titles
LOWER_WORDS = {
    "de", "del", "dels", "d", "da", "les", "la", "el", "els", "l", "lo",
    "i", "a", "al", "als", "s", "sa", "ses", "en", "d'",
}


def smart_title(name: str) -> str:
    """Convert ICGC all-caps toponyms to Wikipedia-style casing."""
    if not name.isupper():
        return name
    out = []
    for w in name.split():
        lw = w.lower()
        if lw.rstrip("'") in LOWER_WORDS:
            out.append(lw)
        else:
            out.append(lw[:1].upper() + lw[1:])
    return " ".join(out)


def month_range() -> tuple[str, str]:
    """Last 12 full months as YYYYMMDD bounds."""
    today = date.today()
    end_y, end_m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    start_y, start_m = (end_y, end_m - 11) if end_m > 11 else (end_y - 1, end_m + 1)
    return f"{start_y:04d}{start_m:02d}01", f"{end_y:04d}{end_m:02d}28"


def fetch_views(article: str, project: str, start: str, end: str) -> int:
    url = PV_URL.format(
        project=project,
        article=urllib.parse.quote(article.replace(" ", "_")),
        start=start,
        end=end,
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
            return sum(item["views"] for item in data.get("items", []))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 0  # no such article
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(3)
    return 0


def main() -> None:
    attrs = json.loads(ATTRS_FILE.read_text())
    names: set[str] = set()
    for a in attrs.values():
        ns = a.get("names") or []
        if ns and ns[0].get("t"):
            names.add(ns[0]["t"])
        if a.get("comarca"):
            names.add(a["comarca"])

    cache = json.loads(FAME_FILE.read_text()) if FAME_FILE.exists() else {}
    todo = [n for n in sorted(names) if n not in cache]
    print(f"{len(names)} distinct names, {len(cache)} cached, {len(todo)} to fetch")

    if not todo:
        print("fame cache already complete")
        return

    start, end = month_range()
    print(f"pageview window: {start} .. {end}")
    lock = threading.Lock()
    done = 0
    errors: list[str] = []

    def work(name: str) -> None:
        nonlocal done
        if THROTTLE_S:
            time.sleep(THROTTLE_S)
        title = smart_title(name)
        entry = {
            "ca": fetch_views(title, "ca.wikipedia.org", start, end),
            "es": fetch_views(title, "es.wikipedia.org", start, end),
        }
        with lock:
            cache[name] = entry
            done += 1
            if done % 100 == 0:
                FAME_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
                print(f"  {done}/{len(todo)} (saved)")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(work, n): n for n in todo}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001 - log and continue
                errors.append(f"{futs[fut]}: {e}")

    FAME_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    print(f"done: {len(cache)} names cached -> {FAME_FILE}")
    if errors:
        print(f"{len(errors)} errors (rerun to retry):")
        for e in errors[:20]:
            print("  " + e)


if __name__ == "__main__":
    main()
