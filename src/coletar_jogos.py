# -*- coding: utf-8 -*-
"""coletar_jogos.py - Monta data/jogos.csv via API interna do BFF.
Endpoint descoberto pelo espiao: bff-estrelabet.estrelabet.bet.br/games/lobby/group
Usa cookies da sessao salva para autenticar as chamadas.
"""
import os, json, csv
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
BASE = os.getenv("EB_BASE", "https://www.estrelabet.bet.br")
BFF  = "https://bff-estrelabet.estrelabet.bet.br"
SESSAO   = ROOT / "data" / "sessao.json"
SAIDA_CSV = ROOT / "data" / "jogos.csv"


def coletar():
    jogos = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(SESSAO), locale="pt-BR")

        # --- passo 1: listar todos os provedores ---
        print(">> Buscando provedores via API...")
        r = ctx.request.get(
            BFF + "/games/lobby/group",
            params={
                "language": "pb",
                "group": "jogos",
                "categorySlug": "providers",
                "fields.categoryContent": "true",
                "fields.providers": "true",
            },
        )
        providers = r.json()["data"]["providers"]
        print(">>", len(providers), "provedores encontrados.")

        # --- passo 2: jogos de cada provedor ---
        for i, prov in enumerate(providers, 1):
            code = prov["vendorCode"]
            name = prov["vendorDisplayName"]
            try:
                r2 = ctx.request.get(
                    BFF + "/games/lobby/group",
                    params={
                        "language": "pb",
                        "group": "jogos",
                        "providerCode": code,
                        "fields.providerWithGames": "true",
                    },
                )
                pwg   = r2.json().get("data", {}).get("providerWithGames", [])
                games = pwg[0]["games"] if pwg else []
                novos = 0
                for g in games:
                    slug = g.get("url", "").strip()
                    if not slug:
                        continue
                    jogos.append({
                        "provedor":       name,
                        "slug_provedor":  code,
                        "nome":           g.get("name", slug),
                        "url_jogo":       BASE + "/gameplay/" + slug,
                    })
                    novos += 1
                print("  [%d/%d] %s: +%d (total %d)"
                      % (i, len(providers), code, novos, len(jogos)))
            except Exception as e:
                print("  [%d/%d] %s: FALHA (%s)"
                      % (i, len(providers), code, str(e)[:60]))

        browser.close()

    SAIDA_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f,
                           fieldnames=["provedor", "slug_provedor", "nome", "url_jogo"])
        w.writeheader()
        w.writerows(jogos)

    print("\n>>", len(jogos), "jogos salvos em", SAIDA_CSV)


if __name__ == "__main__":
    coletar()
