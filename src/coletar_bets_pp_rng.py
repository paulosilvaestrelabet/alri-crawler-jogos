# -*- coding: utf-8 -*-
"""coletar_bets_pp_rng.py - Coleta bet minima/maxima dos slots/crash games
Pragmatic Play da aba "200 RNG" (data/vinculo_200rng.csv).

O client Pragmatic Play (gs2c/btrzmbdurg.net) expoe, na resposta de
gs2c/ge/v3/gameService (formato query-string, nao JSON), a lista de
valores de moeda "sc=0.01,0.02,...,12.50" e o numero de linhas "l=20".
A aposta total minima/maxima exibida no jogo e:
    min_bet = min(sc) * l
    max_bet = max(sc) * l
Validado contra 3 jogos que ja tinham Min/Max Bet BRL preenchidos na
planilha (Gates of Olympus, Joker's Jewels, Tigre Sortudo) -- bateu exato.
"""
import asyncio, csv, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO  = ROOT / "data" / "sessao.json"
VINCULO = ROOT / "data" / "vinculo_200rng.csv"
SAIDA   = ROOT / "data" / "resultados" / "bets_pp_rng.csv"

TIMEOUT_NAV_MS    = 20000
ESPERA_SERVICE_MS = 15000
N_ABAS            = 4

SERVICE_HOST = "btrzmbdurg.net"
SERVICE_PATH = "gameService"

RE_SC = re.compile(r"[&?]sc=([^&]+)")
RE_L  = re.compile(r"[&?]l=([^&]+)")


def extrair_limites(body_texto):
    m_sc = RE_SC.search(body_texto)
    m_l = RE_L.search(body_texto)
    if not m_sc or not m_l:
        return None, None
    try:
        valores = [float(x) for x in m_sc.group(1).split(",") if x]
        linhas = float(m_l.group(1))
    except ValueError:
        return None, None
    if not valores or linhas <= 0:
        return None, None
    return min(valores) * linhas, max(valores) * linhas


async def coletar_jogo(page, url_jogo):
    corpo = {}
    pronto = asyncio.Event()

    async def on_response(resp):
        if SERVICE_HOST in resp.url and SERVICE_PATH in resp.url:
            if not pronto.is_set():
                try:
                    b = await resp.body()
                    corpo["texto"] = b.decode("utf-8", errors="replace")
                except Exception:
                    corpo["texto"] = ""
                pronto.set()

    page.on("response", on_response)
    try:
        await page.goto(url_jogo, wait_until="domcontentloaded", timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        page.remove_listener("response", on_response)
        return "ERRO_NAV", str(e)[:100], None, None

    try:
        await asyncio.wait_for(pronto.wait(), timeout=ESPERA_SERVICE_MS / 1000.0)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        return "SEM_CONFIG", "gameService nao respondeu em %ds" % (ESPERA_SERVICE_MS // 1000), None, None

    page.remove_listener("response", on_response)

    min_bet, max_bet = extrair_limites(corpo.get("texto", ""))
    if min_bet is None:
        return "SEM_LIMITES", "gameService recebido mas sem campos sc/l reconheciveis", None, None

    return "OK", "", round(min_bet, 4), round(max_bet, 4)


async def _processar_lote(ctx, linhas, n_abas, total_geral):
    pages = [await ctx.new_page() for _ in range(n_abas)]
    pool = asyncio.Queue()
    for pg in pages:
        await pool.put(pg)

    resultados = []
    lock = asyncio.Lock()
    contador = [0]

    async def tarefa(linha):
        page = await pool.get()
        try:
            try:
                status, detalhe, min_bet, max_bet = await asyncio.wait_for(
                    coletar_jogo(page, linha["url_jogo"]), timeout=40)
            except asyncio.TimeoutError:
                status, detalhe, min_bet, max_bet = "TIMEOUT", "Timeout global 40s", None, None
                try:
                    await page.goto("about:blank", timeout=5000)
                except Exception:
                    pass

            row = {
                "jogo_planilha":     linha["jogo_planilha"],
                "provider_planilha": linha["provider_planilha"],
                "nome_site":         linha["nome_site"],
                "url_jogo":          linha["url_jogo"],
                "min_bet_brl":       min_bet,
                "max_bet_brl":       max_bet,
                "status":            status,
                "detalhe":           detalhe,
            }
            async with lock:
                resultados.append(row)
                contador[0] += 1
                print("  [%d/%d] %-14s min=%-10s max=%-10s %s"
                      % (contador[0], total_geral, status, min_bet, max_bet, linha["nome_site"][:40]))
            return row
        finally:
            await pool.put(page)

    await asyncio.gather(*[tarefa(l) for l in linhas])
    for pg in pages:
        await pg.close()
    return resultados


async def rodar_async():
    if not VINCULO.exists():
        print("!! %s nao existe. Rode vincular_rng.py antes." % VINCULO)
        return

    with open(VINCULO, encoding="utf-8-sig") as f:
        linhas = [r for r in csv.DictReader(f)
                  if r["provedor_site"] == "Pragmatic Play" and r["url_jogo"]]

    total = len(linhas)
    print(">> %d jogos Pragmatic Play (RNG) para coletar" % total)

    def _chave(l):
        return (l["jogo_planilha"], l["provider_planilha"])

    por_chave = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))

        pendentes = linhas
        for tentativa, n_abas in enumerate([N_ABAS, 2, 1], start=1):
            if not pendentes:
                break
            print(">> Tentativa %d: %d jogos | %d abas" % (tentativa, len(pendentes), n_abas))
            novos = await _processar_lote(ctx, pendentes, n_abas, total)
            for row in novos:
                por_chave[(row["jogo_planilha"], row["provider_planilha"])] = row
            pendentes = [l for l in pendentes if por_chave[_chave(l)]["status"] != "OK"]

        await browser.close()

    resultados = [por_chave[_chave(l)] for l in linhas]

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        w.writeheader()
        w.writerows(resultados)

    from collections import Counter
    cont = Counter(r["status"] for r in resultados)
    print("\n>> Resultado salvo em", SAIDA)
    print(">> RESUMO:", dict(cont))


def rodar():
    asyncio.run(rodar_async())


if __name__ == "__main__":
    rodar()
