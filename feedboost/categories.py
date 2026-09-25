"""Priradenie produktov do oficiálneho stromu kategórií Heureky (CATEGORYTEXT)."""
from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path

import requests
from lxml import etree

from .feed import Product, strip_html

TREE_URLS = {
    "sk": "https://www.heureka.sk/direct/xml-export/shops/heureka-sekce.xml",
    "cz": "https://www.heureka.cz/direct/xml-export/shops/heureka-sekce.xml",
}
STOP = {"pre", "na", "do", "the", "and", "set", "sada", "bez", "pro", "ako", "alebo", "ktory", "ktora", "ktore",
        "vhodny", "vhodna", "vhodne", "velmi", "moze", "vasu", "vase", "vasej", "svoj", "tento", "tato"}

CATEGORY_PROMPT = """Priraďuješ produkty e-shopu do stromu kategórií porovnávača Heureka.
Dostaneš produkt a očíslovaný zoznam kandidátskych kategórií. Vyber JEDNU, ktorá najpresnejšie zodpovedá tomu,
čo produkt JE (nie na čo sa používa s inými vecami). Ak žiadna nesedí, vráť -1.
Odpovedz IBA JSON: {"index": <číslo>, "istota": "vysoká|stredná|nízka"}"""


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _stems(s: str) -> set[str]:
    words = re.findall(r"[a-z]{3,}", _norm(s))
    return {w[:5] for w in words if w not in STOP}


class CategoryTree:
    def __init__(self, leaves: list[str], extra_valid: list[str] | None = None):
        self.leaves = leaves  # plné cesty "Heureka.sk | A | B | C"
        self.index = []
        for full in leaves:
            parts = [x.strip() for x in full.split("|")[1:]]
            self.index.append((full, _stems(parts[-1]) if parts else set(), _stems(" ".join(parts[:-1]))))
        self.valid = {self._key(x) for x in leaves + (extra_valid or [])}

    @staticmethod
    def _key(category: str) -> str:
        c = re.sub(r"\s*[|>]\s*", " | ", category.strip().lower())
        return re.sub(r"^heureka\.(sk|cz) \| ", "", c)

    @classmethod
    def from_xml(cls, data: bytes, prefix: str = "Heureka.sk") -> "CategoryTree":
        root = etree.fromstring(data, etree.XMLParser(recover=True, huge_tree=True))
        leaves = []
        full = [x.strip() for x in root.xpath("//CATEGORY_FULLNAME/text()")]

        def walk(el, path):
            for cat in el.findall("CATEGORY"):
                name = (cat.findtext("CATEGORY_NAME") or "").strip()
                if not name:
                    continue
                p = path + [name]
                if cat.find("CATEGORY") is None:
                    leaves.append(" | ".join([prefix] + p))
                else:
                    walk(cat, p)

        walk(root, [])
        return cls(leaves, full)

    @classmethod
    def load(cls, cache_dir: str | Path, market: str = "sk", max_age_days: int = 7, log=print) -> "CategoryTree | None":
        cache = Path(cache_dir) / f"heureka_kategorie_{market}.xml"
        if not cache.exists() or time.time() - cache.stat().st_mtime > max_age_days * 86400:
            try:
                r = requests.get(TREE_URLS[market], timeout=60, headers={"User-Agent": "Mozilla/5.0 FeedBoost/0.2"})
                r.raise_for_status()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(r.content)
            except Exception as e:  # noqa: BLE001
                if not cache.exists():
                    log(f"! Strom kategórií Heureky sa nepodarilo stiahnuť ({type(e).__name__}) – kategórie preskočím.")
                    return None
        tree = cls.from_xml(cache.read_bytes(), "Heureka.sk" if market == "sk" else "Heureka.cz")
        return tree if tree.leaves else None

    def is_valid(self, category: str) -> bool:
        return self._key(category) in self.valid

    def candidates(self, p: Product, k: int = 12) -> list[tuple[str, float]]:
        name, cat = _stems(p.name), _stems(p.category)
        cat_parts = [x for x in re.split(r"\s*[|>]\s*", p.category) if x and not x.lower().startswith("heureka.")]
        cat_leaf = _stems(cat_parts[-1]) if cat_parts else set()
        desc = _stems(strip_html(p.description)[:400])
        scored = []
        for full, leaf, parents in self.index:
            sc = 3 * len(name & leaf) + 1.5 * len(cat & leaf) + 3 * len(cat_leaf & leaf) + 1 * len(desc & leaf) \
                + 1 * len(name & parents) + 1 * len(cat & parents) + 0.3 * len(desc & parents)
            if sc > 0:
                scored.append((full, sc))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


def assign_category(p: Product, tree: CategoryTree, ai=None) -> tuple[str, str]:
    """Vráti (kategória, spôsob). Prázdna kategória = nenašli sme vhodnú."""
    if p.category and tree.is_valid(p.category):
        return p.category, "ponechaná"
    cands = tree.candidates(p)
    if not cands:
        return "", "nenájdená"
    if ai is not None and getattr(ai, "available", False):
        listing = "\n".join(f"{i}. {c}" for i, (c, _) in enumerate(cands))
        user = (f"Produkt:\n{json.dumps({'nazov': p.name, 'kategoria_eshopu': p.category, 'popis': strip_html(p.description)[:500]}, ensure_ascii=False)}"
                f"\n\nKandidáti:\n{listing}")
        try:
            res = ai.chat_json(CATEGORY_PROMPT, user)
            idx = int(res.get("index", -1))
            if 0 <= idx < len(cands) and res.get("istota") != "nízka":
                return cands[idx][0], "AI"
            return "", "AI neistá"
        except Exception:  # noqa: BLE001
            pass
    best, score = cands[0]
    if score >= 3 and (len(cands) == 1 or score > cands[1][1]):
        return best, "podľa zhody slov"
    return "", "neistá"
