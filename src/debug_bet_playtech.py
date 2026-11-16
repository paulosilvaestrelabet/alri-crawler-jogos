# -*- coding: utf-8 -*-
"""debug_bet_playtech.py - Testa extracao do range de aposta em varios
jogos Playtech (texto real no DOM do iframe onegameslink.com)."""
import asyncio, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO = ROOT / "data" / "sessao.json"
RE_BET = re.compile(r"r\$\s*([\d.,]+)\s*[-–]\s*([\d.,]+)", re.I)

JOGOS = [
    ("Live Roulette", "https://www.estrelabet.bet.br/gameplay/live-roulette-playtech"),
    ("All Bets Blackjack Live", "https://www.estrelabet.bet.br/gameplay/all-bets-blackjack-live-playtech-eb"),
    ("Sticky Bandits Roulette Live", "https://www.estrelabet.bet.br/gameplay/sticky-bandits-roulette-live-playtech-eb"),
    ("Adventures Beyond Wonderland Live", "https://www.estrelabet.bet.br/gameplay/adventures-beyond-wonderland-live-playtech"),
    ("Who Wants To Be a Millionaire?", "https://www.estrelabet.bet.br/gameplay/who-wants-to-be-a-millionaire"),
]


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()
        for nome, url in JOGOS:
            print("\n=== %s ===" % nome)
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(15000)
            achou = False
            for i, f in enumerate(page.frames):
                try:
                    txt = await f.inner_text("body", timeout=2000) or ""
                except Exception:
                    continue
                m = RE_BET.search(txt.lower())
                if m:
                    print("  frame[%d] %s -> min=%s max=%s" % (i, f.url[:60], m.group(1), m.group(2)))
                    achou = True
            if not achou:
                print("  sem match em nenhum frame (%d frames)" % len(page.frames))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
