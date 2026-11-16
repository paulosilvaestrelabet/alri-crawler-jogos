# -*- coding: utf-8 -*-
"""main_alri.py - Orquestrador do monitor Alri (alri.com).
Uso:
  python main_alri.py                 -> login + coleta pelas paginas dos provedores
                                         + verificacao + dashboard
  python main_alri.py --teste         -> idem, verificando so 10 jogos
  python main_alri.py --sem-login     -> reaproveita data/alri/sessao.json (so serve
                                         se nenhuma run usou a sessao: o refresh
                                         token e rotativo e fica invalido)
  python main_alri.py --sem-coleta    -> reaproveita data/alri/jogos.csv
O login e feito a cada run: a sessao da Alri expira apos 24h ociosa.
Credenciais: ALRI_EMAIL / ALRI_SENHA em config/.env (sem elas, login manual).
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "alri"))
import login as m_login
import coletar_jogos as m_coletar
import check_jogos as m_check
import relatorio as m_rel
import publicar_runs as m_pub

SESSAO = ROOT / "data" / "alri" / "sessao.json"
JOGOS  = ROOT / "data" / "alri" / "jogos.csv"

ERROS_REAIS = {"ERRO_ALEA", "ERRO_IFRAME", "ERRO_REDE", "NAO_CARREGOU", "ERRO_404",
               "ERRO_HTTP", "ERRO_LAUNCH", "BLOQUEADO", "KYC", "SESSAO_EXPIRADA"}
RECHECK     = {"SEM_LAUNCH", "TIMEOUT", "SITE_INACESSIVEL", "COMING_SOON",
               "INCONCLUSIVO"}
INFO_RECHECK = ("SEM_LAUNCH: a pagina nao chamou POST /api/v1/games/play nem o fallback "
                "via API respondeu. TIMEOUT/SITE_INACESSIVEL: rede lenta ou a pagina da "
                "Alri recusou a conexao (proxy/IP). INCONCLUSIVO: TraceId na Evolution, "
                "a conta de teste so abre ~2 mesas seguidas antes de ser bloqueada. "
                "COMING_SOON: jogo "
                "marcado como em breve na plataforma. ")


def main():
    args = sys.argv[1:]
    if "--sem-login" not in args or not SESSAO.exists():
        print("=== ETAPA 1: LOGIN ===")
        m_login.fazer_login()
    if "--sem-coleta" not in args or not JOGOS.exists():
        print("=== ETAPA 2: COLETAR JOGOS (paginas dos provedores) ===")
        m_coletar.coletar()
    print("=== ETAPA 3: VERIFICAR JOGOS ===")
    limite = 10 if "--teste" in args else None
    m_check.rodar(limite=limite)
    print("=== ETAPA 4: GERAR DASHBOARD ===")
    m_rel.gerar(res_dir=ROOT / "data" / "alri" / "resultados",
                dash=ROOT / "dashboard" / "alri.html",
                titulo="Alri",
                erros_reais=ERROS_REAIS, recheck_status=RECHECK,
                info_recheck=INFO_RECHECK)
    m_pub.gerar()   # dados do artefato Alri GameCheck (republicado pelo Claude)
    print("\n>> Concluido! Abra dashboard/alri.html no navegador.")


if __name__ == "__main__":
    main()
