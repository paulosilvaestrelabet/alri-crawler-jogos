# -*- coding: utf-8 -*-
"""recheck_jogos.py - Re-verifica jogos por status ou provedor com sessao fresca.

Usos:
  python src/recheck_jogos.py                     -> Evolution + INDISPONIVEL (padrao)
  python src/recheck_jogos.py --status TIMEOUT    -> todos os TIMEOUT do resultado mais recente
  python src/recheck_jogos.py --status INDISPONIVEL

Saida: data/resultados/recheck_<modo>_YYYY-MM-DD.csv
"""
import os, csv, sys, time, asyncio, glob
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
SESSAO = ROOT / "data" / "sessao.json"
JOGOS  = ROOT / "data" / "jogos.csv"
HOJE   = datetime.now().strftime("%Y-%m-%d")

# mesmos valores do check_jogos.py apos as correcoes
TIMEOUT_NAV_MS  = 60000   # 60s — domcontentloaded + margem para jogos pesados
ESPERA_JOGO_MS  = 12000   # 12s espera JS do jogo inicializar
TIMEOUT_GLOBAL  = 120     # 120s ponta-a-ponta por jogo
N_ABAS          = 4       # 4 abas — gentil com o PC

PROVEDORES_PADRAO  = {"Evolution"}
PROVEDORES_IGNORAR = {"TaDaGaming"}   # mesmos que check_jogos.py — 91% TIMEOUT, ignorar sempre

SELETORES = [
    "iframe",
    "video",
    "canvas",
    "[id*='game']",
    "[class*='game']",
    "[class*='gameplay']",
    "[data-testid*='game']",
]


def ultimo_resultado():
    arquivos = sorted(glob.glob(
        str(ROOT / "data" / "resultados" / "resultado_*.csv")))
    if not arquivos:
        return []
    with open(arquivos[-1], encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def montar_lista(modo, status_filtro):
    with open(JOGOS, encoding="utf-8-sig") as f:
        todos = list(csv.DictReader(f))
    mapa_jogos = {j["url_jogo"]: j for j in todos}

    anteriores = ultimo_resultado()
    vistos = set()
    lista = []

    if status_filtro:
        # modo --status: pega todas as URLs com aquele status, exceto provedores ignorados
        urls = [r["url_jogo"] for r in anteriores if r.get("status") == status_filtro]
        for url in urls:
            jogo = mapa_jogos.get(url)
            if jogo and url not in vistos and jogo.get("provedor", "") not in PROVEDORES_IGNORAR:
                lista.append(jogo)
                vistos.add(url)
    else:
        # modo padrao: Evolution + INDISPONIVEL
        for j in todos:
            if j.get("provedor", "") in PROVEDORES_PADRAO and j["url_jogo"] not in vistos:
                lista.append(j)
                vistos.add(j["url_jogo"])
        ind_urls = {r["url_jogo"] for r in anteriores if r.get("status") == "INDISPONIVEL"}
        for url in ind_urls:
            jogo = mapa_jogos.get(url)
            if jogo and url not in vistos:
                lista.append(jogo)
                vistos.add(url)

    return lista


async def classificar(page, url_jogo):
    try:
        resp = await page.goto(url_jogo, wait_until="domcontentloaded",
                               timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        return "TIMEOUT", str(e)[:80]

    code = resp.status if resp else 0
    if code == 404:
        return "ERRO_404", "HTTP 404"
    if code >= 500:
        return "ERRO_HTTP", "HTTP " + str(code)

    try:
        body = (await page.inner_text("body", timeout=4000) or "").lower()
    except Exception:
        body = ""

    if any(t in body for t in ["faca login", "entre na sua conta", "sessao expirada"]):
        return "SESSAO_EXPIRADA", "Pediu login"
    if any(t in body for t in ["pagina nao encontrada", "not found", "404"]):
        return "ERRO_404", "Texto 404 na pagina"

    await page.wait_for_timeout(ESPERA_JOGO_MS)

    for frame in page.frames[:8]:
        try:
            fb = (await frame.inner_text("body", timeout=2000) or "").lower()
            if "traceid:" in fb:
                return "INDISPONIVEL", "Game not available (TraceId Alea)"
        except Exception:
            continue

    for sel in SELETORES:
        try:
            if await page.locator(sel).count() == 0:
                continue
            if sel == "iframe":
                el = page.locator("iframe").first
                w     = await el.get_attribute("width") or ""
                h     = await el.get_attribute("height") or ""
                src   = await el.get_attribute("src") or ""
                style = await el.get_attribute("style") or ""
                if not src and not w and not h and "width" not in style:
                    continue
            return "OK", "Renderizou (" + sel + ")"
        except Exception:
            continue

    return "NAO_CARREGOU", "Sem iframe/canvas visivel"


async def rodar_async(status_filtro):
    if not SESSAO.exists():
        print("!! sessao.json nao encontrado. Rode login.py antes.")
        return

    modo_label = status_filtro if status_filtro else "padrao"
    saida = ROOT / "data" / "resultados" / ("recheck_%s_%s.csv" % (modo_label, HOJE))

    jogos = montar_lista(modo_label, status_filtro)
    total = len(jogos)
    if not total:
        print("!! Nenhum jogo encontrado para re-verificar (status=%s)." % modo_label)
        return

    print(">> Re-verificando %d jogos com status=%s" % (total, modo_label))
    print(">> domcontentloaded | nav %ds | espera %ds | global %ds | %d abas" % (
        TIMEOUT_NAV_MS // 1000, ESPERA_JOGO_MS // 1000, TIMEOUT_GLOBAL, N_ABAS))

    # retomada parcial
    ja_feitos = set()
    modo_arquivo = "w"
    escrever_header = True
    if saida.exists():
        with open(saida, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ja_feitos.add(row["url_jogo"])
        if ja_feitos:
            print(">> Retomando: %d ja re-verificados, %d pendentes."
                  % (len(ja_feitos), total - len(ja_feitos)))
            modo_arquivo = "a"
            escrever_header = False

    jogos_pendentes = [j for j in jogos if j["url_jogo"] not in ja_feitos]
    if not jogos_pendentes:
        print(">> Todos ja re-verificados.")
        return

    saida.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["data", "provedor", "nome", "url_jogo", "status", "detalhe", "tempo_ms"]
    resultados = []
    lock_csv = asyncio.Lock()
    contador = [len(ja_feitos)]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(storage_state=str(SESSAO), locale="pt-BR")
        pages = [await ctx.new_page() for _ in range(N_ABAS)]

        pool = asyncio.Queue()
        for pg in pages:
            await pool.put(pg)

        with open(saida, modo_arquivo, newline="", encoding="utf-8-sig") as csv_f:
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            if escrever_header:
                writer.writeheader()
                csv_f.flush()

            async def tarefa(jogo):
                page = await pool.get()
                try:
                    t0 = time.time()
                    try:
                        status, detalhe = await asyncio.wait_for(
                            classificar(page, jogo["url_jogo"]),
                            timeout=TIMEOUT_GLOBAL)
                    except asyncio.TimeoutError:
                        status, detalhe = "TIMEOUT", ("Timeout global %ds" % TIMEOUT_GLOBAL)
                        try:
                            await page.goto("about:blank", timeout=5000)
                        except Exception:
                            pass
                    ms = int((time.time() - t0) * 1000)
                    row = {
                        "data":     HOJE,
                        "provedor": jogo.get("provedor", ""),
                        "nome":     jogo.get("nome", ""),
                        "url_jogo": jogo["url_jogo"],
                        "status":   status,
                        "detalhe":  detalhe,
                        "tempo_ms": ms,
                    }
                    async with lock_csv:
                        resultados.append(row)
                        writer.writerow(row)
                        csv_f.flush()
                        contador[0] += 1
                        print("  [%d/%d] %-16s %-20s %s" % (
                            contador[0], total,
                            status, jogo.get("provedor", "")[:18],
                            jogo.get("nome", "")[:35]))
                    return row
                finally:
                    await pool.put(page)

            await asyncio.gather(*[tarefa(j) for j in jogos_pendentes])

        await browser.close()

    from collections import Counter
    cont = Counter(r["status"] for r in resultados)
    print("\n>> Re-check salvo em", saida)
    print(">> RESUMO:", dict(cont))

    if status_filtro == "TIMEOUT":
        ok_agora = cont.get("OK", 0)
        ainda_timeout = cont.get("TIMEOUT", 0)
        print("\n>> De %d TIMEOUT anteriores:" % total)
        print("   %d viraram OK com as novas correcoes (%.0f%%)" % (
            ok_agora, ok_agora / total * 100 if total else 0))
        print("   %d continuam TIMEOUT (%.0f%%)" % (
            ainda_timeout, ainda_timeout / total * 100 if total else 0))

    return saida


def rodar():
    status_filtro = None
    args = sys.argv[1:]
    if "--status" in args:
        idx = args.index("--status")
        if idx + 1 < len(args):
            status_filtro = args[idx + 1]
    asyncio.run(rodar_async(status_filtro))


if __name__ == "__main__":
    rodar()
