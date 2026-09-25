"""Diagnostika feedu: surové ukážky položiek, početnosť tagov, kategórie, údaje zo stránok."""
from __future__ import annotations

import sys
from collections import Counter

from lxml import etree

from .enrich import fetch_page
from .feed import load_bytes, parse_feed


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    for url in (argv or sys.argv[1:]):
        print(f"\n########## {url}")
        data = load_bytes(url)
        root = etree.fromstring(data, etree.XMLParser(recover=True, huge_tree=True))
        for el in root.iter():
            if isinstance(el.tag, str) and el.tag.startswith("{") and "google" not in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        items = list(root.iter("SHOPITEM"))
        tags = Counter()
        for it in items:
            tags.update({c.tag for c in it if isinstance(c.tag, str)})
        print(f"položiek: {len(items)}")
        print("tagy (v koľkých položkách):", dict(tags.most_common()))
        for it in items[:2]:
            raw = etree.tostring(it, encoding="unicode")
            print("--- ukážka položky:\n" + raw[:1500])
        cats = Counter((it.findtext("CATEGORYTEXT") or "").strip() for it in items)
        print("--- najčastejšie CATEGORYTEXT:")
        for c, n in cats.most_common(8):
            print(f"  {n}× {c}")
        _, products = parse_feed(data)
        for p in products[:2]:
            if p.url.startswith("http"):
                pg = fetch_page(p.url)
                print(f"--- stránka {p.url}\n  ean={pg.ean} brand={pg.brand} desc={pg.description[:150]!r}\n  specs={dict(list(pg.specs.items())[:12])} err={pg.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
