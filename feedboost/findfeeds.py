"""Skúsi nájsť verejný produktový feed (Heureka / Google) na zozname webov.

Použitie: python -m feedboost.findfeeds sample/eshopy.txt
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

PATHS = [
    "/heureka.xml", "/heureka-sk.xml", "/heureka_sk.xml", "/feed/heureka.xml", "/feeds/heureka.xml",
    "/export/heureka.xml", "/xml/heureka.xml", "/heureka/export/products.xml", "/export/heureka_sk.xml",
    "/google.xml", "/feed/google.xml", "/feeds/google.xml", "/export/google.xml", "/xml/google.xml",
    "/products.xml", "/export/products.xml", "/feed.xml", "/zbozi.xml",
]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FeedBoost/0.2 (hladanie feedu)"}


def looks_like_feed(head: bytes) -> str:
    h = head[:4000].decode("utf-8", "ignore")
    if "<SHOPITEM" in h or "<SHOP" in h:
        return "heureka"
    if "base.google.com/ns" in h and ("<item" in h or "<entry" in h):
        return "google"
    return ""


def check(url: str) -> str:
    try:
        with requests.get(url, headers=UA, timeout=15, stream=True, allow_redirects=True) as r:
            if r.status_code != 200:
                return ""
            head = b""
            for chunk in r.iter_content(2048):
                head += chunk
                if len(head) >= 4000:
                    break
            return looks_like_feed(head)
    except requests.RequestException:
        return ""


def main(argv=None) -> int:
    for s in (sys.stdout,):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    src = Path((argv or sys.argv[1:] or ["sample/eshopy.txt"])[0])
    domains = [d.strip() for d in src.read_text("utf-8").splitlines() if d.strip() and not d.startswith("#")]
    out = Path("output"); out.mkdir(exist_ok=True)
    rows = []
    for i, d in enumerate(domains, 1):
        base = d if d.startswith("http") else f"https://{d}"
        found = ""
        for path in PATHS:
            kind = check(urljoin(base, path))
            if kind:
                found = f"{urljoin(base, path)} ({kind})"
                break
            time.sleep(0.3)
        print(f"[{i}/{len(domains)}] {d}: {found or 'nenašiel sa'}", flush=True)
        rows.append([d, found])
    with (out / "najdene_feedy.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["web", "feed"])
        w.writerows(rows)
    print(f"Hotovo: {sum(1 for r in rows if r[1])} z {len(rows)} webov má verejný feed. Výsledok: output/najdene_feedy.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
