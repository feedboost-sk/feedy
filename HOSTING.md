# Opravený feed pre klienta: zadarmo cez GitHub

**Ako to funguje:** Klient nemusí nič meniť vo svojom e-shope. Opravený feed stiahne každý deň GitHub zo 
pôvodného feedu klienta. Pridá k nemu schválené vylepšenia (názvy, popisy, parametre, kategórie, 
opravené duplicitné ID) a zverejní ho na stálej adrese. Túto adresu klient zadá v Heureke namiesto 
pôvodného feedu. Ceny a dostupnosť sa preberajú z pôvodného feedu, takže sú vždy aktuálne.

```
feed klienta (pôvodný)  ──►  GitHub Actions (každý deň)  ──►  https://TVOJ-UCET.github.io/feedy/klient.xml  ──►  Heureka
                               + klienti/*.json (vylepšenia)
```

## Nastavenie (raz, asi 15 minút)

1. Na GitHube si vytvor nový repozitár, napríklad `feedy`. Musí byť **Public**, pretože GitHub Pages je zadarmo len pre verejné repozitáre.
2. Nahraj doň celý priečinok feedboost okrem `output/`, `.venv/` a `.env`. Tieto sú v `.gitignore`.
   Súbor `github_workflows/feedy.yml` musí byť v repozitári na ceste **`.github/workflows/feedy.yml`**. Najjednoduchšie ho vytvoríš na GitHube cez **Add file → Create new file**: do názvu napíš `.github/workflows/feedy.yml` a vlož do neho obsah súboru.
3. V repozitári otvor **Settings → Pages → Source: GitHub Actions**.
4. Otvor **Actions → Opravené feedy klientov → Run workflow**. Po 1 až 2 minútach bude feed dostupný na adrese
   `https://TVOJ-UCET.github.io/feedy/<kod-klienta>.xml`.

## Nový klient

1. Vylepšenia (JSON z FeedBoostu) a mapu kategórií nahraj do priečinka `klienti/`.
2. Do `klienti/klienti.json` pridaj klienta a nastav `"aktivny": true`.
3. Po commite sa feed vyrobí automaticky.
4. Klientovi pošli adresu feedu a návod: *Heureka administrácia → Nastavenia → XML feed → zmeniť adresu*.

## Na čo myslieť

- **Repozitár je verejný**, takže vylepšené texty uvidí ktokoľvek. Keďže ich pôvodný feed je tiež verejný, spravidla to nevadí. Klientovi to však povedz.
- **Keď klient spoluprácu ukončí**, nastav mu `"aktivny": false`. Klient si predtým musí v Heureke vrátiť svoj pôvodný feed, inak by Heureka ostala bez feedu.
- **Keď GitHub zlyhá**, dostaneš e-mail o chybe. Posledný úspešný feed zostáva zverejnený.
