"""Načítanie produktového feedu (Heureka XML alebo Google Merchant XML) do jednotného formátu."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import requests
from lxml import etree

G_NS = "http://base.google.com/ns/1.0"


@dataclass
class Product:
    id: str
    name: str = ""
    description: str = ""
    url: str = ""
    image: str = ""
    price: str = ""
    manufacturer: str = ""
    category: str = ""
    ean: str = ""
    delivery: str = ""
    params: dict[str, str] = field(default_factory=dict)
    extra: str = ""  # doplnkové údaje zo stránky produktu (enrich.py)
    group: str = ""  # ITEMGROUP_ID / item_group_id – varianty toho istého produktu
    dup_id: bool = False  # ITEM_ID sa vo feede opakuje (interné id dostane príponu ~N)

    def to_prompt_dict(self) -> dict:
        d = {
            "nazov": self.name,
            "popis": self.description,
            "vyrobca": self.manufacturer,
            "kategoria": self.category,
            "cena": self.price,
            "parametre": self.params,
        }
        if self.extra:
            d["udaje_zo_stranky_produktu"] = self.extra[:3000]
        return d


def load_bytes(source: str) -> bytes:
    """Stiahne feed z URL alebo načíta z lokálneho súboru."""
    if source.startswith(("http://", "https://")):
        r = requests.get(source, timeout=60, headers={"User-Agent": "Mozilla/5.0 FeedBoost/0.1"})
        r.raise_for_status()
        return r.content
    return Path(source).read_bytes()


def _text(el, tag: str, ns: str | None = None) -> str:
    if el is None:
        return ""
    found = el.find(f"{{{ns}}}{tag}" if ns else tag)
    if found is None:
        return ""
    if len(found):  # obsah s vnorenými elementmi (napr. <DESCRIPTION><p>…</p></DESCRIPTION> alebo <POPIS>)
        parts = [t.strip() for t in found.itertext() if t.strip()]
        return "\n".join(parts)
    return (found.text or "").strip()


def _parse_heureka(root) -> list[Product]:
    products = []
    for it in root.iter("SHOPITEM"):
        params = {}
        for p in it.findall("PARAM"):
            k, v = _text(p, "PARAM_NAME"), _text(p, "VAL")
            if k:
                params[k] = v
        products.append(Product(
            id=_text(it, "ITEM_ID") or _text(it, "EAN") or _text(it, "URL"),
            name=_text(it, "PRODUCTNAME") or _text(it, "PRODUCT"),
            description=_text(it, "DESCRIPTION"),
            url=_text(it, "URL"),
            image=_text(it, "IMGURL"),
            price=_text(it, "PRICE_VAT"),
            manufacturer=_text(it, "MANUFACTURER"),
            category=_text(it, "CATEGORYTEXT"),
            ean=_text(it, "EAN"),
            delivery=_text(it, "DELIVERY_DATE") or _text(it, "AVAILABILITY") or _text(it, "DELIVERY"),
            params=params,
            group=_text(it, "ITEMGROUP_ID"),
        ))
    return products


def _parse_google(root) -> list[Product]:
    products = []
    items = list(root.iter("item")) or list(root.iter("entry"))
    for it in items:
        g = lambda t: _text(it, t, G_NS)  # noqa: E731
        params = {}
        for key, label in (("color", "Farba"), ("size", "Veľkosť"), ("material", "Materiál")):
            if g(key):
                params[label] = g(key)
        products.append(Product(
            id=g("id"),
            name=g("title") or _text(it, "title"),
            description=g("description") or _text(it, "description"),
            url=g("link") or _text(it, "link"),
            image=g("image_link"),
            price=g("price"),
            manufacturer=g("brand"),
            category=g("product_type") or g("google_product_category"),
            ean=g("gtin"),
            delivery=g("availability"),
            params=params,
            group=g("item_group_id"),
        ))
    return products


def parse_feed(data: bytes) -> tuple[str, list[Product]]:
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    root = etree.fromstring(data, parser)
    if root is None:
        raise ValueError("Feed sa nepodarilo načítať ako XML.")
    # odstránenie default namespace (napr. xmlns="http://www.heureka.cz/ns/offer/1.0"), g: ponecháme
    for el in root.iter():
        if isinstance(el.tag, str) and el.tag.startswith("{") and not el.tag.startswith(f"{{{G_NS}}}"):
            el.tag = el.tag.split("}", 1)[1]
    if root.tag == "SHOP" or root.find(".//SHOPITEM") is not None:
        fmt, products = "heureka", _parse_heureka(root)
    else:
        fmt, products = "google", _parse_google(root)
    return fmt, _unique_ids(products)


def _unique_ids(products: list[Product]) -> list[Product]:
    """Duplicitné ITEM_ID označí (Heureka ich vyžaduje jedinečné) a interne ich odlíši."""
    from collections import Counter
    counts = Counter(p.id for p in products)
    seen: Counter = Counter()
    for p in products:
        if counts[p.id] > 1:
            seen[p.id] += 1
            p.dup_id = True
            if seen[p.id] > 1:
                p.id = f"{p.id}~{seen[p.id]}"
    return products


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</li>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()
