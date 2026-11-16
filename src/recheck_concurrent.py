# -*- coding: utf-8 -*-
"""recheck_concurrent.py - Re-verifica jogos que podem ter falhado por sessao concorrente.

Alvo:
  - Games Global  com status INDISPONIVEL (provider nao aceita multiplas sessoes)
  - Playson       com status DEMO_ONLY    (idem - retorna demo quando ha sessao ativa)
  - Qualquer      com status SEM_LAUNCH   (BFF nao respondeu, possivelmente por conflito)

Roda com N_ABAS=1 (sequencial) para evitar conflito de sessao.
Usa a mesma logica BFF de check_jogos.py para classificacao precisa.
Ao final, mescla o resultado de volta no CSV principal do dia.

Uso:
  python src/recheck_concurrent.py
"""
import os, csv, sys, time, asyncio, glob, shutil
from datetime import datetime
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
HOJE   = datetime.now().strftime("%Y-%m-%d")

N_ABAS          = 1       # sequencial: evita conflito de sessao concorrente
TIMEOUT_NAV_MS  = 25000
ESPERA_LAUNCH_MS = 20000
ESPERA_JOGO_MS  = 8000
TIMEOUT_GLOBAL  = 70      # segundos

# Regras de selecao para recheck por concorrencia
ALVOS = [
    {"provedor": "Games Global", "status": "INDISPONIVEL"},
    {"provedor": "Playson",      "status": "DEMO_ONLY"},
    # SEM_LAUNCH: qualquer provedor
    {"provedor": None,           "status": "SEM_LAUNCH"},
]

# Providers com tempo de carregamento maior (verifica iframe por mais tempo)
PROVEDORES_EXTENDIDO = {"Pragmatic Play", "Evolution", "Playtech", "Games Global"}
ERROS_IFRAME_UNIVERSAL = ["traceid:"]
ERROS_IFRAME_EXTENDIDO = [
    "traceid:", "reinicie o jogo", "ocorreu um erro",
    "an error occurred", "game error", "restri", "not available in your",
]
_AUDIO_KEYWORDS = ["audio", "som ", "sound", "microfon", "mute", "silenci"]


def _restri_eh_audio(text):
    idx = text.find("restri")
    if idx == -1:
        return False
    ctx = text[max(0, idx - 50): idx + 100]
    return any(kw in ctx for kw in _AUDIO_KEYWORDS)


def _gamecode(data_real):
    try:
        gd = data_real.get("gameDetails", {})
        return gd.get("game_code") or gd.get("gameCode") or ""
    except Exception:
        return ""


async def classificar(page, url_jogo, provedor=""):
    """Mesma logica BFF de check_jogos.py."""
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
    nav_aborted = False
    r = None
    try:
        r = await page.goto(url_jogo, wait_until="domcontentloaded",
                            timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        err_str = str(e)
        if "ERR_ABORTED" in err_str:
            nav_aborted = True
        else:
            page.remove_listener("response", on_response)
            return "TIMEOUT", err_str[:80], ""

    if not nav_aborted:
        http = r.status if r else 0
        if http == 404:
            page.remove_listener("response", on_response)
            return "ERRO_404", "HTTP 404", ""
        if http >= 500:
            page.remove_listener("response", on_response)
            return "ERRO_HTTP", "HTTP " + str(http), ""

    bff_timeout = ESPERA_LAUNCH_MS / 1000.0
    try:
        await asyncio.wait_for(launch_ready.wait(), timeout=bff_timeout)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        if nav_aborted:
            symbol = url_jogo.rstrip("/").split("/")[-1]
            try:
                api_resp = await page.context.request.get(
                    "https://" + BFF + "/launch/game",
                    params={"symbol": symbol, "language": "pt",
                            "hasDemo": "true", "isMobile": "false"},
                    timeout=10000)
                api_body = await api_resp.json()
                api_data = api_body.get("data", {})
                if isinstance(api_data, dict):
                    if "real" in api_data:
                        return "OK", "Logado (BFF direto/ERR_ABORTED)", _gamecode(api_data["real"])
                    if "free" in api_data:
                        return "DEMO_ONLY", "Deslogado (BFF direto/ERR_ABORTED)", ""
            except Exception:
                pass
            return "TIMEOUT", "ERR_ABORTED (sem BFF em %ds)" % (ESPERA_LAUNCH_MS // 1000), ""
        try:
            body_txt = (await page.inner_text("body", timeout=3000) or "").lower()
            if any(t in body_txt for t in ["faca login", "entre na sua conta", "sessao expirada"]):
                return "SESSAO_EXPIRADA", "Pediu login (sem launch API)", ""
        except Exception:
            pass
        return "SEM_LAUNCH", "BFF /launch/game nao chamado em %ds" % (ESPERA_LAUNCH_MS // 1000), ""

    page.remove_listener("response", on_response)

    http_api  = launch_data.get("status", 0)
    resp_body = launch_data.get("body", {})
    data      = resp_body.get("data", {})

    if http_api == 404:
        return "ERRO_404", "BFF launch HTTP 404", ""

    if http_api >= 400:
        msg_err = str(resp_body).lower()
        if any(t in msg_err for t in ["session", "login", "unauthorized",
                                       "nao autenticado", "not authenticated"]):
            return "SESSAO_EXPIRADA", str(resp_body)[:120], ""
        return "ERRO_HTTP", "BFF HTTP %d | %s" % (http_api, str(resp_body)[:60]), ""

    if "real" in data:
        gc       = _gamecode(data["real"])
        extended = provedor in PROVEDORES_EXTENDIDO
        espera   = ESPERA_JOGO_MS * 2 if extended else ESPERA_JOGO_MS
        padroes  = ERROS_IFRAME_EXTENDIDO if extended else ERROS_IFRAME_UNIVERSAL

        await page.wait_for_timeout(espera)

        frames_alvo = page.frames if extended else page.frames[:10]
        for frame in frames_alvo:
            try:
                fb = (await frame.inner_text("body", timeout=2000) or "").lower()
                for padrao in padroes:
                    if padrao in fb:
                        if padrao == "restri" and _restri_eh_audio(fb):
                            continue
                        return "INDISPONIVEL", "Erro iframe (" + padrao + ")", gc
            except Exception:
                continue

        if extended:
            try:
                body_main = (await page.inner_text("body", timeout=3000) or "").lower()
                for padrao in padroes:
                    if padrao in body_main:
                        if padrao == "restri" and _restri_eh_audio(body_main):
                            continue
                        return "INDISPONIVEL", "Erro pagina (" + padrao + ")", gc
            except Exception:
                pass

        return "OK", "Logado (data.real) [recheck]", gc

    if "free" in data:
        return "DEMO_ONLY", "Deslogado (data.free) [recheck]", ""

    if data == {} or data is None:
        symbol = url_jogo.rstrip("/").split("/")[-1]
        try:
            retry_resp = await page.context.request.get(
                "https://" + BFF + "/launch/game",
                params={"symbol": symbol, "language": "pt",
                        "hasDemo": "true", "isMobile": "false"},
                timeout=10000)
            retry_body = await retry_resp.json()
            retry_data = retry_body.get("data", {})
            if isinstance(retry_data, dict):
                if "real" in retry_data:
                    return "OK", "Logado (retry) [recheck]", _gamecode(retry_data["real"])
                if "free" in retry_data:
                    return "DEMO_ONLY", "Deslogado (retry) [recheck]", ""
        except Exception:
            pass
        return "SEM_DEMO", "BFF retornou data vazio com retry [recheck]", ""

    msg_body = str(resp_body).lower()
    if any(t in msg_body for t in ["session", "login", "unauthorized"]):
        return "SESSAO_EXPIRADA", str(resp_body)[:120], ""

    return "ERRO_API", "Resp inesperada: " + str(resp_body)[:100], ""


def montar_lista():
    """Seleciona jogos do resultado mais recente conforme regras ALVOS."""
    arquivos = sorted(glob.glob(str(ROOT / "data" / "resultados" / "resultado_*.csv")))
    if not arquivos:
        print("!! Nenhum resultado encontrado.")
        return []
    ultimo = arquivos[-1]
    print(">> Lendo resultados de:", Path(ultimo).name)

    with open(ultimo, encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f))

    # mapa url -> linha para preservar dados originais
    vistos = set()
    selecionados = []
    for l in linhas:
        url  = l["url_jogo"]
        prov = l.get("provedor", "")
        st   = l.get("status", "")
        if url in vistos:
            continue
        for regra in ALVOS:
            prov_ok = regra["provedor"] is None or prov == regra["provedor"]
            if prov_ok and st == regra["status"]:
                selecionados.append(l)
                vistos.add(url)
                break

    return selecionados, ultimo


def mesclar_no_principal(saida_recheck, arquivo_principal):
    """Substitui linhas no CSV principal pelos resultados do recheck."""
    with open(saida_recheck, encoding="utf-8-sig") as f:
        novos = {r["url_jogo"]: r for r in csv.DictReader(f)}

    with open(arquivo_principal, encoding="utf-8-sig") as f:
        originais = list(csv.DictReader(f))
        fieldnames = originais[0].keys() if originais else []

    atualizados = 0
    for row in originais:
        if row["url_jogo"] in novos:
            novo = novos[row["url_jogo"]]
            row["status"]   = novo["status"]
            row["detalhe"]  = novo["detalhe"] + " [recheck]"
            row["gamecode"] = novo.get("gamecode", row.get("gamecode", ""))
            row["tempo_ms"] = novo["tempo_ms"]
            atualizados += 1

    # backup antes de sobrescrever
    bkp_dir = Path(arquivo_principal).parent / "backups"
    bkp_dir.mkdir(exist_ok=True)
    ts  = datetime.now().strftime("%H%M%S")
    bkp = bkp_dir / (Path(arquivo_principal).stem + "_pre_recheck_" + ts + ".csv")
    shutil.copy2(arquivo_principal, bkp)

    with open(arquivo_principal, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(originais[0].keys()))
        writer.writeheader()
        writer.writerows(originais)

    print(">> %d linhas atualizadas no resultado principal." % atualizados)
    print(">> Backup pre-recheck salvo em:", bkp)


async def rodar_async():
    if not SESSAO.exists():
        print("!! sessao.json nao encontrado. Rode login.py antes.")
        return

    resultado = montar_lista()
    if not resultado:
        return
    jogos, arquivo_principal = resultado
    total = len(jogos)

    if not total:
        print("!! Nenhum jogo selecionado para recheck.")
        return

    from collections import Counter
    dist = Counter(
        ("SEM_LAUNCH" if j["status"] == "SEM_LAUNCH" else j["provedor"] + "/" + j["status"])
        for j in jogos
    )
    print(">> Recheck de %d jogos (N_ABAS=1, sequencial):" % total)
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print("   %-40s %d" % (k, v))

    saida = ROOT / "data" / "resultados" / ("recheck_concurrent_%s.csv" % HOJE)

    # retomada parcial
    ja_feitos = set()
    modo_arquivo = "w"
    escrever_header = True
    if saida.exists():
        with open(saida, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ja_feitos.add(row["url_jogo"])
        if ja_feitos:
            print(">> Retomando: %d ja feitos, %d pendentes."
                  % (len(ja_feitos), total - len(ja_feitos)))
            modo_arquivo = "a"
            escrever_header = False

    jogos_pendentes = [j for j in jogos if j["url_jogo"] not in ja_feitos]
    if not jogos_pendentes:
        print(">> Todos ja re-verificados.")
        mesclar_no_principal(saida, arquivo_principal)
        return

    saida.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["data", "provedor", "nome", "url_jogo",
                  "status", "detalhe", "gamecode", "tempo_ms"]
    resultados = []
    contador   = [len(ja_feitos)]

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
        page = await ctx.new_page()  # unica aba

        with open(saida, modo_arquivo, newline="", encoding="utf-8-sig") as csv_f:
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            if escrever_header:
                writer.writeheader()
                csv_f.flush()

            for idx, jogo in enumerate(jogos_pendentes):
                t0 = time.time()
                try:
                    status, detalhe, gamecode = await asyncio.wait_for(
                        classificar(page, jogo["url_jogo"], jogo.get("provedor", "")),
                        timeout=TIMEOUT_GLOBAL)
                except asyncio.TimeoutError:
                    status, detalhe, gamecode = "TIMEOUT", "Timeout global %ds" % TIMEOUT_GLOBAL, ""
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
                    "gamecode": gamecode,
                    "tempo_ms": ms,
                }
                resultados.append(row)
                writer.writerow(row)
                csv_f.flush()
                contador[0] += 1
                print("  [%d/%d] %-16s %-20s %s" % (
                    contador[0], total,
                    status, jogo.get("provedor", "")[:18],
                    jogo.get("nome", "")[:35]))

        await browser.close()

    cont = Counter(r["status"] for r in resultados)
    print("\n>> Recheck salvo em:", saida)
    print(">> RESUMO:", dict(cont))

    mesclar_no_principal(saida, arquivo_principal)
    print("\n>> Regenerando dashboard...")
    sys.path.insert(0, str(ROOT / "src"))
    import relatorio
    relatorio.gerar()


def rodar():
    asyncio.run(rodar_async())


if __name__ == "__main__":
    rodar()
