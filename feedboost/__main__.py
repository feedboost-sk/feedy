"""FeedBoost – audit a AI vylepšenie produktového feedu e-shopu.

Použitie:
  python -m feedboost https://www.eshop.sk/heureka.xml --shop "Eshop.sk"
  python -m feedboost sample/sample_heureka.xml --shop "Demo shop" --n 5 --lang cs
  python -m feedboost feed.xml --audit-only
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from .ai import AIClient
from .audit import audit_feed, pick_showcase
from .categories import CategoryTree, assign_category
from .enrich import enrich_all
from .feed import load_bytes, parse_feed
from .report import build_html, write_csv


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "eshop"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="feedboost", description="Audit a AI vylepšenie produktového feedu")
    ap.add_argument("feed", help="URL alebo cesta k Heureka / Google XML feedu")
    ap.add_argument("--shop", help="Názov e-shopu do reportu (predvolene doména)")
    ap.add_argument("--n", type=int, default=10, help="Koľko produktov vylepšiť do ukážky (predvolene 10)")
    ap.add_argument("--lang", default="sk", help="Jazyk výstupu: sk, cs, hu, pl, ro, de (predvolene sk)")
    ap.add_argument("--out", default="output", help="Priečinok pre výstupy")
    ap.add_argument("--contact", default=os.getenv("FEEDBOOST_CONTACT", ""), help="Tvoj kontakt do päty reportu")
    ap.add_argument("--audit-only", action="store_true", help="Iba audit bez AI (nepotrebuje API kľúč)")
    ap.add_argument("--provider", help="openai alebo anthropic (predvolene podľa kľúča v .env)")
    ap.add_argument("--model", help="Názov AI modelu (predvolene z .env AI_MODEL)")
    ap.add_argument("--no-enrich", action="store_true", help="Nečítať údaje zo stránok produktov")
    ap.add_argument("--no-categories", action="store_true", help="Nepriraďovať kategórie Heureky")
    ap.add_argument("--ids", help="Čiarkou oddelené ITEM_ID produktov do ukážky (namiesto automatického výberu)")
    ap.add_argument("--export", action="store_true",
                    help="Uložiť podklady ukážkových produktov do JSON (na ručné/externé AI spracovanie) a AI nespúšťať")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # Windows konzola
        except Exception:  # noqa: BLE001
            pass
    load_env()
    args = ap.parse_args(argv)
    if not args.contact:
        args.contact = os.getenv("FEEDBOOST_CONTACT", "")

    shop = args.shop or (urlparse(args.feed).netloc.replace("www.", "") if args.feed.startswith("http") else Path(args.feed).stem)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"→ Načítavam feed: {args.feed}")
    fmt, products = parse_feed(load_bytes(args.feed))
    print(f"  formát: {fmt}, produktov: {len(products)}")
    if not products:
        print("Vo feede sa nenašli žiadne produkty.", file=sys.stderr)
        return 1

    tree = None
    if not args.no_categories:
        tree = CategoryTree.load(out.parent if out.name != "output" else out)
        if tree:
            print(f"→ Strom kategórií Heureky načítaný (počet kategórií: {len(tree.leaves)})")
    audit = audit_feed(products, tree.is_valid if tree else None)
    print(f"→ Audit hotový. Skóre feedu: {audit['score']}/100")
    for it in audit["summary"][:8]:
        print(f"  - {it['issue'].label}: {it['count']} ({it['pct']} %)")

    if args.ids:
        wanted = [x.strip() for x in args.ids.split(",") if x.strip()]
        by_id = {p.id: p for p in products}
        showcase = [by_id[i] for i in wanted if i in by_id]
        missing = [i for i in wanted if i not in by_id]
        if missing:
            print(f"! Tieto ID vo feede nie sú: {', '.join(missing)}")
    else:
        showcase = pick_showcase(products, audit, args.n)
    enriched = {p.id: p for p in showcase}
    notes: dict[str, list[str]] = {p.id: [] for p in showcase}
    if not args.no_enrich and not args.audit_only and any(p.url.startswith("http") and ".example/" not in p.url for p in showcase):
        print(f"→ Čítam stránky produktov z ukážky ({len(showcase)}) – hľadám údaje, ktoré vo feede chýbajú")
        enriched, notes = enrich_all(showcase)

    if args.export:
        import json
        pod = [{"id": p.id, "url": p.url, "duplicitne_id": p.dup_id, **enriched[p.id].to_prompt_dict(),
                "ean": enriched[p.id].ean, "povodny_popis": p.description[:3000]} for p in showcase]
        pod_path = out / f"{slug(shop)}-podklady.json"
        pod_path.write_text(json.dumps(pod, ensure_ascii=False, indent=1), "utf-8")
        print(f"✓ Podklady: {pod_path}")

    improved: dict[str, dict] = {}
    ai = None
    if not args.audit_only:
        ai = AIClient(args.provider, args.model, cache_path=str(out / "ai_cache.json"))
        if not ai.available:
            print("! Chýba AI (API kľúč alebo Ollama v .env) – pokračujem len s tým, čo je v cache.")
        else:
            print(f"→ AI vylepšenie {len(showcase)} produktov ({ai.provider}, {ai.model}, jazyk {args.lang})")
        for i, p in enumerate(showcase, 1):
            ep = enriched[p.id]
            try:
                if (ai.available and not args.export) or ai.cached(ep, args.lang):
                    improved[p.id] = ai.improve(ep, args.lang)
                    print(f"  [{i}/{len(showcase)}] {improved[p.id].get('nazov', '')[:70]}")
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(showcase)}] chyba pri {p.id}: {e}", file=sys.stderr)

    if tree and improved and args.lang == "sk":
        print("→ Priraďujem kategórie Heureky")
        for p in showcase:
            if p.id in improved:
                preset = improved[p.id].get("kategoria")
                if preset and tree.is_valid(preset):  # kategória už určená (napr. ručne v cache)
                    improved[p.id] = {**improved[p.id], "kategoria_sposob": improved[p.id].get("kategoria_sposob", "určená")}
                    continue
                cat, how = assign_category(enriched[p.id], tree, ai if ai and ai.available else None)
                improved[p.id] = {**improved[p.id], "kategoria": cat, "kategoria_sposob": how}
                if cat and how != "ponechaná":
                    print(f"  {p.id}: {cat} ({how})")

    base = f"{slug(shop)}-{args.lang}"
    html_path = out / f"{base}-report.html"
    html_path.write_text(build_html(shop, args.feed, showcase, audit, improved, args.lang, args.contact,
                                    enriched=enriched, notes=notes, category_ok=tree.is_valid if tree else None), "utf-8")
    print(f"✓ Report: {html_path}")
    if improved:
        csv_path = out / f"{base}-vylepsene.csv"
        write_csv(csv_path, showcase, improved, enriched)
        print(f"✓ CSV:    {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
