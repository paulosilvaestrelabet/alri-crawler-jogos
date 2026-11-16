# -*- coding: utf-8 -*-
"""debug_launch_json.py - Dumps the raw /launch/game BFF response to inspect
whether bet-limit fields are available directly via API (not just DOM)."""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
BFF    = "bff-estrelabet.estrelabet.bet.br"
SESSAO = ROOT / "data" / "sessao.json"
URL    = "https://www.estrelabet.bet.br/gameplay/ice-fishing"
SAIDA  = ROOT / "data" / "_debug_frames" / "launch_ice_fishing.json"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()

        found = {}
        ready = asyncio.Event()

        async def on_response(resp):
            if BFF in resp.url and "/launch/game" in resp.url:
                try:
                    found["body"] = await resp.json()
                except Exception:
                    pass
                ready.set()

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=20000)
        try:
            await asyncio.wait_for(ready.wait(), timeout=18)
        except asyncio.TimeoutError:
            print("!! sem resposta do BFF")

        SAIDA.parent.mkdir(parents=True, exist_ok=True)
        SAIDA.write_text(json.dumps(found.get("body", {}), indent=2, ensure_ascii=False), encoding="utf-8")
        print(">> salvo em", SAIDA)

        await page.wait_for_timeout(3000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
