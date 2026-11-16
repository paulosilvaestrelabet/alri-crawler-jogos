# -*- coding: utf-8 -*-
"""check_jogos.py (Alri) - Abre cada jogo e intercepta o launch da plataforma.

Launch da Alri (descoberto nos bundles do site):
  POST https://api.pam.alri.com/api/v1/games/play  body {game: <gameCode>, device}
  2xx -> {url: <launch url do provedor>, ...}
  erro -> ApiError {code, error, details: {reason}}

Classificacao:
  OK              launch 2xx + iframe do jogo presente e sem texto de erro
  ERRO_ALEA       iframe da Alea exibe "An error occurred ... TraceId" (ex: BGaming)
  ERRO_IFRAME     frame do provedor exibe erro (ex: Play'n GO "Something went wrong")
  ERRO_REDE       frame do provedor caiu em chrome-error:// (ex: Galaxsys,
                  dominio do jogo fecha a conexao)
  INCONCLUSIVO    ERRO_ALEA na Evolution: a conta de teste so abre ~2 mesas
                  seguidas e fica bloqueada; manualmente os jogos funcionam
  NAO_CARREGOU    launch 2xx mas nenhum iframe do jogo na pagina
  COMING_SOON     GAME_COMING_SOON (ou pagina mostra "coming soon")
  ERRO_404        GAME_NOT_FOUND / HTTP 404
  BLOQUEADO       FEATURE_BLOCKED / COUNTRY_NOT_ENABLED / HTTP 403
  KYC             KYC_* (conta de teste sem verificacao)
  SESSAO_EXPIRADA SESSION_* / HTTP 401 / redirecionou para /waitlist/
  ERRO_HTTP       launch HTTP 5xx
  ERRO_LAUNCH     outro erro 4xx do launch
  SEM_LAUNCH      /games/play nao foi chamado nem respondeu via API direta
  SITE_INACESSIVEL net::ERR_* ao abrir a pagina da Alri (ex: proxy/IP bloqueado)
  TIMEOUT         navegacao ou timeout global
"""
import os, csv, sys, time, json, asyncio, shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT   = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "config" / ".env")
API    = "https://api.pam.alri.com/api/v1"
SESSAO = ROOT / "data" / "alri" / "sessao.json"
JOGOS  = ROOT / "data" / "alri" / "jogos.csv"
HOJE   = datetime.now().strftime("%Y-%m-%d")
SAIDA  = ROOT / "data" / "alri" / "resultados" / ("resultado_" + HOJE + ".csv")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

TIMEOUT_NAV_MS           = 30000
ESPERA_LAUNCH_MS         = 20000   # tempo max aguardando POST /games/play
ESPERA_IFRAME_MS         = 20000   # tempo max ate o iframe do provedor ser inserido
ESPERA_JOGO_MS           = 8000    # depois do iframe, aguarda o conteudo carregar
ESPERA_JOGO_EXTENDIDA_MS = 14000
TIMEOUT_GLOBAL           = 90
N_ABAS   = int(os.getenv("ALRI_ABAS", "4"))
HEADLESS = os.getenv("ALRI_HEADLESS", "0") == "1"
LIMITE   = int(os.getenv("ALRI_LIMITE", "0")) or None

# apos N SESSAO_EXPIRADA/SITE_INACESSIVEL seguidas a run para
# (retomada continua de onde parou)
MAX_SESSAO_SEGUIDAS = 10
STATUS_ABORTA = {"SESSAO_EXPIRADA", "SITE_INACESSIVEL"}

PROVEDORES_ERRO_EXTENDIDO = {"pragmatic-play", "pragmatic-play-live", "evolution"}
# provedores que bloqueiam a conta apos poucos launches seguidos: verificados
# primeiro na run e com ERRO_ALEA reportado como INCONCLUSIVO
PROVEDORES_LIMITE_SESSAO = {"evolution"}

# texto de erro dentro do frame do provedor -> ERRO_IFRAME (TraceId -> ERRO_ALEA)
ERROS_IFRAME_UNIVERSAL = [
    "something went wrong",   # Play'n GO (ContainerLauncher)
    "an error occurred",
    "game error",
    "game is not available",
    "not available in your",
    "session expired",
    "ocorreu um erro",
]
# "restri" so nos provedores live: badge de audio gera falso positivo
ERROS_IFRAME_EXTENDIDO = ERROS_IFRAME_UNIVERSAL + ["restri"]
_AUDIO_KEYWORDS = ["audio", "som ", "sound", "microfon", "mute", "silenci"]

CODIGOS = {
    "GAME_NOT_FOUND":      "ERRO_404",
    "GAME_COMING_SOON":    "COMING_SOON",
    "FEATURE_BLOCKED":     "BLOQUEADO",
    "COUNTRY_NOT_ENABLED": "BLOQUEADO",
}


def _restri_eh_audio(text):
    idx = text.find("restri")
    if idx == -1:
        return False
    ctx = text[max(0, idx - 50): idx + 100]
    return any(kw in ctx for kw in _AUDIO_KEYWORDS)


def _launch_url(body):
    if not isinstance(body, dict):
        return ""
    d = body.get("data") if isinstance(body.get("data"), dict) else body
    return d.get("url") or ""


def _classificar_erro(http, body):
    """Mapeia resposta de erro do /games/play para (status, detalhe)."""
    body = body if isinstance(body, dict) else {}
    code = str(body.get("code") or "")
    det  = body.get("details") if isinstance(body.get("details"), dict) else {}
    msg  = body.get("error") or body.get("message") or ""
    detalhe = "HTTP %d %s %s %s" % (http, code, det.get("reason") or "", msg)
    detalhe = " ".join(detalhe.split())[:150]
    if code in CODIGOS:
        return CODIGOS[code], detalhe
    if code.startswith("SESSION_") or http == 401:
        return "SESSAO_EXPIRADA", detalhe
    if code.startswith("KYC_"):
        return "KYC", detalhe
    if http == 404:
        return "ERRO_404", detalhe
    if http == 403:
        return "BLOQUEADO", detalhe
    if http >= 500:
        return "ERRO_HTTP", detalhe
    return "ERRO_LAUNCH", detalhe


async def _launch_direto(page, game_code, api_headers):
    """Chama POST /games/play com o token do localStorage (fallback)."""
    if not game_code or "x-brand-id" not in api_headers:
        return None
    try:
        raw = await page.evaluate("() => localStorage.getItem('brand-auth-token')")
        token = json.loads(raw) if raw else None
    except Exception:
        token = None
    if not token:
        return None
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + token}
    headers.update({k: v for k, v in api_headers.items()})
    try:
        r = await page.context.request.post(
            API + "/games/play", data={"game": game_code, "device": "desktop"},
            headers=headers, timeout=15000)
        try:
            body = await r.json()
        except Exception:
            body = {}
        return r.status, body
    except Exception:
        return None


async def _verificar_iframe(page, slug_prov, launch_url):
    """Launch 2xx: confere se o iframe do jogo existe e nao mostra erro."""
    extended = slug_prov in PROVEDORES_ERRO_EXTENDIDO
    espera   = ESPERA_JOGO_EXTENDIDA_MS if extended else ESPERA_JOGO_MS
    padroes  = ERROS_IFRAME_EXTENDIDO if extended else ERROS_IFRAME_UNIVERSAL

    # o iframe pode demorar a ser inserido apos o launch: espera ele aparecer
    host = urlparse(launch_url).netloc
    try:
        await page.wait_for_selector("iframe[src*='%s']" % host,
                                     state="attached", timeout=ESPERA_IFRAME_MS)
    except Exception:
        if not any(f.url and host in f.url for f in page.frames):
            return ("NAO_CARREGOU", "Launch OK mas sem iframe de %s em %ds"
                    % (host, ESPERA_IFRAME_MS // 1000))
    await page.wait_for_timeout(espera)

    textos = []
    for frame in page.frames[1:]:
        try:
            fb = (await frame.inner_text("body", timeout=2000) or "").lower()
        except Exception:
            fb = ""
        # frame do provedor nao conectou: Chrome troca pela pagina de erro dele
        if frame.url.startswith("chrome-error://"):
            return "ERRO_REDE", ("Iframe do provedor nao conectou: "
                                 + " ".join(fb.split())[:110])
        textos.append(fb)

    # TraceId primeiro: e o marcador especifico da Alea
    for fb in textos:
        if "traceid:" in fb:
            return "ERRO_ALEA", "Erro Alea (TraceId)"
    for fb in textos:
        for padrao in padroes:
            if padrao in fb:
                if padrao == "restri" and _restri_eh_audio(fb):
                    continue
                return "ERRO_IFRAME", "Erro iframe (" + padrao + ")"
    return "OK", "Launch OK, iframe carregou"


async def classificar(page, jogo, api_headers):
    """Retorna (status, detalhe, launch_host, http_launch)."""
    launch = {}
    pronto = asyncio.Event()

    async def on_response(resp):
        if "/api/v1/games/play" in resp.url and resp.request.method == "POST":
            if pronto.is_set():
                return
            try:
                body = await resp.json()
            except Exception:
                body = {}
            # access token expirado: o site renova e repete o POST sozinho,
            # entao espera a proxima resposta em vez de registrar o 401
            if (resp.status == 401 and isinstance(body, dict)
                    and body.get("code") == "AUTH_TOKEN_EXPIRED"
                    and not launch.get("renovou")):
                launch["renovou"] = True
                return
            launch["status"] = resp.status
            launch["body"] = body
            pronto.set()

    page.on("response", on_response)
    try:
        try:
            try:
                r = await page.goto(jogo["url_jogo"], wait_until="domcontentloaded",
                                    timeout=TIMEOUT_NAV_MS)
            except Exception as e:
                # redirect residual do jogo anterior na mesma aba interrompe o
                # goto em ~1s; nao e falha do jogo, repete a navegacao uma vez
                if "interrupted by another navigation" not in str(e):
                    raise
                await page.wait_for_timeout(1500)
                r = await page.goto(jogo["url_jogo"], wait_until="domcontentloaded",
                                    timeout=TIMEOUT_NAV_MS)
        except Exception as e:
            err = str(e)
            if "ERR_ABORTED" in err:
                r = None
            elif "net::ERR_" in err:
                return "SITE_INACESSIVEL", err.split("\n")[0][:80], "", ""
            else:
                return "TIMEOUT", err[:80], "", ""
        if r is not None and r.status == 404:
            return "ERRO_404", "Pagina do jogo HTTP 404", "", ""
        if r is not None and r.status >= 500:
            return "ERRO_HTTP", "Pagina do jogo HTTP %d" % r.status, "", ""

        try:
            await asyncio.wait_for(pronto.wait(), timeout=ESPERA_LAUNCH_MS / 1000.0)
        except asyncio.TimeoutError:
            pass
    finally:
        page.remove_listener("response", on_response)

    # deslogado, o site manda para /waitlist/ ou /compendium/
    for gate in ("/waitlist", "/compendium"):
        if gate in page.url:
            return "SESSAO_EXPIRADA", "Redirecionou para %s/" % gate, "", ""

    if not pronto.is_set():
        try:
            body_txt = (await page.inner_text("body", timeout=3000) or "").lower()
        except Exception:
            body_txt = ""
        if "coming soon" in body_txt:
            return "COMING_SOON", "Pagina exibe 'coming soon' (sem launch)", "", ""
        direto = await _launch_direto(page, jogo.get("game_code", ""), api_headers)
        if direto is None:
            return ("SEM_LAUNCH", "/games/play nao chamado em %ds"
                    % (ESPERA_LAUNCH_MS // 1000), "", "")
        http, body = direto
        url = _launch_url(body)
        if 200 <= http < 300 and url:
            return ("OK", "Launch OK via API direta (iframe nao verificado)",
                    urlparse(url).netloc, http)
        st, det = _classificar_erro(http, body)
        return st, det + " [API direta]", "", http

    http = launch.get("status", 0)
    body = launch.get("body", {})
    url  = _launch_url(body)
    if 200 <= http < 300 and url:
        slug = jogo.get("slug_provedor", "")
        st, det = await _verificar_iframe(page, slug, url)
        # a conta de teste so abre ~2 mesas Evolution e depois fica bloqueada por
        # um tempo (sessoes antigas continuam abertas na Evolution); o TraceId
        # que vem a seguir nao indica jogo quebrado
        if slug in PROVEDORES_LIMITE_SESSAO and st == "ERRO_ALEA":
            st, det = "INCONCLUSIVO", ("TraceId Alea: limite de sessoes da conta "
                                       "na Evolution (launch OK)")
        return st, det, urlparse(url).netloc, http
    if 200 <= http < 300:
        return "ERRO_LAUNCH", "HTTP %d sem url: %s" % (http, str(body)[:100]), "", http
    st, det = _classificar_erro(http, body)
    return st, det, "", http


async def rodar_async(limite=None):
    if not JOGOS.exists():
        print("!! data/alri/jogos.csv nao existe. Rode a coleta antes.")
        return
    if not SESSAO.exists():
        print("!! data/alri/sessao.json nao existe. Rode o login antes.")
        return

    with open(JOGOS, encoding="utf-8-sig") as f:
        jogos = list(csv.DictReader(f))

    lim = limite or LIMITE
    if lim:
        jogos = jogos[:lim]
        print(">> MODO TESTE: limitado a %d jogos." % len(jogos))
    total = len(jogos)

    ja_feitos, modo, header = set(), "w", True
    if SAIDA.exists() and not lim:
        with open(SAIDA, encoding="utf-8-sig") as f:
            ja_feitos = {row["url_jogo"] for row in csv.DictReader(f)}
        if ja_feitos:
            print(">> Retomando: %d ja verificados, %d pendentes."
                  % (len(ja_feitos), total - len(ja_feitos)))
            modo, header = "a", False

    pendentes = [j for j in jogos if j["url_jogo"] not in ja_feitos]
    # Evolution primeiro, enquanto a conta ainda nao bateu o limite de sessoes
    pendentes.sort(key=lambda j: j.get("slug_provedor") not in PROVEDORES_LIMITE_SESSAO)
    if not pendentes:
        print(">> Todos os jogos ja foram verificados.")
        return SAIDA

    print(">> %d jogos para verificar | %d abas | headless=%s"
          % (len(pendentes), N_ABAS, HEADLESS))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["data", "provedor", "nome", "game_code", "url_jogo", "status",
                  "detalhe", "launch_host", "http_launch", "tempo_ms"]
    resultados  = []
    lock_csv    = asyncio.Lock()
    contador    = [len(ja_feitos)]
    sessao_seq  = [0]
    abortar     = asyncio.Event()
    api_headers = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS,
                                          args=["--start-maximized"])
        ctx = await browser.new_context(storage_state=str(SESSAO), locale="en-US",
                                        user_agent=UA)

        # guarda X-Brand-Id / X-Device-Id que o proprio site envia (p/ fallback)
        def on_request(req):
            if "api.pam.alri.com" in req.url and "x-brand-id" not in api_headers:
                h = req.headers
                if "x-brand-id" in h:
                    api_headers["x-brand-id"] = h["x-brand-id"]
                    if "x-device-id" in h:
                        api_headers["x-device-id"] = h["x-device-id"]
        ctx.on("request", on_request)

        pages = [await ctx.new_page() for _ in range(N_ABAS)]
        pool = asyncio.Queue()
        for pg in pages:
            await pool.put(pg)

        with open(SAIDA, modo, newline="", encoding="utf-8-sig") as csv_f:
            writer = csv.DictWriter(csv_f, fieldnames=fieldnames)
            if header:
                writer.writeheader()
                csv_f.flush()

            async def tarefa(jogo):
                if abortar.is_set():
                    return None
                page = await pool.get()
                try:
                    if abortar.is_set():
                        return None
                    t0 = time.time()
                    try:
                        status, detalhe, host, http = await asyncio.wait_for(
                            classificar(page, jogo, api_headers),
                            timeout=TIMEOUT_GLOBAL)
                    except asyncio.TimeoutError:
                        status, detalhe, host, http = (
                            "TIMEOUT", "Timeout global %ds" % TIMEOUT_GLOBAL, "", "")
                    # descarrega o jogo (para audio/sockets do provedor)
                    try:
                        await page.goto("about:blank", timeout=5000)
                    except Exception:
                        pass
                    row = {
                        "data":        HOJE,
                        "provedor":    jogo.get("provedor", ""),
                        "nome":        jogo.get("nome", ""),
                        "game_code":   jogo.get("game_code", ""),
                        "url_jogo":    jogo["url_jogo"],
                        "status":      status,
                        "detalhe":     detalhe,
                        "launch_host": host,
                        "http_launch": http,
                        "tempo_ms":    int((time.time() - t0) * 1000),
                    }
                    async with lock_csv:
                        sessao_seq[0] = sessao_seq[0] + 1 if status in STATUS_ABORTA else 0
                        if sessao_seq[0] >= MAX_SESSAO_SEGUIDAS and not abortar.is_set():
                            abortar.set()
                            print("!! %d %s seguidas: sessao caiu ou site bloqueou o "
                                  "acesso. Parando; refaca o login e rode de novo "
                                  "(retoma de onde parou)." % (sessao_seq[0], status))
                        if abortar.is_set() and status in STATUS_ABORTA:
                            return None   # nao grava: sera refeito na retomada
                        resultados.append(row)
                        writer.writerow(row)
                        csv_f.flush()
                        contador[0] += 1
                        print("  [%d/%d] %-15s %-16s %s"
                              % (contador[0], total, status,
                                 jogo.get("provedor", "")[:16],
                                 jogo.get("nome", "")[:40]))
                    return row
                finally:
                    await pool.put(page)

            await asyncio.gather(*[tarefa(j) for j in pendentes])

        await browser.close()

    from collections import Counter
    print("\n>> Resultado salvo em", SAIDA)
    print(">> RESUMO:", dict(Counter(r["status"] for r in resultados)))

    bkp_dir = SAIDA.parent / "backups"
    bkp_dir.mkdir(parents=True, exist_ok=True)
    bkp = bkp_dir / (SAIDA.stem + "_bkp_" + datetime.now().strftime("%H%M%S") + SAIDA.suffix)
    shutil.copy2(SAIDA, bkp)
    print(">> Backup salvo em", bkp)
    if abortar.is_set():
        raise SystemExit(2)
    return SAIDA


def rodar(limite=None):
    return asyncio.run(rodar_async(limite=limite))


if __name__ == "__main__":
    rodar()
