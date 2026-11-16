# -*- coding: utf-8 -*-
"""main.py - Orquestrador do monitor EstrelaBet (roda 1x/dia).
Uso:
  python main.py                 -> verifica jogos + gera relatorio
  python main.py --coletar       -> re-coleta a lista de jogos antes
  python main.py --login         -> forca novo login antes de tudo
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
SESSAO = ROOT / "data" / "sessao.json"
sys.path.insert(0, str(ROOT / "src"))
import login as m_login
import coletar_jogos as m_coletar
import check_jogos as m_check
import relatorio as m_rel


def main():
    args = sys.argv[1:]
    if "--login" in args or not SESSAO.exists():
        print("=== ETAPA 1: LOGIN ===")
        m_login.fazer_login()
    if "--coletar" in args:
        print("=== ETAPA 2: COLETAR JOGOS ===")
        m_coletar.coletar()
    print("=== ETAPA 3: VERIFICAR JOGOS ===")
    limite = 10 if "--teste" in args else None
    m_check.rodar(limite=limite)
    print("=== ETAPA 4: GERAR DASHBOARD ===")
    m_rel.gerar()
    print("\n>> Concluido! Abra dashboard/index.html no navegador.")


if __name__ == "__main__":
    main()
