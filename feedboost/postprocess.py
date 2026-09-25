"""Kontrola a oprava výstupu AI pravidlami – malé lokálne modely často nedodržia všetky pokyny."""
from __future__ import annotations

import re

from .audit import PROMO_WORDS
from .feed import Product, strip_html

# vety, ktoré nemajú čo robiť v popise pre zákazníka
BAD_SENTENCES = re.compile(
    r"[^.\n]*(informácie nie sú (dostupné|k dispozícii)|nie je uvedené|nie sú uvedené|chýbajú údaje|"
    r"doplňte|odporúčame doplniť|neuvádza sa)[^.\n]*[.\n]?",
    re.I,
)

UNIT_PATTERNS = [
    ("Objem", r"(\d+(?:[.,]\d+)?)\s?(ml|l)\b"),
    ("Hmotnosť", r"(?:hmotnos\w*|váha|váži)\s*:?\s*(\d+(?:[.,]\d+)?)\s?(kg|g)\b"),
    ("Rozmery", r"(\d+(?:[.,]\d+)?\s?[x×]\s?\d+(?:[.,]\d+)?(?:\s?[x×]\s?\d+(?:[.,]\d+)?)?)\s?(cm|mm|m)\b"),
    ("Počet kusov", r"(\d+)\s?(ks)\b"),
]


def _is_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7


def _fix_caps(name: str, brand: str) -> str:
    out = name.lower()
    out = out[:1].upper() + out[1:]
    if brand:
        out = re.sub(re.escape(brand), brand, out, flags=re.I)
    # jednotky späť: 250ML -> 250 ml
    return out


def _remove_promo(name: str) -> str:
    for w in sorted(PROMO_WORDS, key=len, reverse=True):
        if w in ("top", "hit", "best"):
            name = re.sub(rf"\b{w}\b", "", name, flags=re.I)
        else:
            name = re.sub(re.escape(w), "", name, flags=re.I)
    name = re.sub(r"[!]+", "", name)
    name = re.sub(r"\s*[-–|,]\s*$", "", name.strip())
    name = re.sub(r"^\s*[-–|,]\s*", "", name)
    return re.sub(r"\s{2,}", " ", name).strip()


def _norm_units(s: str) -> str:
    return re.sub(r"(\d)\s?(ml|l|g|kg|cm|mm|ks)\b", r"\1 \2", s, flags=re.I)


def extract_params(p: Product) -> dict[str, str]:
    text = " ".join([p.name, strip_html(p.description)])
    found = {}
    for label, pat in UNIT_PATTERNS:
        ms = list(re.finditer(pat, text, re.I))
        if label in ("Rozmery", "Objem") and len({m.group(0) for m in ms}) > 1:
            continue  # viac rôznych hodnôt (napr. set z viacerých kusov) – radšej nič
        m = ms[0] if ms else None
        if m:
            found[label] = f"{m.group(1).replace(' ', '')} {m.group(2).lower()}"
    return found


def fix_result(p: Product, res: dict) -> dict:
    res = dict(res)
    fixes = []
    name = (res.get("nazov") or p.name).strip()
    if _is_caps(name):
        name = _fix_caps(name, p.manufacturer)
        fixes.append("Názov prepísaný z VEĽKÝCH PÍSMEN.")
    cleaned = _remove_promo(name)
    if cleaned != name and cleaned:
        name = cleaned
        fixes.append("Z názvu odstránené reklamné slová.")
    if p.manufacturer:
        brand_first = p.manufacturer.split()[0].lower()
        if brand_first not in name.lower():
            name = f"{p.manufacturer} {name}"
    # varianty: nesmú zmiznúť údaje, ktoré odlišujú produkt (strana, číslo modelu…)
    for w in re.findall(r"\b(ľavá|pravá|ľavý|pravý|ľavé|pravé|[A-Z]{1,4}-?\d{2,}[A-Z]{0,3})\b", p.name):
        if re.fullmatch(r"\d+(ML|L|G|KG|CM|MM|KS)", w, re.I):
            continue
        if w.lower().replace(" ", "") not in name.lower().replace(" ", ""):
            name = f"{name} {w}"
    res["nazov"] = _norm_units(name)[:150]

    popis = res.get("popis") or ""
    popis2 = BAD_SENTENCES.sub("", popis).strip()
    popis2 = re.sub(r"\*\*(.+?)\*\*", r"\1", popis2)          # markdown tučné
    popis2 = re.sub(r"(?m)^\s*[*\-•]\s+", "– ", popis2)          # odrážky
    popis2 = re.sub(r"(?m)^#+\s*", "", popis2)
    popis2 = re.sub(r"\n{2,}", "\n", popis2)
    res["popis"] = _norm_units(popis2)

    params = {k: v for k, v in (res.get("parametre") or {}).items()
              if v and str(v).strip() and not re.search(r"áno\s*/\s*nie|kategória", f"{k} {v}", re.I)}
    have = {k.lower() for k in params}
    for k, v in extract_params(p).items():
        if k.lower() not in have and not any(v.split()[0] in str(x) for x in params.values()):
            params[k] = v
    res["parametre"] = params
    res["zmeny"] = list(res.get("zmeny") or []) + [f for f in fixes if f not in (res.get("zmeny") or [])]
    return res
