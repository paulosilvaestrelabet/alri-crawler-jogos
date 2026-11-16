# -*- coding: utf-8 -*-
"""coletar_jogos.py (Alri) - Monta data/alri/jogos.csv visitando as paginas
dos provedores.

1. /providers/ -> links /casino/providers/<slug>/ (fallback: manifest CMS)
2. cada /casino/providers/<slug>/ -> rola a pagina e coleta /casino/games/<seoSlug>/
3. cruza com o catalogo publico (stellar-assets .../catalog.json) para obter
   o gameCode (e o que o POST /games/play recebe) e o nome oficial.
   Jogos do catalogo que nao apareceram na pagina do provedor entram com
   origem=catalogo, para nao ficarem sem verificacao.
"""
import os, csv, re
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT      = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "config" / ".env")
BASE      = os.getenv("ALRI_BASE", "https://alri.com")
MANIFEST  = "https://stellar-assets.alri.com/casino/manifest"
SESSAO    = ROOT / "data" / "alri" / "sessao.json"
SAIDA_CSV = ROOT / "data" / "alri" / "jogos.csv"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
RE_PROV = re.compile(r"/casino/providers/([^/?#]+)")
RE_GAME = re.compile(r"/casino/games/([^/?#]+)")
MAX_ROLAGENS = 40


def _hrefs(page):
    return page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.getAttribute('href'))")


def _provedores_pagina(page):
    page.goto(BASE + "/providers/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    if "/waitlist" in page.url:
        return None
    slugs = []
    for h in _hrefs(page):
        m = RE_PROV.search(h or "")
        if m and m.group(1) not in slugs:
            slugs.append(m.group(1))
    return slugs


def _provedores_manifest(req):
    """Fallback: bloco provider_chips da pagina 'providers' no CMS."""
    man = req.get(MANIFEST + "/alri/en/manifest.json").json()
    ref = man["pages"]["providers"]["ref"]
    pagina = req.get(MANIFEST + "/" + ref).json()
    slugs = []
    for sec in pagina.get("sections", []):
        for logo in sec.get("props", {}).get("logos", []):
            if logo.get("slug") and logo["slug"] not in slugs:
                slugs.append(logo["slug"])
    return slugs


def _jogos_da_pagina(page, slug):
    """Abre a pagina do provedor, rola ate parar de aparecer jogo novo."""
    r = page.goto(BASE + "/casino/providers/%s/" % slug,
                  wait_until="domcontentloaded", timeout=60000)
    http = r.status if r else 0
    page.wait_for_timeout(4000)
    if "/waitlist" in page.url:
        return http, None
    vistos, estavel = [], 0
    for _ in range(MAX_ROLAGENS):
        antes = len(vistos)
        for h in _hrefs(page):
            m = RE_GAME.search(h or "")
            if m and m.group(1) not in vistos:
                vistos.append(m.group(1))
        # botao de paginacao, se existir
        for txt in ["Load more", "Show more", "View more", "Ver mais", "Carregar mais"]:
            try:
                b = page.locator("button:has-text('%s')" % txt).first
                if b.count() > 0 and b.is_visible():
                    b.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1200)
        estavel = estavel + 1 if len(vistos) == antes else 0
        if estavel >= 3:
            break
    return http, vistos


def coletar():
    jogos = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(SESSAO), locale="en-US",
                                  user_agent=UA)
        page = ctx.new_page()

        print(">> Baixando catalogo publico...")
        catalogo = ctx.request.get(MANIFEST + "/alri/catalog.json").json()["games"]
        por_seo = {g["seoSlug"]: g for g in catalogo}
        print(">>", len(catalogo), "jogos no catalogo.")

        print(">> Lendo provedores em /providers/ ...")
        slugs = _provedores_pagina(page)
        if slugs is None:
            print("!! /providers/ redirecionou para /waitlist/ (sessao invalida ou "
                  "conta sem acesso). Rode o login novamente.")
            browser.close()
            raise SystemExit(1)
        if not slugs:
            print("!! Nenhum link de provedor na pagina; usando manifest do CMS.")
            slugs = _provedores_manifest(ctx.request)
        print(">>", len(slugs), "provedores:", ", ".join(slugs))

        for i, slug in enumerate(slugs, 1):
            do_catalogo = [g for g in catalogo if g["providerSlug"] == slug]
            nome_prov = do_catalogo[0]["providerName"] if do_catalogo else slug
            try:
                http, seo_slugs = _jogos_da_pagina(page, slug)
            except Exception as e:
                http, seo_slugs = 0, []
                print("  [%d/%d] %s: falha ao abrir pagina (%s)"
                      % (i, len(slugs), slug, str(e)[:60]))
            if seo_slugs is None:
                print("!! Sessao caiu (redirecionou para /waitlist/). Abortando.")
                browser.close()
                raise SystemExit(1)

            na_pagina = set(seo_slugs)
            for s in seo_slugs:
                g = por_seo.get(s, {})
                jogos.append({
                    "provedor":      nome_prov,
                    "slug_provedor": slug,
                    "nome":          g.get("name", s),
                    "game_code":     g.get("gameCode", ""),
                    "url_jogo":      BASE + "/casino/games/%s/" % s,
                    "origem":        "pagina",
                })
            faltando = [g for g in do_catalogo if g["seoSlug"] not in na_pagina]
            for g in faltando:
                jogos.append({
                    "provedor":      nome_prov,
                    "slug_provedor": slug,
                    "nome":          g["name"],
                    "game_code":     g["gameCode"],
                    "url_jogo":      BASE + "/casino/games/%s/" % g["seoSlug"],
                    "origem":        "catalogo",
                })
            print("  [%d/%d] %-22s HTTP %s | pagina %d | so no catalogo %d"
                  % (i, len(slugs), slug, http, len(na_pagina), len(faltando)))

        browser.close()

    SAIDA_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["provedor", "slug_provedor", "nome",
                                          "game_code", "url_jogo", "origem"])
        w.writeheader()
        w.writerows(jogos)
    print("\n>>", len(jogos), "jogos salvos em", SAIDA_CSV)


if __name__ == "__main__":
    coletar()
