# -*- coding: utf-8 -*-
"""check_jogos.py - Verifica cada jogo interceptando a chamada BFF /launch/game.
Classifica: OK / DEMO_ONLY / SEM_LAUNCH / SESSAO_EXPIRADA / ERRO_404 / ERRO_HTTP / TIMEOUT / ERRO_API.

Logica:
  data.real  presente -> OK         (sessao autenticada, jogo real disponivel)
  data.free  presente -> DEMO_ONLY  (deslogado ou jogo so tem demo)
  API nao chamada     -> SEM_LAUNCH (provider usa outro sistema, ex: Evolution)
  Outros erros        -> ERRO_*
"""
import os, csv, sys, time, asyncio, shutil
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
JOGOS  = ROOT / "data" / "jogos.csv"
HOJE   = datetime.now().strftime("%Y-%m-%d")
SAIDA  = ROOT / "data" / "resultados" / ("resultado_" + HOJE + ".csv")

TIMEOUT_NAV_MS          = 20000   # timeout de navegacao (ms)
ESPERA_LAUNCH_MS        = 18000   # tempo max aguardando BFF /launch/game responder (ms)
ESPERA_JOGO_MS          = 6000    # aguarda jogo carregar antes de checar erros
ESPERA_JOGO_EXTENDIDA_MS = 14000  # aguarda mais para providers com erros em iframe
N_ABAS                  = 8       # abas paralelas

# LIMITE: quantos jogos verificar (0 = todos). Override via env EB_LIMITE=10
LIMITE = int(os.getenv("EB_LIMITE", "0")) or None

# sem exclusoes: todos os provedores incluidos
PROVEDORES_IGNORAR: set = set()

# Providers que ocasionalmente retornam data.real mas exibem erro dentro do iframe
PROVEDORES_ERRO_EXTENDIDO = {"Pragmatic Play", "Evolution", "Playtech", "Games Global"}

# Padroes de erro no iframe (sem acento; busca em texto lowercased do iframe)
ERROS_IFRAME_UNIVERSAL = ["traceid:"]
ERROS_IFRAME_EXTENDIDO = [
    "traceid:",             # Alea: marcador universal de erro no servidor
    "reinicie o jogo",      # Playtech: "Ocorreu um erro. Reinicie o jogo"
    "ocorreu um erro",      # generico PT (frase longa, segura)
    "an error occurred",    # generico EN (frase longa, segura)
    "game error",           # generico EN
    "restri",               # geo-restricao (audio filtrado por _restri_eh_audio)
    "not available in your",# EN: "not available in your country/region"
]

# Palavras que, quando aparecem perto de "restri", indicam restricao de AUDIO
# (jogo funcional) -- nao devem ser classificadas como INDISPONIVEL
_AUDIO_KEYWORDS = ["audio", "som ", "sound", "microfon", "mute", "silenci"]


def _restri_eh_audio(text):
    """Retorna True se 'restri' no texto indica restricao de audio (jogo OK).

    PP live tables exibem icone/badge de 'restricao de audio' enquanto o jogo
    esta ativo. Geo-restricoes aparecem sem contexto de audio.
    """
    idx = text.find("restri")
    if idx == -1:
        return False
    ctx = text[max(0, idx - 50): idx + 100]
    return any(kw in ctx for kw in _AUDIO_KEYWORDS)


def _gamecode(data_real):
    """Extrai game_code de data.real.gameDetails."""
    try:
        gd = data_real.get("gameDetails", {})
        return gd.get("game_code") or gd.get("gameCode") or ""
    except Exception:
        return ""


async def classificar(page, url_jogo, provedor=""):
    """Navega para o jogo e intercepta a chamada BFF /launch/game.
    Retorna (status, detalhe, gamecode)."""
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
    r          = None
    nav_aborted = False
    try:
        r = await page.goto(url_jogo, wait_until="domcontentloaded",
                            timeout=TIMEOUT_NAV_MS)
    except Exception as e:
        err_str = str(e)
        if "ERR_ABORTED" in err_str:
            # SPA redireciona a navegacao; listener continua ativo para capturar BFF
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

    # aguarda a chamada ao BFF /launch/game
    bff_timeout = ESPERA_LAUNCH_MS / 1000.0
    try:
        await asyncio.wait_for(launch_ready.wait(), timeout=bff_timeout)
    except asyncio.TimeoutError:
        page.remove_listener("response", on_response)
        if nav_aborted:
            # Navegacao abortou e BFF nao respondeu: tenta chamada direta ao BFF
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
        # fallback normal: verifica texto de login na pagina
        try:
            body_txt = (await page.inner_text("body", timeout=3000) or "").lower()
            if any(t in body_txt for t in ["faca login", "entre na sua conta",
                                           "sessao expirada"]):
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
        gc = _gamecode(data["real"])
        extended = provedor in PROVEDORES_ERRO_EXTENDIDO
        espera   = ESPERA_JOGO_EXTENDIDA_MS if extended else ESPERA_JOGO_MS
        padroes  = ERROS_IFRAME_EXTENDIDO   if extended else ERROS_IFRAME_UNIVERSAL

        await page.wait_for_timeout(espera)

        # verifica todos os frames (extended) ou os primeiros 10
        frames_alvo = page.frames if extended else page.frames[:10]
        for frame in frames_alvo:
            try:
                fb = (await frame.inner_text("body", timeout=2000) or "").lower()
                for padrao in padroes:
                    if padrao in fb:
                        if padrao == "restri" and _restri_eh_audio(fb):
                            continue  # badge de audio: jogo funcional
                        return "INDISPONIVEL", "Erro iframe (" + padrao + ")", gc
            except Exception:
                continue

        # para providers especificos verifica tambem o body principal
        # (Playtech mostra modal de erro sobre o iframe)
        if extended:
            try:
                body_main = (await page.inner_text("body", timeout=3000) or "").lower()
                for padrao in padroes:
                    if padrao in body_main:
                        if padrao == "restri" and _restri_eh_audio(body_main):
                            continue  # badge de audio: jogo funcional
                        return "INDISPONIVEL", "Erro pagina (" + padrao + ")", gc
            except Exception:
                pass

        return "OK", "Logado (data.real)", gc

    if "free" in data:
        return "DEMO_ONLY", "Deslogado (data.free)", ""

    # data: {} quando logado pode ser conflito de sessao concorrente (8 abas)
    # retry imediato via chamada direta ao BFF sem re-navegar a pagina
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
                    return "OK", "Logado (data.real via retry)", _gamecode(retry_data["real"])
                if "free" in retry_data:
                    return "DEMO_ONLY", "Deslogado (data.free via retry)", ""
        except Exception:
            pass
        return "SEM_DEMO", "BFF retornou data vazio mesmo com retry", ""

    # resposta 2xx mas sem real nem free
    msg_body = str(resp_body).lower()
    if any(t in msg_body for t in ["session", "login", "unauthorized"]):
        return "SESSAO_EXPIRADA", str(resp_body)[:120], ""

    return "ERRO_API", "Resp inesperada: " + str(resp_body)[:100], ""


async def rodar_async(limite=None):
    if not JOGOS.exists():
        print("!! data/jogos.csv nao existe. Rode coletar_jogos.py antes.")
        return

    with open(JOGOS, encoding="utf-8-sig") as f:
        jogos = list(csv.DictReader(f))
    total_geral = len(jogos)

    # aplica limite global (env EB_LIMITE ou parametro)
    lim = limite or LIMITE
    if lim:
        jogos = jogos[:lim]
        total_geral = len(jogos)
        print(">> MODO TESTE: limitado a %d jogos." % total_geral)

    # retomada: pula URLs ja processadas no CSV parcial de hoje
    ja_feitos       = set()
    modo_arquivo    = "w"
    escrever_header = True
    if SAIDA.exists() and not lim:
        with open(SAIDA, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ja_feitos.add(row["url_jogo"])
        if ja_feitos:
            print(">> Retomando: %d ja verificados, %d pendentes."
                  % (len(ja_feitos), total_geral - len(ja_feitos)))
            modo_arquivo    = "a"
            escrever_header = False

    ignorados = [j for j in jogos
                 if j.get("provedor", "") in PROVEDORES_IGNORAR
                 and j["url_jogo"] not in ja_feitos]
    if ignorados:
        provedores_ign = sorted({j["provedor"] for j in ignorados})
        print(">> Ignorando %d jogos de: %s"
              % (len(ignorados), ", ".join(provedores_ign)))

    jogos_pendentes = [j for j in jogos
                       if j["url_jogo"] not in ja_feitos
                       and j.get("provedor", "") not in PROVEDORES_IGNORAR]
    total_pendente  = len(jogos_pendentes)
    if not total_pendente:
        print(">> Todos os jogos ja foram verificados.")
        return

    print(">> %d jogos para verificar | %d abas | headless=False"
          % (total_pendente, N_ABAS))
    print(">> Provedores ignorados:", ", ".join(sorted(PROVEDORES_IGNORAR)))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["data", "provedor", "nome", "url_jogo",
                  "status", "detalhe", "gamecode", "tempo_ms"]

    resultados = []
    lock_csv   = asyncio.Lock()
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
        pages = [await ctx.new_page() for _ in range(N_ABAS)]

        pool = asyncio.Queue()
        for pg in pages:
            await pool.put(pg)

        with open(SAIDA, modo_arquivo, newline="", encoding="utf-8-sig") as csv_f:
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            if escrever_header:
                writer.writeheader()
                csv_f.flush()

            async def tarefa(jogo):
                page = await pool.get()
                try:
                    t0 = time.time()
                    try:
                        status, detalhe, gamecode = await asyncio.wait_for(
                            classificar(page, jogo["url_jogo"],
                                        jogo.get("provedor", "")), timeout=65)
                    except asyncio.TimeoutError:
                        status, detalhe, gamecode = "TIMEOUT", "Timeout global 65s", ""
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
                    async with lock_csv:
                        resultados.append(row)
                        writer.writerow(row)
                        csv_f.flush()
                        contador[0] += 1
                        print("  [%d/%d] %-16s %-12s %s"
                              % (contador[0], total_geral,
                                 status,
                                 jogo.get("provedor", "")[:12],
                                 jogo.get("nome", "")[:40]))
                    return row
                finally:
                    await pool.put(page)

            await asyncio.gather(*[tarefa(j) for j in jogos_pendentes])

        await browser.close()

    from collections import Counter
    cont = Counter(r["status"] for r in resultados)
    print("\n>> Resultado salvo em", SAIDA)
    print(">> RESUMO:", dict(cont))

    # backup automatico pos-run para evitar perda de dados
    bkp_dir = SAIDA.parent / "backups"
    bkp_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    bkp = bkp_dir / (SAIDA.stem + "_bkp_" + ts + SAIDA.suffix)
    shutil.copy2(SAIDA, bkp)
    print(">> Backup salvo em", bkp)

    return SAIDA


def rodar(limite=None):
    asyncio.run(rodar_async(limite=limite))


if __name__ == "__main__":
    rodar()
