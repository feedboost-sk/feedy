"""Pravidlá úprav feedu pre Rolmajster.sk (žalúzie, rolety, garniže, moskytiéry).

Počíta sa pri každom zostavení feedu z aktuálneho feedu klienta, takže sa automaticky
upravia aj nové produkty. Nič si nevymýšľa – všetko berie z názvu, popisu a URL.

Ručne:  python -m feedboost.pravidla.rolmajster https://rolmajster.sk/heureka.xml --out output/klienti/rolmajster
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from ..feed import Product, load_bytes, parse_feed

Z = "Heureka.sk | Dielňa, stavba, záhrada | Stavba | Dvere, okná | Okná a parapety | Žalúzie"
R = "Heureka.sk | Dielňa, stavba, záhrada | Stavba | Dvere, okná | Okná a parapety | Rolety"
S = "Heureka.sk | Dielňa, stavba, záhrada | Stavba | Dvere, okná | Okná a parapety | Sieťky proti hmyzu"
G = "Heureka.sk | Bývanie a doplnky | Bytové doplnky | Garniže"
CATMAP = {
    "Heureka.sk | Stavebniny | Okná a parapety | Žalúzie": Z,
    "Heureka.sk | Stavebniny | Okná a parapety | Rolety": R,
    "Heureka.sk | Dom a záhrada | Domácnosť | Garniže": G,
    "Heureka.sk | Stavebniny | Okná a parapety | Siete proti hmyzu": S,
    "Heureka.sk | Dielňa, stavba, záhrada | Stavba | Dvere, okná | Okná a parapety | Sieťky proti hmyzu": S,
}
COL = ["Biela", "Čierna", "Hnedá", "Antracit", "Sivá", "Šedá", "Strieborná", "Béžová", "Krémová", "Breza", "Dub",
       "Orech", "Wenge", "Čerešňa", "Buk", "Mahagón", "Grafit", "Prírodná", "Matné striebro", "Starožitné zlato",
       "Nehrdzavejúca oceľ", "Monako Dub", "Zlatá"]
COLRE = r"\b(" + "|".join(sorted(set(COL), key=len, reverse=True)) + r")\b"
GARBLED = re.compile(r"[†Ⓥ€⧸ⱩŞ|~]")
TYPOS = [(re.compile(r"\bna na\b"), "na"), (re.compile(r"Jednoduchác"), "Jednoduchá"),
         (re.compile(r"zatemňovaciev kazete"), "zatemňovacia v kazete")]


def new_category(p: Product) -> str:
    if p.category in CATMAP:
        return CATMAP[p.category]
    n = f"{p.name} {p.url}".lower()
    if re.search(r"moskyt|hmyz", n):
        return S
    if re.search(r"garni|tyč|koľajn|kolajn|krúžk|háčik|hacik|konzol|držiak|spon|oblúk|obluk|záclon", n):
        return G
    if re.search(r"žalúz|zaluz", n):
        return Z
    return R


MANUAL_NAMES = {"roleta-v-hlinikovej-kazete": "Roleta v hliníkovej kazete"}  # ručne overené názvy podľa URL


def fix_name(name: str, url: str) -> tuple[str, list[str]]:
    notes = []
    n = name
    slug0 = url.rstrip("/").split("/")[-1].split("?")[0]
    if (GARBLED.search(n) or not re.search(r"[A-Za-zÁ-ž]{3}", n)) and slug0 in MANUAL_NAMES:
        n = MANUAL_NAMES[slug0]
        notes.append("Nečitateľný názov nahradený.")
    elif GARBLED.search(n) or not re.search(r"[A-Za-zÁ-ž]{3}", n):
        slug = url.rstrip("/").split("/")[-1].split("?")[0]
        n = slug.replace("-", " ").capitalize()
        notes.append("Nečitateľný názov nahradený názvom podľa adresy stránky.")
    for rx, rep in TYPOS:
        if rx.search(n):
            n = rx.sub(rep, n)
            notes.append("Oprava preklepu v názve.")
    n = re.sub(r"(\d)\s*mm\b", r"\1 mm", n)
    n = re.sub(r"(\d+)\s*x\s*(\d+)\s*cm", r"\1 × \2 cm", n)
    n = re.sub(r"(\d)cm\b", r"\1 cm", n)
    n = re.sub(COLRE, lambda m: m.group(1).lower(), n)
    n = re.sub(r"\s{2,}", " ", n).strip()
    if not n.lower().startswith("rolmajster"):
        n = "Rolmajster " + n
    return n, notes


def params(name: str, desc: str) -> dict[str, str]:
    o: dict[str, str] = {}
    low = name.lower()
    for rx, mat in ((r"hliník", "hliník"), (r"drev", "drevo"), (r"bambus", "bambus"), (r"pvc", "PVC"), (r"kovov", "kov")):
        if re.search(rx, low):
            o["Materiál"] = mat
            break
    m = re.search(r"(\d+)\s*mm", name)
    if m:
        if "žalúz" in low:
            o["Šírka lamely"] = m.group(1) + " mm"
        elif re.search(r"tyč|garni", low):
            o["Priemer"] = m.group(1) + " mm"
    m = re.search(COLRE, name)
    if m:
        o["Farba"] = m.group(1).lower()
    m = re.search(r"(\d+)\s*x\s*(\d+)\s*cm", name)
    if m:
        o["Šírka"] = m.group(1) + " cm"
        o["Výška"] = m.group(2) + " cm"
    else:
        m = re.search(r"(\d{2,3})\s*cm\s*$", name)
        if m:
            o["Dĺžka"] = m.group(1) + " cm"
    if "zatemňova" in low:
        o["Zatemnenie"] = "100 %"
    if "deň-noc" in low or "deň noc" in low:
        o["Typ látky"] = "deň-noc"
    if "neinvazív" in low:
        o["Montáž"] = "bez vŕtania"
    elif "vlastnú montáž" in low:
        o["Montáž"] = "vlastná montáž"
    if "na mieru" in low or "vyrábaný individuálne" in (desc or "").lower():
        o["Výroba"] = "na mieru"
    for t in ("Jednoduchá", "Dvojitá", "Stropná", "Jednodrážková", "Dvojdrážková", "Trojdrážková"):
        if t.lower() in low.replace("jednoduchác", "jednoduchá"):
            o["Typ"] = t.lower()
            break
    m = re.search(r"(\d+,\d+)\s*mm\s*x\s*(\d+,\d+)\s*mm", desc or "")
    if m and "moskyt" in low:
        o["Veľkosť ôk"] = f"{m.group(1)} × {m.group(2)} mm"
    return o


def group_key(name: str) -> str:
    n = re.sub(r"\s*\d+\s*x\s*\d+\s*cm.*$", "", name)
    n = re.sub(r"\s*\d{2,3}\s*cm\s*$", "", n)
    n = re.sub(COLRE, "", n)
    return re.sub(r"\s{2,}", " ", n).strip()


def first_sentence(new_name: str, pr: dict) -> str:
    t = re.sub(r"^Rolmajster\s+", "", new_name)
    t = re.sub(r"\s*\d+ × \d+ cm$", "", t)
    t = re.sub(r"\s*\d{2,3} cm$", "", t).rstrip(". ")
    bits = []
    if "Šírka" in pr:
        bits.append(f"rozmer {pr['Šírka'][:-3]} × {pr['Výška']}")
    elif "Dĺžka" in pr:
        bits.append(f"dĺžka {pr['Dĺžka']}")
    if pr.get("Výroba") == "na mieru" and "mieru" not in t:
        bits.append("vyrábané na mieru")
    return t[:1].upper() + t[1:] + (", " + ", ".join(bits) if bits else "") + "."


def clean_desc(s: str) -> str:
    s = re.sub(r"^Špecifikácia produktu:\s*", "", s or "")
    return re.sub(r"([a-záäčďéíľĺňóôŕšťúýž0-9])([A-ZÁČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záäčďéíľĺňóôŕšťúýž])", r"\1. \2", s)


def improve_all(products: list[Product]) -> dict[str, dict]:
    groups: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        groups[group_key(p.name)].append(p)
    gid = {}
    for k, v in groups.items():
        if len(v) > 1:
            h = "RM-" + hashlib.md5(k.encode()).hexdigest()[:6].upper()
            for p in v:
                gid[p.id] = h
    out: dict[str, dict] = {}
    for p in products:
        name, notes = fix_name(p.name, p.url)
        pr = params(p.name, p.description)
        imp: dict = {"nazov": name, "parametre": pr, "kategoria": new_category(p), "zmeny": notes}
        if p.description.strip():
            imp["popis"] = first_sentence(name, pr) + "\n" + clean_desc(p.description)
        if p.id in gid and not p.group:
            imp["itemgroup"] = gid[p.id]
        out[p.id] = imp
    return out


def main(argv=None) -> int:
    import argparse
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("feed")
    ap.add_argument("--out", default="output/klienti/rolmajster")
    a = ap.parse_args(argv)
    _, products = parse_feed(load_bytes(a.feed))
    imp = improve_all(products)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rolmajster-vylepsenia.json").write_text(json.dumps({f"{k}:sk": v for k, v in imp.items()}, ensure_ascii=False, indent=1), "utf-8")
    c = Counter()
    for v in imp.values():
        c["parametre"] += bool(v["parametre"])
        c["itemgroup"] += "itemgroup" in v
        c["preklep"] += any("preklep" in z for z in v["zmeny"])
    print(f"Produktov: {len(products)} | s parametrami: {c['parametre']} | zoskupených: {c['itemgroup']} | opravených preklepov: {c['preklep']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
