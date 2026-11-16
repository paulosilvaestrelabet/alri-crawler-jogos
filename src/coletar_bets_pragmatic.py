# -*- coding: utf-8 -*-
"""coletar_bets_pragmatic.py - Coleta bet minima/maxima dos jogos Pragmatic
Play listados em data/vinculo_100live.csv.

Pragmatic Play expoe os limites na resposta JSON de
  https://games.pragmaticplaylive.net/api/ui/tableConfig?...
em params."<tipo>_bet_min"/"<tipo>_bet_max" (um par por tipo de aposta:
player/banker/tie, red/black/odd/even..., twentyone_3, perfectpairs...)
mais um par agregado "table_bet_min_limit"/"table_bet_max_limit".

Em roleta (tableName contem "ROULETTE") o agregado "table_bet_max_limit"
pode ser inflado (cobre exposicao total, nao a aposta max de uma unica
jogada) -- mesmo problema ja visto na Evolution -- por isso e ignorado
so nesse caso; nos demais tipos de jogo ele bate com o maior "*_bet_max"
e e mantido.
"""
import asyncio, csv, os, re, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT     = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO   = ROOT / "data" / "sessao.json"
VINCULO  = ROOT / "data" / "vinculo_100live.csv"
SAIDA    = ROOT / "data" / "resultados" / "bets_pragmatic_play.csv"

TIMEOUT_NAV_MS   = 20000
ESPERA_CONFIG_MS = 15000
N_ABAS           = 4

CONFIG_HOST = "pragmaticplaylive.net"
CONFIG_PATH = "/api/ui/tableConfig"

RE_MIN = re.compile(r"(min_limit|bet_min|min_bet)$", re.I)
RE_MAX = re.compile(r"(max_limit|bet_max|max_bet)$", re.I)


def extrair_limites(table_config_json):
    """Varre o params do tableConfig e retorna (min_bet, max_bet)."""
    table_name = str(table_config_json.get("tableName", ""))
    ignorar_table = "roulette" in table_name.lower()

    params = table_config_json.get("params", {}) or {}
    mins, maxs = [], []
    for k, v in params.items():
        if ignorar_table and k.lower().startswith("table_"):
            continue
        if "payout" in k.lower():
            continue
        if RE_MIN.search(k):
            try:
                val = float(v)
                if val > 0:
                    mins.append(val)
            except (TypeError, ValueError):
                pass
        elif RE_MAX.search(k):
            try:
                val = float(v)
                if val > 0:
                    maxs.append(val)
            except (TypeError, ValueError):
                pass

    return (min(mins) if mins else None, max(maxs) if maxs else None)


async def coletar_jogo(page, url_jogo):
    config_data = {}
    config_ready = asyncio.Event()

    async def on_response(resp):
        if CONFIG_HOST in resp.url and CONFIG_PATH in resp.url:
            if not config_ready.is_set():
                try:
                    config_data["body"] = await resp.json()
                except Exception:
                    config_data["body"] = {}
                config_ready.set()

    page.on("response", on_response)
    try:
        await page.goto(url_jogo, wait_until="domcontentloaded", timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        page.remove_listener("response", on_response)
        return "ERRO_NAV", str(e)[:100], None, None

    try:
        await asyncio.wait_for(config_ready.wait(), timeout=ESPERA_CONFIG_MS / 1000.0)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        return "SEM_CONFIG", "tableConfig nao respondeu em %ds" % (ESPERA_CONFIG_MS // 1000), None, None

    page.remove_listener("response", on_response)

    body = config_data.get("body", {})
    min_bet, max_bet = extrair_limites(body)
    if min_bet is None or max_bet is None:
        return "SEM_LIMITES", "tableConfig recebido mas sem campos de limite reconheciveis", None, None

    return "OK", "", min_bet, max_bet


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
        print("!! %s nao existe. Rode vincular_live.py antes." % VINCULO)
        return

    with open(VINCULO, encoding="utf-8-sig") as f:
        linhas = [r for r in csv.DictReader(f)
                  if r["provedor_site"] == "Pragmatic Play" and r["url_jogo"]]

    total = len(linhas)
    print(">> %d jogos Pragmatic Play para coletar" % total)

    por_url = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = await browser.new_context(
            storage_state=str(SESSAO), locale="pt-BR",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))

        # varias linhas da planilha podem apontar para o mesmo url_jogo;
        # a chave de deduplicacao precisa ser a linha da planilha, nao a
        # url, senao uma linha some no meio do caminho.
        def _chave(l):
            return (l["jogo_planilha"], l["provider_planilha"])

        pendentes = linhas
        for tentativa, n_abas in enumerate([N_ABAS, 2, 1], start=1):
            if not pendentes:
                break
            print(">> Tentativa %d: %d jogos | %d abas" % (tentativa, len(pendentes), n_abas))
            novos = await _processar_lote(ctx, pendentes, n_abas, total)
            for row in novos:
                por_url[(row["jogo_planilha"], row["provider_planilha"])] = row
            pendentes = [l for l in pendentes if por_url[_chave(l)]["status"] != "OK"]

        await browser.close()

    resultados = [por_url[_chave(l)] for l in linhas]

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
