# FeedBoost – audit a AI vylepšenie produktového feedu

Zoberie Heureka alebo Google XML feed e-shopu a vytvorí:

1. **Audit bez AI**: skóre kvality feedu (0 až 100) a zoznam problémov. Hľadá chýbajúci EAN, výrobcu, parametre a popisy, reklamné slová v názve, VEĽKÉ PÍSMENÁ a duplicitné popisy.
2. **Ukážku pred a po**: AI vylepší N produktov s najhorším skóre (názov, popis, parametre), voliteľne aj s prekladom do CZ, HU, PL a ďalších jazykov.
3. **HTML report**, ktorý pošleš majiteľovi e-shopu, a **CSV** s vylepšenými dátami.

## Inštalácia (raz)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # a do .env doplň OPENAI_API_KEY alebo ANTHROPIC_API_KEY
```

## AI zadarmo

- **Google Gemini (odporúčané):** Na [aistudio.google.com](https://aistudio.google.com) si vytvor API kľúč (karta netreba) a do `.env` napíš `GEMINI_API_KEY=tvoj_kluc`. Bezplatná verzia má denné limity, na ukážky po 10 produktov stačí. Google môže dáta z bezplatnej verzie použiť na trénovanie. Pri verejných produktových dátach to nevadí, citlivé dáta klientov tam však neposielaj.
- **Ollama (lokálne, úplne offline):** Nainštaluj [ollama.com](https://ollama.com), spusti `ollama pull qwen2.5:7b` a do `.env` napíš `AI_PROVIDER=ollama`. Je to pomalšie a slovenčina je slabšia, preto výstupy dôkladne kontroluj.

## Použitie

```bash
# ukážka na fiktívnom feede (funguje aj bez API kľúča, AI výstupy sú predpripravené)
mkdir output
cp sample/demo_ai_cache.json output/ai_cache.json      # Windows: copy sample\demo_ai_cache.json output\ai_cache.json
python -m feedboost sample/sample_heureka.xml --shop "Demo Kozmetika" --n 6

# iba audit reálneho e-shopu (bez API kľúča, zadarmo)
python -m feedboost https://www.nejaky-eshop.sk/heureka.xml --audit-only

# plná ukážka pre oslovenie: 10 produktov
python -m feedboost https://www.nejaky-eshop.sk/heureka.xml --shop "Nejaký e-shop" --n 10

# preklad pre expanziu do Česka
python -m feedboost https://www.nejaky-eshop.sk/heureka.xml --n 10 --lang cs
```

Výstupy sa uložia do priečinka `output/`. Výsledky AI sa ukladajú do cache (`output/ai_cache.json`), takže opakované spustenie nič nestojí.

## Čo robí skript navyše (od verzie 0.2)

- **Číta stránky produktov z ukážky.** Na webe e-shopu hľadá EAN, výrobcu, parametre a dlhší popis, ktoré vo feede chýbajú. Nájdené údaje sa zobrazia v reporte ako „Zo stránky: …“. Tieto zistenia fungujú v predaji veľmi dobre. Vypneš to prepínačom `--no-enrich`.
- **Priraďuje kategórie Heureky.** Stiahne oficiálny strom kategórií, skontroluje, či sú kategórie vo feede platné, a produktom bez kategórie ju navrhne pomocou AI. Vypneš to prepínačom `--no-categories`.

## Práca pre klienta (od verzie 0.3)

- `python -m feedboost.catmap FEED --shop kod`: prevedie všetky kategórie e-shopu na aktuálny strom Heureky. Výsledok je JSON mapa a CSV na kontrolu.
- `python -m feedboost.build_feed --feed FEED --improved vylepsenia.json --catmap mapa.json --fix-dup-ids --out opraveny.xml`: vyrobí opravený feed a tabuľku zmien na schválenie.
- `python -m feedboost.publish`: postaví feedy všetkých klientov z `klienti/klienti.json`. Na GitHube to beží automaticky každý deň, pozri `HOSTING.md`.
- Celý postup je v `PROCES_KLIENT.md` a odpoveď pre klienta v `ODPOVED_ANO.md`.

## Ako nájsť feed e-shopu

Skús tieto adresy (často fungujú na Shoptete, WooCommerce aj vlastných riešeniach):

- `https://www.eshop.sk/heureka.xml`, `/heureka/export/products.xml`, `/feed/heureka.xml`
- `/google.xml`, `/feed/google.xml`, `/export/google.xml`
- Vyhľadávanie: `site:eshop.sk heureka.xml` alebo `site:eshop.sk filetype:xml`

Ak feed nie je verejný, e-shopu ponúkni audit a požiadaj o odkaz na feed. Majitelia ho väčšinou radi pošlú.

## Pred odoslaním ukážky

- **Každý výstup AI si prečítaj.** Jedna vymyslená vlastnosť v ukážke ti zníži dôveryhodnosť.
- Spracuj 10 produktov. Stačí to na presvedčenie a stojí to len pár centov.
- Report je samostatný HTML súbor. Pošli ho ako prílohu, alebo ho v Chrome ulož ako PDF (Tlačiť → Uložiť ako PDF).

## Čo ďalej (pre platených klientov)

- Export v tvare, ktorý Shoptet alebo WooCommerce vie priamo importovať (mapovanie stĺpcov si over podľa ich dokumentácie k importu).
- Spracovanie celého katalógu dávkovo.
- Mesačné sledovanie feedu a upozornenie, keď pribudnú produkty s problémami.
