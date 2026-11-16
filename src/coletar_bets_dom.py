# -*- coding: utf-8 -*-
"""coletar_bets_dom.py - Coleta bet minima/maxima para providers cujo client
renderiza o range direto no DOM do iframe (Playtech, CreedRoomz), no
formato "R$ <min> - <max>" (ex: "R$ 0.50 - 15,000").

Diferente da Evolution (config JSON) e Pragmatic Play (tableConfig JSON),
aqui nao ha API de limites; o texto aparece no HUD do proprio jogo e e
lido via inner_text dos iframes.

Formato numerico observado: ponto decimal, virgula como separador de
milhar (ex: "15,000" = 15000; "2.50" = 2.5) -- diferente do formato BR
usado no restante do site. A virgula e sempre removida antes do parse.

Uso: python coletar_bets_dom.py <PROVEDOR>   (Playtech | CreedRoomz)
Saida: data/resultados/bets_<provedor>.csv
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
VINCULO = ROOT / "data" / "vinculo_100live.csv"

TIMEOUT_NAV_MS  = 20000
ESPERA_JOGO_MS  = 15000   # tempo para o HUD do jogo renderizar o range
N_ABAS          = 4

RE_BET = re.compile(r"r\$\s*([\d.,]+)\s*[-–]\s*([\d.,]+)", re.I)


def _parse_valor(s):
    """'15,000' -> 15000.0 | '2.50' -> 2.5 | '5' -> 5.0"""
    return float(s.replace(",", ""))


async def coletar_jogo(page, url_jogo):
    """Navega ate o jogo e procura o texto 'R$ min - max' nos frames.
    Retorna (status, detalhe, min_bet, max_bet)."""
    try:
        await page.goto(url_jogo, wait_until="domcontentloaded", timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        return "ERRO_NAV", str(e)[:100], None, None

    await page.wait_for_timeout(ESPERA_JOGO_MS)

    for frame in page.frames:
        try:
            txt = await frame.inner_text("body", timeout=2000) or ""
        except Exception:
            continue
        m = RE_BET.search(txt.lower())
        if m:
            try:
                min_bet = _parse_valor(m.group(1))
                max_bet = _parse_valor(m.group(2))
            except ValueError:
                continue
            return "OK", "", min_bet, max_bet

    return "SEM_MATCH", "Padrao 'R$ min - max' nao encontrado em nenhum frame (%d frames)" % len(page.frames), None, None


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
                    coletar_jogo(page, linha["url_jogo"]), timeout=45)
            except asyncio.TimeoutError:
                status, detalhe, min_bet, max_bet = "TIMEOUT", "Timeout global 45s", None, None
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


async def rodar_async(provedor):
    if not VINCULO.exists():
        print("!! %s nao existe. Rode vincular_live.py antes." % VINCULO)
        return

    with open(VINCULO, encoding="utf-8-sig") as f:
        linhas = [r for r in csv.DictReader(f)
                  if r["provedor_site"] == provedor and r["url_jogo"]]

    total = len(linhas)
    print(">> %d jogos %s para coletar" % (total, provedor))
    if not total:
        return

    saida = ROOT / "data" / "resultados" / ("bets_%s.csv" % provedor.lower().replace(" ", "_"))

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

    saida.parent.mkdir(parents=True, exist_ok=True)
    with open(saida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        w.writeheader()
        w.writerows(resultados)

    from collections import Counter
    cont = Counter(r["status"] for r in resultados)
    print("\n>> Resultado salvo em", saida)
    print(">> RESUMO:", dict(cont))


def rodar(provedor):
    asyncio.run(rodar_async(provedor))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python coletar_bets_dom.py <Playtech|CreedRoomz>")
        sys.exit(1)
    rodar(sys.argv[1])
