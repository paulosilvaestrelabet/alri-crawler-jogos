# -*- coding: utf-8 -*-
"""diagnostico_sem_launch.py - Investiga jogos que retornaram SEM_LAUNCH / SEM_DEMO.
Captura TODAS as chamadas ao BFF (nao apenas /launch/game) para descobrir qual
endpoint esses provedores realmente usam. Roda 1 aba por vez para descartar
interferencia de multiplas sessoes."""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
BASE   = os.getenv("EB_BASE", "https://www.estrelabet.bet.br")
BFF    = "bff-estrelabet.estrelabet.bet.br"
SESSAO = ROOT / "data" / "sessao.json"

ESPERA_MS = 20000  # aguarda requests por 20s apos domcontentloaded

JOGOS = [
    ("Games Global",  "Phoenix Infernal Win",            "/gameplay/phoenix-infernal-win-gg"),
    ("Games Global",  "Piggy Vault Bonanza Rush Express", "/gameplay/piggy-vault-bonanza-rush-express"),
    ("Games Global",  "Scarab Fortunes Power Combo",      "/gameplay/scarab-fortunes-power-combo"),
    ("Games Global",  "Crazy Monkey Banana Kingdom",      "/gameplay/crazy-monkey-banana-kingdom"),
    ("Games Global",  "Classic Blackjack with Ten-20",    "/gameplay/classic-blackjack-with-ten-20"),
    ("Games Global",  "Devilish Fortunes",                "/gameplay/devilish-fortunes"),
    ("Games Global",  "Crown Bonanza",                    "/gameplay/crown-bonanza-gg"),
    ("Games Global",  "Area Link Dragon Ascension",       "/gameplay/area-link-dragon-ascension-gg"),
    ("Games Global",  "Area Link Wolf Unleashed",         "/gameplay/area-link-wolf-unleashed"),
    ("Games Global",  "Bison Prime Power Combo",          "/gameplay/bison-prime-power-combo"),
    ("Games Global",  "Bass Brothers",                    "/gameplay/bass-brothers"),
    ("TaDaGaming",    "Fortune Gems 3",                   "/gameplay/fortune-gems-3-tada-gaming"),
    ("TaDaGaming",    "Fortune Gems 2",                   "/gameplay/fortune-gems-2-tada-gaming"),
    ("TaDaGaming",    "Fortune Tree",                     "/gameplay/fortune-tree-tada-gaming"),
    ("TaDaGaming",    "Go Rush",                          "/gameplay/go-rush-tada-gaming"),
    ("TaDaGaming",    "Mayan Empire",                     "/gameplay/mayan-empire-tada-gaming"),
    ("TaDaGaming",    "Mines Gold",                       "/gameplay/mines-gold-tada-gaming"),
    ("TaDaGaming",    "Money Coming",                     "/gameplay/money-coming-tada-gaming"),
    ("TaDaGaming",    "Potion Wizard",                    "/gameplay/potion-wizard-tada-gaming"),
    ("TaDaGaming",    "Sin City",                         "/gameplay/sin-city-tada-gaming"),
    ("TaDaGaming",    "Crazy Hunter",                     "/gameplay/crazy-hunter-tada-gaming"),
    ("TaDaGaming",    "Safari Mystery",                   "/gameplay/safari-mystery-tada-gaming"),
    ("TaDaGaming",    "Seven Seven Seven",                "/gameplay/seven-seven-seven"),
    ("TaDaGaming",    "Lucky Jaguar 2",                   "/gameplay/lucky-jaguar-2"),
    ("TaDaGaming",    "Tower",                            "/gameplay/tower"),
    ("Amusnet",       "Greek Fortune",                    "/gameplay/greek-fortune"),
    ("Hacksaw",       "Chaos Crew II",                    "/gameplay/chaos-crew-ii-hacksaw"),
    ("Hacksaw",       "Beam Boys",                        "/gameplay/beam-boys-hacksaw"),
    ("Hacksaw",       "Feel the Beat",                    "/gameplay/feel-the-beat"),
    ("Darwin",        "Hot Bingo",                        "/gameplay/hot-bingo"),
    ("Wazdan",        "Sun of Fortune",                   "/gameplay/sun-of-fortune"),
]


async def investigar(page, provedor, nome, path):
    url = BASE + path
    chamadas = []

    async def on_request(req):
        if BFF in req.url:
            chamadas.append({"tipo": "REQ", "url": req.url, "method": req.method})

    async def on_response(resp):
        if BFF in resp.url:
            try:
                body = await resp.json()
            except Exception:
                body = "<nao-json>"
            chamadas.append({
                "tipo":   "RESP",
                "url":    resp.url,
                "status": resp.status,
                "body":   body,
            })

    page.on("request",  on_request)
    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        page.remove_listener("request",  on_request)
        page.remove_listener("response", on_response)
        print("  TIMEOUT/ERRO navegacao: %s" % str(e)[:60])
        return

    await page.wait_for_timeout(ESPERA_MS)
    page.remove_listener("request",  on_request)
    page.remove_listener("response", on_response)

    # filtra apenas respostas BFF (ignora tracking, analytics, etc.)
    resps = [c for c in chamadas if c["tipo"] == "RESP"]
    if not resps:
        print("  >> NENHUMA chamada BFF detectada!")
        return

    for r in resps:
        endpoint = r["url"].replace("https://" + BFF, "")
        # trunca query string longa
        if "?" in endpoint:
            base_ep, qs = endpoint.split("?", 1)
            qs_short = qs[:120] + ("..." if len(qs) > 120 else "")
            endpoint = base_ep + "?" + qs_short
        body = r["body"]
        if isinstance(body, dict):
            data = body.get("data", {})
            if isinstance(data, dict):
                tem_real = "real" in data
                tem_free = "free" in data
                resumo = ("data.real=SIM" if tem_real else "data.real=NAO") + \
                         " | " + ("data.free=SIM" if tem_free else "data.free=NAO") + \
                         " | data keys=" + str(list(data.keys()))[:80]
            else:
                resumo = "data=" + str(data)[:120]
        else:
            resumo = str(body)[:120]
        print("  [HTTP %d] %s" % (r["status"], endpoint[:100]))
        print("           %s" % resumo)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            storage_state=str(SESSAO),
            locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()

        for i, (provedor, nome, path) in enumerate(JOGOS, 1):
            print("\n[%d/%d] %s | %s" % (i, len(JOGOS), provedor, nome))
            await investigar(page, provedor, nome, path)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
