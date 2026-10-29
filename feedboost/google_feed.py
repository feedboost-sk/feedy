"""Z opraveného Heureka feedu vyrobí feed pre Google Merchant Center (RSS 2.0, menný priestor g:).

Použitie samostatne:
  python -m feedboost.google_feed --feed output/klient.xml --mena EUR --krajina SK --out output/klient-google.xml

V publish.py sa volá automaticky, ak má klient v klienti.json pole "google", napr.:
  "google": {"mena": "EUR", "krajina": "SK"}            (voliteľne aj "kategorie": "klient-google.json")
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

from lxml import etree

G = "http://base.google.com/ns/1.0"

# Heureka kategória -> Google product category ID. Pravidlá sa skúšajú postupne na poslednej
# časti cesty (bez diakritiky, malými písmenami); platí prvé, ktoré sedí. SK aj CZ názvy.
RULES: list[tuple[str, int | None]] = [
    (r"elektrick\w* (vozidl|vozitk)", 2753), (r"odraz", 3441), (r"trojkol|trikol|slapac|slapaci", 2724),
    (r"kostym", 5193), (r"kociky pre babik|kocarky pro panenk", 3584), (r"^kociky$|^kocarky$", 568),
    (r"korby|tasky na koc|podlozky do koc|prislusenstvo ku koc|prislusenstvi ke koc|slnecnik|slunecnik|plastenky na koc", 4387),
    (r"vlozky a podlozky do autosed|doplnky k autosed|doplnky k autosed", 4486),
    (r"podsedak|^autosedacky$", 547), (r"fusak", 8537),
    (r"rc model|dialkove ovladanie k rc|dalkova ovladani k rc", 3601), (r"plys", 1259), (r"figur", 6058),
    (r"domcek\w* pre babik|domecky pro panenk", 2499), (r"^detske kuchynky$|^detske kuchynky$", 543622),
    (r"kuchynk|kuchynek|kuchynkam|kuchynkam", 543690), (r"hry na profes", 3129), (r"hudobn|hudebn", 3252),
    (r"interakt", 7198), (r"gulockov|kulickov", 3163), (r"stavebnic", 3287), (r"hojdac\w* kon|houpaci kon", 3441),
    (r"chodit", 1241), (r"hracie podlozky|hraci podlozky", 543612), (r"lezadl|lehatk", 555), (r"ohrad", 539),
    (r"zabran|poistk|pojistk", 544), (r"monitor|pestunk|chuvick", 541),
    (r"detske stolicky|detske zidlick|jidelni zidlick|jedalensk\w* stolick", 559), (r"stolik|stolecky", 554),
    (r"kolisk", 6393), (r"postielk|postylk", 6394), (r"matrac", 2696), (r"osusk", 576), (r"vanick|vane", 4679),
    (r"dojcenske flase|kojenecke lahve", 564), (r"odsavac", 565), (r"dojciace vankuse|kojici polstare", 5298),
    (r"cumlik|dudlik", 7360), (r"nocnik", 552), (r"plien|plen", 551), (r"zavinovac", 543665),
    (r"batoh", 100), (r"penazenk|penezenk", 2668), (r"kabelky a tasky", 3032), (r"siltovk|ksiltovk", 5625),
    (r"pyzam", 2580), (r"zupan", 2302), (r"ponozk", 5423), (r"vytvarne a kreativne sady|slizu", 4986),
    (r"balonik|balonk", 2587), (r"bublifuk", 3874), (r"trampol", 1738), (r"vozik\w* za (bicyk|kolo)", 3811),
    (r"obliecky|povleceni|plachty|prosteradl", 4171), (r"taniere|talire", 3553), (r"pribory", 5647),
    (r"inhalator", 505669), (r"pre najmensich|pro nejmensi", 2847), (r"vlacik|vlacky", 5152),
]
DEFAULT_BY_TOP = [(r"^hracky", 1253), (r"^detsky tovar|^detske zbozi", 537)]


def _strip(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def google_category(heureka_path: str, overrides: dict[str, int] | None = None) -> int | None:
    if overrides and heureka_path in overrides:
        return overrides[heureka_path]
    segs = [s.strip() for s in heureka_path.split("|")][1:]
    if not segs:
        return None
    last = _strip(segs[-1])
    for rx, gid in RULES:
        if re.search(rx, last):
            return gid
    top = _strip(segs[0])
    for rx, gid in DEFAULT_BY_TOP:
        if re.search(rx, top):
            return gid
    return None


def _local(tag) -> str:
    return tag.split("}", 1)[1] if isinstance(tag, str) and tag.startswith("{") else tag


def _txt(item, tag) -> str:
    for c in item:
        if _local(c.tag) == tag:
            return "".join(c.itertext()).strip()
    return ""


def _all(item, tag) -> list[str]:
    return ["".join(c.itertext()).strip() for c in item if _local(c.tag) == tag]


def _price(s: str, mena: str) -> str:
    s = s.replace(" ", "").replace(",", ".")
    try:
        return f"{float(s):.2f} {mena}"
    except ValueError:
        return ""


def _clean_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()[:5000]


def _gtin_ok(ean: str) -> bool:
    if not re.fullmatch(r"\d{8}|\d{12,14}", ean):
        return False
    digits = [int(d) for d in ean]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def build_google(heureka_xml: bytes, mena: str, krajina: str, overrides: dict | None = None,
                 nazov_obchodu: str = "", link_obchodu: str = "") -> tuple[bytes, dict]:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(heureka_xml, parser)
    items = [el for el in root.iter() if _local(el.tag) == "SHOPITEM"]
    rss = etree.Element("rss", nsmap={"g": G}, version="2.0")
    ch = etree.SubElement(rss, "channel")
    etree.SubElement(ch, "title").text = nazov_obchodu or "Produkty"
    etree.SubElement(ch, "link").text = link_obchodu or ""
    etree.SubElement(ch, "description").text = "Produktový feed pre Google Merchant Center"
    stats = {"produktov": 0, "bez_kategorie_google": 0, "bez_gtin": 0}

    def g(parent, tag, text):
        if text:
            etree.SubElement(parent, f"{{{G}}}{tag}").text = text

    for it in items:
        item_id = _txt(it, "ITEM_ID")
        title = _txt(it, "PRODUCTNAME") or _txt(it, "PRODUCT")
        link = _txt(it, "URL")
        price = _price(_txt(it, "PRICE_VAT"), mena)
        if not (item_id and title and link and price):
            continue
        e = etree.SubElement(ch, "item")
        g(e, "id", item_id[:50])
        etree.SubElement(e, "title").text = title[:150]
        desc = _clean_html(_txt(it, "DESCRIPTION")) or title
        etree.SubElement(e, "description").text = desc
        etree.SubElement(e, "link").text = link
        imgs = _all(it, "IMGURL") + _all(it, "IMGURL_ALTERNATIVE")
        if imgs:
            g(e, "image_link", imgs[0])
            for extra in imgs[1:11]:
                g(e, "additional_image_link", extra)
        g(e, "price", price)
        dd = _txt(it, "DELIVERY_DATE")
        avail = "in_stock" if (dd == "" or (dd.isdigit() and int(dd) <= 14)) else "out_of_stock"
        g(e, "availability", avail)
        g(e, "condition", "new")
        brand = _txt(it, "MANUFACTURER")
        g(e, "brand", brand[:70])
        ean = _txt(it, "EAN")
        if _gtin_ok(ean):
            g(e, "gtin", ean)
        else:
            stats["bez_gtin"] += 1
            if not brand:
                g(e, "identifier_exists", "no")
        g(e, "item_group_id", _txt(it, "ITEMGROUP_ID"))
        cat = _txt(it, "CATEGORYTEXT")
        gid = google_category(cat, overrides) if cat else None
        if gid:
            g(e, "google_product_category", str(gid))
        else:
            stats["bez_kategorie_google"] += 1
        if cat:
            g(e, "product_type", " > ".join(s.strip() for s in cat.split("|")[1:])[:750])
        prices = [_price(_txt(d, "DELIVERY_PRICE"), mena) for d in it if _local(d.tag) == "DELIVERY"]
        prices = [p for p in prices if p]
        if prices:
            sh = etree.SubElement(e, f"{{{G}}}shipping")
            g(sh, "country", krajina)
            g(sh, "price", min(prices, key=lambda p: float(p.split()[0])))
        for p in it:
            if _local(p.tag) == "PARAM":
                n, v = _txt(p, "PARAM_NAME").lower(), _txt(p, "VAL")
                if n in ("farba", "barva") and v:
                    g(e, "color", v[:100])
                elif n in ("veľkosť", "velkost", "velikost") and v:
                    g(e, "size", v[:100])
        stats["produktov"] += 1
    return etree.tostring(rss, xml_declaration=True, encoding="utf-8", pretty_print=True), stats


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="feedboost.google_feed")
    ap.add_argument("--feed", required=True, help="opravený Heureka feed (súbor)")
    ap.add_argument("--mena", default="EUR")
    ap.add_argument("--krajina", default="SK")
    ap.add_argument("--kategorie", help="JSON {heureka cesta: google ID} – ručné výnimky")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ov = json.loads(Path(a.kategorie).read_text("utf-8")) if a.kategorie else None
    data, st = build_google(Path(a.feed).read_bytes(), a.mena, a.krajina, ov)
    Path(a.out).write_bytes(data)
    print(f"✓ Google feed: {a.out}  {st}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
