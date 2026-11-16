# -*- coding: utf-8 -*-
"""debug_ws_scan.py - Captura frames de WebSocket durante o carregamento do
jogo, procurando por texto relacionado a limites de aposta (para providers
como Playtech, cujo client pode nao expor os limites via HTTP JSON)."""
import asyncio, os, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO = ROOT / "data" / "sessao.json"
URL    = os.getenv("DEBUG_URL", "https://www.estrelabet.bet.br/gameplay/roleta-brasileira-playtech")

KEYWORDS = re.compile(r"(bet|limit|stake|wager|min|max)", re.I)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()

        sockets_seen = []

        def on_ws(ws):
            print(">> WS aberto:", ws.url[:120])
            sockets_seen.append(ws.url)

            def on_frame_received(payload):
                text = payload if isinstance(payload, str) else str(payload)
                if KEYWORDS.search(text):
                    print("   [WS msg com match, %d chars]: %s" % (len(text), text[:300]))

            ws.on("framereceived", on_frame_received)

        page.on("websocket", on_ws)
        await page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(20000)

        print("\n>> Total de sockets:", len(sockets_seen))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
