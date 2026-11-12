"""Z opraveného Heureka feedu vyrobí feed pre Zboží.cz (formát Zboží: SHOP/SHOPITEM v mennom priestore Zboží).

Zboží používa takmer rovnaké značky ako Heureka (PRODUCTNAME, DESCRIPTION, URL, IMGURL, PRICE_VAT, EAN,
DELIVERY_DATE, PARAM, ITEMGROUP_ID, DELIVERY…), líši sa hlavne stromom kategórií. Preto:
  - CATEGORYTEXT sa prevedie z Heureka cesty na cestu Zboží podľa mapy klienta (klienti/<kod>-zbozi.json),
  - značky, ktoré Zboží nepozná (HEUREKA_CPC, ACCESSORY, GIFT…), sa vynechajú.

Použitie samostatne:
  python -m feedboost.zbozi_feed --feed output/klient.xml --kategorie klienti/klient-zbozi.json --out output/klient-zbozi.xml

V publish.py sa volá automaticky, ak má klient v klienti.json pole "zbozi", napr.:
  "zbozi": {"kategorie": "cime-zbozi.json"}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lxml import etree

ZBOZI_NS = "http://www.zbozi.cz/ns/offer/1.0"
VYNECHAT = {"HEUREKA_CPC", "ACCESSORY", "GIFT", "GIFT_ID", "SPECIAL_SERVICE", "SALES_VOUCHER", "EXTENDED_WARRANTY"}


def _local(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and tag.startswith("{") else tag


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def zbozi_category(heureka_path: str, catmap: dict[str, str]) -> str:
    """Heureka cesta -> cesta Zboží. Bez záznamu v mape ostane Heureka cesta bez úvodného „Heureka.cz | “
    (Zboží si ju potom zaradí samo)."""
    hit = catmap.get(_norm(heureka_path))
    if hit:
        return hit
    return re.sub(r"^Heureka\.(cz|sk)\s*\|\s*", "", heureka_path.strip())


def _copy(el, parent):
    """Skopíruje element do menného priestoru Zboží (vrátane potomkov a CDATA textu)."""
    new = etree.SubElement(parent, f"{{{ZBOZI_NS}}}{_local(el.tag)}")
    if len(el):
        for ch in el:
            if isinstance(ch.tag, str):
                _copy(ch, new)
    else:
        txt = "".join(el.itertext())
        new.text = etree.CDATA(txt) if _local(el.tag) == "DESCRIPTION" and txt else txt
    return new


def build_zbozi(heureka_xml: bytes, catmap: dict[str, str] | None = None) -> tuple[bytes, dict]:
    cm = {_norm(k): v for k, v in (catmap or {}).items()}
    parser = etree.XMLParser(recover=True, huge_tree=True, strip_cdata=False, resolve_entities=False)
    root = etree.fromstring(heureka_xml, parser)
    items = [el for el in root.iter() if _local(el.tag) == "SHOPITEM"]
    shop = etree.Element(f"{{{ZBOZI_NS}}}SHOP", nsmap={None: ZBOZI_NS})
    stats = {"produktov": 0, "kategoria_zbozi": 0, "kategoria_bez_mapy": 0}
    for it in items:
        out = etree.SubElement(shop, f"{{{ZBOZI_NS}}}SHOPITEM")
        for ch in it:
            if not isinstance(ch.tag, str):
                continue
            tag = _local(ch.tag)
            if tag in VYNECHAT:
                continue
            if tag == "CATEGORYTEXT":
                old = "".join(ch.itertext()).strip()
                new = zbozi_category(old, cm)
                stats["kategoria_zbozi" if _norm(old) in cm else "kategoria_bez_mapy"] += 1
                etree.SubElement(out, f"{{{ZBOZI_NS}}}CATEGORYTEXT").text = new
                continue
            _copy(ch, out)
        stats["produktov"] += 1
    return etree.tostring(shop, xml_declaration=True, encoding="utf-8", pretty_print=True), stats


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="feedboost.zbozi_feed")
    ap.add_argument("--feed", required=True, help="opravený Heureka feed (súbor)")
    ap.add_argument("--kategorie", help="JSON {heureka cesta: cesta Zboží}")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cm = json.loads(Path(a.kategorie).read_text("utf-8")) if a.kategorie else {}
    data, st = build_zbozi(Path(a.feed).read_bytes(), cm)
    Path(a.out).write_bytes(data)
    print(f"✓ Zboží feed: {a.out}  {st}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
