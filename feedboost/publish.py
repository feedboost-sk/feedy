"""Postaví opravené feedy pre všetkých klientov z klienti/klienti.json do priečinka public/.

Spúšťa ho GitHub Actions každý deň (pozri .github/workflows/feedy.yml), ale dá sa spustiť aj ručne:
  python -m feedboost.publish
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

from .build_feed import build, load_improved
from .feed import load_bytes


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    cfg = json.loads(Path("klienti/klienti.json").read_text("utf-8"))
    public = Path("public")
    public.mkdir(exist_ok=True)
    ok = True
    links = []
    for c in cfg.get("klienti", []):
        if not c.get("aktivny", True):
            continue
        name = c["kod"]
        try:
            improved = load_improved([f"klienti/{f}" for f in c.get("vylepsenia", [])])
            catmap = json.loads(Path(f"klienti/{c['kategorie']}").read_text("utf-8")) if c.get("kategorie") else {}
            data, log = build(load_bytes(c["feed"]), improved, catmap, c.get("opravit_duplicitne_id", False))
            (public / f"{name}.xml").write_bytes(data)
            print(f"✓ {name}: {len(log)} upravených produktov")
            links.append(f'<li><a href="{name}.xml">{name}.xml</a></li>')
        except Exception as e:  # noqa: BLE001  – jeden klient nesmie zhodiť ostatných
            ok = False
            print(f"::warning::{name}: nový feed sa nepodarilo vyrobiť ({e}) – ponechávam včerajší")
            base = os.getenv("FEEDY_URL", "").rstrip("/")
            if base:
                try:
                    r = requests.get(f"{base}/{name}.xml", timeout=60)
                    r.raise_for_status()
                    (public / f"{name}.xml").write_bytes(r.content)
                    links.append(f'<li><a href="{name}.xml">{name}.xml</a> (včerajší)</li>')
                except Exception as e2:  # noqa: BLE001
                    print(f"::error::{name}: ani včerajší feed nie je dostupný ({e2})")
    (public / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Feedy</title><ul>" + "".join(links) + "</ul>", "utf-8")
    if not ok:
        print("Niektorý feed sa nepodaril – pozri upozornenia vyššie.")
    return 0  # ostatné feedy sa nasadia aj tak


if __name__ == "__main__":
    raise SystemExit(main())
