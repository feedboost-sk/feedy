"""Hromadný prevod kategórií e-shopu na aktuálny strom Heureky.

Neprekladá produkt po produkte, ale každú UNIKÁTNU kategóriu raz (pri 40 000 produktoch
je ich typicky len pár stoviek). Výsledok:
  <shop>-kategorie.json  – mapa {stará: nová}, vstup pre build_feed --catmap
  <shop>-kategorie.csv   – na kontrolu človekom (počet produktov, ukážky, spôsob priradenia)

Použitie:
  python -m feedboost.catmap https://eshop.sk/heureka.xml --shop eshop            # AI (Ollama/Gemini/…) vyberie z kandidátov
  python -m feedboost.catmap https://eshop.sk/heureka.xml --shop eshop --export   # len podklady na ručné/Claude spracovanie
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .ai import AIClient
from .categories import CategoryTree, assign_category
from .feed import Product, load_bytes, parse_feed


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if p.exists():
        for line in p.read_text("utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    load_env()
    ap = argparse.ArgumentParser(prog="feedboost.catmap")
    ap.add_argument("feed")
    ap.add_argument("--shop", required=True, help="Krátky názov (použije sa v názve súborov)")
    ap.add_argument("--out", default="output")
    ap.add_argument("--export", action="store_true", help="Len uložiť podklady (bez AI)")
    ap.add_argument("--min-count", type=int, default=1, help="Ignorovať kategórie s menej produktmi")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tree = CategoryTree.load(out)
    if not tree:
        print("Strom kategórií Heureky nie je k dispozícii.", file=sys.stderr)
        return 1
    _, products = parse_feed(load_bytes(args.feed))
    counts = Counter(p.category for p in products if p.category)
    samples: dict[str, list[str]] = defaultdict(list)
    for p in products:
        if p.category and len(samples[p.category]) < 5:
            samples[p.category].append(p.name)
    todo = [c for c, n in counts.most_common() if n >= args.min_count and not tree.is_valid(c)]
    print(f"Produktov: {len(products)}, unikátnych kategórií: {len(counts)}, na prevod: {len(todo)}")

    map_path = out / f"{args.shop}-kategorie.json"
    mapping = json.loads(map_path.read_text("utf-8")) if map_path.exists() else {}

    if args.export:
        pod = []
        for c in todo:
            pseudo = Product(id="x", name=" / ".join(samples[c]), category=c)
            pod.append({"stara": c, "pocet": counts[c], "ukazky": samples[c],
                        "kandidati": [k for k, _ in tree.candidates(pseudo, k=10)]})
        p = out / f"{args.shop}-kategorie-podklady.json"
        p.write_text(json.dumps(pod, ensure_ascii=False, indent=1), "utf-8")
        print(f"✓ Podklady: {p}")
        return 0

    ai = AIClient(cache_path=str(out / "ai_cache.json"))
    rows = []
    for i, c in enumerate(todo, 1):
        depth = len([x for x in c.replace(">", "|").split("|") if x.strip() and not x.strip().lower().startswith("heureka.")])
        if c in mapping:
            new, how = mapping[c], "z mapy"
        elif depth <= 2:
            new, how = "", "príliš všeobecná – treba zaradiť po produktoch"
        else:
            pseudo = Product(id="x", name=" / ".join(samples[c][:3]), category=c)
            new, how = assign_category(pseudo, tree, ai if ai.available else None)
            if new:
                mapping[c] = new
            map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), "utf-8")
        rows.append({"stara_kategoria": c, "pocet_produktov": counts[c], "nova_kategoria": new,
                     "sposob": how, "ukazky": " | ".join(samples[c][:3])})
        print(f"[{i}/{len(todo)}] {counts[c]}× {c[:60]} → {new[-60:] if new else '??'} ({how})", flush=True)

    csv_path = out / f"{args.shop}-kategorie.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["stara_kategoria"], delimiter=";")
        w.writeheader()
        w.writerows(rows)
    covered = sum(counts[c] for c in todo if mapping.get(c))
    print(f"✓ Mapa: {map_path}\n✓ Na kontrolu: {csv_path}")
    print(f"Prevedené kategórie pokrývajú {covered} z {sum(counts[c] for c in todo)} produktov s neaktuálnou kategóriou.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
