# -*- coding: utf-8 -*-
"""coletar_gamecodes.py - Coleta o gamecode de uma lista especifica de jogos.
Le data/jogos_gamecodes_entrada.csv e salva data/gamecodes_resultado.csv com
colunas: provedor, nome, url_jogo, gamecode, status.

Usa interceptacao BFF /launch/game identica ao check_jogos.py.
Roda com 4 abas para evitar conflito de sessao concorrente."""
import asyncio, csv, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
BASE    = os.getenv("EB_BASE", "https://www.estrelabet.bet.br")
BFF     = "bff-estrelabet.estrelabet.bet.br"
SESSAO  = ROOT / "data" / "sessao.json"
ENTRADA = ROOT / "data" / "jogos_gamecodes_entrada.csv"
SAIDA   = ROOT / "data" / "gamecodes_resultado.csv"

TIMEOUT_NAV_MS   = 20000
ESPERA_LAUNCH_MS = 18000
N_ABAS           = 4   # conservador para evitar conflito de sessao


def _gamecode(data_real):
    try:
        gd = data_real.get("gameDetails", {})
        return gd.get("game_code") or gd.get("gameCode") or ""
    except Exception:
        return ""


async def coletar_gamecode(page, url_jogo):
    """Intercepta /launch/game e retorna (gamecode, status)."""
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
        return "", "TIMEOUT"

    http = r.status if r else 0
    if http == 404:
        page.remove_listener("response", on_response)
        return "", "ERRO_404"
    if http >= 500:
        page.remove_listener("response", on_response)
        return "", "ERRO_HTTP_" + str(http)

    try:
        await asyncio.wait_for(launch_ready.wait(),
                               timeout=ESPERA_LAUNCH_MS / 1000.0)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        return "", "SEM_LAUNCH"

    page.remove_listener("response", on_response)

    http_api  = launch_data.get("status", 0)
    resp_body = launch_data.get("body", {})
    data      = resp_body.get("data", {})

    if http_api >= 400:
        return "", "ERRO_HTTP_" + str(http_api)

    if "real" in data:
        return _gamecode(data["real"]), "OK"

    if "free" in data:
        return "", "DEMO_ONLY"

    # data: {} -> retry direto
    if data == {} or data is None:
        symbol = url_jogo.rstrip("/").split("/")[-1]
        try:
            retry_resp = await page.context.request.get(
                "https://" + BFF + "/launch/game",
                params={"symbol": symbol, "language": "pt",
                        "hasDemo": "true", "isMobile": "false"},
                timeout=10000)
            retry_data = (await retry_resp.json()).get("data", {})
            if isinstance(retry_data, dict) and "real" in retry_data:
                return _gamecode(retry_data["real"]), "OK"
        except Exception:
            pass
        return "", "SEM_DEMO"

    return "", "ERRO_API"


async def main():
    if not ENTRADA.exists():
        print("!! Arquivo nao encontrado:", ENTRADA)
        return

    with open(ENTRADA, encoding="utf-8-sig") as f:
        jogos = list(csv.DictReader(f))
    total = len(jogos)
    print(">> %d jogos para coletar gamecode | %d abas" % (total, N_ABAS))

    fieldnames = ["provedor", "nome", "url_jogo", "gamecode", "status"]
    resultados = []
    lock_csv   = asyncio.Lock()
    contador   = [0]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            storage_state=str(SESSAO),
            locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        pages = [await ctx.new_page() for _ in range(N_ABAS)]
        pool  = asyncio.Queue()
        for pg in pages:
            await pool.put(pg)

        with open(SAIDA, "w", newline="", encoding="utf-8-sig") as csv_f:
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            writer.writeheader()
            csv_f.flush()

            async def tarefa(jogo):
                page = await pool.get()
                try:
                    t0 = time.time()
                    try:
                        gamecode, status = await asyncio.wait_for(
                            coletar_gamecode(page, jogo["url_jogo"]),
                            timeout=50)
                    except asyncio.TimeoutError:
                        gamecode, status = "", "TIMEOUT"
                        try:
                            await page.goto("about:blank", timeout=5000)
                        except Exception:
                            pass
                    row = {
                        "provedor": jogo.get("provedor", ""),
                        "nome":     jogo.get("nome", ""),
                        "url_jogo": jogo["url_jogo"],
                        "gamecode": gamecode,
                        "status":   status,
                    }
                    async with lock_csv:
                        resultados.append(row)
                        writer.writerow(row)
                        csv_f.flush()
                        contador[0] += 1
                        gc_display = gamecode if gamecode else "(sem gamecode)"
                        print("  [%d/%d] %-12s %-16s %s"
                              % (contador[0], total,
                                 status,
                                 jogo.get("provedor", "")[:12],
                                 gc_display[:50]))
                    return row
                finally:
                    await pool.put(page)

            await asyncio.gather(*[tarefa(j) for j in jogos])

        await browser.close()

    from collections import Counter
    cont = Counter(r["status"] for r in resultados)
    sem_gc = [r for r in resultados if not r["gamecode"]]
    print("\n>> Resultado salvo em:", SAIDA)
    print(">> RESUMO status:", dict(cont))
    print(">> Jogos sem gamecode: %d" % len(sem_gc))
    if sem_gc:
        for r in sem_gc:
            print("   %-16s %s" % (r["status"], r["nome"]))


if __name__ == "__main__":
    asyncio.run(main())
