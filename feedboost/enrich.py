"""Doplnenie údajov zo stránky produktu na webe e-shopu (JSON-LD, tabuľky parametrov).

Čítame len verejnú stránku produktu, ktorú e-shop sám uvádza vo feede (URL), a len pre pár
produktov v ukážke, s pauzou medzi požiadavkami.
"""
from __future__ import annotations

import dataclasses
import json
import re
import time

import requests
from lxml import html as lhtml

from .feed import Product

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FeedBoost/0.2 (audit produktoveho feedu)"
SKIP_KEYS = re.compile(r"kategóri|zaradenie|cena|price|doprava|dodanie|dostupn|skladom|sklad|kód|kod|záruka|zaruka|hodnoten|recenz", re.I)


@dataclasses.dataclass
class PageData:
    ean: str = ""
    brand: str = ""
    description: str = ""
    specs: dict = dataclasses.field(default_factory=dict)
    ok: bool = False
    error: str = ""


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _iter_jsonld(obj):
    if isinstance(obj, list):
        for x in obj:
            yield from _iter_jsonld(x)
    elif isinstance(obj, dict):
        yield obj
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in obj:
                yield from _iter_jsonld(obj[k])


def _valid_ean(code: str) -> bool:
    code = re.sub(r"\D", "", code or "")
    if len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def parse_page(page_html: str) -> PageData:
    d = PageData()
    try:
        doc = lhtml.fromstring(page_html)
    except Exception as e:  # noqa: BLE001
        d.error = f"HTML sa nepodarilo načítať: {e}"
        return d

    # 1) JSON-LD Product
    for node in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(node.text_content())
        except Exception:  # noqa: BLE001
            continue
        for obj in _iter_jsonld(data):
            t = obj.get("@type")
            types = t if isinstance(t, list) else [t]
            if "Product" not in types:
                continue
            for k in ("gtin13", "gtin", "gtin14", "gtin12", "gtin8", "ean"):
                v = str(obj.get(k) or "")
                if _valid_ean(v):
                    d.ean = re.sub(r"\D", "", v)
                    break
            b = obj.get("brand")
            if isinstance(b, dict):
                b = b.get("name")
            if isinstance(b, list) and b:
                b = b[0].get("name") if isinstance(b[0], dict) else b[0]
            if isinstance(b, str):
                d.brand = _clean(b)
            desc = obj.get("description")
            if isinstance(desc, str) and len(desc) > len(d.description):
                d.description = _clean(lhtml.fromstring(f"<div>{desc}</div>").text_content())
            for prop in obj.get("additionalProperty") or []:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value") is not None:
                    d.specs[_clean(str(prop["name"]))] = _clean(str(prop["value"]))

    # 2) tabuľky parametrov (2 bunky v riadku) a zoznamy dt/dd
    for tr in doc.xpath("//table//tr"):
        cells = tr.xpath("./th|./td")
        if len(cells) == 2:
            k, v = _clean(cells[0].text_content()).rstrip(":"), _clean(cells[1].text_content())
            if 1 < len(k) <= 40 and 0 < len(v) <= 120 and not SKIP_KEYS.search(k):
                d.specs.setdefault(k, v)
    for dl in doc.xpath("//dl"):
        for dt, dd in zip(dl.xpath("./dt"), dl.xpath("./dd")):
            k, v = _clean(dt.text_content()).rstrip(":"), _clean(dd.text_content())
            if 1 < len(k) <= 40 and 0 < len(v) <= 120 and not SKIP_KEYS.search(k):
                d.specs.setdefault(k, v)

    # 3) EAN v texte stránky (napr. „EAN: 8588…“)
    if not d.ean:
        for k, v in d.specs.items():
            if re.search(r"\bean\b|gtin|čiarový", k, re.I) and _valid_ean(v):
                d.ean = re.sub(r"\D", "", v)
                break
    if not d.description:
        meta = doc.xpath('//meta[@property="og:description"]/@content|//meta[@name="description"]/@content')
        if meta:
            d.description = _clean(meta[0])

    d.specs = {k: v for k, v in list(d.specs.items())[:25] if not re.search(r"\bean\b|gtin", k, re.I)}
    d.ok = bool(d.ean or d.brand or d.description or d.specs)
    return d


def fetch_page(url: str, timeout: int = 20) -> PageData:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept-Language": "sk,cs;q=0.8"})
        r.raise_for_status()
        r.encoding = r.encoding or r.apparent_encoding
        return parse_page(r.text)
    except Exception as e:  # noqa: BLE001
        return PageData(error=type(e).__name__ + (f" {e.response.status_code}" if getattr(e, "response", None) is not None else ""))


def enrich_product(p: Product, page: PageData) -> tuple[Product, list[str]]:
    """Vráti kópiu produktu doplnenú o údaje zo stránky a zoznam zistení (pre report)."""
    notes = []
    upd = {}
    if not p.ean and page.ean:
        upd["ean"] = page.ean
        notes.append(f"EAN {page.ean} máte na stránke produktu, ale chýba vo feede.")
    if not p.manufacturer and page.brand:
        upd["manufacturer"] = page.brand
        notes.append(f"Výrobca „{page.brand}“ je na stránke produktu, ale chýba vo feede.")
    new_specs = {k: v for k, v in page.specs.items() if k.lower() not in {x.lower() for x in p.params}}
    if new_specs:
        n = len(new_specs)
        word = "parameter" if n == 1 else "parametre" if n < 5 else "parametrov"
        verb = "je" if n == 1 or n >= 5 else "sú"
        notes.append(f"Na stránke produktu {verb} {n} {word}, ktoré vo feede chýbajú.")
    extra = []
    if page.description and len(page.description) > len(p.description) + 50:
        extra.append("Popis zo stránky: " + page.description[:2000])
    if new_specs:
        extra.append("Parametre zo stránky: " + "; ".join(f"{k}: {v}" for k, v in new_specs.items()))
    if new_specs:
        upd["params"] = {**p.params, **new_specs}
    upd["extra"] = "\n".join(extra)
    return dataclasses.replace(p, **upd), notes


def enrich_all(products: list[Product], delay: float = 1.0, log=print) -> tuple[dict[str, Product], dict[str, list[str]]]:
    enriched, notes = {}, {}
    for i, p in enumerate(products, 1):
        if not p.url.startswith("http") or ".example/" in p.url:
            enriched[p.id], notes[p.id] = p, []
            continue
        page = fetch_page(p.url)
        enriched[p.id], notes[p.id] = enrich_product(p, page)
        status = "ok" if page.ok else f"nič ({page.error or 'žiadne údaje'})"
        log(f"  [{i}/{len(products)}] stránka produktu: {status}"
            + (f", +{len(notes[p.id])} zistení" if notes[p.id] else ""))
        time.sleep(delay)
    return enriched, notes
