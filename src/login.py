# -*- coding: utf-8 -*-
"""login.py - Faz login na EstrelaBet e salva a sessao autenticada em data/sessao.json.
Fluxo atual do site: botao 'Entrar' -> navega para /login -> preenche CPF/email + senha.
Detecta sucesso aguardando saida da URL /login. Fallback: 120s manual."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

ROOT  = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "config" / ".env")
EMAIL  = os.getenv("EB_EMAIL")
SENHA  = os.getenv("EB_SENHA")
BASE   = os.getenv("EB_BASE", "https://www.estrelabet.bet.br")
SESSAO = ROOT / "data" / "sessao.json"


def _salvar(ctx, page):
    print(">> URL atual:", page.url[:120])
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    ctx.storage_state(path=str(SESSAO))
    print(">> Sessao salva em:", SESSAO)


def fazer_login():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        ctx = browser.new_context(
            locale="pt-BR", viewport=None,
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0 Safari/537.36"))
        page = ctx.new_page()

        print(">> Abrindo o site...")
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # --- tenta clicar em Entrar ---
        clicou = False
        for sel in ["text=Entrar", "button:has-text('Entrar')",
                    "[data-testid*='login']", "a:has-text('Entrar')"]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    clicou = True
                    print(">> Cliquei em 'Entrar':", sel)
                    break
            except Exception:
                continue

        if not clicou:
            print("!! Botao 'Entrar' nao encontrado.")
            print("!! Faca login MANUAL. Aguardando 120s...")
            try:
                page.wait_for_timeout(120000)
            except Exception:
                pass
            _salvar(ctx, page)
            browser.close()
            return

        # aguarda navegacao para pagina /login (o site usa pagina dedicada)
        try:
            page.wait_for_url("**/login**", timeout=10000)
            print(">> Pagina de login carregada:", page.url[:80])
        except PWTimeout:
            print(">> URL nao mudou para /login, continuando na pagina atual...")

        page.wait_for_timeout(2000)

        # --- preenche email/CPF ---
        sel_email = ("input[type='email'], input[name='email'], "
                     "input[name='document'], input[name='cpf'], "
                     "input[placeholder*='CPF'], input[placeholder*='mail'], "
                     "input[placeholder*='E-mail'], input[placeholder*='Usuario']")
        try:
            inp = page.locator(sel_email).first
            inp.wait_for(state="visible", timeout=10000)
            inp.click()
            inp.fill(EMAIL)
            print(">> Email/CPF preenchido.")
        except Exception as e:
            print("!! Falha ao preencher email/CPF:", str(e)[:80])
            print("!! Faca login MANUAL. Aguardando 120s...")
            try:
                page.wait_for_timeout(120000)
            except Exception:
                pass
            _salvar(ctx, page)
            browser.close()
            return

        page.wait_for_timeout(500)

        # --- preenche senha ---
        sel_senha = ("input[type='password'], input[name='password'], "
                     "input[placeholder*='enha'], input[placeholder*='Senha']")
        try:
            inp_s = page.locator(sel_senha).first
            inp_s.wait_for(state="visible", timeout=10000)
            inp_s.click()
            inp_s.fill(SENHA)
            print(">> Senha preenchida.")
        except Exception as e:
            print("!! Falha ao preencher senha:", str(e)[:80])
            print("!! Faca login MANUAL. Aguardando 120s...")
            try:
                page.wait_for_timeout(120000)
            except Exception:
                pass
            _salvar(ctx, page)
            browser.close()
            return

        page.wait_for_timeout(500)

        # --- clica em submit ---
        submeteu = False
        for sub in ["button[type='submit']", "button:has-text('Entrar')",
                    "button:has-text('Login')", "button:has-text('Acessar')"]:
            try:
                b = page.locator(sub).last
                if b.count() > 0 and b.is_visible():
                    b.click()
                    submeteu = True
                    print(">> Submit clicado:", sub)
                    break
            except Exception:
                continue

        if not submeteu:
            print("!! Botao submit nao encontrado - tentando Enter...")
            try:
                page.keyboard.press("Enter")
                submeteu = True
            except Exception:
                pass

        print(">> Aguardando redirecionamento apos login (max 30s)...")

        # sucesso = URL sai de /login
        try:
            page.wait_for_url(
                lambda url: "/login" not in url,
                timeout=30000)
            print(">> Login confirmado! URL:", page.url[:80])
        except PWTimeout:
            print("!! Nao saiu da pagina /login em 30s.")
            print("!! Verifique a janela. Aguardando mais 90s para login manual...")
            try:
                page.wait_for_timeout(90000)
            except Exception:
                pass

        _salvar(ctx, page)
        browser.close()


if __name__ == "__main__":
    fazer_login()
