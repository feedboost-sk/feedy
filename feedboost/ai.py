"""AI vylepšenie produktov – OpenAI alebo Anthropic (Claude) cez ich HTTP API, s cache."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

from .feed import Product, strip_html
from .postprocess import fix_result

LANG_NAMES = {"sk": "slovenčina", "cs": "čeština", "hu": "maďarčina", "pl": "poľština", "ro": "rumunčina", "de": "nemčina"}

SYSTEM_PROMPT = """Si špecialista na produktové feedy pre Heureku a Google Shopping na slovenskom a českom trhu.
Vylepšuješ názvy, popisy a parametre produktov tak, aby lepšie predávali a spĺňali pravidlá porovnávačov.

PRAVIDLÁ:
- NIKDY si nevymýšľaj fakty. Používaj len informácie, ktoré sú v dodaných dátach (názov, popis, parametre, výrobca, kategória). Ak niečo nevieš, radšej to vynechaj.
- Názov: formát "Výrobca + typ produktu + model/séria + kľúčový variant (farba, veľkosť, objem)". Bez reklamných slov (akcia, zľava, TOP, novinka, doprava zdarma, !!!), bez VEĽKÝCH PÍSMEN, max. 120 znakov.
- Z názvu NIKDY neodstraňuj údaje, ktoré odlišujú variant (farba, ľavá/pravá, veľkosť, číslo modelu, doplnok ako „s výškovo nastaviteľným stolom“).
- Nepíš markdown (žiadne **, #, odrážky s *). Nosnosť nie je hmotnosť.
- Popis: 400–900 znakov, prirodzený jazyk, prvá veta povie čo to je a pre koho. Potom hlavné vlastnosti a úžitok. Čistý text bez HTML, odseky oddeľ \\n. Bez výmyslov typu certifikáty, záruky, ocenenia, ak nie sú v dátach.
- Parametre: vytiahni len tie, ktoré sú jednoznačne uvedené v texte (napr. Farba, Materiál, Objem, Rozmery, Hmotnosť, Veľkosť). Nepridávaj odhady.
- Ak je vstupných údajov málo, napíš kratší popis len z toho, čo vieš (popis je pre zákazníka – nikdy doň nepíš, že informácie chýbajú), a v "zmeny" uveď, aké údaje by mal e-shop doplniť (napr. výrobca, zloženie, EAN).
- Zmeny: 2–4 krátke body po slovensky, čo si zlepšil a prečo (pre majiteľa e-shopu).

Odpovedz IBA platným JSON objektom v tvare:
{"nazov": "...", "popis": "...", "parametre": {"Názov parametra": "hodnota"}, "zmeny": ["..."]}"""


def _user_prompt(p: Product, lang: str) -> str:
    data = p.to_prompt_dict()
    data["popis"] = strip_html(data["popis"])[:3000]
    lang_name = LANG_NAMES.get(lang, lang)
    extra = ""
    if lang != "sk":
        extra = (f"\nVýstupné polia nazov, popis a parametre napíš v jazyku: {lang_name} "
                 f"(prirodzene lokalizované pre tamojší trh, nie doslovný preklad). Pole zmeny nechaj po slovensky.")
    return f"Produkt:\n{json.dumps(data, ensure_ascii=False, indent=2)}\n\nJazyk výstupu: {lang_name}.{extra}"


def _extract_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"AI nevrátila JSON: {text[:200]}")
    return json.loads(m.group(0))


class AIClient:
    def __init__(self, provider: str | None = None, model: str | None = None, cache_path: str = "output/ai_cache.json"):
        self.provider = (provider or os.getenv("AI_PROVIDER") or self._detect()).lower()
        self.model = model or os.getenv("AI_MODEL") or {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-sonnet-4-5",
            "gemini": "gemini-2.5-flash",
            "ollama": "gemma3:12b",
        }.get(self.provider, "")
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text("utf-8")) if self.cache_path.exists() else {}

    @staticmethod
    def _detect() -> str:
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.getenv("GEMINI_API_KEY"):
            return "gemini"
        return "none"

    @property
    def available(self) -> bool:
        return self.provider in ("openai", "anthropic", "gemini", "ollama")

    def _key(self, p: Product, lang: str) -> str:
        raw = json.dumps([p.to_prompt_dict(), lang], ensure_ascii=False, sort_keys=True)
        return f"{p.id}:{lang}:{hashlib.sha1(raw.encode()).hexdigest()[:10]}"

    def cached(self, p: Product, lang: str) -> dict | None:
        k = self._key(p, lang)
        if k in self.cache:
            return self.cache[k]
        # fallback: cache podľa ID (napr. ručne pripravené ukážky)
        return self.cache.get(f"{p.id}:{lang}")

    def improve(self, p: Product, lang: str = "sk") -> dict:
        hit = self.cached(p, lang)
        if hit:
            return fix_result(p, hit)
        if not self.available:
            raise RuntimeError("Nie je nastavený OPENAI_API_KEY ani ANTHROPIC_API_KEY (pozri .env.example).")
        user = _user_prompt(p, lang)
        for attempt in range(3):
            try:
                text = self._call_anthropic(user) if self.provider == "anthropic" else self._call_openai(user)
                result = _extract_json(text)
                break
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        result.setdefault("parametre", {})
        result.setdefault("zmeny", [])
        result = fix_result(p, result)
        self.cache[self._key(p, lang)] = result
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), "utf-8")
        return result

    def chat_json(self, system: str, user: str) -> dict:
        """Všeobecné AI volanie s JSON odpoveďou (napr. výber kategórie)."""
        for attempt in range(3):
            try:
                text = (self._call_anthropic(user, system) if self.provider == "anthropic"
                        else self._call_openai(user, system))
                return _extract_json(text)
            except (requests.RequestException, ValueError, json.JSONDecodeError):
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        return {}

    def _openai_compat(self) -> tuple[str, dict, bool]:
        """(base_url, headers, json_mode) pre OpenAI-kompatibilné API: OpenAI, Gemini (zadarmo), Ollama (lokálne)."""
        if self.provider == "gemini":
            return ("https://generativelanguage.googleapis.com/v1beta/openai",
                    {"Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"}, False)
        if self.provider == "ollama":
            return (os.getenv("OLLAMA_URL", "http://localhost:11434") + "/v1", {}, True)
        return (os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, True)

    def _call_openai(self, user: str, system: str = SYSTEM_PROMPT) -> str:
        base, headers, json_mode = self._openai_compat()
        body = {
            "model": self.model,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = requests.post(base + "/chat/completions", headers=headers, json=body,
                          timeout=300 if self.provider == "ollama" else 120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _call_anthropic(self, user: str, system: str = SYSTEM_PROMPT) -> str:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 2000,
                "temperature": 0.3,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=120,
        )
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
