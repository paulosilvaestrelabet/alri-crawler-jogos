# -*- coding: utf-8 -*-
"""preencher_planilha.py - Escreve os valores coletados de bet minima/maxima
(data/resultados/bets_*.csv) nas colunas "Min Bet BRL"/"Max Bet BRL" da aba
"100 Live" da planilha em public/, casando pelas colunas Jogo+Provider.

So preenche linhas com status OK; as demais ficam como estavam (em branco)
para checagem manual.
"""
import csv
import glob
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
RESULTADOS = ROOT / "data" / "resultados"
ABA = "Top Live"

COL_MIN = "Min Bet BRL"
COL_MAX = "Max Bet BRL"


def _achar_planilha():
    candidatos = list(PUBLIC.glob("*.xlsx"))
    if len(candidatos) != 1:
        raise FileNotFoundError("Esperava 1 planilha .xlsx em public/, achou %d" % len(candidatos))
    return candidatos[0]


def carregar_resultados(padrao="bets_*.csv"):
    """Le os bets_*.csv que casam com o padrao e monta
    {(jogo_planilha, provider_planilha): (min, max)}."""
    por_chave = {}
    arquivos = sorted(glob.glob(str(RESULTADOS / padrao)))
    for arq in arquivos:
        with open(arq, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["status"] != "OK":
                    continue
                chave = (row["jogo_planilha"], row["provider_planilha"])
                por_chave[chave] = (float(row["min_bet_brl"]), float(row["max_bet_brl"]))
    return por_chave


def preencher(aba=ABA, padrao="bets_*.csv"):
    caminho = _achar_planilha()
    por_chave = carregar_resultados(padrao)
    print(">> %d resultados OK carregados de %s" % (len(por_chave), padrao))

    wb = openpyxl.load_workbook(caminho)
    ws = wb[aba]
    header = [c.value for c in ws[1]]
    col_jogo = header.index("Jogo") + 1
    col_provider = header.index("Provider") + 1
    col_min = header.index(COL_MIN) + 1
    col_max = header.index(COL_MAX) + 1

    preenchidas, sem_resultado = 0, []
    for row_idx in range(2, ws.max_row + 1):
        jogo = ws.cell(row=row_idx, column=col_jogo).value
        if not jogo:
            continue
        provider = ws.cell(row=row_idx, column=col_provider).value
        chave = (jogo, provider)
        if chave in por_chave:
            min_bet, max_bet = por_chave[chave]
            ws.cell(row=row_idx, column=col_min).value = min_bet
            ws.cell(row=row_idx, column=col_max).value = max_bet
            preenchidas += 1
        else:
            sem_resultado.append(jogo)

    wb.save(caminho)
    print(">> %d linhas preenchidas em '%s'" % (preenchidas, caminho.name))
    if sem_resultado:
        print(">> %d linhas sem resultado (ficaram em branco p/ checagem manual):" % len(sem_resultado))
        for j in sem_resultado:
            print("  -", j)


if __name__ == "__main__":
    preencher()
