# -*- coding: utf-8 -*-
"""login.py (Alri) - Faz login na Alri e salva a sessao em data/alri/sessao.json.
Fluxo: /login/ -> #login-identifier + #login-password -> submit.
Sucesso = POST api.pam.alri.com/api/v1/auth/login 2xx e token gravado no
localStorage (brand-auth-token). Sem ALRI_EMAIL/ALRI_SENHA no .env, ou se o
preenchimento falhar, espera ate 180s pelo login MANUAL na janela aberta.
A sessao expira apos 24h ociosa (config auth.idleTimeoutSecs), por isso o
main_alri.py faz login a cada run."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

ROOT   = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "config" / ".env")
EMAIL  = os.getenv("ALRI_EMAIL")
SENHA  = os.getenv("ALRI_SENHA")
BASE   = os.getenv("ALRI_BASE", "https://alri.com")
SESSAO = ROOT / "data" / "alri" / "sessao.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TOKEN_KEY       = "brand-auth-token"
ESPERA_MANUAL_S = 180


def _tem_token(page):
    try:
        return bool(page.evaluate("k => localStorage.getItem(k)", TOKEN_KEY))
    except Exception:
        return False


def _aguardar_token(page, segundos):
    for _ in range(segundos):
        if _tem_token(page):
            return True
        page.wait_for_timeout(1000)
    return False


def _casino_liberado(page):
    """Logado, /casino/ nao deve redirecionar para /waitlist/."""
    page.goto(BASE + "/casino/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    return "/waitlist" not in page.url


def fazer_login():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = browser.new_context(locale="en-US", viewport=None, user_agent=UA)
        page = ctx.new_page()

        print(">> Abrindo a pagina de login...")
        page.goto(BASE + "/login/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # banner de cookies cobre o formulario
        try:
            btn = page.locator("button:has-text('Accept cookies')").first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
        except Exception:
            pass

        automatico = False
        if EMAIL and SENHA:
            try:
                inp = page.locator("#login-identifier").first
                try:
                    inp.wait_for(state="visible", timeout=15000)
                except Exception:
                    # formulario as vezes nao renderiza na primeira carga
                    print(">> Formulario nao apareceu, recarregando /login/ ...")
                    page.goto(BASE + "/login/", wait_until="networkidle", timeout=60000)
                    inp.wait_for(state="visible", timeout=20000)
                inp.fill(EMAIL)
                page.locator("#login-password").first.fill(SENHA)
                with page.expect_response(
                        lambda r: "/api/v1/auth/login" in r.url
                        and r.request.method == "POST",
                        timeout=30000) as resp_info:
                    page.locator("button[type='submit']:has-text('Log in')").last.click()
                resp = resp_info.value
                print(">> POST /auth/login ->", resp.status)
                if resp.status >= 400:
                    try:
                        print("!! Resposta:", resp.text()[:200])
                    except Exception:
                        pass
                automatico = resp.ok
            except Exception as e:
                print("!! Falha no login automatico:", str(e)[:100])
        else:
            print("!! ALRI_EMAIL/ALRI_SENHA nao definidos em config/.env.")

        if automatico:
            ok = _aguardar_token(page, 15)
        else:
            print("!! Faca login MANUAL na janela. Aguardando ate %ds..."
                  % ESPERA_MANUAL_S)
            ok = _aguardar_token(page, ESPERA_MANUAL_S)

        if not ok:
            print("!! Token nao encontrado no localStorage. Login NAO confirmado.")
            browser.close()
            raise SystemExit(1)

        print(">> Token OK. Conferindo acesso ao cassino...")
        if not _casino_liberado(page):
            print("!! Logado, mas /casino/ redireciona para /waitlist/.")
            print("!! A conta nao tem acesso ao cassino (site em pre-lancamento?).")

        SESSAO.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(SESSAO))
        print(">> Sessao salva em:", SESSAO)
        browser.close()


if __name__ == "__main__":
    fazer_login()
