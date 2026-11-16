# -*- coding: utf-8 -*-
"""vincular_live.py - Vincula os jogos da aba "100 Live" da planilha (public/)
aos jogos reais do site (data/jogos.csv), para descobrir a url_jogo de cada um.

Gera data/vinculo_100live.csv com: jogo (planilha), provider (planilha),
nome_site, provedor_site, url_jogo, score, status.

score < LIMIAR_REVISAO deve ser conferido manualmente antes de rodar a coleta.
"""
import csv
import difflib
import unicodedata
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
JOGOS_CSV = ROOT / "data" / "jogos.csv"
SAIDA = ROOT / "data" / "vinculo_100live.csv"

ABA = "Top Live"
LIMIAR_REVISAO = 0.85

# planilha usa nomes de provider diferentes dos do site
MAPA_PROVEDOR = {
    "playtech playtech": "playtech",
    "evolution": "evolution",
    "pragmaticplay": "pragmatic play",
    "creedroomz": "creedroomz",
    "pascalgaming": "pascal gaming",
}


def _norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.lower().strip()


def _achar_planilha():
    candidatos = list(PUBLIC.glob("*.xlsx"))
    if not candidatos:
        raise FileNotFoundError("Nenhuma planilha .xlsx encontrada em public/")
    if len(candidatos) > 1:
        raise FileNotFoundError(
            "Mais de uma planilha em public/: %s" % ", ".join(c.name for c in candidatos))
    return candidatos[0]


def carregar_linhas_planilha(caminho, aba=ABA):
    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb[aba]
    header = [c.value for c in ws[1]]
    linhas = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(header, row))
        if d.get("Jogo"):
            linhas.append(d)
    return linhas


def carregar_jogos_site():
    with open(JOGOS_CSV, encoding="utf-8-sig") as f:
        jogos = list(csv.DictReader(f))
    por_provedor = defaultdict(list)
    for j in jogos:
        por_provedor[_norm(j["provedor"])].append(j)
    return por_provedor


def vincular(linhas, por_provedor, mapa_provedor=MAPA_PROVEDOR):
    resultados = []
    for linha in linhas:
        jogo = linha["Jogo"]
        provider = linha["Provider"]
        prov_norm = mapa_provedor.get(_norm(provider), _norm(provider))
        candidatos = por_provedor.get(prov_norm, [])
        jn = _norm(jogo)

        melhor, melhor_score = None, 0.0
        for c in candidatos:
            score = difflib.SequenceMatcher(None, jn, _norm(c["nome"])).ratio()
            if score > melhor_score:
                melhor, melhor_score = c, score

        status = "OK" if melhor and melhor_score >= LIMIAR_REVISAO else "REVISAR"
        resultados.append({
            "jogo_planilha":     jogo,
            "provider_planilha": provider,
            "nome_site":         melhor["nome"] if melhor else "",
            "provedor_site":     melhor["provedor"] if melhor else "",
            "url_jogo":          melhor["url_jogo"] if melhor else "",
            "score":             round(melhor_score, 2),
            "status":            status,
        })
    return resultados


def rodar():
    caminho = _achar_planilha()
    print(">> Planilha:", caminho.name)
    linhas = carregar_linhas_planilha(caminho)
    print(">>", len(linhas), "jogos na aba", ABA)

    por_provedor = carregar_jogos_site()
    resultados = vincular(linhas, por_provedor)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(resultados[0].keys()))
        w.writeheader()
        w.writerows(resultados)

    revisar = [r for r in resultados if r["status"] == "REVISAR"]
    sem_match = [r for r in resultados if not r["url_jogo"]]
    print(">> %d vinculados, %d para revisar, %d sem nenhum candidato."
          % (len(resultados) - len(revisar), len(revisar), len(sem_match)))
    print(">> Salvo em", SAIDA)
    if revisar:
        print("\n>> Conferir manualmente:")
        for r in revisar:
            print("  [%.2f] %-40s (%s) -> %s" % (
                r["score"], r["jogo_planilha"], r["provider_planilha"], r["nome_site"] or "???"))


if __name__ == "__main__":
    rodar()
