"""Vyrobí OPRAVENÝ Heureka feed: pôvodný feed klienta + schválené vylepšenia.

Zachová všetko z pôvodného feedu (ceny, dostupnosť, obrázky…) a prepíše/doplní len:
  PRODUCTNAME, PRODUCT, DESCRIPTION, CATEGORYTEXT, PARAM, MANUFACTURER, EAN
Voliteľne opraví duplicitné ITEM_ID (druhý a ďalší výskyt dostane príponu -2, -3…).

Použitie:
  python -m feedboost.build_feed --feed https://eshop.sk/heureka.xml \\
      --improved output/final/eshop/ai_cache.json --catmap output/eshop-kategorie.json \\
      --fix-dup-ids --out output/eshop-opraveny-feed.xml

Vstup --improved: JSON {"ITEM_ID" alebo "ITEM_ID:sk" alebo "ITEM_ID:sk:hash": {nazov, popis, parametre, kategoria, vyrobca, ean}}
Vstup --catmap:   JSON {"stará kategória": "Heureka.sk | … nová"} – platí pre VŠETKY produkty so starou kategóriou.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

from .feed import load_bytes


def load_improved(paths: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in paths:
        data = json.loads(Path(p).read_text("utf-8"))
        for key, val in data.items():
            parts = key.split(":")
            if len(parts) >= 2 and parts[1] != "sk":
                continue  # iné jazyky sa do SK feedu nedávajú
            item_id = parts[0]
            out[item_id] = {**out.get(item_id, {}), **val}
    return out


def _local(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and tag.startswith("{") else tag


def _set_child(item, ns: str, tag: str, text: str, after: tuple[str, ...] = ()) -> None:
    """Nastaví text elementu; ak neexistuje, vytvorí ho (za niektorým z tagov `after`, inak na koniec)."""
    for c in item:
        if _local(c.tag) == tag:
            for sub in list(c):
                c.remove(sub)
            c.text = text
            return
    el = etree.Element(f"{{{ns}}}{tag}" if ns else tag)
    el.text = text
    el.tail = "\n    "
    anchor = None
    for c in item:
        if _local(c.tag) in after:
            anchor = c
    if anchor is not None:
        anchor.addnext(el)
    else:
        item.append(el)


def _cdata_desc(item, ns: str, text: str) -> None:
    for c in item:
        if _local(c.tag) == "DESCRIPTION":
            for sub in list(c):
                c.remove(sub)
            c.text = etree.CDATA(text)
            return
    _set_child(item, ns, "DESCRIPTION", "")
    _cdata_desc(item, ns, text)


def build(feed_bytes: bytes, improved: dict[str, dict], catmap: dict[str, str],
          fix_dup_ids: bool = False) -> tuple[bytes, list[dict]]:
    parser = etree.XMLParser(recover=True, huge_tree=True, strip_cdata=False, resolve_entities=False)
    root = etree.fromstring(feed_bytes, parser)
    items = [el for el in root.iter() if _local(el.tag) == "SHOPITEM"]
    if not items:
        raise ValueError("Vo feede nie sú položky SHOPITEM (podporovaný je Heureka formát).")
    ns = items[0].tag.split("}", 1)[0][1:] if items[0].tag.startswith("{") else ""
    catmap_norm = {re.sub(r"\s+", " ", k.strip()).lower(): v for k, v in catmap.items()}

    def text_of(item, tag):
        for c in item:
            if _local(c.tag) == tag:
                return "".join(c.itertext()).strip()
        return ""

    log: list[dict] = []
    seen: Counter = Counter()
    for item in items:
        item_id = text_of(item, "ITEM_ID")
        seen[item_id] += 1
        occurrence = seen[item_id]
        changes = []

        # 1) duplicitné ITEM_ID
        key = item_id if occurrence == 1 else f"{item_id}~{occurrence}"
        if fix_dup_ids and occurrence > 1:
            new_id = f"{item_id}-{occurrence}"
            _set_child(item, ns, "ITEM_ID", new_id)
            changes.append(f"ITEM_ID {item_id} → {new_id} (duplicita)")

        # 2) kategória podľa mapy (pre všetky produkty)
        old_cat = text_of(item, "CATEGORYTEXT")
        new_cat = catmap_norm.get(re.sub(r"\s+", " ", old_cat).lower()) if old_cat else None

        # 3) vylepšenia konkrétneho produktu
        imp = improved.get(key) or (improved.get(item_id) if occurrence == 1 else None)
        old_name = text_of(item, "PRODUCTNAME") or text_of(item, "PRODUCT")
        if imp:
            if imp.get("nazov"):
                _set_child(item, ns, "PRODUCTNAME", imp["nazov"], after=("ITEM_ID",))
                if any(_local(c.tag) == "PRODUCT" for c in item):
                    _set_child(item, ns, "PRODUCT", imp["nazov"])
                changes.append("názov")
            if imp.get("popis"):
                _cdata_desc(item, ns, imp["popis"])
                changes.append("popis")
            if imp.get("vyrobca") and not text_of(item, "MANUFACTURER"):
                _set_child(item, ns, "MANUFACTURER", imp["vyrobca"])
                changes.append("výrobca")
            if imp.get("ean") and not text_of(item, "EAN"):
                _set_child(item, ns, "EAN", imp["ean"])
                changes.append("EAN")
            if imp.get("kategoria"):
                new_cat = imp["kategoria"]
            if imp.get("itemgroup") and not text_of(item, "ITEMGROUP_ID"):
                _set_child(item, ns, "ITEMGROUP_ID", imp["itemgroup"], after=("ITEM_ID",))
                changes.append("varianty zoskupené")
            params = imp.get("parametre") or {}
            if params:
                existing = {text_of(p, "PARAM_NAME").lower() for p in item if _local(p.tag) == "PARAM"}
                added = 0
                for name, val in params.items():
                    if name.lower() in existing or not str(val).strip():
                        continue
                    p = etree.SubElement(item, f"{{{ns}}}PARAM" if ns else "PARAM")
                    n = etree.SubElement(p, f"{{{ns}}}PARAM_NAME" if ns else "PARAM_NAME")
                    n.text = name
                    v = etree.SubElement(p, f"{{{ns}}}VAL" if ns else "VAL")
                    v.text = str(val)
                    added += 1
                if added:
                    changes.append(f"+{added} parametrov")

        if new_cat and new_cat != old_cat:
            _set_child(item, ns, "CATEGORYTEXT", new_cat)
            changes.append("kategória")

        if changes:
            imp = imp or {}
            log.append({"ITEM_ID": item_id, "vyskyt": occurrence, "zmeny": ", ".join(changes),
                        "nazov_povodny": old_name, "nazov_novy": imp.get("nazov", ""),
                        "popis_novy": imp.get("popis", ""),
                        "parametre_nove": " | ".join(f"{k}: {v}" for k, v in (imp.get("parametre") or {}).items()),
                        "kategoria_povodna": old_cat, "kategoria_nova": new_cat or ""})

    out = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    return out, log


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="feedboost.build_feed", description="Vyrobí opravený Heureka feed")
    ap.add_argument("--feed", required=True, help="URL alebo súbor pôvodného feedu")
    ap.add_argument("--improved", action="append", default=[], help="JSON s vylepšeniami (môže byť viackrát)")
    ap.add_argument("--catmap", help="JSON mapa starých kategórií na nové")
    ap.add_argument("--fix-dup-ids", action="store_true", help="Opraviť duplicitné ITEM_ID")
    ap.add_argument("--out", required=True, help="Výstupný XML súbor")
    args = ap.parse_args(argv)

    improved = load_improved(args.improved)
    catmap = json.loads(Path(args.catmap).read_text("utf-8")) if args.catmap else {}
    data, log = build(load_bytes(args.feed), improved, catmap, args.fix_dup_ids)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    log_path = out.with_name(out.stem + "-zmeny.csv")
    with log_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["ITEM_ID", "vyskyt", "zmeny", "nazov_povodny", "nazov_novy", "popis_novy",
                                          "parametre_nove", "kategoria_povodna", "kategoria_nova"], delimiter=";")
        w.writeheader()
        w.writerows(log)
    c = Counter(z for row in log for z in row["zmeny"].split(", "))
    print(f"✓ Opravený feed: {out}  ({len(data) // 1024} kB)")
    print(f"✓ Zoznam zmien:  {log_path}  (upravených produktov: {len(log)})")
    for k, v in c.most_common(10):
        print(f"  - {k}: {v}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
