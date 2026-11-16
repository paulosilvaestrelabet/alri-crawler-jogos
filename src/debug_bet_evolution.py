# -*- coding: utf-8 -*-
"""debug_bet_evolution.py - Debug: acha o texto "R$ min - max" nos frames
de alguns jogos Evolution, para validar o regex antes de rodar em lote."""
import asyncio, os, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
BFF    = "bff-estrelabet.estrelabet.bet.br"
SESSAO = ROOT / "data" / "sessao.json"

TIMEOUT_NAV_MS   = 20000
ESPERA_LAUNCH_MS = 18000
ESPERA_JOGO_MS   = 12000

RE_BET = re.compile(r"r\$\s*([\d.,]+)\s*[-–]\s*([\d.,]+)")

JOGOS_TESTE = [
    ("Ice Fishing", "https://www.estrelabet.bet.br/gameplay/ice-fishing"),
]

DUMP_DIR = ROOT / "data" / "_debug_frames"


async def checar(page, nome, url_jogo):
    launch_ready = asyncio.Event()

    async def on_response(resp):
        if BFF in resp.url and "/launch/game" in resp.url:
            if not launch_ready.is_set():
                launch_ready.set()

    page.on("response", on_response)
    await page.goto(url_jogo, wait_until="domcontentloaded", timeout=TIMEOUT_NAV_MS)
    try:
        await asyncio.wait_for(launch_ready.wait(), timeout=ESPERA_LAUNCH_MS / 1000.0)
    except asyncio.TimeoutError:
        print("  !! BFF launch nao respondeu")
    page.remove_listener("response", on_response)

    await page.wait_for_timeout(ESPERA_JOGO_MS)

    print("  >> Frames: %d" % len(page.frames))
    for i, frame in enumerate(page.frames):
        try:
            fb = await frame.inner_text("body", timeout=2000) or ""
        except Exception as ex:
            fb = ""
            print("    frame[%d] inner_text ERRO: %s" % (i, str(ex)[:60]))
        try:
            html = await frame.content()
        except Exception as ex:
            html = ""
            print("    frame[%d] content ERRO: %s" % (i, str(ex)[:60]))

        m = RE_BET.search(fb.lower()) or RE_BET.search(html.lower())
        if m:
            print("    frame[%d] url=%-50s MATCH min=%s max=%s"
                  % (i, frame.url[:50], m.group(1), m.group(2)))
        else:
            preview = fb[:100].replace("\n", " | ")
            print("    frame[%d] url=%-50s len_html=%d sem match. texto='%s'"
                  % (i, frame.url[:50], len(html), preview))
            if html:
                DUMP_DIR.mkdir(parents=True, exist_ok=True)
                dump_path = DUMP_DIR / ("%s_frame%d.html" % (nome.replace(" ", "_"), i))
                dump_path.write_text(html, encoding="utf-8")
                print("    frame[%d] html salvo em %s" % (i, dump_path))


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()
        for nome, url in JOGOS_TESTE:
            print("\n=== %s ===" % nome)
            await checar(page, nome, url)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
