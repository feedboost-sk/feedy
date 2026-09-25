"""Výstupy: HTML report pred/po (na poslanie e-shopu) a CSV s vylepšenými dátami."""
from __future__ import annotations

import csv
import datetime as dt
import html
from pathlib import Path

import dataclasses
from collections import Counter

from .audit import audit_product, product_score
from .feed import Product, strip_html

CSS = """
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;background:#f5f6f8;color:#1c2330;line-height:1.5}
.wrap{max-width:960px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:40px 0 12px}.muted{color:#667085}
.hero{background:#fff;border-radius:16px;padding:24px;display:flex;gap:24px;align-items:center;flex-wrap:wrap;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.score{width:120px;height:120px;border-radius:50%;display:grid;place-items:center;font-size:36px;font-weight:700;color:#fff;flex:none}
.kpis{display:flex;gap:16px;flex-wrap:wrap}.kpi{background:#f5f6f8;border-radius:12px;padding:12px 16px;min-width:140px}
.kpi b{display:block;font-size:22px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}
td,th{padding:10px 14px;text-align:left;border-bottom:1px solid #eef0f3;font-size:14px}th{background:#fafbfc;font-weight:600}
.sev{font-size:12px;padding:2px 8px;border-radius:99px;white-space:nowrap}
.sev-kritické{background:#fde8e8;color:#b42318}.sev-dôležité{background:#fff4e5;color:#b54708}.sev-odporúčanie{background:#eef4ff;color:#3538cd}
.bar{height:8px;background:#eef0f3;border-radius:99px;min-width:80px}.bar i{display:block;height:100%;border-radius:99px;background:#f79009}
.card{background:#fff;border-radius:16px;padding:20px;margin:16px 0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.card-head{display:flex;gap:16px;align-items:center;margin-bottom:12px}.card-head img{width:72px;height:72px;object-fit:contain;border-radius:8px;background:#f5f6f8;flex:none}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:700px){.cols{grid-template-columns:1fr}}
.before,.after{border-radius:12px;padding:14px;font-size:14px;min-width:0;overflow-wrap:anywhere}
.before{background:#fdf2f2}.after{background:#ecfdf3}.lbl{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
.before .lbl{color:#b42318}.after .lbl{color:#067647}.pname{font-weight:600;margin-bottom:8px}.desc{white-space:pre-line;color:#344054}
.params{margin-top:8px;font-size:13px}.params span{display:inline-block;background:rgba(0,0,0,.05);border-radius:6px;padding:2px 8px;margin:2px 4px 2px 0}
.changes{margin:12px 0 0;padding-left:18px;font-size:14px;color:#344054}
.tags span{font-size:12px;margin:2px 4px 2px 0;display:inline-block;white-space:normal}.card-head>div{min-width:0}
@media(max-width:600px){.bar{display:none}td,th{padding:8px 10px}.kpis{gap:8px}.kpi{min-width:0;flex:1 1 90px;padding:10px}.kpi b{font-size:18px}.score{width:88px;height:88px;font-size:28px}.hero{padding:16px}}
.tbl{overflow-x:auto;border-radius:12px}
.cta{background:#1c2330;color:#fff;border-radius:16px;padding:24px;margin-top:40px}.cta a{color:#9ec5ff}
"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def _score_color(s: int) -> str:
    return "#12b76a" if s >= 80 else "#f79009" if s >= 55 else "#f04438"


def _params_html(params: dict) -> str:
    if not params:
        return '<div class="params muted">Žiadne parametre</div>'
    return '<div class="params">' + "".join(f"<span>{_e(k)}: {_e(v)}</span>" for k, v in params.items()) + "</div>"


def build_html(shop: str, source: str, products: list[Product], audit: dict, improved: dict[str, dict],
               lang: str, contact: str, enriched: dict | None = None, notes: dict | None = None,
               category_ok=None) -> str:
    enriched = enriched or {}
    notes = notes or {}
    today = dt.date.today().strftime("%d.%m.%Y")
    s = audit["score"]
    affected = sum(1 for v in audit["per_product"].values() if v)
    rows = "".join(
        f'<tr><td>{_e(it["issue"].label)}</td><td><span class="sev sev-{it["issue"].severity}">{it["issue"].severity}</span></td>'
        f'<td>{it["count"]}</td><td><div class="bar"><i style="width:{it["pct"]}%"></i></div> {it["pct"]} %</td></tr>'
        for it in audit["summary"]
    ) or '<tr><td colspan="4">Nenašli sme žiadne problémy.</td></tr>'

    # skóre po úprave: produkt s novým názvom/popisom/parametrami prejde rovnakým auditom
    after_scores: dict[str, int] = {}
    if lang == "sk":
        upd = {}
        for p in products:
            imp = improved.get(p.id)
            if imp:
                base = enriched.get(p.id, p)
                upd[p.id] = dataclasses.replace(
                    base, name=imp.get("nazov") or p.name, description=imp.get("popis") or p.description,
                    params={**base.params, **(imp.get("parametre") or {})},
                    category=imp.get("kategoria") or base.category)
        dc = Counter(strip_html(x.description) for x in upd.values() if x.description.strip())
        after_scores = {pid: product_score(audit_product(x, dc, category_ok)) for pid, x in upd.items()}
    before_scores = {pid: product_score(audit["per_product"].get(pid, [])) for pid in after_scores}
    avg = lambda d: round(sum(d.values()) / len(d)) if d else 0  # noqa: E731

    cards = []
    for p in products:
        imp = improved.get(p.id)
        if not imp:
            continue
        issues = audit["per_product"].get(p.id, [])
        tags = "".join(f'<span class="sev sev-{i.severity}">{_e(i.label)}</span> ' for i in issues)
        before_desc = strip_html(p.description) or "— bez popisu —"
        if len(before_desc) > 700:
            before_desc = before_desc[:700] + "…"
        ep = enriched.get(p.id, p)
        found = "".join(f"<li><b>Zo stránky:</b> {_e(n)}</li>" for n in notes.get(p.id, []))
        changes = found + "".join(f"<li>{_e(c)}</li>" for c in imp.get("zmeny", []))
        cat_new = imp.get("kategoria") or ""
        cat_how = imp.get("kategoria_sposob", "")
        cat_html = ""
        if cat_new and cat_how != "ponechaná":
            label = "návrh – skontrolujte" if cat_how in ("podľa zhody slov",) else "priradená"
            cat_html = f'<div class="params"><span>Kategória ({label}): {_e(cat_new)}</span></div>'
        extra_html = "".join(f'<div class="params"><span>{lbl}: {_e(v)}</span></div>' for lbl, v, old in (
            ("EAN", ep.ean, p.ean), ("Výrobca", ep.manufacturer, p.manufacturer)) if v and v != old)
        img = f'<img src="{_e(p.image)}" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">' if p.image else ""
        cards.append(f"""
<div class="card">
  <div class="card-head">{img}<div><div class="muted" style="font-size:13px">ID {_e(p.id)} · skóre {product_score(issues)}/100{f' → <b style="color:#067647">{after_scores[p.id]}/100</b>' if p.id in after_scores else ''}</div>
  <div class="tags">{tags}</div></div></div>
  <div class="cols">
    <div class="before"><div class="lbl">Teraz</div><div class="pname">{_e(p.name)}</div>
      <div class="desc">{_e(before_desc)}</div>{_params_html(p.params)}</div>
    <div class="after"><div class="lbl">Po úprave{' (' + _e(lang.upper()) + ')' if lang != 'sk' else ''}</div><div class="pname">{_e(imp.get('nazov'))}</div>
      <div class="desc">{_e(imp.get('popis'))}</div>{_params_html({**ep.params, **imp.get('parametre', {})} if lang == 'sk' else imp.get('parametre', {}))}{extra_html}{cat_html}</div>
  </div>
  {f'<ul class="changes">{changes}</ul>' if changes else ''}
</div>""")

    return f"""<!doctype html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audit produktového feedu – {_e(shop)}</title><style>{CSS}</style></head><body><div class="wrap">
<div class="muted">Audit produktového feedu · {today}</div>
<h1>{_e(shop)}</h1>
<div class="muted" style="margin-bottom:20px;font-size:13px;overflow-wrap:anywhere">Zdroj: {_e(source)}</div>
<div class="hero">
  <div class="score" style="background:{_score_color(s)}">{s}</div>
  <div><div style="font-weight:600;margin-bottom:8px">Kvalita feedu (0–100)</div>
  <div class="kpis">
    <div class="kpi"><b>{audit['total']}</b>produktov vo feede</div>
    <div class="kpi"><b>{affected}</b>produktov s problémom</div>
    <div class="kpi"><b>{len(audit['summary'])}</b>typov problémov</div>
    {f'<div class="kpi" style="background:#ecfdf3"><b>{avg(before_scores)} → {avg(after_scores)}</b>skóre ukážkových produktov po úprave</div>' if after_scores else ''}
  </div></div>
</div>
{'<p class="muted" style="font-size:13px">Skóre po úprave rátame rovnakými pravidlami. EAN, kategóriu a obrázky AI nedoplní – tie musí dodať e-shop alebo dodávateľ, preto skóre nemusí dosiahnuť 100.</p>' if after_scores else ''}
<h2>Čo sme vo feede našli</h2>
<p class="muted">Porovnávače (Heureka, Google Shopping) zobrazujú lepšie produkty s kompletným názvom, výrobcom, EAN a parametrami.
Chýbajúce údaje znamenajú horšie párovanie, menej zobrazení vo filtroch a drahšie kliky.</p>
<div class="tbl"><table><tr><th>Problém</th><th>Závažnosť</th><th>Počet</th><th>Podiel produktov</th></tr>{rows}</table></div>
{f'''<h2>Ukážka: {len(cards)} produktov pred a po úprave</h2>
<p class="muted">Úpravy vychádzajú výhradne z údajov, ktoré už máte vo feede – nič sme si nevymysleli. Pred nasadením ich skontroluje človek.</p>
{''.join(cards)}''' if cards else ''}
<div class="cta"><div style="font-size:18px;font-weight:600;margin-bottom:6px">{'Chcete takto upraviť celý katalóg?' if cards else 'Chcete tieto problémy opraviť?'}</div>
<div>Spracujem všetky produkty, dodám súbor pripravený na import a feed budem priebežne strážiť.<br>{_e(contact)}</div></div>
</div></body></html>"""


def write_csv(path: Path, products: list[Product], improved: dict[str, dict], enriched: dict | None = None) -> None:
    enriched = enriched or {}
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["ITEM_ID", "URL", "PRODUCTNAME_povodny", "PRODUCTNAME_novy", "DESCRIPTION_novy",
                    "PARAMETRE_novy", "CATEGORYTEXT_novy", "MANUFACTURER", "EAN"])
        for p in products:
            imp = improved.get(p.id)
            if not imp:
                continue
            ep = enriched.get(p.id, p)
            params = " | ".join(f"{k}: {v}" for k, v in imp.get("parametre", {}).items())
            w.writerow([p.id, p.url, p.name, imp.get("nazov", ""), imp.get("popis", ""), params,
                        imp.get("kategoria", ""), ep.manufacturer, ep.ean])
