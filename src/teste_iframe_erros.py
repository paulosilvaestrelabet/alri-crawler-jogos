# -*- coding: utf-8 -*-
"""teste_iframe_erros.py - Testa deteccao de erros dentro de iframes para
Pragmatic Play, Evolution, Playtech e Games Global.

Usa a mesma logica de check_jogos.py mas roda sequencialmente com 1 aba
e exibe os frames detectados para debug."""
import asyncio, os, sys, time
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

TIMEOUT_NAV_MS          = 20000
ESPERA_LAUNCH_MS        = 18000
ESPERA_JOGO_EXTENDIDA_MS = 14000

ERROS_IFRAME_EXTENDIDO = [
    "traceid:",
    "reinicie o jogo",
    "ocorreu um erro",
    "an error occurred",
    "game error",
    "restri",
    "not available in your",
]

JOGOS_TESTE = [
    ("Pragmatic Play", "Andar Bahar (restricao geografica)",
     "https://www.estrelabet.bet.br/gameplay/andar-bahar"),
]


def _gamecode(data_real):
    try:
        gd = data_real.get("gameDetails", {})
        return gd.get("game_code") or gd.get("gameCode") or ""
    except Exception:
        return ""


async def checar(page, provedor, nome, url_jogo):
    launch_data  = {}
    launch_ready = asyncio.Event()

    async def on_response(resp):
        if BFF in resp.url and "/launch/game" in resp.url:
            if not launch_ready.is_set():
                try:
                    launch_data["status"] = resp.status
                    launch_data["body"]   = await resp.json()
                except Exception:
                    launch_data["status"] = resp.status
                    launch_data["body"]   = {}
                launch_ready.set()

    page.on("response", on_response)
    try:
        r = await page.goto(url_jogo, wait_until="domcontentloaded",
                            timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        page.remove_listener("response", on_response)
        return "TIMEOUT_NAV", str(e)[:80]

    http = r.status if r else 0
    if http == 404:
        page.remove_listener("response", on_response)
        return "ERRO_404", "HTTP 404"

    try:
        await asyncio.wait_for(launch_ready.wait(),
                               timeout=ESPERA_LAUNCH_MS / 1000.0)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        return "SEM_LAUNCH", "BFF /launch/game nao chamado em %ds" % (ESPERA_LAUNCH_MS // 1000)

    page.remove_listener("response", on_response)

    resp_body = launch_data.get("body", {})
    data      = resp_body.get("data", {})

    if "real" not in data:
        return "SEM_REAL", "data keys=" + str(list(data.keys()) if isinstance(data, dict) else data)

    gc = _gamecode(data["real"])
    print("  >> BFF retornou data.real | gamecode=%s" % gc)
    print("  >> Aguardando %ds para iframe carregar..." % (ESPERA_JOGO_EXTENDIDA_MS // 1000))
    await page.wait_for_timeout(ESPERA_JOGO_EXTENDIDA_MS)

    # inspeciona todos os frames
    print("  >> Frames detectados: %d" % len(page.frames))
    for i, frame in enumerate(page.frames):
        try:
            fb = (await frame.inner_text("body", timeout=2000) or "").lower()
            preview = fb[:120].replace("\n", " ")
            print("    frame[%d] url=%-60s texto='%s'" % (i, frame.url[:60], preview))
            for padrao in ERROS_IFRAME_EXTENDIDO:
                if padrao in fb:
                    print("  !! ERRO DETECTADO no frame[%d]: padrao='%s'" % (i, padrao))
                    return "INDISPONIVEL", "Erro iframe (%s) | gc=%s" % (padrao, gc)
        except Exception as ex:
            print("    frame[%d] url=%-60s ERRO: %s" % (i, frame.url[:60], str(ex)[:60]))

    # verifica tambem o body principal (modal sobreposto ao iframe)
    try:
        body_main = (await page.inner_text("body", timeout=3000) or "").lower()
        print("  >> Body principal (%d chars): '%s'" % (len(body_main), body_main[:120].replace("\n", " ")))
        for padrao in ERROS_IFRAME_EXTENDIDO:
            if padrao in body_main:
                print("  !! ERRO DETECTADO no body principal: padrao='%s'" % padrao)
                return "INDISPONIVEL", "Erro pagina (%s) | gc=%s" % (padrao, gc)
    except Exception as ex:
        print("  >> Body principal ERRO: %s" % str(ex)[:60])

    return "OK", "data.real OK | gc=%s" % gc


async def main():
    if not SESSAO.exists():
        print("!! sessao.json nao encontrado. Rode login.py primeiro.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO),
            locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = await ctx.new_page()

        print(">> Testando %d jogos com deteccao de erro em iframe\n" % len(JOGOS_TESTE))
        for i, (provedor, nome, url) in enumerate(JOGOS_TESTE, 1):
            print("[%d/%d] %s | %s" % (i, len(JOGOS_TESTE), provedor, nome))
            t0 = time.time()
            status, detalhe = await checar(page, provedor, nome, url)
            ms = int((time.time() - t0) * 1000)
            print("  => STATUS: %-16s | %s | %dms\n" % (status, detalhe, ms))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
