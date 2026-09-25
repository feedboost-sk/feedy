"""Kontrola kvality feedu bez AI – rýchla diagnostika, ktorú vieš ukázať každému e-shopu."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .feed import Product, strip_html

PROMO_WORDS = [
    "akcia", "akcie", "zľava", "zlava", "sleva", "výpredaj", "vypredaj", "výprodej", "novinka",
    "doprava zdarma", "doprava zadarmo", "top", "best", "super cena", "najlacnejš", "nejlevněj",
    "skladom", "skladem", "hit", "!!!",
]

SEVERITY = {"kritické": 3, "dôležité": 2, "odporúčanie": 1}


@dataclass
class Issue:
    code: str
    label: str
    severity: str


ISSUES = {
    "no_name": Issue("no_name", "Chýba názov produktu", "kritické"),
    "dup_id": Issue("dup_id", "Rovnaké ITEM_ID má viac produktov (Heureka vyžaduje jedinečné)", "kritické"),
    "no_desc": Issue("no_desc", "Chýba popis", "kritické"),
    "short_desc": Issue("short_desc", "Príliš krátky popis (< 150 znakov)", "dôležité"),
    "dup_desc": Issue("dup_desc", "Rovnaký popis ako iné produkty", "dôležité"),
    "html_desc": Issue("html_desc", "Popis plný HTML/formátovania", "odporúčanie"),
    "promo_name": Issue("promo_name", "Reklamné slová v názve (Heureka/Google ich nepovoľuje)", "dôležité"),
    "caps_name": Issue("caps_name", "Názov písaný VEĽKÝMI písmenami", "dôležité"),
    "long_name": Issue("long_name", "Príliš dlhý názov (> 150 znakov)", "odporúčanie"),
    "short_name": Issue("short_name", "Príliš všeobecný/krátky názov", "dôležité"),
    "no_brand_in_name": Issue("no_brand_in_name", "Názov neobsahuje výrobcu", "odporúčanie"),
    "no_manufacturer": Issue("no_manufacturer", "Chýba výrobca (MANUFACTURER)", "dôležité"),
    "no_ean": Issue("no_ean", "Chýba EAN – horšie párovanie na Heureke/Google", "dôležité"),
    "no_params": Issue("no_params", "Žiadne parametre (farba, veľkosť, materiál…)", "dôležité"),
    "no_category": Issue("no_category", "Chýba kategória", "dôležité"),
    "bad_category": Issue("bad_category", "Kategória sa nezhoduje s aktuálnym stromom Heureky (vlastná alebo zastaraná)", "odporúčanie"),
    "no_image": Issue("no_image", "Chýba obrázok", "kritické"),
    "no_price": Issue("no_price", "Chýba cena", "kritické"),
    "no_delivery": Issue("no_delivery", "Chýba dostupnosť / doba dodania", "odporúčanie"),
}


def _has_promo(name: str) -> bool:
    low = name.lower()
    for w in PROMO_WORDS:
        if w == "top" or w == "hit" or w == "best":
            if re.search(rf"\b{w}\b", low):
                return True
        elif w in low:
            return True
    return False


def audit_product(p: Product, desc_counts: Counter, category_ok=None) -> list[Issue]:
    out = []
    if p.dup_id:
        out.append(ISSUES["dup_id"])
    name = p.name.strip()
    desc_plain = strip_html(p.description)
    if not name:
        out.append(ISSUES["no_name"])
    else:
        if _has_promo(name):
            out.append(ISSUES["promo_name"])
        letters = [c for c in name if c.isalpha()]
        if len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            out.append(ISSUES["caps_name"])
        if len(name) > 150:
            out.append(ISSUES["long_name"])
        if len(name.split()) < 3:
            out.append(ISSUES["short_name"])
        if p.manufacturer and p.manufacturer.lower() not in name.lower():
            out.append(ISSUES["no_brand_in_name"])
    if not desc_plain:
        out.append(ISSUES["no_desc"])
    else:
        if len(desc_plain) < 150:
            out.append(ISSUES["short_desc"])
        if desc_counts[desc_plain] > 1 and (not p.group or desc_counts.get(("grp", desc_plain, p.group), 0) < desc_counts[desc_plain]):
            out.append(ISSUES["dup_desc"])
        if p.description.count("<") > 15:
            out.append(ISSUES["html_desc"])
    if not p.manufacturer:
        out.append(ISSUES["no_manufacturer"])
    if not p.ean:
        out.append(ISSUES["no_ean"])
    if not p.params:
        out.append(ISSUES["no_params"])
    if not p.category:
        out.append(ISSUES["no_category"])
    elif category_ok is not None and not category_ok(p.category):
        out.append(ISSUES["bad_category"])
    if not p.image:
        out.append(ISSUES["no_image"])
    if not p.price:
        out.append(ISSUES["no_price"])
    if not p.delivery:
        out.append(ISSUES["no_delivery"])
    return out


def product_score(issues: list[Issue]) -> int:
    penalty = sum({"kritické": 30, "dôležité": 12, "odporúčanie": 4}[i.severity] for i in issues)
    return max(0, 100 - penalty)


def audit_feed(products: list[Product], category_ok=None) -> dict:
    desc_counts = Counter(strip_html(p.description) for p in products if p.description.strip())
    # varianty (rovnaké ITEMGROUP_ID) môžu mať rovnaký popis – to nie je chyba
    desc_counts.update(("grp", strip_html(p.description), p.group) for p in products if p.group and p.description.strip())
    per_product = {}
    counter = Counter()
    for p in products:
        iss = audit_product(p, desc_counts, category_ok)
        per_product[p.id] = iss
        counter.update(i.code for i in iss)
    scores = [product_score(v) for v in per_product.values()] or [0]
    summary = [
        {"issue": ISSUES[c], "count": n, "pct": round(100 * n / max(1, len(products)))}
        for c, n in counter.most_common()
    ]
    summary.sort(key=lambda s: (-SEVERITY[s["issue"].severity], -s["count"]))
    return {
        "total": len(products),
        "score": round(sum(scores) / len(scores)),
        "per_product": per_product,
        "summary": summary,
    }


def pick_showcase(products: list[Product], audit: dict, n: int) -> list[Product]:
    """Vyberie produkty s najväčším potenciálom zlepšenia (najviac problémov), s obrázkom a názvom."""
    candidates = [p for p in products if p.name and p.image]
    candidates.sort(key=lambda p: product_score(audit["per_product"][p.id]))
    # rozmanitosť: najviac 1 produkt z jednej skupiny variantov / rovnakého začiatku názvu
    picked, seen = [], set()
    for p in candidates:
        key = p.group or " ".join(re.findall(r"\w+", p.name.lower())[:2])
        if key in seen:
            continue
        seen.add(key)
        picked.append(p)
        if len(picked) >= n:
            return picked
    for p in candidates:  # doplnenie, ak je rôznych produktov málo
        if len(picked) >= n:
            break
        if p not in picked:
            picked.append(p)
    return picked
