# -*- coding: utf-8 -*-
"""debug_network_scan.py - Captura todas as respostas JSON durante o carregamento
do jogo e procura por campos relacionados a limites de aposta (bet/limit)."""
import asyncio, json, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO = ROOT / "data" / "sessao.json"
import os
URL    = os.getenv("DEBUG_URL", "https://www.estrelabet.bet.br/gameplay/ice-fishing")
DUMP_DIR = ROOT / "data" / "_debug_frames"

KEYWORDS = re.compile(r"(bet|limit|stake|wager)", re.I)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()

        hits = []

        async def on_response(resp):
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                body = await resp.json()
            except Exception:
                return
            text = json.dumps(body, ensure_ascii=False)
            if KEYWORDS.search(text):
                hits.append((resp.url, body))

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(15000)
        page.remove_listener("response", on_response)

        slug = URL.rstrip("/").split("/")[-1]
        print(">> %d respostas JSON com match de palavra-chave" % len(hits))
        DUMP_DIR.mkdir(parents=True, exist_ok=True)
        for i, (url, body) in enumerate(hits):
            print("  [%d] %s" % (i, url[:120]))
            (DUMP_DIR / ("net_%s_%d.json" % (slug, i))).write_text(
                json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
